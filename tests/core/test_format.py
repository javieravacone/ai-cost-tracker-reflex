"""Port of the "format" block of src/lib/report/report.test.ts, plus a parity table.

fixtures/format_cases_ts.json was produced by running the TS formatters (Node 24, en-US ICU)
on the inputs in NUMS and the date/time cases below (script: /tmp/opencode/fmt-cases.ts).
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from bis_core.cost import format_usd
from bis_core.report.format import (
    format_compact,
    format_credits,
    format_date,
    format_date_time,
    format_day,
    format_delta,
    format_int,
    format_month,
    format_number,
    format_pct,
    format_time,
    format_tokens,
    format_usd_axis,
    nice_ticks,
    plural,
    relative_time,
)

TS = json.loads((Path(__file__).parent / "fixtures" / "format_cases_ts.json").read_text(encoding="utf-8"))

NUMS = [0, -0.0, 0.004, 0.005, 0.0049, 0.05, 0.25, 0.28088, 1, 1.005, 1.25, 1.35, 2.45, 2.5, 9.995, 9.999, 10, 12.25, 123.45, 999.95, 999, 1000, 1234.5, 1530, 9999, 9999.5, 10000, 12300, 20392, 99999, 999999, 1000000, 1234567, 4560000, 1e9, 2.5e9, -0.04, -0.4, -1.5, -2.5, -12.5, -1234.567, 0.00001, 0.00005, 0.0042, 0.00999, 1234.567, 0.125, 0.135, 33.333333, 66.666666]  # fmt: skip

FNS = {
    "format_int": format_int,
    "format_number": format_number,
    "format_credits": format_credits,
    "format_tokens": format_tokens,
    "format_compact": format_compact,
    "format_pct": format_pct,
    "format_usd_axis": format_usd_axis,
    "format_usd": format_usd,
    "format_delta": format_delta,
}


# --- ported cases ----------------------------------------------------------------------------


def test_uses_en_us_grouping_and_decimals():
    assert format_int(1234567) == "1,234,567"
    assert format_int(1234) == "1,234"
    assert format_tokens(12_300) == "12.3 k"
    assert format_tokens(4_560_000) == "4.6 M"
    assert format_pct(0.42) == "42.0%"


def test_formats_ai_credits():
    assert format_credits(0) == "0"
    assert format_credits(0.001) == "<0.01"
    assert format_credits(0.28088) == "0.28"
    assert format_credits(123.45) == "123.5"
    assert format_credits(12_345.6) == "12,346"
    assert format_credits(math.nan) == "—"


def test_formats_compact_counts_and_deltas():
    assert format_compact(1_530) == "1.5 k"
    assert format_compact(20_392) == "20 k"
    assert format_delta(0.124) == "+12%"
    assert format_delta(-0.08) == "−8%"
    assert format_delta(0) == "0%"


def test_formats_en_us_dates_in_utc():
    iso = "2026-10-18T22:56:00Z"
    assert format_date_time(iso) == "Oct 18, 2026, 10:56 PM"
    assert format_date(iso) == "Oct 18, 2026"
    assert format_time(iso) == "10:56 PM"
    assert format_day("2026-10-06") == "Oct 6"
    assert format_month("2026-10") == "October 2026"
    assert format_date(None) == "—"


def test_formats_relative_times():  # from src/lib/sync/sync.test.ts ("summary formatting")
    at = "2026-10-17T10:00:00.000Z"
    t = 1_792_231_200_000  # Date.parse(at)
    assert relative_time(at, t - 5000) == "just now"
    assert relative_time(at, t + 30_000) == "just now"
    assert relative_time(at, t + 3 * 60_000) == "3 min ago"
    assert relative_time(at, t + 2 * 3_600_000) == "2 h ago"
    assert relative_time(at, t + 26 * 3_600_000) == "1 day ago"


# --- parity table against the TS formatters ----------------------------------------------------


@pytest.mark.parametrize("name", list(FNS))
def test_number_formatters_match_ts(name):
    got = [FNS[name](n) for n in NUMS]
    assert got == TS["nums"][name]


def test_nice_ticks_match_ts():
    for max_value, expected in TS["ticks"]:
        assert nice_ticks(max_value) == expected, max_value


def test_dates_match_ts():
    for iso, dt, d, t in TS["dates"]:
        assert (format_date_time(iso), format_date(iso), format_time(iso)) == (dt, d, t), iso
    for day, expected in TS["days"]:
        assert format_day(day) == expected
    for month, expected in TS["months"]:
        assert format_month(month) == expected


def test_relative_time_and_plural_match_ts():
    at = "2026-10-17T10:00:00.000Z"
    t = 1_792_231_200_000
    for delta, expected in TS["rel"]:
        assert relative_time(at, t + delta) == expected, delta
    for n, expected in TS["plural"]:
        assert plural(n, "session", "sessions") == expected if n != 1.4 else plural(n, "a", "b") == expected
