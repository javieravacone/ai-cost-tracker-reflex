"""Shared shapes and formatters for the "Sync" button (port of src/lib/sync/summary.ts).

The persisted JSON (`sync_state['app.lastSync']`) uses the same camelCase keys as the TS app so
both apps can read each other's last sync.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

LAST_SYNC_KEY = "app.lastSync"


@dataclass
class SyncSummary:
    """Persisted in sync_state under `app.lastSync` after every full sync."""

    at: str  # ISO time the sync finished
    ok: bool  # True when no source reported an error
    new_turns: int
    turns: int
    issues: int
    pull_requests: int
    errors: list[str] = field(default_factory=list)  # short user-facing messages, never secrets
    duration_ms: int = 0

    def to_json(self) -> str:
        """Same JSON as `JSON.stringify(summary)` in the TS app (key order and names)."""
        return json.dumps(
            {
                "at": self.at,
                "ok": self.ok,
                "newTurns": self.new_turns,
                "turns": self.turns,
                "issues": self.issues,
                "pullRequests": self.pull_requests,
                "errors": self.errors,
                "durationMs": self.duration_ms,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )


@dataclass
class SyncOutcome:
    """`{status: "busy"}` or `{status: "done", ...summary}`."""

    status: Literal["done", "busy"]
    summary: SyncSummary | None = None


def _parse_date(s: str) -> datetime | None:
    try:
        d = datetime.fromisoformat(s)
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _num(v: Any) -> int | float:
    """`Number(v) || 0` for JSON values (NaN and unparsable values become 0)."""
    if isinstance(v, bool):
        n: float = float(v)
    elif isinstance(v, (int, float)):
        n = v
    elif isinstance(v, str):
        try:
            n = float(v.strip()) if v.strip() else 0.0
        except ValueError:
            n = math.nan
    else:
        n = math.nan
    if isinstance(n, float):
        if math.isnan(n):
            return 0
        if n.is_integer():
            return int(n)
    return n


def _js_string(v: Any) -> str:
    """`String(v)` for JSON values."""
    if isinstance(v, str):
        return v
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, list):
        return ",".join("" if x is None else _js_string(x) for x in v)
    return "[object Object]"


def parse_sync_summary(raw: str | None) -> SyncSummary | None:
    """Parses the stored `app.lastSync` JSON; None when missing or malformed."""
    if not raw:
        return None
    try:
        v = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(v, dict):
        return None
    at = v.get("at")
    if not isinstance(at, str) or _parse_date(at) is None:
        return None
    errors = v.get("errors")
    return SyncSummary(
        at=at,
        ok=v.get("ok") is True,
        new_turns=_num(v.get("newTurns")),
        turns=_num(v.get("turns")),
        issues=_num(v.get("issues")),
        pull_requests=_num(v.get("pullRequests")),
        errors=[_js_string(e) for e in errors] if isinstance(errors, list) else [],
        duration_ms=_num(v.get("durationMs")),
    )


def _plural(n: int, one: str, many: str) -> str:
    return f"{n:,} {one if n == 1 else many}"


def summary_text(new_turns: int, issues: int, pull_requests: int) -> str:
    """'3 new turns · 8 issues · 4 PRs'."""
    return " · ".join(
        [
            _plural(new_turns, "new turn", "new turns"),
            _plural(issues, "issue", "issues"),
            _plural(pull_requests, "PR", "PRs"),
        ]
    )


def _to_datetime(at: str | datetime) -> datetime:
    if isinstance(at, datetime):
        return at if at.tzinfo else at.replace(tzinfo=timezone.utc)
    d = _parse_date(at)
    if d is None:
        raise ValueError(f"Invalid time value {at!r}")
    return d


def _epoch_ms(d: datetime) -> int:
    return math.floor(d.timestamp() * 1000)


def relative_time(at: str | datetime, now_ms: int | float) -> str:
    """'just now', '3 min ago', '2 h ago', '4 days ago' (future clamps to 'just now')."""
    diff = max(0, now_ms - _epoch_ms(_to_datetime(at)))
    minutes = math.floor(diff / 60_000)
    if minutes < 1:
        return "just now"
    if minutes < 60:
        return f"{minutes} min ago"
    hours = math.floor(minutes / 60)
    if hours < 24:
        return f"{hours} h ago"
    days = math.floor(hours / 24)
    return "1 day ago" if days == 1 else f"{days} days ago"


_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def clock_time(at: str | datetime) -> str:
    """'10:41 PM' in the local time zone (en-US, like `Intl.DateTimeFormat`)."""
    d = _to_datetime(at).astimezone()
    hour = d.hour % 12 or 12
    return f"{hour}:{d.minute:02d} {'AM' if d.hour < 12 else 'PM'}"


def exact_time(at: str | datetime) -> str:
    """'Oct 17, 2026, 10:41 PM' in the local time zone (en-US, like `Intl.DateTimeFormat`)."""
    d = _to_datetime(at).astimezone()
    return f"{_MONTHS[d.month - 1]} {d.day}, {d.year}, {clock_time(d)}"
