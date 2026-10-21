"""Port of src/lib/github/client.test.ts."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from bis_core.github.client import (
    GitHubApiError,
    GitHubClient,
    GitHubConfig,
    GitHubConfigError,
    get_github_config,
    split_repo,
)

API = "https://api.github.com"


def resp(body: Any, headers: dict[str, str] | None = None, status: int = 200) -> httpx.Response:
    return httpx.Response(status, content=json.dumps(body).encode(), headers={"content-type": "application/json", **(headers or {})})


def mock_transport(routes: dict[str, httpx.Response | Callable[[], httpx.Response]]) -> tuple[httpx.MockTransport, list[httpx.Request]]:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        r = routes.get(str(request.url))
        if r is None:
            return resp({"message": f"no route {request.url}"}, status=404)
        return r() if callable(r) else r

    return httpx.MockTransport(handler), calls


def pull(number: int, updated: str, body: str | None = None) -> dict[str, Any]:
    return {
        "number": number,
        "title": f"PR {number}",
        "state": "open",
        "body": body,
        "html_url": f"https://github.com/acme-labs/atlas/pull/{number}",
        "created_at": "2026-10-01T00:00:00Z",
        "updated_at": updated,
        "merged_at": None,
        "head": {"ref": f"feat/{number}-x"},
    }


class TestConfig:
    def test_requires_github_token(self) -> None:
        with pytest.raises(GitHubConfigError):
            get_github_config({})
        assert get_github_config({"GITHUB_TOKEN": "t"}) == GitHubConfig(token="t", api_base=API)

    def test_validates_repo_slugs(self) -> None:
        assert split_repo("acme-labs/atlas") == ("acme-labs", "atlas")
        with pytest.raises(ValueError):
            split_repo("atlas")
        with pytest.raises(ValueError):
            split_repo("a/b/c")


class TestGitHubClient:
    def test_paginates_issues_via_link_and_drops_prs(self) -> None:
        page2 = f"{API}/repositories/1/issues?page=2"
        transport, calls = mock_transport(
            {
                f"{API}/repos/acme-labs/atlas/issues?state=all&per_page=100&since=2026-10-01T00%3A00%3A00.000Z": resp(
                    [
                        {"number": 1, "title": "a", "state": "open", "html_url": "u1", "created_at": "c", "closed_at": None},
                        {"number": 2, "title": "pr", "state": "open", "html_url": "u2", "created_at": "c", "closed_at": None, "pull_request": {"url": "x"}},
                    ],
                    {"link": f'<{page2}>; rel="next"'},
                ),
                page2: resp([{"number": 3, "title": "c", "state": "closed", "html_url": "u3", "created_at": "c", "closed_at": "d"}]),
            }
        )
        gh = GitHubClient(GitHubConfig(token="ghp_secret", api_base=API), transport=transport)
        issues = gh.list_issues("acme-labs/atlas", "2026-10-01T00:00:00.000Z")
        assert [i.number for i in issues] == [1, 3]
        assert calls[0].headers["authorization"] == "Bearer ghp_secret"

    def test_fetch_repo_stops_at_prs_older_than_since_and_attaches_commits(self) -> None:
        transport, calls = mock_transport(
            {
                f"{API}/repos/acme-labs/atlas/issues?state=all&per_page=100&since=2026-10-05T00%3A00%3A00Z": resp([]),
                f"{API}/repos/acme-labs/atlas/pulls?state=all&sort=updated&direction=desc&per_page=100": resp(
                    [pull(10, "2026-10-06T00:00:00Z", "closes #4"), pull(9, "2026-10-01T00:00:00Z")],
                    {"link": f'<{API}/never-fetched>; rel="next"'},
                ),
                f"{API}/repos/acme-labs/atlas/pulls/10/commits?per_page=100": resp([{"sha": "s1"}, {"sha": "s2"}]),
            }
        )
        gh = GitHubClient(GitHubConfig(token="t", api_base=API), transport=transport)
        snap = gh.fetch_repo("acme-labs/atlas", since="2026-10-05T00:00:00Z")
        assert snap.issues == []
        assert len(snap.pull_requests) == 1
        pr = snap.pull_requests[0]
        assert (pr.number, pr.linked_issues, pr.commit_shas, pr.head_branch) == (10, [4], ["s1", "s2"], "feat/10-x")
        assert len(calls) == 3

    def test_raises_github_api_error_with_rate_limit_context_and_no_token(self) -> None:
        transport, _ = mock_transport(
            {
                f"{API}/repos/a/b/pulls/1/commits?per_page=100": resp(
                    {"message": "API rate limit exceeded"},
                    {"x-ratelimit-remaining": "0", "x-ratelimit-reset": "1792000000"},
                    403,
                )
            }
        )
        gh = GitHubClient(GitHubConfig(token="ghp_secret", api_base=API), transport=transport)
        with pytest.raises(GitHubApiError) as info:
            gh.list_pull_commit_shas("a/b", 1)
        assert info.value.status == 403
        assert "HTTP 403 (rate limited until 2026-10-14T" in str(info.value)
        assert "ghp_secret" not in str(info.value)
