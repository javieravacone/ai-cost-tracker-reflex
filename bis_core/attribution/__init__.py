"""Attribution engine: turn -> project / team / issue / PR with a confidence level.

Port of src/lib/attribution/index.ts. Pure and synchronous: no I/O. All lookup maps are built
once per call.
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from bis_core._js import parse_iso_ms
from bis_core.attribution.branch import is_default_branch, parse_issue_from_branch
from bis_core.attribution.repo import normalize_repo
from bis_core.types import (
    CONFIDENCE_LEVELS,
    Attribution,
    Confidence,
    Issue,
    ManualAssignment,
    Member,
    PullRequest,
    RepoMapping,
    Turn,
)

__all__ = [
    "CONFIDENCE_LEVELS",
    "AttributionContext",
    "InferredIssue",
    "attribute",
    "is_default_branch",
    "issue_key",
    "normalize_repo",
    "parse_issue_from_branch",
    "pr_key",
    "summarize_confidence",
]


@dataclass
class InferredIssue:
    issue_key: str
    reason: str


@dataclass
class AttributionContext:
    repo_mappings: list[RepoMapping] = field(default_factory=list)
    members: list[Member] = field(default_factory=list)
    issues: list[Issue] = field(default_factory=list)
    pull_requests: list[PullRequest] = field(default_factory=list)
    manual_assignments: list[ManualAssignment] = field(default_factory=list)
    # Optional hook: returns an InferredIssue (or a mapping with issue_key/reason) or None.
    infer_issue: Callable[[Turn], InferredIssue | Mapping[str, str] | None] | None = None


def issue_key(repo: str, n: int) -> str:
    return f"{repo}#{n}"


def pr_key(repo: str, n: int) -> str:
    return f"{repo}!{n}"


MIN_SHA_PREFIX = 7
_HEX_RE = re.compile(r"[0-9a-f]+")


@dataclass(eq=False)
class _IndexedPr:
    pr: PullRequest
    repo: str
    created_ms: float  # invalid dates become -inf
    end_ms: float  # merged_at, or +inf while not merged


@dataclass
class _RepoPrIndex:
    by_branch: dict[str, list[_IndexedPr]] = field(default_factory=dict)
    by_sha: dict[str, list[_IndexedPr]] = field(default_factory=dict)
    by_sha_prefix: dict[str, list[tuple[str, _IndexedPr]]] = field(default_factory=dict)


@dataclass
class _Index:
    project_by_repo: dict[str, str]
    member_by_user: dict[str, Member]
    issue_keys: set[str]
    pr_by_key: dict[str, _IndexedPr]
    prs_by_repo: dict[str, _RepoPrIndex]
    manual_by_turn: dict[str, ManualAssignment]
    repo_cache: dict[str | None, str | None]
    branch_cache: dict[str | None, int | None]


def _memo(cache: dict, key: Any, fn: Callable[[Any], Any]) -> Any:
    if key in cache:
        return cache[key]
    v = fn(key)
    cache[key] = v
    return v


def _to_ms(iso: str | None, fallback: float) -> float:
    if not iso:
        return fallback
    t = parse_iso_ms(iso)
    return fallback if t is None else float(t)


def _build_index(ctx: AttributionContext) -> _Index:
    repo_cache: dict[str | None, str | None] = {}

    def repo_of_cached(r: str) -> str:
        n = _memo(repo_cache, r, normalize_repo)
        return n if n is not None else r.strip().lower()

    project_by_repo: dict[str, str] = {}
    for m in ctx.repo_mappings:
        project_by_repo[repo_of_cached(m.repo)] = m.project_id

    member_by_user: dict[str, Member] = {}
    for mem in ctx.members:
        member_by_user[mem.user_name.lower()] = mem

    issue_keys = {issue_key(repo_of_cached(i.repo), i.number) for i in ctx.issues}

    pr_by_key: dict[str, _IndexedPr] = {}
    prs_by_repo: dict[str, _RepoPrIndex] = {}
    for pr in ctx.pull_requests:
        repo = repo_of_cached(pr.repo)
        ix = _IndexedPr(pr=pr, repo=repo, created_ms=_to_ms(pr.created_at, -math.inf), end_ms=_to_ms(pr.merged_at, math.inf))
        pr_by_key[pr_key(repo, pr.number)] = ix
        r = prs_by_repo.get(repo)
        if r is None:
            r = _RepoPrIndex()
            prs_by_repo[repo] = r
        if pr.head_branch:
            r.by_branch.setdefault(pr.head_branch, []).append(ix)
        for raw in pr.commit_shas:
            sha = raw.strip().lower()
            if len(sha) < MIN_SHA_PREFIX:
                continue
            exact = r.by_sha.get(sha)
            if exact is None:
                r.by_sha[sha] = [ix]
            elif not any(e is ix for e in exact):
                exact.append(ix)
            r.by_sha_prefix.setdefault(sha[:MIN_SHA_PREFIX], []).append((sha, ix))

    manual_by_turn: dict[str, ManualAssignment] = {}
    for a in ctx.manual_assignments:
        manual_by_turn[a.turn_id] = a  # last wins

    return _Index(
        project_by_repo=project_by_repo,
        member_by_user=member_by_user,
        issue_keys=issue_keys,
        pr_by_key=pr_by_key,
        prs_by_repo=prs_by_repo,
        manual_by_turn=manual_by_turn,
        repo_cache=repo_cache,
        branch_cache={},
    )


def _select_pr(candidates: list[_IndexedPr], at_ms: float) -> _IndexedPr | None:
    """Picks the PR most plausibly being worked on at `at_ms`:
    1. PRs whose [created_at, merged_at ?? inf] window contains the turn (latest created wins);
    2. else the most recently created PR before the turn;
    3. else the most recently created PR overall.
    """
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]
    in_window: _IndexedPr | None = None
    before: _IndexedPr | None = None
    latest: _IndexedPr | None = None
    for c in candidates:
        if latest is None or c.created_ms > latest.created_ms:
            latest = c
        if math.isnan(at_ms):
            continue
        if c.created_ms <= at_ms <= c.end_ms:
            if in_window is None or c.created_ms > in_window.created_ms:
                in_window = c
        elif c.created_ms <= at_ms:
            if before is None or c.created_ms > before.created_ms:
                before = c
    return in_window or before or latest


def _find_prs_by_commit(ix: _Index, repo: str, raw_sha: str) -> list[_IndexedPr]:
    sha = raw_sha.strip().lower()
    if len(sha) < MIN_SHA_PREFIX or not _HEX_RE.fullmatch(sha):
        return []
    r = ix.prs_by_repo.get(repo)
    if r is None:
        return []
    exact = r.by_sha.get(sha)
    if exact:
        return exact  # O(1) fast path for full / identical shas
    bucket = r.by_sha_prefix.get(sha[:MIN_SHA_PREFIX])
    if not bucket:
        return []
    out: list[_IndexedPr] = []
    for full, pr in bucket:
        if (full.startswith(sha) or sha.startswith(full)) and not any(o is pr for o in out):
            out.append(pr)
    return out


def _linked_issue(ip: _IndexedPr) -> tuple[str | None, str]:
    """Issue derived from a PR's linked issues: only when exactly one is linked."""
    linked = ip.pr.linked_issues
    if len(linked) == 1:
        return issue_key(ip.repo, linked[0]), f"linked issue → #{linked[0]}"
    if len(linked) == 0:
        return None, "no linked issue"
    return None, f"{len(linked)} linked issues, issue left empty"


def _project_reason(turn: Turn, repo: str | None, project_id: str | None) -> str:
    parts: list[str] = []
    if not repo:
        parts.append(f"unrecognized repo {turn.repo_url}" if turn.repo_url else "no repo")
    elif not turn.branch:
        parts.append("no branch")
    elif is_default_branch(turn.branch):
        parts.append(f"branch {turn.branch}: default branch")
    else:
        parts.append(f"branch {turn.branch}: no issue/PR match")
    if repo and project_id is None:
        parts.append("repo not mapped")
    return "; ".join(parts)


def _attribute_one(turn: Turn, ix: _Index, ctx: AttributionContext) -> Attribution:
    turn_repo = _memo(ix.repo_cache, turn.repo_url, normalize_repo)
    project_id: str | None = (
        turn.project_hint if turn.project_hint is not None else (ix.project_by_repo.get(turn_repo) if turn_repo else None)
    )
    if turn.team_id is not None:
        team_id = turn.team_id
    elif turn.user_name:
        member = ix.member_by_user.get(turn.user_name.lower())
        team_id = member.team_id if member else None
    else:
        team_id = None
    at = _to_ms(turn.started_at, math.nan)

    def result(confidence: Confidence, reason: str, repo: str | None, issue: str | None, pr: str | None) -> Attribution:
        return Attribution(
            turn_id=turn.id,
            project_id=project_id,
            team_id=team_id,
            user_name=turn.user_name,
            repo=repo,
            issue_key=issue,
            pr_key=pr,
            confidence=confidence,
            reason=reason,
        )

    # 1. manual
    manual = ix.manual_by_turn.get(turn.id)
    if manual:
        norm = _memo(ix.repo_cache, manual.repo, normalize_repo)
        repo = norm if norm is not None else manual.repo.strip().lower()
        mapped_project = ix.project_by_repo.get(repo)
        if mapped_project:
            project_id = mapped_project
        issue = issue_key(repo, manual.issue_number) if manual.issue_number is not None else None
        pr = pr_key(repo, manual.pr_number) if manual.pr_number is not None else None
        parts: list[str] = []
        if issue:
            parts.append(f"#{manual.issue_number}")
        if pr:
            parts.append(f"PR !{manual.pr_number}")
        if not issue and pr:
            known = ix.pr_by_key.get(pr)
            if known:
                issue, note = _linked_issue(known)
                parts.append(note)
            else:
                parts.append("PR not synced")
        reason = f"manual → {repo}" + (" " + ", ".join(parts) if parts else " (project only)")
        if manual.note:
            reason += f" — {manual.note}"
        return result("manual", reason, repo, issue, pr)

    if turn_repo:
        repo_ix = ix.prs_by_repo.get(turn_repo)
        branch_prs = (repo_ix.by_branch.get(turn.branch) if (turn.branch and repo_ix) else None) or []

        # 2. exact-branch
        n = _memo(ix.branch_cache, turn.branch, parse_issue_from_branch)
        if n is not None:
            issue = issue_key(turn_repo, n)
            sel = _select_pr(branch_prs, at)
            reason = f"branch {turn.branch} → #{n}"
            if issue not in ix.issue_keys:
                reason += " (issue not synced)"
            if sel:
                reason += f"; PR !{sel.pr.number}"
            return result("exact-branch", reason, turn_repo, issue, pr_key(turn_repo, sel.pr.number) if sel else None)

        # 3. exact-pr
        head_pr = _select_pr(branch_prs, at)
        if head_pr:
            key, note = _linked_issue(head_pr)
            reason = f"branch {turn.branch} = head of PR !{head_pr.pr.number}; {note}"
            return result("exact-pr", reason, turn_repo, key, pr_key(turn_repo, head_pr.pr.number))

        # 4. exact-commit
        if turn.commit_sha:
            commit_pr = _select_pr(_find_prs_by_commit(ix, turn_repo, turn.commit_sha), at)
            if commit_pr:
                key, note = _linked_issue(commit_pr)
                short = turn.commit_sha.strip().lower()[:MIN_SHA_PREFIX]
                reason = f"commit {short} in PR !{commit_pr.pr.number}; {note}"
                return result("exact-commit", reason, turn_repo, key, pr_key(turn_repo, commit_pr.pr.number))

    # 5. inferred
    inferred = ctx.infer_issue(turn) if ctx.infer_issue else None
    if inferred:
        if isinstance(inferred, Mapping):
            inferred = InferredIssue(issue_key=inferred["issue_key"], reason=inferred["reason"])
        return result("inferred", f"inferred: {inferred.reason}", turn_repo, inferred.issue_key, None)

    # 6. project
    return result("project", _project_reason(turn, turn_repo, project_id), turn_repo, None, None)


def attribute(turns: list[Turn], ctx: AttributionContext) -> list[Attribution]:
    """Attributes every turn; output order matches input order. O(turns + context)."""
    ix = _build_index(ctx)
    return [_attribute_one(t, ix, ctx) for t in turns]


def summarize_confidence(attributions: list[Attribution]) -> dict[Confidence, int]:
    out: dict[Confidence, int] = {c: 0 for c in CONFIDENCE_LEVELS}
    for a in attributions:
        out[a.confidence] += 1
    return out
