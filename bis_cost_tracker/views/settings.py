"""Settings (`/ajustes`), port of src/app/ajustes/page.tsx."""

from __future__ import annotations

from typing import Any

from bis_core.cost import AI_CREDIT_USD, NANO_PER_CREDIT
from bis_core.db import get_db
from bis_core.db.content import content_stats
from bis_core.links import github_repo_url
from bis_core.report import load_refs
from bis_core.report.format import format_date_time, format_int, format_number, format_usd, plural

from bis_cost_tracker.views import kit
from bis_cost_tracker.views.kit import MONO, chip, ext, muted, sp, td, txt


def _usd_per_m(n: float) -> str:
    return f"{format_usd(n)} / M"


def empty() -> dict[str, Any]:
    return {
        "has_content": False,
        "content_lead": "",
        "content_rest": "",
        "events": "",
        "manual_hint": "",
        "manual_count": "",
        "credit_rule": "",
        "prices_subtitle": "",
        "prices": [],
        "plans_subtitle": "",
        "plans": [],
        "mappings_subtitle": "",
        "mappings": [],
        "entities_subtitle": "",
        "entities": [],
        "members_subtitle": "",
        "members": [],
    }


def build() -> dict[str, Any]:
    db = get_db()
    refs = load_refs(db)
    content = content_stats(db)
    team_name = {t.id: t.name for t in refs.teams}
    project_name = {p.id: p.name for p in refs.projects}
    plan_name = {p.id: p.name for p in refs.seat_plans}
    out = empty()

    out["has_content"] = content.turns_with_content > 0
    out["content_lead"] = f"{plural(content.turns_with_content, 'turn has', 'turns have')} captured content"
    last = f"; last stored {format_date_time(content.last_captured_at)} UTC" if content.last_captured_at else ""
    out["content_rest"] = f" ({plural(content.events, 'agent step', 'agent steps')}, {plural(content.skill_uses, 'turn', 'turns')} with a skill{last})."
    out["events"] = format_int(content.events)
    n_manual = len(refs.manual_assignments)
    out["manual_hint"] = f"SQLite · {plural(n_manual, 'manual assignment', 'manual assignments')}"
    out["manual_count"] = format_int(n_manual)
    out["credit_rule"] = f"1 credit = {format_int(NANO_PER_CREDIT)} nano = {format_usd(AI_CREDIT_USD)}"

    out["prices_subtitle"] = f"{plural(len(refs.prices), 'model', 'models')} · USD per million tokens"
    out["prices"] = [
        kit.row(
            [
                td([txt(p.model), sp(), chip("prefix")] if p.model.endswith("*") else [txt(p.model), sp()], c=f"whitespace-nowrap {MONO}"),
                td([txt(_usd_per_m(p.input_per_mtok))], right=True),
                td([txt(_usd_per_m(p.output_per_mtok))], right=True),
                td([txt(_usd_per_m(p.cache_read_per_mtok))], right=True),
                td([txt(_usd_per_m(p.cache_write_per_mtok))], right=True),
                td([chip("included ×0", "ok") if p.premium_multiplier == 0 else txt(f"×{format_number(p.premium_multiplier)}")], right=True),
            ]
        )
        for p in refs.prices
    ]

    out["plans_subtitle"] = plural(len(refs.seat_plans), "plan", "plans")
    out["plans"] = [
        kit.row(
            [
                td([txt(p.name, "font-medium")], b=[kit.box(f"text-label-3 {MONO}", [txt(p.id)])]),
                td([txt(format_usd(p.monthly_price_usd))], right=True),
                td([txt(format_int(p.included_ai_credits))], right=True),
                td([txt(format_int(p.included_premium_requests))], right=True),
                td([txt(format_usd(p.overage_per_premium_request_usd))], right=True),
            ]
        )
        for p in refs.seat_plans
    ]

    out["mappings_subtitle"] = plural(len(refs.repo_mappings), "mapping", "mappings")
    out["mappings"] = [
        kit.row(
            [
                td([ext(m.repo, github_repo_url(m.repo), "Repository on GitHub")], c=MONO),
                td([txt(project_name[m.project_id]) if m.project_id in project_name else muted(f"{m.project_id} (doesn’t exist)")]),
            ]
        )
        for m in refs.repo_mappings
    ]

    out["entities_subtitle"] = f"{plural(len(refs.teams), 'team', 'teams')} · {plural(len(refs.projects), 'project', 'projects')}"
    out["entities"] = [kit.row([td([chip("Team", "info")]), td([txt(t.id)], c=MONO), td([txt(t.name)])]) for t in refs.teams] + [
        kit.row([td([chip("Project")]), td([txt(p.id)], c=MONO), td([txt(p.name)])]) for p in refs.projects
    ]

    out["members_subtitle"] = f"{plural(len(refs.members), 'person', 'people')} with a seat"
    out["members"] = [
        kit.row(
            [
                td([txt(m.user_name)], c=MONO),
                td([txt(m.display_name)]),
                td([txt(team_name.get(m.team_id, m.team_id))]),
                td([txt(plan_name.get(m.seat_plan_id, m.seat_plan_id))]),
            ]
        )
        for m in refs.members
    ]
    return out
