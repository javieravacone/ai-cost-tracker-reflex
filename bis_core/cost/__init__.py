"""Cost engine: pure functions, no I/O (port of src/lib/cost/index.ts).

Views per turn:
 1. API-equivalent cost: what the tokens would cost at list price (tokens x ModelPrice).
 2. Real Copilot consumption: GitHub AI credits reported by the Copilot server on each LLM call
    (`copilot_usage_nano_aiu`), gross at list price, before the included pool. Unknown (None)
    when the client did not report it, never treated as 0.
 3. Subscription cost (legacy model): the member's Copilot seat plus premium-request overage
    for the calendar month (UTC), prorated over that member-month's turns.

Credits per member-month: used vs included per seat; and pooled per billing entity, where the
included credits of every seat are shared and only usage above the pool is billed.

Nothing is rounded internally; use `format_usd` for display only.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from functools import cmp_to_key

from bis_core._js import first_nonzero, intl_usd, iso_from_ms, is_finite, locale_compare, parse_iso_ms
from bis_core.types import Member, ModelPrice, SeatPlan, Turn, TurnCost

__all__ = [
    "AI_CREDIT_USD",
    "DEFAULT_BILLING_ENTITY",
    "NANO_PER_CREDIT",
    "CostContext",
    "CreditPool",
    "CreditsMonth",
    "MemberCredits",
    "MemberMonth",
    "SubscriptionMonth",
    "UnpricedModel",
    "api_equivalent_cost",
    "compute_costs",
    "credit_pools",
    "credits_month_cost",
    "credits_to_usd",
    "find_price",
    "format_usd",
    "idle_seats",
    "member_months",
    "month_of",
    "nano_to_credits",
    "premium_requests_for",
    "subscription_month_cost",
    "unpriced_models",
]

# 1 GitHub AI credit = $0.01 USD.
AI_CREDIT_USD = 0.01
# Copilot reports usage in nano AI units: 1 credit = 1e9 nano (so 1 nano = $1e-11).
NANO_PER_CREDIT = 1e9
# Default billing entity: the POC treats every member as one organization sharing a pool.
DEFAULT_BILLING_ENTITY = "org"


@dataclass
class CostContext:
    prices: list[ModelPrice] = field(default_factory=list)
    members: list[Member] = field(default_factory=list)
    seat_plans: list[SeatPlan] = field(default_factory=list)


@dataclass(kw_only=True)
class CreditsMonth:
    """Credit figures for one member-month or one pool. Overage is billed at $0.01 per credit."""

    credits_used: float  # known usage only (turns without data add nothing)
    included_credits: float
    overage_credits: float  # max(0, used - included)
    overage_usd: float  # overage_credits x AI_CREDIT_USD


@dataclass(kw_only=True)
class MemberCredits(CreditsMonth):
    turns_with_data: int  # turns with a known copilot_nano_aiu


@dataclass(kw_only=True)
class MemberMonth:
    user_name: str
    team_id: str
    month: str  # "YYYY-MM" (UTC)
    seat_plan_id: str
    seat_usd: float
    premium_used: float
    included_premium: float
    overage_requests: float
    overage_usd: float
    total_usd: float  # seat_usd + overage_usd
    turn_count: int
    api_equivalent_usd: float
    # AI credits of the member-month against the seat's own allowance (no pooling).
    credits: MemberCredits


@dataclass(kw_only=True)
class CreditPool(CreditsMonth):
    """Included credits pooled per billing entity and month."""

    month: str  # "YYYY-MM" (UTC)
    entity: str
    seats: int  # members (seats) contributing their included credits
    turns: int  # member turns in the month
    turns_with_data: int


@dataclass(kw_only=True)
class SubscriptionMonth:
    seat_usd: float
    included_premium: float
    overage_requests: float
    overage_usd: float
    total_usd: float


# ---------------------------------------------------------------------------
# AI credits


def nano_to_credits(nano: float | None) -> float | None:
    """nano AI units -> credits. None, negative or non-finite -> None (unknown)."""
    if nano is None or not is_finite(nano) or nano < 0:
        return None
    return nano / NANO_PER_CREDIT


def credits_to_usd(credits: float | None) -> float | None:
    """credits -> USD at $0.01 per credit; None stays None."""
    return None if credits is None else credits * AI_CREDIT_USD


def credits_month_cost(included_credits: float, credits_used: float) -> CreditsMonth:
    """Overage above an allowance (seat or pool), billed at $0.01 per credit."""
    included = included_credits if is_finite(included_credits) and included_credits > 0 else 0
    used = credits_used if is_finite(credits_used) and credits_used > 0 else 0
    overage = max(0, used - included)
    return CreditsMonth(credits_used=used, included_credits=included, overage_credits=overage, overage_usd=overage * AI_CREDIT_USD)


def _credits_fields(c: CreditsMonth) -> dict[str, float]:
    return {
        "credits_used": c.credits_used,
        "included_credits": c.included_credits,
        "overage_credits": c.overage_credits,
        "overage_usd": c.overage_usd,
    }


def _included_credits_of(plan: SeatPlan | None) -> float:
    return plan.included_ai_credits if plan is not None and plan.included_ai_credits is not None else 0


# ---------------------------------------------------------------------------
# Pricing


def find_price(model: str | None, prices: list[ModelPrice]) -> ModelPrice | None:
    """Resolve the price entry for a model id.
    1. Exact, case-insensitive match (whitespace-trimmed).
    2. Otherwise the longest matching prefix among entries ending in "*" ("claude-sonnet*").
    3. Otherwise None. Ties keep the first entry in `prices`.
    """
    if model is None:
        return None
    m = model.strip().lower()
    if m == "":
        return None
    for p in prices:
        if p.model.strip().lower() == m:
            return p
    best: ModelPrice | None = None
    best_len = -1
    for p in prices:
        key = p.model.strip().lower()
        if not key.endswith("*"):
            continue
        prefix = key[:-1]
        if m.startswith(prefix) and len(prefix) > best_len:
            best = p
            best_len = len(prefix)
    return best


def _tok(n: float) -> float:
    """Non-finite or negative token counts are treated as 0."""
    return n if is_finite(n) and n > 0 else 0


def api_equivalent_cost(turn: Turn, price: ModelPrice | None) -> float:
    """API-equivalent (list-price) cost of a turn, in USD.

    ASSUMPTIONS (surface in UI):
    - `input_tokens` INCLUDES cached tokens. Uncached input = max(0, input - cache_read -
      cache_creation), billed at input_per_mtok; cache reads at cache_read_per_mtok; cache
      creation at cache_write_per_mtok.
    - Reasoning tokens are already included in `output_tokens`, so they are NOT added again.
    - Unknown model (None price) => 0. Negative / non-finite token counts => 0.
    """
    if not price:
        return 0
    inp = _tok(turn.input_tokens)
    cache_read = _tok(turn.cache_read_tokens)
    cache_creation = _tok(turn.cache_creation_tokens)
    output = _tok(turn.output_tokens)
    uncached = max(0, inp - cache_read - cache_creation)
    return (
        uncached * price.input_per_mtok
        + cache_read * price.cache_read_per_mtok
        + cache_creation * price.cache_write_per_mtok
        + output * price.output_per_mtok
    ) / 1e6


def premium_requests_for(_turn: Turn, price: ModelPrice | None) -> float:
    """Estimated premium requests consumed by a turn: 1 user prompt x model multiplier.
    Unknown model => assumed multiplier 1. Negative multipliers are clamped to 0."""
    if not price:
        return 1
    m = price.premium_multiplier
    return m if is_finite(m) and m > 0 else 0


def subscription_month_cost(plan: SeatPlan | None, premium_used: float) -> SubscriptionMonth:
    """Seat + overage for one member-month."""
    if not plan:
        return SubscriptionMonth(seat_usd=0, included_premium=0, overage_requests=0, overage_usd=0, total_usd=0)
    overage_requests = max(0, premium_used - plan.included_premium_requests)
    overage_usd = overage_requests * plan.overage_per_premium_request_usd
    return SubscriptionMonth(
        seat_usd=plan.monthly_price_usd,
        included_premium=plan.included_premium_requests,
        overage_requests=overage_requests,
        overage_usd=overage_usd,
        total_usd=plan.monthly_price_usd + overage_usd,
    )


def month_of(iso: str) -> str:
    """Calendar month "YYYY-MM" in UTC. Falls back to the first 7 chars if unparseable."""
    t = parse_iso_ms(iso)
    if t is None:
        return iso[:7]
    return iso_from_ms(t)[:7]


# ---------------------------------------------------------------------------
# Ledger (shared by compute_costs / member_months)


class _Lookup:
    def __init__(self, ctx: CostContext) -> None:
        self._prices = ctx.prices
        self._price_cache: dict[str | None, ModelPrice | None] = {}
        self._members: dict[str, Member] = {}
        for m in ctx.members:
            k = m.user_name.strip().lower()
            if k not in self._members:
                self._members[k] = m
        self._plans: dict[str, SeatPlan] = {}
        for p in ctx.seat_plans:
            if p.id not in self._plans:
                self._plans[p.id] = p

    def price(self, model: str | None) -> ModelPrice | None:
        if model in self._price_cache:
            return self._price_cache[model]
        p = find_price(model, self._prices)
        self._price_cache[model] = p
        return p

    def member(self, user_name: str | None) -> Member | None:
        if user_name is None:
            return None
        return self._members.get(user_name.strip().lower())

    def plan(self, plan_id: str) -> SeatPlan | None:
        return self._plans.get(plan_id)


@dataclass
class _Group:
    member: Member
    month: str
    idx: list[int] = field(default_factory=list)
    premium: float = 0
    api: float = 0
    credits: float = 0
    credit_turns: int = 0


def _ledger(turns: list[Turn], ctx: CostContext) -> tuple[list[TurnCost], list[_Group], _Lookup]:
    lookup = _Lookup(ctx)
    costs: list[TurnCost] = []
    groups: dict[tuple[str, str], _Group] = {}

    for i, turn in enumerate(turns):
        price = lookup.price(turn.model)
        api = api_equivalent_cost(turn, price)
        premium = premium_requests_for(turn, price)
        credits = nano_to_credits(turn.copilot_nano_aiu)
        costs.append(
            TurnCost(
                turn_id=turn.id,
                api_equivalent_usd=api,
                premium_requests=premium,
                subscription_usd=0,
                ai_credits=credits,
                ai_credits_usd=credits_to_usd(credits),
            )
        )
        member = lookup.member(turn.user_name)
        if not member:
            continue  # unallocated: subscription_usd stays 0
        month = month_of(turn.started_at)
        key = (member.user_name, month)
        g = groups.get(key)
        if g is None:
            g = _Group(member=member, month=month)
            groups[key] = g
        g.idx.append(i)
        g.premium += premium
        g.api += api
        if credits is not None:
            g.credits += credits
            g.credit_turns += 1

    for g in groups.values():
        total = subscription_month_cost(lookup.plan(g.member.seat_plan_id), g.premium).total_usd
        if g.premium > 0:
            for i in g.idx:
                costs[i].subscription_usd = (total * costs[i].premium_requests) / g.premium
        else:
            each = total / len(g.idx)
            for i in g.idx:
                costs[i].subscription_usd = each

    return costs, list(groups.values()), lookup


# ---------------------------------------------------------------------------
# Public API


def compute_costs(turns: list[Turn], ctx: CostContext) -> list[TurnCost]:
    """Per-turn costs, same order as `turns`.

    Turns whose user_name is None or not a known member get subscription_usd 0 (unallocated).
    Each member-month's (seat + overage) is prorated over its turns by premium_requests; if
    that member-month consumed 0 premium requests, it is split equally.
    """
    return _ledger(turns, ctx)[0]


def _by_month_user(a: MemberMonth, b: MemberMonth) -> int:
    return first_nonzero(locale_compare(a.month, b.month), locale_compare(a.user_name, b.user_name))


def member_months(turns: list[Turn], ctx: CostContext) -> list[MemberMonth]:
    """Aggregates for every (member, UTC month) that has at least one turn. Sorted by month, user."""
    _, groups, lookup = _ledger(turns, ctx)
    out: list[MemberMonth] = []
    for g in groups:
        plan = lookup.plan(g.member.seat_plan_id)
        sub = subscription_month_cost(plan, g.premium)
        out.append(
            MemberMonth(
                user_name=g.member.user_name,
                team_id=g.member.team_id,
                month=g.month,
                seat_plan_id=g.member.seat_plan_id,
                seat_usd=sub.seat_usd,
                premium_used=g.premium,
                included_premium=sub.included_premium,
                overage_requests=sub.overage_requests,
                overage_usd=sub.overage_usd,
                total_usd=sub.total_usd,
                turn_count=len(g.idx),
                api_equivalent_usd=g.api,
                credits=MemberCredits(
                    **_credits_fields(credits_month_cost(_included_credits_of(plan), g.credits)),
                    turns_with_data=g.credit_turns,
                ),
            )
        )
    return sorted(out, key=cmp_to_key(_by_month_user))


def _unique_members(members: list[Member]) -> list[Member]:
    seen: set[str] = set()
    out: list[Member] = []
    for m in members:
        k = m.user_name.strip().lower()
        if k in seen:
            continue
        seen.add(k)
        out.append(m)
    return out


def credit_pools(
    turns: list[Turn],
    ctx: CostContext,
    months: Iterable[str] | None = None,
    entity_of: Callable[[Member], str] = lambda _m: DEFAULT_BILLING_ENTITY,
) -> list[CreditPool]:
    """Included AI credits pooled per billing entity and UTC month.

    The pool is the sum of the included credits of every seat (every member, used or idle), and
    only known usage above the pool is billed: overage = max(0, sum used - pool) x $0.01. Turns
    of non-members do not count (no seat). `months` defaults to the months of member turns;
    `entity_of` defaults to a single organization. Sorted by month, entity.
    """
    _, groups, lookup = _ledger(turns, ctx)
    members = _unique_members(ctx.members)
    month_list = sorted(set(months if months is not None else (g.month for g in groups)))
    out: list[CreditPool] = []
    for month in month_list:
        by_entity: dict[str, dict[str, float]] = {}

        def entry(e: str) -> dict[str, float]:
            x = by_entity.get(e)
            if x is None:
                x = {"seats": 0, "included": 0, "used": 0, "turns": 0, "with_data": 0}
                by_entity[e] = x
            return x

        for m in members:
            x = entry(entity_of(m))
            x["seats"] += 1
            x["included"] += _included_credits_of(lookup.plan(m.seat_plan_id))
        for g in groups:
            if g.month != month:
                continue
            x = entry(entity_of(g.member))
            x["used"] += g.credits
            x["turns"] += len(g.idx)
            x["with_data"] += g.credit_turns
        for entity, x in by_entity.items():
            out.append(
                CreditPool(
                    month=month,
                    entity=entity,
                    seats=int(x["seats"]),
                    turns=int(x["turns"]),
                    turns_with_data=int(x["with_data"]),
                    **_credits_fields(credits_month_cost(x["included"], x["used"])),
                )
            )
    return sorted(
        out,
        key=cmp_to_key(lambda a, b: first_nonzero(locale_compare(a.month, b.month), locale_compare(a.entity, b.entity))),
    )


def idle_seats(ctx: CostContext, months: Iterable[str], turns: list[Turn]) -> list[MemberMonth]:
    """Members with zero turns in a given month: full seat cost, nothing used.
    `months` are "YYYY-MM" strings (duplicates ignored). Sorted by month, user."""
    lookup = _Lookup(ctx)
    active: set[tuple[str, str]] = set()
    for t in turns:
        m = lookup.member(t.user_name)
        if m:
            active.add((m.user_name, month_of(t.started_at)))
    out: list[MemberMonth] = []
    for month in dict.fromkeys(months):
        for member in _unique_members(ctx.members):
            if (member.user_name, month) in active:
                continue
            plan = lookup.plan(member.seat_plan_id)
            sub = subscription_month_cost(plan, 0)
            out.append(
                MemberMonth(
                    user_name=member.user_name,
                    team_id=member.team_id,
                    month=month,
                    seat_plan_id=member.seat_plan_id,
                    seat_usd=sub.seat_usd,
                    premium_used=0,
                    included_premium=sub.included_premium,
                    overage_requests=0,
                    overage_usd=0,
                    total_usd=sub.total_usd,
                    turn_count=0,
                    api_equivalent_usd=0,
                    credits=MemberCredits(
                        **_credits_fields(credits_month_cost(_included_credits_of(plan), 0)), turns_with_data=0
                    ),
                )
            )
    return sorted(out, key=cmp_to_key(_by_month_user))


@dataclass
class UnpricedModel:
    model: str | None
    turns: int


def unpriced_models(turns: list[Turn], prices: list[ModelPrice]) -> list[UnpricedModel]:
    """Models (incl. None) with no matching price entry, by turn count desc."""
    cache: dict[str | None, bool] = {}
    counts: dict[str | None, int] = {}
    for t in turns:
        priced = cache.get(t.model)
        if priced is None:
            priced = find_price(t.model, prices) is not None
            cache[t.model] = priced
        if not priced:
            counts[t.model] = counts.get(t.model, 0) + 1
    out = [UnpricedModel(model=m, turns=n) for m, n in counts.items()]
    return sorted(
        out,
        key=cmp_to_key(lambda a, b: first_nonzero(b.turns - a.turns, locale_compare(a.model or "", b.model or ""))),
    )


# ---------------------------------------------------------------------------
# Display


def format_usd(n: float) -> str:
    """"$1,234.56"; values with 0 < |n| < 0.01 use 4 decimals ("$0.0042"); values with
    0 < |n| < 0.00005 render as "<$0.0001". Non-finite => "—"."""
    if not is_finite(n):
        return "—"
    a = abs(n)
    if 0 < a < 0.00005:
        return "-<$0.0001" if n < 0 else "<$0.0001"
    if 0 < a < 0.01:
        return intl_usd(n, 4)
    return intl_usd(0.0 if n == 0 else n, 2)  # avoid "-$0.00"

