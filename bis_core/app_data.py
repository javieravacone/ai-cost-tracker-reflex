"""App-level data helpers for the pages (port of the pure parts of src/app/_lib/data.ts).

No web framework imports: the UI layer passes query params as a plain mapping.
"""

from __future__ import annotations

import os
import re
import sqlite3
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, TypeVar
from urllib.parse import unquote_to_bytes

from bis_core._js import encode_uri_component, iso_from_ms, js_number, now_ms, num_str, parse_iso_ms
from bis_core.db import get_db, get_sync_state, list_turns
from bis_core.links import LangsmithRef, linkable_repo
from bis_core.report import (
    DEFAULT_DAYS,
    NONE_KEY,
    PeriodRange,
    Report,
    ReportRow,
    load_report,
    range_from_search_params,
    summarize,
)
from bis_core.report.format import format_range_date

__all__ = [
    "LANGSMITH_PROJECT_ID_KEY",
    "LANGSMITH_TENANT_ID_KEY",
    "GroupSignals",
    "PeriodData",
    "PreviousCredits",
    "by_credits_desc",
    "describe_period",
    "get_period_report",
    "group_signals",
    "href_with",
    "langsmith_ref",
    "param",
    "person_href",
    "previous_period_credits",
    "real_repos_by_project",
    "safe_decode",
    "team_href",
]

# Same keys as src/lib/sync/langsmith.ts (learnt by the LangSmith sync).
LANGSMITH_PROJECT_ID_KEY = "langsmith.projectId"
LANGSMITH_TENANT_ID_KEY = "langsmith.tenantId"

SearchParams = Mapping[str, Any]
T = TypeVar("T")


def param(sp: SearchParams, name: str) -> str | None:
    v = sp.get(name)
    s = v[0] if isinstance(v, (list, tuple)) and v else (None if isinstance(v, (list, tuple)) else v)
    return None if s is None or s == "" else s


_FORM_SAFE = re.compile(r"[A-Za-z0-9*\-._]")


def _form_encode(s: str) -> str:
    """application/x-www-form-urlencoded, as URLSearchParams serializes it."""
    out: list[str] = []
    for ch in s:
        if ch == " ":
            out.append("+")
        elif _FORM_SAFE.fullmatch(ch):
            out.append(ch)
        else:
            out.append("".join(f"%{b:02X}" for b in ch.encode("utf-8", "surrogatepass")))
    return "".join(out)


def _js_string(v: Any) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return num_str(v)
    return str(v)


def href_with(path: str, params: Mapping[str, Any]) -> str:
    """Builds "path?query", dropping empty values and the default `days`."""
    qs: dict[str, str] = {}
    for k, v in params.items():
        if v is None or v == "":
            continue
        if k == "days" and js_number(v) == DEFAULT_DAYS:
            continue
        qs[k] = _js_string(v)
    s = "&".join(f"{_form_encode(k)}={_form_encode(v)}" for k, v in qs.items())
    return f"{path}?{s}" if s else path


def team_href(team_id: str, days: int) -> str:
    """Team detail page (`/equipos/[id]`), keeping `?days=`."""
    return href_with(f"/equipos/{encode_uri_component(team_id)}", {"days": days})


def person_href(user_name: str, days: int) -> str:
    """Person detail page (`/personas/[user]`), keeping `?days=`."""
    return href_with(f"/personas/{encode_uri_component(user_name)}", {"days": days})


def safe_decode(s: str) -> str:
    """Route params arrive URL-encoded; a malformed escape is kept as is."""
    if re.search(r"%(?![0-9a-fA-F]{2})", s):
        return s
    try:
        return unquote_to_bytes(s).decode("utf-8")
    except UnicodeDecodeError:
        return s


def langsmith_ref(db: sqlite3.Connection | None = None) -> LangsmithRef:
    """LangSmith endpoint and ids (learnt by the sync) needed to build UI links."""
    conn = db if db is not None else get_db()
    return LangsmithRef(
        endpoint=os.environ.get("LANGSMITH_ENDPOINT"),
        tenant_id=get_sync_state(conn, LANGSMITH_TENANT_ID_KEY),
        project_id=get_sync_state(conn, LANGSMITH_PROJECT_ID_KEY),
    )


def real_repos_by_project(report: Report) -> dict[str, list[str]]:
    """Real GitHub repos mapped to each project (fictional seed repos have no page to link to)."""
    out: dict[str, list[str]] = {}
    for m in report.refs.repo_mappings:
        if linkable_repo(m.repo):
            out.setdefault(m.project_id, []).append(m.repo)
    return out


@dataclass
class PeriodData:
    sp: SearchParams
    period: PeriodRange
    report: Report
    db_empty: bool  # True when the DB has no turns at all (not just in this period)
    now: int  # request time (ms), for relative times ("2 h ago")


def get_period_report(
    search_params: SearchParams,
    db: sqlite3.Connection | None = None,
    now: int | None = None,
) -> PeriodData:
    conn = db if db is not None else get_db()
    t = now if now is not None else now_ms()
    period = range_from_search_params(search_params, t)
    report = load_report(conn, period)
    db_empty = len(report.rows) == 0 and len(list_turns(conn)) == 0
    return PeriodData(sp=search_params, period=period, report=report, db_empty=db_empty, now=t)


@dataclass
class GroupSignals:
    """Per-group presentation signals: how many turns use a model without a price (their API
    cost is $0) and whether any turn is real (LangSmith, not seed)."""

    unpriced_by_key: dict[str, int]
    real_keys: set[str]

    def unpriced(self, key: str) -> int:
        return self.unpriced_by_key.get(key, 0)

    def real(self, key: str) -> bool:
        return key in self.real_keys


def group_signals(report: Report, key_of: Callable[[ReportRow], str | None]) -> GroupSignals:
    """`key_of` must match the grouping used by the report helper (None -> NONE_KEY)."""
    unpriced_models = {m.model for m in report.unpriced_models}
    unpriced: dict[str, int] = {}
    real: set[str] = set()
    for r in report.rows:
        k = key_of(r)
        key = NONE_KEY if k is None else k
        if r.turn.model in unpriced_models:
            unpriced[key] = unpriced.get(key, 0) + 1
        if r.turn.source == "langsmith":
            real.add(key)
    return GroupSignals(unpriced_by_key=unpriced, real_keys=real)


def describe_period(p: PeriodRange) -> str:
    """"Last 30 days: Sep 22, 2026 – Oct 21, 2026 (UTC)"."""
    from_ms = parse_iso_ms(p.from_)
    to_ms = parse_iso_ms(p.to)
    if from_ms is None or to_ms is None:
        raise ValueError("Invalid time value")
    return f"Last {p.days} days: {format_range_date(from_ms)} – {format_range_date(to_ms - 1)} (UTC)"


@dataclass
class PreviousCredits:
    ai_credits: float
    turns: int
    credit_turns: int


def previous_period_credits(p: PeriodRange, db: sqlite3.Connection | None = None) -> PreviousCredits | None:
    """Real consumption in the period of the same length right before `p` (for the "vs previous
    period" delta). None when that period has no turn with AI-credit data."""
    from_ms = parse_iso_ms(p.from_)
    to_ms = parse_iso_ms(p.to)
    if from_ms is None or to_ms is None:
        return None
    span = to_ms - from_ms
    conn = db if db is not None else get_db()
    m = summarize(load_report(conn, iso_from_ms(from_ms - span), p.from_).rows)
    return PreviousCredits(ai_credits=m.ai_credits, turns=m.turns, credit_turns=m.credit_turns) if m.credit_turns > 0 else None


def by_credits_desc(items: list[T]) -> list[T]:
    """Presentation order for tables and lists that lead with real consumption: AI credits desc,
    then the library order (API-equivalent cost); the NONE bucket stays last."""
    indexed = list(enumerate(items))
    indexed.sort(key=lambda x: (int(getattr(x[1], "key") == NONE_KEY), -getattr(x[1], "ai_credits"), x[0]))
    return [it for _, it in indexed]
