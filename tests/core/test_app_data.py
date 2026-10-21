"""Tests for bis_core.app_data (port of the pure helpers in src/app/_lib/data.ts).

The TS module has no unit tests; expected strings were checked against Node 24 (Intl,
URLSearchParams, encodeURIComponent, decodeURIComponent).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from bis_core.app_data import (
    LANGSMITH_PROJECT_ID_KEY,
    LANGSMITH_TENANT_ID_KEY,
    by_credits_desc,
    describe_period,
    get_period_report,
    group_signals,
    href_with,
    langsmith_ref,
    param,
    person_href,
    previous_period_credits,
    real_repos_by_project,
    safe_decode,
    team_href,
)
from bis_core.db import open_db, set_sync_state, upsert_members, upsert_repo_mappings, upsert_seat_plans, upsert_turns
from bis_core.report import NONE_KEY, PeriodRange, load_report, range_from_days
from bis_core.types import Member, RepoMapping, SeatPlan, Turn

NOW = 1_792_224_000_000  # 2026-10-17T08:00:00.000Z


def turn(id: str, **over) -> Turn:
    base = dict(
        id=id,
        trace_id=id,
        conversation_id=None,
        started_at="2026-10-16T10:00:00.000Z",
        ended_at=None,
        user_name="ana",
        team_id=None,
        project_hint=None,
        repo_url=None,
        branch=None,
        commit_sha=None,
        github_org=None,
        agent_name=None,
        model="mystery",
        input_tokens=0,
        output_tokens=0,
        cache_read_tokens=0,
        cache_creation_tokens=0,
        reasoning_tokens=0,
        llm_calls=1,
        tool_calls=0,
        copilot_nano_aiu=None,
        copilot_usage_coverage=None,
        source="seed",
    )
    base.update(over)
    return Turn(**base)


@pytest.fixture
def db():
    conn = open_db(":memory:")
    upsert_seat_plans(conn, [SeatPlan(id="biz", name="Business", monthly_price_usd=19, included_premium_requests=300, overage_per_premium_request_usd=0.04, included_ai_credits=1900)])
    upsert_members(conn, [Member(user_name="ana", display_name="Ana", team_id="data", seat_plan_id="biz")])
    upsert_turns(
        conn,
        [
            turn("now1", copilot_nano_aiu=5 * 10**9, source="langsmith"),
            turn("prev1", started_at="2026-10-05T10:00:00.000Z", copilot_nano_aiu=2 * 10**9),
            turn("prev2", started_at="2026-10-06T10:00:00.000Z"),
        ],
    )
    yield conn
    conn.close()


def test_param_takes_the_first_value_and_drops_empty_strings():
    assert param({"a": "x"}, "a") == "x"
    assert param({"a": ["y", "z"]}, "a") == "y"
    assert param({"a": ""}, "a") is None
    assert param({}, "a") is None


def test_href_with_drops_empty_values_and_the_default_days():
    assert href_with("/sesiones", {"days": 30, "team": "web"}) == "/sesiones?team=web"
    assert href_with("/sesiones", {"days": "7", "team": None, "user": ""}) == "/sesiones?days=7"
    assert href_with("/x", {"q": "a b~*&é/", "days": 7}) == "/x?q=a+b%7E*%26%C3%A9%2F&days=7"
    assert href_with("/", {}) == "/"


def test_team_and_person_hrefs_encode_the_id_and_keep_days():
    assert team_href("data", 30) == "/equipos/data"
    assert team_href("data eng", 7) == "/equipos/data%20eng?days=7"
    assert person_href("ana.ruiz ñ/(x)!*~'", 90) == "/personas/ana.ruiz%20%C3%B1%2F(x)!*~'?days=90"


def test_safe_decode_keeps_malformed_escapes():
    assert safe_decode("ana%20ruiz") == "ana ruiz"
    assert safe_decode("%E0%A4%A") == "%E0%A4%A"
    assert safe_decode("100%") == "100%"


def test_describe_period():
    p = PeriodRange(days=30, from_="2026-09-22T00:00:00.000Z", to="2026-10-22T00:00:00.000Z")
    assert describe_period(p) == "Last 30 days: Sep 22, 2026 – Oct 21, 2026 (UTC)"


def test_by_credits_desc_keeps_library_order_on_ties_and_none_last():
    items = [
        SimpleNamespace(key=NONE_KEY, ai_credits=99),
        SimpleNamespace(key="a", ai_credits=1),
        SimpleNamespace(key="b", ai_credits=5),
        SimpleNamespace(key="c", ai_credits=1),
    ]
    assert [x.key for x in by_credits_desc(items)] == ["b", "a", "c", NONE_KEY]


def test_group_signals_counts_unpriced_turns_and_real_groups(db):
    r = load_report(db)
    s = group_signals(r, lambda row: row.turn.id if row.turn.id != "prev2" else None)
    assert s.unpriced("now1") == 1
    assert s.unpriced(NONE_KEY) == 1
    assert s.unpriced("missing") == 0
    assert s.real("now1") is True
    assert s.real("prev1") is False


def test_period_report_and_previous_period_credits(db):
    data = get_period_report({"days": "7"}, db, NOW)
    assert data.period == range_from_days(7, NOW)
    assert [x.turn.id for x in data.report.rows] == ["now1"]
    assert data.db_empty is False
    assert data.now == NOW
    # the 7 days before Oct 11-17 hold prev1 (2 credits, known) and prev2 (unknown)
    prev = previous_period_credits(range_from_days(7, NOW), db)
    assert (prev.ai_credits, prev.turns, prev.credit_turns) == (2, 2, 1)
    assert previous_period_credits(range_from_days(30, NOW), db) is None


def test_langsmith_ref_and_real_repos(db, monkeypatch):
    monkeypatch.setenv("LANGSMITH_ENDPOINT", "https://eu.api.smith.langchain.com")
    set_sync_state(db, LANGSMITH_TENANT_ID_KEY, "org")
    set_sync_state(db, LANGSMITH_PROJECT_ID_KEY, "p")
    ref = langsmith_ref(db)
    assert (ref.endpoint, ref.tenant_id, ref.project_id) == ("https://eu.api.smith.langchain.com", "org", "p")
    upsert_repo_mappings(
        db,
        [
            RepoMapping(repo="acme-labs/atlas-api", project_id="atlas"),
            RepoMapping(repo="javieravacone/ai-cost-tracker", project_id="tracker"),
        ],
    )
    assert real_repos_by_project(load_report(db)) == {"tracker": ["javieravacone/ai-cost-tracker"]}
