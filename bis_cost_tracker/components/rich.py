"""Renderers for the view-model kit (bis_cost_tracker/views/kit.py).

Segments and boxes are plain dicts in state; these components draw them with real elements.
Boxes nest up to five levels; each level is an `rx.memo` component so the generated JS is
shared by every table and page instead of being inlined per usage.
"""

from __future__ import annotations

from typing import Any

import reflex as rx
from reflex.components.react_router.dom import ReactRouterLink

Dict = dict[str, Any]


def L(v: Any) -> rx.Var:
    """Cast a state value to a list of dicts (for rx.foreach)."""
    return v.to(list[Dict])


def D(v: Any) -> rx.Var:
    return v.to(Dict)


def svg_attrs(**kw: Any) -> dict[str, Any]:
    """SVG presentation attributes with React (camelCase) names."""
    names = {
        "stroke_width": "strokeWidth",
        "stroke_linecap": "strokeLinecap",
        "stroke_linejoin": "strokeLinejoin",
        "stroke_opacity": "strokeOpacity",
        "stroke_dasharray": "strokeDasharray",
        "shape_rendering": "shapeRendering",
        "text_anchor": "textAnchor",
    }
    return {names.get(k, k): v for k, v in kw.items()}


def chevron(class_name: Any = "size-3") -> rx.Component:
    return rx.el.svg(
        rx.el.svg.path(
            d="M4.5 2.5 8 6l-3.5 3.5",
            custom_attrs=svg_attrs(fill="none", stroke="currentColor", stroke_width="1.7", stroke_linecap="round", stroke_linejoin="round"),
        ),
        view_box="0 0 12 12",
        class_name=rx.Var.create("chevron shrink-0 ") + class_name if isinstance(class_name, rx.Var) else f"chevron shrink-0 {class_name}",
        aria_hidden="true",
    )


def _span(s: rx.Var) -> rx.Component:
    s = D(s)
    return rx.el.span(s["t"], class_name=s["c"].to(str), title=s["ti"].to(str))


def _atom(s: rx.Var) -> rx.Component:
    s = D(s)
    return rx.cond(s["k"] == "chev", chevron(s["c"].to(str)), _span(s))


def _leaf(s: rx.Var) -> rx.Component:
    s = D(s)
    return rx.match(
        s["k"],
        (
            "a",
            ReactRouterLink.create(
                s["t"],
                rx.foreach(L(s["s"]), _atom),
                to=s["h"].to(str),
                class_name=s["c"].to(str),
                title=s["ti"].to(str),
            ),
        ),
        (
            "x",
            rx.el.a(
                s["t"],
                rx.el.span("↗", aria_hidden="true", class_name=s["ac"].to(str) + " text-[0.85em] font-normal opacity-75"),
                href=s["h"].to(str),
                target="_blank",
                rel="noreferrer",
                class_name=s["c"].to(str),
                title=s["ti"].to(str),
            ),
        ),
        ("l", rx.el.a(s["t"], href=s["h"].to(str), target="_blank", rel="noreferrer noopener", class_name=s["c"].to(str), title=s["ti"].to(str))),
        ("chev", chevron(s["c"].to(str))),
        # Nested group (inside a group): its children are atoms.
        ("g", rx.el.span(rx.foreach(L(s["s"]), _atom), class_name=s["c"].to(str), title=s["ti"].to(str))),
        (
            "meter",
            rx.el.span(
                rx.el.span(s["t"], class_name="tabular-nums"),
                rx.el.span(
                    rx.el.span(class_name=s["f"].to(str), style={"width": s["w"]}),
                    class_name="h-1.5 w-12 overflow-hidden rounded-full bg-fill",
                    aria_hidden="true",
                ),
                class_name=s["c"].to(str),
            ),
        ),
        (
            "mix",
            rx.el.div(
                rx.foreach(
                    L(s["p"]),
                    lambda p: rx.el.div(class_name=p["c"].to(str), style={"flexGrow": p["g"], "flexBasis": "0px", "minWidth": "2px"}),
                ),
                class_name=s["c"].to(str),
                title=s["ti"].to(str),
                role="img",
                aria_label=s["ti"].to(str),
            ),
        ),
        (
            "tog",
            rx.el.details(
                rx.el.summary(
                    chevron("size-3"),
                    aria_label=s["ti"].to(str),
                    title=s["ti"].to(str),
                    class_name="press ml-auto grid size-8 cursor-pointer place-items-center rounded-full text-label-3 hover:bg-fill hover:text-label",
                ),
                open=s["o"].to(bool),
            ),
        ),
        _span(s),
    )


def seg(s: rx.Var) -> rx.Component:
    """One segment (a group renders its leaf children inside a span)."""
    s = D(s)
    return rx.cond(
        s["k"] == "g",
        rx.el.span(rx.foreach(L(s["s"]), _leaf), class_name=s["c"].to(str), title=s["ti"].to(str)),
        _leaf(s),
    )


def segs(v: Any) -> rx.Component:
    return rx.foreach(L(v), seg)


@rx.memo
def rich_box1(b: rx.Var[Dict]) -> rx.Component:
    return rx.el.div(segs(b["s"]), class_name=b["c"].to(str), title=b["ti"].to(str))


@rx.memo
def rich_box2(b: rx.Var[Dict]) -> rx.Component:
    return rx.el.div(segs(b["s"]), rx.foreach(L(b["b"]), lambda c: rich_box1(b=c)), class_name=b["c"].to(str), title=b["ti"].to(str))


@rx.memo
def rich_box3(b: rx.Var[Dict]) -> rx.Component:
    return rx.el.div(segs(b["s"]), rx.foreach(L(b["b"]), lambda c: rich_box2(b=c)), class_name=b["c"].to(str), title=b["ti"].to(str))


@rx.memo
def rich_box4(b: rx.Var[Dict]) -> rx.Component:
    return rx.el.div(segs(b["s"]), rx.foreach(L(b["b"]), lambda c: rich_box3(b=c)), class_name=b["c"].to(str), title=b["ti"].to(str))


@rx.memo
def rich_box5(b: rx.Var[Dict]) -> rx.Component:
    return rx.el.div(segs(b["s"]), rx.foreach(L(b["b"]), lambda c: rich_box4(b=c)), class_name=b["c"].to(str), title=b["ti"].to(str))


@rx.memo
def rich_cell(b: rx.Var[Dict]) -> rx.Component:
    """A table cell: the box itself is the <td>."""
    return rx.el.td(segs(b["s"]), rx.foreach(L(b["b"]), lambda c: rich_box4(b=c)), class_name=b["c"].to(str), title=b["ti"].to(str))


def box(v: Any) -> rx.Component:
    return rich_box5(b=D(v))


def inline(v: Any, class_name: str = "") -> rx.Component:
    """Segments inside a <span>."""
    return rx.el.span(segs(v), class_name=class_name)
