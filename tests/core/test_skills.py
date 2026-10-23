"""Port of src/lib/report/skills.test.ts, plus the DB reads used by the skills page."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from bis_core.db import open_db, upsert_turns
from bis_core.report.skills import (
    ContentFlag,
    SkillsReport,
    SkillUsageInput,
    list_content_flags,
    list_skill_usage,
    load_skills_report,
    skills_report,
)
from bis_core.types import Turn

approx = pytest.approx
_UNSET = object()


def row(id: str, team=_UNSET, user="ana", conv="c1", at="2026-10-21T07:00:00.000Z", credits=_UNSET, tools=0):
    credits = 1 if credits is _UNSET else credits
    team = "data" if team is _UNSET else team
    return SimpleNamespace(
        turn=SimpleNamespace(id=id, started_at=at, tool_calls=tools),
        attribution=SimpleNamespace(team_id=team, user_name=user),
        cost=SimpleNamespace(ai_credits=credits, ai_credits_usd=None if credits is None else credits / 100),
        team_name="Data" if team == "data" else team,
        conversation_key=conv,
    )


def flags(entries):
    return {i: ContentFlag(captured=f.get("captured", True), error=f.get("error", False)) for i, f in entries}


ROWS = [
    row("s1", credits=2, tools=4, at="2026-10-20T10:00:00.000Z", conv="c1"),
    row("s2", credits=4, tools=2, at="2026-10-21T10:00:00.000Z", conv="c2", user="bo"),
    row("s3", credits=None, tools=6, at="2026-10-21T11:00:00.000Z", conv="c2", user="bo"),
    row("b1", credits=10, tools=10),  # same team, captured, no skill -> baseline
    row("b2", credits=6, tools=0),  # baseline, with error
    row("x1", credits=99, team="other"),  # other team: not in baseline
    row("n1", credits=50),  # no captured content: unknown skill use, excluded
]
F = flags([("s1", {}), ("s2", {}), ("s3", {"error": True}), ("b1", {}), ("b2", {"error": True}), ("x1", {})])
USAGE = [
    SkillUsageInput(turn_id="s1", skill="guide", version="aaaa1111"),
    SkillUsageInput(turn_id="s2", skill="guide", version="bbbb2222"),
    SkillUsageInput(turn_id="s3", skill="guide", version="bbbb2222"),
    SkillUsageInput(turn_id="zz", skill="guide", version="aaaa1111"),  # outside the period
]
R = skills_report(ROWS, USAGE, F)
G = R.skills[0]


def test_counts_captured_turns_and_turns_with_skills():
    assert (R.captured_turns, R.turns_with_skills) == (6, 3)
    assert [s.name for s in R.skills] == ["guide"]


def test_aggregates_turns_sessions_people_cost_tool_calls_and_errors():
    assert (G.turns, G.sessions, G.people, G.teams, G.credits_per_turn, G.usd_per_turn, G.tool_calls_per_turn) == (
        3,
        2,
        2,
        ["Data"],
        3,
        0.03,
        4,
    )
    assert G.error_rate == approx(1 / 3)
    assert G.first_seen == "2026-10-20T10:00:00.000Z"
    assert G.last_seen == "2026-10-21T11:00:00.000Z"


def test_compares_against_same_team_captured_turns_without_any_skill():
    b = G.baseline
    assert (b.turns, b.credits_per_turn, b.tool_calls_per_turn, b.error_rate) == (2, 8, 5, 0.5)


def test_splits_by_version_newest_first_with_first_last_seen():
    assert [(v.version, v.turns, v.credits_per_turn, v.first_seen[:10]) for v in G.versions] == [
        ("bbbb2222", 2, 4, "2026-10-21"),
        ("aaaa1111", 1, 2, "2026-10-20"),
    ]


def test_is_empty_without_captured_content():
    assert skills_report(ROWS, [], {}) == SkillsReport(captured_turns=0, turns_with_skills=0, skills=[])


def test_reads_skill_usage_and_content_flags_from_the_v3_tables():
    db = open_db(":memory:")
    base = dict(
        trace_id="tr",
        conversation_id=None,
        started_at="2026-10-21T07:00:00.000Z",
        ended_at=None,
        user_name="ana",
        team_id="data",
        project_hint=None,
        repo_url=None,
        branch=None,
        commit_sha=None,
        github_org=None,
        agent_name=None,
        model=None,
        input_tokens=0,
        output_tokens=0,
        cache_read_tokens=0,
        cache_creation_tokens=0,
        reasoning_tokens=0,
        llm_calls=1,
        tool_calls=0,
        copilot_nano_aiu=None,
        copilot_usage_coverage=None,
        source="langsmith",
    )
    upsert_turns(db, [Turn(id="a", **base), Turn(id="b", **base)])
    db.execute(
        "INSERT INTO turn_content (turn_id, user_prompt, final_answer, error, captured_at) VALUES "
        "('a', 'hi', NULL, NULL, '2026-10-21T08:00:00.000Z'), ('b', NULL, NULL, 'boom', '2026-10-21T08:00:00.000Z')"
    )
    db.execute(
        "INSERT INTO skill_usage (turn_id, skill, version, path) VALUES ('a', 'guide', '', NULL), ('a', 'guide', 'aaaa1111', '/x/SKILL.md')"
    )
    assert list_skill_usage(db) == [
        SkillUsageInput(turn_id="a", skill="guide", version=None, path=None),
        SkillUsageInput(turn_id="a", skill="guide", version="aaaa1111", path="/x/SKILL.md"),
    ]
    assert list_content_flags(db) == {
        "a": ContentFlag(captured=True, error=False),
        "b": ContentFlag(captured=False, error=True),
    }
    rows = [row("a"), row("b")]
    r = load_skills_report(db, rows)
    assert (r.captured_turns, r.turns_with_skills, [v.version for v in r.skills[0].versions]) == (1, 1, [None, "aaaa1111"])
    db.close()
