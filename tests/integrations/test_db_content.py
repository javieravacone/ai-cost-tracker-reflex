"""Port of src/lib/db/content.test.ts."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from bis_core.db import SCHEMA_VERSION, delete_manual_assignment, open_db, reset_db, upsert_turns
from bis_core.db.content import (
    ContentFlags,
    SkillUsageRow,
    content_stats,
    get_turn_contents,
    get_turn_events,
    list_content_flags,
    list_skill_usage,
    save_turn_content,
)
from bis_core.types import SkillUse, Turn, TurnContent, TurnEvent


def turn(turn_id: str) -> Turn:
    return Turn(
        id=turn_id,
        trace_id=turn_id,
        conversation_id="c",
        started_at="2026-10-21T07:00:00.000Z",
        ended_at=None,
        user_name=None,
        team_id=None,
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
        llm_calls=0,
        tool_calls=0,
        copilot_nano_aiu=None,
        copilot_usage_coverage=None,
        source="langsmith",
    )


def content(turn_id: str, **over: Any) -> TurnContent:
    base = TurnContent(
        turn_id=turn_id,
        user_prompt="hi",
        user_prompt_truncated=False,
        final_answer="hello",
        final_answer_truncated=False,
        error=None,
        skills=[SkillUse(name="guide", version="abcd1234", path="/r/.github/skills/guide/SKILL.md")],
        feedback_stats=None,
    )
    return replace(base, **over)


def event(turn_id: str, seq: int, **over: Any) -> TurnEvent:
    base = TurnEvent(
        turn_id=turn_id,
        seq=seq,
        run_id=f"{turn_id}-{seq}",
        trace_id=turn_id,
        kind="tool",
        name="read_file",
        started_at=None,
        duration_ms=12,
        tokens_in=None,
        tokens_out=None,
        nano_aiu=None,
        text=None,
        text_truncated=False,
        tool_calls=[],
        args='{"filePath":"/a"}',
        args_truncated=False,
        result="x",
        result_truncated=True,
        error=None,
    )
    return replace(base, **over)


@pytest.fixture
def db() -> Iterator[sqlite3.Connection]:
    conn = open_db(":memory:")
    upsert_turns(conn, [turn("t1"), turn("t2")])
    yield conn
    conn.close()


def test_round_trips_content_ordered_events_and_skill_usage(db: sqlite3.Connection) -> None:
    save_turn_content(
        db,
        [content("t1")],
        [event("t1", 1, kind="llm", name="chat m", tool_calls=["read_file"], tokens_in=5), event("t1", 0)],
    )
    assert get_turn_contents(db, ["t1", "t2"])["t1"] == content("t1")
    assert len(get_turn_contents(db, ["t2"])) == 0
    ev = get_turn_events(db, ["t1"])["t1"]
    assert [e.seq for e in ev] == [0, 1]
    assert ev[0] == event("t1", 0)
    assert (ev[1].kind, ev[1].tool_calls, ev[1].tokens_in) == ("llm", ["read_file"], 5)
    assert list_skill_usage(db) == [
        SkillUsageRow(turn_id="t1", skill="guide", version="abcd1234", path="/r/.github/skills/guide/SKILL.md")
    ]


def test_writes_json_columns_exactly_like_the_ts_app(db: sqlite3.Connection) -> None:
    save_turn_content(db, [content("t1", feedback_stats={"thumbs": 1.0})], [event("t1", 0, tool_calls=["a", "b"])])
    row = db.execute("SELECT skills_json, feedback_json FROM turn_content").fetchone()
    assert tuple(row) == (
        '[{"name":"guide","version":"abcd1234","path":"/r/.github/skills/guide/SKILL.md"}]',
        '{"thumbs":1}',
    )
    assert db.execute("SELECT tool_calls FROM turn_events").fetchone()[0] == '["a","b"]'


def test_re_saving_a_turn_replaces_its_events_and_skills(db: sqlite3.Connection) -> None:
    save_turn_content(db, [content("t1")], [event("t1", 0), event("t1", 1)])
    save_turn_content(
        db, [content("t1", skills=[SkillUse(name="other", version=None, path=None)], error="boom")], [event("t1", 0)]
    )
    assert len(get_turn_events(db, ["t1"])["t1"]) == 1
    assert list_skill_usage(db) == [SkillUsageRow(turn_id="t1", skill="other", version=None, path=None)]
    assert list_content_flags(db)["t1"] == ContentFlags(captured=True, error=True)


def test_counts_only_turns_with_real_captured_text_cascades_and_wipes_on_reset(db: sqlite3.Connection) -> None:
    save_turn_content(
        db, [content("t1"), content("t2", user_prompt=None, final_answer=None, skills=[])], [event("t2", 0)]
    )
    s = content_stats(db)
    assert (s.turns_with_content, s.events, s.skill_uses, s.skills) == (1, 1, 1, 1)
    db.execute("DELETE FROM turns WHERE id = 't1'")
    assert list_skill_usage(db) == []
    delete_manual_assignment(db, "t2")
    reset_db(db)
    s = content_stats(db)
    assert (s.turns_with_content, s.events, s.skill_uses) == (0, 0, 0)


def test_adds_the_v3_tables_to_an_existing_v2_database_without_touching_its_rows(tmp_path: Path) -> None:
    file = tmp_path / "app.db"
    a = open_db(str(file))
    upsert_turns(a, [turn("keep")])
    a.executescript("DROP TABLE skill_usage; DROP TABLE turn_events; DROP TABLE turn_content; PRAGMA user_version = 2;")
    a.close()
    b = open_db(str(file))
    assert b.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    assert SCHEMA_VERSION == 3
    save_turn_content(b, [content("keep")], [])
    assert get_turn_contents(b, ["keep"])["keep"].user_prompt == "hi"
    b.close()
