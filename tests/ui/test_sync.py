"""Sync button logic with a stubbed run_full_sync (no network), and the "Last synced" label."""

from __future__ import annotations

import asyncio

import pytest

import bis_cost_tracker.state as state
from bis_core._js import parse_iso_ms
from bis_core.db import set_sync_state
from bis_core.sync import SyncOutcome
from bis_core.sync.summary import SyncSummary
from bis_cost_tracker.views.shell import last_sync_view

SUMMARY = SyncSummary(at="2026-10-21T10:36:00.000Z", ok=True, new_turns=2, turns=21, issues=6, pull_requests=4)


def _run(monkeypatch: pytest.MonkeyPatch, fake) -> tuple[dict, bool]:
    monkeypatch.setattr(state, "run_full_sync", fake)
    return asyncio.run(state.perform_sync())


def test_sync_done_shows_summary_and_reloads(app_db, monkeypatch):
    calls = []

    def fake(db):
        calls.append(db)
        return SyncOutcome(status="done", summary=SUMMARY)

    toast, reload = _run(monkeypatch, fake)
    assert len(calls) == 1 and reload is True
    assert toast["show"] and toast["tone"] == "text-ok-text" and toast["lines"][0].startswith("✓ ")


def test_sync_with_errors_and_busy(app_db, monkeypatch):
    bad = SyncSummary(at=SUMMARY.at, ok=False, new_turns=0, turns=21, issues=0, pull_requests=0, errors=["GitHub: rate limited"])
    toast, reload = _run(monkeypatch, lambda db: SyncOutcome(status="done", summary=bad))
    assert reload and toast["lines"] == ["GitHub: rate limited"] and toast["tone"] == "text-warn-text" and toast["lead"]
    toast, reload = _run(monkeypatch, lambda db: SyncOutcome(status="busy"))
    assert not reload and toast["lines"] == ["A sync is already in progress"]


def test_sync_exception_is_a_failed_toast(app_db, monkeypatch):
    def boom(db):
        raise RuntimeError("network down")

    toast, reload = _run(monkeypatch, boom)
    assert not reload and toast["lines"] == ["Sync failed (network or server error)"] and toast["tone"] == "text-bad-text"


def test_last_synced_label(app_db):
    set_sync_state(app_db, "app.lastSync", SUMMARY.to_json())
    v = last_sync_view(now=parse_iso_ms(SUMMARY.at) + 2 * 3600 * 1000)
    assert v["known"] and not v["never"] and v["label"] == "2 h ago" and v["clock"].startswith(" (")
    app_db.execute("DELETE FROM sync_state WHERE key = 'app.lastSync'")
    assert last_sync_view()["label"] == "Never"


def test_reload_current_rebuilds_the_visible_page(app_db):
    import bis_cost_tracker.bis_cost_tracker  # noqa: F401 - registers the page states
    from reflex.state import State

    from bis_cost_tracker.pages.teams import TeamsState

    root = State(_reflex_internal_init=True)
    teams = root.get_substate(TeamsState.get_full_name().split(".")[1:])
    app = root.get_substate(state.AppState.get_full_name().split(".")[1:])
    teams._page = "TeamsState"  # set by _shell() on page load (lives on AppState)
    assert app._page == "TeamsState" and teams.loaded is False
    asyncio.run(state.AppState.reload_current.fn(app))
    assert teams.loaded is True and teams.data["rows"]
