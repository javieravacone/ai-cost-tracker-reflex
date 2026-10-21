"""Port of src/lib/report/report.test.ts (the "format" block lives in test_format.py)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from bis_core.cost import UnpricedModel
from bis_core.db import (
    get_turn,
    list_turns_by_conversation,
    open_db,
    set_manual_assignment,
    upsert_issues,
    upsert_members,
    upsert_model_prices,
    upsert_projects,
    upsert_pull_requests,
    upsert_repo_mappings,
    upsert_seat_plans,
    upsert_teams,
    upsert_turns,
)
from bis_core.report import (
    NONE_KEY,
    DateRange,
    PeriodRange,
    RepoCount,
    Report,
    RowFilters,
    by_day,
    by_issue,
    by_model,
    by_pr,
    by_project,
    by_team,
    by_user,
    compute_totals,
    days_in_range,
    filter_rows,
    full_months_range,
    list_conversations,
    load_conversation,
    load_report,
    month_share,
    months_in_range,
    parse_days,
    parse_issue_key,
    parse_pr_key,
    range_from_days,
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

approx = pytest.approx

REPO = "https://github.com/acme/atlas-api.git"
SANDBOX = "git@github.com:acme/sandbox.git"
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
        repo_url=REPO,
        branch="main",
        commit_sha=None,
        github_org="acme",
        agent_name="GitHub Copilot",
        model="gpt-4.1",
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


TURNS = [
    # ana, conversation c1: issue branch, Opus (10x premium) then gpt-4.1 (included model)
    # AI credits: t1 1500 credits (full coverage), t2 600 (half coverage), t3 unknown.
    turn("t1", conversation_id="c1", branch="feat/101-login", model="claude-opus-4.1", input_tokens=1_000_000, copilot_nano_aiu=1500 * 10**9, copilot_usage_coverage=1),
    turn("t2", conversation_id="c1", started_at="2026-10-12T10:05:00.000Z", branch="feat/101-login", output_tokens=1_000_000, copilot_nano_aiu=600 * 10**9, copilot_usage_coverage=0.5),
    # bob on the head branch of PR !110 (links #101)
    turn("t3", conversation_id="c2", user_name="bob", started_at="2026-10-13T09:00:00.000Z", branch="refactor/x", copilot_usage_coverage=0),
    # bob in an unmapped repo with an unpriced model, no conversation id
    turn("t4", user_name="bob", started_at="2026-10-14T09:00:00.000Z", repo_url=SANDBOX, model="mystery-model"),
    # ana, same month but before the range: must still count for proration
    turn("t5", conversation_id="c0", started_at="2026-10-02T09:00:00.000Z", model="claude-opus-4.1", copilot_nano_aiu=4000 * 10**9, copilot_usage_coverage=1),
    # ana, previous month: outside every Oct computation
    turn("t6", conversation_id="c9", started_at="2026-09-20T09:00:00.000Z"),
    # unknown user, no repo
    turn("t7", conversation_id="c3", user_name="zed", started_at="2026-10-15T09:00:00.000Z", repo_url=None, branch=None),
    # bob on main, manually assigned to #102 (not synced)
    turn("t8", conversation_id="c4", user_name="bob", started_at="2026-10-16T09:00:00.000Z"),
    # ana on develop in the mapped repo: project only, "No issue"
    turn("t9", conversation_id="c1", started_at="2026-10-16T11:00:00.000Z", branch="develop"),
]


@pytest.fixture
def db():
    conn = open_db(":memory:")
    upsert_teams(conn, [Team(id="platform", name="Platform"), Team(id="web", name="Web")])
    upsert_projects(conn, [Project(id="atlas", name="Atlas")])
    upsert_repo_mappings(conn, [RepoMapping(repo="acme/atlas-api", project_id="atlas")])
    upsert_seat_plans(conn, [SeatPlan(id="biz", name="Business", monthly_price_usd=19, included_premium_requests=300, overage_per_premium_request_usd=0.04, included_ai_credits=1900)])
    upsert_model_prices(
        conn,
        [
            ModelPrice(model="gpt-4.1", input_per_mtok=2, output_per_mtok=8, cache_read_per_mtok=0.5, cache_write_per_mtok=0, premium_multiplier=0),
            ModelPrice(model="claude-opus-4*", input_per_mtok=15, output_per_mtok=75, cache_read_per_mtok=1.5, cache_write_per_mtok=18.75, premium_multiplier=10),
        ],
    )
    upsert_members(
        conn,
        [
            Member(user_name="ana", display_name="Ana R.", team_id="platform", seat_plan_id="biz"),
            Member(user_name="bob", display_name="Bob S.", team_id="web", seat_plan_id="biz"),
            Member(user_name="idle", display_name="Idle I.", team_id="web", seat_plan_id="biz"),
        ],
    )
    upsert_issues(
        conn,
        [
            Issue(
                repo="acme/atlas-api",
                number=101,
                title="Login form",
                state="open",
                url="https://github.com/acme/atlas-api/issues/101",
                created_at="2026-09-01T00:00:00.000Z",
                closed_at=None,
            )
        ],
    )
    upsert_pull_requests(
        conn,
        [
            PullRequest(
                repo="acme/atlas-api",
                number=110,
                title="Refactor X",
                state="open",
                head_branch="refactor/x",
                url="https://github.com/acme/atlas-api/pull/110",
                linked_issues=[101],
                commit_shas=[],
                created_at="2026-09-01T00:00:00.000Z",
                merged_at=None,
            )
        ],
    )
    upsert_turns(conn, TURNS)
    set_manual_assignment(conn, ManualAssignment(turn_id="t8", repo="acme/atlas-api", issue_number=102, pr_number=None, note="hotfix"))
    yield conn
    conn.close()


def row(r: Report, turn_id: str):
    return next(x for x in r.rows if x.turn.id == turn_id)


# --- range helpers ---------------------------------------------------------------------------


def test_parses_days_with_a_30_day_default():
    assert parse_days("7") == 7
    assert parse_days("90") == 90
    assert parse_days(["60", "7"]) == 60
    assert parse_days("15") == 30
    assert parse_days("abc") == 30
    assert parse_days(None) == 30


def test_builds_the_last_n_calendar_days_including_today_utc():
    r = range_from_days(7, datetime(2026, 10, 16, 13, 45, tzinfo=timezone.utc))
    assert r == PeriodRange(days=7, from_=RANGE.from_, to=RANGE.to)
    days = days_in_range(r)
    assert len(days) == 7
    assert days[0] == "2026-10-10"
    assert days[6] == "2026-10-16"


def test_lists_touched_months_treating_to_as_exclusive():
    assert months_in_range(DateRange(from_="2026-09-20T00:00:00Z", to="2026-10-17T00:00:00Z")) == ["2026-09", "2026-10"]
    assert months_in_range(DateRange(from_="2026-09-05T00:00:00Z", to="2026-10-01T00:00:00Z")) == ["2026-09"]
    assert months_in_range(DateRange(from_="2026-11-30T00:00:00Z", to="2027-01-02T00:00:00Z")) == ["2026-11", "2026-12", "2027-01"]
    assert full_months_range(RANGE) == DateRange(from_="2026-10-01T00:00:00.000Z", to="2026-11-01T00:00:00.000Z")


def test_computes_the_share_of_a_month_inside_the_range():
    assert month_share("2026-10", RANGE) == approx(7 / 31)
    assert month_share("2026-09", RANGE) == 0
    assert month_share("2026-10", DateRange(from_="2026-01-01T00:00:00Z", to="2027-01-01T00:00:00Z")) == 1


def test_parses_issue_and_pr_keys():
    assert parse_issue_key("acme/atlas-api#101") == {"repo": "acme/atlas-api", "number": 101}
    assert parse_pr_key("acme/atlas-api!110") == {"repo": "acme/atlas-api", "number": 110}
    assert parse_issue_key("nope") is None


# --- load_report -----------------------------------------------------------------------------


def test_joins_turn_attribution_cost_with_resolved_names_only_in_range(db):
    r = load_report(db, RANGE)
    assert [x.turn.id for x in r.rows] == ["t1", "t2", "t3", "t4", "t7", "t8", "t9"]
    t1 = row(r, "t1")
    assert t1.team_name == "Platform"
    assert t1.project_name == "Atlas"
    assert t1.user_display_name == "Ana R."
    assert t1.attribution.issue_key == "acme/atlas-api#101"
    assert t1.attribution.confidence == "exact-branch"
    assert t1.cost.api_equivalent_usd == approx(15)
    assert t1.day == "2026-10-12"
    assert row(r, "t2").tokens == 1_000_000
    assert row(r, "t4").conversation_key == "t4"  # no conversation id -> turn id


def test_prorates_the_subscription_over_the_whole_month(db):
    r = load_report(db, RANGE.from_, RANGE.to)
    # ana Oct: premium t1 10 + t5 10 (+0 for gpt-4.1) = 20, seat $19 -> t1 gets 10/20.
    assert row(r, "t1").cost.subscription_usd == approx(9.5)
    assert row(r, "t2").cost.subscription_usd == 0
    # bob Oct: only t4 (unknown model -> 1 premium request) consumes premium.
    assert row(r, "t4").cost.subscription_usd == approx(19)
    # unknown user -> unallocated
    assert row(r, "t7").cost.subscription_usd == 0
    assert [f"{m.user_name}:{m.month}:{m.turn_count}" for m in r.member_months] == ["ana:2026-10:4", "bob:2026-10:3"]


def test_reports_idle_seats_unpriced_models_unmapped_repos_and_confidence(db):
    r = load_report(db, RANGE)
    assert len(r.idle_seats) == 1
    s = r.idle_seats[0]
    assert (s.user_name, s.month, s.total_usd) == ("idle", "2026-10", 19)
    assert s.period_usd == approx((19 * 7) / 31)
    assert r.unpriced_models == [UnpricedModel(model="mystery-model", turns=1)]
    assert r.unmapped_repos == [RepoCount(repo="acme/sandbox", turns=1)]
    assert r.turns_without_repo == 1
    assert r.confidence == {"manual": 1, "exact-branch": 2, "exact-pr": 1, "exact-commit": 0, "inferred": 0, "project": 3}
    assert r.sources == {"seed": 7, "langsmith": 0}


def test_loads_everything_without_a_range_counting_idle_seats_in_full(db):
    r = load_report(db)
    assert r.range is None
    assert len(r.rows) == len(TURNS)
    assert [f"{s.user_name}:{s.month}:{s.period_share}" for s in r.idle_seats] == [
        "bob:2026-09:1",
        "idle:2026-09:1",
        "idle:2026-10:1",
    ]


def test_reflects_manual_assignments_on_reload(db):
    r = load_report(db, RANGE)
    a8 = row(r, "t8").attribution
    assert (a8.confidence, a8.issue_key, a8.project_id) == ("manual", "acme/atlas-api#102", "atlas")
    set_manual_assignment(db, ManualAssignment(turn_id="t9", repo="acme/atlas-api", issue_number=None, pr_number=110, note=None))
    a9 = row(load_report(db, RANGE), "t9").attribution
    assert (a9.confidence, a9.pr_key, a9.issue_key) == ("manual", "acme/atlas-api!110", "acme/atlas-api#101")


# --- aggregations ----------------------------------------------------------------------------


def test_computes_totals_including_idle_seats(db):
    t = compute_totals(load_report(db, RANGE))
    assert t.turns == 7
    assert t.conversations == 5  # c1, c2, t4, c3, c4
    assert t.users == 3  # ana, bob, zed
    assert t.api_equivalent_usd == approx(15 + 8)
    assert t.premium_requests == 10 + 1
    assert t.turns_subscription_usd == approx(9.5 + 19)
    assert t.idle_seats_usd == approx((19 * 7) / 31)
    assert t.subscription_usd == approx(28.5 + (19 * 7) / 31)
    assert t.pct_with_issue == approx(4 / 7)
    assert t.pct_with_pr == approx(1 / 7)


def test_aggregates_known_ai_credits_only_with_coverage_and_partial_counts(db):
    r = load_report(db, RANGE)
    assert (row(r, "t1").cost.ai_credits, row(r, "t1").cost.ai_credits_usd) == (1500, 15)
    assert (row(r, "t3").cost.ai_credits, row(r, "t3").cost.ai_credits_usd) == (None, None)
    t = compute_totals(r)
    assert t.ai_credits == approx(2100)  # t5 is before the range
    assert t.ai_credits_usd == approx(21)
    assert t.credit_turns == 2
    assert t.credit_partial_turns == 1  # t2
    web = next(b for b in by_team(r) if b.key == "web")
    assert (web.ai_credits, web.credit_turns, web.turns) == (0, 0, 3)


def test_reports_member_month_credits_and_the_pooled_allowance_over_full_months(db):
    r = load_report(db, RANGE)
    ana = next(m for m in r.member_months if m.user_name == "ana")
    c = ana.credits
    assert (c.credits_used, c.included_credits, c.overage_credits, c.turns_with_data) == (6100, 1900, 4200, 3)
    assert c.overage_usd == approx(42)
    assert len(r.credit_pools) == 1
    p = r.credit_pools[0]
    assert (p.month, p.entity, p.seats, p.included_credits, p.credits_used, p.overage_credits) == ("2026-10", "org", 3, 5700, 6100, 400)
    assert p.overage_usd == approx(4)


def test_groups_by_team_project_model_and_user(db):
    r = load_report(db, RANGE)

    teams = by_team(r)
    assert [(b.label, b.turns) for b in teams] == [("Platform", 3), ("Web", 3), ("No team", 1)]
    assert teams[2].key == NONE_KEY

    projects = by_project(r)
    assert [(b.key, b.turns) for b in projects] == [("atlas", 5), (NONE_KEY, 2)]
    assert projects[0].no_issue.turns == 1  # t9
    assert projects[0].distinct_issues == 2
    assert projects[0].distinct_prs == 1
    assert projects[0].attributed == 4
    assert projects[0].confidence["manual"] == 1

    models = by_model(r)
    assert next(m for m in models if m.key == "mystery-model").priced is False
    opus = next(m for m in models if m.key == "claude-opus-4.1")
    assert (opus.priced, opus.premium_multiplier) == (True, 10)

    users = by_user(r)
    ana = next(u for u in users if u.key == "ana")
    assert (ana.label, ana.team_name, ana.is_member) == ("Ana R.", "Platform", True)
    zed = next(u for u in users if u.key == "zed")
    assert (zed.is_member, zed.team_name) == (False, None)


def test_fills_every_day_of_the_range(db):
    days = by_day(load_report(db, RANGE))
    assert len(days) == 7
    assert next(d for d in days if d.key == "2026-10-12").turns == 2
    assert next(d for d in days if d.key == "2026-10-11").turns == 0


def test_enriches_issues_and_prs_with_github_data_or_marks_them_not_synced(db):
    r = load_report(db, RANGE)
    issues = by_issue(r)
    i101 = next(i for i in issues if i.number == 101)
    assert (i101.repo, i101.turns, i101.project_name) == ("acme/atlas-api", 3, "Atlas")
    assert i101.issue.title == "Login form"
    assert i101.pr_keys == ["acme/atlas-api!110"]
    assert (i101.confidence["exact-branch"], i101.confidence["exact-pr"]) == (2, 1)
    i102 = next(i for i in issues if i.number == 102)
    assert i102.issue is None
    assert i102.turns == 1

    prs = by_pr(r)
    assert len(prs) == 1
    assert (prs[0].number, prs[0].turns, prs[0].issue_keys) == (110, 1, ["acme/atlas-api#101"])
    assert prs[0].pr.title == "Refactor X"


def test_filters_rows_and_lists_conversations(db):
    r = load_report(db, RANGE)
    ids = lambda rows: sorted(x.turn.id for x in rows)  # noqa: E731
    assert ids(filter_rows(r.rows, RowFilters(no_issue=True))) == ["t4", "t7", "t9"]
    assert ids(filter_rows(r.rows, user="ANA")) == ["t1", "t2", "t9"]
    assert ids(filter_rows(r.rows, {"project": NONE_KEY})) == ["t4", "t7"]
    assert [x.turn.id for x in filter_rows(r.rows, team="web", issue="acme/atlas-api#101")] == ["t3"]

    convs = list_conversations(r.rows)
    assert convs[0].key == "c1"  # last activity Oct 16 11:00
    c1 = next(c for c in convs if c.key == "c1")
    assert (c1.turns, c1.first_at, c1.last_at, c1.user_display_name, c1.branches, c1.issue_keys, c1.repos) == (
        3,
        "2026-10-12T10:00:00.000Z",
        "2026-10-16T11:00:00.000Z",
        "Ana R.",
        ["develop", "feat/101-login"],
        ["acme/atlas-api#101"],
        ["acme/atlas-api"],
    )


def test_loads_a_single_conversation_with_full_month_cost_basis(db):
    c = load_conversation(db, "c1", list_turns_by_conversation(db, "c1"))
    assert [x.turn.id for x in c.rows] == ["t1", "t2", "t9"]
    assert c.rows[0].cost.subscription_usd == approx(9.5)
    single = load_conversation(db, "t4", [get_turn(db, "t4")])
    assert [x.turn.id for x in single.rows] == ["t4"]
    assert load_conversation(db, "nope", []) is None
