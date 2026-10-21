"""Port of src/lib/sync/sync.test.ts (+ .env.local loading and the Python-only CLI parsing)."""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx
import pytest

from bis_core.db import (
    get_sync_state,
    list_issues,
    list_turns,
    open_db,
    set_sync_state,
    upsert_repo_mappings,
    upsert_turns,
)
from bis_core.db.content import content_stats, list_skill_usage
from bis_core.github.client import RepoSnapshot
from bis_core.langsmith.client import ClientOptions
from bis_core.sync import (
    LANGSMITH_PROJECT_ID_KEY,
    LANGSMITH_STATE_KEY,
    LANGSMITH_TENANT_ID_KEY,
    LAST_SYNC_KEY,
    NO_GITHUB_TOKEN,
    clock_time,
    exact_time,
    github_repos,
    langsmith_window_start,
    load_local_env,
    parse_env_file,
    parse_sync_summary,
    read_last_sync,
    real_turn_repos,
    relative_time,
    resolve_github_token,
    run_full_sync,
    summary_text,
    sync_github,
    sync_langsmith,
)
from bis_core.types import Issue, RepoMapping, Turn

from .conftest import CONTENT_FIXTURE, EU_FIXTURE, load_fixture

ENV = {"LANGSMITH_API_KEY": "lsv2_test_secret", "LANGSMITH_ENDPOINT": "https://ls.example"}
NOW = datetime(2026, 10, 17, tzinfo=timezone.utc)
FIXTURE_TURN_START = "2026-10-16T15:38:39.044Z"


def resp(body: Any, status: int = 200) -> httpx.Response:
    return httpx.Response(status, content=json.dumps(body).encode(), headers={"content-type": "application/json"})


class LangSmithMock:
    """LangSmith transport mock: sessions lookup, then one page with the fixture runs per query."""

    def __init__(self, items: list[dict[str, Any]] | None = None, tenant_id: str | None = None) -> None:
        self.items = items if items is not None else load_fixture(EU_FIXTURE)
        self.tenant_id = tenant_id
        self.bodies: list[dict[str, Any]] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "/api/v1/sessions" in url:
            session: dict[str, Any] = {"id": "proj-1", "name": "copilot-vscode"}
            if self.tenant_id:
                session["tenant_id"] = self.tenant_id
            return resp([session])
        if url.endswith("/api/v2/runs/query"):
            self.bodies.append(json.loads(request.content))
            return resp({"items": self.items, "next_cursor": None})
        return resp({}, 404)

    @property
    def options(self) -> ClientOptions:
        return ClientOptions(transport=httpx.MockTransport(self.handler), min_interval_s=0, sleep=lambda _s: None)


def turn(**over: Any) -> Turn:
    base = Turn(
        id="t",
        trace_id="trace",
        conversation_id=None,
        started_at="2026-10-10T10:00:00.000Z",
        ended_at=None,
        user_name=None,
        team_id=None,
        project_hint=None,
        repo_url=None,
        branch=None,
        commit_sha=None,
        github_org=None,
        agent_name=None,
        model="gpt-5",
        input_tokens=0,
        output_tokens=0,
        cache_read_tokens=0,
        cache_creation_tokens=0,
        reasoning_tokens=0,
        llm_calls=0,
        tool_calls=0,
        copilot_nano_aiu=None,
        copilot_usage_coverage=None,
        source="langsmith",
    )
    return replace(base, **over)


def db_with_repos() -> sqlite3.Connection:
    """Seed repo + real repo (mapped) + real repo (unmapped)."""
    db = open_db(":memory:")
    upsert_repo_mappings(
        db,
        [
            RepoMapping(repo="acme-labs/atlas-api", project_id="atlas"),
            RepoMapping(repo="javieravacone/ai-cost-tracker", project_id="act"),
        ],
    )
    upsert_turns(
        db,
        [
            turn(id="s1", source="seed", repo_url="git@github.com:acme-labs/atlas-api.git"),
            turn(id="r1", repo_url="https://github.com/JavierAvacone/ai-cost-tracker.git"),
            turn(id="r2", repo_url="https://github.com/someone/unmapped.git"),
            turn(id="r3", repo_url=None),
        ],
    )
    return db


def issue(repo: str, number: int) -> Issue:
    return Issue(
        repo=repo,
        number=number,
        title=f"Issue {number}",
        state="open",
        url=f"https://github.com/{repo}/issues/{number}",
        created_at="2026-10-01T00:00:00Z",
        closed_at=None,
    )


class GitHubMock:
    def __init__(self, impl: Any = None) -> None:
        self.calls: list[tuple[str, str | None]] = []
        self.impl = impl or (lambda repo: RepoSnapshot(issues=[issue(repo, 1), issue(repo, 2)], pull_requests=[]))

    def fetch_repo(self, repo: str, since: str | None = None) -> RepoSnapshot:
        self.calls.append((repo, since))
        return self.impl(repo)


# --- syncLangSmith ----------------------------------------------------------------------------


class TestSyncLangSmith:
    def test_uses_the_stored_cursor_minus_2h_overlap_and_advances_it(self) -> None:
        db = open_db(":memory:")
        set_sync_state(db, LANGSMITH_STATE_KEY, "2026-10-16T12:00:00.000Z")
        ls = LangSmithMock()
        r = sync_langsmith(db, env=ENV, now=NOW, client_options=ls.options)
        assert r.incremental is True
        assert len(ls.bodies) == 1
        assert ls.bodies[0]["min_start_time"] == "2026-10-16T10:00:00.000Z"
        assert ls.bodies[0]["max_start_time"] == "2026-10-17T00:00:00.000Z"
        assert r.latest == FIXTURE_TURN_START
        assert get_sync_state(db, LANGSMITH_STATE_KEY) == FIXTURE_TURN_START

    def test_defaults_to_30_days_without_state_or_with_full_and_since_wins(self) -> None:
        thirty = NOW - timedelta(days=30)
        assert langsmith_window_start(None, NOW) == thirty
        assert langsmith_window_start("2026-10-16T12:00:00.000Z", NOW, full=True) == thirty
        since = datetime(2026, 10, 1, tzinfo=timezone.utc)
        assert langsmith_window_start("2026-10-16T12:00:00.000Z", NOW, since=since) == since

    def test_does_not_move_the_cursor_backwards(self) -> None:
        db = open_db(":memory:")
        set_sync_state(db, LANGSMITH_STATE_KEY, "2026-10-16T20:00:00.000Z")
        sync_langsmith(db, env=ENV, now=NOW, client_options=LangSmithMock().options)
        assert get_sync_state(db, LANGSMITH_STATE_KEY) == "2026-10-16T20:00:00.000Z"

    def test_counts_only_turns_that_were_not_in_the_db_as_new(self) -> None:
        db = open_db(":memory:")
        first = sync_langsmith(db, env=ENV, now=NOW, client_options=LangSmithMock().options)
        assert (first.runs, first.turns, first.upserted, first.new_turns, first.with_repo) == (
            len(load_fixture(EU_FIXTURE)),
            1,
            1,
            1,
            1,
        )
        second = sync_langsmith(db, env=ENV, now=NOW, client_options=LangSmithMock().options)
        assert (second.turns, second.upserted, second.new_turns) == (1, 1, 0)
        assert len(list_turns(db)) == 1

    def test_stores_captured_content_steps_skills_and_the_project_tenant_ids(self) -> None:
        db = open_db(":memory:")
        when = datetime(2026, 10, 21, 8, tzinfo=timezone.utc)
        ls = LangSmithMock(load_fixture(CONTENT_FIXTURE), tenant_id="org-1")
        r = sync_langsmith(db, env=ENV, now=when, client_options=ls.options)
        assert (r.turns, r.with_content, r.events, r.with_skills) == (1, 1, 8, 1)
        assert get_sync_state(db, LANGSMITH_PROJECT_ID_KEY) == "proj-1"
        assert get_sync_state(db, LANGSMITH_TENANT_ID_KEY) == "org-1"
        assert [f"{s.skill}@{s.version}" for s in list_skill_usage(db)] == ["cost-tracker-guide@ecfcda53"]
        # A second sync of the same window replaces instead of duplicating.
        sync_langsmith(db, env=ENV, now=when, client_options=LangSmithMock(load_fixture(CONTENT_FIXTURE)).options)
        s = content_stats(db)
        assert (s.turns_with_content, s.events, s.skill_uses) == (1, 8, 1)


# --- GitHub repo selection -------------------------------------------------------------------


class TestGitHubRepoSelection:
    def test_app_scope_keeps_only_mapped_repos_seen_in_real_turns(self) -> None:
        db = db_with_repos()
        assert real_turn_repos(db) == ["javieravacone/ai-cost-tracker"]
        assert github_repos(db, scope="real-turns") == ["javieravacone/ai-cost-tracker"]

    def test_cli_scope_keeps_every_mapped_repo_and_honours_repo(self) -> None:
        db = db_with_repos()
        assert sorted(github_repos(db)) == ["acme-labs/atlas-api", "javieravacone/ai-cost-tracker"]
        assert github_repos(db, repo="ACME-labs/atlas-api") == ["acme-labs/atlas-api"]

    def test_syncs_incrementally_per_repo_and_reports_a_failing_repo_without_stopping(self) -> None:
        db = db_with_repos()
        set_sync_state(db, "github.acme-labs/atlas-api.lastSync", "2026-10-15T00:00:00.000Z")

        def impl(repo: str) -> RepoSnapshot:
            if repo == "acme-labs/atlas-api":
                raise RuntimeError("boom")
            return RepoSnapshot(issues=[issue(repo, 7)], pull_requests=[])

        gh = GitHubMock(impl)
        res = sync_github(db, client=gh, now=lambda: NOW)
        assert ("acme-labs/atlas-api", "2026-10-15T00:00:00.000Z") in gh.calls
        failed = next(r for r in res if r.repo == "acme-labs/atlas-api")
        assert (failed.error, failed.issues) == ("boom", 0)
        assert next(r for r in res if r.repo == "javieravacone/ai-cost-tracker").issues == 1
        assert get_sync_state(db, "github.javieravacone/ai-cost-tracker.lastSync") == "2026-10-17T00:00:00.000Z"
        assert get_sync_state(db, "github.acme-labs/atlas-api.lastSync") == "2026-10-15T00:00:00.000Z"


# --- resolveGitHubToken ----------------------------------------------------------------------


class TestResolveGitHubToken:
    def test_prefers_github_token_without_running_anything(self) -> None:
        calls: list[Any] = []
        assert resolve_github_token({"GITHUB_TOKEN": " ghp_x "}, run=lambda *a: calls.append(a) or "") == "ghp_x"
        assert calls == []

    def test_falls_back_to_gh_auth_token_across_candidates_none_when_unavailable(self) -> None:
        calls: list[tuple[str, list[str], float]] = []

        def run(binary: str, args: Any, timeout: float) -> str:
            calls.append((binary, list(args), timeout))
            if binary == "gh":
                raise FileNotFoundError("ENOENT")
            return "gho_from_cli\n"

        assert resolve_github_token({}, run=run, candidates=["gh", "/home/u/.local/bin/gh"]) == "gho_from_cli"
        assert calls[-1] == ("/home/u/.local/bin/gh", ["auth", "token"], 5)

        def fail(*_a: Any) -> str:
            raise RuntimeError("x")

        assert resolve_github_token({}, run=fail, candidates=["gh"]) is None


# --- runFullSync -----------------------------------------------------------------------------


def ticking(start: datetime, step: timedelta = timedelta(seconds=1)) -> Any:
    state = {"t": start}

    def now() -> datetime:
        state["t"] += step
        return state["t"]

    return now


class TestRunFullSync:
    def test_syncs_both_sources_filters_repos_to_real_turns_and_persists_last_sync(self) -> None:
        db = db_with_repos()
        gh = GitHubMock()
        out = run_full_sync(db, env=ENV, now=ticking(NOW), langsmith_client_options=LangSmithMock().options, github_client=gh)
        assert [c[0] for c in gh.calls] == ["javieravacone/ai-cost-tracker"]
        assert out.status == "done" and out.summary is not None
        s = out.summary
        assert (s.ok, s.new_turns, s.turns, s.issues, s.pull_requests, s.errors) == (True, 1, 1, 2, 0, [])
        assert [i.repo for i in list_issues(db)] == ["javieravacone/ai-cost-tracker", "javieravacone/ai-cost-tracker"]

        stored = read_last_sync(db)
        assert stored == s
        assert stored is not None and stored.duration_ms > 0
        raw = json.loads(get_sync_state(db, LAST_SYNC_KEY) or "{}")
        assert "status" not in raw
        # Same JSON shape as the TS app (camelCase keys, same order).
        assert list(raw) == ["at", "ok", "newTurns", "turns", "issues", "pullRequests", "errors", "durationMs"]

    def test_skips_github_with_a_clear_message_when_there_is_no_token(self) -> None:
        db = db_with_repos()
        out = run_full_sync(
            db, env=ENV, now=lambda: NOW, langsmith_client_options=LangSmithMock().options, resolve_token=lambda _env: None
        )
        assert out.summary is not None
        s = out.summary
        assert (out.status, s.ok, s.new_turns, s.issues, s.errors) == ("done", False, 1, 0, [NO_GITHUB_TOKEN])

    def test_a_failing_langsmith_does_not_block_github_and_messages_never_leak_the_key(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        db = db_with_repos()
        options = ClientOptions(
            transport=httpx.MockTransport(lambda _r: resp({"detail": "nope"}, 401)), min_interval_s=0, sleep=lambda _s: None
        )
        out = run_full_sync(db, env=ENV, now=lambda: NOW, langsmith_client_options=options, github_client=GitHubMock())
        assert out.summary is not None
        assert (out.summary.ok, out.summary.issues, out.summary.errors) == (False, 2, ["LangSmith: key rejected (HTTP 401)"])
        logged = capsys.readouterr()
        assert ENV["LANGSMITH_API_KEY"] not in logged.err + logged.out
        assert ENV["LANGSMITH_API_KEY"] not in json.dumps(asdict(out.summary))

    def test_a_failing_github_repo_does_not_lose_the_langsmith_turns(self, capsys: pytest.CaptureFixture[str]) -> None:
        db = db_with_repos()

        def boom(_repo: str) -> RepoSnapshot:
            raise httpx.ConnectError("fetch failed")

        out = run_full_sync(
            db, env=ENV, now=lambda: NOW, langsmith_client_options=LangSmithMock().options, github_client=GitHubMock(boom)
        )
        assert out.summary is not None
        assert (out.summary.ok, out.summary.new_turns, out.summary.errors) == (
            False,
            1,
            ["GitHub javieravacone/ai-cost-tracker: could not connect"],
        )
        assert len([t for t in list_turns(db) if t.started_at == FIXTURE_TURN_START]) == 1
        capsys.readouterr()

    def test_returns_busy_while_another_sync_is_running_then_releases_the_lock(self) -> None:
        db = db_with_repos()
        gate = threading.Event()
        entered = threading.Event()

        def slow(repo: str) -> RepoSnapshot:
            entered.set()
            gate.wait(5)
            return RepoSnapshot(issues=[issue(repo, 1)], pull_requests=[])

        def opts() -> dict[str, Any]:
            return {"env": ENV, "now": lambda: NOW, "langsmith_client_options": LangSmithMock().options}

        result: dict[str, Any] = {}
        worker = threading.Thread(
            target=lambda: result.setdefault("first", run_full_sync(db, github_client=GitHubMock(slow), **opts()))
        )
        worker.start()
        assert entered.wait(5)
        busy = run_full_sync(db, github_client=GitHubMock(), **opts())
        assert busy.status == "busy" and busy.summary is None
        gate.set()
        worker.join(5)
        assert result["first"].status == "done" and result["first"].summary.ok is True
        assert run_full_sync(db, github_client=GitHubMock(), **opts()).status == "done"


# --- summary formatting ----------------------------------------------------------------------


class TestSummaryFormatting:
    def test_pluralizes_the_toast_text(self) -> None:
        assert summary_text(new_turns=3, issues=8, pull_requests=4) == "3 new turns · 8 issues · 4 PRs"
        assert summary_text(new_turns=1, issues=1, pull_requests=1) == "1 new turn · 1 issue · 1 PR"
        assert summary_text(new_turns=1234, issues=0, pull_requests=2) == "1,234 new turns · 0 issues · 2 PRs"

    def test_formats_relative_times(self) -> None:
        at = "2026-10-17T10:00:00.000Z"
        t = int(datetime(2026, 10, 17, 10, tzinfo=timezone.utc).timestamp() * 1000)
        assert relative_time(at, t - 5000) == "just now"
        assert relative_time(at, t + 30_000) == "just now"
        assert relative_time(at, t + 3 * 60_000) == "3 min ago"
        assert relative_time(at, t + 2 * 3_600_000) == "2 h ago"
        assert relative_time(at, t + 26 * 3_600_000) == "1 day ago"
        assert relative_time(at, t + 50 * 3_600_000) == "2 days ago"

    def test_formats_exact_and_clock_times_like_intl_en_us(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TZ", "UTC")
        import time

        time.tzset()
        try:
            assert exact_time("2026-10-17T22:41:00.000Z") == "Oct 17, 2026, 10:41 PM"
            assert clock_time("2026-10-17T00:05:00.000Z") == "12:05 AM"
            assert clock_time("2026-10-17T12:00:00.000Z") == "12:00 PM"
        finally:
            monkeypatch.undo()
            time.tzset()

    def test_parses_stored_summaries_defensively(self) -> None:
        assert parse_sync_summary(None) is None
        assert parse_sync_summary("not json") is None
        assert parse_sync_summary('{"at":"nope"}') is None
        s = parse_sync_summary('{"at":"2026-10-17T10:00:00.000Z","ok":1,"newTurns":"3","errors":[1,"x"]}')
        assert s is not None
        assert (s.ok, s.new_turns, s.turns, s.errors, s.duration_ms) == (False, 3, 0, ["1", "x"], 0)


# --- .env.local ------------------------------------------------------------------------------


class TestLocalEnv:
    def test_parses_dotenv_lines(self) -> None:
        text = "# c\nA=1\nexport B = two \nC=\"q#v\"\nD='x' \nE=v # note\nF=abc#def\nG=\nbad line\n=x\n"
        assert parse_env_file(text) == {"A": "1", "B": "two", "C": "q#v", "D": "x", "E": "v", "F": "abc", "G": ""}

    def test_loads_without_overriding_and_respects_if_missing(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        (tmp_path / ".env.local").write_text("RX_TEST_A=file\nRX_TEST_B=file\n", encoding="utf-8")
        monkeypatch.setenv("RX_TEST_A", "env")
        monkeypatch.delenv("RX_TEST_B", raising=False)
        load_local_env(env={}, cwd=tmp_path)  # custom env: no-op
        assert "RX_TEST_B" not in os.environ
        load_local_env(if_missing="RX_TEST_A", cwd=tmp_path)  # variable already set: no-op
        assert "RX_TEST_B" not in os.environ
        load_local_env(cwd=tmp_path)
        assert os.environ["RX_TEST_A"] == "env"
        assert os.environ["RX_TEST_B"] == "file"
        monkeypatch.delenv("RX_TEST_B")
