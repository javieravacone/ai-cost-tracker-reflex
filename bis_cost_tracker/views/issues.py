"""Issues (`/issues`) and Pull requests (`/prs`), ports of src/app/issues/page.tsx and src/app/prs/page.tsx."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from bis_core.app_data import by_credits_desc, describe_period, get_period_report, group_signals, href_with
from bis_core.links import branch_url, github_repo_url, issue_key_url, issue_url, pr_key_url, pr_url
from bis_core.report import by_issue, by_pr, compute_totals, parse_issue_key, parse_pr_key
from bis_core.report.format import format_int, format_pct, format_tokens, format_usd, plural, short_repo

from bis_cost_tracker.views import kit
from bis_cost_tracker.views.kit import LINK, MONO, box, ext, group, link, muted, real_chip, td, txt


def empty() -> dict[str, Any]:
    return {
        "empty": True,
        "db_empty": False,
        "subtitle": "",
        "stats": [],
        "has_rows": False,
        "rows": [],
        "has_no_issue": False,
        "projects_href": "",
    }


def _key_links(keys: list[str], days: int, kind: str) -> dict[str, Any]:
    """PRs column (issues page) / Issues column (PRs page): in-app link + GitHub marker."""
    if not keys:
        return td([muted("—")], c=f"whitespace-nowrap {MONO}")
    items = []
    for k in keys:
        if kind == "pr":
            n = (parse_pr_key(k) or {}).get("number", k)
            a = link(f"!{n}", href_with("/sesiones", {"days": days, "pr": k}), LINK)
            mark = ext(None, pr_key_url(k), f"Pull request #{n} on GitHub", "text-[12px]")
        else:
            n = (parse_issue_key(k) or {}).get("number", k)
            a = link(f"#{n}", href_with("/sesiones", {"days": days, "issue": k}), LINK, ti="See its sessions")
            mark = ext(None, issue_key_url(k), f"Issue #{n} on GitHub", "text-[12px]")
        items.append(group([a, mark], "inline-flex items-baseline"))
    # Nested groups only render atoms, so the wrapper is a box (its segments render links).
    return td(None, c=f"whitespace-nowrap {MONO}", b=[box("flex flex-wrap gap-x-2 gap-y-0.5", items)])


def _title_link(title: str | None, href: str, what: str) -> dict[str, Any]:
    return link(
        title or "",
        href,
        "line-clamp-1 font-medium text-label hover:text-link",
        ti=f"See sessions for this {what}",
        s=[] if title else [muted("Untitled (not synced)")],
    )


def build_issues(sp_: Mapping[str, Any]) -> dict[str, Any]:
    d = get_period_report(sp_)
    period, report = d.period, d.report
    out = empty()
    out["subtitle"] = describe_period(period)
    out["db_empty"] = d.db_empty
    if not report.rows:
        return out
    out["empty"] = False

    issues = by_credits_desc(by_issue(report))
    totals = compute_totals(report)
    sig = group_signals(report, lambda r: r.attribution.issue_key)
    no_issue_turns = totals.turns - totals.with_issue
    days = period.days
    unsynced = sum(1 for i in issues if not i.issue)

    out["subtitle"] = f"How much does each issue cost? · {describe_period(period)}"
    stats = [
        txt(f"{plural(len(issues), 'issue', 'issues')} with activity · {format_pct(totals.pct_with_issue)} of turns · "),
        link(f"{plural(no_issue_turns, 'turn', 'turns')} with no issue", href_with("/sesiones", {"days": days, "sin_issue": 1}), LINK),
    ]
    if unsynced > 0:
        stats.append(txt(f" · {format_int(unsynced)} not synced"))
    out["stats"] = stats
    out["has_no_issue"] = totals.with_issue < totals.turns
    out["projects_href"] = href_with("/proyectos", {"days": days})

    rows = []
    for i in issues:
        sessions = href_with("/sesiones", {"days": days, "issue": i.key})
        meta = [
            group(
                [
                    link(f"{short_repo(i.repo)}#{i.number}", sessions, f"{LINK} {MONO}", ti=f"{i.repo}#{i.number}: see its sessions"),
                    ext(None, issue_url(i.repo, i.number), f"Issue #{i.number} on GitHub", "text-[12px]"),
                ],
                "inline-flex items-baseline",
            ),
            kit.state_badge(i.issue.state if i.issue else "unsynced"),
            txt(i.project_name) if i.project_name else None,
            real_chip() if sig.real(i.key) else None,
        ]
        detail = kit.detail_grid(
            [
                ("Project", [txt(i.project_name) if i.project_name else muted("—")]),
                ("API equivalent", kit.api_cost(i.api_equivalent_usd, i.turns, sig.unpriced(i.key))),
                ("Tokens", [txt(format_tokens(i.tokens))]),
                ("Repo", [ext(i.repo, github_repo_url(i.repo), "Repository on GitHub", MONO)]),
                ("Confidence", kit.confidence_mix(i.confidence, "mt-2 w-28")),
            ]
        )
        rows.append(
            kit.row(
                [
                    td(
                        [_title_link(i.issue.title if i.issue else None, sessions, "issue")],
                        c="min-w-[18rem] max-w-[34rem]",
                        b=[box("mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-[12.5px] text-label-3", meta)],
                    ),
                    td([txt(format_int(i.turns))], right=True, b=[kit.sub([txt(plural(i.users, "person", "people"))])]),
                    td(kit.credits_stack(i), right=True),
                    td([txt(format_usd(i.subscription_usd))], right=True),
                    _key_links(i.pr_keys, days, "pr"),
                    kit.toggle_cell(),
                ],
                detail,
                rid=f"issue-{i.key}",
            )
        )
    out["rows"] = rows
    out["has_rows"] = bool(rows)
    return out


def build_prs(sp_: Mapping[str, Any]) -> dict[str, Any]:
    d = get_period_report(sp_)
    period, report = d.period, d.report
    out = empty()
    out["subtitle"] = describe_period(period)
    out["db_empty"] = d.db_empty
    if not report.rows:
        return out
    out["empty"] = False

    prs = by_credits_desc(by_pr(report))
    totals = compute_totals(report)
    sig = group_signals(report, lambda r: r.attribution.pr_key)
    days = period.days

    out["subtitle"] = f"How much does each PR cost? · {describe_period(period)}"
    out["stats"] = [txt(f"{plural(len(prs), 'PR', 'PRs')} with activity · {format_pct(totals.pct_with_pr)} of turns")]

    rows = []
    for p in prs:
        sessions = href_with("/sesiones", {"days": days, "pr": p.key})
        head = p.pr.head_branch if p.pr else None
        meta = [
            ext(f"{short_repo(p.repo)}!{p.number}", pr_url(p.repo, p.number), f"Pull request #{p.number} on GitHub", MONO),
            ext(head, branch_url(p.repo, head), "Head branch on GitHub", f"inline-block max-w-[16rem] truncate align-bottom {MONO}") if head else None,
            kit.state_badge(p.pr.state if p.pr else "unsynced"),
            txt(p.project_name) if p.project_name else None,
            real_chip() if sig.real(p.key) else None,
        ]
        detail = kit.detail_grid(
            [
                ("Branch", [ext(head, branch_url(p.repo, head), head, f"block truncate {MONO}") if head else muted("—")]),
                ("Repo", [ext(p.repo, github_repo_url(p.repo), "Repository on GitHub", f"block truncate {MONO}")]),
                ("API equivalent", kit.api_cost(p.api_equivalent_usd, p.turns, sig.unpriced(p.key))),
                ("Tokens", [txt(format_tokens(p.tokens))]),
                ("Confidence", kit.confidence_mix(p.confidence, "mt-2 w-28")),
            ]
        )
        rows.append(
            kit.row(
                [
                    td(
                        [_title_link(p.pr.title if p.pr else None, sessions, "PR")],
                        c="min-w-[18rem] max-w-[34rem]",
                        b=[box("mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-[12.5px] text-label-3", meta)],
                    ),
                    td([txt(format_int(p.turns))], right=True, b=[kit.sub([txt(plural(p.users, "person", "people"))])]),
                    td(kit.credits_stack(p), right=True),
                    td([txt(format_usd(p.subscription_usd))], right=True),
                    _key_links(p.issue_keys, days, "issue"),
                    kit.toggle_cell(),
                ],
                detail,
                rid=f"pr-{p.key}",
            )
        )
    out["rows"] = rows
    out["has_rows"] = bool(rows)
    return out
