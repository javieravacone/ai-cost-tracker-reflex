"""GitHub REST v3 client (read-only), port of ai-cost-tracker src/lib/github/client.ts.

Token: fine-grained PAT with Issues + Pull requests + Contents (metadata) read access. Endpoints:
- GET /repos/{o}/{r}/issues?state=all[&since=]      (items with `pull_request` are PRs: skipped)
- GET /repos/{o}/{r}/pulls?state=all&sort=updated&direction=desc
- GET /repos/{o}/{r}/pulls/{n}/commits              (GitHub caps this list at 250 commits)
Pagination via the `Link` header (rel="next"), per_page=100.
"""

from __future__ import annotations

import os
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlencode, urlsplit

import httpx

from bis_core.github.parse import GhPull, map_issue, map_pull_request, parse_next_link
from bis_core.types import Issue, PullRequest

_TIMEOUT = httpx.Timeout(60.0, connect=30.0)


@dataclass
class GitHubConfig:
    token: str
    api_base: str


class GitHubConfigError(Exception):
    pass


class GitHubApiError(Exception):
    def __init__(self, message: str, status: int) -> None:
        super().__init__(message)
        self.status = status


def get_github_config(env: Mapping[str, str | None] | None = None) -> GitHubConfig:
    env = os.environ if env is None else env
    token = (env.get("GITHUB_TOKEN") or "").strip()
    if not token:
        raise GitHubConfigError(
            "GITHUB_TOKEN is not set. Create a fine-grained read-only token and add it to .env.local "
            "(see .env.example)."
        )
    api_base = ((env.get("GITHUB_API_URL") or "").strip() or "https://api.github.com").rstrip("/")
    return GitHubConfig(token=token, api_base=api_base)


def split_repo(slug: str) -> tuple[str, str]:
    parts = slug.split("/")
    owner = parts[0] if parts else ""
    name = parts[1] if len(parts) > 1 else ""
    if not owner or not name or len(parts) > 2:
        raise ValueError(f'Invalid repo slug "{slug}", expected "owner/name"')
    return owner, name


@dataclass
class RepoSnapshot:
    issues: list[Issue] = field(default_factory=list)
    pull_requests: list[PullRequest] = field(default_factory=list)


def _parse_ms(ts: str | None) -> float:
    """`Date.parse`: epoch milliseconds, NaN when unparsable (NaN never compares true)."""
    if not ts:
        return float("nan")
    try:
        d = datetime.fromisoformat(ts)
    except ValueError:
        return float("nan")
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.timestamp() * 1000


def _rate_reset_iso(reset: str | None) -> str:
    try:
        seconds = float(reset or 0)
    except ValueError:
        seconds = 0.0
    d = datetime.fromtimestamp(seconds, tz=timezone.utc)
    return d.strftime("%Y-%m-%dT%H:%M:%S.") + f"{d.microsecond // 1000:03d}Z"


class GitHubClient:
    def __init__(self, config: GitHubConfig, transport: httpx.BaseTransport | None = None) -> None:
        self._config = config
        self._http = httpx.Client(transport=transport, timeout=_TIMEOUT)

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> GitHubClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def paginate(self, path: str) -> Iterator[list[Any]]:
        """Yields each page of a paginated list endpoint. `path` may be relative or a full next URL."""
        url: str | None = path if path.startswith("http") else f"{self._config.api_base}{path}"
        while url:
            res = self._http.get(
                url,
                headers={
                    "authorization": f"Bearer {self._config.token}",
                    "accept": "application/vnd.github+json",
                    "x-github-api-version": "2022-11-28",
                },
            )
            if not res.is_success:
                try:
                    text = res.text[:300]
                except Exception:  # noqa: BLE001 - body decoding must never hide the HTTP error
                    text = ""
                rate = ""
                if res.status_code == 403 and res.headers.get("x-ratelimit-remaining") == "0":
                    rate = f" (rate limited until {_rate_reset_iso(res.headers.get('x-ratelimit-reset'))})"
                raise GitHubApiError(
                    f"GitHub GET {urlsplit(url).path} failed: HTTP {res.status_code}{rate} {text}".strip(),
                    res.status_code,
                )
            yield res.json()
            url = parse_next_link(res.headers.get("link"))

    def _all(self, path: str) -> list[Any]:
        out: list[Any] = []
        for page in self.paginate(path):
            out.extend(page)
        return out

    def list_issues(self, repo: str, since: str | None = None) -> list[Issue]:
        o, r = split_repo(repo)
        params = {"state": "all", "per_page": "100"}
        if since:
            params["since"] = since
        raw = self._all(f"/repos/{o}/{r}/issues?{urlencode(params)}")
        return [i for i in (map_issue(repo, x) for x in raw) if i is not None]

    def list_pulls(self, repo: str, since: str | None = None) -> list[GhPull]:
        """PRs updated at/after `since` (all when omitted); stops paging once older ones appear."""
        o, r = split_repo(repo)
        qs = urlencode({"state": "all", "sort": "updated", "direction": "desc", "per_page": "100"})
        out: list[GhPull] = []
        since_ms = _parse_ms(since) if since else None
        for page in self.paginate(f"/repos/{o}/{r}/pulls?{qs}"):
            if since_ms is None:
                fresh = page
            else:
                fresh = [p for p in page if _parse_ms(p.get("updated_at")) >= since_ms]
            out.extend(fresh)
            if len(fresh) < len(page):
                break
        return out

    def list_pull_commit_shas(self, repo: str, number: int) -> list[str]:
        o, r = split_repo(repo)
        commits = self._all(f"/repos/{o}/{r}/pulls/{number}/commits?per_page=100")
        return [c["sha"] for c in commits]

    def fetch_repo(self, repo: str, since: str | None = None) -> RepoSnapshot:
        """Issues + PRs (with commit SHAs) for one repo, optionally only those updated since."""
        issues = self.list_issues(repo, since)
        pulls = self.list_pulls(repo, since)
        pull_requests = [map_pull_request(repo, p, self.list_pull_commit_shas(repo, p["number"])) for p in pulls]
        return RepoSnapshot(issues=issues, pull_requests=pull_requests)
