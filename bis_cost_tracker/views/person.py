"""Person detail (`/personas/[user]`), port of src/app/personas/[user]/page.tsx."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from bis_core._js import encode_uri_component
from bis_core.app_data import describe_period, get_period_report, href_with, real_repos_by_project, team_href
from bis_core.attribution import CONFIDENCE_LEVELS
from bis_core.db import get_db, list_turns
from bis_core.links import github_profile_url, github_repo_url, issue_url, pr_key_url
from bis_core.report import NONE_KEY, parse_pr_key
from bis_core.report.format import (
    format_compact,
    format_credits,
    format_date_time,
    format_day,
    format_int,
    format_month,
    format_pct,
    format_tokens,
    format_usd,
    plural,
    ratio,
    relative_time,
    short_repo,
)
from bis_core.report.people import initials, person_detail

from bis_cost_tracker.views import kit
from bis_cost_tracker.views.chart import EMPTY_CHART, daily_bars
from bis_cost_tracker.views.kit import LINK, MONO, box, chip, ext, link, muted, real_chip, td, txt
from bis_cost_tracker.views.sessions import issue_pr_links, repo_cells

MAX_SESSIONS = 10


def empty() -> dict[str, Any]:
    return {
        "found": True,
        "crumbs": [],
        "name": "",
        "avatar": kit.avatar("", "lg"),
        "subtitle": [],
        "period": "",
        "has_credits": False,
        "hero_value": "",
        "hero_alt": kit.box(),
        "hint": "",
        "has_seat": False,
        "seat": {},
        "stats": [],
        "has_turns": False,
        "chart_title": "",
        "chart": EMPTY_CHART,
        "empty_note": "",
        "projects_subtitle": "",
        "projects": [],
        "models": [],
        "has_issues": False,
        "no_issue_href": "/sesiones",
        "issues": [],
        "sessions_subtitle": "",
        "sessions_href": "/sesiones",
        "sessions": [],
    }


def _dominant(counts: Mapping[str, int]) -> str:
    best = CONFIDENCE_LEVELS[0]
    for c in CONFIDENCE_LEVELS:
        if counts[c] > counts[best]:
            best = c
    return best


def build(user: str, sp_: Mapping[str, Any]) -> dict[str, Any]:
    d0 = get_period_report(sp_)
    period, report, now = d0.period, d0.report, d0.now
    wanted = user.lower()
    known = any(t.user_name and t.user_name.lower() == wanted for t in list_turns(get_db()))
    d = person_detail(report, user, known=known)
    out = empty()
    if d is None:
        out["found"] = False
        return out
    days = period.days
    person, m = d.person, d.totals
    has_credits = m.credit_turns > 0
    crumbs = [{"label": "Teams", "href": href_with("/equipos", {"days": days})}]
    if person.team_id:
        crumbs.append({"label": person.team_name or person.team_id, "href": team_href(person.team_id, days)})
    else:
        crumbs.append({"label": "People", "href": href_with("/personas", {"days": days})})
    crumbs.append({"label": person.display_name, "href": ""})
    out["crumbs"] = crumbs
    out["name"] = person.display_name
    out["avatar"] = kit.avatar(initials(person.display_name), "lg", m.turns == 0)
    profile = github_profile_url(person.user_name) if d.real else None
    sub = [ext(person.user_name, profile, "GitHub profile", MONO)]
    if person.team_name:
        sub += [txt("·", "text-label-3"), txt(person.team_name)]
    if person.seat_plan_name:
        sub += [txt("·", "text-label-3"), txt(person.seat_plan_name)]
    if not person.is_member:
        sub.append(chip("not a member", "warn", "Not in the members table: no seat or subscription cost"))
    if d.real:
        sub.append(real_chip())
    sub.append(txt(describe_period(period), "w-full text-label-3"))
    out["subtitle"] = sub

    out["has_credits"] = has_credits
    out["hero_value"] = format_credits(m.ai_credits)
    out["hero_alt"] = kit.credits_stack(m)
    if has_credits:
        out["hint"] = f"{format_usd(m.ai_credits_usd)} gross at list price" + (" · lower bound, some data missing" if m.credit_turns < m.turns else "")
    else:
        out["hint"] = "Copilot reported no credits in this period" if m.turns > 0 else "No activity in this period"

    if d.seat:
        s = d.seat
        over = s.included_credits > 0 and s.credits_used > s.included_credits
        missing = s.turn_count - s.turns_with_data
        month = format_month(s.month)
        out["has_seat"] = True
        out["seat"] = {
            "month": month[:1].upper() + month[1:],
            "has_included": s.included_credits > 0,
            "share": format_pct(s.share),
            "bar": f"grow-x h-full rounded-full {'bg-bad' if over else 'bg-accent'}",
            "w": f"{min(100, s.share * 100):g}%",
            "used": format_credits(s.credits_used),
            "included": f" of {format_int(s.included_credits)} credits included in {person.seat_plan_name}",
            "over": f" · {format_credits(s.overage_credits)} overage" if over else "",
            "used_credits": f"{format_credits(s.credits_used)} credits",
            "no_included": f" this month. The {person.seat_plan_name} plan includes no AI credits: all usage goes to the pool or is paid separately.",
            "missing": f"{plural(missing, 'turn', 'turns')} this month with no data: lower bound" if missing > 0 else "",
        }

    out["stats"] = [
        {
            "label": "Tokens",
            "value": format_tokens(m.tokens),
            "hint": f"{format_compact(m.input_tokens)} → {format_compact(m.output_tokens)} · {format_compact(d.cache_read_tokens)} cached",
            "title": f"{format_int(m.input_tokens)} input (incl. cache) · {format_int(m.output_tokens)} output · {format_int(d.cache_read_tokens)} read from cache",
            "mono": False,
        },
        {"label": "Turns", "value": format_int(m.turns), "hint": f"{format_pct(ratio(m.with_issue, m.turns))} with an issue", "title": "", "mono": False},
        {"label": "Sessions", "value": format_int(m.conversations), "hint": f"last {relative_time(d.last_at, now)}" if d.last_at else "", "title": "", "mono": False},
        {"label": "Active days", "value": format_int(d.active_days), "hint": f"of {format_int(len(d.daily))}", "title": "", "mono": False},
        {
            "label": "Top model",
            "value": d.top_model.label if d.top_model else "—",
            "hint": f"{format_pct(d.top_model.share)} of turns" if d.top_model else "",
            "title": "",
            "mono": True,
        },
    ]
    out["has_turns"] = m.turns > 0
    out["empty_note"] = f"{person.display_name} has no turns in this period. Try a longer period at the top right."
    if m.turns > 0:
        out["chart_title"] = "AI credits per day" if has_credits else "Turns per day"
        out["chart"] = daily_bars(
            [
                {
                    "day": x.key,
                    "label": format_day(x.key),
                    "value": x.ai_credits if has_credits else x.turns,
                    "title": f"{format_day(x.key)}: {format_credits(x.ai_credits)} credits ({format_usd(x.ai_credits_usd)}) · {plural(x.turns, 'turn', 'turns')} · {format_tokens(x.tokens)} tokens",
                }
                for x in d.daily
            ],
            format_value=format_credits if has_credits else format_int,
            format_axis=format_compact,
            aria_label=f"{'AI credits' if has_credits else 'Turns'} per day for {person.display_name}",
        )

    project_repos = real_repos_by_project(report)
    out["projects_subtitle"] = "AI credits, tokens and turns" if has_credits else "Tokens and turns"
    proj_rows = []
    for p in d.projects:
        sub_segs = [txt(plural(p.conversations, "session", "sessions"))]
        for repo in project_repos.get(p.key, []):
            sub_segs += [txt(" · "), ext("GitHub", github_repo_url(repo), f"{repo} on GitHub")]
        proj_rows.append(
            kit.row(
                [
                    td(
                        [
                            link(
                                "" if p.key == NONE_KEY else p.label,
                                href_with("/sesiones", {"days": days, "user": person.user_name, "project": p.key}),
                                "block truncate font-medium text-label hover:text-link",
                                s=[muted("No project")] if p.key == NONE_KEY else [],
                            )
                        ],
                        c="max-w-[14rem]",
                        b=[kit.sub(sub_segs)],
                    ),
                    td(kit.credits_stack(p), right=True),
                    td([kit.meter(ratio(p.ai_credits, m.ai_credits) if has_credits else ratio(p.turns, m.turns))], right=True),
                    td([txt(format_tokens(p.tokens))], right=True),
                    td([txt(format_int(p.turns))], right=True),
                ],
                rid=f"pp-{p.key}",
            )
        )
    out["projects"] = proj_rows
    out["models"] = kit.bar_list(
        [
            kit.bar_item(
                x.key,
                [txt(x.label, MONO)],
                x.turns,
                [txt(format_int(x.turns))],
                secondary=f"{format_credits(x.ai_credits)} cr." if x.credit_turns > 0 else "no data",
            )
            for x in d.models[:6]
        ]
    )

    out["has_issues"] = bool(d.issues)
    out["no_issue_href"] = href_with("/sesiones", {"days": days, "user": person.user_name, "sin_issue": 1})
    issue_rows = []
    for i in d.issues[:8]:
        prs: list[dict[str, Any]] = []
        for k in i.pr_keys:
            n = (parse_pr_key(k) or {}).get("number", k)
            prs.append(
                kit.group(
                    [
                        link(f"!{n}", href_with("/sesiones", {"days": days, "user": person.user_name, "pr": k}), LINK),
                        ext(None, pr_key_url(k), f"Pull request {k} on GitHub", "text-[12px]"),
                    ],
                    "inline-flex items-baseline",
                )
            )
        issue_rows.append(
            kit.row(
                [
                    td(
                        [
                            link(
                                i.issue.title if i.issue else f"{short_repo(i.repo)}#{i.number}",
                                href_with("/sesiones", {"days": days, "user": person.user_name, "issue": i.key}),
                                "block truncate font-medium text-label hover:text-link",
                                ti=i.issue.title if i.issue else i.key,
                            )
                        ],
                        c="max-w-[26rem]",
                        b=[
                            box(
                                "mt-0.5 flex flex-wrap items-center gap-x-3 text-[12.5px] text-label-3",
                                [
                                    ext(f"{short_repo(i.repo)}#{i.number}", issue_url(i.repo, i.number), f"Issue #{i.number} on GitHub", MONO),
                                    kit.state_badge(i.issue.state if i.issue else "unsynced"),
                                ],
                            )
                        ],
                    ),
                    td([kit.confidence_badge(_dominant(i.confidence))]),
                    td([muted("—")], c=MONO) if not prs else td(None, c=MONO, b=[box("flex flex-wrap gap-x-2", prs)]),
                    td(kit.credits_stack(i), right=True),
                    td([txt(format_int(i.turns))], right=True),
                ],
                rid=f"pi-{i.key}",
            )
        )
    out["issues"] = issue_rows

    convs = d.conversations
    out["sessions_subtitle"] = "Newest first" + (f" · {MAX_SESSIONS} of {format_int(len(convs))}" if len(convs) > MAX_SESSIONS else "")
    out["sessions_href"] = href_with("/sesiones", {"days": days, "user": person.user_name})
    sess = []
    for c in convs[:MAX_SESSIONS]:
        branches = [{"repo": c.repos[0] if len(c.repos) == 1 else None, "branch": b} for b in c.branches]
        sess.append(
            kit.row(
                [
                    td(
                        [link(format_date_time(c.last_at), href_with(f"/sesiones/{encode_uri_component(c.key)}", {"days": days}), "font-medium text-link tabular-nums hover:underline")],
                        c="whitespace-nowrap",
                        b=[box("mt-0.5 text-[12.5px] tabular-nums text-label-3", [txt(f"since {format_date_time(c.first_at)}")])],
                    ),
                    repo_cells(c.repos, branches, c.branches, "max-w-[18rem]"),
                    td([txt(format_int(c.turns))], right=True, b=[kit.sub([txt(f"{format_tokens(c.tokens)} tokens")])]),
                    td(kit.credits_stack(c), right=True),
                    issue_pr_links(c.issue_keys, c.pr_keys, days, with_titles=False),
                ],
                rid=f"ps-{c.key}",
            )
        )
    out["sessions"] = sess
    return out
