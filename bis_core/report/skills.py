"""Skill analytics (port of src/lib/report/skills.ts).

Which skills Copilot read, how often, at what cost and quality, per version, compared with
turns of the same teams that used no skill. Only turns with captured content count: without
content we can't know whether a skill was read.

`skills_report` is pure. `list_skill_usage`, `list_content_flags` and `load_skills_report` read
the v3 content tables (`skill_usage`, `turn_content`) directly with SQL, mirroring
`listSkillUsage` / `listContentFlags` from src/lib/db/content.ts, so this module does not depend
on the integrations' content repository.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass
from functools import cmp_to_key
from typing import Any

from bis_core._js import first_nonzero, locale_compare
from bis_core.report import NONE_KEY

__all__ = [
    "ContentFlag",
    "SkillStat",
    "SkillUsageInput",
    "SkillVersionStat",
    "SkillsReport",
    "TurnGroupStats",
    "group_stats",
    "list_content_flags",
    "list_skill_usage",
    "load_skills_report",
    "skills_report",
]


@dataclass
class SkillUsageInput:
    turn_id: str
    skill: str
    version: str | None
    path: str | None = None


@dataclass
class ContentFlag:
    captured: bool
    error: bool


@dataclass(kw_only=True)
class TurnGroupStats:
    turns: int
    # Mean AI credits per turn over turns with credit data; None when none has it.
    credits_per_turn: float | None
    usd_per_turn: float | None
    tool_calls_per_turn: float | None
    # Share 0..1 of turns that reported an error.
    error_rate: float | None


@dataclass(kw_only=True)
class SkillVersionStat(TurnGroupStats):
    version: str | None
    first_seen: str
    last_seen: str


@dataclass(kw_only=True)
class SkillStat(TurnGroupStats):
    name: str
    sessions: int
    people: int
    teams: list[str]
    first_seen: str
    last_seen: str
    # Turns of the same teams, with captured content and no skill at all.
    baseline: TurnGroupStats
    versions: list[SkillVersionStat]


@dataclass
class SkillsReport:
    captured_turns: int  # turns in the period with captured content
    turns_with_skills: int  # captured turns that used at least one skill
    skills: list[SkillStat]


def _stats_fields(s: TurnGroupStats) -> dict[str, Any]:
    return {
        "turns": s.turns,
        "credits_per_turn": s.credits_per_turn,
        "usd_per_turn": s.usd_per_turn,
        "tool_calls_per_turn": s.tool_calls_per_turn,
        "error_rate": s.error_rate,
    }


def _flag(flags: Mapping[str, Any], turn_id: str) -> ContentFlag | None:
    f = flags.get(turn_id)
    if f is None or isinstance(f, ContentFlag):
        return f
    return ContentFlag(captured=bool(f.get("captured")), error=bool(f.get("error")))


def group_stats(rows: list[Any], flags: Mapping[str, Any]) -> TurnGroupStats:
    if not rows:
        return TurnGroupStats(turns=0, credits_per_turn=None, usd_per_turn=None, tool_calls_per_turn=None, error_rate=None)
    known = [r for r in rows if r.cost.ai_credits is not None]
    credits = 0.0
    usd = 0.0
    for r in known:
        credits += r.cost.ai_credits if r.cost.ai_credits is not None else 0
        usd += r.cost.ai_credits_usd if r.cost.ai_credits_usd is not None else 0
    tool_calls = 0
    for r in rows:
        tool_calls += r.turn.tool_calls
    errors = 0
    for r in rows:
        f = _flag(flags, r.turn.id)
        if f is not None and f.error:
            errors += 1
    return TurnGroupStats(
        turns=len(rows),
        credits_per_turn=credits / len(known) if known else None,
        usd_per_turn=usd / len(known) if known else None,
        tool_calls_per_turn=tool_calls / len(rows),
        error_rate=errors / len(rows),
    )


def _span(rows: list[Any]) -> dict[str, str]:
    starts = sorted(r.turn.started_at for r in rows)
    return {"first_seen": starts[0], "last_seen": starts[-1]}


def _team_key(r: Any) -> str:
    return r.attribution.team_id if r.attribution.team_id is not None else NONE_KEY


def skills_report(rows: list[Any], usage: list[Any], flags: Mapping[str, Any]) -> SkillsReport:
    by_id = {r.turn.id: r for r in rows}
    used: dict[str, dict[str | None, dict[str, None]]] = {}  # skill -> version -> ordered turn ids
    with_skill: dict[str, None] = {}
    for u in usage:
        turn_id = u.turn_id if not isinstance(u, Mapping) else u["turn_id"]
        skill = u.skill if not isinstance(u, Mapping) else u["skill"]
        version = u.version if not isinstance(u, Mapping) else u.get("version")
        if turn_id not in by_id:
            continue  # outside the period
        with_skill[turn_id] = None
        used.setdefault(skill, {}).setdefault(version, {})[turn_id] = None

    def is_captured(r: Any) -> bool:
        f = _flag(flags, r.turn.id)
        return bool(f is not None and f.captured) or r.turn.id in with_skill

    captured = [r for r in rows if is_captured(r)]
    no_skill = [r for r in captured if r.turn.id not in with_skill]

    skills: list[SkillStat] = []
    for name, versions in used.items():
        ids: dict[str, None] = {}
        for s in versions.values():
            for i in s:
                ids[i] = None
        skill_rows = sorted(
            (by_id[i] for i in ids),
            key=cmp_to_key(lambda a, b: locale_compare(a.turn.started_at, b.turn.started_at)),
        )
        teams = {_team_key(r) for r in skill_rows}
        version_stats: list[SkillVersionStat] = []
        for version, v_ids in versions.items():
            v_rows = [by_id[i] for i in v_ids]
            version_stats.append(SkillVersionStat(version=version, **_stats_fields(group_stats(v_rows, flags)), **_span(v_rows)))
        version_stats.sort(key=cmp_to_key(lambda a, b: locale_compare(b.last_seen, a.last_seen)))
        team_names = {
            (r.team_name if r.team_name is not None else r.attribution.team_id)
            for r in skill_rows
        }
        skills.append(
            SkillStat(
                name=name,
                **_stats_fields(group_stats(skill_rows, flags)),
                sessions=len({r.conversation_key for r in skill_rows}),
                people=len({r.attribution.user_name.lower() for r in skill_rows if r.attribution.user_name}),
                teams=sorted(t for t in team_names if t),
                **_span(skill_rows),
                baseline=group_stats([r for r in no_skill if _team_key(r) in teams], flags),
                versions=version_stats,
            )
        )
    skills.sort(key=cmp_to_key(lambda a, b: first_nonzero(b.turns - a.turns, locale_compare(a.name, b.name))))
    return SkillsReport(captured_turns=len(captured), turns_with_skills=len(with_skill), skills=skills)


# ---------------------------------------------------------------------------
# Reads (schema v3 content tables)


def list_skill_usage(db: sqlite3.Connection) -> list[SkillUsageInput]:
    """Every skill use, ordered by skill, version, turn (version '' -> None)."""
    rows = db.execute("SELECT turn_id, skill, version, path FROM skill_usage ORDER BY skill, version, turn_id").fetchall()
    return [
        SkillUsageInput(
            turn_id=str(r[0]),
            skill=str(r[1]),
            version=str(r[2]) if r[2] else None,
            path=None if r[3] is None else str(r[3]),
        )
        for r in rows
    ]


def list_content_flags(db: sqlite3.Connection) -> dict[str, ContentFlag]:
    """Per-turn flags for analytics: captured content and error."""
    rows = db.execute(
        "SELECT turn_id, user_prompt IS NOT NULL OR final_answer IS NOT NULL AS captured, error IS NOT NULL AS err FROM turn_content"
    ).fetchall()
    return {str(r[0]): ContentFlag(captured=int(r[1]) == 1, error=int(r[2]) == 1) for r in rows}


def load_skills_report(db: sqlite3.Connection, rows: list[Any]) -> SkillsReport:
    """`skills_report` over the report rows with usage and flags read from the database."""
    return skills_report(rows, list_skill_usage(db), list_content_flags(db))
