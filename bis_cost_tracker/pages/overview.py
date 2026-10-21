"""Overview (`/`), port of src/app/page.tsx."""

from __future__ import annotations

from typing import Any

import reflex as rx

from bis_cost_tracker.components.layout import shell
from bis_cost_tracker.components.rich import box
from bis_cost_tracker.components.ui import (
    LINK,
    avisos,
    bar_list,
    card,
    confidence_help,
    confidence_legend,
    daily_chart,
    disclosure,
    empty_state,
    kpi,
    kpi_tiles,
    loading,
    more_link,
    page_header,
    rlink,
)
from bis_cost_tracker.components.rich import seg
from bis_cost_tracker.state import AppState
from bis_cost_tracker.views import overview


@AppState.register
class OverviewState(AppState):
    data: dict[str, Any] = overview.empty()
    loaded: bool = False

    def _build(self) -> None:
        self.data = overview.build(self._query())
        self.loaded = True

    @rx.event
    def load(self):
        self._shell("OverviewState")
        self._build()


def _hero(d: Any) -> rx.Component:
    value = rx.cond(
        d["has_credits"],
        rx.fragment(
            d["hero_value"],
            rx.el.span("AI credits", class_name="ml-3 text-[0.36em] font-medium tracking-normal text-label-2"),
        ),
        box(d["hero_alt"]),
    )
    hint = rx.cond(
        d["has_credits"],
        rx.el.span(
            rx.el.span(d["hero_usd"], class_name="font-medium text-label-2"),
            rx.el.span("gross at list price"),
            rx.cond(
                d["has_delta"],
                rx.el.span(
                    rx.el.span(d["delta_arrow"], aria_hidden="true"),
                    d["delta"],
                    class_name="inline-flex items-center gap-1 rounded-full bg-fill px-2.5 py-0.5 text-[12.5px] font-medium text-label-2 tabular-nums",
                    title=d["delta_title"].to(str),
                ),
            ),
            class_name="flex flex-wrap items-center gap-x-3 gap-y-2",
        ),
        "Copilot reported no credits in this period",
    )
    return card(
        rx.el.div(
            kpi("Actual Copilot usage", value, hint, size="xl"),
            rx.el.dl(
                rx.cond(
                    d["show_peak"],
                    rx.el.div(
                        rx.el.dt("Peak day", class_name="text-label-3"),
                        rx.el.dd(d["peak"], class_name="mt-0.5 font-medium text-label tabular-nums"),
                    ),
                ),
                rx.el.div(
                    rx.el.dt("Active days", class_name="text-label-3"),
                    rx.el.dd(d["active"], class_name="mt-0.5 font-medium text-label tabular-nums"),
                ),
                class_name="grid gap-3 text-[13px] sm:text-right",
            ),
            class_name="flex flex-wrap items-start justify-between gap-x-10 gap-y-6",
        ),
        rx.el.div(
            rx.el.h2(d["chart_title"], class_name="mb-3 text-[13px] font-medium text-label-2"),
            daily_chart(d["chart"]),
            class_name="mt-10",
        ),
        hero=True,
        class_name="p-7! sm:p-9!",
    )


def _models(d: Any) -> rx.Component:
    return disclosure(
        "Models and attribution confidence",
        rx.el.div(
            rx.el.div(
                rx.el.h3("Models · API cost and turns", class_name="mb-3 text-[13px] font-medium text-label-2"),
                bar_list(d["models"]),
            ),
            rx.el.div(
                rx.el.h3("Attribution confidence", class_name="mb-4 text-[13px] font-medium text-label-2"),
                seg(d["mix"]),
                rx.el.div(confidence_legend(d["legend"]), class_name="mt-4"),
                rx.el.div(
                    rx.el.span("With issue ", seg(d["with_issue"])),
                    rx.el.span("With PR ", seg(d["with_pr"])),
                    class_name="mt-5 flex flex-wrap items-center gap-x-6 gap-y-2 text-[13px] text-label-2",
                ),
                rx.el.p(
                    "Turns without an issue can be reviewed in ",
                    rlink("Sessions with no issue", href=d["sin_issue_href"].to(str), class_name=LINK),
                    " and assigned by hand.",
                    class_name="mt-5 text-[13px] text-label-2",
                ),
                rx.el.div(confidence_help(), class_name="mt-4"),
            ),
            class_name="grid gap-x-12 gap-y-10 lg:grid-cols-2",
        ),
        hint=d["models_hint"],
        surface=True,
    )


def _content(d: Any) -> rx.Component:
    header = page_header("Overview", d["subtitle"])
    return rx.cond(
        d["empty"],
        rx.fragment(header, empty_state(d["db_empty"])),
        rx.fragment(
            header,
            avisos(d["avisos"]),
            _hero(d),
            kpi_tiles(d["tiles"]),
            rx.el.div(
                card(bar_list(d["teams"]), title="Teams", subtitle="AI credits · USD", action=more_link(d["teams_href"].to(str))),
                card(bar_list(d["projects"]), title="Projects", subtitle="AI credits · USD", action=more_link(d["projects_href"].to(str))),
                card(
                    bar_list(d["issues"], empty="No turn in this period has an issue"),
                    title="Issues",
                    subtitle="AI credits · USD",
                    action=more_link(d["issues_href"].to(str)),
                ),
                class_name="stagger grid gap-4 lg:grid-cols-3",
            ),
            _models(d),
        ),
    )


def page() -> rx.Component:
    return shell("/", rx.cond(OverviewState.loaded, _content(OverviewState.data), loading()))
