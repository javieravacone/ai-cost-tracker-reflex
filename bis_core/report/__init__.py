"""Report layer: joins turns + attribution + cost and aggregates them for the dashboard.

Port of src/lib/report/index.ts. `load_report` is the only function doing I/O (synchronous
sqlite3 reads); every aggregation helper is pure over the returned `Report`.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, fields, replace
from functools import cmp_to_key
from typing import Any

from bis_core._js import first_nonzero, is_finite, iso_from_ms, is_integer, js_number, locale_compare, parse_iso_ms
from bis_core.attribution import (
    CONFIDENCE_LEVELS,
    AttributionContext,
    attribute,
    issue_key,
    pr_key,
    summarize_confidence,
)
from bis_core.cost import (
    CostContext,
    CreditPool,
    MemberMonth,
    UnpricedModel,
    compute_costs,
    credit_pools as compute_credit_pools,
    find_price,
    idle_seats as compute_idle_seats,
    member_months as compute_member_months,
    month_of,
    unpriced_models as compute_unpriced_models,
)
from bis_core.db import (
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
)
from bis_core.report.range import (
    DAY_OPTIONS,
    DEFAULT_DAYS,
    DateRange,
    PeriodRange,
    day_of,
    days_in_range,
    full_months_range,
    month_share,
    months_in_range,
    parse_days,
    range_from_days,
    range_from_search_params,
)
from bis_core.types import (
    Attribution,
    Confidence,
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
    TurnCost,
)

__all__ = [
    "DAY_OPTIONS",
    "DEFAULT_DAYS",
    "NONE_KEY",
    "Bucket",
    "ConversationSummary",
    "DateRange",
    "IdleSeat",
    "IssueBucket",
    "Metrics",
    "ModelBucket",
    "PeriodRange",
    "PrBucket",
    "ProjectBucket",
    "RepoCount",
    "Report",
    "ReportRefs",
    "ReportRow",
    "RowFilters",
    "Totals",
    "UserBucket",
    "by_day",
    "by_issue",
    "by_model",
    "by_pr",
    "by_project",
    "by_team",
    "by_user",
    "compute_totals",
    "conversation_key_of",
    "day_of",
    "days_in_range",
    "filter_rows",
    "full_months_range",
    "group_rows",
    "list_conversations",
    "load_conversation",
    "load_refs",
    "load_report",
    "month_share",
    "months_in_range",
    "parse_days",
    "parse_issue_key",
    "parse_pr_key",
    "range_from_days",
    "range_from_search_params",
    "summarize",
    "tokens_of",
]

# ---------------------------------------------------------------------------
# Types


@dataclass
class ReportRefs:
    teams: list[Team]
    projects: list[Project]
    repo_mappings: list[RepoMapping]
    members: list[Member]
    issues: list[Issue]
    pull_requests: list[PullRequest]
    prices: list[ModelPrice]
    seat_plans: list[SeatPlan]
    manual_assignments: list[ManualAssignment]


@dataclass
class ReportRow:
    turn: Turn
    attribution: Attribution
    cost: TurnCost
    team_name: str | None
    project_name: str | None
    user_display_name: str | None
    conversation_key: str  # conversation_id, or the turn id when the turn has no conversation
    day: str  # "YYYY-MM-DD" UTC
    tokens: int  # input (incl. cached) + output


@dataclass(kw_only=True)
class IdleSeat(MemberMonth):
    """An idle member-month plus the part of its seat that falls inside the period."""

    period_share: float  # 0..1 fraction of the month inside the range
    period_usd: float  # total_usd x period_share


@dataclass
class RepoCount:
    repo: str
    turns: int


@dataclass
class Report:
    range: DateRange | None
    rows: list[ReportRow]
    refs: ReportRefs
    member_months: list[MemberMonth]
    # AI credits pooled per billing entity, for the full months touched by the period.
    credit_pools: list[CreditPool]
    idle_seats: list[IdleSeat]
    unpriced_models: list[UnpricedModel]
    unmapped_repos: list[RepoCount]
    turns_without_repo: int
    confidence: dict[Confidence, int]
    sources: dict[str, int]


# ---------------------------------------------------------------------------
# Loading


def load_refs(db: sqlite3.Connection) -> ReportRefs:
    return ReportRefs(
        teams=list_teams(db),
        projects=list_projects(db),
        repo_mappings=list_repo_mappings(db),
        members=list_members(db),
        issues=list_issues(db),
        pull_requests=list_pull_requests(db),
        prices=list_model_prices(db),
        seat_plans=list_seat_plans(db),
        manual_assignments=list_manual_assignments(db),
    )


def conversation_key_of(t: Turn) -> str:
    return t.conversation_id if t.conversation_id is not None else t.id


def tokens_of(t: Turn) -> int:
    def n(x: Any) -> Any:
        return x if is_finite(x) and x > 0 else 0

    return n(t.input_tokens) + n(t.output_tokens)


def _shallow(obj: Any) -> dict[str, Any]:
    return {f.name: getattr(obj, f.name) for f in fields(obj)}


def load_report(
    db: sqlite3.Connection,
    from_: str | DateRange | None = None,
    to: str | None = None,
) -> Report:
    """Loads turns in [from_, to) and joins attribution + cost.

    `from_` may also be a DateRange / PeriodRange. Subscription cost is prorated per
    member-month over ALL turns of that month, so costs are computed over the full calendar
    months touched by the range and then the in-range turns are kept. `member_months` therefore
    describe complete months. Idle seats are imputed to the period by the fraction of the month
    that falls inside the range. Without from_/to every turn is loaded and idle seats count in
    full for every month that has turns.
    """
    if isinstance(from_, DateRange):
        from_, to = from_.from_, from_.to
    refs = load_refs(db)
    rng = DateRange(from_=from_, to=to) if (from_ and to) else None

    turns = list_turns(db, from_, to)
    full = full_months_range(rng) if rng else None
    cost_turns = list_turns(db, full.from_, full.to) if full else turns

    cost_ctx = CostContext(prices=refs.prices, members=refs.members, seat_plans=refs.seat_plans)
    costs = compute_costs(cost_turns, cost_ctx)
    cost_by_id = {c.turn_id: c for c in costs}

    attributions = attribute(
        turns,
        AttributionContext(
            repo_mappings=refs.repo_mappings,
            members=refs.members,
            issues=refs.issues,
            pull_requests=refs.pull_requests,
            manual_assignments=refs.manual_assignments,
        ),
    )

    team_name = {t.id: t.name for t in refs.teams}
    project_name = {p.id: p.name for p in refs.projects}
    display_name = {m.user_name.lower(): m.display_name for m in refs.members}

    rows: list[ReportRow] = []
    for turn, a in zip(turns, attributions):
        cost = cost_by_id.get(turn.id) or TurnCost(
            turn_id=turn.id,
            api_equivalent_usd=0,
            premium_requests=0,
            subscription_usd=0,
            ai_credits=None,
            ai_credits_usd=None,
        )
        rows.append(
            ReportRow(
                turn=turn,
                attribution=a,
                cost=cost,
                team_name=team_name.get(a.team_id, a.team_id) if a.team_id else None,
                project_name=project_name.get(a.project_id, a.project_id) if a.project_id else None,
                user_display_name=display_name.get(a.user_name.lower()) if a.user_name else None,
                conversation_key=conversation_key_of(turn),
                day=day_of(turn.started_at),
                tokens=tokens_of(turn),
            )
        )

    months = months_in_range(rng) if rng else sorted({month_of(t.started_at) for t in turns})
    month_set = set(months)
    idle: list[IdleSeat] = []
    for m in compute_idle_seats(cost_ctx, months, cost_turns):
        share = month_share(m.month, rng) if rng else 1
        idle.append(IdleSeat(**_shallow(m), period_share=share, period_usd=m.total_usd * share))

    unmapped: dict[str, int] = {}
    turns_without_repo = 0
    for r in rows:
        if not r.attribution.repo:
            turns_without_repo += 1
        elif not r.attribution.project_id:
            unmapped[r.attribution.repo] = unmapped.get(r.attribution.repo, 0) + 1

    sources: dict[str, int] = {"seed": 0, "langsmith": 0}
    for t in turns:
        sources[t.source] = sources.get(t.source, 0) + 1

    return Report(
        range=rng,
        rows=rows,
        refs=refs,
        member_months=[m for m in compute_member_months(cost_turns, cost_ctx) if m.month in month_set],
        credit_pools=compute_credit_pools(cost_turns, cost_ctx, months),
        idle_seats=idle,
        unpriced_models=compute_unpriced_models(turns, refs.prices),
        unmapped_repos=sorted(
            (RepoCount(repo=k, turns=v) for k, v in unmapped.items()),
            key=cmp_to_key(lambda a, b: first_nonzero(b.turns - a.turns, locale_compare(a.repo, b.repo))),
        ),
        turns_without_repo=turns_without_repo,
        confidence=summarize_confidence(attributions),
        sources=sources,
    )


# ---------------------------------------------------------------------------
# Metrics


def _empty_confidence() -> dict[Confidence, int]:
    return {c: 0 for c in CONFIDENCE_LEVELS}


@dataclass(kw_only=True)
class Metrics:
    turns: int = 0
    conversations: int = 0
    users: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    tokens: int = 0
    api_equivalent_usd: float = 0
    subscription_usd: float = 0
    premium_requests: float = 0
    # Real Copilot consumption: sum of KNOWN AI credits (turns without data add nothing).
    ai_credits: float = 0
    ai_credits_usd: float = 0  # gross, list price, before the included pool
    credit_turns: int = 0  # turns with a known value (ai_credits is not None)
    credit_partial_turns: int = 0  # known but only some chat calls reported it (lower bound)
    with_issue: int = 0
    with_pr: int = 0
    attributed: int = 0  # turns with an issue or a PR
    confidence: dict[Confidence, int] = field(default_factory=_empty_confidence)


def _metrics_fields(m: Metrics) -> dict[str, Any]:
    return {f.name: getattr(m, f.name) for f in fields(Metrics)}


@dataclass(kw_only=True)
class Bucket(Metrics):
    key: str
    label: str


# Sentinel key used for rows whose grouping key is None.
NONE_KEY = "__none__"


def _nonneg(x: Any) -> Any:
    v = x if is_finite(x) else 0  # `x || 0` (NaN -> 0)
    return max(0, v)


class _Acc:
    def __init__(self) -> None:
        self.m = Metrics()
        self._convs: set[str] = set()
        self._users: set[str] = set()

    def add(self, r: ReportRow) -> None:
        m = self.m
        m.turns += 1
        m.input_tokens += _nonneg(r.turn.input_tokens)
        m.output_tokens += _nonneg(r.turn.output_tokens)
        m.tokens += r.tokens
        m.api_equivalent_usd += r.cost.api_equivalent_usd
        m.subscription_usd += r.cost.subscription_usd
        m.premium_requests += r.cost.premium_requests
        if r.cost.ai_credits is not None:
            m.ai_credits += r.cost.ai_credits
            m.ai_credits_usd += r.cost.ai_credits_usd if r.cost.ai_credits_usd is not None else 0
            m.credit_turns += 1
            cov = r.turn.copilot_usage_coverage
            if cov is not None and cov < 1:
                m.credit_partial_turns += 1
        if r.attribution.issue_key:
            m.with_issue += 1
        if r.attribution.pr_key:
            m.with_pr += 1
        if r.attribution.issue_key or r.attribution.pr_key:
            m.attributed += 1
        m.confidence[r.attribution.confidence] += 1
        self._convs.add(r.conversation_key)
        if r.attribution.user_name:
            self._users.add(r.attribution.user_name.lower())

    def metrics(self) -> Metrics:
        return replace(self.m, conversations=len(self._convs), users=len(self._users), confidence=dict(self.m.confidence))


def summarize(rows: list[ReportRow]) -> Metrics:
    acc = _Acc()
    for r in rows:
        acc.add(r)
    return acc.metrics()


@dataclass(kw_only=True)
class Totals(Metrics):
    # Subscription imputed to the period's turns (seat + overage, prorated).
    turns_subscription_usd: float
    # Seats without any turn in a month, imputed by the share of the month inside the period.
    idle_seats_usd: float
    # subscription_usd = turns_subscription_usd + idle_seats_usd.
    pct_with_issue: float  # 0..1
    pct_with_pr: float  # 0..1


def compute_totals(report: Report) -> Totals:
    m = summarize(report.rows)
    idle_usd = 0.0
    for x in report.idle_seats:
        idle_usd += x.period_usd
    base = _metrics_fields(m)
    base["subscription_usd"] = m.subscription_usd + idle_usd
    return Totals(
        **base,
        turns_subscription_usd=m.subscription_usd,
        idle_seats_usd=idle_usd,
        pct_with_issue=m.with_issue / m.turns if m.turns else 0,
        pct_with_pr=m.with_pr / m.turns if m.turns else 0,
    )


# ---------------------------------------------------------------------------
# Grouping


def _by_cost_desc(a: Bucket, b: Bucket) -> float:
    return first_nonzero(
        b.api_equivalent_usd - a.api_equivalent_usd,
        b.subscription_usd - a.subscription_usd,
        b.turns - a.turns,
        locale_compare(a.label, b.label),
    )


def group_rows(
    rows: list[ReportRow],
    key_of: Callable[[ReportRow], str | None],
    label_of: Callable[[str, ReportRow], str],
    none_label: str,
) -> list[Bucket]:
    """Generic group-by. Rows whose key is None land in NONE_KEY with `none_label`.
    Sorted by API-equivalent cost desc, with the NONE bucket always last."""
    groups: dict[str, tuple[_Acc, ReportRow]] = {}
    for r in rows:
        k = key_of(r)
        key = NONE_KEY if k is None else k
        g = groups.get(key)
        if g is None:
            g = (_Acc(), r)
            groups[key] = g
        g[0].add(r)
    buckets = [
        Bucket(key=key, label=none_label if key == NONE_KEY else label_of(key, sample), **_metrics_fields(acc.metrics()))
        for key, (acc, sample) in groups.items()
    ]
    return sorted(
        buckets,
        key=cmp_to_key(lambda a, b: first_nonzero(int(a.key == NONE_KEY) - int(b.key == NONE_KEY), _by_cost_desc(a, b))),
    )


def by_team(report: Report) -> list[Bucket]:
    return group_rows(
        report.rows,
        lambda r: r.attribution.team_id,
        lambda k, r: r.team_name if r.team_name is not None else k,
        "No team",
    )


@dataclass(kw_only=True)
class ProjectBucket(Bucket):
    no_issue: Metrics  # turns of this project with no issue ("No issue" bucket)
    distinct_issues: int
    distinct_prs: int


def by_project(report: Report) -> list[ProjectBucket]:
    buckets = group_rows(
        report.rows,
        lambda r: r.attribution.project_id,
        lambda k, r: r.project_name if r.project_name is not None else k,
        "No project (unmapped repo or no repo)",
    )
    out: list[ProjectBucket] = []
    for b in buckets:
        rows = [
            r for r in report.rows if (r.attribution.project_id if r.attribution.project_id is not None else NONE_KEY) == b.key
        ]
        out.append(
            ProjectBucket(
                **_shallow(b),
                no_issue=summarize([r for r in rows if not r.attribution.issue_key]),
                distinct_issues=len({r.attribution.issue_key for r in rows if r.attribution.issue_key}),
                distinct_prs=len({r.attribution.pr_key for r in rows if r.attribution.pr_key}),
            )
        )
    return out


@dataclass(kw_only=True)
class ModelBucket(Bucket):
    priced: bool
    premium_multiplier: float | None


def by_model(report: Report) -> list[ModelBucket]:
    out: list[ModelBucket] = []
    for b in group_rows(report.rows, lambda r: r.turn.model, lambda k, _r: k, "(no model)"):
        price = None if b.key == NONE_KEY else find_price(b.key, report.refs.prices)
        out.append(
            ModelBucket(
                **_shallow(b),
                priced=price is not None,
                premium_multiplier=price.premium_multiplier if price is not None else None,
            )
        )
    return out


@dataclass(kw_only=True)
class UserBucket(Bucket):
    user_name: str | None
    team_name: str | None
    seat_plan_id: str | None
    is_member: bool


def by_user(report: Report) -> list[UserBucket]:
    members = {m.user_name.lower(): m for m in report.refs.members}
    team_name = {t.id: t.name for t in report.refs.teams}

    def label(k: str, r: ReportRow) -> str:
        if r.user_display_name is not None:
            return r.user_display_name
        return r.attribution.user_name if r.attribution.user_name is not None else k

    out: list[UserBucket] = []
    for b in group_rows(
        report.rows,
        lambda r: r.attribution.user_name.lower() if r.attribution.user_name is not None else None,
        label,
        "(unknown user)",
    ):
        m = None if b.key == NONE_KEY else members.get(b.key)
        out.append(
            UserBucket(
                **_shallow(b),
                user_name=None if b.key == NONE_KEY else (m.user_name if m else b.key),
                team_name=team_name.get(m.team_id, m.team_id) if m else None,
                seat_plan_id=m.seat_plan_id if m else None,
                is_member=bool(m),
            )
        )
    return out


def by_day(report: Report) -> list[Bucket]:
    """One bucket per UTC day; with a range every day is present (zeros included), oldest first."""
    buckets = group_rows(report.rows, lambda r: r.day, lambda k, _r: k, "")
    by_key = {b.key: b for b in buckets}
    days = days_in_range(report.range) if report.range else sorted(by_key.keys())
    return [by_key.get(day) or Bucket(key=day, label=day, **_metrics_fields(summarize([]))) for day in days]


# ---------------------------------------------------------------------------
# Issues & PRs


def _parse_key(key: str, sep: str) -> dict[str, Any] | None:
    i = key.rfind(sep)
    n = js_number(key[i + 1 :])
    if i > 0 and is_integer(n):
        return {"repo": key[:i], "number": int(n)}
    return None


def parse_issue_key(key: str) -> dict[str, Any] | None:
    """"owner/name#12" -> {"repo": "owner/name", "number": 12}; None when unparseable."""
    return _parse_key(key, "#")


def parse_pr_key(key: str) -> dict[str, Any] | None:
    """"owner/name!45" -> {"repo": "owner/name", "number": 45}; None when unparseable."""
    return _parse_key(key, "!")


@dataclass(kw_only=True)
class IssueBucket(Bucket):
    repo: str
    number: int
    issue: Issue | None  # None = issue not synced from GitHub
    project_id: str | None
    project_name: str | None
    pr_keys: list[str]  # PR keys seen on this issue's turns plus synced PRs that link it


def _lower_repo_issue_key(repo: str, n: int) -> str:
    return issue_key(repo.lower(), n)


def by_issue(report: Report) -> list[IssueBucket]:
    issues = {_lower_repo_issue_key(i.repo, i.number): i for i in report.refs.issues}
    linking_prs: dict[str, dict[str, None]] = {}
    for pr in report.refs.pull_requests:
        for n in pr.linked_issues:
            k = _lower_repo_issue_key(pr.repo, n)
            linking_prs.setdefault(k, {})[pr_key(pr.repo.lower(), pr.number)] = None
    rows = [r for r in report.rows if r.attribution.issue_key]
    out: list[IssueBucket] = []
    for b in group_rows(rows, lambda r: r.attribution.issue_key, lambda k, _r: k, ""):
        parsed = parse_issue_key(b.key) or {"repo": b.key, "number": 0}
        own = [r for r in rows if r.attribution.issue_key == b.key]
        prs = dict(linking_prs.get(b.key, {}))
        for r in own:
            if r.attribution.pr_key:
                prs[r.attribution.pr_key] = None
        sample = own[0] if own else None
        out.append(
            IssueBucket(
                **_shallow(b),
                repo=parsed["repo"],
                number=parsed["number"],
                issue=issues.get(b.key),
                project_id=sample.attribution.project_id if sample else None,
                project_name=sample.project_name if sample else None,
                pr_keys=sorted(prs),
            )
        )
    return out


@dataclass(kw_only=True)
class PrBucket(Bucket):
    repo: str
    number: int
    pr: PullRequest | None  # None = PR not synced from GitHub
    issue_keys: list[str]  # the PR's linked issues plus issues seen on its turns
    project_name: str | None


def by_pr(report: Report) -> list[PrBucket]:
    prs = {pr_key(p.repo.lower(), p.number): p for p in report.refs.pull_requests}
    rows = [r for r in report.rows if r.attribution.pr_key]
    out: list[PrBucket] = []
    for b in group_rows(rows, lambda r: r.attribution.pr_key, lambda k, _r: k, ""):
        parsed = parse_pr_key(b.key) or {"repo": b.key, "number": 0}
        pr = prs.get(b.key)
        own = [r for r in rows if r.attribution.pr_key == b.key]
        keys: dict[str, None] = {issue_key(parsed["repo"], n): None for n in pr.linked_issues} if pr else {}
        for r in own:
            if r.attribution.issue_key:
                keys[r.attribution.issue_key] = None
        out.append(
            PrBucket(
                **_shallow(b),
                repo=parsed["repo"],
                number=parsed["number"],
                pr=pr,
                issue_keys=sorted(keys),
                project_name=own[0].project_name if own else None,
            )
        )
    return out


# ---------------------------------------------------------------------------
# Conversations


@dataclass
class RowFilters:
    team: str | None = None  # team id, or NONE_KEY
    project: str | None = None  # project id, or NONE_KEY
    user: str | None = None  # user_name (case-insensitive), or NONE_KEY
    issue: str | None = None  # issue key
    pr: str | None = None  # PR key
    no_issue: bool = False  # only turns without issue


def _matches(value: str | None, wanted: str | None, ci: bool = False) -> bool:
    if wanted is None or wanted == "":
        return True
    if wanted == NONE_KEY:
        return value is None
    if value is None:
        return False
    return value.lower() == wanted.lower() if ci else value == wanted


def filter_rows(rows: list[ReportRow], f: RowFilters | Mapping[str, Any] | None = None, **kwargs: Any) -> list[ReportRow]:
    """Filters rows by team / project / user / issue / PR / no_issue (RowFilters, mapping or kwargs)."""
    if f is None:
        f = RowFilters(**kwargs)
    elif isinstance(f, Mapping):
        f = RowFilters(**f)
    return [
        r
        for r in rows
        if _matches(r.attribution.team_id, f.team)
        and _matches(r.attribution.project_id, f.project)
        and _matches(r.attribution.user_name, f.user, True)
        and _matches(r.attribution.issue_key, f.issue)
        and _matches(r.attribution.pr_key, f.pr)
        and (not f.no_issue or r.attribution.issue_key is None)
    ]


@dataclass(kw_only=True)
class ConversationSummary(Metrics):
    key: str
    first_at: str
    last_at: str
    user_name: str | None
    user_display_name: str | None
    team_name: str | None
    project_names: list[str]
    repos: list[str]
    branches: list[str]
    models: list[str]
    issue_keys: list[str]
    pr_keys: list[str]


def _uniq(xs: list[str | None]) -> list[str]:
    return sorted({x for x in xs if x})


def list_conversations(rows: list[ReportRow]) -> list[ConversationSummary]:
    """One entry per conversation, most recent activity first."""
    groups: dict[str, list[ReportRow]] = {}
    for r in rows:
        groups.setdefault(r.conversation_key, []).append(r)
    out: list[ConversationSummary] = []
    for key, g in groups.items():
        starts = sorted(r.turn.started_at for r in g)
        first = next(r for r in g if r.turn.started_at == starts[0])
        out.append(
            ConversationSummary(
                key=key,
                **_metrics_fields(summarize(g)),
                first_at=starts[0],
                last_at=starts[-1],
                user_name=first.attribution.user_name,
                user_display_name=first.user_display_name,
                team_name=first.team_name,
                project_names=_uniq([r.project_name for r in g]),
                repos=_uniq([r.attribution.repo for r in g]),
                branches=_uniq([r.turn.branch for r in g]),
                models=_uniq([r.turn.model for r in g]),
                issue_keys=_uniq([r.attribution.issue_key for r in g]),
                pr_keys=_uniq([r.attribution.pr_key for r in g]),
            )
        )
    return sorted(
        out,
        key=cmp_to_key(lambda a, b: first_nonzero(locale_compare(b.last_at, a.last_at), locale_compare(a.key, b.key))),
    )


def load_conversation(db: sqlite3.Connection, key: str, turns: list[Turn]) -> Report | None:
    """Rows of one conversation (or of a single turn without conversation), with costs computed
    over the full months they belong to so subscription proration matches the dashboard."""
    if not turns:
        return None
    starts = [t for t in (parse_iso_ms(x.started_at) for x in turns) if t is not None]
    if not starts:
        return None
    report = load_report(db, iso_from_ms(min(starts)), iso_from_ms(max(starts) + 1))
    return replace(report, rows=[r for r in report.rows if r.conversation_key == key])
