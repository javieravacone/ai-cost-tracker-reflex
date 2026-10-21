"""Team detail (`/equipos/[id]`), port of src/app/equipos/[id]/page.tsx."""

from __future__ import annotations

from typing import Any

import reflex as rx

from bis_cost_tracker.components.layout import shell
from bis_cost_tracker.components.rich import L, box, inline
from bis_cost_tracker.components.ui import (
    bar_list,
    card,
    data_table,
    kpi,
    loading,
    more_link,
    not_found,
    page_header,
    section,
    stat,
)
from bis_cost_tracker.state import AppState
from bis_cost_tracker.views.shell import team_title, set_title_script
from bis_cost_tracker.views import team


@AppState.register
class TeamState(AppState):
    data: dict[str, Any] = team.empty()
    loaded: bool = False

    def _build(self) -> None:
        self.data = team.build(self._segment(1), self._query())
        self.loaded = True

    @rx.event
    def load(self):
        self._shell("TeamState")
        self._build()
        # Dynamic document title, like the Next app's generateMetadata.
        return rx.call_script(set_title_script(team_title(self._segment(1))))


MEMBER_COLS = [
    ("Person", False, ""),
    ("AI credits", True, ""),
    ("Turns", True, ""),
    ("Tokens", True, ""),
    ("Main project", False, ""),
    ("Last activity", True, ""),
]


def hero_value(d: Any) -> rx.Component:
    return rx.cond(
        d["has_credits"],
        rx.fragment(d["hero_value"], rx.el.span("AI credits", class_name="ml-3 text-[0.36em] font-medium tracking-normal text-label-2")),
        box(d["hero_alt"]),
    )


def stats(items: Any) -> rx.Component:
    return rx.el.dl(
        rx.foreach(L(items), lambda s: stat(s["label"], s["value"], s["hint"])),
        class_name="stagger mt-9 grid grid-cols-2 gap-x-8 gap-y-6 border-t border-separator/70 pt-7 sm:grid-cols-3 lg:grid-cols-5",
    )


def _content(d: Any) -> rx.Component:
    return rx.cond(
        d["found"],
        rx.fragment(
            page_header(d["name"], inline(d["subtitle"], "flex flex-wrap items-center gap-x-2 gap-y-1"), crumbs=d["crumbs"]),
            rx.el.section(
                rx.el.div(
                    kpi("Actual Copilot usage", hero_value(d), d["hint"], size="xl"),
                    rx.cond(
                        d["has_last"],
                        rx.el.div(
                            rx.el.div("Last activity", class_name="text-label-3"),
                            rx.el.div(d["last"], class_name="mt-0.5 font-medium text-label", title=d["last_title"].to(str)),
                            class_name="text-[13px] sm:text-right",
                        ),
                    ),
                    class_name="flex flex-wrap items-end justify-between gap-x-10 gap-y-8",
                ),
                stats(d["stats"]),
                class_name="overflow-hidden rounded-[24px] glass-hero p-7! sm:p-9!",
            ),
            section(
                "Members",
                data_table(MEMBER_COLS, d["members"]),
                subtitle="Usage by each person on this team. Select a row to see their profile and sessions.",
            ),
            rx.el.div(
                card(bar_list(d["projects"], empty="No turns in this period"), title="Team projects", subtitle=d["projects_subtitle"]),
                card(
                    bar_list(d["issues"], empty="No team turn has an issue"),
                    title="Team issues",
                    subtitle="Top 5 by AI credits",
                    action=more_link(d["issues_href"].to(str), "All issues"),
                ),
                class_name="stagger grid gap-4 lg:grid-cols-2",
            ),
            rx.el.div(more_link(d["sessions_href"].to(str), "See all team sessions"), class_name="-mt-2 flex justify-end px-1"),
        ),
        not_found(),
    )


def page() -> rx.Component:
    return shell("/equipos", rx.cond(TeamState.loaded, _content(TeamState.data), loading()))
