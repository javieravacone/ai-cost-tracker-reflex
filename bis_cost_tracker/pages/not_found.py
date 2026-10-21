"""404 page (port of src/app/not-found.tsx): the shell with no active section."""

from __future__ import annotations

import reflex as rx

from bis_cost_tracker.components.layout import shell
from bis_cost_tracker.components.ui import not_found
from bis_cost_tracker.state import AppState


@AppState.register
class NotFoundState(AppState):
    def _build(self) -> None:
        pass

    @rx.event
    def load(self):
        self._shell("NotFoundState")


def page() -> rx.Component:
    return shell("", not_found())
