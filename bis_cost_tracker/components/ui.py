"""Presentational building blocks (port of src/components/ui.tsx).

Same class names as the Next app; data arrives as state Vars built by bis_cost_tracker/views.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import reflex as rx
from reflex.components.react_router.dom import ReactRouterLink

from bis_core.attribution import CONFIDENCE_LEVELS
from bis_core.report.format import CONFIDENCE_HELP, CONFIDENCE_LABEL

from bis_cost_tracker.components.rich import D, Dict, L, box, chevron, rich_cell, seg, segs, svg_attrs
from bis_cost_tracker.views.kit import CONF_BAR

LINK = "text-link hover:underline underline-offset-2 decoration-1"
MONO = "font-mono text-[12px]"


def rlink(*children: Any, href: Any, class_name: Any = "", **props: Any) -> rx.Component:
    """In-app link with client-side navigation (react-router)."""
    return ReactRouterLink.create(*children, to=href, class_name=class_name, **props)


def code(text: str) -> rx.Component:
    return rx.el.code(text, class_name="rounded-[5px] bg-fill px-1.5 py-px font-mono text-[0.86em] text-label")


def more_link(href: Any, label: str = "See all") -> rx.Component:
    return rlink(
        label,
        rx.el.svg(
            rx.el.svg.path(
                d="M2.5 6h7M6.5 3l3 3-3 3",
                custom_attrs=svg_attrs(fill="none", stroke="currentColor", stroke_width="1.6", stroke_linecap="round", stroke_linejoin="round"),
            ),
            view_box="0 0 12 12",
            class_name="size-3",
            aria_hidden="true",
        ),
        href=href,
        class_name="press inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-[13px] font-medium text-link hover:bg-accent/10",
    )


# --- page structure ----------------------------------------------------------------------------


def breadcrumbs(crumbs: Any) -> rx.Component:
    """`crumbs`: Var list of {"label", "href"}; the last one is the current page."""
    items = L(crumbs)
    n = items.length()
    return rx.el.nav(
        rx.el.ol(
            rx.foreach(
                items,
                lambda c, i: rx.el.li(
                    rx.cond(
                        (c["href"] != "") & (i < n - 1),
                        rlink(
                            c["label"],
                            href=c["href"].to(str),
                            class_name="press -mx-1.5 truncate rounded-full px-1.5 py-0.5 font-medium text-link hover:bg-accent/10",
                        ),
                        rx.el.span(c["label"], class_name="truncate text-label-2"),
                    ),
                    rx.cond(i < n - 1, chevron("size-2.5 text-label-3")),
                    class_name="inline-flex min-w-0 items-center gap-1",
                ),
            ),
            class_name="flex flex-wrap items-center gap-x-1 gap-y-1 text-[13px]",
        ),
        aria_label="Breadcrumb",
        class_name="mb-3",
    )


def page_header(title: Any, subtitle: Any = None, crumbs: Any = None, action: Any = None) -> rx.Component:
    return rx.el.header(
        breadcrumbs(crumbs) if crumbs is not None else rx.fragment(),
        rx.el.div(
            rx.el.div(
                rx.el.h1(
                    title,
                    class_name="font-display text-[32px] leading-[1.1] font-bold tracking-[-0.025em] text-label sm:text-[36px]",
                ),
                rx.el.div(subtitle, class_name="mt-2 text-[15px] text-label-2") if subtitle is not None else rx.fragment(),
                class_name="min-w-0",
            ),
            rx.el.div(action, class_name="shrink-0") if action is not None else rx.fragment(),
            class_name="flex flex-wrap items-end justify-between gap-x-6 gap-y-3",
        ),
    )


def section(title: Any, *children: Any, subtitle: Any = None, action: Any = None) -> rx.Component:
    return rx.el.section(
        rx.el.div(
            rx.el.div(
                rx.el.h2(title, class_name="font-display text-[20px] font-semibold tracking-[-0.018em]"),
                rx.el.p(subtitle, class_name="mt-1 text-[13px] text-label-2") if subtitle is not None else rx.fragment(),
                class_name="min-w-0",
            ),
            rx.el.div(action, class_name="shrink-0 text-[13px]") if action is not None else rx.fragment(),
            class_name="mb-4 flex items-end justify-between gap-4 px-1",
        ),
        *children,
    )


def card(
    *children: Any,
    title: Any = None,
    subtitle: Any = None,
    action: Any = None,
    class_name: str = "",
    flush: bool = False,
    hero: bool = False,
) -> rx.Component:
    head = (
        rx.el.div(
            rx.el.div(
                rx.el.h2(title, class_name="text-[15px] font-semibold tracking-[-0.012em]") if title is not None else rx.fragment(),
                rx.el.p(subtitle, class_name="mt-1 text-[13px] text-label-2") if subtitle is not None else rx.fragment(),
                class_name="min-w-0",
            ),
            rx.el.div(action, class_name="-my-1 shrink-0 text-[13px]") if action is not None else rx.fragment(),
            class_name=f"flex items-start justify-between gap-4 {'px-6 pt-6 pb-4' if flush else 'mb-5'}",
        )
        if title is not None or action is not None
        else rx.fragment()
    )
    surface = "glass-hero" if hero else "bg-surface shadow-card"
    return rx.el.section(
        head,
        *children,
        class_name=f"overflow-hidden rounded-[24px] {surface} {'' if flush else 'p-6 sm:p-7'} {class_name}",
    )


def kpi(label: Any, value: Any, hint: Any = None, size: str = "md") -> rx.Component:
    return rx.el.div(
        rx.el.div(label, class_name="text-[13px] font-medium text-label-2"),
        rx.el.div(
            value,
            class_name="font-display font-semibold tabular-nums text-label "
            + (
                "mt-2 text-[48px] leading-none tracking-[-0.035em] sm:text-[56px]"
                if size == "xl"
                else "mt-2 text-[28px] leading-tight tracking-[-0.022em]"
            ),
        ),
        rx.el.div(hint, class_name=("mt-3 text-[14px]" if size == "xl" else "mt-1.5 text-[12.5px]") + " text-label-3")
        if hint is not None
        else rx.fragment(),
        class_name="min-w-0",
    )


def kpi_tiles(items: Any, cols4: Any = True) -> rx.Component:
    """`items`: Var list of {"label", "value" (segs), "hint"}."""
    return rx.el.div(
        rx.foreach(
            L(items),
            lambda it: rx.el.div(
                kpi(it["label"], segs(it["value"]), rx.cond(it["hint"] != "", it["hint"], None)),
                class_name="rounded-[22px] bg-surface p-6 shadow-card",
            ),
        ),
        class_name=rx.cond(cols4, "stagger grid gap-4 sm:grid-cols-2 xl:grid-cols-4", "stagger grid gap-4 sm:grid-cols-2 xl:grid-cols-3"),
    )


def disclosure(title: Any, *children: Any, hint: Any = None, surface: bool = False, open_: Any = None, class_name: str = "", **props: Any) -> rx.Component:
    extra = {"open": open_} if open_ is not None else {}
    return rx.el.details(
        rx.el.summary(
            chevron("size-3"),
            rx.el.span(title, class_name="text-label"),
            rx.el.span(hint, class_name="min-w-0 truncate text-[13px] font-normal text-label-3") if hint is not None else rx.fragment(),
            class_name="press flex cursor-pointer select-none items-center gap-2 rounded-[14px] text-[13.5px] font-medium text-label-2 hover:text-label "
            + ("px-6 py-5" if surface else "-mx-2 px-2 py-1.5"),
        ),
        rx.el.div(*children, class_name="px-6 pb-6" if surface else "pt-4 pb-1"),
        class_name=f"disclosure group {'rounded-[22px] bg-surface shadow-card' if surface else ''} {class_name}",
        **extra,
        **props,
    )


def notice(tone: str, title: Any, *children: Any) -> rx.Component:
    s = {
        "warn": ("bg-warn/10", "text-warn", "!"),
        "info": ("bg-accent/8", "text-accent", "i"),
        "ok": ("bg-ok/10", "text-ok", "✓"),
        "error": ("bg-bad/10", "text-bad", "!"),
    }[tone]
    return rx.el.div(
        rx.el.span(
            rx.el.span(s[2], class_name="text-surface"),
            class_name=f"mt-px grid size-[18px] shrink-0 place-items-center rounded-full bg-current text-[11px] leading-none font-bold {s[1]}",
            aria_hidden="true",
        ),
        rx.el.div(
            rx.el.div(title, class_name="font-semibold text-label"),
            rx.el.div(*children, class_name="mt-0.5 text-label-2") if children else rx.fragment(),
            class_name="min-w-0 text-[13px]",
        ),
        class_name=f"flex gap-3 rounded-[16px] px-5 py-4 {s[0]}",
        role="alert" if tone == "error" else "status",
    )


def avisos(items: Any) -> rx.Component:
    """All data-quality warnings behind one quiet row: "Warnings (n)" that expands in place.
    `items`: Var list of {"key", "tone", "title", "body" (segs)}."""
    lst = L(items)
    warn = lst.map(lambda i: i["tone"] == "warn").contains(True)
    return rx.cond(
        lst.length() > 0,
        rx.el.details(
            rx.el.summary(
                rx.el.span(class_name=rx.cond(warn, "size-2 shrink-0 rounded-full bg-warn", "size-2 shrink-0 rounded-full bg-accent"), aria_hidden="true"),
                rx.el.span(
                    "Warnings ",
                    rx.el.span("(", lst.length(), ")", class_name="tabular-nums text-label-3"),
                    class_name="font-medium text-label",
                ),
                rx.el.span(
                    rx.foreach(lst, lambda i, n: rx.el.span(rx.cond(n > 0, " · ", ""), i["title"])),
                    class_name="hidden min-w-0 flex-1 truncate text-label-3 sm:block",
                ),
                rx.el.span(
                    rx.el.span("Show", class_name="when-closed"),
                    rx.el.span("Hide", class_name="when-open"),
                    chevron("size-2.5"),
                    class_name="ml-auto inline-flex items-center gap-1 text-[12.5px] font-medium text-link",
                ),
                class_name="press flex cursor-pointer select-none items-center gap-3 rounded-[18px] px-5 py-3.5 text-[13px] hover:bg-hover",
            ),
            rx.el.ul(
                rx.foreach(
                    lst,
                    lambda i: rx.el.li(
                        rx.el.span(
                            class_name=rx.cond(i["tone"] == "warn", "mt-[7px] size-1.5 shrink-0 rounded-full bg-warn", "mt-[7px] size-1.5 shrink-0 rounded-full bg-accent"),
                            aria_hidden="true",
                        ),
                        rx.el.div(
                            rx.el.div(i["title"], class_name="font-medium text-label"),
                            rx.el.div(segs(i["body"]), class_name="mt-0.5 text-label-2"),
                            class_name="min-w-0 max-w-[88ch]",
                        ),
                        class_name="flex gap-3 text-[13px]",
                    ),
                ),
                class_name="space-y-4 px-5 pt-1 pb-5",
            ),
            class_name="disclosure group rounded-[18px] bg-surface/70 shadow-card",
        ),
    )


def empty_state(db_empty: Any) -> rx.Component:
    return rx.el.div(
        rx.el.div(
            rx.el.svg(
                rx.cond(
                    db_empty,
                    rx.fragment(
                        rx.el.svg.ellipse(cx="12", cy="6", rx="7", ry="2.6"),
                        rx.el.svg.path(d="M5 6v6c0 1.4 3.1 2.6 7 2.6s7-1.2 7-2.6V6M5 12v6c0 1.4 3.1 2.6 7 2.6s7-1.2 7-2.6v-6"),
                    ),
                    rx.fragment(
                        rx.el.svg.rect(x="4", y="5", width="16", height="15", rx="3"),
                        rx.el.svg.path(d="M4 10h16M9 3v4M15 3v4"),
                    ),
                ),
                view_box="0 0 24 24",
                class_name="size-7",
                custom_attrs=svg_attrs(fill="none", stroke="currentColor", stroke_width="1.6", stroke_linecap="round"),
            ),
            class_name="grid size-16 place-items-center rounded-full bg-accent/10 text-accent",
            aria_hidden="true",
        ),
        rx.cond(
            db_empty,
            rx.fragment(
                rx.el.h2("No turns yet", class_name="mt-6 text-[20px] font-semibold tracking-[-0.016em]"),
                rx.el.p(
                    "Load sample data with ",
                    code("npm run seed"),
                    " or import your real traces with ",
                    code("npm run sync"),
                    " (and ",
                    code("npm run sync:github"),
                    " for issues and PRs). The VS Code guide is in ",
                    code("docs/vscode-setup.md"),
                    ".",
                    class_name="mt-2 max-w-lg text-[14px] text-label-2",
                ),
            ),
            rx.fragment(
                rx.el.h2("Nothing here for this period", class_name="mt-6 text-[20px] font-semibold tracking-[-0.016em]"),
                rx.el.p(
                    "Try a longer period at the top right, or run ",
                    code("npm run sync"),
                    " to fetch recent traces.",
                    class_name="mt-2 max-w-lg text-[14px] text-label-2",
                ),
            ),
        ),
        class_name="flex flex-col items-center rounded-[24px] bg-surface px-8 py-20 text-center shadow-card",
    )


def empty_note(*children: Any) -> rx.Component:
    return rx.el.div(*children, class_name="rounded-[24px] bg-surface px-8 py-14 text-center text-[14px] text-label-2 shadow-card")


def loading() -> rx.Component:
    block = "skeleton rounded-[24px]"
    return rx.el.div(
        rx.el.div(rx.el.div(class_name="skeleton h-9 w-52 rounded-xl"), rx.el.div(class_name="skeleton h-4 w-72 rounded-md"), class_name="space-y-3"),
        rx.el.div(class_name=f"h-80 {block}"),
        rx.el.div(*[rx.el.div(class_name=f"h-32 {block}") for _ in range(4)], class_name="grid gap-4 sm:grid-cols-2 xl:grid-cols-4"),
        rx.el.span("Loading…", class_name="sr-only"),
        aria_busy="true",
        class_name="flex flex-col gap-8",
    )


# --- confidence --------------------------------------------------------------------------------


def confidence_legend(pcts: Any) -> rx.Component:
    """`pcts`: Var dict confidence -> formatted share."""
    p = D(pcts)
    return rx.el.div(
        *[
            rx.el.span(
                rx.el.span(class_name=f"size-2 rounded-full {CONF_BAR[c]}", aria_hidden="true"),
                rx.el.span(CONFIDENCE_LABEL[c], class_name="text-label"),
                rx.el.span(p[c], class_name="tabular-nums text-label-3"),
                class_name="inline-flex items-center gap-1.5",
                title=CONFIDENCE_HELP[c],
            )
            for c in CONFIDENCE_LEVELS
        ],
        class_name="flex flex-wrap gap-x-5 gap-y-2 text-[12.5px] text-label-2",
    )


def confidence_help(*children: Any, title: str | None = None) -> rx.Component:
    title = title or ("What do these figures mean?" if children else "What does confidence mean?")
    return disclosure(
        title,
        rx.el.div(*children, class_name="mb-5 max-w-[90ch] text-[13px] text-label-2") if children else rx.fragment(),
        rx.el.dl(
            *[
                rx.el.div(
                    rx.el.span(class_name=f"mt-1.5 size-2 shrink-0 rounded-full {CONF_BAR[c]}", aria_hidden="true"),
                    rx.el.div(
                        rx.el.dt(
                            CONFIDENCE_LABEL[c],
                            " ",
                            rx.el.span("phase 2", class_name="inline-flex items-center whitespace-nowrap rounded-full px-2 py-0.5 align-middle text-[11.5px] leading-[1.35] font-medium bg-fill text-label-2")
                            if c == "inferred"
                            else rx.fragment(),
                            class_name="text-[13px] font-semibold text-label",
                        ),
                        rx.el.dd(CONFIDENCE_HELP[c], class_name="mt-0.5 text-[12.5px] text-label-2"),
                        class_name="min-w-0",
                    ),
                    class_name="flex gap-3",
                )
                for c in CONFIDENCE_LEVELS
            ],
            class_name="grid grid-cols-[repeat(auto-fill,minmax(16rem,1fr))] gap-x-8 gap-y-4",
        ),
        rx.el.p(
            "Cascade: manual › branch with issue number › branch = PR head › commit in PR › (inferred, phase 2) › project only.",
            class_name="mt-5 text-[12.5px] text-label-2",
        ),
    )


# --- tables -----------------------------------------------------------------------------------

Col = tuple[str, bool, str]  # (label, right-aligned, extra class)


def th(label: str, right: bool = False, class_name: str = "") -> rx.Component:
    """`label` "sr:Details" renders a screen-reader-only header."""
    content = rx.el.span(label[3:], class_name="sr-only") if label.startswith("sr:") else label
    return rx.el.th(
        content,
        scope="col",
        class_name="sticky top-0 z-10 bg-surface/85 backdrop-blur-xl backdrop-saturate-150 whitespace-nowrap border-b border-separator/70 px-3 pt-4 pb-3 text-[12px] font-medium text-label-3 "
        + ("text-right" if right else "text-left")
        + f" {class_name}",
    )


def _grid(g: rx.Var, i: rx.Var) -> rx.Component:
    """One <DetailGrid> (with an optional heading line above it)."""
    return rx.el.div(
        rx.cond(
            L(g["head"]).length() > 0,
            rx.el.div(segs(g["head"]), class_name="mb-2 flex items-baseline gap-2 px-1 text-[12.5px]"),
        ),
        rx.el.dl(
            rx.foreach(
                L(g["items"]),
                lambda it: rx.el.div(
                    rx.el.dt(it["l"], class_name="text-[12px] text-label-3"),
                    rx.el.dd(segs(it["v"]), class_name="mt-1 text-[13.5px] tabular-nums text-label"),
                    class_name="min-w-0",
                ),
            ),
            class_name="grid grid-cols-2 gap-x-8 gap-y-4 rounded-[16px] bg-surface/80 px-5 py-4 sm:grid-cols-3 lg:grid-cols-5",
        ),
        class_name=rx.cond(i > 0, "mt-3", ""),
    )


@rx.memo
def detail_grids(grids: rx.Var[list[Dict]]) -> rx.Component:
    return rx.el.div(rx.foreach(grids, _grid))


def _row(r: rx.Var, ncols: int, detail_class: str) -> rx.Component:
    return rx.fragment(
        rx.el.tr(rx.foreach(L(r["cells"]), lambda c: rich_cell(b=c)), class_name=r["c"].to(str), id=r["id"].to(str)),
        rx.cond(
            r["has_d"],
            rx.el.tr(rx.el.td(box(r["d"]), col_span=ncols, class_name=detail_class), class_name="row-detail"),
        ),
        rx.cond(
            r["has_g"],
            rx.el.tr(rx.el.td(detail_grids(grids=L(r["g"])), col_span=ncols, class_name=detail_class), class_name="row-detail"),
        ),
    )


def data_table(
    cols: Sequence[Col],
    rows: Any,
    standalone: bool = True,
    max_height: str = "max-h-[min(76vh,56rem)]",
    class_name: str = "",
    detail_class: str = "bg-fill/40 pt-0 pb-5",
    tail: Any = None,
) -> rx.Component:
    """Table in its own scroll area (sticky header); rows are view-model rows (kit.row)."""
    return rx.el.div(
        rx.el.table(
            rx.el.thead(rx.el.tr(*[th(label, right, c) for label, right, c in cols])),
            rx.el.tbody(rx.foreach(L(rows), lambda r: _row(r, len(cols), detail_class)), tail if tail is not None else rx.fragment()),
            class_name="dtable",
        ),
        class_name=f"scroll-area overflow-auto {max_height} {'rounded-[24px] bg-surface shadow-card' if standalone else ''} {class_name}",
    )


# --- lists and charts ---------------------------------------------------------------------------


def _bar_body(i: rx.Var, label: rx.Component) -> rx.Component:
    return rx.fragment(
        rx.el.div(
            rx.el.span(label, rx.cond(i["mode"] == "ext", seg(i["ext"])), class_name="flex min-w-0 items-baseline gap-1"),
            rx.el.span(
                segs(i["display"]),
                rx.cond(i["secondary"] != "", rx.el.span(i["secondary"], class_name="ml-2 text-[12.5px] text-label-3")),
                class_name="shrink-0 text-right tabular-nums",
            ),
            class_name="flex items-baseline justify-between gap-4 text-[13.5px]",
        ),
        rx.el.div(
            rx.el.div(class_name="grow-x h-full rounded-full bg-accent/85", style={"width": i["w"]}),
            class_name="mt-2 h-1 overflow-hidden rounded-full bg-fill",
            aria_hidden="true",
        ),
    )


def _bar_item(i: rx.Var) -> rx.Component:
    plain_label = rx.el.span(segs(i["label"]), class_name="min-w-0 truncate font-medium text-label")
    return rx.el.li(
        rx.match(
            i["mode"],
            (
                "ext",
                rx.el.div(
                    _bar_body(
                        i,
                        rlink(
                            segs(i["label"]),
                            href=i["href"].to(str),
                            class_name="stretched stretched-round min-w-0 truncate font-medium text-label",
                        ),
                    ),
                    class_name="press relative rounded-[14px] px-3 py-2.5 hover:bg-hover",
                ),
            ),
            ("link", rlink(_bar_body(i, plain_label), href=i["href"].to(str), class_name="press block rounded-[14px] px-3 py-2.5 hover:bg-hover")),
            rx.el.div(_bar_body(i, plain_label), class_name="px-3 py-2.5"),
        )
    )


def bar_list(items: Any, empty: str = "No data") -> rx.Component:
    lst = L(items)
    return rx.cond(
        lst.length() == 0,
        rx.el.p(empty, class_name="py-6 text-center text-[13px] text-label-3"),
        rx.el.ul(rx.foreach(lst, _bar_item), class_name="-mx-3 space-y-1"),
    )


def daily_chart(chart: Any) -> rx.Component:
    """Inline SVG bar chart drawn from views.chart.daily_bars()."""
    c = D(chart)
    text_style = {"fontSize": "12px"}
    return rx.el.svg(
        rx.foreach(
            L(c["ticks"]),
            lambda t: rx.el.svg.g(
                rx.el.svg.line(
                    x1="0",
                    x2=c["plot_w"],
                    y1=t["y"],
                    y2=t["y"],
                    custom_attrs=svg_attrs(stroke=t["stroke"], stroke_opacity=t["op"], stroke_width="1", shape_rendering="crispEdges"),
                ),
                rx.el.svg.text(t["label"], x=c["axis_x"], y=t["ty"], style=text_style, custom_attrs={"fill": "var(--label-3)"}, aria_hidden="true"),
            ),
        ),
        rx.foreach(
            L(c["bars"]),
            lambda b: rx.el.svg.g(
                rx.el.svg.rect(
                    rx.el.svg.title(b["title"]),
                    class_name="hit",
                    x=b["hx"],
                    y=c["top"],
                    width=b["hw"],
                    height=c["plot_h"],
                    rx="6",
                    custom_attrs={"fill": "transparent"},
                ),
                rx.cond(
                    b["d"] != "",
                    rx.el.svg.path(
                        d=b["d"],
                        class_name="mark pointer-events-none",
                        style={"--i": b["i"]},
                        custom_attrs={"fill": "var(--accent)"},
                    ),
                ),
                rx.cond(
                    b["label"] != "",
                    rx.el.svg.text(
                        b["label"],
                        x=b["lx"],
                        y=c["label_y"],
                        style=text_style,
                        custom_attrs=svg_attrs(text_anchor=b["anchor"], fill="var(--label-3)"),
                        aria_hidden="true",
                    ),
                ),
                class_name="slot",
            ),
        ),
        rx.cond(
            c["has_avg"],
            rx.el.svg.g(
                rx.el.svg.line(
                    x1="0",
                    x2=c["plot_w"],
                    y1=c["avg_y"],
                    y2=c["avg_y"],
                    custom_attrs=svg_attrs(stroke="var(--label-2)", stroke_opacity="0.7", stroke_width="1.25", stroke_dasharray="4 5"),
                ),
                rx.el.svg.rect(
                    x=c["pill_x"],
                    y=c["pill_y"],
                    width=c["pill_w"],
                    height="22",
                    rx="11",
                    custom_attrs={"fill": "var(--surface)", "stroke": "var(--separator)"},
                ),
                rx.el.svg.text(
                    c["avg_label"],
                    x=c["pill_tx"],
                    y=c["pill_ty"],
                    style={"fontSize": "12px", "fontWeight": 500},
                    custom_attrs=svg_attrs(text_anchor="middle", fill="var(--label-2)"),
                ),
                class_name="avg pointer-events-none",
            ),
        ),
        view_box=c["view_box"].to(str),
        class_name="chart h-auto w-full select-none",
        role="img",
        aria_label=c["aria"].to(str),
    )


def not_found() -> rx.Component:
    """Port of src/app/not-found.tsx."""
    return rx.el.div(
        rx.el.div(
            "?",
            class_name="grid size-16 place-items-center rounded-full bg-accent/10 font-display text-[22px] font-semibold text-accent",
            aria_hidden="true",
        ),
        rx.el.h1("Not found", class_name="mt-6 text-[22px] font-semibold tracking-[-0.016em]"),
        rx.el.p(
            "This team, person or session doesn’t exist (or has no data anymore). Go back to the list and pick another one.",
            class_name="mt-2 max-w-lg text-[14px] text-label-2",
        ),
        rx.el.div(
            rlink("Teams", href="/equipos", class_name="press rounded-[10px] bg-accent px-5 py-2 text-white shadow-control hover:bg-accent-hover"),
            rlink("People", href="/personas", class_name="press rounded-[10px] bg-fill px-5 py-2 text-label hover:bg-fill-2"),
            class_name="mt-6 flex flex-wrap justify-center gap-3 text-[13.5px] font-medium",
        ),
        class_name="flex flex-col items-center rounded-[24px] bg-surface px-8 py-20 text-center shadow-card",
    )


def stat(label: Any, value: Any, hint: Any, mono: Any = False, title: Any = "") -> rx.Component:
    """KPI under the hero (team / person pages)."""
    return rx.el.div(
        rx.el.dt(label, class_name="text-[13px] font-medium text-label-2"),
        rx.el.dd(
            value,
            class_name=rx.cond(
                mono,
                "mt-1 truncate leading-tight font-semibold tabular-nums text-label pt-1 font-mono text-[15px]",
                "mt-1 truncate leading-tight font-semibold tabular-nums text-label font-display text-[24px] tracking-[-0.02em]",
            ),
            title=rx.cond(mono, value, ""),
        ),
        rx.cond(hint != "", rx.el.dd(hint, class_name="mt-1 text-[12.5px] text-label-3")),
        class_name="min-w-0",
        title=title,
    )
