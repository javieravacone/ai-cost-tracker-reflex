"""Port of src/lib/report/people.test.ts."""

from __future__ import annotations

import pytest

from bis_core.db import (
    open_db,
    upsert_members,
    upsert_model_prices,
    upsert_projects,
    upsert_repo_mappings,
    upsert_seat_plans,
    upsert_teams,
    upsert_turns,
)
from bis_core.report import NONE_KEY, DateRange, load_report
from bis_core.report.people import TopShare, initials, person_detail, team_detail
from bis_core.types import Member, ModelPrice, Project, RepoMapping, SeatPlan, Team, Turn

approx = pytest.approx

ATLAS = "https://github.com/acme/atlas-api.git"
BEACON = "https://github.com/acme/beacon.git"
RANGE = DateRange(from_="2026-10-10T00:00:00.000Z", to="2026-10-17T00:00:00.000Z")


def turn(id: str, **over) -> Turn:
    base = dict(
        id=id,
        trace_id=f"trace-{id}",
        conversation_id=None,
        started_at="2026-10-12T10:00:00.000Z",
        ended_at=None,
        user_name="ana",
        team_id=None,
        project_hint=None,
        repo_url=ATLAS,
        branch="main",
        commit_sha=None,
        github_org="acme",
        agent_name="GitHub Copilot",
        model="gpt-4.1",
        input_tokens=100,
        output_tokens=50,
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


G = 10**9
TURNS = [
    # ana (data): 3 turns, 2 conversations, atlas (300 credits) + beacon (100 credits)
    turn("a1", conversation_id="ca1", branch="feat/7-x", copilot_nano_aiu=200 * G, copilot_usage_coverage=1, cache_read_tokens=40),
    turn("a2", conversation_id="ca1", started_at="2026-10-12T10:05:00.000Z", copilot_nano_aiu=100 * G, copilot_usage_coverage=1, model="claude-sonnet-4"),
    turn("a3", conversation_id="ca2", started_at="2026-10-14T08:00:00.000Z", repo_url=BEACON, copilot_nano_aiu=100 * G, copilot_usage_coverage=1, source="langsmith"),
    # bob (web member) with a turn explicitly tagged team=data
    turn("b1", conversation_id="cb1", user_name="bob", team_id="data", started_at="2026-10-13T09:00:00.000Z"),
    # bob in his own team
    turn("b2", conversation_id="cb2", user_name="bob", started_at="2026-10-15T09:00:00.000Z"),
    # unknown user, team attr data
    turn("u1", conversation_id="cu1", user_name=None, team_id="data", started_at="2026-10-16T09:00:00.000Z"),
    # ana outside the range
    turn("a0", conversation_id="ca0", started_at="2026-10-02T09:00:00.000Z", copilot_nano_aiu=500 * G, copilot_usage_coverage=1),
    # a non-member with turns
    turn("z1", conversation_id="cz1", user_name="zed", team_id="web", started_at="2026-10-11T09:00:00.000Z"),
]


@pytest.fixture
def db():
    conn = open_db(":memory:")
    upsert_teams(conn, [Team(id="data", name="Data Engineering"), Team(id="web", name="Web")])
    upsert_projects(conn, [Project(id="atlas", name="Atlas"), Project(id="beacon", name="Beacon")])
    upsert_repo_mappings(
        conn, [RepoMapping(repo="acme/atlas-api", project_id="atlas"), RepoMapping(repo="acme/beacon", project_id="beacon")]
    )
    upsert_seat_plans(conn, [SeatPlan(id="biz", name="Business", monthly_price_usd=19, included_premium_requests=300, overage_per_premium_request_usd=0.04, included_ai_credits=1900)])
    upsert_model_prices(conn, [ModelPrice(model="gpt-4.1", input_per_mtok=2, output_per_mtok=8, cache_read_per_mtok=0.5, cache_write_per_mtok=0, premium_multiplier=0)])
    upsert_members(
        conn,
        [
            Member(user_name="ana", display_name="Ana Ruiz", team_id="data", seat_plan_id="biz"),
            Member(user_name="idle", display_name="Idle Person", team_id="data", seat_plan_id="biz"),
            Member(user_name="bob", display_name="Bob S.", team_id="web", seat_plan_id="biz"),
        ],
    )
    upsert_turns(conn, TURNS)
    yield conn
    conn.close()


# --- team_detail -----------------------------------------------------------------------------


def test_team_detail_returns_none_for_an_unknown_team(db):
    assert team_detail(load_report(db, RANGE), "nope") is None


def test_lists_every_member_idle_included_guests_and_the_unidentified_bucket_last(db):
    t = team_detail(load_report(db, RANGE), "data")
    assert t.team.name == "Data Engineering"
    assert [m.key for m in t.members] == ["ana", "bob", "idle", NONE_KEY]
    assert t.member_count == 2
    assert t.active_members == 2  # ana + bob (guest) have turns here

    ana = t.members[0]
    assert (ana.label, ana.is_member, ana.turns, ana.conversations, ana.active_days, ana.real) == ("Ana Ruiz", True, 3, 2, 2, True)
    assert ana.ai_credits == approx(400)
    assert ana.last_at == "2026-10-14T08:00:00.000Z"
    assert ana.top_project == TopShare(key="atlas", label="Atlas", share=0.75)

    bob = t.members[1]
    assert (bob.is_member, bob.other_team_name, bob.turns) == (False, "Web", 1)

    idle = t.members[2]
    assert (idle.label, idle.is_member, idle.turns, idle.last_at, idle.top_project) == ("Idle Person", True, 0, None, None)

    unidentified = t.members[3]
    assert (unidentified.label, unidentified.user_name, unidentified.turns) == ("Unidentified person", None, 1)


def test_totals_and_breakdowns_cover_only_the_teams_rows(db):
    t = team_detail(load_report(db, RANGE), "data")
    assert t.totals.turns == 5
    assert t.totals.users == 2
    assert t.pct_with_issue == approx(1 / 5)
    assert [p.key for p in t.projects] == ["atlas", "beacon"]
    assert t.projects[0].ai_credits == approx(300)
    assert [i.key for i in t.issues] == ["acme/atlas-api#7"]
    assert t.last_at == "2026-10-16T09:00:00.000Z"
    assert t.real is True


def test_shows_a_known_team_without_turns_in_the_period(db):
    t = team_detail(load_report(db, DateRange(from_="2026-11-01T00:00:00Z", to="2026-11-08T00:00:00Z")), "data")
    assert t.totals.turns == 0
    assert [m.key for m in t.members] == ["ana", "idle"]
    assert t.active_members == 0


# --- person_detail ---------------------------------------------------------------------------


def test_aggregates_the_persons_rows_across_teams(db):
    p = person_detail(load_report(db, RANGE), "ANA")
    pr = p.person
    assert (pr.user_name, pr.display_name, pr.is_member, pr.team_id, pr.team_name, pr.seat_plan_name) == (
        "ana",
        "Ana Ruiz",
        True,
        "data",
        "Data Engineering",
        "Business",
    )
    assert p.totals.turns == 3
    assert p.totals.ai_credits == approx(400)
    assert p.cache_read_tokens == 40
    assert p.active_days == 2
    assert p.first_at == "2026-10-12T10:00:00.000Z"
    assert p.top_model.key == "gpt-4.1"
    assert p.top_model.share == approx(2 / 3)
    assert [(x.key, x.turns) for x in p.projects] == [("atlas", 2), ("beacon", 1)]
    assert [m.key for m in p.models] == ["gpt-4.1", "claude-sonnet-4"]
    assert [i.key for i in p.issues] == ["acme/atlas-api#7"]
    assert len(p.daily) == 7
    assert next(d for d in p.daily if d.key == "2026-10-12").turns == 2
    assert [c.key for c in p.conversations] == ["ca2", "ca1"]  # newest first
    assert p.real is True


def test_seat_usage_uses_the_whole_last_month_of_the_period(db):
    p = person_detail(load_report(db, RANGE), "ana")
    # October: a0 (500, before the range) + a1..a3 (400)
    assert (p.seat.month, p.seat.included_credits, p.seat.turn_count, p.seat.turns_with_data) == ("2026-10", 1900, 4, 4)
    assert p.seat.credits_used == approx(900)
    assert p.seat.share == approx(900 / 1900)


def test_an_idle_member_gets_an_empty_detail_with_the_plan_allowance(db):
    p = person_detail(load_report(db, RANGE), "idle")
    assert p.totals.turns == 0
    assert p.conversations == []
    assert (p.seat.credits_used, p.seat.included_credits, p.seat.share) == (0, 1900, 0)


def test_a_non_member_takes_the_team_of_their_turns_and_has_no_seat(db):
    p = person_detail(load_report(db, RANGE), "zed")
    assert (p.person.is_member, p.person.team_id, p.person.team_name, p.person.seat_plan_id) == (False, "web", "Web", None)
    assert p.seat is None


def test_returns_none_for_an_unknown_person_unless_known(db):
    r = load_report(db, RANGE)
    assert person_detail(r, "nobody") is None
    assert person_detail(r, "nobody", known=True).person.display_name == "nobody"


# --- initials --------------------------------------------------------------------------------


def test_builds_avatar_initials():
    assert initials("Ana Ruiz") == "AR"
    assert initials("javieravacone") == "JA"
    assert initials("ana.ruiz") == "AR"
    assert initials("María José de la Peña") == "MP"
    assert initials("  ") == "?"
