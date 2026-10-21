"""Incremental LangSmith -> SQLite sync of Copilot Chat turns (port of src/lib/sync/langsmith.ts).

Shared by `scripts/sync.py` and the app's Sync button.
"""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Protocol

from bis_core.db import get_sync_state, get_turn, set_sync_state, upsert_turns
from bis_core.db.content import save_turn_content
from bis_core.langsmith.client import (
    ClientOptions,
    LangSmithClient,
    LangSmithProject,
    get_langsmith_config,
)
from bis_core.content_types import has_captured_content
from bis_core.langsmith.content import extract_turn_content
from bis_core.langsmith.map import LangSmithRun, map_runs_to_turns, parse_iso

LANGSMITH_STATE_KEY = "langsmith.lastStartTime"
# Tracing project id and its organization (tenant) id, stored for LangSmith UI trace links.
LANGSMITH_PROJECT_ID_KEY = "langsmith.projectId"
LANGSMITH_TENANT_ID_KEY = "langsmith.tenantId"
DEFAULT_LOOKBACK_DAYS = 30
# Re-read this much before the last seen turn so in-flight traces get their late children.
OVERLAP = timedelta(hours=2)


class LangSmithLike(Protocol):
    """What the sync needs from a LangSmith client (tests pass fakes).

    `resolve_project` (project id plus tenant id) is optional; when absent `resolve_project_id`
    is used and no tenant id is stored.
    """

    def resolve_project_id(self) -> str: ...

    def fetch_runs_in_window(
        self, project_id: str, start: datetime, end: datetime | None = None
    ) -> list[LangSmithRun]: ...


@dataclass
class LangSmithWindow:
    project: str
    endpoint: str
    start: datetime  # `from` in the TS app
    end: datetime  # `to` in the TS app
    incremental: bool


@dataclass
class LangSmithSyncResult(LangSmithWindow):
    runs: int
    turns: int
    upserted: int
    new_turns: int  # turns whose id was not in the DB before this sync
    with_repo: int
    with_tokens: int
    latest: str | None  # latest turn start seen in this window (None when no turns)
    state: str | None  # value of the incremental cursor after the sync
    with_content: int  # turns with captured prompt/answer (content capture on)
    events: int  # agent steps (model + tool calls) stored
    with_skills: int  # turns where at least one skill was detected


def langsmith_window_start(
    stored: str | None, now: datetime, full: bool = False, since: datetime | None = None
) -> datetime:
    """Window start: `since` > default lookback when `full`/no state > stored cursor minus overlap."""
    if since:
        return since
    default_from = now - timedelta(days=DEFAULT_LOOKBACK_DAYS)
    if full or not stored:
        return default_from
    stored_at = parse_iso(stored)
    if stored_at is None:  # `new Date(garbage)` -> Invalid Date; fall back to the lookback
        return default_from
    return stored_at - OVERLAP


def sync_langsmith(
    db: sqlite3.Connection,
    full: bool = False,
    since: datetime | None = None,
    env: Mapping[str, str | None] | None = None,
    now: datetime | None = None,
    client: LangSmithLike | None = None,
    client_options: ClientOptions | None = None,
    on_start: Callable[[LangSmithWindow], None] | None = None,
) -> LangSmithSyncResult:
    config = get_langsmith_config(os.environ if env is None else env)
    now = now or datetime.now(timezone.utc)
    stored = get_sync_state(db, LANGSMITH_STATE_KEY)
    start = langsmith_window_start(stored, now, full=full, since=since)
    window = LangSmithWindow(
        project=config.project,
        endpoint=config.endpoint,
        start=start,
        end=now,
        incremental=bool(stored and not full and not since),
    )
    if on_start:
        on_start(window)

    own_client = client is None
    ls = client if client is not None else LangSmithClient(config, client_options)
    try:
        resolve = getattr(ls, "resolve_project", None)
        project = resolve() if callable(resolve) else LangSmithProject(id=ls.resolve_project_id(), tenant_id=None)
        set_sync_state(db, LANGSMITH_PROJECT_ID_KEY, project.id)
        if project.tenant_id:
            set_sync_state(db, LANGSMITH_TENANT_ID_KEY, project.tenant_id)
        runs = ls.fetch_runs_in_window(project.id, start, now)
    finally:
        if own_client:
            ls.close()  # type: ignore[union-attr]

    turns = map_runs_to_turns(runs)
    new_turns = sum(1 for t in turns if get_turn(db, t.id) is None)
    upserted = upsert_turns(db, turns)
    extracted = extract_turn_content(runs)
    save_turn_content(db, extracted.contents, extracted.events, now)

    latest: str | None = None
    for t in turns:
        if not latest or t.started_at > latest:
            latest = t.started_at
    if latest and (not stored or latest > stored):
        set_sync_state(db, LANGSMITH_STATE_KEY, latest)

    return LangSmithSyncResult(
        project=window.project,
        endpoint=window.endpoint,
        start=window.start,
        end=window.end,
        incremental=window.incremental,
        runs=len(runs),
        turns=len(turns),
        upserted=upserted,
        new_turns=new_turns,
        with_repo=sum(1 for t in turns if t.repo_url),
        with_tokens=sum(1 for t in turns if t.input_tokens + t.output_tokens > 0),
        latest=latest,
        state=get_sync_state(db, LANGSMITH_STATE_KEY),
        with_content=sum(1 for c in extracted.contents if has_captured_content(c)),
        events=len(extracted.events),
        with_skills=sum(1 for c in extracted.contents if c.skills),
    )


__all__ = [
    "DEFAULT_LOOKBACK_DAYS",
    "LANGSMITH_PROJECT_ID_KEY",
    "LANGSMITH_STATE_KEY",
    "LANGSMITH_TENANT_ID_KEY",
    "OVERLAP",
    "LangSmithLike",
    "LangSmithSyncResult",
    "LangSmithWindow",
    "langsmith_window_start",
    "sync_langsmith",
]
