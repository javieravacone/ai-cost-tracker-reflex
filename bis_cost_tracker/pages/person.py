"""Person detail (`/personas/[user]`), port of src/app/personas/[user]/page.tsx."""

from __future__ import annotations

from typing import Any

import reflex as rx

from bis_cost_tracker.components.layout import shell
from bis_cost_tracker.components.rich import L, inline, seg
from bis_cost_tracker.components.ui import (
    LINK,
    bar_list,
    card,
    daily_chart,
    data_table,
    empty_note,
    kpi,
    loading,
    more_link,
    not_found,
    page_header,
    rlink,
    section,
    stat,
)
from bis_cost_tracker.pages.team import hero_value
from bis_cost_tracker.state import AppState
from bis_cost_tracker.views import person


@AppState.register
class PersonState(AppState):
    data: dict[str, Any] = person.empty()
    loaded: bool = False

    def _build(self) -> None:
        self.data = person.build(self._segment(1), self._query())
        self.loaded = True

    @rx.event
    def load(self):
        self._shell("PersonState")
        self._build()


PROJECT_COLS = [("Project", False, ""), ("AI credits", True, ""), ("Share", True, ""), ("Tokens", True, ""), ("Turns", True, "")]
ISSUE_COLS = [("Issue", False, ""), ("Confidence", False, ""), ("PRs", False, ""), ("AI credits", True, ""), ("Turns", True, "")]
SESSION_COLS = [("Last activity", False, ""), ("Repo and branches", False, ""), ("Turns", True, ""), ("AI credits", True, ""), ("Issues · PRs", False, "")]


def _seat(s: Any) -> rx.Component:
    return rx.el.div(
        rx.el.div(
            rx.el.span("Seat · ", rx.el.span(s["month"], class_name="inline-block"), class_name="font-medium text-label-2"),
            rx.cond(s["has_included"], rx.el.span(s["share"], class_name="tabular-nums font-semibold text-label")),
            class_name="flex items-baseline justify-between gap-3 text-[13px]",
        ),
        rx.cond(
            s["has_included"],
            rx.fragment(
                rx.el.div(
                    rx.el.div(class_name=s["bar"].to(str), style={"width": s["w"]}),
                    class_name="mt-3 h-2 overflow-hidden rounded-full bg-fill",
                    aria_hidden="true",
                ),
                rx.el.div(
                    rx.el.span(s["used"], class_name="font-medium text-label-2"),
                    s["included"],
                    rx.el.span(s["over"], class_name="text-bad-text"),
                    class_name="mt-2.5 text-[12.5px] tabular-nums text-label-3",
                ),
            ),
            rx.el.div(
                rx.el.span(s["used_credits"], class_name="font-medium text-label-2"),
                s["no_included"],
                class_name="mt-2 text-[12.5px] text-label-3",
            ),
        ),
        rx.cond(s["missing"] != "", rx.el.div(s["missing"], class_name="mt-1.5 text-[12px] text-warn-text")),
        class_name="w-full max-w-[22rem] rounded-[18px] bg-surface/70 px-5 py-4 shadow-card",
    )


def _content(d: Any) -> rx.Component:
    title = rx.el.span(seg(d["avatar"]), rx.el.span(d["name"], class_name="min-w-0"), class_name="flex items-center gap-4")
    hero = rx.el.section(
        rx.el.div(
            kpi("Actual Copilot usage", hero_value(d), d["hint"], size="xl"),
            rx.cond(d["has_seat"], _seat(d["seat"])),
            class_name="flex flex-wrap items-start justify-between gap-x-10 gap-y-8",
        ),
        rx.el.dl(
            rx.foreach(L(d["stats"]), lambda s: stat(s["label"], s["value"], s["hint"], mono=s["mono"].to(bool), title=s["title"].to(str))),
            class_name="stagger mt-9 grid grid-cols-2 gap-x-8 gap-y-6 border-t border-separator/70 pt-7 sm:grid-cols-3 lg:grid-cols-5",
        ),
        rx.cond(
            d["has_turns"],
            rx.el.div(
                rx.el.h2(d["chart_title"], class_name="mb-3 text-[13px] font-medium text-label-2"),
                daily_chart(d["chart"]),
                class_name="mt-9",
            ),
        ),
        class_name="overflow-hidden rounded-[24px] glass-hero p-7! sm:p-9!",
    )
    body = rx.cond(
        d["has_turns"],
        rx.fragment(
            rx.el.div(
                card(
                    data_table(PROJECT_COLS, d["projects"], standalone=False),
                    title="Usage by project",
                    subtitle=d["projects_subtitle"],
                    flush=True,
                ),
                card(bar_list(d["models"]), title="Models", subtitle="Turns · AI credits"),
                class_name="stagger grid gap-4 lg:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)]",
            ),
            section(
                "Issues and PRs",
                rx.cond(
                    d["has_issues"],
                    data_table(ISSUE_COLS, d["issues"]),
                    empty_note("No turn has an issue. ", rlink("Review their turns with no issue", href=d["no_issue_href"].to(str), class_name=LINK)),
                ),
                subtitle="Work their turns are attributed to, by AI credits",
            ),
            section(
                "Sessions",
                data_table(SESSION_COLS, d["sessions"]),
                subtitle=d["sessions_subtitle"],
                action=more_link(d["sessions_href"].to(str), "See all"),
            ),
        ),
        empty_note(d["empty_note"]),
    )
    return rx.cond(
        d["found"],
        rx.fragment(
            page_header(title, inline(d["subtitle"], "flex flex-wrap items-center gap-x-2 gap-y-1"), crumbs=d["crumbs"]),
            hero,
            body,
        ),
        not_found(),
    )


def page() -> rx.Component:
    return shell("/personas", rx.cond(PersonState.loaded, _content(PersonState.data), loading()))
