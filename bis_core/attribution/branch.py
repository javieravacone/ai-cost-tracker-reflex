"""Conservative extraction of a GitHub issue number from a branch name.

Port of src/lib/attribution/branch.ts. Rules (case-insensitive; a leading "refs/heads/" is
stripped first):
 1. Reject long-lived / default branches: main, master, develop, development, dev, trunk,
    staging, production, prod, gh-pages, HEAD.
 2. Reject bot / release namespaces by FIRST path segment: release(s), dependabot, renovate,
    snyk-*, revert-* (GitHub revert branches carry a PR number, not an issue number), and
    tag-like "v1.2" style names.
 3. Reject when the branch contains a date: a year-like 19xx/20xx followed by a date separator
    (-, _, ., /) and a month 1..12 (e.g. hotfix/2026-10-16, 2026_10-cleanup).
 4. Only the LAST path segment is inspected ("users/ana/123-x" -> "123-x"). It must be one of:
      - "<n>" or "#<n>", optionally followed by "-" or "_" and a slug (123, 123-login, #123-x)
      - "issue-<n>", "issues-<n>", "gh-<n>" (separator "-"/"_" optional, optional "#"),
        optionally followed by "-"/"_" and a slug.
    Anything else is rejected, notably Jira keys (ABC-123-x), versions (next-16.4.2, 1.2.3)
    and number runs ("123-456").
 5. The number must be 1..9_999_999 without a leading zero.
"""

from __future__ import annotations

import re

DEFAULT_BRANCHES = frozenset(
    {
        "main",
        "master",
        "develop",
        "development",
        "dev",
        "trunk",
        "staging",
        "production",
        "prod",
        "gh-pages",
        "head",
    }
)

_REJECT_FIRST_SEGMENT = re.compile(r"(?:releases?|dependabot|renovate|snyk-.*|revert-.*|v[0-9]+(?:\.[0-9]+)*)")
_DATE_RE = re.compile(r"(?:^|[/_.-])(?:19|20)[0-9][0-9][-_./](?:0?[1-9]|1[0-2])(?:\Z|[-_./])")
_NUMBER_SEGMENT = re.compile(r"#?([1-9][0-9]{0,6})(?:[-_](.*))?")
_PREFIXED_SEGMENT = re.compile(r"(?:issues?|gh)[-_]?#?([1-9][0-9]{0,6})(?:[-_].*)?")
_NUMBER_RUN = re.compile(r"[0-9_.-]+")
_REF_PREFIX = re.compile(r"^refs/heads/", re.IGNORECASE)


def _strip_ref(branch: str) -> str:
    return _REF_PREFIX.sub("", branch.strip(), count=1)


def is_default_branch(branch: str | None) -> bool:
    """Returns True for well-known default / long-lived branch names."""
    if not branch:
        return False
    return _strip_ref(branch).lower() in DEFAULT_BRANCHES


def parse_issue_from_branch(branch: str | None) -> int | None:
    if not branch:
        return None
    b = _strip_ref(branch).lower()
    if not b or b in DEFAULT_BRANCHES:
        return None

    segs = [s for s in b.split("/") if s]
    if not segs:
        return None
    if _REJECT_FIRST_SEGMENT.fullmatch(segs[0]):
        return None
    if _DATE_RE.search(b):
        return None

    last = segs[-1]

    plain = _NUMBER_SEGMENT.fullmatch(last)
    if plain:
        rest = plain.group(2)
        # "123-456", "123-4-5": runs of numbers are dates/versions, not slugs.
        if rest is not None and (rest == "" or _NUMBER_RUN.fullmatch(rest)):
            return None
        return int(plain.group(1))

    prefixed = _PREFIXED_SEGMENT.fullmatch(last)
    if prefixed:
        return int(prefixed.group(1))
    return None
