"""Port of src/lib/db/db.test.ts."""

from __future__ import annotations

import os
import sqlite3
from dataclasses import replace

import pytest

from bis_core.db import (
    SCHEMA_VERSION,
    TABLES,
    close_db,
    delete_manual_assignment,
    get_db,
    get_sync_state,
    get_turn,
    list_issues,
    list_manual_assignments,
    list_members,
    list_model_prices,
    list_projects,
    list_pull_requests,
    list_repo_mappings,
    list_seat_plans,
    list_teams,
    list_turns,
    list_turns_by_conversation,
    open_db,
    reset_db,
    set_manual_assignment,
    set_sync_state,
    upsert_issues,
    upsert_members,
    upsert_model_prices,
    upsert_projects,
    upsert_pull_requests,
    upsert_repo_mappings,
    upsert_seat_plans,
    upsert_teams,
    upsert_turns,
    with_transaction,
)
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


def turn(**over) -> Turn:
    base = dict(
        id="t1",
        trace_id="trace-1",
        conversation_id="conv-1",
        started_at="2026-10-01T10:00:00.000Z",
        ended_at="2026-10-01T10:00:42.000Z",
        user_name="ana.ruiz",
        team_id="platform",
        project_hint=None,
        repo_url="https://github.com/acme-labs/atlas-api.git",
        branch="feat/12-login",
        commit_sha="a" * 40,
        github_org="acme-labs",
        agent_name="GitHub Copilot",
        model="claude-sonnet-4.5",
        input_tokens=52000,
        output_tokens=1800,
        cache_read_tokens=38000,
        cache_creation_tokens=1200,
        reasoning_tokens=0,
        llm_calls=4,
        tool_calls=7,
        copilot_nano_aiu=280_880_000,
        copilot_usage_coverage=1,
        source="seed",
    )
    base.update(over)
    return Turn(**base)


# The turns and seat_plans tables as created by schema v1, before AI credits.
V1_TURNS_AND_PLANS = """
CREATE TABLE turns (
  id TEXT PRIMARY KEY, trace_id TEXT NOT NULL, conversation_id TEXT, started_at TEXT NOT NULL,
  ended_at TEXT, user_name TEXT, team_id TEXT, project_hint TEXT, repo_url TEXT, branch TEXT,
  commit_sha TEXT, github_org TEXT, agent_name TEXT, model TEXT,
  input_tokens INTEGER NOT NULL DEFAULT 0, output_tokens INTEGER NOT NULL DEFAULT 0,
  cache_read_tokens INTEGER NOT NULL DEFAULT 0, cache_creation_tokens INTEGER NOT NULL DEFAULT 0,
  reasoning_tokens INTEGER NOT NULL DEFAULT 0, llm_calls INTEGER NOT NULL DEFAULT 0,
  tool_calls INTEGER NOT NULL DEFAULT 0,
  source TEXT NOT NULL CHECK (source IN ('langsmith', 'seed'))
);
CREATE TABLE seat_plans (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, monthly_price_usd REAL NOT NULL,
  included_premium_requests INTEGER NOT NULL, overage_per_premium_request_usd REAL NOT NULL
);"""


@pytest.fixture
def db():
    conn = open_db(":memory:")
    yield conn
    conn.close()


# --- schema ----------------------------------------------------------------------------------


def test_migration_is_idempotent_and_enables_foreign_keys(tmp_path):
    file = tmp_path / "app.db"
    a = open_db(file)
    upsert_teams(a, [Team(id="platform", name="Platform")])
    a.close()
    b = open_db(file)
    assert list_teams(b) == [Team(id="platform", name="Platform")]
    assert b.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert b.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    b.close()


def test_adds_ai_credit_columns_to_a_v1_database(tmp_path):
    file = tmp_path / "app.db"
    old = sqlite3.connect(file)
    old.executescript(V1_TURNS_AND_PLANS)
    old.execute(
        "INSERT INTO turns (id, trace_id, started_at, model, input_tokens, source) "
        "VALUES ('old', 'tr', '2026-10-01T00:00:00.000Z', 'gpt-4.1', 10, 'seed')"
    )
    old.execute("INSERT INTO seat_plans VALUES ('biz', 'Business', 19, 300, 0.04)")
    old.execute("INSERT INTO seat_plans VALUES ('copilot-enterprise', 'Copilot Enterprise', 39, 1000, 0.04)")
    old.execute("PRAGMA user_version = 1")
    old.commit()
    old.close()

    a = open_db(file)

    def cols(t: str) -> list[str]:
        return [r[1] for r in a.execute(f"PRAGMA table_info({t})").fetchall()]

    assert {"copilot_nano_aiu", "copilot_usage_coverage"} <= set(cols("turns"))
    assert "included_ai_credits" in cols("seat_plans")
    assert a.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    old_turn = get_turn(a, "old")
    assert old_turn is not None
    assert (old_turn.input_tokens, old_turn.copilot_nano_aiu, old_turn.copilot_usage_coverage) == (10, None, None)
    # Unknown plan ids keep 0; the plan ids the POC ships get their documented allowance.
    assert list_seat_plans(a) == [
        SeatPlan(
            id="biz",
            name="Business",
            monthly_price_usd=19,
            included_premium_requests=300,
            overage_per_premium_request_usd=0.04,
            included_ai_credits=0,
        ),
        SeatPlan(
            id="copilot-enterprise",
            name="Copilot Enterprise",
            monthly_price_usd=39,
            included_premium_requests=1000,
            overage_per_premium_request_usd=0.04,
            included_ai_credits=3900,
        ),
    ]
    upsert_turns(a, [turn(id="new", copilot_nano_aiu=5e9)])
    a.execute("UPDATE seat_plans SET included_ai_credits = 5 WHERE id = 'copilot-enterprise'")
    a.close()

    # Re-opening an already migrated file is a no-op (no second back-fill).
    b = open_db(file)
    assert list_seat_plans(b)[1].included_ai_credits == 5
    new_turn = get_turn(b, "new")
    assert new_turn is not None and new_turn.copilot_nano_aiu == 5_000_000_000
    assert isinstance(new_turn.copilot_nano_aiu, int)
    assert len(list_turns(b)) == 2
    b.close()


def test_creates_the_turns_indexes(db):
    names = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type = 'index' AND tbl_name = 'turns'")}
    assert {"idx_turns_started_at", "idx_turns_conversation_id", "idx_turns_user_name"} <= names


def test_creates_the_v3_content_tables(db):
    tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert {"turn_content", "turn_events", "skill_usage"} <= tables
    assert db.execute("PRAGMA user_version").fetchone()[0] == 3


# --- turns -----------------------------------------------------------------------------------


def test_roundtrips_a_turn_with_all_fields(db):
    t = turn()
    assert upsert_turns(db, [t]) == 1
    assert get_turn(db, "t1") == t
    assert get_turn(db, "missing") is None


def test_roundtrips_nullable_fields_as_none(db):
    t = turn(
        conversation_id=None,
        ended_at=None,
        user_name=None,
        team_id=None,
        repo_url=None,
        branch=None,
        commit_sha=None,
        github_org=None,
        agent_name=None,
        model=None,
        copilot_nano_aiu=None,
        copilot_usage_coverage=None,
        source="langsmith",
    )
    upsert_turns(db, [t])
    assert get_turn(db, "t1") == t


def test_keeps_copilot_usage_none_distinct_from_0_and_stores_big_values_exactly(db):
    big = 2**31 * 7 + 12_345  # > int32, well below 2^53
    upsert_turns(
        db,
        [
            turn(id="a", copilot_nano_aiu=None, copilot_usage_coverage=0),
            turn(id="b", copilot_nano_aiu=0, copilot_usage_coverage=1),
            turn(id="c", copilot_nano_aiu=big, copilot_usage_coverage=0.5),
        ],
    )
    a, b, c = get_turn(db, "a"), get_turn(db, "b"), get_turn(db, "c")
    assert (a.copilot_nano_aiu, a.copilot_usage_coverage) == (None, 0)
    assert (b.copilot_nano_aiu, b.copilot_usage_coverage) == (0, 1)
    assert (c.copilot_nano_aiu, c.copilot_usage_coverage) == (big, 0.5)
    assert db.execute("SELECT typeof(copilot_nano_aiu) AS t FROM turns WHERE id = 'c'").fetchone()[0] == "integer"


def test_upsert_is_idempotent_and_updates_on_conflict(db):
    upsert_turns(db, [turn(), turn(id="t2")])
    upsert_turns(db, [turn(), turn(id="t2")])
    assert len(list_turns(db)) == 2
    upsert_turns(db, [turn(output_tokens=999, model="gpt-5")])
    t1 = get_turn(db, "t1")
    assert t1.output_tokens == 999
    assert t1.model == "gpt-5"
    assert len(list_turns(db)) == 2


def test_returns_0_and_does_nothing_for_an_empty_list(db):
    assert upsert_turns(db, []) == 0
    assert list_turns(db) == []


def test_list_turns_orders_and_filters_from_inclusive_to_exclusive(db):
    upsert_turns(
        db,
        [
            turn(id="c", started_at="2026-10-03T09:00:00.000Z"),
            turn(id="a", started_at="2026-10-01T09:00:00.000Z"),
            turn(id="b", started_at="2026-10-02T09:00:00.000Z"),
        ],
    )
    ids = lambda ts: [t.id for t in ts]  # noqa: E731
    assert ids(list_turns(db)) == ["a", "b", "c"]
    assert ids(list_turns(db, None, None)) == ["a", "b", "c"]
    assert ids(list_turns(db, from_="2026-10-02T09:00:00.000Z")) == ["b", "c"]
    assert ids(list_turns(db, to="2026-10-02T09:00:00.000Z")) == ["a"]
    assert ids(list_turns(db, "2026-10-01T12:00:00.000Z", "2026-10-03T00:00:00.000Z")) == ["b"]


def test_lists_turns_by_conversation_in_time_order(db):
    upsert_turns(
        db,
        [
            turn(id="x2", conversation_id="x", started_at="2026-10-01T10:05:00.000Z"),
            turn(id="x1", conversation_id="x", started_at="2026-10-01T10:00:00.000Z"),
            turn(id="y1", conversation_id="y"),
        ],
    )
    assert [t.id for t in list_turns_by_conversation(db, "x")] == ["x1", "x2"]
    assert list_turns_by_conversation(db, "none") == []


def test_rolls_back_the_whole_batch_when_one_row_is_invalid(db):
    bad = turn(id="bad", source="other")
    with pytest.raises(sqlite3.IntegrityError):
        upsert_turns(db, [turn(id="ok"), bad])
    assert list_turns(db) == []


# --- reference entities ----------------------------------------------------------------------


def test_roundtrips_and_upserts_teams_and_projects(db):
    upsert_teams(db, [Team(id="web", name="Web"), Team(id="data", name="Data Engineering")])
    assert upsert_teams(db, [Team(id="web", name="Web Experience")]) == 1
    assert list_teams(db) == [Team(id="data", name="Data Engineering"), Team(id="web", name="Web Experience")]

    upsert_projects(db, [Project(id="atlas", name="Atlas")])
    upsert_projects(db, [Project(id="atlas", name="Atlas v2"), Project(id="nimbus", name="Nimbus")])
    assert list_projects(db) == [Project(id="atlas", name="Atlas v2"), Project(id="nimbus", name="Nimbus")]


def test_stores_repo_mapping_slugs_lowercase_and_updates_the_project(db):
    upsert_repo_mappings(db, [RepoMapping(repo="Acme-Labs/Atlas-API", project_id="atlas")])
    upsert_repo_mappings(db, [RepoMapping(repo="acme-labs/atlas-api", project_id="nimbus")])
    assert list_repo_mappings(db) == [RepoMapping(repo="acme-labs/atlas-api", project_id="nimbus")]


def test_roundtrips_and_upserts_members(db):
    m = Member(user_name="ana.ruiz", display_name="Ana Ruiz", team_id="platform", seat_plan_id="copilot-business")
    upsert_members(db, [m])
    upsert_members(db, [replace(m, seat_plan_id="copilot-enterprise")])
    assert list_members(db) == [replace(m, seat_plan_id="copilot-enterprise")]


def test_roundtrips_issues_keyed_by_repo_and_number(db):
    open_issue = Issue(
        repo="Acme-Labs/atlas-api",
        number=12,
        title="Login fails",
        state="open",
        url="https://github.com/acme-labs/atlas-api/issues/12",
        created_at="2026-09-01T00:00:00.000Z",
        closed_at=None,
    )
    same_number_other_repo = replace(open_issue, repo="acme-labs/atlas-web")
    upsert_issues(db, [open_issue, same_number_other_repo])
    upsert_issues(db, [replace(open_issue, state="closed", closed_at="2026-09-05T00:00:00.000Z")])
    assert list_issues(db) == [
        replace(open_issue, repo="acme-labs/atlas-api", state="closed", closed_at="2026-09-05T00:00:00.000Z"),
        same_number_other_repo,
    ]


def test_roundtrips_pull_requests_with_json_array_columns(db):
    pr = PullRequest(
        repo="acme-labs/atlas-api",
        number=45,
        title="Fix login",
        state="open",
        head_branch="fix/12-login",
        url="https://github.com/acme-labs/atlas-api/pull/45",
        linked_issues=[12, 13],
        commit_shas=["a" * 40, "b" * 40],
        created_at="2026-09-02T00:00:00.000Z",
        merged_at=None,
    )
    upsert_pull_requests(db, [pr, replace(pr, number=46, linked_issues=[], commit_shas=[])])
    upsert_pull_requests(
        db, [replace(pr, state="merged", merged_at="2026-09-04T00:00:00.000Z", commit_shas=["c" * 40])]
    )
    assert list_pull_requests(db) == [
        replace(pr, state="merged", merged_at="2026-09-04T00:00:00.000Z", commit_shas=["c" * 40]),
        replace(pr, number=46, linked_issues=[], commit_shas=[]),
    ]
    # Stored as compact JSON, like JSON.stringify.
    assert db.execute("SELECT linked_issues FROM pull_requests WHERE number = 45").fetchone()[0] == "[12,13]"


def test_roundtrips_model_prices_with_real_values(db):
    p = ModelPrice(
        model="claude-sonnet-4*",
        input_per_mtok=3,
        output_per_mtok=15,
        cache_read_per_mtok=0.3,
        cache_write_per_mtok=3.75,
        premium_multiplier=1,
    )
    upsert_model_prices(db, [p, replace(p, model="gpt-5-mini", premium_multiplier=0.33)])
    upsert_model_prices(db, [replace(p, output_per_mtok=16.5)])
    assert list_model_prices(db) == [
        replace(p, output_per_mtok=16.5),
        replace(p, model="gpt-5-mini", premium_multiplier=0.33),
    ]


def test_roundtrips_seat_plans(db):
    plan = SeatPlan(
        id="copilot-business",
        name="Copilot Business",
        monthly_price_usd=19,
        included_premium_requests=300,
        overage_per_premium_request_usd=0.04,
        included_ai_credits=1900,
    )
    upsert_seat_plans(db, [plan])
    upsert_seat_plans(db, [replace(plan, monthly_price_usd=21.5)])
    assert list_seat_plans(db) == [replace(plan, monthly_price_usd=21.5)]


# --- manual assignments ----------------------------------------------------------------------

ASSIGNMENT = ManualAssignment(turn_id="t1", repo="Acme-Labs/atlas-api", issue_number=12, pr_number=None, note="hotfix on main")


def test_sets_replaces_and_deletes_one_assignment_per_turn(db):
    upsert_turns(db, [turn(), turn(id="t2")])
    set_manual_assignment(db, ASSIGNMENT)
    assert list_manual_assignments(db) == [replace(ASSIGNMENT, repo="acme-labs/atlas-api")]

    set_manual_assignment(db, replace(ASSIGNMENT, issue_number=None, pr_number=45, note=None))
    assert list_manual_assignments(db) == [
        ManualAssignment(turn_id="t1", repo="acme-labs/atlas-api", issue_number=None, pr_number=45, note=None)
    ]

    set_manual_assignment(db, replace(ASSIGNMENT, turn_id="t2"))
    assert len(list_manual_assignments(db)) == 2

    delete_manual_assignment(db, "t1")
    assert [x.turn_id for x in list_manual_assignments(db)] == ["t2"]
    delete_manual_assignment(db, "does-not-exist")
    assert len(list_manual_assignments(db)) == 1


def test_manual_assignment_requires_the_turn_to_exist(db):
    with pytest.raises(sqlite3.IntegrityError):
        set_manual_assignment(db, replace(ASSIGNMENT, turn_id="ghost"))


# --- sync state ------------------------------------------------------------------------------


def test_sync_state_gets_none_when_missing_sets_and_overwrites(db):
    assert get_sync_state(db, "langsmith.cursor") is None
    set_sync_state(db, "langsmith.cursor", "2026-10-01T00:00:00Z")
    set_sync_state(db, "github.cursor", "abc")
    set_sync_state(db, "langsmith.cursor", "2026-10-02T00:00:00Z")
    assert get_sync_state(db, "langsmith.cursor") == "2026-10-02T00:00:00Z"
    assert get_sync_state(db, "github.cursor") == "abc"
    updated = db.execute("SELECT updated_at FROM sync_state WHERE key = 'github.cursor'").fetchone()[0]
    assert len(updated) == 24 and updated.endswith("Z")  # toISOString format


# --- with_transaction ------------------------------------------------------------------------


def test_with_transaction_supports_nesting_and_rolls_back_inner_failures_only(db):
    def outer() -> None:
        upsert_teams(db, [Team(id="a", name="A")])

        def inner() -> None:
            upsert_teams(db, [Team(id="b", name="B")])
            raise RuntimeError("boom")

        with pytest.raises(RuntimeError, match="boom"):
            with_transaction(db, inner)

    with_transaction(db, outer)
    assert [t.id for t in list_teams(db)] == ["a"]


# --- reset_db --------------------------------------------------------------------------------


def test_reset_db_deletes_every_row_but_keeps_the_schema_usable(db):
    upsert_turns(db, [turn()])
    upsert_teams(db, [Team(id="platform", name="Platform")])
    upsert_projects(db, [Project(id="atlas", name="Atlas")])
    upsert_repo_mappings(db, [RepoMapping(repo="acme-labs/atlas-api", project_id="atlas")])
    upsert_members(db, [Member(user_name="ana.ruiz", display_name="Ana", team_id="platform", seat_plan_id="x")])
    set_manual_assignment(
        db, ManualAssignment(turn_id="t1", repo="acme-labs/atlas-api", issue_number=1, pr_number=None, note=None)
    )
    set_sync_state(db, "k", "v")

    reset_db(db)

    for table in TABLES:
        assert db.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()[0] == 0
    assert get_sync_state(db, "k") is None
    upsert_turns(db, [turn()])
    assert len(list_turns(db)) == 1


# --- get_db ----------------------------------------------------------------------------------


def test_get_db_creates_the_parent_directory_and_returns_a_cached_singleton(tmp_path, monkeypatch):
    target = tmp_path / "nested" / "deeper" / "app.db"
    monkeypatch.setenv("DB_PATH", str(target))
    try:
        a = get_db()
        b = get_db()
        assert a is b
        assert os.path.exists(target)
        upsert_teams(a, [Team(id="web", name="Web")])
        close_db()
        assert list_teams(get_db()) == [Team(id="web", name="Web")]
    finally:
        close_db()
