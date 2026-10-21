"""App-wide state: shell data (period picker, last sync, data-source status) and the Sync action.

Every page state subclasses `AppState` and, in its `load` (on_load) handler, calls
`self._shell()` and then computes its own view model with bis_cost_tracker.views.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, ClassVar

import reflex as rx

from bis_core.app_data import safe_decode
from bis_core.db import default_db_path, open_db
from bis_core.report import DAY_OPTIONS, parse_days
from bis_core.sync import SyncOutcome, run_full_sync

from bis_cost_tracker.views.shell import (
    EMPTY_TOAST,
    days_query,
    last_sync_view,
    period_index,
    period_links,
    source_status,
    toast_view,
)

log = logging.getLogger(__name__)

TOAST_MS = 5000

_DEFAULT_PERIOD = [{"label": f"{d} days", "href": "/" if d == 30 else f"/?days={d}", "selected": d == 30} for d in DAY_OPTIONS]


def _sync_blocking() -> SyncOutcome:
    """Full sync on its own connection (the page loads keep using the shared one)."""
    db = open_db(default_db_path())
    try:
        return run_full_sync(db)
    finally:
        db.close()


class AppState(rx.State):
    """Shell data shared by every page."""

    days: int = 30
    days_q: str = ""
    period: list[dict[str, Any]] = _DEFAULT_PERIOD
    period_index: int = 1
    period_tx: str = "translateX(100%)"
    last_sync: dict[str, Any] = {"never": False, "known": False, "label": "…", "clock": "", "title": ""}
    source: dict[str, Any] = {
        "dot": "size-2 rounded-full bg-conf-project",
        "title": "",
        "has_counts": False,
        "langsmith": "",
        "seed": "",
        "project_url": "",
    }
    syncing: bool = False
    toast: dict[str, Any] = EMPTY_TOAST
    toast_id: int = 0

    # Page states register here so the Sync action can reload the visible page.
    _registry: ClassVar[dict[str, type[rx.State]]] = {}
    _page: str = ""

    # --- helpers for page states ------------------------------------------------------------

    def _query(self) -> dict[str, str]:
        return dict(self.router.url.query_parameters)

    def _path(self) -> str:
        return self.router.url.path or "/"

    def _segment(self, index: int) -> str:
        """Decoded path segment (`/equipos/<id>` -> index 1 is the id)."""
        parts = [p for p in self._path().split("/") if p]
        return safe_decode(parts[index]) if len(parts) > index else ""

    def _shell(self, page: str) -> None:
        q = self._query()
        self._page = page
        self.days = parse_days(q.get("days"))
        self.days_q = days_query(self.days)
        self.period = period_links(self._path(), q)
        self.period_index = period_index(self.days)
        self.period_tx = f"translateX({self.period_index * 100}%)"
        self.last_sync = last_sync_view()
        self.source = source_status()

    @classmethod
    def register(cls, state: type[rx.State]) -> type[rx.State]:
        cls._registry[state.__name__] = state
        return state

    # --- sync -----------------------------------------------------------------------------------

    @rx.event(background=True)
    async def sync_now(self):
        async with self:
            if self.syncing:
                return
            self.syncing = True
            self.toast = EMPTY_TOAST
        outcome: SyncOutcome | None = None
        try:
            outcome = await asyncio.to_thread(_sync_blocking)
            toast = toast_view(outcome)
        except Exception:  # noqa: BLE001 - shown as "Sync failed" like the Next app
            log.exception("sync failed")
            toast = toast_view(None, error=True)
        async with self:
            self.syncing = False
            self.toast = toast
            self.toast_id += 1
            mine = self.toast_id
            self.last_sync = last_sync_view()
            self.source = source_status()
        if outcome is not None and outcome.status == "done":
            yield AppState.reload_current
        await asyncio.sleep(TOAST_MS / 1000)
        async with self:
            if self.toast_id == mine:
                self.toast = EMPTY_TOAST

    @rx.event
    async def reload_current(self):
        """Recompute the visible page after a sync (fresh numbers without navigating)."""
        cls = self._registry.get(self._page)
        if cls is None:
            return
        page = await self.get_state(cls)
        page._build()  # type: ignore[attr-defined]
