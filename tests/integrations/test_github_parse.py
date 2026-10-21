"""Port of src/lib/github/parse.test.ts."""

from __future__ import annotations

from bis_core.github.parse import map_issue, map_pull_request, parse_linked_issues, parse_next_link
from bis_core.types import Issue, PullRequest


class TestParseLinkedIssues:
    def test_handles_every_closing_keyword_variant_case_insensitively(self) -> None:
        body = "\n".join(
            ["Close #1", "closes #2", "CLOSED #3", "fix #4", "Fixes #5", "fixed #6", "resolve #7", "Resolves: #8", "resolved #9"]
        )
        assert parse_linked_issues(body) == [1, 2, 3, 4, 5, 6, 7, 8, 9]

    def test_dedupes_and_sorts(self) -> None:
        assert parse_linked_issues("Fixes #12. Also fixes #3 and closes #12") == [3, 12]

    def test_ignores_plain_mentions_cross_repo_refs_and_keywords_inside_words(self) -> None:
        assert parse_linked_issues("Related to #4, see #5") == []
        assert parse_linked_issues("fixes other-org/other#6") == []
        assert parse_linked_issues("prefixes #7 and unresolved #8") == []
        assert parse_linked_issues("fixes #9abc") == []

    def test_only_links_the_first_number_after_a_keyword(self) -> None:
        assert parse_linked_issues("Fixes #1, #2") == [1]

    def test_accepts_same_repo_issue_urls_when_the_repo_is_known(self) -> None:
        body = "Fixes https://github.com/acme-labs/atlas/issues/42\ncloses https://github.com/x/y/issues/1"
        assert parse_linked_issues(body, "acme-labs/atlas") == [42]
        assert parse_linked_issues(body) == []

    def test_handles_null_and_empty_bodies(self) -> None:
        assert parse_linked_issues(None) == []
        assert parse_linked_issues("") == []


class TestParseNextLink:
    def test_extracts_rel_next(self) -> None:
        link = (
            '<https://api.github.com/repositories/1/issues?page=2>; rel="next", '
            '<https://api.github.com/repositories/1/issues?page=5>; rel="last"'
        )
        assert parse_next_link(link) == "https://api.github.com/repositories/1/issues?page=2"
        assert parse_next_link('<https://x/?page=1>; rel="prev", <https://x/?page=1>; rel="first"') is None
        assert parse_next_link(None) is None


BASE_ISSUE = {
    "number": 7,
    "title": "Login breaks",
    "state": "closed",
    "html_url": "https://github.com/acme-labs/atlas/issues/7",
    "created_at": "2026-10-01T00:00:00Z",
    "closed_at": "2026-10-02T00:00:00Z",
}

PULL = {
    "number": 45,
    "title": "Fix login",
    "state": "closed",
    "body": "Fixes #7",
    "html_url": "https://github.com/acme-labs/atlas/pull/45",
    "created_at": "2026-10-01T00:00:00Z",
    "updated_at": "2026-10-03T00:00:00Z",
    "merged_at": "2026-10-03T00:00:00Z",
    "head": {"ref": "feat/7-login"},
}


class TestMappers:
    def test_maps_issues_and_skips_prs_returned_by_issues(self) -> None:
        assert map_issue("acme-labs/atlas", BASE_ISSUE) == Issue(
            repo="acme-labs/atlas",
            number=7,
            title="Login breaks",
            state="closed",
            url=BASE_ISSUE["html_url"],
            created_at=BASE_ISSUE["created_at"],
            closed_at=BASE_ISSUE["closed_at"],
        )
        assert map_issue("acme-labs/atlas", {**BASE_ISSUE, "pull_request": {"url": "x"}}) is None

    def test_maps_a_merged_pr_with_linked_issues_and_commits(self) -> None:
        assert map_pull_request("acme-labs/atlas", PULL, ["sha1", "sha2"]) == PullRequest(
            repo="acme-labs/atlas",
            number=45,
            title="Fix login",
            state="merged",
            head_branch="feat/7-login",
            url=PULL["html_url"],
            linked_issues=[7],
            commit_shas=["sha1", "sha2"],
            created_at=PULL["created_at"],
            merged_at=PULL["merged_at"],
        )

    def test_distinguishes_closed_unmerged_and_open_prs(self) -> None:
        assert map_pull_request("a/b", {**PULL, "merged_at": None}).state == "closed"
        pr = map_pull_request("a/b", {**PULL, "state": "open", "merged_at": None, "body": None})
        assert (pr.state, pr.linked_issues, pr.commit_shas) == ("open", [], [])
