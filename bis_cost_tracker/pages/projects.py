"""Projects (`/proyectos`), port of src/app/proyectos/page.tsx."""

from __future__ import annotations

from typing import Any

import reflex as rx

from bis_cost_tracker.components.layout import shell
from bis_cost_tracker.components.ui import code, confidence_help, data_table, empty_state, loading, page_header
from bis_cost_tracker.state import AppState
from bis_cost_tracker.views import projects


@AppState.register
class ProjectsState(AppState):
    data: dict[str, Any] = projects.empty()
    loaded: bool = False

    def _build(self) -> None:
        self.data = projects.build(self._query())
        self.loaded = True

    @rx.event
    def load(self):
        self._shell("ProjectsState")
        self._build()


COLS = [("Project", False, ""), ("Turns", True, ""), ("AI credits", True, ""), ("Subscription", True, ""), ("Attributed", True, ""), ("sr:Details", False, "w-12")]


def _content(d: Any) -> rx.Component:
    header = page_header("Projects", d["subtitle"])
    return rx.cond(
        d["empty"],
        rx.fragment(header, empty_state(d["db_empty"])),
        rx.fragment(
            header,
            data_table(COLS, d["rows"]),
            confidence_help(
                "The project comes from the repo → project mapping (or the ",
                code("project.id"),
                " attribute). “No issue” groups the project’s turns that couldn’t be attributed to any issue (they may have "
                "a PR). “No project” = unmapped repo or turn with no repo. AI credits = actual usage reported by Copilot "
                "(1 credit = $0.01, gross); “no data” is not 0. Subscription doesn’t include unused seats (they have no project).",
            ),
        ),
    )


def page() -> rx.Component:
    return shell("/proyectos", rx.cond(ProjectsState.loaded, _content(ProjectsState.data), loading()))
