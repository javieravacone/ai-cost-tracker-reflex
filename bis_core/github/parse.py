"""Pure GitHub helpers: closing-keyword parsing, Link header pagination, REST -> domain mappers.

Port of ai-cost-tracker src/lib/github/parse.ts. Raw REST v3 objects are plain dicts.
"""

from __future__ import annotations

import re
from typing import Any

from bis_core.types import Issue, PullRequest

# GitHub closing keywords: close/closes/closed, fix/fixes/fixed, resolve/resolves/resolved.
# https://docs.github.com/en/issues/tracking-your-work-with-issues/using-issues/linking-a-pull-request-to-an-issue
_KEYWORD = r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\b:?\s+"
_ISSUE_REF_RE = re.compile(_KEYWORD + r"#(\d+)\b", re.IGNORECASE)

GhIssue = dict[str, Any]
GhPull = dict[str, Any]


def parse_linked_issues(body: str | None, repo: str | None = None) -> list[int]:
    """Issue numbers a PR body closes in the SAME repo (`Fixes #12`).

    Cross-repo references (`fixes other/repo#3`) are ignored; full issue URLs are accepted only
    when `repo` matches.
    """
    if not body:
        return []
    found: set[int] = {int(m.group(1)) for m in _ISSUE_REF_RE.finditer(body)}
    if repo:
        url_re = re.compile(
            _KEYWORD + r"https?://github\.com/" + re.escape(repo) + r"/issues/(\d+)\b", re.IGNORECASE
        )
        found.update(int(m.group(1)) for m in url_re.finditer(body))
    return sorted(n for n in found if n > 0)


_LINK_RE = re.compile(r'<([^>]+)>\s*;\s*rel="([^"]+)"')


def parse_next_link(link: str | None) -> str | None:
    """URL of rel="next" in a GitHub `Link` header, or None."""
    if not link:
        return None
    for part in link.split(","):
        m = _LINK_RE.search(part.strip())
        if m and "next" in m.group(2).split():
            return m.group(1)
    return None


def map_issue(repo: str, raw: GhIssue) -> Issue | None:
    """`/issues` also returns PRs; those (with `pull_request`) map to None."""
    if raw.get("pull_request"):
        return None
    return Issue(
        repo=repo,
        number=raw["number"],
        title=raw["title"],
        state="closed" if raw.get("state") == "closed" else "open",
        url=raw["html_url"],
        created_at=raw["created_at"],
        closed_at=raw.get("closed_at"),
    )


def map_pull_request(repo: str, raw: GhPull, commit_shas: list[str] | None = None) -> PullRequest:
    merged_at = raw.get("merged_at")
    if merged_at:
        state = "merged"
    elif raw.get("state") == "closed":
        state = "closed"
    else:
        state = "open"
    return PullRequest(
        repo=repo,
        number=raw["number"],
        title=raw["title"],
        state=state,
        head_branch=raw["head"]["ref"],
        url=raw["html_url"],
        linked_issues=parse_linked_issues(raw.get("body"), repo),
        commit_shas=list(commit_shas or []),
        created_at=raw["created_at"],
        merged_at=merged_at,
    )
