"""LangSmith REST client (read-only) for the Copilot Chat tracing project (port of client.ts).

Endpoints (docs checked 2026-10-16):
- GET  /api/v1/sessions?name=<project>         list tracer sessions (projects) -> TracerSession[]
  https://docs.langchain.com/langsmith/smith-api/tracer-sessions/read-tracer-sessions
- POST /api/v2/runs/query                      { project_ids, min_start_time, max_start_time,
  selects, page_size<=1000, cursor } -> { items, next_cursor }
  https://docs.langchain.com/langsmith/smith-api/runs/query-runs
  (v1 POST /api/v1/runs/query is marked deprecated; self-hosted needs LangSmith >= v0.16)
- Rate limits: <=7-day windows 10 req/10s, larger windows 3 req/10s -> we slice the window
  into <=7-day chunks and space requests; 429 is retried with backoff.
  https://docs.langchain.com/langsmith/export-traces#rate-limits
Auth: `x-api-key`; optional `X-Tenant-Id` (workspace) header. The key is never logged.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode

import httpx

from bis_core.langsmith.map import LangSmithRun, iso_utc


@dataclass
class LangSmithConfig:
    api_key: str
    endpoint: str
    project: str
    workspace_id: str | None


class LangSmithConfigError(Exception):
    pass


class LangSmithApiError(Exception):
    def __init__(self, message: str, status: int) -> None:
        super().__init__(message)
        self.status = status


def _env_str(env: Mapping[str, str | None], key: str) -> str:
    v = env.get(key)
    return v.strip() if isinstance(v, str) else ""


def get_langsmith_config(env: Mapping[str, str | None] | None = None) -> LangSmithConfig:
    env = os.environ if env is None else env
    api_key = _env_str(env, "LANGSMITH_API_KEY")
    if not api_key:
        raise LangSmithConfigError(
            "LANGSMITH_API_KEY is not set. Add it to .env.local (see .env.example) or your environment."
        )
    return LangSmithConfig(
        api_key=api_key,
        endpoint=(_env_str(env, "LANGSMITH_ENDPOINT") or "https://api.smith.langchain.com").rstrip("/"),
        project=_env_str(env, "LANGSMITH_PROJECT") or "copilot-vscode",
        workspace_id=_env_str(env, "LANGSMITH_WORKSPACE_ID") or None,
    )


# Fields requested from /api/v2/runs/query (only `id` is returned when `selects` is omitted).
RUN_SELECTS: tuple[str, ...] = (
    "ID",
    "NAME",
    "RUN_TYPE",
    "STATUS",
    "START_TIME",
    "END_TIME",
    "TRACE_ID",
    "PARENT_RUN_IDS",
    "DOTTED_ORDER",
    "IS_ROOT",
    "THREAD_ID",
    "METADATA",
    "EXTRA",
    "PROMPT_TOKENS",
    "COMPLETION_TOKENS",
    "TOTAL_TOKENS",
    "PROMPT_TOKEN_DETAILS",
    "COMPLETION_TOKEN_DETAILS",
    "TAGS",
    # Content (only present when Copilot runs with content capture on; F3, 2026-10-21): prompts,
    # answers, tool arguments and results. Needed for the session transcript and skill detection.
    "INPUTS",
    "OUTPUTS",
    "ERROR",
    "FEEDBACK_STATS",
)


@dataclass
class LangSmithProject:
    """Tracing project plus the organization (tenant) that owns it, used to build trace links."""

    id: str
    tenant_id: str | None


@dataclass
class ClientOptions:
    # Custom httpx transport (tests use `httpx.MockTransport`).
    transport: httpx.BaseTransport | None = None
    # Minimum spacing between requests in seconds (default 1.1 s ~ 10 req / 10 s).
    min_interval_s: float = 1.1
    max_retries: int = 4
    # Sleep function taking seconds (tests pass a no-op).
    sleep: Callable[[float], None] | None = None


MAX_WINDOW = timedelta(days=7)
# Generous timeouts: a 1000-run page with inputs/outputs can be large (Node fetch has no
# overall timeout either).
_TIMEOUT = httpx.Timeout(300.0, connect=30.0)


def slice_window(start: datetime, end: datetime, max_span: timedelta = MAX_WINDOW) -> list[tuple[datetime, datetime]]:
    """Split [start, end) into consecutive windows no longer than `max_span`."""
    out: list[tuple[datetime, datetime]] = []
    cur = start
    while cur < end:
        stop = min(cur + max_span, end)
        out.append((cur, stop))
        cur = stop
    return out


def _now() -> datetime:
    return datetime.now(timezone.utc)


class LangSmithClient:
    def __init__(self, config: LangSmithConfig, opts: ClientOptions | None = None) -> None:
        opts = opts or ClientOptions()
        self._config = config
        self._min_interval_s = opts.min_interval_s
        self._max_retries = opts.max_retries
        self._sleep = opts.sleep or time.sleep
        self._last_request_at = 0.0
        self._http = httpx.Client(transport=opts.transport, timeout=_TIMEOUT)

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> LangSmithClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _headers(self) -> dict[str, str]:
        h = {
            "x-api-key": self._config.api_key,
            "accept": "application/json",
            "content-type": "application/json",
        }
        if self._config.workspace_id:
            h["X-Tenant-Id"] = self._config.workspace_id
        return h

    def _request(self, method: str, path: str, body: Any = None) -> Any:
        attempt = 0
        while True:
            wait = self._last_request_at + self._min_interval_s - time.monotonic()
            if wait > 0:
                self._sleep(wait)
            self._last_request_at = time.monotonic()

            res = self._http.request(
                method,
                f"{self._config.endpoint}{path}",
                headers=self._headers(),
                content=None if body is None else json.dumps(body, ensure_ascii=False, separators=(",", ":")),
            )
            if res.is_success:
                return res.json()

            retryable = res.status_code == 429 or res.status_code >= 500
            if retryable and attempt < self._max_retries:
                try:
                    retry_after = float(res.headers.get("retry-after") or "nan")
                except ValueError:
                    retry_after = float("nan")
                ok = retry_after == retry_after and retry_after > 0 and retry_after != float("inf")
                self._sleep(retry_after if ok else 2**attempt * 2.0)
                attempt += 1
                continue
            try:
                text = res.text[:500]
            except Exception:  # noqa: BLE001 - body decoding must never hide the HTTP error
                text = ""
            hint = (
                " (check LANGSMITH_API_KEY / LANGSMITH_WORKSPACE_ID)" if res.status_code in (401, 403) else ""
            )
            raise LangSmithApiError(
                f"LangSmith {method} {path} failed: HTTP {res.status_code}{hint} {text}".strip(), res.status_code
            )

    def resolve_project(self, name: str | None = None) -> LangSmithProject:
        """Resolve the tracing project (tracer session) by exact name.

        The same response carries `tenant_id` (the LangSmith organization/workspace id used in UI
        trace links).
        """
        name = self._config.project if name is None else name
        qs = urlencode({"name": name, "limit": "1"})
        sessions = self._request("GET", f"/api/v1/sessions?{qs}")
        items = sessions if isinstance(sessions, list) else []
        match = next((s for s in items if isinstance(s, dict) and s.get("name") == name), None)
        if match is None:
            raise LangSmithApiError(
                f'LangSmith project "{name}" not found. Check LANGSMITH_PROJECT '
                "(it must match the Langsmith-Project OTLP header).",
                404,
            )
        tenant = match.get("tenant_id")
        return LangSmithProject(id=match["id"], tenant_id=tenant if isinstance(tenant, str) and tenant else None)

    def resolve_project_id(self, name: str | None = None) -> str:
        """Resolve the tracing project (tracer session) id by exact name."""
        return self.resolve_project(name).id

    def query_runs(
        self,
        project_id: str,
        min_start_time: datetime,
        max_start_time: datetime | None = None,
        is_root: bool | None = None,
        filter: str | None = None,  # noqa: A002 - mirrors the API field name
        page_size: int | None = None,
    ) -> Iterator[list[LangSmithRun]]:
        """Cursor-paginated /api/v2/runs/query; yields one page of runs at a time."""
        cursor: str | None = None
        while True:
            body: dict[str, Any] = {
                "project_ids": [project_id],
                "min_start_time": iso_utc(min_start_time),
                "max_start_time": iso_utc(max_start_time or _now()),
                "selects": list(RUN_SELECTS),
                "page_size": page_size if page_size is not None else 1000,
            }
            if is_root is not None:
                body["is_root"] = is_root
            if filter:
                body["filter"] = filter
            if cursor:
                body["cursor"] = cursor
            page = self._request("POST", "/api/v2/runs/query", body)
            page = page if isinstance(page, dict) else {}
            yield page.get("items") or []
            cursor = page.get("next_cursor") or None
            if not cursor:
                break

    def fetch_runs_in_window(self, project_id: str, start: datetime, end: datetime | None = None) -> list[LangSmithRun]:
        """All runs (roots + children) started in [start, end), fetched in <=7-day slices.

        Stays in the short-window rate-limit tier. Returned flat; group into turns with
        `map_runs_to_turns`.
        """
        seen: dict[str, LangSmithRun] = {}
        for lo, hi in slice_window(start, end or _now()):
            for page in self.query_runs(project_id, lo, hi):
                for run in page:
                    seen[run["id"]] = run
        return list(seen.values())
