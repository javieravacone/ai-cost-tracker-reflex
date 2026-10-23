"""Projects (`/proyectos`), port of src/app/proyectos/page.tsx."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from typing import Any

from bis_core.app_data import by_credits_desc, describe_period, get_period_report, group_signals, href_with, real_repos_by_project
from bis_core.links import github_repo_url
from bis_core.report import NONE_KEY, by_project
from bis_core.report.format import format_int, format_number, format_pct, format_tokens, format_usd, plural, ratio

from bis_cost_tracker.views import kit
from bis_cost_tracker.views.kit import LINK, box, ext, link, muted, real_chip, sp, td, txt


def empty() -> dict[str, Any]:
    return {"empty": True, "db_empty": False, "subtitle": "", "rows": []}


def build(sp_: Mapping[str, Any]) -> dict[str, Any]:
    d = get_period_report(sp_)
    period, report = d.period, d.report
    out = empty()
    out["subtitle"] = f"Where is the usage going? · {describe_period(period)}"
    out["db_empty"] = d.db_empty
    if not report.rows:
        return out
    out["empty"] = False

    projects = by_credits_desc(by_project(report))
    sig = group_signals(report, lambda r: r.attribution.project_id)
    no_issue_report = replace(report, rows=[r for r in report.rows if not r.attribution.issue_key])
    no_issue_sig = group_signals(no_issue_report, lambda r: r.attribution.project_id)
    days = period.days
    real_repos = real_repos_by_project(report)

    rows = []
    for p in projects:
        none = p.key == NONE_KEY
        has_no_issue = not none and p.no_issue.turns > 0
        no_issue_href = href_with("/sesiones", {"days": days, "project": p.key, "sin_issue": 1})
        sub_segs = [txt(f"{plural(p.distinct_issues, 'issue', 'issues')} · {plural(p.distinct_prs, 'PR', 'PRs')} · {plural(p.users, 'person', 'people')}")]
        for repo in real_repos.get(p.key, []):
            sub_segs += [txt(" · "), ext("GitHub", github_repo_url(repo), f"{repo} on GitHub")]
        name = td(
            [
                link("" if none else p.label, href_with("/sesiones", {"days": days, "project": p.key}), "font-medium text-label hover:text-link", s=[muted("No project")] if none else []),
                sp(),
                real_chip() if sig.real(p.key) else None,
            ],
            c="whitespace-nowrap",
            b=[kit.sub(sub_segs)],
        )
        attributed = td([kit.meter(ratio(p.attributed, p.turns))], right=True)
        if has_no_issue:
            attributed["b"].append(box("mt-1 text-[12.5px]", [link(f"{format_int(p.no_issue.turns)} with no issue", no_issue_href, LINK)]))
        detail = kit.detail_grid(
            [
                ("Tokens", [txt(format_tokens(p.tokens))]),
                ("API equivalent", kit.api_cost(p.api_equivalent_usd, p.turns, sig.unpriced(p.key))),
                ("Premium requests (legacy)", [txt(format_number(p.premium_requests))]),
                ("Issues · PRs", [txt(f"{format_int(p.distinct_issues)} · {format_int(p.distinct_prs)}")]),
                ("Confidence", kit.confidence_mix(p.confidence, "mt-2 w-28")),
            ]
        )
        if has_no_issue:
            ni = p.no_issue
            detail = kit.detail_grids(
                detail,
                kit.detail_grid(
                    [
                        ("Turns", [txt(format_int(ni.turns))]),
                        ("AI credits", kit.credits_inline(ni)),
                        ("API equivalent", kit.api_cost(ni.api_equivalent_usd, ni.turns, no_issue_sig.unpriced(p.key))),
                        ("Subscription", [txt(f"{format_usd(ni.subscription_usd)} · {format_number(ni.premium_requests)} premium")]),
                        (
                            "Attributed (PR) · confidence",
                            kit.group(
                                [kit.meter(ratio(ni.attributed, ni.turns)), kit.confidence_mix(ni.confidence, "w-16")],
                                "inline-flex items-center gap-3",
                            ),
                        ),
                    ],
                    head=[
                        link("No issue", no_issue_href, f"{LINK} font-medium"),
                        txt(
                            f"{format_pct(ratio(ni.turns, p.turns))} of the project · {plural(ni.conversations, 'session', 'sessions')} · {plural(ni.users, 'person', 'people')}",
                            "text-label-3",
                        ),
                    ],
                ),
            )
        rows.append(
            kit.row(
                [
                    name,
                    td([txt(format_int(p.turns))], right=True, b=[kit.sub([txt(plural(p.conversations, "session", "sessions"))])]),
                    td(kit.credits_stack(p), right=True),
                    td([txt(format_usd(p.subscription_usd))], right=True),
                    attributed,
                    kit.toggle_cell(),
                ],
                detail,
                rid=f"proyecto-{p.key}",
            )
        )
    out["rows"] = rows
    return out
