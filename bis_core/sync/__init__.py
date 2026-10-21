"""On-demand sync used by the app's "Sync" button and the CLI scripts (port of src/lib/sync/index.ts).

LangSmith first (turns), then GitHub (issues + PRs of the repos seen in real turns). One failing
source does not stop the other; a process-wide lock prevents overlapping runs.
"""

from __future__ import annotations

import os
import sqlite3
import sys
import threading
from collections.abc import Callable, Mapping, MutableMapping
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

from bis_core.db import get_sync_state, set_sync_state
from bis_core.langsmith.client import ClientOptions, LangSmithApiError, LangSmithConfigError
from bis_core.langsmith.map import iso_utc
from bis_core.sync.github import (
    GitHubLike,
    GitHubRepoResult,
    RunCommand,
    Scope,
    github_repos,
    github_state_key,
    real_turn_repos,
    resolve_github_token,
    sync_github,
)
from bis_core.sync.langsmith import (
    DEFAULT_LOOKBACK_DAYS,
    LANGSMITH_PROJECT_ID_KEY,
    LANGSMITH_STATE_KEY,
    LANGSMITH_TENANT_ID_KEY,
    OVERLAP,
    LangSmithLike,
    LangSmithSyncResult,
    LangSmithWindow,
    langsmith_window_start,
    sync_langsmith,
)
from bis_core.sync.summary import (
    LAST_SYNC_KEY,
    SyncOutcome,
    SyncSummary,
    clock_time,
    exact_time,
    parse_sync_summary,
    relative_time,
    summary_text,
)

Env = Mapping[str, str | None]


# --- .env.local ---------------------------------------------------------------------------------


def parse_env_file(text: str) -> dict[str, str]:
    """Minimal dotenv parser (KEY=value, optional `export`, quotes, `#` comments)."""
    out: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].lstrip()
        key, sep, value = line.partition("=")
        key = key.strip()
        if not sep or not key or any(c.isspace() for c in key):
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'`":
            quote = value[0]
            value = value[1:-1]
            if quote == '"':
                value = value.replace("\\n", "\n")
        else:
            hash_at = value.find("#")  # Node's loadEnvFile: `#` starts a comment in unquoted values
            if hash_at >= 0:
                value = value[:hash_at].rstrip()
        out[key] = value
    return out


def load_local_env(
    env: MutableMapping[str, str] | None = None,
    if_missing: str | None = None,
    cwd: str | os.PathLike[str] | None = None,
) -> None:
    """Loads `<cwd>/.env.local` into `os.environ` without overriding variables already set.

    With `if_missing`, only when that variable is unset. No-op for a custom (test) `env`.
    """
    if env is not None and env is not os.environ:
        return
    if if_missing and os.environ.get(if_missing):
        return
    file = Path(cwd or os.getcwd()) / ".env.local"
    if not file.is_file():
        return
    for key, value in parse_env_file(file.read_text(encoding="utf-8")).items():
        os.environ.setdefault(key, value)


def read_last_sync(db: sqlite3.Connection) -> SyncSummary | None:
    return parse_sync_summary(get_sync_state(db, LAST_SYNC_KEY))


# --- short user-facing error messages (never echo secrets or raw response bodies) ---------------


def langsmith_error_message(err: BaseException) -> str:
    if isinstance(err, LangSmithConfigError):
        return "LangSmith: LANGSMITH_API_KEY is missing (.env.local)"
    if isinstance(err, LangSmithApiError):
        if err.status in (401, 403):
            return f"LangSmith: key rejected (HTTP {err.status})"
        if err.status == 404:
            return "LangSmith: project not found (LANGSMITH_PROJECT)"
        if err.status == 429:
            return "LangSmith: too many requests, try again in a minute"
        return f"LangSmith: HTTP error {err.status}"
    return "LangSmith: sync could not be completed"


def github_error_message(r: GitHubRepoResult) -> str:
    if r.status == 401:
        return "GitHub: token rejected (HTTP 401)"
    if r.status == 403:
        return f"GitHub {r.repo}: no permission or rate limit reached (HTTP 403)"
    if r.status == 404:
        return f"GitHub {r.repo}: not found or no access (HTTP 404)"
    if r.status:
        return f"GitHub {r.repo}: HTTP error {r.status}"
    return f"GitHub {r.repo}: could not connect"


NO_GITHUB_TOKEN = "GitHub skipped: no token (set GITHUB_TOKEN or run `gh auth login`)"


# --- full sync ----------------------------------------------------------------------------------

_lock = threading.Lock()


def is_sync_running() -> bool:
    return _lock.locked()


def _log_error(message: str) -> None:
    print(message, file=sys.stderr)


def _epoch_ms(d: datetime) -> int:
    return (d - datetime(1970, 1, 1, tzinfo=timezone.utc)) // timedelta(milliseconds=1)


def run_full_sync(
    db: sqlite3.Connection,
    env: Env | None = None,
    now: Callable[[], datetime] | None = None,
    langsmith_client: LangSmithLike | None = None,
    langsmith_client_options: ClientOptions | None = None,
    github_client: GitHubLike | None = None,
    github_transport: httpx.BaseTransport | None = None,
    resolve_token: Callable[[Env], str | None] | None = None,
) -> SyncOutcome:
    """LangSmith then GitHub (real-turn repos only); persists and returns the summary."""
    if not _lock.acquire(blocking=False):
        return SyncOutcome(status="busy")
    clock = now or (lambda: datetime.now(timezone.utc))
    started = _epoch_ms(clock())
    try:
        env = os.environ if env is None else env
        if env is os.environ:
            load_local_env(if_missing="LANGSMITH_API_KEY")
        errors: list[str] = []
        new_turns = turns = issues = pull_requests = 0

        try:
            ls = sync_langsmith(
                db, env=env, now=clock(), client=langsmith_client, client_options=langsmith_client_options
            )
            new_turns, turns = ls.new_turns, ls.turns
        except Exception as err:  # noqa: BLE001 - one failing source must not stop the other
            _log_error(f"[sync] LangSmith: {err}")
            errors.append(langsmith_error_message(err))

        try:
            token = None if github_client else (resolve_token or resolve_github_token)(env)
            if not github_client and not token:
                errors.append(NO_GITHUB_TOKEN)
            else:
                results = sync_github(
                    db,
                    scope="real-turns",
                    env=env,
                    now=clock,
                    token=token,
                    client=github_client,
                    transport=github_transport,
                )
                for r in results:
                    issues += r.issues
                    pull_requests += r.pull_requests
                    if r.error:
                        _log_error(f"[sync] GitHub {r.repo}: {r.error}")
                        errors.append(github_error_message(r))
        except Exception as err:  # noqa: BLE001
            _log_error(f"[sync] GitHub: {err}")
            errors.append("GitHub: sync could not be completed")

        end = clock()
        summary = SyncSummary(
            at=iso_utc(end),
            ok=not errors,
            new_turns=new_turns,
            turns=turns,
            issues=issues,
            pull_requests=pull_requests,
            errors=errors,
            duration_ms=max(0, _epoch_ms(end) - started),
        )
        set_sync_state(db, LAST_SYNC_KEY, summary.to_json())
        return SyncOutcome(status="done", summary=summary)
    finally:
        _lock.release()


__all__ = [
    "DEFAULT_LOOKBACK_DAYS",
    "LANGSMITH_PROJECT_ID_KEY",
    "LANGSMITH_STATE_KEY",
    "LANGSMITH_TENANT_ID_KEY",
    "LAST_SYNC_KEY",
    "NO_GITHUB_TOKEN",
    "OVERLAP",
    "GitHubLike",
    "GitHubRepoResult",
    "LangSmithLike",
    "LangSmithSyncResult",
    "LangSmithWindow",
    "RunCommand",
    "Scope",
    "SyncOutcome",
    "SyncSummary",
    "clock_time",
    "exact_time",
    "github_error_message",
    "github_repos",
    "github_state_key",
    "is_sync_running",
    "langsmith_error_message",
    "langsmith_window_start",
    "load_local_env",
    "parse_env_file",
    "parse_sync_summary",
    "read_last_sync",
    "real_turn_repos",
    "relative_time",
    "resolve_github_token",
    "run_full_sync",
    "summary_text",
    "sync_github",
    "sync_langsmith",
]
