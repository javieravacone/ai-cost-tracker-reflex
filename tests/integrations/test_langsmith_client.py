"""Port of src/lib/langsmith/client.test.ts."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import httpx
import pytest

from bis_core.langsmith.client import (
    ClientOptions,
    LangSmithApiError,
    LangSmithClient,
    LangSmithConfig,
    LangSmithConfigError,
    LangSmithProject,
    get_langsmith_config,
    slice_window,
)

CONFIG = LangSmithConfig(api_key="lsv2_test_secret", endpoint="https://ls.example", project="copilot-vscode", workspace_id="ws-1")


def utc(s: str) -> datetime:
    return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)


def resp(body: Any, status: int = 200, headers: dict[str, str] | None = None) -> httpx.Response:
    return httpx.Response(status, content=json.dumps(body).encode(), headers={"content-type": "application/json", **(headers or {})})


def make_client(responses: list[httpx.Response]) -> tuple[LangSmithClient, list[httpx.Request]]:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return responses.pop(0) if responses else resp({}, 500)

    c = LangSmithClient(
        CONFIG, ClientOptions(transport=httpx.MockTransport(handler), min_interval_s=0, sleep=lambda _s: None)
    )
    return c, calls


class TestGetLangSmithConfig:
    def test_throws_a_clear_error_without_leaking_anything_when_the_key_is_missing(self) -> None:
        with pytest.raises(LangSmithConfigError, match="LANGSMITH_API_KEY"):
            get_langsmith_config({})

    def test_applies_defaults(self) -> None:
        assert get_langsmith_config({"LANGSMITH_API_KEY": "k"}) == LangSmithConfig(
            api_key="k", endpoint="https://api.smith.langchain.com", project="copilot-vscode", workspace_id=None
        )
        cfg = get_langsmith_config({"LANGSMITH_API_KEY": "k", "LANGSMITH_ENDPOINT": "https://eu.api.smith.langchain.com/"})
        assert cfg.endpoint == "https://eu.api.smith.langchain.com"


class TestSliceWindow:
    def test_splits_into_at_most_7_day_windows(self) -> None:
        start = utc("2026-09-16T00:00:00")
        end = utc("2026-10-16T00:00:00")
        slices = slice_window(start, end)
        assert len(slices) == 5
        assert slices[0][0] == start
        assert slices[-1][1] == end
        assert slice_window(end, end) == []


class TestLangSmithClient:
    def test_resolves_the_project_id_by_name_with_auth_and_workspace_headers(self) -> None:
        c, calls = make_client([resp([{"id": "p-1", "name": "copilot-vscode"}])])
        assert c.resolve_project_id() == "p-1"
        assert str(calls[0].url) == "https://ls.example/api/v1/sessions?name=copilot-vscode&limit=1"
        assert calls[0].headers["x-api-key"] == "lsv2_test_secret"
        assert calls[0].headers["X-Tenant-Id"] == "ws-1"

    def test_resolves_the_project_together_with_its_tenant_id(self) -> None:
        c, _ = make_client([resp([{"id": "p-1", "name": "copilot-vscode", "tenant_id": "org-9"}])])
        assert c.resolve_project() == LangSmithProject(id="p-1", tenant_id="org-9")
        c2, _ = make_client([resp([{"id": "p-1", "name": "copilot-vscode"}])])
        assert c2.resolve_project() == LangSmithProject(id="p-1", tenant_id=None)

    def test_errors_when_the_project_does_not_exist(self) -> None:
        c, _ = make_client([resp([])])
        with pytest.raises(LangSmithApiError, match="not found"):
            c.resolve_project_id()

    def test_follows_next_cursor_and_dedupes_runs_across_slices(self) -> None:
        c, calls = make_client(
            [
                resp({"items": [{"id": "a"}, {"id": "b"}], "next_cursor": "cur-1"}),
                resp({"items": [{"id": "c"}], "next_cursor": None}),
                resp({"items": [{"id": "c"}, {"id": "d"}]}),
            ]
        )
        runs = c.fetch_runs_in_window("p-1", utc("2026-10-01T00:00:00"), utc("2026-10-10T00:00:00"))
        assert sorted(r["id"] for r in runs) == ["a", "b", "c", "d"]
        assert len(calls) == 3
        bodies = [json.loads(call.content) for call in calls]
        assert bodies[0]["project_ids"] == ["p-1"]
        assert bodies[0]["min_start_time"] == "2026-10-01T00:00:00.000Z"
        assert bodies[0]["max_start_time"] == "2026-10-08T00:00:00.000Z"
        assert bodies[0]["page_size"] == 1000
        assert "METADATA" in bodies[0]["selects"]
        assert {"INPUTS", "OUTPUTS", "ERROR", "FEEDBACK_STATS", "END_TIME"} <= set(bodies[0]["selects"])
        assert bodies[1]["cursor"] == "cur-1"
        assert bodies[2]["min_start_time"] == "2026-10-08T00:00:00.000Z"

    def test_retries_429_and_surfaces_other_errors_without_the_api_key(self) -> None:
        c, _ = make_client([resp({}, 429, {"retry-after": "1"}), resp([{"id": "p-1", "name": "copilot-vscode"}])])
        assert c.resolve_project_id() == "p-1"

        c2, _ = make_client([resp({"detail": "bad key"}, 401)])
        with pytest.raises(LangSmithApiError) as info:
            c2.resolve_project_id()
        err = info.value
        assert err.status == 401
        assert "HTTP 401" in str(err)
        assert "lsv2_test_secret" not in str(err)

    def test_backs_off_on_5xx_honouring_retry_after_seconds(self) -> None:
        slept: list[float] = []
        responses = [resp({}, 503), resp({}, 429, {"retry-after": "3"}), resp([{"id": "p-1", "name": "copilot-vscode"}])]
        c = LangSmithClient(
            CONFIG,
            ClientOptions(
                transport=httpx.MockTransport(lambda _r: responses.pop(0)), min_interval_s=0, sleep=slept.append
            ),
        )
        assert c.resolve_project_id() == "p-1"
        assert slept == [2.0, 3.0]
