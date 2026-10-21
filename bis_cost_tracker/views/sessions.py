"""Sessions (`/sesiones`), port of src/app/sesiones/page.tsx."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace
from functools import cmp_to_key
from typing import Any

from bis_core._js import encode_uri_component, locale_compare
from bis_core.app_data import describe_period, get_period_report, group_signals, href_with, langsmith_ref, param
from bis_core.db import get_db
from bis_core.db.content import list_skill_usage
from bis_core.links import branch_url, github_repo_url, langsmith_trace_url
from bis_core.report import NONE_KEY, RowFilters, filter_rows, list_conversations, parse_issue_key, parse_pr_key
from bis_core.report.format import format_date_time, format_int, format_tokens, format_usd

from bis_cost_tracker.views import kit
from bis_cost_tracker.views.kit import LINK, MONO, box, ext, link, muted, real_chip, td, txt

MAX_ROWS = 300


def repo_cells(repos: Sequence[str], branches: Sequence[Mapping[str, Any]], branch_titles: Sequence[str], c: str) -> dict[str, Any]:
    """"Repo and branches" cell: repos (GitHub links) over branches (links when the repo is known)."""
    repo_segs: list[dict[str, Any]] = []
    for k, repo in enumerate(repos):
        if k > 0:
            repo_segs.append(txt(", "))
        repo_segs.append(ext(repo, github_repo_url(repo), "Repository on GitHub"))
    if not repos:
        repo_segs.append(muted("no repo"))
    branch_segs: list[dict[str, Any]] = []
    for k, b in enumerate(branches):
        if k > 0:
            branch_segs.append(txt(", "))
        branch_segs.append(ext(b["branch"], branch_url(b["repo"], b["branch"]), "Branch on GitHub"))
    return td(
        None,
        c=c,
        b=[
            box(f"truncate {MONO}", repo_segs, ti=", ".join(repos)),
            box(f"mt-0.5 truncate text-label-3 {MONO}", branch_segs, ti=", ".join(branch_titles)),
        ],
    )


def issue_pr_links(issue_keys: Sequence[str], pr_keys: Sequence[str], days: int, with_titles: bool = True) -> dict[str, Any]:
    segs: list[dict[str, Any]] = []
    for k in issue_keys:
        n = (parse_issue_key(k) or {}).get("number", k)
        segs.append(link(f"#{n}", href_with("/sesiones", {"days": days, "issue": k}), LINK, ti=f"Sessions for {k}" if with_titles else ""))
    for k in pr_keys:
        n = (parse_pr_key(k) or {}).get("number", k)
        segs.append(link(f"!{n}", href_with("/sesiones", {"days": days, "pr": k}), LINK, ti=f"Sessions for {k}" if with_titles else ""))
    if not segs:
        segs.append(muted("—"))
    return td(None, c=MONO, b=[box("flex flex-wrap gap-x-2 gap-y-0.5", segs)])


def _session_links(rows: list[Any], ls: Any) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for r in sorted(rows, key=lambda r: r.turn.started_at):
        lk = out.setdefault(r.conversation_key, {"branches": [], "trace": None})
        b = r.turn.branch
        if b and not any(x["branch"] == b and x["repo"] == r.attribution.repo for x in lk["branches"]):
            lk["branches"].append({"repo": r.attribution.repo, "branch": b})
        if not lk["trace"] and r.turn.source == "langsmith":
            lk["trace"] = langsmith_trace_url(ls, r.turn.id, r.turn.trace_id)
    for lk in out.values():
        lk["branches"].sort(key=cmp_to_key(lambda x, y: locale_compare(x["branch"], y["branch"])))
    return out


def empty() -> dict[str, Any]:
    return {
        "empty": True,
        "db_empty": False,
        "subtitle": "",
        "form_key": "",
        "hidden": [],
        "teams": [],
        "projects": [],
        "users": [],
        "team": "",
        "project": "",
        "user": "",
        "sin_issue": False,
        "active": False,
        "clear_href": "/sesiones",
        "tokens": [],
        "count": "0",
        "count_rest": "",
        "has_rows": False,
        "rows": [],
    }


def build(sp_: Mapping[str, Any]) -> dict[str, Any]:
    d = get_period_report(sp_)
    period, report = d.period, d.report
    out = empty()
    out["subtitle"] = f"Copilot conversations, newest first · {describe_period(period)}"
    out["db_empty"] = d.db_empty
    if not report.rows:
        return out
    out["empty"] = False
    days = period.days
    f = RowFilters(
        team=param(sp_, "team"),
        project=param(sp_, "project"),
        user=param(sp_, "user"),
        issue=param(sp_, "issue"),
        pr=param(sp_, "pr"),
        no_issue=param(sp_, "sin_issue") == "1",
    )
    skill = param(sp_, "skill")
    skill_turns = {u.turn_id for u in list_skill_usage(get_db()) if u.skill == skill} if skill else None
    filtered = [r for r in filter_rows(report.rows, f) if skill_turns is None or r.turn.id in skill_turns]
    conversations = list_conversations(filtered)
    sig = group_signals(replace(report, rows=filtered), lambda r: r.conversation_key)
    links = _session_links(filtered, langsmith_ref())
    active = any(v for v in (f.team, f.project, f.user, f.issue, f.pr, f.no_issue)) or bool(skill)
    seen: dict[str, Any] = {}
    for r in report.rows:
        seen[r.attribution.user_name.lower() if r.attribution.user_name else NONE_KEY] = r
    users = [
        {"key": k, "label": "(unknown)" if k == NONE_KEY else (r.user_display_name or r.attribution.user_name or k)}
        for k, r in seen.items()
    ]
    users.sort(key=cmp_to_key(lambda a, b: locale_compare(a["label"], b["label"])))
    base = {"days": days, "team": f.team, "project": f.project, "user": f.user, "sin_issue": 1 if f.no_issue else None}

    hidden = []
    if days != 30:
        hidden.append({"name": "days", "value": str(days)})
    if f.issue:
        hidden.append({"name": "issue", "value": f.issue})
    if f.pr:
        hidden.append({"name": "pr", "value": f.pr})
    if skill:
        hidden.append({"name": "skill", "value": skill})
    out["hidden"] = hidden
    out["teams"] = [{"value": t.id, "label": t.name} for t in report.refs.teams] + [{"value": NONE_KEY, "label": "No team"}]
    out["projects"] = [{"value": p.id, "label": p.name} for p in report.refs.projects] + [{"value": NONE_KEY, "label": "No project"}]
    out["users"] = [{"value": u["key"], "label": u["label"]} for u in users]
    out["team"] = f.team or ""
    out["project"] = f.project or ""
    out["user"] = (f.user or "").lower()
    out["sin_issue"] = f.no_issue
    out["form_key"] = "|".join(str(x) for x in (days, f.team, f.project, f.user, f.issue, f.pr, f.no_issue, skill))
    out["active"] = active
    out["clear_href"] = href_with("/sesiones", {"days": days})
    tokens = []
    if f.issue:
        tokens.append({"label": "Issue", "value": f.issue, "href": href_with("/sesiones", {**base, "pr": f.pr, "skill": skill}), "aria": "Remove issue filter"})
    if f.pr:
        tokens.append({"label": "PR", "value": f.pr, "href": href_with("/sesiones", {**base, "issue": f.issue, "skill": skill}), "aria": "Remove PR filter"})
    if skill:
        tokens.append({"label": "Skill", "value": skill, "href": href_with("/sesiones", {**base, "issue": f.issue, "pr": f.pr}), "aria": "Remove skill filter"})
    out["tokens"] = tokens
    n_conv = len(conversations)
    out["count"] = format_int(n_conv)
    out["count_rest"] = (
        f" {'session' if n_conv == 1 else 'sessions'} · "
        + f"{format_int(len(filtered))} {'turn' if len(filtered) == 1 else 'turns'}"
        + (" matching the filters (each session’s figures count only those turns)" if active else "")
        + (f" · showing the {MAX_ROWS} most recent" if n_conv > MAX_ROWS else "")
    )
    out["has_rows"] = n_conv > 0
    rows = []
    for n, c in enumerate(conversations[:MAX_ROWS]):
        lk = links.get(c.key, {"branches": [], "trace": None})
        when = td(
            [link(format_date_time(c.last_at), href_with(f"/sesiones/{encode_uri_component(c.key)}", {"days": days}), "font-medium text-link tabular-nums hover:underline")],
            c="whitespace-nowrap",
            b=[
                box("mt-0.5 text-[12.5px] tabular-nums text-label-3", [txt(f"{format_int(c.turns)} {'turn' if c.turns == 1 else 'turns'} · since {format_date_time(c.first_at)}")]),
                box("mt-0.5 text-[12.5px]", [ext("LangSmith", lk["trace"], "First turn’s trace in LangSmith")]) if lk["trace"] else None,
            ],
        )
        who_name = c.user_display_name or c.user_name
        who = td(
            [txt(who_name, "font-medium") if who_name else muted("—")],
            c="whitespace-nowrap",
            b=[box("mt-0.5 flex items-center gap-2 text-[12.5px] text-label-3", [txt(c.team_name) if c.team_name else None, real_chip() if sig.real(c.key) else None])]
            if (c.team_name or sig.real(c.key))
            else [],
        )
        rows.append(
            kit.row(
                [
                    when,
                    who,
                    repo_cells(c.repos, lk["branches"], c.branches, "max-w-[16rem]"),
                    td(kit.credits_stack(c), right=True),
                    issue_pr_links(c.issue_keys, c.pr_keys, days),
                    kit.toggle_cell(),
                ],
                kit.detail_grid(
                    [
                        ("Tokens", [txt(format_tokens(c.tokens))]),
                        ("API equivalent", kit.api_cost(c.api_equivalent_usd, c.turns, sig.unpriced(c.key))),
                        ("Subscription", [txt(format_usd(c.subscription_usd))]),
                        ("Models", [txt(", ".join(c.models), f"block truncate {MONO}", ", ".join(c.models))] if c.models else [muted("—")]),
                        ("Confidence", kit.confidence_mix(c.confidence, "mt-2 w-28")),
                    ]
                ),
                rid=f"sesion-{n}",
            )
        )
    out["rows"] = rows
    return out
