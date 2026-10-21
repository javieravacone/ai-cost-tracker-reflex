"""Overview page (`/`), port of src/app/page.tsx."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from bis_core.app_data import (
    by_credits_desc,
    describe_period,
    get_period_report,
    group_signals,
    href_with,
    previous_period_credits,
    real_repos_by_project,
    team_href,
)
from bis_core.attribution import CONFIDENCE_LEVELS
from bis_core.links import github_repo_url, issue_url
from bis_core.report import NONE_KEY, by_day, by_issue, by_model, by_project, by_team, by_user, compute_totals
from bis_core.report.format import (
    format_compact,
    format_credits,
    format_day,
    format_delta,
    format_int,
    format_pct,
    format_tokens,
    format_usd,
    format_usd_axis,
    plural,
    ratio,
    short_repo,
)

from bis_cost_tracker.views import kit
from bis_cost_tracker.views.chart import EMPTY_CHART, daily_bars
from bis_cost_tracker.views.kit import LINK, code, credits_compact, link, real_chip, sp, txt

TOP = 5


def empty() -> dict[str, Any]:
    return {
        "empty": True,
        "db_empty": False,
        "subtitle": "",
        "avisos": [],
        "has_credits": False,
        "hero_value": "",
        "hero_alt": kit.box(),
        "hero_usd": "",
        "has_delta": False,
        "delta": "",
        "delta_arrow": "",
        "delta_title": "",
        "show_peak": False,
        "peak": "",
        "active": "",
        "chart_title": "",
        "chart": EMPTY_CHART,
        "tiles": [],
        "teams": [],
        "projects": [],
        "issues": [],
        "models": [],
        "models_hint": "",
        "mix": kit.confidence_mix({}),
        "legend": {c: "" for c in CONFIDENCE_LEVELS},
        "with_issue": kit.meter(0),
        "with_pr": kit.meter(0),
        "sin_issue_href": "/sesiones?sin_issue=1",
        "teams_href": "/equipos",
        "projects_href": "/proyectos",
        "issues_href": "/issues",
    }


def build(sp_: Mapping[str, Any]) -> dict[str, Any]:
    d = get_period_report(sp_)
    period, report = d.period, d.report
    days = period.days
    out = empty()
    out["subtitle"] = describe_period(period)
    out["db_empty"] = d.db_empty
    if not report.rows:
        return out
    out["empty"] = False

    totals = compute_totals(report)
    daily = by_day(report)
    teams = by_credits_desc(by_team(report))[:TOP]
    projects = by_credits_desc(by_project(report))[:TOP]
    issues = by_credits_desc(by_issue(report))[:TOP]
    models = by_model(report)[:6]
    non_members = [u for u in by_user(report) if not u.is_member]
    non_member_turns = sum(u.turns for u in non_members)
    unpriced_turns = sum(m.turns for m in report.unpriced_models)
    team_sig = group_signals(report, lambda r: r.attribution.team_id)
    project_sig = group_signals(report, lambda r: r.attribution.project_id)
    issue_sig = group_signals(report, lambda r: r.attribution.issue_key)
    project_repo = real_repos_by_project(report)
    has_credits = totals.credit_turns > 0

    def metric(b: Any) -> float:
        return b.ai_credits if has_credits else b.api_equivalent_usd

    peak = daily[0] if daily else None
    for b in daily:
        if metric(b) > metric(peak):
            peak = b
    active_days = len([b for b in daily if b.turns > 0])
    credits_missing = totals.turns - totals.credit_turns
    prev = previous_period_credits(period) if has_credits else None
    delta = totals.ai_credits / prev.ai_credits - 1 if prev and prev.ai_credits > 0 else None
    pool_used = sum(p.credits_used for p in report.credit_pools)
    pool_included = sum(p.included_credits for p in report.credit_pools)
    pool_over = sum(p.overage_usd for p in report.credit_pools)

    # --- warnings
    avisos: list[dict[str, Any]] = []
    if report.unpriced_models:
        n = len(report.unpriced_models)
        names = ", ".join(f"{m.model if m.model is not None else '(no model)'} ({plural(m.turns, 'turn', 'turns')})" for m in report.unpriced_models)
        avisos.append(
            {
                "key": "unpriced",
                "tone": "warn",
                "title": "1 model with no price" if n == 1 else f"{n} models with no price",
                "body": [
                    txt(f"{names}: their API cost isn’t added and premium requests are estimated at ×1. Add the price in "),
                    code("model_prices"),
                    txt(" (see "),
                    link("Settings", "/ajustes", LINK),
                    txt(")."),
                ],
            }
        )
    if report.unmapped_repos:
        n = len(report.unmapped_repos)
        names = ", ".join(f"{r.repo} ({plural(r.turns, 'turn', 'turns')})" for r in report.unmapped_repos)
        avisos.append(
            {
                "key": "unmapped",
                "tone": "warn",
                "title": "1 repo with no project" if n == 1 else f"{n} repos with no project",
                "body": [txt(f"{names}. Add a mapping in "), code("repo_mappings"), txt(" to attribute them.")],
            }
        )
    if report.turns_without_repo > 0:
        avisos.append(
            {
                "key": "norepo",
                "tone": "info",
                "title": f"{plural(report.turns_without_repo, 'turn', 'turns')} with no repo",
                "body": [
                    txt(
                        "Copilot reported no repo (window without a git folder, or attributes not exported): they can only be attributed by hand."
                    )
                ],
            }
        )
    if credits_missing > 0:
        partial = f", {format_int(totals.credit_partial_turns)} with partial data" if totals.credit_partial_turns > 0 else ""
        avisos.append(
            {
                "key": "credits",
                "tone": "info",
                "title": f"{plural(credits_missing, 'turn', 'turns')} with no credit data",
                "body": [
                    txt(
                        "Copilot didn’t report their usage (legacy plan, BYOK or older client). They count as “no data”, not as 0: the "
                        f"actual usage shown is a lower bound ({format_pct(ratio(totals.credit_turns, totals.turns))} of turns with data{partial})."
                    )
                ],
            }
        )
    if non_member_turns > 0:
        avisos.append(
            {
                "key": "nonmembers",
                "tone": "info",
                "title": f"{plural(non_member_turns, 'turn', 'turns')} from non-members",
                "body": [txt(f"{', '.join(u.label for u in non_members)}: no subscription cost assigned.")],
            }
        )
    out["avisos"] = avisos

    # --- hero
    out["has_credits"] = has_credits
    out["hero_value"] = format_credits(totals.ai_credits)
    out["hero_alt"] = kit.credits_stack(totals)
    out["hero_usd"] = format_usd(totals.ai_credits_usd)
    if delta is not None and prev is not None:
        out["has_delta"] = True
        out["delta_arrow"] = "↑" if delta >= 0 else "↓"
        out["delta"] = f"{format_delta(delta)} vs previous {days} days"
        out["delta_title"] = f"{format_credits(prev.ai_credits)} credits in the previous {days} days"
    if peak is not None and metric(peak) > 0:
        out["show_peak"] = True
        out["peak"] = f"{format_day(peak.key)} · " + (f"{format_credits(peak.ai_credits)} credits" if has_credits else format_usd(peak.api_equivalent_usd))
    out["active"] = f"{format_int(active_days)} of {format_int(len(daily))}"
    out["chart_title"] = "AI credits per day" if has_credits else "API-equivalent cost per day"
    points = [
        {
            "day": b.key,
            "label": format_day(b.key),
            "value": metric(b),
            "title": f"{format_day(b.key)}: {format_credits(b.ai_credits)} credits ({format_usd(b.ai_credits_usd)}) · {format_usd(b.api_equivalent_usd)} API · {format_usd(b.subscription_usd)} subscription · {plural(b.turns, 'turn', 'turns')}",
        }
        for b in daily
    ]
    out["chart"] = daily_bars(
        points,
        format_value=format_credits if has_credits else format_usd,
        format_axis=format_compact if has_credits else format_usd_axis,
        aria_label=f"{'AI credits' if has_credits else 'API-equivalent cost'} per day, {format_int(len(daily))} days",
    )

    # --- tiles
    tiles = [
        {
            "label": "Subscription cost",
            "value": [txt(format_usd(totals.subscription_usd))],
            "hint": f"includes {format_usd(totals.idle_seats_usd)} in unused seats" if totals.idle_seats_usd > 0 else "seats + premium request overage",
        },
        {
            "label": "API-equivalent cost",
            "value": [kit.api_cost(totals.api_equivalent_usd, totals.turns, unpriced_turns)]
            if unpriced_turns >= totals.turns
            else [txt(format_usd(totals.api_equivalent_usd))],
            "hint": f"{format_tokens(totals.tokens)} tokens" + (f" · {format_int(unpriced_turns)} with no price" if unpriced_turns > 0 else ""),
        },
        {
            "label": "Credit pool",
            "value": [txt(format_pct(ratio(pool_used, pool_included)))],
            "hint": f"{format_compact(pool_used)} of {format_compact(pool_included)} used" + (f" · {format_usd(pool_over)} overage" if pool_over > 0 else ""),
        }
        if pool_included > 0 or pool_used > 0
        else {"label": "Sessions", "value": [txt(format_int(totals.conversations))], "hint": plural(totals.turns, "turn", "turns")},
        {
            "label": "Turns with an issue",
            "value": [txt(format_pct(totals.pct_with_issue))],
            "hint": f"{plural(totals.turns, 'turn', 'turns')} from {plural(totals.users, 'person', 'people')}",
        },
    ]
    out["tiles"] = tiles

    # --- top lists
    def label_with_real(text: str, real: bool) -> list[dict[str, Any]]:
        return [txt(text), sp(), real_chip()] if real else [txt(text), sp()]

    out["teams"] = kit.bar_list(
        [
            kit.bar_item(
                t.key,
                label_with_real(t.label, team_sig.real(t.key)),
                t.ai_credits,
                [credits_compact(t, quiet=True)],
                href=href_with("/sesiones", {"days": days, "team": t.key}) if t.key == NONE_KEY else team_href(t.key, days),
            )
            for t in teams
        ]
    )
    out["projects"] = kit.bar_list(
        [
            kit.bar_item(
                p.key,
                label_with_real("No project" if p.key == NONE_KEY else p.label, project_sig.real(p.key)),
                p.ai_credits,
                [credits_compact(p, quiet=True)],
                href=href_with("/sesiones", {"days": days, "project": p.key}),
                external=(
                    github_repo_url((project_repo.get(p.key) or [None])[0]),
                    f"{(project_repo.get(p.key) or [None])[0]} on GitHub",
                ),
            )
            for p in projects
        ]
    )
    out["issues"] = kit.bar_list(
        [
            kit.bar_item(
                i.key,
                [
                    kit.group(
                        [txt(i.issue.title if i.issue else f"{short_repo(i.repo)}#{i.number}"), sp()]
                        + ([real_chip()] if issue_sig.real(i.key) else []),
                        ti=f"{i.repo}#{i.number}",
                    )
                ],
                i.ai_credits,
                [credits_compact(i, quiet=True)],
                href=href_with("/sesiones", {"days": days, "issue": i.key}),
                external=(issue_url(i.repo, i.number), f"Issue #{i.number} on GitHub"),
            )
            for i in issues
        ]
    )

    # --- models and confidence
    out["models_hint"] = f"{plural(len(models), 'model', 'models')} · {format_pct(ratio(totals.attributed, totals.turns))} of turns with an issue or PR"
    out["models"] = kit.bar_list(
        [
            kit.bar_item(
                m.key,
                [txt(m.label, "font-mono text-[12.5px]")],
                m.api_equivalent_usd,
                [kit.api_cost(m.api_equivalent_usd, m.turns, 0 if m.priced else m.turns)],
                secondary=format_int(m.turns),
            )
            for m in models
        ]
    )
    total = sum(report.confidence.values())
    out["mix"] = kit.confidence_mix(report.confidence, "w-full", "lg")
    out["legend"] = {c: format_pct(ratio(report.confidence[c], total)) for c in CONFIDENCE_LEVELS}
    out["with_issue"] = kit.meter(totals.pct_with_issue, c="ml-1")
    out["with_pr"] = kit.meter(totals.pct_with_pr, c="ml-1")
    out["sin_issue_href"] = href_with("/sesiones", {"days": days, "sin_issue": 1})
    out["teams_href"] = href_with("/equipos", {"days": days})
    out["projects_href"] = href_with("/proyectos", {"days": days})
    out["issues_href"] = href_with("/issues", {"days": days})
    return out
