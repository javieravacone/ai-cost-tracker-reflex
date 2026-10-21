"""Geometry of the daily bar chart (port of `DailyBars` in src/components/ui.tsx).

Everything is computed here so the component only draws SVG elements from plain numbers.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from bis_core.report.format import format_usd, format_usd_axis, nice_ticks

W = 1000
H = 240
AXIS = 54
BOTTOM = 28
TOP = 10


def _n(x: float) -> str:
    """Number as JS would print it in an SVG attribute (no trailing .0)."""
    if float(x).is_integer():
        return str(int(x))
    return repr(float(x))


def bar_path(x: float, y: float, w: float, h: float, r: float) -> str:
    """Bar with rounded top corners only (flat baseline)."""
    rr = min(r, w / 2, h)
    return (
        f"M{_n(x)},{_n(y + h)}V{_n(y + rr)}Q{_n(x)},{_n(y)} {_n(x + rr)},{_n(y)}H{_n(x + w - rr)}"
        f"Q{_n(x + w)},{_n(y)} {_n(x + w)},{_n(y + rr)}V{_n(y + h)}Z"
    )


def daily_bars(
    points: Sequence[dict[str, Any]],
    format_value: Callable[[float], str] = format_usd,
    format_axis: Callable[[float], str] = format_usd_axis,
    aria_label: str = "Daily bar chart",
) -> dict[str, Any]:
    """`points`: [{"day", "label", "value", "title"}] -> drawable chart dict."""
    plot_w = W - AXIS
    plot_h = H - TOP - BOTTOM
    max_value = max([0.0, *(p["value"] for p in points)])
    ticks = nice_ticks(max_value, 3)
    top = ticks[-1] or 1

    def y(v: float) -> float:
        return TOP + plot_h - (v / top) * plot_h

    slot = plot_w / max(1, len(points))
    bar = max(2, min(22, slot * 0.56))
    import math

    label_every = max(1, math.ceil(len(points) / 7))
    avg = sum(p["value"] for p in points) / len(points) if points else 0
    avg_label = f"avg {format_value(avg)}"
    pill_w = max(96, len(avg_label) * 7 + 20)

    out_ticks = [
        {
            "y": y(t),
            "ty": y(t) + 4,
            "stroke": "var(--separator-strong)" if t == 0 else "var(--separator)",
            "op": 1 if t == 0 else 0.6,
            "label": format_axis(t),
        }
        for t in ticks
    ]
    bars = []
    for i, p in enumerate(points):
        h = max(2, (p["value"] / top) * plot_h) if p["value"] > 0 else 0
        x = i * slot + (slot - bar) / 2
        show_label = i % label_every == 0
        bars.append(
            {
                "key": p["day"],
                "hx": i * slot,
                "hw": slot,
                "title": p["title"],
                "d": bar_path(x, TOP + plot_h - h, bar, h, 5) if h > 0 else "",
                "i": str(i),
                "label": p["label"] if show_label else "",
                "lx": x if i == 0 else i * slot + slot / 2,
                "anchor": "start" if i == 0 else "middle",
            }
        )
    return {
        "view_box": f"0 0 {W} {H}",
        "aria": aria_label,
        "plot_w": plot_w,
        "plot_h": plot_h,
        "top": TOP,
        "label_y": H - 6,
        "axis_x": plot_w + 12,
        "ticks": out_ticks,
        "bars": bars,
        "has_avg": avg > 0,
        "avg_y": y(avg),
        "pill_x": plot_w - pill_w - 4,
        "pill_y": y(avg) - 11,
        "pill_w": pill_w,
        "pill_tx": plot_w - 4 - pill_w / 2,
        "pill_ty": y(avg) + 4,
        "avg_label": avg_label,
    }


EMPTY_CHART: dict[str, Any] = daily_bars([])
