"""Data for the app shell: period picker links, "Last synced", data-source status, sync toast."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from bis_core._js import now_ms
from bis_core.app_data import href_with, langsmith_ref
from bis_core.db import get_db, list_turns
from bis_core.links import langsmith_project_url
from bis_core.report import DAY_OPTIONS, DEFAULT_DAYS, parse_days
from bis_core.report.format import format_int
from bis_core.sync import SyncOutcome, clock_time, exact_time, read_last_sync, relative_time, summary_text


def days_query(days: int) -> str:
    """"?days=7" for the sidebar links (empty for the default period)."""
    return "" if days == DEFAULT_DAYS else f"?days={days}"


def period_links(path: str, query: Mapping[str, str]) -> list[dict[str, Any]]:
    """Segmented control links: keep the other params, drop ok/error, default days removed."""
    days = parse_days(query.get("days"))
    out = []
    for d in DAY_OPTIONS:
        # URLSearchParams keeps insertion order: an existing `days` stays in place.
        ordered: dict[str, str] = {}
        for k, v in query.items():
            if k in ("ok", "error"):
                continue
            if k == "days":
                if d != DEFAULT_DAYS:
                    ordered["days"] = str(d)
                continue
            ordered[k] = v
        if "days" not in query and d != DEFAULT_DAYS:
            ordered["days"] = str(d)
        out.append({"label": f"{d} days", "href": href_with(path, ordered), "selected": d == days})
    return out


def period_index(days: int) -> int:
    return DAY_OPTIONS.index(days) if days in DAY_OPTIONS else 0


def last_sync_view(now: int | None = None) -> dict[str, Any]:
    s = read_last_sync(get_db())
    t = now if now is not None else now_ms()
    if s is None:
        return {"never": True, "known": False, "label": "Never", "clock": "", "title": "Not synced yet"}
    return {
        "never": False,
        "known": True,
        "label": relative_time(s.at, t),
        "clock": f" ({clock_time(s.at)})",
        "title": exact_time(s.at),
    }


def source_status() -> dict[str, Any]:
    db = get_db()
    counts = {"seed": 0, "langsmith": 0}
    for t in list_turns(db):
        counts[t.source] = counts.get(t.source, 0) + 1
    total = counts["seed"] + counts["langsmith"]
    project_url = langsmith_project_url(langsmith_ref(db)) if counts["langsmith"] > 0 else None
    if total == 0:
        dot, title = "bg-conf-project", "Empty database"
    elif counts["langsmith"] > 0:
        dot, title = "bg-ok", "Real + sample data" if counts["seed"] > 0 else "Real data"
    else:
        dot, title = "bg-warn", "Sample data only"
    return {
        "dot": f"size-2 rounded-full {dot}",
        "title": title,
        "has_counts": total > 0,
        "langsmith": f"{format_int(counts['langsmith'])} LangSmith turns",
        "seed": f"{format_int(counts['seed'])} seed turns (fictional)",
        "project_url": project_url or "",
    }


def toast_view(outcome: SyncOutcome | None, error: bool = False) -> dict[str, Any]:
    """Same wording and tones as the Next app's sync toast."""
    if error or outcome is None:
        return {"show": True, "lead": "", "lines": ["Sync failed (network or server error)"], "tone": "text-bad-text"}
    if outcome.status == "busy":
        return {"show": True, "lead": "", "lines": ["A sync is already in progress"], "tone": "text-warn-text"}
    s = outcome.summary
    assert s is not None
    text = summary_text(s.new_turns, s.issues, s.pull_requests)
    if s.ok:
        return {"show": True, "lead": "", "lines": [f"✓ {text}"], "tone": "text-ok-text"}
    return {
        "show": True,
        "lead": text,
        "lines": list(s.errors),
        "tone": "text-bad-text" if len(s.errors) > 1 else "text-warn-text",
    }


EMPTY_TOAST: dict[str, Any] = {"show": False, "lead": "", "lines": [], "tone": ""}
