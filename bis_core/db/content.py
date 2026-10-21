"""Repository for captured content (schema v3): turn_content, turn_events, skill_usage.

Port of ai-cost-tracker src/lib/db/content.ts. A sync replaces everything stored for each turn it
fetched, so re-syncs are idempotent. JSON columns are written exactly like the TS app
(`skills_json` = `[{"name","version","path"}]`, compact JSON), so both apps can read them.
"""

from __future__ import annotations

import json
import math
import sqlite3
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any

from bis_core.db import with_transaction
from bis_core.langsmith.content import js_stringify
from bis_core.langsmith.map import iso_utc
from bis_core.types import SkillUse, TurnContent, TurnEvent


def _bool(v: Any) -> bool:
    try:
        return float(v) == 1
    except (TypeError, ValueError):
        return False


def _int(v: Any) -> int | None:
    return None if v is None else int(v)


def _str(v: Any) -> str | None:
    return None if v is None else str(v)


def _parse_json(raw: Any, fallback: Any) -> Any:
    if not isinstance(raw, str):
        return fallback
    try:
        return json.loads(raw)
    except ValueError:
        return fallback


def _round(v: int | float | None) -> int | None:
    """`Math.round` (half up) for integer columns."""
    return None if v is None else math.floor(v + 0.5)


def _rows(db: sqlite3.Connection, sql: str, params: Sequence[Any] = ()) -> list[dict[str, Any]]:
    """Rows as dicts, independent of the connection's row_factory."""
    cur = db.execute(sql, params)
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, tuple(r))) for r in cur.fetchall()]


def save_turn_content(
    db: sqlite3.Connection,
    contents: Sequence[TurnContent],
    events: Sequence[TurnEvent],
    now: datetime | None = None,
) -> None:
    """Replaces content, events and skill usage of every turn in `contents` (turns must exist)."""
    if not contents:
        return
    at = iso_utc(now or datetime.now(timezone.utc))
    events_by_turn: dict[str, list[TurnEvent]] = {}
    for e in events:
        events_by_turn.setdefault(e.turn_id, []).append(e)

    up_content = (
        "INSERT INTO turn_content (turn_id, user_prompt, user_prompt_truncated, final_answer, "
        "final_answer_truncated, error, skills_json, feedback_json, captured_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT (turn_id) DO UPDATE SET user_prompt = excluded.user_prompt, "
        "user_prompt_truncated = excluded.user_prompt_truncated, final_answer = excluded.final_answer, "
        "final_answer_truncated = excluded.final_answer_truncated, error = excluded.error, "
        "skills_json = excluded.skills_json, feedback_json = excluded.feedback_json, captured_at = excluded.captured_at"
    )
    ins_event = (
        "INSERT INTO turn_events (turn_id, seq, run_id, trace_id, kind, name, started_at, duration_ms, tokens_in, "
        "tokens_out, nano_aiu, text, text_truncated, tool_calls, args, args_truncated, result, result_truncated, error) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
    )
    ins_skill = "INSERT OR IGNORE INTO skill_usage (turn_id, skill, version, path) VALUES (?, ?, ?, ?)"

    def write() -> None:
        for c in contents:
            db.execute("DELETE FROM turn_events WHERE turn_id = ?", (c.turn_id,))
            db.execute("DELETE FROM skill_usage WHERE turn_id = ?", (c.turn_id,))
            db.execute(
                up_content,
                (
                    c.turn_id,
                    c.user_prompt,
                    int(c.user_prompt_truncated),
                    c.final_answer,
                    int(c.final_answer_truncated),
                    c.error,
                    js_stringify([asdict(s) for s in c.skills]),
                    js_stringify(c.feedback_stats) if c.feedback_stats else None,
                    at,
                ),
            )
            for e in events_by_turn.get(c.turn_id, []):
                db.execute(
                    ins_event,
                    (
                        e.turn_id,
                        e.seq,
                        e.run_id,
                        e.trace_id,
                        e.kind,
                        e.name,
                        e.started_at,
                        _round(e.duration_ms),
                        _round(e.tokens_in),
                        _round(e.tokens_out),
                        _round(e.nano_aiu),
                        e.text,
                        int(e.text_truncated),
                        js_stringify(e.tool_calls),
                        e.args,
                        int(e.args_truncated),
                        e.result,
                        int(e.result_truncated),
                        e.error,
                    ),
                )
            for s in c.skills:
                db.execute(ins_skill, (c.turn_id, s.name, s.version if s.version is not None else "", s.path))

    with_transaction(db, write)


def _skill_from_json(v: Any) -> SkillUse | None:
    if not isinstance(v, dict):
        return None
    return SkillUse(name=str(v.get("name")), version=v.get("version"), path=v.get("path"))


def _content_from_row(r: dict[str, Any]) -> TurnContent:
    skills = [s for s in (_skill_from_json(x) for x in _parse_json(r["skills_json"], []) or []) if s is not None]
    return TurnContent(
        turn_id=str(r["turn_id"]),
        user_prompt=_str(r["user_prompt"]),
        user_prompt_truncated=_bool(r["user_prompt_truncated"]),
        final_answer=_str(r["final_answer"]),
        final_answer_truncated=_bool(r["final_answer_truncated"]),
        error=_str(r["error"]),
        skills=skills,
        feedback_stats=_parse_json(r["feedback_json"], None),
    )


def _event_from_row(r: dict[str, Any]) -> TurnEvent:
    return TurnEvent(
        turn_id=str(r["turn_id"]),
        seq=int(r["seq"]),
        run_id=str(r["run_id"]),
        trace_id=str(r["trace_id"]),
        kind="llm" if r["kind"] == "llm" else "tool",
        name=str(r["name"]),
        started_at=_str(r["started_at"]),
        duration_ms=_int(r["duration_ms"]),
        tokens_in=_int(r["tokens_in"]),
        tokens_out=_int(r["tokens_out"]),
        nano_aiu=_int(r["nano_aiu"]),
        text=_str(r["text"]),
        text_truncated=_bool(r["text_truncated"]),
        tool_calls=_parse_json(r["tool_calls"], []),
        args=_str(r["args"]),
        args_truncated=_bool(r["args_truncated"]),
        result=_str(r["result"]),
        result_truncated=_bool(r["result_truncated"]),
        error=_str(r["error"]),
    )


def _unique(ids: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(ids))


def get_turn_contents(db: sqlite3.Connection, turn_ids: Iterable[str]) -> dict[str, TurnContent]:
    """Content of the given turns (missing turns are simply absent from the dict)."""
    out: dict[str, TurnContent] = {}
    for turn_id in _unique(turn_ids):
        rows = _rows(db, "SELECT * FROM turn_content WHERE turn_id = ?", (turn_id,))
        if rows:
            out[turn_id] = _content_from_row(rows[0])
    return out


def get_turn_events(db: sqlite3.Connection, turn_ids: Iterable[str]) -> dict[str, list[TurnEvent]]:
    """Agent steps of the given turns, in order."""
    out: dict[str, list[TurnEvent]] = {}
    for turn_id in _unique(turn_ids):
        rows = _rows(db, "SELECT * FROM turn_events WHERE turn_id = ? ORDER BY seq", (turn_id,))
        if rows:
            out[turn_id] = [_event_from_row(r) for r in rows]
    return out


@dataclass
class SkillUsageRow:
    turn_id: str
    skill: str
    version: str | None
    path: str | None


def list_skill_usage(db: sqlite3.Connection) -> list[SkillUsageRow]:
    rows = _rows(db, "SELECT turn_id, skill, version, path FROM skill_usage ORDER BY skill, version, turn_id")
    return [
        SkillUsageRow(
            turn_id=str(r["turn_id"]),
            skill=str(r["skill"]),
            version=str(r["version"]) if r["version"] else None,
            path=_str(r["path"]),
        )
        for r in rows
    ]


@dataclass
class ContentFlags:
    captured: bool
    error: bool


def list_content_flags(db: sqlite3.Connection) -> dict[str, ContentFlags]:
    """Per-turn flags for analytics: captured content and error."""
    rows = _rows(
        db,
        "SELECT turn_id, user_prompt IS NOT NULL OR final_answer IS NOT NULL AS captured, "
        "error IS NOT NULL AS err FROM turn_content",
    )
    return {str(r["turn_id"]): ContentFlags(captured=_bool(r["captured"]), error=_bool(r["err"])) for r in rows}


@dataclass
class ContentStats:
    turns_with_content: int
    events: int
    skill_uses: int
    skills: int
    last_captured_at: str | None


def content_stats(db: sqlite3.Connection) -> ContentStats:
    c = _rows(
        db,
        "SELECT COUNT(*) AS n, MAX(captured_at) AS last FROM turn_content "
        "WHERE user_prompt IS NOT NULL OR final_answer IS NOT NULL",
    )[0]
    e = _rows(db, "SELECT COUNT(*) AS n FROM turn_events")[0]
    s = _rows(db, "SELECT COUNT(DISTINCT turn_id) AS uses, COUNT(DISTINCT skill) AS skills FROM skill_usage")[0]
    return ContentStats(
        turns_with_content=int(c["n"]),
        events=int(e["n"]),
        skill_uses=int(s["uses"]),
        skills=int(s["skills"]),
        last_captured_at=str(c["last"]) if c["last"] else None,
    )
