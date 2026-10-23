"""Teams (`/equipos`), port of src/app/equipos/page.tsx."""

from __future__ import annotations

from typing import Any

import reflex as rx

from bis_cost_tracker.components.layout import shell
from bis_cost_tracker.components.ui import code, confidence_help, data_table, empty_state, loading, page_header
from bis_cost_tracker.state import AppState
from bis_cost_tracker.views import teams


@AppState.register
class TeamsState(AppState):
    data: dict[str, Any] = teams.empty()
    loaded: bool = False

    def _build(self) -> None:
        self.data = teams.build(self._query())
        self.loaded = True

    @rx.event
    def load(self):
        self._shell("TeamsState")
        self._build()


COLS = [("Team", False, ""), ("Turns", True, ""), ("AI credits", True, ""), ("Subscription", True, ""), ("Attributed", True, ""), ("sr:Details", False, "w-12")]


def _content(d: Any) -> rx.Component:
    header = page_header("Teams", d["subtitle"])
    return rx.cond(
        d["empty"],
        rx.fragment(header, empty_state(d["db_empty"])),
        rx.fragment(
            header,
            data_table(COLS, d["rows"]),
            confidence_help(
                "Select a team to see its members and each person’s profile. The team comes from the turn’s ",
                code("team.id"),
                " attribute or, if missing, from the member’s team. “Attributed” = turns with an issue or PR. AI credits = "
                "actual usage reported by Copilot (1 credit = $0.01, gross, before the included pool); “no data” if no turn "
                "reported it. Subscription = the cost charged to the turns; “unused” are seats of team members with no turns "
                "in the month, charged to the period.",
            ),
        ),
    )


def page() -> rx.Component:
    return shell("/equipos", rx.cond(TeamsState.loaded, _content(TeamsState.data), loading()))
