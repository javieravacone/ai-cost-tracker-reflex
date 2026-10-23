"""People (`/personas`), port of src/app/personas/page.tsx."""

from __future__ import annotations

from typing import Any

import reflex as rx

from bis_cost_tracker.components.layout import shell
from bis_cost_tracker.components.ui import card, confidence_help, data_table, disclosure, empty_state, loading, page_header, section
from bis_cost_tracker.state import AppState
from bis_cost_tracker.views import people


@AppState.register
class PeopleState(AppState):
    data: dict[str, Any] = people.empty()
    loaded: bool = False

    def _build(self) -> None:
        self.data = people.build(self._query())
        self.loaded = True

    @rx.event
    def load(self):
        self._shell("PeopleState")
        self._build()


COLS = [("Person", False, ""), ("Turns", True, ""), ("AI credits", True, ""), ("Subscription", True, ""), ("With issue", True, ""), ("sr:Details", False, "w-12")]
POOL_COLS = [("Month", False, ""), ("Entity", False, ""), ("Seats", True, ""), ("Used / pool", True, ""), ("Overage", True, ""), ("Turns with data", True, "")]
IDLE_COLS = [("Month", False, ""), ("Person", False, ""), ("Seat (month)", True, ""), ("Share in period", True, ""), ("Charged", True, "")]
MM_COLS = [
    ("Month", False, ""),
    ("Person", False, ""),
    ("Credits used / included", True, ""),
    ("Month total", True, ""),
    ("API equivalent", True, ""),
    ("sr:Details", False, "w-12"),
]


def _content(d: Any) -> rx.Component:
    header = page_header("People", d["subtitle"])
    return rx.cond(
        d["empty"],
        rx.fragment(header, empty_state(d["db_empty"])),
        rx.fragment(
            header,
            data_table(COLS, d["rows"]),
            rx.cond(
                d["has_pools"],
                section(
                    "AI credit pool",
                    data_table(POOL_COLS, d["pools"]),
                    rx.el.p(
                        "All members form a single entity (organization) in this POC. Turns with no data don’t add up, so with "
                        "incomplete coverage the usage and overage are lower bounds. Turns from people who aren’t members don’t count.",
                        class_name="mt-3 max-w-[90ch] px-1 text-[12.5px] text-label-3",
                    ),
                    subtitle="Included credits from all seats for the month, shared by the billing entity. Only usage above it is paid ($0.01 per credit).",
                ),
            ),
            section(
                "Unused seats",
                rx.cond(
                    d["has_idle"],
                    data_table(IDLE_COLS, d["idle"]),
                    card(rx.el.p("Every member used Copilot in each month of the period.", class_name="text-[14px] text-label-2")),
                ),
                subtitle="Members with no turns in the month",
                action=rx.cond(d["has_idle"], rx.el.span(d["idle_total"], class_name="font-semibold tabular-nums text-warn-text")),
            ),
            disclosure(
                "Details by member and month",
                rx.el.p(
                    "Full months touched by the period: AI credits vs. those included in the seat (without the pool). Under-used: "
                    "less than ",
                    d["low_usage"],
                    " of the included premium requests (legacy).",
                    class_name="mb-4 max-w-[90ch] text-[13px] text-label-2",
                ),
                data_table(MM_COLS, d["mm"], standalone=False, class_name="-mx-6 rounded-none!", max_height="max-h-[min(70vh,44rem)]"),
                rx.el.p(
                    "Figures for the full calendar month (UTC). “Credit overage (without pool)” only compares with the seat’s own "
                    "credits; what is actually billed is the pool overage. Each member-month’s subscription cost is split across its "
                    "turns by premium requests (legacy model); turns in the period get their share.",
                    class_name="mt-4 max-w-[90ch] text-[12.5px] text-label-3",
                ),
                hint=d["mm_hint"],
                surface=True,
            ),
            confidence_help(),
        ),
    )


def page() -> rx.Component:
    return shell("/personas", rx.cond(PeopleState.loaded, _content(PeopleState.data), loading()))
