"""Display helpers, en-US locale (port of src/lib/report/format.ts).

Currency stays in `format_usd` (bis_core.cost). `relative_time` mirrors `relativeTime` from
src/lib/sync/summary.ts so the UI can format "3 min ago" without importing the sync package.
"""

from __future__ import annotations

import math
from datetime import datetime

from bis_core._js import (
    intl_number,
    is_finite,
    is_integer,
    js_round,
    num_str,
    parse_iso_ms,
    to_fixed,
    to_precision_number,
    utc_from_ms,
)
from bis_core.cost import format_usd
from bis_core.types import Confidence

__all__ = [
    "CONFIDENCE_HELP",
    "CONFIDENCE_LABEL",
    "format_compact",
    "format_credits",
    "format_date",
    "format_date_time",
    "format_day",
    "format_delta",
    "format_int",
    "format_month",
    "format_number",
    "format_pct",
    "format_time",
    "format_tokens",
    "format_usd",
    "format_usd_axis",
    "nice_ticks",
    "plural",
    "ratio",
    "relative_time",
    "short_repo",
]


def _int(n: float) -> str:
    return intl_number(n, 0, 0)


def _up_to1(n: float) -> str:
    return intl_number(n, 0, 1)


def _dec1(n: float) -> str:
    return intl_number(n, 1, 1)


def _dec2(n: float) -> str:
    return intl_number(n, 2, 2)


def format_int(n: float) -> str:
    """1234567 -> "1,234,567". Non-finite -> "—"."""
    return _int(js_round(n)) if is_finite(n) else "—"


def format_number(n: float) -> str:
    """Premium requests can be fractional multipliers (0.33x); one decimal when needed."""
    if not is_finite(n):
        return "—"
    return _int(n) if is_integer(n) else _dec1(n)


def format_credits(n: float) -> str:
    """GitHub AI credits (1 credit = $0.01): 0.28088 -> "0.28", 123.45 -> "123.5",
    12345 -> "12,345"; tiny positive values -> "<0.01". Non-finite -> "—"."""
    if not is_finite(n):
        return "—"
    a = abs(n)
    if a == 0:
        return "0"
    if a < 0.005:
        return "-<0.01" if n < 0 else "<0.01"
    if a < 10:
        return _dec2(n)
    if a < 1000:
        return _dec1(n)
    return _int(js_round(n))


def format_tokens(n: float) -> str:
    """Compact token counts: 950 -> "950", 12_300 -> "12.3 k", 4_560_000 -> "4.6 M"."""
    if not is_finite(n):
        return "—"
    a = abs(n)
    if a >= 1e9:
        return f"{_dec1(n / 1e9)} B"
    if a >= 1e6:
        return f"{_dec1(n / 1e6)} M"
    if a >= 1e4:
        return f"{_dec1(n / 1e3)} k"
    return _int(n)


def format_compact(n: float) -> str:
    """Compact counts: 0 -> "0", 2.4 -> "2.4", 840 -> "840", 1_530 -> "1.5 k", 20_392 -> "20 k"."""
    if not is_finite(n):
        return "—"
    a = abs(n)
    if a >= 1e6:
        return f"{_up_to1(n / 1e6)} M"
    if a >= 1e4:
        return f"{_int(js_round(n / 1e3))} k"
    if a >= 1e3:
        return f"{_up_to1(n / 1e3)} k"
    if a >= 10 or is_integer(n):
        return _int(js_round(n))
    return _up_to1(n)


def format_delta(change: float) -> str:
    """Relative change as a signed percentage: 0.124 -> "+12%", -0.08 -> "−8%", 0 -> "0%"."""
    if not is_finite(change):
        return "—"
    pct = js_round(change * 100)
    if pct == 0:
        return "0%"
    return f"{'+' if pct > 0 else '−'}{_int(abs(pct))}%"


def format_pct(r: float) -> str:
    """ratio 0..1 -> "42.0%"."""
    if not is_finite(r):
        return "—"
    return f"{_dec1(r * 100)}%"


def ratio(part: float, total: float) -> float:
    return part / total if total > 0 else 0


def plural(n: float, one: str, many: str) -> str:
    """1 -> "1 session", 3 -> "3 sessions" (count + noun)."""
    return f"{format_int(n)} {one if is_finite(n) and js_round(n) == 1 else many}"


def short_repo(repo: str) -> str:
    """"owner/name" -> "name" (the full repo goes in a tooltip)."""
    i = repo.rfind("/")
    return repo[i + 1 :] if i >= 0 else repo


def format_usd_axis(n: float) -> str:
    """Short USD for chart axes: 0 -> "$0", 12 -> "$12", 0.5 -> "$0.50", 1500 -> "$1.5k"."""
    if not is_finite(n):
        return "—"
    if n == 0:
        return "$0"
    a = abs(n)
    if a >= 1000:
        return f"${to_fixed(n / 1000, 0 if a >= 10_000 else 1)}k"
    if is_integer(n):
        return f"${num_str(n)}"
    return f"${to_fixed(n, 3)}" if a < 0.01 else f"${to_fixed(n, 2)}"


def nice_ticks(max_value: float, target: int = 4) -> list[float]:
    """"Nice" axis ticks from 0 to >= max using a 1-2-5 sequence. Returns at least [0, step]."""
    if not is_finite(max_value) or max_value <= 0:
        return [0, 1]
    raw = max_value / max(1, target)
    mag = 10.0 ** math.floor(math.log10(raw))
    norm = raw / mag
    step = (1 if norm <= 1 else 2 if norm <= 2 else 2.5 if norm <= 2.5 else 5 if norm <= 5 else 10) * mag
    ticks: list[float] = []
    v = 0.0
    while v < max_value + step * 0.999:
        ticks.append(_clean(to_precision_number(v, 12)))
        v += step
    return ticks if len(ticks) >= 2 else [0, _clean(step)]


def _clean(x: float) -> float | int:
    return int(x) if isinstance(x, float) and x.is_integer() else x


# --- Dates (Intl.DateTimeFormat en-US, UTC) ------------------------------------------------

_MONTHS_SHORT = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
_MONTHS_LONG = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)


def _clock(dt: datetime) -> str:
    h = dt.hour % 12 or 12
    return f"{h}:{dt.minute:02d} {'AM' if dt.hour < 12 else 'PM'}"


def _medium(dt: datetime) -> str:
    return f"{_MONTHS_SHORT[dt.month - 1]} {dt.day}, {dt.year}"


def format_date_time(iso: str | None) -> str:
    """"Oct 16, 2026, 9:30 AM" (UTC)."""
    if not iso:
        return "—"
    t = parse_iso_ms(iso)
    if t is None:
        return iso
    dt = utc_from_ms(t)
    return f"{_medium(dt)}, {_clock(dt)}"


def format_date(iso: str | None) -> str:
    """"Oct 16, 2026" (UTC)."""
    if not iso:
        return "—"
    t = parse_iso_ms(iso)
    return iso if t is None else _medium(utc_from_ms(t))


def format_time(iso: str | None) -> str:
    """"9:30 AM" (UTC)."""
    if not iso:
        return "—"
    t = parse_iso_ms(iso)
    return "" if t is None else _clock(utc_from_ms(t))


def format_day(day: str) -> str:
    """"YYYY-MM-DD" -> "Oct 16"."""
    t = parse_iso_ms(f"{day}T00:00:00Z")
    if t is None:
        return day
    dt = utc_from_ms(t)
    return f"{_MONTHS_SHORT[dt.month - 1]} {dt.day}"


def format_month(month: str) -> str:
    """"YYYY-MM" -> "October 2026"."""
    t = parse_iso_ms(f"{month}-01T00:00:00Z")
    if t is None:
        return month
    dt = utc_from_ms(t)
    return f"{_MONTHS_LONG[dt.month - 1]} {dt.year}"


def format_range_date(ms: float) -> str:
    """Intl en-US {day: numeric, month: short, year: numeric} in UTC: "Oct 10, 2026"."""
    return _medium(utc_from_ms(ms))


def relative_time(at: str | float, now: float) -> str:
    """"just now", "3 min ago", "2 h ago", "4 days ago" (future clamps to "just now")."""
    at_ms = at if isinstance(at, (int, float)) else parse_iso_ms(at)
    if at_ms is None:
        diff = math.nan
    else:
        diff = max(0, now - at_ms)
    if math.isnan(diff):
        # JS: Math.max(0, NaN) is NaN, every comparison is false -> "NaN days ago".
        return "NaN days ago"
    minutes = math.floor(diff / 60_000)
    if minutes < 1:
        return "just now"
    if minutes < 60:
        return f"{minutes} min ago"
    h = math.floor(minutes / 60)
    if h < 24:
        return f"{h} h ago"
    d = math.floor(h / 24)
    return "1 day ago" if d == 1 else f"{d} days ago"


CONFIDENCE_LABEL: dict[Confidence, str] = {
    "manual": "Manual",
    "exact-branch": "Branch",
    "exact-pr": "PR",
    "exact-commit": "Commit",
    "inferred": "Inferred",
    "project": "Project only",
}

CONFIDENCE_HELP: dict[Confidence, str] = {
    "manual": "Assigned by hand to an issue/PR from the session view. Takes precedence over everything else.",
    "exact-branch": "The branch contains the issue number (e.g. feat/123-login → #123).",
    "exact-pr": "The branch is the head branch of a synced PR; the issue comes from its single linked issue.",
    "exact-commit": "The turn's commit belongs to a synced PR; the issue comes from its single linked issue.",
    "inferred": "Inferred from content (phase 2, not implemented yet).",
    "project": "Only the project is known (from the repo), or not even that: default branch, no PR or issue.",
}
