"""Port of src/lib/cost/cost.test.ts."""

from __future__ import annotations

import itertools
import math
import time
from dataclasses import replace
from datetime import datetime, timezone

import pytest

from bis_core._js import iso_from_ms
from bis_core.cost import (
    AI_CREDIT_USD,
    NANO_PER_CREDIT,
    CostContext,
    CreditsMonth,
    MemberCredits,
    UnpricedModel,
    api_equivalent_cost,
    compute_costs,
    credit_pools,
    credits_month_cost,
    credits_to_usd,
    find_price,
    format_usd,
    idle_seats,
    member_months,
    month_of,
    nano_to_credits,
    premium_requests_for,
    subscription_month_cost,
    unpriced_models,
)
from bis_core.types import Member, ModelPrice, SeatPlan, Turn

approx = pytest.approx
_seq = itertools.count(1)


def turn(**over) -> Turn:
    n = next(_seq)
    base = dict(
        id=f"t{n}",
        trace_id=f"tr{n}",
        conversation_id=None,
        started_at="2026-10-05T12:00:00Z",
        ended_at=None,
        user_name="alice",
        team_id="team-a",
        project_hint=None,
        repo_url=None,
        branch=None,
        commit_sha=None,
        github_org=None,
        agent_name=None,
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


def price(model: str, **over) -> ModelPrice:
    base = dict(
        model=model,
        input_per_mtok=3,
        output_per_mtok=15,
        cache_read_per_mtok=0.3,
        cache_write_per_mtok=3.75,
        premium_multiplier=1,
    )
    base.update(over)
    return ModelPrice(**base)


PRICES = [
    price("gpt-4.1", input_per_mtok=2, output_per_mtok=8, cache_read_per_mtok=0.5, cache_write_per_mtok=0, premium_multiplier=0),
    price("claude-sonnet*", premium_multiplier=1),
    price("claude-sonnet-4.5*", premium_multiplier=1.25),
    price("claude-opus*", input_per_mtok=15, output_per_mtok=75, premium_multiplier=10),
]

PLANS = [
    SeatPlan(id="business", name="Business", monthly_price_usd=19, included_premium_requests=300, overage_per_premium_request_usd=0.04, included_ai_credits=1900),
    SeatPlan(id="enterprise", name="Enterprise", monthly_price_usd=39, included_premium_requests=1000, overage_per_premium_request_usd=0.04, included_ai_credits=3900),
]

MEMBERS = [
    Member(user_name="alice", display_name="Alice", team_id="team-a", seat_plan_id="business"),
    Member(user_name="bob", display_name="Bob", team_id="team-b", seat_plan_id="enterprise"),
    Member(user_name="carol", display_name="Carol", team_id="team-a", seat_plan_id="business"),
]

CTX = CostContext(prices=PRICES, members=MEMBERS, seat_plans=PLANS)


def nano_for(credits: float) -> float:
    return credits * NANO_PER_CREDIT


# --- find_price ------------------------------------------------------------------------------


def test_find_price_matches_exactly_case_insensitively():
    assert find_price("GPT-4.1", PRICES).model == "gpt-4.1"
    assert find_price("  gpt-4.1 ", PRICES).model == "gpt-4.1"


def test_find_price_prefers_exact_over_prefix():
    ps = [price("claude-sonnet*", premium_multiplier=1), price("claude-sonnet-4", premium_multiplier=7)]
    assert find_price("claude-sonnet-4", ps).premium_multiplier == 7


def test_find_price_falls_back_to_prefix_match():
    assert find_price("claude-opus-4.1", PRICES).model == "claude-opus*"
    assert find_price("Claude-Sonnet-4", PRICES).model == "claude-sonnet*"


def test_find_price_picks_the_longest_matching_prefix_regardless_of_order():
    assert find_price("claude-sonnet-4.5-20250929", PRICES).model == "claude-sonnet-4.5*"
    assert find_price("claude-sonnet-4.5", list(reversed(PRICES))).model == "claude-sonnet-4.5*"


def test_find_price_does_not_prefix_match_entries_without_star():
    assert find_price("gpt-4.1-mini", PRICES) is None


def test_find_price_returns_none_for_unknown_none_or_empty():
    assert find_price("gemini-2.5-pro", PRICES) is None
    assert find_price(None, PRICES) is None
    assert find_price("", PRICES) is None
    assert find_price("gpt-4.1", []) is None


def test_a_bare_star_entry_is_a_catch_all():
    ps = [price("*", premium_multiplier=2), price("claude*")]
    assert find_price("anything", ps).model == "*"
    assert find_price("claude-x", ps).model == "claude*"


# --- api_equivalent_cost ---------------------------------------------------------------------

P = price("m", input_per_mtok=3, output_per_mtok=15, cache_read_per_mtok=0.3, cache_write_per_mtok=3.75)


def test_prices_plain_input_output():
    assert api_equivalent_cost(turn(input_tokens=1_000_000, output_tokens=100_000), P) == approx(4.5, abs=1e-12)


def test_treats_input_as_including_cached_tokens():
    t = turn(input_tokens=1_000_000, cache_read_tokens=600_000, cache_creation_tokens=100_000, output_tokens=0)
    assert api_equivalent_cost(t, P) == approx(1.455, abs=1e-12)


def test_clamps_uncached_input_to_0():
    t = turn(input_tokens=100, cache_read_tokens=1_000_000, cache_creation_tokens=0)
    assert api_equivalent_cost(t, P) == approx(0.3, abs=1e-12)


def test_does_not_double_count_reasoning_tokens():
    a = turn(output_tokens=1_000_000, reasoning_tokens=0)
    b = turn(output_tokens=1_000_000, reasoning_tokens=800_000)
    assert api_equivalent_cost(b, P) == api_equivalent_cost(a, P)
    assert api_equivalent_cost(b, P) == approx(15, abs=1e-12)


def test_returns_0_for_none_price_and_for_zero_tokens():
    assert api_equivalent_cost(turn(input_tokens=5000, output_tokens=5000), None) == 0
    assert api_equivalent_cost(turn(), P) == 0


def test_ignores_negative_and_non_finite_token_counts():
    t = turn(input_tokens=-500, output_tokens=math.nan, cache_read_tokens=-1, cache_creation_tokens=math.inf)
    assert api_equivalent_cost(t, P) == 0


# --- premium_requests_for --------------------------------------------------------------------


def test_uses_the_model_multiplier_including_0_and_10():
    assert premium_requests_for(turn(), find_price("gpt-4.1", PRICES)) == 0
    assert premium_requests_for(turn(), find_price("claude-opus-4", PRICES)) == 10
    assert premium_requests_for(turn(), find_price("claude-sonnet-4.5", PRICES)) == 1.25


def test_assumes_1_for_unknown_models_and_clamps_negatives():
    assert premium_requests_for(turn(), None) == 1
    assert premium_requests_for(turn(), price("x", premium_multiplier=-3)) == 0


# --- subscription_month_cost -----------------------------------------------------------------


def test_charges_overage_only_above_included():
    assert subscription_month_cost(PLANS[0], 300).total_usd == 19
    s = subscription_month_cost(PLANS[0], 350)
    assert s.overage_requests == 50
    assert s.overage_usd == approx(2, abs=1e-12)
    assert s.total_usd == approx(21, abs=1e-12)


def test_missing_plan_costs_0():
    assert subscription_month_cost(None, 999).total_usd == 0


# --- month_of --------------------------------------------------------------------------------


def test_month_of_uses_utc_calendar_months():
    assert month_of("2026-10-31T23:59:59Z") == "2026-10"
    assert month_of("2026-11-01T00:00:00Z") == "2026-11"
    # 23:30 at -02:00 on Oct 31 is Nov 1 01:30 UTC
    assert month_of("2026-10-31T23:30:00-02:00") == "2026-11"
    assert month_of("2026-11-01T00:30:00+02:00") == "2026-10"


def test_month_of_falls_back_to_string_prefix_when_unparseable():
    assert month_of("garbage") == "garbage"[:7]


# --- compute_costs ---------------------------------------------------------------------------


def test_preserves_order_and_turn_ids():
    ts = [turn(user_name="bob"), turn(user_name=None), turn(), turn(user_name="carol")]
    assert [c.turn_id for c in compute_costs(ts, CTX)] == [t.id for t in ts]


def test_prorates_seat_by_premium_requests_and_sums_exactly_to_the_month_cost():
    ts = [turn(model="claude-opus-4"), turn(model="claude-sonnet-4"), turn(model="gpt-4.1"), turn(model="unknown-model")]
    cs = compute_costs(ts, CTX)
    assert [c.premium_requests for c in cs] == [10, 1, 0, 1]
    assert cs[0].subscription_usd == approx((19 * 10) / 12, abs=1e-12)
    assert cs[2].subscription_usd == 0
    assert abs(sum(c.subscription_usd for c in cs) - 19) < 1e-9


def test_splits_equally_when_the_member_month_used_0_premium_requests():
    cs = compute_costs([turn(model="gpt-4.1"), turn(model="gpt-4.1"), turn(model="gpt-4.1")], CTX)
    for c in cs:
        assert c.subscription_usd == approx(19 / 3, abs=1e-12)
    assert abs(sum(c.subscription_usd for c in cs) - 19) < 1e-9


def test_adds_overage_above_included_premium_requests():
    # 31 opus turns = 310 premium requests on a 300-included plan => 10 * 0.04 overage
    cs = compute_costs([turn(model="claude-opus-4") for _ in range(31)], CTX)
    assert abs(sum(c.subscription_usd for c in cs) - (19 + 0.4)) < 1e-9


def test_splits_member_costs_at_the_utc_month_boundary():
    ts = [
        turn(started_at="2026-09-30T23:59:59Z", model="claude-sonnet-4"),
        turn(started_at="2026-10-01T00:00:00Z", model="claude-sonnet-4"),
        turn(started_at="2026-10-15T10:00:00Z", model="claude-sonnet-4"),
    ]
    cs = compute_costs(ts, CTX)
    assert cs[0].subscription_usd == approx(19, abs=1e-12)  # alone in September
    assert cs[1].subscription_usd == approx(9.5, abs=1e-12)
    assert cs[2].subscription_usd == approx(9.5, abs=1e-12)


def test_gives_unknown_or_none_users_0_subscription_but_still_computes_api_cost():
    ts = [
        turn(user_name=None, model="claude-opus-4", input_tokens=1_000_000),
        turn(user_name="mallory", model="claude-opus-4", input_tokens=1_000_000),
    ]
    for c in compute_costs(ts, CTX):
        assert c.subscription_usd == 0
        assert c.api_equivalent_usd == approx(15, abs=1e-12)
        assert c.premium_requests == 10


def test_matches_members_case_insensitively():
    assert compute_costs([turn(user_name="ALICE")], CTX)[0].subscription_usd == approx(19, abs=1e-12)


def test_member_with_an_unknown_seat_plan_gets_0_subscription():
    c2 = replace(CTX, members=[Member(user_name="dan", display_name="Dan", team_id="t", seat_plan_id="nope")])
    assert compute_costs([turn(user_name="dan")], c2)[0].subscription_usd == 0


def test_keeps_members_independent():
    cs = compute_costs([turn(user_name="alice"), turn(user_name="bob"), turn(user_name="bob")], CTX)
    assert cs[0].subscription_usd == approx(19, abs=1e-12)
    assert cs[1].subscription_usd + cs[2].subscription_usd == approx(39, abs=1e-12)


def test_returns_empty_for_no_turns():
    assert compute_costs([], CTX) == []


def test_handles_10k_turns_quickly_and_consistently():
    users = ["alice", "bob", "carol", None, "ghost"]
    models = ["gpt-4.1", "claude-sonnet-4", "claude-sonnet-4.5", "claude-opus-4", "mystery", None]
    ts = []
    for i in range(10_000):
        ms = int(datetime(2026, (i % 3) + 1, 1 + (i % 28), i % 24, tzinfo=timezone.utc).timestamp() * 1000)
        ts.append(
            turn(
                user_name=users[i % len(users)],
                model=models[i % len(models)],
                started_at=iso_from_ms(ms),
                input_tokens=1000 + i,
                output_tokens=200 + (i % 500),
                cache_read_tokens=i % 700,
            )
        )
    t0 = time.perf_counter()
    cs = compute_costs(ts, CTX)
    mm = member_months(ts, CTX)
    elapsed = (time.perf_counter() - t0) * 1000
    assert len(cs) == 10_000
    assert elapsed < 3000  # generous bound for Python
    assert abs(sum(c.subscription_usd for c in cs) - sum(m.total_usd for m in mm)) < 1e-6
    assert sum(m.turn_count for m in mm) == 6000  # 3 of 5 users are members


# --- member_months ---------------------------------------------------------------------------


def test_aggregates_per_member_and_utc_month():
    ts = [
        turn(user_name="alice", started_at="2026-10-01T00:00:00Z", model="claude-opus-4", input_tokens=1_000_000),
        turn(user_name="alice", started_at="2026-10-20T00:00:00Z", model="claude-opus-4"),
        turn(user_name="alice", started_at="2026-11-02T00:00:00Z", model="gpt-4.1"),
        turn(user_name="bob", started_at="2026-10-03T00:00:00Z", model="claude-sonnet-4"),
        turn(user_name=None),
    ]
    mm = member_months(ts, CTX)
    assert [f"{m.month}/{m.user_name}" for m in mm] == ["2026-10/alice", "2026-10/bob", "2026-11/alice"]
    alice_oct = mm[0]
    assert (
        alice_oct.team_id,
        alice_oct.seat_plan_id,
        alice_oct.seat_usd,
        alice_oct.premium_used,
        alice_oct.included_premium,
        alice_oct.overage_requests,
        alice_oct.overage_usd,
        alice_oct.total_usd,
        alice_oct.turn_count,
    ) == ("team-a", "business", 19, 20, 300, 0, 0, 19, 2)
    assert alice_oct.api_equivalent_usd == approx(15, abs=1e-12)
    assert (mm[2].premium_used, mm[2].total_usd, mm[2].turn_count) == (0, 19, 1)


def test_reports_overage_fields():
    [m] = member_months([turn(model="claude-opus-4") for _ in range(35)], CTX)
    assert m.premium_used == 350
    assert m.overage_requests == 50
    assert m.overage_usd == approx(2, abs=1e-12)
    assert m.total_usd == approx(21, abs=1e-12)


# --- idle_seats ------------------------------------------------------------------------------


def test_lists_members_without_turns_in_the_given_months_at_full_seat_cost():
    ts = [turn(user_name="alice", started_at="2026-10-05T00:00:00Z"), turn(user_name="bob", started_at="2026-11-05T00:00:00Z")]
    idle = idle_seats(CTX, ["2026-10", "2026-11", "2026-10"], ts)
    assert [f"{m.month}/{m.user_name}" for m in idle] == ["2026-10/bob", "2026-10/carol", "2026-11/alice", "2026-11/carol"]
    bob = idle[0]
    assert (bob.seat_usd, bob.total_usd, bob.premium_used, bob.turn_count, bob.api_equivalent_usd, bob.included_premium) == (
        39,
        39,
        0,
        0,
        0,
        1000,
    )


def test_returns_every_member_when_there_are_no_turns_and_nothing_for_no_months():
    assert len(idle_seats(CTX, ["2026-10"], [])) == 3
    assert idle_seats(CTX, [], []) == []


# --- unpriced_models -------------------------------------------------------------------------


def test_counts_turns_per_unpriced_model_including_none_sorted_desc():
    ts = [turn(model="mystery"), turn(model=None), turn(model="mystery"), turn(model="claude-opus-4"), turn(model="gpt-4.1")]
    assert unpriced_models(ts, PRICES) == [UnpricedModel(model="mystery", turns=2), UnpricedModel(model=None, turns=1)]
    assert unpriced_models([], PRICES) == []


# --- format_usd ------------------------------------------------------------------------------


def test_format_usd_with_thousands_separators_and_2_decimals():
    assert format_usd(1234.567) == "$1,234.57"
    assert format_usd(0) == "$0.00"
    assert format_usd(-0.0) == "$0.00"
    assert format_usd(0.01) == "$0.01"
    assert format_usd(-12.5) == "-$12.50"


def test_format_usd_uses_4_decimals_for_tiny_positive_values():
    assert format_usd(0.0042) == "$0.0042"
    assert format_usd(0.00999) == "$0.0100"
    assert format_usd(0.00001) == "<$0.0001"


def test_format_usd_renders_non_finite_as_a_dash():
    assert format_usd(math.nan) == "—"


# --- AI credits ------------------------------------------------------------------------------


def test_uses_1_credit_1e9_nano_1_cent():
    assert AI_CREDIT_USD == 0.01
    assert NANO_PER_CREDIT == 1e9
    assert nano_to_credits(280_880_000) == approx(0.28088, abs=1e-12)
    assert credits_to_usd(nano_to_credits(280_880_000)) == approx(0.0028088, abs=1e-12)
    assert credits_to_usd(1900) == approx(19, abs=1e-12)


def test_keeps_unknown_none_apart_from_a_reported_0():
    assert nano_to_credits(None) is None
    assert nano_to_credits(math.nan) is None
    assert nano_to_credits(-5) is None
    assert nano_to_credits(0) == 0
    assert credits_to_usd(None) is None
    assert credits_to_usd(0) == 0


def test_compute_costs_reports_per_turn_credits_and_gross_usd_none_when_unknown():
    known, zero, unknown = compute_costs(
        [turn(copilot_nano_aiu=nano_for(2.5)), turn(copilot_nano_aiu=0), turn(copilot_nano_aiu=None)], CTX
    )
    assert known.ai_credits == approx(2.5, abs=1e-12)
    assert known.ai_credits_usd == approx(0.025, abs=1e-12)
    assert (zero.ai_credits, zero.ai_credits_usd) == (0, 0)
    assert (unknown.ai_credits, unknown.ai_credits_usd) == (None, None)


def test_credits_month_cost_bills_only_credits_above_the_allowance():
    assert credits_month_cost(1900, 1500) == CreditsMonth(credits_used=1500, included_credits=1900, overage_credits=0, overage_usd=0)
    over = credits_month_cost(1900, 2400)
    assert over.overage_credits == 500
    assert over.overage_usd == approx(5, abs=1e-12)
    assert credits_month_cost(0, 10).overage_usd == approx(0.1, abs=1e-12)
    assert credits_month_cost(math.nan, -3) == CreditsMonth(credits_used=0, included_credits=0, overage_credits=0, overage_usd=0)


def test_sums_known_credits_per_member_month_against_the_seat_allowance():
    ts = [
        turn(user_name="alice", copilot_nano_aiu=nano_for(1500)),
        turn(user_name="alice", copilot_nano_aiu=nano_for(600)),
        turn(user_name="alice", copilot_nano_aiu=None),
        turn(user_name="bob", copilot_nano_aiu=nano_for(100)),
    ]
    alice, bob = member_months(ts, CTX)
    assert (alice.credits.included_credits, alice.credits.overage_credits, alice.credits.turns_with_data) == (1900, approx(200), 2)
    assert alice.credits.credits_used == approx(2100, abs=1e-9)
    assert alice.credits.overage_usd == approx(2, abs=1e-9)
    assert alice.turn_count == 3
    assert (bob.credits.credits_used, bob.credits.included_credits, bob.credits.overage_credits, bob.credits.overage_usd) == (
        100,
        3900,
        0,
        0,
    )


def test_idle_seats_carry_their_allowance_and_zero_usage():
    [idle] = idle_seats(CTX, ["2026-10"], [turn(user_name="alice"), turn(user_name="bob")])
    assert idle.user_name == "carol"
    assert idle.credits == MemberCredits(credits_used=0, included_credits=1900, overage_credits=0, overage_usd=0, turns_with_data=0)


# --- credit_pools ----------------------------------------------------------------------------


def test_pools_every_seats_included_credits_and_bills_only_usage_above_the_pool():
    # Pool = alice 1900 + bob 3900 + carol 1900 (idle) = 7700. alice alone overshoots her seat.
    ts = [
        turn(user_name="alice", copilot_nano_aiu=nano_for(5000)),
        turn(user_name="bob", copilot_nano_aiu=nano_for(2000)),
        turn(user_name="dave", copilot_nano_aiu=nano_for(99_999)),  # not a member: no seat, not pooled
        turn(user_name="bob", copilot_nano_aiu=None),
    ]
    [pool] = credit_pools(ts, CTX)
    assert (pool.month, pool.entity, pool.seats, pool.included_credits, pool.turns, pool.turns_with_data, pool.overage_credits, pool.overage_usd) == (
        "2026-10",
        "org",
        3,
        7700,
        3,
        2,
        0,
        0,
    )
    assert pool.credits_used == approx(7000, abs=1e-9)
    # Without pooling alice would pay 3100 credits of overage.
    alice = next(m for m in member_months(ts, CTX) if m.user_name == "alice")
    assert alice.credits.overage_credits == approx(3100, abs=1e-9)


def test_charges_overage_once_the_pool_is_exhausted():
    [pool] = credit_pools([turn(user_name="alice", copilot_nano_aiu=nano_for(8000)), turn(user_name="bob", copilot_nano_aiu=nano_for(1000))], CTX)
    assert pool.overage_credits == approx(1300, abs=1e-9)
    assert pool.overage_usd == approx(13, abs=1e-9)


def test_is_per_month_and_per_billing_entity_and_lists_requested_months_without_turns():
    ts = [
        turn(user_name="alice", started_at="2026-10-05T00:00:00Z", copilot_nano_aiu=nano_for(10)),
        turn(user_name="bob", started_at="2026-11-05T00:00:00Z", copilot_nano_aiu=nano_for(20)),
    ]
    pools = credit_pools(ts, CTX, ["2026-10", "2026-11", "2026-12"], lambda m: m.team_id)

    def fmt(x: float) -> str:
        return str(int(x)) if float(x).is_integer() else str(x)

    assert [f"{p.month}/{p.entity}:{p.seats}:{fmt(p.included_credits)}:{fmt(p.credits_used)}" for p in pools] == [
        "2026-10/team-a:2:3800:10",
        "2026-10/team-b:1:3900:0",
        "2026-11/team-a:2:3800:0",
        "2026-11/team-b:1:3900:20",
        "2026-12/team-a:2:3800:0",
        "2026-12/team-b:1:3900:0",
    ]


def test_treats_a_plan_without_included_credits_as_a_zero_pool():
    free = CostContext(
        prices=PRICES,
        members=[Member(user_name="alice", display_name="A", team_id="t", seat_plan_id="free")],
        seat_plans=[SeatPlan(id="free", name="Free", monthly_price_usd=0, included_premium_requests=50, overage_per_premium_request_usd=0, included_ai_credits=0)],
    )
    [pool] = credit_pools([turn(copilot_nano_aiu=280_880_000)], free)
    assert pool.included_credits == 0
    assert pool.overage_credits == approx(0.28088, abs=1e-12)
    assert pool.overage_usd == approx(0.0028088, abs=1e-12)
