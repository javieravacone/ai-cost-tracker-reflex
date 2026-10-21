"""Reporting periods (port of src/lib/report/range.ts).

All dates are UTC; ranges are [from_, to) ISO strings, the same convention as `list_turns`.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from bis_core._js import DAY_MS, date_utc, iso_from_ms, js_number, now_ms, parse_iso_ms

DAY_OPTIONS: tuple[int, ...] = (7, 30, 60, 90)
DEFAULT_DAYS = 30


@dataclass
class DateRange:
    from_: str  # inclusive, ISO 8601
    to: str  # exclusive, ISO 8601


@dataclass
class PeriodRange(DateRange):
    days: int


def parse_days(value: Any) -> int:
    """`?days=` value -> one of DAY_OPTIONS; anything else (missing, invalid, arrays) -> DEFAULT_DAYS."""
    raw = value[0] if isinstance(value, (list, tuple)) and value else (None if isinstance(value, (list, tuple)) else value)
    n = js_number(raw)
    if isinstance(n, float) and math.isnan(n):
        return DEFAULT_DAYS
    return int(n) if n in DAY_OPTIONS else DEFAULT_DAYS


def _start_of_utc_day(ms: int) -> int:
    return (ms // DAY_MS) * DAY_MS


def _now_ms(now: datetime | int | float | None) -> int:
    if now is None:
        return now_ms()
    if isinstance(now, datetime):
        return math.floor(now.timestamp() * 1000)
    return int(now)


def range_from_days(days: int, now: datetime | int | float | None = None) -> PeriodRange:
    """The last `days` calendar days (UTC) including today:
    from = today 00:00 - (days - 1) days, to = tomorrow 00:00."""
    today = _start_of_utc_day(_now_ms(now))
    return PeriodRange(
        days=days,
        from_=iso_from_ms(today - (days - 1) * DAY_MS),
        to=iso_from_ms(today + DAY_MS),
    )


def range_from_search_params(search_params: Mapping[str, Any], now: datetime | int | float | None = None) -> PeriodRange:
    return range_from_days(parse_days(search_params.get("days")), now)


def day_of(iso: str) -> str:
    """"YYYY-MM-DD" (UTC) of an ISO timestamp."""
    t = parse_iso_ms(iso)
    return iso[:10] if t is None else iso_from_ms(t)[:10]


def days_in_range(r: DateRange) -> list[str]:
    """Every UTC day touched by [from_, to), as "YYYY-MM-DD"."""
    start = parse_iso_ms(r.from_)
    end = parse_iso_ms(r.to)
    if start is None or end is None:
        return []
    out: list[str] = []
    t = _start_of_utc_day(start)
    while t < end:
        out.append(iso_from_ms(t)[:10])
        t += DAY_MS
    return out


def _month_start_ms(month: str) -> int:
    return date_utc(int(month[0:4]), int(month[5:7]) - 1, 1)


def _next_month_start_ms(month: str) -> int:
    return date_utc(int(month[0:4]), int(month[5:7]), 1)


def months_in_range(r: DateRange) -> list[str]:
    """Every UTC calendar month touched by [from_, to), as "YYYY-MM"."""
    from_ms = parse_iso_ms(r.from_)
    to_ms = parse_iso_ms(r.to)
    if from_ms is None or to_ms is None or to_ms - 1 < from_ms:
        return []
    last_ms = to_ms - 1
    out: list[str] = []
    month = iso_from_ms(from_ms)[:7]
    last = iso_from_ms(last_ms)[:7]
    while month <= last:
        out.append(month)
        month = iso_from_ms(_next_month_start_ms(month))[:7]
    return out


def full_months_range(r: DateRange) -> DateRange | None:
    """[first day of the first month, first day of the month after the last) covering the range."""
    months = months_in_range(r)
    if not months:
        return None
    return DateRange(from_=iso_from_ms(_month_start_ms(months[0])), to=iso_from_ms(_next_month_start_ms(months[-1])))


def month_share(month: str, r: DateRange) -> float:
    """Fraction (0..1) of calendar month `month` ("YYYY-MM") that falls inside [from_, to)."""
    start = _month_start_ms(month)
    end = _next_month_start_ms(month)
    to_ms = parse_iso_ms(r.to)
    from_ms = parse_iso_ms(r.from_)
    if to_ms is None or from_ms is None:
        return 0
    overlap = min(end, to_ms) - max(start, from_ms)
    return overlap / (end - start) if overlap > 0 else 0
