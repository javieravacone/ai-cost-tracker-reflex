"""View-model kit: plain, JSON-serializable building blocks for rich table cells and inline text.

Pages compute their data in Python (with bis_core) and hand the UI lists of dicts. Most of the
layout is real Reflex components; the heterogeneous inline content of cells (links, chips,
"Real" markers, meters, confidence bars...) is described with two shapes rendered by
`components/rich.py`:

- Segment ("seg"): {"k": kind, "t": text, "c": class, "h": href, "ti": title, "s": [segments]}
  kinds: "t" text span, "a" in-app link (children "s" = atoms), "x" external link with the
  ↗ marker, "l" external link without marker, "chev" chevron glyph, "meter", "mix",
  "g" inline group (children "s" = leaf segments).
- Box: {"c": class, "ti": title, "s": [segments], "b": [boxes]} rendered as a <div>; segments
  first, then child boxes. Table cells are boxes rendered as <td>.

Class names here are Tailwind utilities (rxconfig scans this package) and mirror
src/components/ui.tsx of the Next app one to one.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from bis_core.attribution import CONFIDENCE_LEVELS
from bis_core.report.format import (
    CONFIDENCE_HELP,
    CONFIDENCE_LABEL,
    format_credits,
    format_int,
    format_pct,
    format_usd,
    ratio,
)

Seg = dict[str, Any]
Box = dict[str, Any]

LINK = "text-link hover:underline underline-offset-2 decoration-1"
MONO = "font-mono text-[12px]"


# --- primitives ------------------------------------------------------------------------------


def seg(k: str, t: str = "", c: str = "", h: str = "", ti: str = "", s: Sequence[Seg] | None = None, **extra: Any) -> Seg:
    # Empty attributes are left out to keep the state small (React drops undefined props);
    # containers always carry "s" because the renderer maps over it.
    out: Seg = {"k": k}
    for key, value in (("t", t), ("c", c), ("h", h), ("ti", ti)):
        if value:
            out[key] = value
    if k in ("a", "g") or s:
        out["s"] = list(s or [])
    out.update(extra)
    return out


def txt(text: Any, c: str = "", ti: str = "") -> Seg:
    return seg("t", str(text), c, ti=ti)


def link(text: str, href: str, c: str = "", ti: str = "", s: Sequence[Seg] | None = None) -> Seg:
    """In-app link (client-side navigation)."""
    return seg("a", text, c, href, ti, s)


def chev(c: str = "size-3") -> Seg:
    return seg("chev", c=c)


def group(children: Iterable[Seg], c: str = "", ti: str = "") -> Seg:
    return seg("g", c=c, ti=ti, s=[x for x in children if x])


def box(c: str = "", s: Iterable[Seg] | None = None, b: Iterable[Box] | None = None, ti: str = "") -> Box:
    out: Box = {"s": [x for x in (s or []) if x], "b": [x for x in (b or []) if x]}
    if c:
        out["c"] = c
    if ti:
        out["ti"] = ti
    return out


def ext(text: str | None, href: str | None, ti: str = "", c: str = "") -> Seg | None:
    """ExternalLink: new tab + quiet ↗; with no href the text renders as plain text (fictional
    seed repos); with no text it renders only the ↗ marker (or nothing without href)."""
    icon_only = text is None
    if not href:
        return None if icon_only else txt(text, c, ti)
    cls = f"{LINK} relative z-[1] whitespace-nowrap {'px-0.5' if icon_only else ''} {c}".strip()
    return seg("x", "" if icon_only else text, cls, href, ti, ac="" if icon_only else "ml-0.5")


def plain_ext(text: str, href: str, c: str = LINK) -> Seg:
    """<a target=_blank> without the ↗ marker."""
    return seg("l", text, c, href)


def sp(text: str = " ") -> Seg:
    return txt(text)


# --- atoms of ui.tsx -------------------------------------------------------------------------

CHIP = {
    "neutral": "bg-fill text-label-2",
    "ok": "bg-ok/12 text-ok-text",
    "warn": "bg-warn/14 text-warn-text",
    "bad": "bg-bad/12 text-bad-text",
    "info": "bg-accent/12 text-info-text",
}
CHIP_BASE = "inline-flex items-center whitespace-nowrap rounded-full px-2 py-0.5 align-middle text-[11.5px] leading-[1.35] font-medium"


def chip(text: str, tone: str = "neutral", ti: str = "") -> Seg:
    return txt(text, f"{CHIP_BASE} {CHIP[tone]}", ti)


def real_chip() -> Seg:
    return group(
        [txt("", "size-1.5 rounded-full bg-ok"), txt("Real")],
        "inline-flex items-center gap-1 whitespace-nowrap align-middle text-[11.5px] font-medium text-ok-text",
        "Real turns imported from LangSmith (not sample data)",
    )


def muted(text: str) -> Seg:
    return txt(text, "text-label-3")


CONF_BAR = {
    "manual": "bg-conf-manual",
    "exact-branch": "bg-conf-branch",
    "exact-pr": "bg-conf-pr",
    "exact-commit": "bg-conf-commit",
    "inferred": "bg-conf-inferred",
    "project": "bg-conf-project",
}


def confidence_badge(conf: str) -> Seg:
    return group(
        [txt("", f"size-1.5 rounded-full {CONF_BAR[conf]}"), txt(CONFIDENCE_LABEL[conf])],
        "inline-flex items-center gap-1.5 whitespace-nowrap rounded-full bg-fill px-2 py-0.5 text-[11.5px] font-medium text-label",
        CONFIDENCE_HELP[conf],
    )


def confidence_mix(counts: Mapping[str, int], c: str = "w-20", size: str = "sm") -> Seg:
    total = sum(counts.get(x, 0) for x in CONFIDENCE_LEVELS)
    title = "\n".join(
        f"{CONFIDENCE_LABEL[x]}: {format_int(counts[x])} ({format_pct(ratio(counts[x], total))})"
        for x in CONFIDENCE_LEVELS
        if counts.get(x, 0) > 0
    )
    h = "h-2.5 gap-[3px]" if size == "lg" else "h-1.5 gap-[2px]"
    parts = [{"c": f"{CONF_BAR[x]} first:rounded-l-full last:rounded-r-full", "g": counts[x]} for x in CONFIDENCE_LEVELS if counts.get(x, 0) > 0]
    cls = f"grow-x flex overflow-hidden rounded-full {'bg-fill' if total == 0 else ''} {h} {c}"
    return seg("mix", c=cls, ti=title or "No turns", p=parts)


METER_FILL = {"accent": "bg-accent", "ok": "bg-ok", "warn": "bg-warn", "bad": "bg-bad"}


def meter(value: float, tone: str = "accent", c: str = "") -> Seg:
    v = max(0.0, value) if value == value and value not in (float("inf"), float("-inf")) else 0.0
    width = f"{min(100.0, v * 100):g}%"
    return seg(
        "meter",
        format_pct(v),
        f"inline-flex items-center justify-end gap-2.5 whitespace-nowrap {c}",
        w=width,
        f=f"grow-x block h-full rounded-full {METER_FILL[tone]}",
    )


def state_badge(state: str) -> Seg:
    label, dot = {
        "open": ("Open", "bg-ok"),
        "closed": ("Closed", "bg-conf-project"),
        "merged": ("Merged", "bg-conf-manual"),
        "unsynced": ("Not synced", "bg-warn"),
    }[state]
    return group(
        [txt("", f"size-1.5 rounded-full {dot}"), txt(label)],
        "inline-flex items-center gap-1.5 whitespace-nowrap text-[12.5px] text-label-3",
    )


AVATAR_SIZE = {"sm": "size-8 text-[12px]", "md": "size-10 text-[13.5px]", "lg": "size-14 text-[19px]"}


def avatar(initials: str, size: str = "sm", muted_: bool = False) -> Seg:
    tone = "bg-fill text-label-3" if muted_ else "bg-accent/10 text-accent"
    return txt(initials, f"grid shrink-0 place-items-center rounded-full font-semibold tracking-[0.02em] {AVATAR_SIZE[size]} {tone}")


def avatar_stack(people: Sequence[Mapping[str, Any]], max_: int = 4) -> Seg:
    shown = list(people[:max_])
    rest = len(people) - len(shown)
    items: list[Seg] = []
    for i, p in enumerate(shown):
        tone = "bg-fill-2 text-label-3" if p["muted"] else "bg-[color-mix(in_srgb,var(--accent)_12%,var(--surface))] text-accent"
        items.append(
            txt(
                p["initials"],
                f"grid size-7 place-items-center rounded-full text-[10px] font-semibold tracking-[0.02em] ring-2 ring-surface {tone} {'-ml-1' if i > 0 else ''}",
                p["name"],
            )
        )
    if rest > 0:
        items.append(txt(f"+{rest}", "ml-1.5 text-[11.5px] tabular-nums text-label-3"))
    return group(items, "inline-flex items-center", ", ".join(p["name"] for p in people))


def code(text: str) -> Seg:
    return txt(text, "rounded-[5px] bg-fill px-1.5 py-px font-mono text-[0.86em] text-label")


def sub(segs: Iterable[Seg]) -> Box:
    """Secondary line inside a table cell."""
    return box("mt-0.5 text-[12.5px] font-normal text-label-3", segs)


# --- costs ------------------------------------------------------------------------------------


def api_cost(usd: float, turns: int, unpriced_turns: int = 0) -> Seg:
    if turns > 0 and unpriced_turns >= turns:
        return chip("no price", "warn", "Model has no price in the model_prices table: the API-equivalent cost can’t be computed")
    if unpriced_turns > 0:
        return group(
            [txt("", "size-1.5 rounded-full bg-warn"), txt(format_usd(usd))],
            "inline-flex items-center gap-1.5",
            f"{format_int(unpriced_turns)} of {format_int(turns)} turns use a model with no price and don’t add up here",
        )
    return txt(format_usd(usd))


SIN_DATO_HELP = "Copilot didn’t report credit usage (legacy plan, BYOK or older client): it’s unknown, not 0."


def credit_figures(m: Any) -> dict[str, float]:
    return {
        "turns": m.turns,
        "ai_credits": m.ai_credits,
        "ai_credits_usd": m.ai_credits_usd,
        "credit_turns": m.credit_turns,
        "credit_partial_turns": m.credit_partial_turns,
    }


def turn_credit_figures(cost: Any, coverage: float | None) -> dict[str, float]:
    known = cost.ai_credits is not None
    return {
        "turns": 1,
        "ai_credits": cost.ai_credits if known else 0,
        "ai_credits_usd": cost.ai_credits_usd if cost.ai_credits_usd is not None else 0,
        "credit_turns": 1 if known else 0,
        "credit_partial_turns": 1 if known and coverage is not None and coverage < 1 else 0,
    }


def _fig(m: Any) -> dict[str, float]:
    return m if isinstance(m, dict) else credit_figures(m)


def _credits_parts(m: Any) -> tuple[bool, str]:
    f = _fig(m)
    missing = f["turns"] - f["credit_turns"]
    lower = missing > 0 or f["credit_partial_turns"] > 0
    if lower:
        bits = []
        if missing > 0:
            bits.append(f"{format_int(missing)} of {format_int(f['turns'])} turns with no data")
        if f["credit_partial_turns"] > 0:
            bits.append(f"{format_int(f['credit_partial_turns'])} with partial data")
        title = "; ".join(bits) + ": the figure is a lower bound."
    else:
        title = f"{format_credits(f['ai_credits'])} AI credits = {format_usd(f['ai_credits_usd'])} gross at list price"
    return lower, title


def _no_data(m: Any) -> bool:
    f = _fig(m)
    return f["turns"] > 0 and f["credit_turns"] == 0


def no_data_chip() -> Seg:
    return chip("no data", "warn", SIN_DATO_HELP)


def _ge() -> Seg:
    return txt("≥", "font-normal text-label-3")


def credits_stack(m: Any) -> Box:
    """`<Credits m={...} />` (stack layout): credits over USD, right-aligned."""
    if _no_data(m):
        return box("", [no_data_chip()])
    f = _fig(m)
    lower, title = _credits_parts(m)
    return box(
        "inline-flex flex-col items-end",
        b=[
            box("inline-flex items-baseline gap-1 font-medium text-label", [_ge() if lower else None, txt(format_credits(f["ai_credits"]))]),
            box("mt-0.5 text-[12.5px] font-normal text-label-3", [txt(format_usd(f["ai_credits_usd"]))]),
        ],
        ti=title,
    )


def credits_compact(m: Any, quiet: bool = False) -> Seg:
    if _no_data(m):
        return no_data_chip()
    f = _fig(m)
    lower, title = _credits_parts(m)
    first = [_ge(), sp()] if lower and not quiet else []
    return group(
        [
            group([*first, txt(format_credits(f["ai_credits"]))], "font-medium text-label"),
            txt(format_usd(f["ai_credits_usd"]), "text-[12.5px] text-label-3"),
        ],
        "inline-flex items-baseline gap-2 whitespace-nowrap",
        title,
    )


def credits_inline(m: Any) -> Seg:
    if _no_data(m):
        return no_data_chip()
    f = _fig(m)
    lower, title = _credits_parts(m)
    return group(
        [
            _ge() if lower else None,
            txt(f"{format_credits(f['ai_credits'])} credits "),
            txt(f"· {format_usd(f['ai_credits_usd'])}", "text-label-3"),
        ],
        "inline-flex items-baseline gap-1 whitespace-nowrap",
        title,
    )


# --- tables -------------------------------------------------------------------------------------


def td(content: Box | Iterable[Seg] | None = None, right: bool = False, top: bool = False, c: str = "", b: Iterable[Box] | None = None, ti: str = "") -> Box:
    """A <td> as a box: `content` is either segments or a box whose children are merged in."""
    cls = f"px-3 py-3.5 {'align-top' if top else 'align-middle'} {'whitespace-nowrap text-right tabular-nums' if right else ''} {c}".strip()
    if isinstance(content, dict):
        return box(cls, [], [content, *(b or [])], ti)
    return box(cls, content or [], b, ti)


def row(cells: Sequence[Box], detail: Box | None = None, c: str = "trow", rid: str = "", open_: bool = False) -> dict[str, Any]:
    """Table row; `detail` is either a box or a `detail_grid()` (rendered by a static component)."""
    grids = detail if detail is not None and "grids" in detail else None
    out: dict[str, Any] = {"cells": list(cells), "c": c, "id": rid, "has_d": False, "has_g": False}
    if grids is not None:
        out["g"] = grids["grids"]
        out["has_g"] = True
    elif detail is not None:
        out["d"] = detail
        out["has_d"] = True
    return out


def toggle_cell(label: str = "Show details", open_: bool = False) -> Box:
    return td([seg("tog", ti=label, o=open_)], right=True)


def detail_grid(items: Sequence[tuple[str, Seg | Iterable[Seg]]], head: Iterable[Seg] | None = None) -> dict[str, Any]:
    """<DetailGrid>: label/value pairs of an expanded row (values are segments)."""
    out = []
    for label, value in items:
        segs = [value] if isinstance(value, dict) else [x for x in value if x]
        out.append({"l": label, "v": segs})
    return {"grids": [{"head": [x for x in (head or []) if x], "items": out}]}


def detail_grids(*grids: dict[str, Any]) -> dict[str, Any]:
    """Several detail grids stacked in one expanded row."""
    return {"grids": [g for x in grids for g in x["grids"]]}


# --- bar list -------------------------------------------------------------------------------


def bar_item(
    key: str,
    label: Iterable[Seg],
    value: float,
    display: Iterable[Seg],
    secondary: str = "",
    href: str = "",
    external: tuple[str | None, str] | None = None,
) -> dict[str, Any]:
    ext_href, ext_title = external if external else (None, "")
    return {
        "key": key,
        "label": [x for x in label if x],
        "value": value,
        "display": [x for x in display if x],
        "secondary": secondary,
        "href": href,
        "ext": ext(None, ext_href, ext_title, "shrink-0 text-[12px]") if (href and ext_href) else None,
    }


def bar_list(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Adds the meter width (share of the max) to each item, like <BarList>."""
    mx = max([0.0, *(i["value"] for i in items)])
    for i in items:
        v = i["value"]
        i["w"] = f"{max(1.5, 100 * v / mx):g}%" if mx > 0 and v > 0 else "0%"
        i["mode"] = "ext" if i["ext"] else ("link" if i["href"] else "plain")
    return items
