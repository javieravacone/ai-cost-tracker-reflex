"""Drill-down aggregations for the team and person detail pages (Team -> Person -> Session).

Port of src/lib/report/people.ts. Pure over a loaded `Report` (no I/O): they reuse the row
grouping helpers of the report layer on the subset of rows that belongs to the team or person.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, fields, replace
from functools import cmp_to_key
from typing import Any

from bis_core._js import first_nonzero, iso_from_ms, locale_compare, parse_iso_ms
from bis_core.cost import month_of
from bis_core.report import (
    NONE_KEY,
    Bucket,
    ConversationSummary,
    IssueBucket,
    Metrics,
    ModelBucket,
    ProjectBucket,
    Report,
    ReportRow,
    by_day,
    by_issue,
    by_model,
    by_project,
    list_conversations,
    summarize,
)
from bis_core.types import Member, Team

__all__ = [
    "PersonDetail",
    "PersonRef",
    "SeatUsage",
    "TeamDetail",
    "TeamMemberStat",
    "TopShare",
    "initials",
    "person_detail",
    "team_detail",
]

# ---------------------------------------------------------------------------
# Shared


@dataclass
class TopShare:
    """The leading item of a breakdown and its share (0..1) of the parent total."""

    key: str
    label: str
    share: float  # by AI credits when the parent has credit data, otherwise by turns


def _by_credits_then_turns(a: Any, b: Any) -> float:
    """Real consumption first (AI credits), then turns, then label; NONE last."""
    return first_nonzero(
        int(a.key == NONE_KEY) - int(b.key == NONE_KEY),
        b.ai_credits - a.ai_credits,
        b.turns - a.turns,
        locale_compare(a.label, b.label),
    )


def _sort_by_credits(xs: list[Any]) -> list[Any]:
    return sorted(xs, key=cmp_to_key(_by_credits_then_turns))


def _top_project_of(rows: list[ReportRow], report: Report) -> TopShare | None:
    """Leading project of a set of rows (NONE included only when it is the only one)."""
    if not rows:
        return None
    projects = _sort_by_credits(by_project(replace(report, rows=rows)))
    m = summarize(rows)
    use_credits = m.ai_credits > 0
    top = next((p for p in projects if p.key != NONE_KEY), projects[0] if projects else None)
    if top is None:
        return None
    return TopShare(
        key=top.key,
        label="No project" if top.key == NONE_KEY else top.label,
        share=top.ai_credits / m.ai_credits if use_credits else top.turns / m.turns,
    )


def _last_at_of(rows: list[ReportRow]) -> str | None:
    last: str | None = None
    for r in rows:
        if last is None or r.turn.started_at > last:
            last = r.turn.started_at
    return last


def _first_at_of(rows: list[ReportRow]) -> str | None:
    first: str | None = None
    for r in rows:
        if first is None or r.turn.started_at < first:
            first = r.turn.started_at
    return first


def _active_days_of(rows: list[ReportRow]) -> int:
    return len({r.day for r in rows})


def _is_real(rows: list[ReportRow]) -> bool:
    return any(r.turn.source == "langsmith" for r in rows)


def _user_key(r: ReportRow) -> str:
    return r.attribution.user_name.lower() if r.attribution.user_name is not None else NONE_KEY


def _metrics_fields(m: Metrics) -> dict[str, Any]:
    return {f.name: getattr(m, f.name) for f in fields(Metrics)}


# ---------------------------------------------------------------------------
# Team


@dataclass(kw_only=True)
class TeamMemberStat(Metrics):
    key: str  # lowercased user_name, or NONE_KEY for turns without an identified person
    user_name: str | None
    label: str
    is_member: bool  # member of THIS team
    other_team_name: str | None  # team the person belongs to when it is not this one
    seat_plan_id: str | None
    active_days: int
    last_at: str | None
    top_project: TopShare | None
    real: bool


@dataclass
class TeamDetail:
    team: Team
    totals: Metrics
    pct_with_issue: float  # 0..1
    member_count: int  # members of the team (refs)
    active_members: int  # how many of them (or guests) have turns in the period
    members: list[TeamMemberStat]  # members (zero activity included), then guests, then NONE
    projects: list[ProjectBucket]
    issues: list[IssueBucket]
    last_at: str | None
    real: bool


def team_detail(report: Report, team_id: str) -> TeamDetail | None:
    """Detail of one team: every row attributed to it, split by person. Members without turns
    are listed (zero metrics) so idle seats stay visible. None when the team is neither in the
    refs nor in any row (unknown id)."""
    rows = [r for r in report.rows if r.attribution.team_id == team_id]
    ref = next((t for t in report.refs.teams if t.id == team_id), None)
    if ref is None and not rows:
        return None
    if ref is not None:
        team = ref
    else:
        name = rows[0].team_name if rows and rows[0].team_name is not None else team_id
        team = Team(id=team_id, name=name)

    team_name = {t.id: t.name for t in report.refs.teams}
    member_by_user = {m.user_name.lower(): m for m in report.refs.members}
    team_members = [m for m in report.refs.members if m.team_id == team_id]

    rows_by_user: dict[str, list[ReportRow]] = {}
    for m in team_members:
        rows_by_user[m.user_name.lower()] = []
    for r in rows:
        rows_by_user.setdefault(_user_key(r), []).append(r)

    members: list[TeamMemberStat] = []
    for key, g in rows_by_user.items():
        mem: Member | None = None if key == NONE_KEY else member_by_user.get(key)
        sample = g[0] if g else None
        is_member = mem is not None and mem.team_id == team_id
        if key == NONE_KEY:
            user_name = None
            label = "Unidentified person"
        else:
            user_name = mem.user_name if mem else (sample.attribution.user_name if sample and sample.attribution.user_name is not None else key)
            if mem:
                label = mem.display_name
            elif sample and sample.user_display_name is not None:
                label = sample.user_display_name
            elif sample and sample.attribution.user_name is not None:
                label = sample.attribution.user_name
            else:
                label = key
        members.append(
            TeamMemberStat(
                key=key,
                **_metrics_fields(summarize(g)),
                user_name=user_name,
                label=label,
                is_member=is_member,
                other_team_name=team_name.get(mem.team_id, mem.team_id) if mem and not is_member else None,
                seat_plan_id=mem.seat_plan_id if mem else None,
                active_days=_active_days_of(g),
                last_at=_last_at_of(g),
                top_project=_top_project_of(g, report),
                real=_is_real(g),
            )
        )

    members.sort(
        key=cmp_to_key(
            lambda a, b: first_nonzero(
                int(a.key == NONE_KEY) - int(b.key == NONE_KEY),
                int(a.turns == 0) - int(b.turns == 0),
                int(not a.is_member) - int(not b.is_member),
                _by_credits_then_turns(a, b),
            )
        )
    )

    totals = summarize(rows)
    subset = replace(report, rows=rows)
    return TeamDetail(
        team=team,
        totals=totals,
        pct_with_issue=totals.with_issue / totals.turns if totals.turns else 0,
        member_count=len(team_members),
        active_members=len([m for m in members if m.key != NONE_KEY and m.turns > 0]),
        members=members,
        projects=_sort_by_credits(by_project(subset)),
        issues=_sort_by_credits(by_issue(subset)),
        last_at=_last_at_of(rows),
        real=_is_real(rows),
    )


# ---------------------------------------------------------------------------
# Person


@dataclass
class PersonRef:
    user_name: str
    display_name: str
    is_member: bool
    team_id: str | None
    team_name: str | None
    seat_plan_id: str | None
    seat_plan_name: str | None


@dataclass
class SeatUsage:
    """AI credits of the person's seat in one month against the credits its plan includes."""

    month: str  # "YYYY-MM"
    credits_used: float
    included_credits: float
    share: float  # credits_used / included_credits (0 when nothing is included)
    overage_credits: float
    turn_count: int
    turns_with_data: int


@dataclass
class PersonDetail:
    person: PersonRef
    totals: Metrics
    cache_read_tokens: int
    active_days: int
    first_at: str | None
    last_at: str | None
    top_model: TopShare | None
    projects: list[ProjectBucket]
    issues: list[IssueBucket]
    models: list[ModelBucket]
    daily: list[Bucket]  # one bucket per day of the period (zeros included)
    conversations: list[ConversationSummary]  # newest first
    seat: SeatUsage | None  # seat usage of the last month of the period; None for non-members
    real: bool


def _report_month(report: Report) -> str | None:
    """Last calendar month of the report (the month of its last instant), or of its latest row."""
    if report.range:
        to = parse_iso_ms(report.range.to)
        return month_of(iso_from_ms(to - 1)) if to is not None else None
    last = _last_at_of(report.rows)
    return month_of(last) if last else None


def person_detail(report: Report, user_name: str, known: bool = False) -> PersonDetail | None:
    """Detail of one person (user_name, case-insensitive), over every row of that user in the
    report regardless of the team the turn was attributed to. None when the user is neither a
    member nor present in any row, unless `known` is set (e.g. turns exist outside the period)."""
    wanted = user_name.lower()
    rows = [r for r in report.rows if r.attribution.user_name is not None and r.attribution.user_name.lower() == wanted]
    member = next((m for m in report.refs.members if m.user_name.lower() == wanted), None)
    if member is None and not rows and not known:
        return None

    team_name = {t.id: t.name for t in report.refs.teams}
    plan = next((p for p in report.refs.seat_plans if p.id == member.seat_plan_id), None) if member else None
    # Non-members: the team their turns are attributed to most often.
    team_id = member.team_id if member and member.team_id is not None else None
    if not team_id:
        counts: dict[str, int] = {}
        for r in rows:
            if r.attribution.team_id:
                counts[r.attribution.team_id] = counts.get(r.attribution.team_id, 0) + 1
        ranked = sorted(counts.items(), key=cmp_to_key(lambda a, b: first_nonzero(b[1] - a[1], locale_compare(a[0], b[0]))))
        team_id = ranked[0][0] if ranked else None

    first = rows[0] if rows else None
    if member:
        p_user, p_display = member.user_name, member.display_name
    else:
        p_user = first.attribution.user_name if first and first.attribution.user_name is not None else user_name
        if first and first.user_display_name is not None:
            p_display = first.user_display_name
        elif first and first.attribution.user_name is not None:
            p_display = first.attribution.user_name
        else:
            p_display = user_name
    if team_id:
        if team_id in team_name:
            p_team_name: str | None = team_name[team_id]
        else:
            hit = next((r for r in rows if r.attribution.team_id == team_id), None)
            p_team_name = hit.team_name if hit and hit.team_name is not None else team_id
    else:
        p_team_name = None
    person = PersonRef(
        user_name=p_user,
        display_name=p_display,
        is_member=member is not None,
        team_id=team_id,
        team_name=p_team_name,
        seat_plan_id=member.seat_plan_id if member else None,
        seat_plan_name=plan.name if plan else (member.seat_plan_id if member else None),
    )

    seat: SeatUsage | None = None
    month = _report_month(report)
    if member and month:
        mm = next((m for m in report.member_months if m.month == month and m.user_name.lower() == wanted), None)
        included = mm.credits.included_credits if mm else (plan.included_ai_credits if plan else 0)
        used = mm.credits.credits_used if mm else 0
        seat = SeatUsage(
            month=month,
            credits_used=used,
            included_credits=included,
            share=used / included if included > 0 else 0,
            overage_credits=mm.credits.overage_credits if mm else max(0, used - included),
            turn_count=mm.turn_count if mm else 0,
            turns_with_data=mm.credits.turns_with_data if mm else 0,
        )

    subset = replace(report, rows=rows)
    totals = summarize(rows)
    models = sorted(by_model(subset), key=cmp_to_key(_by_credits_then_turns))
    # "Most used" = most turns (credits order the list).
    top: ModelBucket | None = None
    for m in models:
        if m.key == NONE_KEY:
            continue
        if top is None or m.turns > top.turns:
            top = m
    cache_read = 0
    for r in rows:
        v = r.turn.cache_read_tokens
        cache_read += max(0, v if v else 0)
    return PersonDetail(
        person=person,
        totals=totals,
        cache_read_tokens=cache_read,
        active_days=_active_days_of(rows),
        first_at=_first_at_of(rows),
        last_at=_last_at_of(rows),
        top_model=TopShare(key=top.key, label=top.label, share=top.turns / totals.turns if totals.turns else 0) if top else None,
        projects=_sort_by_credits(by_project(subset)),
        issues=_sort_by_credits(by_issue(subset)),
        models=models,
        daily=by_day(subset),
        conversations=list_conversations(rows),
        seat=seat,
        real=_is_real(rows),
    )


def initials(name: str) -> str:
    """Initials for an avatar: "Ana Ruiz" -> "AR", "javieravacone" -> "JA", "" -> "?"."""
    words = re.sub(r"[._-]+", " ", name).split()
    if not words:
        return "?"
    if len(words) == 1:
        return words[0][:2].upper()
    return (words[0][0] + words[-1][0]).upper()
