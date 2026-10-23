"""Teams (`/equipos`), port of src/app/equipos/page.tsx."""

from __future__ import annotations

from collections.abc import Mapping
from functools import cmp_to_key
from typing import Any

from bis_core._js import first_nonzero, locale_compare
from bis_core.app_data import by_credits_desc, describe_period, get_period_report, group_signals, href_with, team_href
from bis_core.report import NONE_KEY, by_team, compute_totals
from bis_core.report.format import format_int, format_number, format_tokens, format_usd, plural, ratio
from bis_core.report.people import initials

from bis_cost_tracker.views import kit
from bis_cost_tracker.views.kit import box, chev, link, real_chip, td, txt

COLS = 6


def empty() -> dict[str, Any]:
    return {"empty": True, "db_empty": False, "subtitle": "", "rows": []}


def _detail(m: Any, unpriced: int) -> dict[str, Any]:
    return kit.detail_grid(
        [
            ("Tokens", [txt(format_tokens(m.tokens))]),
            ("API equivalent", kit.api_cost(m.api_equivalent_usd, m.turns, unpriced)),
            ("Premium requests (legacy)", [txt(format_number(m.premium_requests))]),
            ("With issue · with PR", [txt(f"{format_int(m.with_issue)} · {format_int(m.with_pr)}")]),
            ("Confidence", kit.confidence_mix(m.confidence, "mt-2 w-28")),
        ]
    )


def build(sp_: Mapping[str, Any]) -> dict[str, Any]:
    d = get_period_report(sp_)
    period, report = d.period, d.report
    out = empty()
    out["subtitle"] = f"Which team uses the most? · {describe_period(period)}"
    out["db_empty"] = d.db_empty
    if not report.rows:
        return out
    out["empty"] = False

    teams = by_credits_desc(by_team(report))
    totals = compute_totals(report)
    sig = group_signals(report, lambda r: r.attribution.team_id)
    total_unpriced = sum(m.turns for m in report.unpriced_models)
    idle_by_team: dict[str, float] = {}
    for s in report.idle_seats:
        idle_by_team[s.team_id] = idle_by_team.get(s.team_id, 0) + s.period_usd
    days = period.days
    active_users = {r.attribution.user_name.lower() for r in report.rows if r.attribution.user_name}
    members_by_team: dict[str, list[dict[str, Any]]] = {}
    for m in report.refs.members:
        members_by_team.setdefault(m.team_id, []).append(
            {"key": m.user_name, "initials": initials(m.display_name), "name": m.display_name, "muted": m.user_name.lower() not in active_users}
        )
    for lst in members_by_team.values():
        lst.sort(key=cmp_to_key(lambda a, b: first_nonzero(int(a["muted"]) - int(b["muted"]), locale_compare(a["name"], b["name"]))))

    rows = []
    for t in teams:
        idle = 0 if t.key == NONE_KEY else idle_by_team.get(t.key, 0)
        none = t.key == NONE_KEY
        href = href_with("/sesiones", {"days": days, "team": t.key}) if none else team_href(t.key, days)
        name_link = link(
            "" if none else t.label,
            href,
            "group inline-flex items-center gap-1 font-medium text-label hover:text-link",
            s=([txt(t.label, "text-label-3")] if none else []) + [chev("size-2.5 text-label-3 group-hover:text-link")],
        )
        people = members_by_team.get(t.key, [])
        name_cell = td(
            None,
            c="whitespace-nowrap",
            b=[
                box("flex items-center gap-3", [name_link, real_chip() if sig.real(t.key) else None]),
                box(
                    "mt-1 flex items-center gap-2.5",
                    [
                        kit.avatar_stack(people) if people else None,
                        txt(f"{plural(t.conversations, 'session', 'sessions')} · {plural(t.users, 'person', 'people')}", "text-[12.5px] text-label-3"),
                    ],
                ),
            ],
        )
        sub_cell = td([txt(format_usd(t.subscription_usd))], right=True)
        if idle > 0:
            sub_cell["b"].append(box("mt-0.5 text-[12.5px] text-warn-text", [txt(f"+ {format_usd(idle)} unused")], ti="Seats with no turns in the month, charged to the period"))
        rows.append(
            kit.row(
                [
                    name_cell,
                    td([txt(format_int(t.turns))], right=True),
                    td(kit.credits_stack(t), right=True),
                    sub_cell,
                    td([kit.meter(ratio(t.attributed, t.turns))], right=True),
                    kit.toggle_cell(),
                ],
                _detail(t, sig.unpriced(t.key)),
                rid=f"equipo-{t.key}",
            )
        )
    total_sub = td([txt(format_usd(totals.turns_subscription_usd))], right=True)
    if totals.idle_seats_usd > 0:
        total_sub["b"].append(box("mt-0.5 text-[12.5px] font-normal text-warn-text", [txt(f"+ {format_usd(totals.idle_seats_usd)} unused")]))
    rows.append(
        kit.row(
            [
                td([txt("Total")], b=[kit.sub([txt(f"{plural(totals.conversations, 'session', 'sessions')} · {plural(totals.users, 'person', 'people')}")])]),
                td([txt(format_int(totals.turns))], right=True),
                td(kit.credits_stack(totals), right=True),
                total_sub,
                td([kit.meter(ratio(totals.attributed, totals.turns))], right=True),
                kit.toggle_cell(),
            ],
            _detail(totals, total_unpriced),
            c="trow-total",
            rid="equipo-total",
        )
    )
    out["rows"] = rows
    return out
