"""Skills (`/skills`), port of src/app/skills/page.tsx."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any

from bis_core.app_data import describe_period, get_period_report, href_with, param
from bis_core.db import get_db
from bis_core.links import blob_url, linkable_repo, repo_relative_path
from bis_core.report.format import format_credits, format_date, format_delta, format_number, format_pct, format_usd, plural
from bis_core.report.skills import SkillStat, load_skills_report, list_skill_usage

from bis_cost_tracker.views import kit
from bis_cost_tracker.views.kit import LINK, MONO, box, chip, ext, group, link, muted, td, txt

HOW = "A skill counts as used when Copilot reads its SKILL.md during the turn."


def empty() -> dict[str, Any]:
    return {"empty": True, "db_empty": False, "no_capture": False, "subtitle": "", "tiles": [], "has_skills": False, "none_text": "", "rows": []}


def _credits(n: float) -> str:
    return format_credits(n)


def _tools(n: float) -> str:
    return format_number(round(n * 10) / 10)


def compare(value: float | None, base: float | None, fmt: Callable[[float], str]) -> dict[str, Any]:
    """`<Compare>`: value plus a quiet delta vs. the no-skill baseline (lower is better)."""
    if value is None:
        return muted("—")
    delta = value / base - 1 if base is not None and base > 0 else None
    title = f"Same-team turns without any skill: {fmt(base)}" if base is not None else "No same-team turns without a skill yet"
    if delta is None:
        second = [txt("no baseline")]
    else:
        tone = "text-ok-text" if delta < -0.005 else "text-warn-text" if delta > 0.005 else ""
        second = [txt(format_delta(delta), tone), txt(f" vs {fmt(base)}")]  # type: ignore[arg-type]
    return group(
        [txt(fmt(value), "font-medium text-label"), group(second, "mt-0.5 text-[12px] text-label-3", title)],
        "inline-flex flex-col items-end",
    )


def skill_file_urls(rows: Sequence[Any], usage: Sequence[Any]) -> dict[str, str]:
    """SKILL.md on GitHub (default branch) per skill, when it was read inside a real repo."""
    by_id = {r.turn.id: r for r in rows}
    out: dict[str, str] = {}
    for u in usage:
        if u.skill in out:
            continue
        r = by_id.get(u.turn_id)
        repo = linkable_repo(r.attribution.repo) if r is not None and r.turn.source == "langsmith" else None
        if not repo:
            continue
        url = blob_url(repo, "HEAD", repo_relative_path(repo, u.path) or f".github/skills/{u.skill}/SKILL.md")
        if url:
            out[u.skill] = url
    return out


def _line(label: str, value: str) -> dict[str, Any]:
    return box("flex items-baseline justify-between gap-4 text-[13px]", [txt(label, "text-label-3"), txt(value, "tabular-nums text-label")])


def version_grid(s: SkillStat, sessions_href: str) -> dict[str, Any]:
    cols = [
        {
            "key": v.version or "unknown",
            "title": f"v{v.version}" if v.version else "unknown version",
            "stats": v,
            "sub": format_date(v.first_seen) if v.first_seen[:10] == v.last_seen[:10] else f"{format_date(v.first_seen)} – {format_date(v.last_seen)}",
            "mono": bool(v.version),
        }
        for v in s.versions
    ]
    cols.append({"key": "__baseline", "title": "No skill (same team)", "stats": s.baseline, "sub": "baseline", "mono": False})
    cards = []
    for c in cols:
        st = c["stats"]
        base = c["key"] == "__baseline"
        title = txt(c["title"]) if base else link(c["title"], sessions_href, "hover:text-link", ti="Sessions that used this skill")
        cards.append(
            box(
                f"rounded-[16px] px-4 py-3.5 {'bg-fill/50' if base else 'bg-surface/90 shadow-card'}",
                b=[
                    box(f"font-semibold text-label {MONO if c['mono'] else 'text-[13px]'}", [title]),
                    box("mt-0.5 text-[12px] text-label-3", [txt(c["sub"])]),
                    box(
                        "mt-3 space-y-1.5",
                        b=[
                            _line("Turns", format_number(st.turns)),
                            _line("Credits / turn", "—" if st.credits_per_turn is None else format_credits(st.credits_per_turn)),
                            _line("$ / turn", "—" if st.usd_per_turn is None else format_usd(st.usd_per_turn)),
                            _line("Tool calls / turn", "—" if st.tool_calls_per_turn is None else _tools(st.tool_calls_per_turn)),
                            _line("Error rate", "—" if st.error_rate is None else format_pct(st.error_rate)),
                        ],
                    ),
                ],
            )
        )
    return box(
        "space-y-3",
        b=[
            box("grid gap-3 [grid-template-columns:repeat(auto-fill,minmax(14rem,1fr))]", b=cards),
            box(
                "text-[12.5px] text-label-3",
                [txt("A version is the short hash of the SKILL.md text Copilot read, so any edit to the file starts a new version.")],
            ),
        ],
    )


def build(sp_: Mapping[str, Any]) -> dict[str, Any]:
    d = get_period_report(sp_)
    period, report = d.period, d.report
    expanded = param(d.sp, "skill")
    out = empty()
    out["subtitle"] = f"{HOW} · {describe_period(period)}"
    out["db_empty"] = d.db_empty
    if not report.rows:
        return out
    out["empty"] = False
    db = get_db()
    usage = list_skill_usage(db)
    r = load_skills_report(db, report.rows)
    file_urls = skill_file_urls(report.rows, usage)
    days = period.days
    if r.captured_turns == 0:
        out["no_capture"] = True
        return out

    out["tiles"] = [
        {"label": "Skills used", "value": [txt(format_number(len(r.skills)))], "hint": "distinct SKILL.md folders read"},
        {
            "label": "Turns with a skill",
            "value": [txt(format_pct(r.turns_with_skills / r.captured_turns if r.captured_turns else 0))],
            "hint": f"{plural(r.turns_with_skills, 'turn', 'turns')} of {plural(r.captured_turns, 'captured turn', 'captured turns')}",
        },
        {"label": "Versions seen", "value": [txt(format_number(sum(len(k.versions) for k in r.skills)))], "hint": "content hashes of SKILL.md"},
    ]
    out["none_text"] = plural(r.captured_turns, "captured turn", "captured turns")
    rows = []
    for s in r.skills:
        rid = f"skill-{s.name}"
        sessions = href_with("/sesiones", {"days": days, "skill": s.name})
        name = td(
            None,
            b=[
                box(
                    "flex flex-wrap items-center gap-2",
                    [
                        ext(s.name, file_urls.get(s.name), "SKILL.md on GitHub (default branch)", f"font-medium {MONO} text-[13px]"),
                        link("", sessions, "press rounded-full", ti="Sessions that used this skill", s=[chip(plural(len(s.versions), "version", "versions"))]),
                    ],
                ),
                kit.sub(
                    [
                        txt(f"{', '.join(s.teams) or 'No team'} · last used {format_date(s.last_seen)} · "),
                        link(plural(s.sessions, "session", "sessions"), sessions, LINK),
                    ]
                ),
            ],
        )
        credits_cell = td([compare(s.credits_per_turn, s.baseline.credits_per_turn, _credits)], right=True)
        if s.usd_per_turn is not None:
            credits_cell["b"].append(box("text-[12px] text-label-3", [txt(f"{format_usd(s.usd_per_turn)} / turn")]))
        rows.append(
            kit.row(
                [
                    name,
                    td([txt(format_number(s.turns), "font-medium text-label")], right=True, b=[kit.sub([txt(plural(s.people, "person", "people"))])]),
                    credits_cell,
                    td([compare(s.tool_calls_per_turn, s.baseline.tool_calls_per_turn, _tools)], right=True),
                    td(
                        [txt("—" if s.error_rate is None else format_pct(s.error_rate), "font-medium text-label")],
                        right=True,
                        b=[kit.sub([txt("no baseline" if s.baseline.error_rate is None else f"{format_pct(s.baseline.error_rate)} without")])],
                    ),
                    kit.toggle_cell("Compare versions", open_=expanded == s.name),
                ],
                version_grid(s, sessions),
                c="trow scroll-mt-24",
                rid=rid,
            )
        )
    out["rows"] = rows
    out["has_skills"] = bool(rows)
    return out
