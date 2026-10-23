"""Sessions (`/sesiones`), port of src/app/sesiones/page.tsx."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlencode

import reflex as rx

from bis_cost_tracker.components.layout import shell
from bis_cost_tracker.components.rich import L, svg_attrs
from bis_cost_tracker.components.ui import (
    LINK,
    MONO,
    card,
    confidence_help,
    data_table,
    empty_note,
    empty_state,
    loading,
    page_header,
    rlink,
)
from bis_cost_tracker.state import AppState
from bis_cost_tracker.views import sessions


@AppState.register
class SessionsState(AppState):
    data: dict[str, Any] = sessions.empty()
    loaded: bool = False

    def _build(self) -> None:
        self.data = sessions.build(self._query())
        self.loaded = True

    @rx.event
    def load(self):
        self._shell("SessionsState")
        self._build()

    @rx.event
    def apply_filters(self, form: dict[str, Any]):
        """Same URL a GET <form action="/sesiones"> produces (field order, empty values kept)."""
        pairs = [(k, "" if v is None else str(v)) for k, v in form.items() if k != "sin_issue" or v]
        return rx.redirect(f"/sesiones?{urlencode(pairs)}")


COLS = [
    ("Last activity", False, ""),
    ("Person", False, ""),
    ("Repo and branches", False, ""),
    ("AI credits", True, ""),
    ("Issues · PRs", False, ""),
    ("sr:Details", False, "w-12"),
]


def _select(label: str, name: str, options: Any, value: Any) -> rx.Component:
    return rx.el.label(
        rx.el.span(label, class_name="px-0.5 text-[12px] font-medium text-label-3"),
        rx.el.span(
            rx.el.select(
                rx.el.option("All", value=""),
                rx.foreach(L(options), lambda o: rx.el.option(o["label"], value=o["value"].to(str))),
                name=name,
                default_value=value,
                class_name="w-full cursor-pointer appearance-none rounded-[10px] bg-fill py-2 pl-3 pr-8 text-[13.5px] text-label outline-none transition-colors hover:bg-fill-2 focus-visible:ring-3 focus-visible:ring-accent/40",
            ),
            rx.el.svg(
                rx.el.svg.path(d="M3 4.5 6 2l3 2.5M3 7.5 6 10l3-2.5"),
                view_box="0 0 12 12",
                class_name="pointer-events-none absolute right-2.5 top-1/2 size-3 -translate-y-1/2 text-label-2",
                custom_attrs=svg_attrs(fill="none", stroke="currentColor", stroke_width="1.6", stroke_linecap="round", stroke_linejoin="round"),
                aria_hidden="true",
            ),
            class_name="relative",
        ),
        class_name="flex min-w-[11rem] flex-col gap-1.5",
    )


def _filters(d: Any) -> rx.Component:
    return card(
        rx.el.form(
            rx.foreach(L(d["hidden"]), lambda h: rx.el.input(type="hidden", name=h["name"].to(str), value=h["value"].to(str))),
            _select("Team", "team", d["teams"], d["team"]),
            _select("Project", "project", d["projects"], d["project"]),
            _select("Person", "user", d["users"], d["user"]),
            rx.el.label(
                rx.el.input(type="checkbox", name="sin_issue", value="1", default_checked=d["sin_issue"].to(bool), class_name="size-4"),
                rx.el.span("Only turns with no issue"),
                class_name="flex cursor-pointer items-center gap-2 py-2 text-[13.5px]",
            ),
            rx.el.div(
                rx.cond(d["active"], rlink("Clear filters", href=d["clear_href"].to(str), class_name=f"{LINK} text-[13px]")),
                rx.el.button(
                    "Apply filters",
                    type="submit",
                    class_name="press rounded-[10px] bg-accent px-5 py-2 text-[13.5px] font-medium text-white shadow-control hover:bg-accent-hover",
                ),
                class_name="ml-auto flex items-center gap-3",
            ),
            key=d["form_key"].to(str),
            on_submit=SessionsState.apply_filters,
            reset_on_submit=False,
            class_name="flex flex-wrap items-end gap-4",
        ),
        class_name="p-5! sm:p-6!",
    )


def _token(t: Any) -> rx.Component:
    return rx.el.span(
        t["label"],
        " ",
        rx.el.span(t["value"], class_name=MONO),
        rlink(
            "×",
            href=t["href"].to(str),
            aria_label=t["aria"].to(str),
            class_name="press grid size-6 place-items-center rounded-full text-[14px] leading-none hover:bg-accent/20",
        ),
        class_name="inline-flex items-center gap-1.5 rounded-full bg-accent/12 py-1 pl-3.5 pr-1 text-[13px] text-info-text",
    )


def _content(d: Any) -> rx.Component:
    header = page_header("Sessions", d["subtitle"])
    return rx.cond(
        d["empty"],
        rx.fragment(header, empty_state(d["db_empty"])),
        rx.fragment(
            header,
            _filters(d),
            rx.el.div(
                rx.foreach(L(d["tokens"]), _token),
                rx.el.p(
                    rx.el.span(d["count"], class_name="font-semibold tabular-nums text-label"),
                    d["count_rest"],
                    class_name="text-[13px] text-label-2",
                ),
                class_name="-my-2 flex flex-wrap items-center gap-x-4 gap-y-2 px-1",
            ),
            rx.cond(
                d["has_rows"],
                data_table(COLS, d["rows"]),
                empty_note("No session matches the filters. ", rlink("Clear filters", href=d["clear_href"].to(str), class_name=LINK)),
            ),
            confidence_help(),
        ),
    )


def page() -> rx.Component:
    return shell("/sesiones", rx.cond(SessionsState.loaded, _content(SessionsState.data), loading()))
