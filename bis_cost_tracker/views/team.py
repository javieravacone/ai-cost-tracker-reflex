"""Team detail (`/equipos/[id]`), port of src/app/equipos/[id]/page.tsx."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from bis_core.app_data import describe_period, get_period_report, href_with, person_href, real_repos_by_project
from bis_core.links import github_repo_url, issue_url
from bis_core.report import NONE_KEY
from bis_core.report.format import (
    format_credits,
    format_date_time,
    format_int,
    format_pct,
    format_tokens,
    format_usd,
    plural,
    relative_time,
    short_repo,
)
from bis_core.report.people import initials, team_detail

from bis_cost_tracker.views import kit
from bis_cost_tracker.views.kit import box, chip, link, muted, real_chip, td, txt


def empty() -> dict[str, Any]:
    return {
        "found": True,
        "name": "",
        "crumbs": [],
        "subtitle": [],
        "has_credits": False,
        "hero_value": "",
        "hero_alt": kit.box(),
        "hint": "",
        "has_last": False,
        "last": "",
        "last_title": "",
        "stats": [],
        "members": [],
        "projects_subtitle": "",
        "projects": [],
        "issues": [],
        "issues_href": "/issues",
        "sessions_href": "/sesiones",
    }


def _member_row(p: Any, days: int, plan_name: str | None, team_id: str, now: int) -> dict[str, Any]:
    idle = p.turns == 0
    none = p.key == NONE_KEY
    href = href_with("/sesiones", {"days": days, "team": team_id, "user": NONE_KEY}) if none else person_href(p.user_name or p.key, days)
    if none:
        meta = "Turns with this team but no user"
    else:
        meta = " · ".join(x for x in [p.user_name if p.user_name and p.user_name != p.label else None, plan_name] if x)
    chips = [real_chip() if p.real else None]
    if not none and not p.is_member:
        chips.append(chip(f"from {p.other_team_name}" if p.other_team_name else "not a member", "info", "Turns attributed to this team (team.id attribute) by someone from another team"))
    if idle:
        chips.append(chip("no activity"))
    label_cls = "hover-link font-medium " + ("text-label-2" if idle or none else "text-label")
    person = td(
        None,
        c="whitespace-nowrap",
        b=[
            box(
                "flex items-center gap-3",
                [kit.avatar("?" if none else initials(p.label), muted_=idle or none)],
                b=[
                    box(
                        "min-w-0",
                        b=[
                            box("flex items-center gap-2", [txt(p.label, label_cls), *chips, link("", href, "stretched", ti=p.label)]),
                            kit.sub([txt(meta)]) if meta else None,
                        ],
                    )
                ],
            )
        ],
    )
    dash = [muted("—")]
    if p.top_project:
        top = td(
            None,
            c="max-w-[14rem]",
            b=[
                box("truncate", [muted(p.top_project.label) if p.top_project.key == NONE_KEY else txt(p.top_project.label)]),
                kit.sub([txt(f"{format_pct(p.top_project.share)} of their usage")]),
            ],
        )
    else:
        top = td(dash, c="max-w-[14rem]")
    if p.last_at:
        last = td(
            None,
            right=True,
            b=[box("", [txt(relative_time(p.last_at, now))], b=[kit.sub([txt(plural(p.active_days, "active day", "active days"))])], ti=f"{format_date_time(p.last_at)} UTC")],
        )
    else:
        last = td(dash, right=True)
    return kit.row(
        [
            person,
            td(dash, right=True) if idle else td(kit.credits_stack(p), right=True),
            td(dash, right=True) if idle else td([txt(format_int(p.turns))], right=True, b=[kit.sub([txt(plural(p.conversations, "session", "sessions"))])]),
            td(dash if idle else [txt(format_tokens(p.tokens))], right=True),
            top,
            last,
        ],
        c=f"trow relative {'[&>td]:text-label-3' if idle else ''}",
        rid=f"member-{p.key}",
    )


def build(team_id: str, sp_: Mapping[str, Any]) -> dict[str, Any]:
    d = get_period_report(sp_)
    period, report, now = d.period, d.report, d.now
    t = team_detail(report, team_id)
    out = empty()
    if t is None:
        out["found"] = False
        return out
    days = period.days
    plan_name = {p.id: p.name for p in report.refs.seat_plans}
    project_repos = real_repos_by_project(report)
    m = t.totals
    has_credits = m.credit_turns > 0
    project_total = m.ai_credits if has_credits else m.turns

    out["name"] = t.team.name
    out["crumbs"] = [{"label": "Teams", "href": href_with("/equipos", {"days": days})}, {"label": t.team.name, "href": ""}]
    out["subtitle"] = [
        txt(plural(t.member_count, "member", "members")),
        real_chip() if t.real else None,
        txt("·", "text-label-3"),
        txt(describe_period(period)),
    ]
    out["subtitle"] = [x for x in out["subtitle"] if x]
    out["has_credits"] = has_credits
    out["hero_value"] = format_credits(m.ai_credits)
    out["hero_alt"] = kit.credits_stack(m)
    if has_credits:
        out["hint"] = f"{format_usd(m.ai_credits_usd)} gross at list price" + (" · lower bound, some data missing" if m.credit_turns < m.turns else "")
    else:
        out["hint"] = "Copilot reported no credits in this period" if m.turns > 0 else "No activity in this period"
    if t.last_at:
        out["has_last"] = True
        out["last"] = relative_time(t.last_at, now)
        out["last_title"] = f"{format_date_time(t.last_at)} UTC"
    out["stats"] = [
        {"label": "Tokens", "value": format_tokens(m.tokens), "hint": f"{format_tokens(m.input_tokens)} input · {format_tokens(m.output_tokens)} output"},
        {"label": "Turns", "value": format_int(m.turns), "hint": ""},
        {"label": "Sessions", "value": format_int(m.conversations), "hint": ""},
        {"label": "Active people", "value": format_int(t.active_members), "hint": f"of {plural(t.member_count, 'member', 'members')}"},
        {"label": "Turns with an issue", "value": format_pct(t.pct_with_issue), "hint": plural(m.with_issue, "turn", "turns")},
    ]
    out["members"] = [
        _member_row(p, days, plan_name.get(p.seat_plan_id, p.seat_plan_id) if p.seat_plan_id else None, t.team.id, now) for p in t.members
    ]
    out["projects_subtitle"] = "AI credits · share of team" if has_credits else "Turns · share of team"
    out["projects"] = kit.bar_list(
        [
            kit.bar_item(
                p.key,
                [muted("No project")] if p.key == NONE_KEY else [txt(p.label)],
                p.ai_credits if has_credits else p.turns,
                [kit.credits_compact(p, quiet=True)] if has_credits else [txt(plural(p.turns, "turn", "turns"))],
                secondary=format_pct(((p.ai_credits if has_credits else p.turns) / project_total) if project_total > 0 else 0),
                href=href_with("/sesiones", {"days": days, "team": t.team.id, "project": p.key}),
                external=(github_repo_url((project_repos.get(p.key) or [None])[0]), f"{(project_repos.get(p.key) or [None])[0]} on GitHub"),
            )
            for p in t.projects
        ]
    )
    out["issues"] = kit.bar_list(
        [
            kit.bar_item(
                i.key,
                [
                    kit.group(
                        [
                            txt(i.issue.title if i.issue else f"{short_repo(i.repo)}#{i.number}"),
                            txt(f"#{i.number}", "ml-1.5 font-mono text-[12px] font-normal text-label-3"),
                        ],
                        ti=f"{i.repo}#{i.number}",
                    )
                ],
                i.ai_credits if has_credits else i.turns,
                [kit.credits_compact(i, quiet=True)] if has_credits else [txt(plural(i.turns, "turn", "turns"))],
                href=href_with("/sesiones", {"days": days, "team": t.team.id, "issue": i.key}),
                external=(issue_url(i.repo, i.number), f"Issue #{i.number} on GitHub"),
            )
            for i in t.issues[:5]
        ]
    )
    out["issues_href"] = href_with("/issues", {"days": days})
    out["sessions_href"] = href_with("/sesiones", {"days": days, "team": t.team.id})
    return out
