"""People (`/personas`), port of src/app/personas/page.tsx."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from bis_core.app_data import by_credits_desc, describe_period, get_period_report, group_signals, href_with, person_href
from bis_core.report import NONE_KEY, by_user
from bis_core.report.format import (
    format_credits,
    format_int,
    format_month,
    format_number,
    format_pct,
    format_tokens,
    format_usd,
    plural,
    ratio,
)
from bis_core.report.people import initials

from bis_cost_tracker.views import kit
from bis_cost_tracker.views.kit import box, chev, chip, link, muted, real_chip, sp, td, txt

LOW_USAGE = 0.1


def empty() -> dict[str, Any]:
    return {
        "empty": True,
        "db_empty": False,
        "subtitle": "",
        "rows": [],
        "has_pools": False,
        "pools": [],
        "has_idle": False,
        "idle_total": "",
        "idle": [],
        "mm_hint": "",
        "mm": [],
        "low_usage": format_pct(LOW_USAGE),
    }


def _first_upper(s: str) -> str:
    return s[:1].upper() + s[1:]


def build(sp_: Mapping[str, Any]) -> dict[str, Any]:
    d = get_period_report(sp_)
    period, report = d.period, d.report
    out = empty()
    out["subtitle"] = f"Who uses Copilot, and are seats being used? Select a person to see their profile · {describe_period(period)}"
    out["db_empty"] = d.db_empty
    if not report.rows and not report.idle_seats:
        return out
    out["empty"] = False

    days = period.days
    users = by_credits_desc(by_user(report))
    sig = group_signals(report, lambda r: r.attribution.user_name.lower() if r.attribution.user_name else None)
    display_name = {m.user_name: m.display_name for m in report.refs.members}
    team_name = {t.id: t.name for t in report.refs.teams}
    plan_name = {p.id: p.name for p in report.refs.seat_plans}
    idle_total = sum(x.period_usd for x in report.idle_seats)
    low_usage = [m for m in report.member_months if m.included_premium > 0 and m.premium_used / m.included_premium < LOW_USAGE]

    rows = []
    for u in users:
        none = u.key == NONE_KEY
        meta = [x for x in [u.team_name, u.user_name if u.user_name and u.user_name != u.label else None, plan_name.get(u.seat_plan_id, u.seat_plan_id) if u.seat_plan_id else None] if x]
        href = href_with("/sesiones", {"days": days, "user": u.key}) if none else person_href(u.user_name or u.key, days)
        name_line = box(
            "flex items-center gap-2",
            [
                link(
                    "" if none else u.label,
                    href,
                    "group inline-flex items-center gap-1 font-medium text-label hover:text-link",
                    s=([txt(u.label, "text-label-3")] if none else []) + [chev("size-2.5 text-label-3 group-hover:text-link")],
                ),
                real_chip() if sig.real(u.key) else None,
                chip("not a member", "warn") if not none and not u.is_member else None,
            ],
        )
        person = td(
            None,
            c="whitespace-nowrap",
            b=[box("flex items-center gap-3", [kit.avatar("?" if none else initials(u.label), muted_=none)], b=[box("min-w-0", b=[name_line, kit.sub([txt(" · ".join(meta))]) if meta else None])])],
        )
        rows.append(
            kit.row(
                [
                    person,
                    td([txt(format_int(u.turns))], right=True, b=[kit.sub([txt(plural(u.conversations, "session", "sessions"))])]),
                    td(kit.credits_stack(u), right=True),
                    td([txt(format_usd(u.subscription_usd))], right=True),
                    td([kit.meter(ratio(u.with_issue, u.turns))], right=True),
                    kit.toggle_cell(),
                ],
                kit.detail_grid(
                    [
                        ("Team", [txt(u.team_name)] if u.team_name else [muted("—")]),
                        ("Tokens", [txt(format_tokens(u.tokens))]),
                        ("API equivalent", kit.api_cost(u.api_equivalent_usd, u.turns, sig.unpriced(u.key))),
                        ("Premium requests (legacy)", [txt(format_number(u.premium_requests))]),
                        ("Confidence", kit.confidence_mix(u.confidence, "mt-2 w-28")),
                    ]
                ),
                rid=f"persona-{u.key}",
            )
        )
    out["rows"] = rows

    # --- credit pools
    pools = []
    for p in report.credit_pools:
        use = ratio(p.credits_used, p.included_credits)
        used = td([txt(format_credits(p.credits_used)), sp(), txt(f"/ {format_int(p.included_credits)}", "text-label-3")], right=True)
        used = td(None, right=True, b=[box("", used["s"])])
        if p.included_credits > 0:
            used["b"].append(box("", [kit.meter(use, "bad" if use > 1 else "ok", "mt-1 text-[12px] text-label-2")]))
        pools.append(
            kit.row(
                [
                    td([txt(_first_upper(format_month(p.month)))], c="whitespace-nowrap font-medium"),
                    td([txt("Organization" if p.entity == "org" else p.entity)], c="whitespace-nowrap text-label-2"),
                    td([txt(format_int(p.seats))], right=True),
                    used,
                    td([txt(format_usd(p.overage_usd))], right=True, c="font-semibold", b=[kit.sub([txt(f"{format_credits(p.overage_credits)} credits")])])
                    if p.overage_credits > 0
                    else td([muted("—")], right=True, c="font-semibold"),
                    td([kit.meter(ratio(p.turns_with_data, p.turns), "warn" if p.turns_with_data < p.turns else "ok")], right=True)
                    if p.turns > 0
                    else td([muted("—")], right=True),
                ],
                rid=f"pool-{p.month}-{p.entity}",
            )
        )
    out["has_pools"] = bool(report.credit_pools)
    out["pools"] = pools

    # --- idle seats
    out["has_idle"] = bool(report.idle_seats)
    out["idle_total"] = f"{format_usd(idle_total)} charged to the period"
    out["idle"] = [
        kit.row(
            [
                td([txt(_first_upper(format_month(s.month)))], c="whitespace-nowrap text-label-2"),
                td(
                    [link(display_name.get(s.user_name, s.user_name), person_href(s.user_name, days), "font-medium text-label hover:text-link")],
                    c="whitespace-nowrap",
                    b=[kit.sub([txt(f"{team_name.get(s.team_id, s.team_id)} · {plan_name.get(s.seat_plan_id, s.seat_plan_id)}")])],
                ),
                td([txt(format_usd(s.total_usd))], right=True),
                td([kit.meter(s.period_share, "warn")], right=True),
                td([txt(format_usd(s.period_usd))], right=True, c="font-semibold"),
            ],
            rid=f"idle-{s.month}-{s.user_name}",
        )
        for s in report.idle_seats
    ]

    # --- member months
    out["mm_hint"] = plural(len(report.member_months), "row", "rows") + (f" · {format_int(len(low_usage))} under-used" if low_usage else "")
    mm_rows = []
    for m in report.member_months:
        use = ratio(m.premium_used, m.included_premium)
        low = m.included_premium > 0 and use < LOW_USAGE
        cr = m.credits
        cr_use = ratio(cr.credits_used, cr.included_credits)
        cr_missing = m.turn_count - cr.turns_with_data
        if cr.turns_with_data == 0 and m.turn_count > 0:
            used_box = box("", [chip("no data", "warn", "No turn in the month reported AI credits: unknown, not 0")])
        else:
            used_box = box(
                "",
                [
                    txt("", "mr-1.5 inline-block size-1.5 rounded-full bg-warn align-middle") if cr_missing > 0 else None,
                    txt(format_credits(cr.credits_used)),
                    sp(),
                    txt(f"/ {format_int(cr.included_credits)}", "text-label-3"),
                ],
                ti=f"{plural(cr_missing, 'turn', 'turns')} with no data: lower bound" if cr_missing > 0 else "",
            )
        used_cell = td(None, right=True, b=[used_box])
        if cr.included_credits > 0 and cr.turns_with_data > 0:
            used_cell["b"].append(box("", [kit.meter(cr_use, "bad" if cr_use > 1 else "ok", "mt-1 text-[12px] text-label-2")]))
        premium = [txt(format_number(m.premium_used)), sp(), txt(f"/ {format_int(m.included_premium)}", "text-label-3")]
        if m.included_premium > 0:
            premium.append(kit.meter(use, "bad" if use > 1 else ("warn" if low else "ok"), "ml-2 text-[12px] text-label-2"))
        mm_rows.append(
            kit.row(
                [
                    td([txt(_first_upper(format_month(m.month)))], c="whitespace-nowrap text-label-2"),
                    td(
                        [
                            link(display_name.get(m.user_name, m.user_name), person_href(m.user_name, days), "font-medium text-label hover:text-link"),
                            sp(),
                            chip("under-used", "warn") if low else None,
                        ],
                        c="whitespace-nowrap",
                        b=[kit.sub([txt(plan_name.get(m.seat_plan_id, m.seat_plan_id))])],
                    ),
                    used_cell,
                    td([txt(format_usd(m.total_usd))], right=True, c="font-semibold"),
                    td([txt(format_usd(m.api_equivalent_usd))], right=True, c="text-label-2"),
                    kit.toggle_cell(),
                ],
                kit.detail_grid(
                    [
                        ("Seat", [txt(format_usd(m.seat_usd))]),
                        (
                            "Credit overage (without pool)",
                            [txt(f"{format_usd(cr.overage_usd)} · {format_credits(cr.overage_credits)} credits")] if cr.overage_credits > 0 else [muted("—")],
                        ),
                        ("Premium used / included (legacy)", premium),
                        (
                            "Premium overage",
                            [txt(f"{format_usd(m.overage_usd)} · {format_number(m.overage_requests)} req.")]
                            if m.overage_usd > 0 or m.overage_requests > 0
                            else [muted("—")],
                        ),
                        ("Turns", [txt(format_int(m.turn_count))]),
                    ]
                ),
                rid=f"mm-{m.month}-{m.user_name}",
            )
        )
    out["mm"] = mm_rows
    return out
