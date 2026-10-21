"""SQLite repository for the POC (port of src/lib/db/index.ts, stdlib `sqlite3` only).

Every data function takes the connection as its first argument so callers (scripts, tests,
UI) can choose between `get_db()` and `open_db(":memory:")`. Connections run in autocommit
mode (`isolation_level=None`); `with_transaction` uses SAVEPOINTs, so it nests like the TS
version.
"""

from __future__ import annotations

import itertools
import json
import math
import os
import sqlite3
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypeVar

from bis_core._js import js_round, now_iso
from bis_core.db.schema import ADDED_COLUMNS, SCHEMA_VERSION, TABLES, migrate
from bis_core.types import (
    Issue,
    ManualAssignment,
    Member,
    ModelPrice,
    Project,
    PullRequest,
    RepoMapping,
    SeatPlan,
    Team,
    Turn,
)

__all__ = [
    "ADDED_COLUMNS",
    "SCHEMA_VERSION",
    "TABLES",
    "close_db",
    "default_db_path",
    "delete_manual_assignment",
    "get_db",
    "get_sync_state",
    "get_turn",
    "is_open",
    "list_issues",
    "list_manual_assignments",
    "list_members",
    "list_model_prices",
    "list_projects",
    "list_pull_requests",
    "list_repo_mappings",
    "list_seat_plans",
    "list_teams",
    "list_turns",
    "list_turns_by_conversation",
    "migrate",
    "open_db",
    "reset_db",
    "set_manual_assignment",
    "set_sync_state",
    "upsert_issues",
    "upsert_members",
    "upsert_model_prices",
    "upsert_projects",
    "upsert_pull_requests",
    "upsert_repo_mappings",
    "upsert_seat_plans",
    "upsert_teams",
    "upsert_turns",
    "with_transaction",
]

T = TypeVar("T")

# ---------------------------------------------------------------------------
# Connection management


def _is_memory_path(p: str) -> bool:
    return p == ":memory:" or p.startswith("file::memory:")


def open_db(db_path: str | os.PathLike[str]) -> sqlite3.Connection:
    """Opens a database (":memory:" allowed), sets pragmas and runs the idempotent migration."""
    path = str(db_path)
    db = sqlite3.connect(
        path,
        isolation_level=None,  # autocommit; transactions are explicit SAVEPOINTs
        check_same_thread=False,  # the UI server may call from worker threads
        uri=path.startswith("file:"),
    )
    db.row_factory = sqlite3.Row
    if not _is_memory_path(path):
        db.execute("PRAGMA journal_mode = WAL")
        db.execute("PRAGMA synchronous = NORMAL")
    db.execute("PRAGMA foreign_keys = ON")
    db.execute("PRAGMA busy_timeout = 5000")
    migrate(db)
    return db


def is_open(db: sqlite3.Connection) -> bool:
    try:
        db.execute("SELECT 1")
        return True
    except sqlite3.ProgrammingError:
        return False


def default_db_path() -> str:
    """Path used by `get_db()`: `$DB_PATH` or `<cwd>/data/app.db`."""
    env = os.environ.get("DB_PATH")
    return env if env is not None else os.path.join(os.getcwd(), "data", "app.db")


_cache: dict[str, Any] = {}
_cache_lock = threading.Lock()


def get_db() -> sqlite3.Connection:
    """Process-wide singleton for `default_db_path()` (re-opened when the path changes)."""
    db_path = default_db_path()
    with _cache_lock:
        cached = _cache.get("db")
        if cached and cached[0] == db_path and is_open(cached[1]):
            return cached[1]
        if not _is_memory_path(db_path):
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        db = open_db(db_path)
        _cache["db"] = (db_path, db)
        return db


def close_db() -> None:
    """Closes the `get_db()` singleton (if open) and clears the cache. Useful for scripts."""
    with _cache_lock:
        cached = _cache.pop("db", None)
        if cached and is_open(cached[1]):
            cached[1].close()


_savepoint_seq = itertools.count(1)


def with_transaction(db: sqlite3.Connection, fn: Callable[[], T]) -> T:
    """Runs `fn` inside a SAVEPOINT (works top-level and nested). Rolls back on raise."""
    name = f"sp_{next(_savepoint_seq)}"
    db.execute(f"SAVEPOINT {name}")
    try:
        result = fn()
        db.execute(f"RELEASE {name}")
        return result
    except BaseException:
        db.execute(f"ROLLBACK TO {name}")
        db.execute(f"RELEASE {name}")
        raise


# ---------------------------------------------------------------------------
# Generic dataclass <-> row mapping (field names equal column names)
#
# text: as-is; lower: lowercased text (repo slugs); int: rounded integer; real: float;
# json: JSON-encoded array/object. None stays NULL (except json -> "[]").


@dataclass(frozen=True)
class _Entity:
    table: str
    cls: type
    columns: tuple[tuple[str, str], ...]  # (column, kind)
    primary_key: tuple[str, ...]
    order_by: str


def _encode(kind: str, value: Any) -> Any:
    if value is None:
        return "[]" if kind == "json" else None
    if kind == "lower":
        return str(value).lower()
    if kind == "int":
        n = value if isinstance(value, (int, float)) else float(value)
        if isinstance(n, float) and not math.isfinite(n):
            return None
        return int(js_round(n))
    if kind == "real":
        return float(value)
    if kind == "json":
        return json.dumps(value, separators=(",", ":"), ensure_ascii=False)
    return str(value)


def _decode(kind: str, value: Any) -> Any:
    if value is None:
        return [] if kind == "json" else None
    if kind == "int":
        if isinstance(value, float) and value.is_integer():
            return int(value)
        return value if isinstance(value, (int, float)) else int(value)
    if kind == "real":
        return float(value)
    if kind == "json":
        return json.loads(str(value))
    return str(value)


def _from_row(entity: _Entity, row: sqlite3.Row) -> Any:
    return entity.cls(**{col: _decode(kind, row[col]) for col, kind in entity.columns})


def _upsert_sql(entity: _Entity) -> str:
    cols = [c for c, _ in entity.columns]
    updates = [f"{c} = excluded.{c}" for c in cols if c not in entity.primary_key]
    return (
        f"INSERT INTO {entity.table} ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)}) "
        f"ON CONFLICT ({', '.join(entity.primary_key)}) DO "
        + (f"UPDATE SET {', '.join(updates)}" if updates else "NOTHING")
    )


def _upsert_many(db: sqlite3.Connection, entity: _Entity, items: Sequence[Any]) -> int:
    if len(items) == 0:
        return 0
    sql = _upsert_sql(entity)

    def run() -> int:
        for item in items:
            db.execute(sql, tuple(_encode(kind, getattr(item, col)) for col, kind in entity.columns))
        return len(items)

    return with_transaction(db, run)


def _list_all(db: sqlite3.Connection, entity: _Entity) -> list[Any]:
    rows = db.execute(f"SELECT * FROM {entity.table} ORDER BY {entity.order_by}").fetchall()
    return [_from_row(entity, r) for r in rows]


# ---------------------------------------------------------------------------
# Entity definitions

_TURN = _Entity(
    table="turns",
    cls=Turn,
    primary_key=("id",),
    order_by="started_at, id",
    columns=(
        ("id", "text"),
        ("trace_id", "text"),
        ("conversation_id", "text"),
        ("started_at", "text"),
        ("ended_at", "text"),
        ("user_name", "text"),
        ("team_id", "text"),
        ("project_hint", "text"),
        ("repo_url", "text"),
        ("branch", "text"),
        ("commit_sha", "text"),
        ("github_org", "text"),
        ("agent_name", "text"),
        ("model", "text"),
        ("input_tokens", "int"),
        ("output_tokens", "int"),
        ("cache_read_tokens", "int"),
        ("cache_creation_tokens", "int"),
        ("reasoning_tokens", "int"),
        ("llm_calls", "int"),
        ("tool_calls", "int"),
        ("copilot_nano_aiu", "int"),
        ("copilot_usage_coverage", "real"),
        ("source", "text"),
    ),
)

_TEAM = _Entity("teams", Team, (("id", "text"), ("name", "text")), ("id",), "id")
_PROJECT = _Entity("projects", Project, (("id", "text"), ("name", "text")), ("id",), "id")
_REPO_MAPPING = _Entity(
    "repo_mappings", RepoMapping, (("repo", "lower"), ("project_id", "text")), ("repo",), "repo"
)
_MEMBER = _Entity(
    "members",
    Member,
    (("user_name", "text"), ("display_name", "text"), ("team_id", "text"), ("seat_plan_id", "text")),
    ("user_name",),
    "user_name",
)
_ISSUE = _Entity(
    "issues",
    Issue,
    (
        ("repo", "lower"),
        ("number", "int"),
        ("title", "text"),
        ("state", "text"),
        ("url", "text"),
        ("created_at", "text"),
        ("closed_at", "text"),
    ),
    ("repo", "number"),
    "repo, number",
)
_PULL_REQUEST = _Entity(
    "pull_requests",
    PullRequest,
    (
        ("repo", "lower"),
        ("number", "int"),
        ("title", "text"),
        ("state", "text"),
        ("head_branch", "text"),
        ("url", "text"),
        ("linked_issues", "json"),
        ("commit_shas", "json"),
        ("created_at", "text"),
        ("merged_at", "text"),
    ),
    ("repo", "number"),
    "repo, number",
)
_MODEL_PRICE = _Entity(
    "model_prices",
    ModelPrice,
    (
        ("model", "text"),
        ("input_per_mtok", "real"),
        ("output_per_mtok", "real"),
        ("cache_read_per_mtok", "real"),
        ("cache_write_per_mtok", "real"),
        ("premium_multiplier", "real"),
    ),
    ("model",),
    "model",
)
_SEAT_PLAN = _Entity(
    "seat_plans",
    SeatPlan,
    (
        ("id", "text"),
        ("name", "text"),
        ("monthly_price_usd", "real"),
        ("included_premium_requests", "int"),
        ("overage_per_premium_request_usd", "real"),
        ("included_ai_credits", "int"),
    ),
    ("id",),
    "id",
)
_MANUAL_ASSIGNMENT = _Entity(
    "manual_assignments",
    ManualAssignment,
    (
        ("turn_id", "text"),
        ("repo", "lower"),
        ("issue_number", "int"),
        ("pr_number", "int"),
        ("note", "text"),
    ),
    ("turn_id",),
    "turn_id",
)

# ---------------------------------------------------------------------------
# Turns


def upsert_turns(db: sqlite3.Connection, turns: Sequence[Turn]) -> int:
    return _upsert_many(db, _TURN, turns)


def list_turns(db: sqlite3.Connection, from_: str | None = None, to: str | None = None) -> list[Turn]:
    """Turns ordered by started_at. `from_` is inclusive, `to` is exclusive; both are ISO 8601
    strings compared lexicographically against `started_at`."""
    where: list[str] = []
    params: list[str] = []
    if from_:
        where.append("started_at >= ?")
        params.append(from_)
    if to:
        where.append("started_at < ?")
        params.append(to)
    sql = "SELECT * FROM turns" + (f" WHERE {' AND '.join(where)}" if where else "") + f" ORDER BY {_TURN.order_by}"
    return [_from_row(_TURN, r) for r in db.execute(sql, params).fetchall()]


def get_turn(db: sqlite3.Connection, turn_id: str) -> Turn | None:
    row = db.execute("SELECT * FROM turns WHERE id = ?", (turn_id,)).fetchone()
    return _from_row(_TURN, row) if row else None


def list_turns_by_conversation(db: sqlite3.Connection, conversation_id: str) -> list[Turn]:
    rows = db.execute(
        f"SELECT * FROM turns WHERE conversation_id = ? ORDER BY {_TURN.order_by}", (conversation_id,)
    ).fetchall()
    return [_from_row(_TURN, r) for r in rows]


# ---------------------------------------------------------------------------
# Reference data


def upsert_teams(db: sqlite3.Connection, teams: Sequence[Team]) -> int:
    return _upsert_many(db, _TEAM, teams)


def list_teams(db: sqlite3.Connection) -> list[Team]:
    return _list_all(db, _TEAM)


def upsert_projects(db: sqlite3.Connection, projects: Sequence[Project]) -> int:
    return _upsert_many(db, _PROJECT, projects)


def list_projects(db: sqlite3.Connection) -> list[Project]:
    return _list_all(db, _PROJECT)


def upsert_repo_mappings(db: sqlite3.Connection, mappings: Sequence[RepoMapping]) -> int:
    """Repo slugs are stored lowercase."""
    return _upsert_many(db, _REPO_MAPPING, mappings)


def list_repo_mappings(db: sqlite3.Connection) -> list[RepoMapping]:
    return _list_all(db, _REPO_MAPPING)


def upsert_members(db: sqlite3.Connection, members: Sequence[Member]) -> int:
    return _upsert_many(db, _MEMBER, members)


def list_members(db: sqlite3.Connection) -> list[Member]:
    return _list_all(db, _MEMBER)


def upsert_issues(db: sqlite3.Connection, issues: Sequence[Issue]) -> int:
    return _upsert_many(db, _ISSUE, issues)


def list_issues(db: sqlite3.Connection) -> list[Issue]:
    return _list_all(db, _ISSUE)


def upsert_pull_requests(db: sqlite3.Connection, prs: Sequence[PullRequest]) -> int:
    return _upsert_many(db, _PULL_REQUEST, prs)


def list_pull_requests(db: sqlite3.Connection) -> list[PullRequest]:
    return _list_all(db, _PULL_REQUEST)


def upsert_model_prices(db: sqlite3.Connection, prices: Sequence[ModelPrice]) -> int:
    return _upsert_many(db, _MODEL_PRICE, prices)


def list_model_prices(db: sqlite3.Connection) -> list[ModelPrice]:
    return _list_all(db, _MODEL_PRICE)


def upsert_seat_plans(db: sqlite3.Connection, plans: Sequence[SeatPlan]) -> int:
    return _upsert_many(db, _SEAT_PLAN, plans)


def list_seat_plans(db: sqlite3.Connection) -> list[SeatPlan]:
    return _list_all(db, _SEAT_PLAN)


# ---------------------------------------------------------------------------
# Manual assignments (one per turn; the turn must exist — FK, cascades on delete)


def set_manual_assignment(db: sqlite3.Connection, assignment: ManualAssignment) -> None:
    _upsert_many(db, _MANUAL_ASSIGNMENT, [assignment])


def delete_manual_assignment(db: sqlite3.Connection, turn_id: str) -> None:
    db.execute("DELETE FROM manual_assignments WHERE turn_id = ?", (turn_id,))


def list_manual_assignments(db: sqlite3.Connection) -> list[ManualAssignment]:
    return _list_all(db, _MANUAL_ASSIGNMENT)


# ---------------------------------------------------------------------------
# Sync state (key/value cursors for incremental syncs)


def get_sync_state(db: sqlite3.Connection, key: str) -> str | None:
    row = db.execute("SELECT value FROM sync_state WHERE key = ?", (key,)).fetchone()
    return str(row["value"]) if row else None


def set_sync_state(db: sqlite3.Connection, key: str, value: str) -> None:
    db.execute(
        "INSERT INTO sync_state (key, value, updated_at) VALUES (?, ?, ?) "
        "ON CONFLICT (key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
        (key, value, now_iso()),
    )


# ---------------------------------------------------------------------------
# Maintenance


def reset_db(db: sqlite3.Connection) -> None:
    """Deletes every row from every table; the schema is kept."""

    def run() -> None:
        for table in TABLES:
            db.execute(f"DELETE FROM {table}")

    with_transaction(db, run)
