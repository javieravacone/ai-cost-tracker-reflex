"""GitHub issues + PRs sync and token resolution (port of src/lib/sync/github.ts).

Shared by `scripts/sync_github.py` and the app's Sync button.
"""

from __future__ import annotations

import os
import sqlite3
import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Protocol

import httpx

from bis_core.attribution import normalize_repo
from bis_core.db import (
    get_sync_state,
    list_repo_mappings,
    list_turns,
    set_sync_state,
    upsert_issues,
    upsert_pull_requests,
)
from bis_core.github.client import GitHubApiError, GitHubClient, RepoSnapshot, get_github_config
from bis_core.langsmith.map import iso_utc

Scope = Literal["mapped", "real-turns"]


def github_state_key(repo: str) -> str:
    return f"github.{repo}.lastSync"


class GitHubLike(Protocol):
    def fetch_repo(self, repo: str, since: str | None = None) -> RepoSnapshot: ...


@dataclass
class GitHubRepoResult:
    repo: str
    issues: int
    pull_requests: int
    since: str | None = None
    error: str | None = None
    status: int | None = None  # HTTP status when the error came from the GitHub API


def real_turn_repos(db: sqlite3.Connection) -> list[str]:
    """Normalized "owner/name" of repos seen in real turns that are also mapped to a project."""
    mapped = {m.repo.lower() for m in list_repo_mappings(db)}
    seen: set[str] = set()
    for t in list_turns(db):
        if t.source != "langsmith":
            continue
        repo = normalize_repo(t.repo_url)
        if repo and repo in mapped:
            seen.add(repo)
    return sorted(seen)


def github_repos(db: sqlite3.Connection, repo: str | None = None, scope: Scope | None = None) -> list[str]:
    """Repos to sync for the given scope/filter (no network).

    "mapped" (CLI, default): every repo in repo_mappings. "real-turns" (app): only mapped repos
    that appear in real (LangSmith) turns, so the fictional seed repos are never requested.
    """
    only = repo.strip().lower() if repo else None
    if scope == "real-turns":
        base = real_turn_repos(db)
    else:
        base = list(dict.fromkeys(m.repo for m in list_repo_mappings(db)))
    return [r for r in base if not only or r == only]


def sync_github(
    db: sqlite3.Connection,
    full: bool = False,
    repo: str | None = None,
    scope: Scope | None = None,
    token: str | None = None,
    env: Mapping[str, str | None] | None = None,
    now: Callable[[], datetime] | None = None,
    client: GitHubLike | None = None,
    transport: httpx.BaseTransport | None = None,
) -> list[GitHubRepoResult]:
    """Fetches issues + PRs (+ commit SHAs) for each repo, incrementally per repo.

    A failing repo is reported in its result (`error`) and does not stop the others. Raises only
    on missing config.
    """
    repos = github_repos(db, repo=repo, scope=scope)
    if not repos:
        return []
    env = os.environ if env is None else env
    own_client = client is None
    gh: GitHubLike = client if client is not None else GitHubClient(
        get_github_config({**env, "GITHUB_TOKEN": token} if token else env), transport=transport
    )
    clock = now or (lambda: datetime.now(timezone.utc))

    results: list[GitHubRepoResult] = []
    try:
        for r in repos:
            since = None if full else get_sync_state(db, github_state_key(r))
            started_at = iso_utc(clock())
            try:
                snap = gh.fetch_repo(r, since=since)
                upsert_issues(db, snap.issues)
                upsert_pull_requests(db, snap.pull_requests)
                set_sync_state(db, github_state_key(r), started_at)
                results.append(
                    GitHubRepoResult(repo=r, issues=len(snap.issues), pull_requests=len(snap.pull_requests), since=since)
                )
            except Exception as err:  # noqa: BLE001 - one failing repo must not stop the others
                results.append(
                    GitHubRepoResult(
                        repo=r,
                        issues=0,
                        pull_requests=0,
                        since=since,
                        error=str(err),
                        status=err.status if isinstance(err, GitHubApiError) else None,
                    )
                )
    finally:
        if own_client:
            gh.close()  # type: ignore[attr-defined]
    return results


# ---------------------------------------------------------------------------------------------
# Token resolution: GITHUB_TOKEN, else the GitHub CLI session (`gh auth token`), never stored.
# ---------------------------------------------------------------------------------------------

RunCommand = Callable[[str, Sequence[str], float], str]


def _run_command(file: str, args: Sequence[str], timeout_s: float) -> str:
    try:
        proc = subprocess.run(
            [file, *args],
            capture_output=True,
            text=True,
            timeout=timeout_s,
            env={**os.environ, "GH_PROMPT_DISABLED": "1", "NO_COLOR": "1"},
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        raise RuntimeError("command failed") from None
    if proc.returncode != 0:
        raise RuntimeError("command failed")
    return proc.stdout


def resolve_github_token(
    env: Mapping[str, str | None] | None = None,
    run: RunCommand | None = None,
    candidates: Sequence[str] | None = None,
) -> str | None:
    """`GITHUB_TOKEN` if set; else `gh auth token` (PATH, then ~/.local/bin/gh), 5 s timeout; else None."""
    env = os.environ if env is None else env
    from_env = (env.get("GITHUB_TOKEN") or "").strip()
    if from_env:
        return from_env
    runner = run or _run_command
    bins = candidates if candidates is not None else ["gh", str(Path.home() / ".local" / "bin" / "gh")]
    for binary in bins:
        try:
            token = runner(binary, ["auth", "token"], 5).strip()
        except Exception:  # noqa: BLE001
            # Not installed / not logged in / timed out: try the next candidate (error text may echo
            # environment details, so it is deliberately dropped).
            continue
        if token and not any(c.isspace() for c in token):
            return token
    return None
