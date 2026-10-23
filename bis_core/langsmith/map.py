"""Pure mapping: LangSmith runs (Copilot Chat OTel spans ingested by LangSmith) -> list[Turn].

Port of ai-cost-tracker src/lib/langsmith/map.ts. Attribute locations were verified against real
runs in T1 (see the comment above `K`). Fields are still looked up across several locations via
`pick()` so that other Copilot/LangSmith versions keep working.

A run is a plain dict (the JSON item returned by `/api/v2/runs/query`, also tolerant of v1).
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from bis_core.types import Turn

LangSmithRun = dict[str, Any]

_MISSING = object()


def _coalesce(*values: Any) -> Any:
    """JavaScript `a ?? b`: first value that is not None."""
    return next((v for v in values if v is not None), None)


def _is_obj(v: Any) -> bool:
    return isinstance(v, dict)


def _get_path(obj: Any, parts: list[str]) -> Any:
    cur = obj
    for p in parts:
        if not _is_obj(cur):
            return None
        cur = cur.get(p, _MISSING)
        if cur is _MISSING:
            return None
    return cur


def _lookup(obj: Any, key: str, underscore_variant: bool) -> Any:
    """Look up `key` in `obj` as a flat key, underscore variant, or nested dotted path."""
    if not _is_obj(obj):
        return None
    if key in obj:
        return obj[key]
    if underscore_variant:
        underscored = key.replace(".", "_")
        if underscored in obj:
            return obj[underscored]
    return _get_path(obj, key.split("."))


def _sources(run: LangSmithRun) -> list[tuple[Any, bool]]:
    extra = run.get("extra")
    return [
        (run.get("metadata"), True),
        (_get_path(extra, ["metadata"]), True),
        (_get_path(extra, ["runtime"]), True),
        (_get_path(extra, ["attributes"]), True),
        (extra, True),
        (run.get("inputs"), False),
        (run.get("outputs"), False),
        # Run top level last, without the underscore variant: `project.id` must never resolve to
        # the run's own `project_id` (the LangSmith tracing project UUID).
        (run, False),
    ]


def _is_present(v: Any) -> bool:
    return v is not None and not (isinstance(v, str) and v == "")


def pick(run: LangSmithRun, keys: list[str]) -> Any:
    """First present value for the first key (in priority order) found in any location."""
    srcs = _sources(run)
    for key in keys:
        for src, underscore in srcs:
            v = _lookup(src, key, underscore)
            if _is_present(v):
                return v
    return None


def _js_number_str(v: int | float) -> str:
    if isinstance(v, float) and v.is_integer() and abs(v) < 1e21:
        return str(int(v))
    return str(v)


def pick_string(run: LangSmithRun, keys: list[str]) -> str | None:
    v = pick(run, keys)
    if isinstance(v, str):
        return v
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return _js_number_str(v)
    return None


def _normalize_number(n: int | float) -> int | float:
    if isinstance(n, float) and n.is_integer():
        return int(n)
    return n


def _to_number(v: Any) -> int | float | None:
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, float):
        return _normalize_number(v) if math.isfinite(v) else None
    if isinstance(v, str) and v.strip() != "":
        try:
            n = float(v.strip())
        except ValueError:
            return None
        return _normalize_number(n) if math.isfinite(n) else None
    return None


def pick_number(run: LangSmithRun, keys: list[str]) -> int | float | None:
    for key in keys:
        n = _to_number(pick(run, [key]))
        if n is not None:
            return n
    return None


# --- attribute key candidates (priority order) ---------------------------------------------

# VERIFIED (T1, 2026-10-16, Copilot Chat 0.69.0 -> LangSmith EU, trace schema "coding-agent-v1"):
# LangSmith stores span attributes as flat `metadata["otel.span.<attr>"]` and resource attributes
# as `metadata["otel.resource.<attr>"]`, plus its own normalized copies (`git_branch`,
# `git_commit_sha`, `repository_url`, `conversation_id`, `agent_name`, `ls_model_name`). The
# `invoke_agent` root carries NO token counts: they live on the child `chat <model>` runs as
# top-level `prompt_tokens` (includes cached), `completion_tokens`,
# `prompt_token_details.raw.cache_read` and `completion_token_details.raw.reasoning`.
# The verified keys go first; the older guesses stay as fallbacks for other versions.


def _span(k: str) -> str:
    return f"otel.span.{k}"


def _resource(k: str) -> str:
    return f"otel.resource.{k}"


class K:
    """Attribute key candidates per field (priority order; also used by the content extractor)."""

    operation = [_span("gen_ai.operation.name"), "gen_ai.operation.name"]
    agent_name = [_span("gen_ai.agent.name"), "agent_name", "gen_ai.agent.name"]
    conversation_id = [
        _span("gen_ai.conversation.id"),
        "conversation_id",
        _span("copilot_chat.session_id"),
        "gen_ai.conversation.id",
        "thread_id",
    ]
    request_model = ["gen_ai.request.model"]
    response_model = ["gen_ai.response.model"]
    model = [
        _span("gen_ai.response.model"),
        _span("gen_ai.request.model"),
        "gen_ai.response.model",
        "gen_ai.request.model",
        "invocation_params.model",
        "ls_model_name",
    ]
    repo = [
        _span("github.copilot.git.repository"),
        "repository_url",
        _span("copilot_chat.repo.remote_url"),
        "github.copilot.git.repository",
        "copilot_chat.repo.remote_url",
    ]
    branch = [
        _span("github.copilot.git.branch"),
        "git_branch",
        _span("copilot_chat.repo.head_branch_name"),
        "github.copilot.git.branch",
        "copilot_chat.repo.head_branch_name",
    ]
    commit = [
        _span("github.copilot.git.commit_sha"),
        "git_commit_sha",
        _span("copilot_chat.repo.head_commit_hash"),
        "github.copilot.git.commit_sha",
        "copilot_chat.repo.head_commit_hash",
    ]
    org = [_span("github.copilot.github.org"), "github.copilot.github.org"]
    turn_count = [_span("copilot_chat.turn_count"), "copilot_chat.turn_count"]
    user_name = [_span("user.name"), _resource("user.name"), "user.name", "resource.user.name", "enduser.id"]
    team_id = [_resource("team.id"), "team.id", "resource.team.id", "resource.attributes.team.id"]
    project_id = [_resource("project.id"), "project.id", "resource.project.id", "resource.attributes.project.id"]
    input_tokens = [
        "gen_ai.usage.input_tokens",
        "usage_metadata.input_tokens",
        "gen_ai.usage.prompt_tokens",
        "prompt_tokens",
    ]
    output_tokens = [
        "gen_ai.usage.output_tokens",
        "usage_metadata.output_tokens",
        "gen_ai.usage.completion_tokens",
        "completion_tokens",
    ]
    cache_read = [
        "gen_ai.usage.cache_read.input_tokens",
        "usage_metadata.input_token_details.cache_read",
        "prompt_token_details.cache_read",
        "prompt_token_details.raw.cache_read",
    ]
    cache_creation = [
        "gen_ai.usage.cache_creation.input_tokens",
        "usage_metadata.input_token_details.cache_creation",
        "prompt_token_details.cache_creation",
        "prompt_token_details.cache_write",
        "prompt_token_details.raw.cache_creation",
        "prompt_token_details.raw.cache_write",
    ]
    # VERIFIED (T1 fixture): every `chat <model>` span carries the server-returned Copilot usage in
    # nano AI units (1 GitHub AI credit = 1e9 nano = $0.01, gross list price). Per LLM call.
    copilot_nano_aiu = [_span("copilot_chat.copilot_usage_nano_aiu"), "copilot_chat.copilot_usage_nano_aiu"]
    reasoning = [
        "gen_ai.usage.reasoning.output_tokens",
        "usage_metadata.reasoning_tokens",
        "usage_metadata.output_token_details.reasoning",
        "completion_token_details.reasoning",
        "completion_token_details.raw.reasoning",
    ]


# --- run classification ----------------------------------------------------------------------


def _lower(s: Any) -> str:
    return s.lower() if isinstance(s, str) else ""


def is_invoke_agent(run: LangSmithRun) -> bool:
    return _lower(run.get("name")).startswith("invoke_agent") or pick_string(run, K.operation) == "invoke_agent"


def is_llm_call(run: LangSmithRun) -> bool:
    if is_invoke_agent(run):
        return False
    op = pick_string(run, K.operation)
    return _lower(run.get("run_type")) == "llm" or op == "chat" or _lower(run.get("name")).startswith("chat ")


def is_tool_call(run: LangSmithRun) -> bool:
    op = pick_string(run, K.operation)
    return (
        _lower(run.get("run_type")) == "tool"
        or op == "execute_tool"
        or _lower(run.get("name")).startswith("execute_tool")
    )


def _ancestors_of(run: LangSmithRun, by_id: dict[str, LangSmithRun]) -> list[str]:
    """Ancestor run ids, root first. Uses parent_run_ids, dotted_order, or parent_run_id chain."""
    parent_ids = run.get("parent_run_ids")
    if parent_ids:
        return list(parent_ids)
    dotted = run.get("dotted_order")
    if dotted:
        ids = [seg[seg.find("Z") + 1 :] for seg in dotted.split(".")]
        ids = [i for i in ids if i]
        if len(ids) > 1:
            return ids[:-1]
    chain: list[str] = []
    seen: set[str] = set()
    parent_id = run.get("parent_run_id")
    while parent_id and parent_id not in seen:
        seen.add(parent_id)
        chain.insert(0, parent_id)
        parent = by_id.get(parent_id)
        parent_id = parent.get("parent_run_id") if parent else None
    return chain


_ZONE_RE = re.compile(r"([zZ]|[+-]\d\d:?\d\d)$")
_DATE_ONLY_Z_RE = re.compile(r"\d{4}-\d{2}-\d{2}[zZ]")


def iso_utc(dt: datetime) -> str:
    """`Date.prototype.toISOString()`: UTC, millisecond precision, trailing "Z"."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_iso(ts: str | None) -> datetime | None:
    """Parse an ISO 8601 timestamp (naive = UTC, like LangSmith v1) to an aware datetime."""
    if not ts or not isinstance(ts, str):
        return None
    with_zone = ts if _ZONE_RE.search(ts) else f"{ts}Z"
    if _DATE_ONLY_Z_RE.fullmatch(with_zone):  # "2026-10-01Z": valid in JS, not for fromisoformat
        with_zone = f"{with_zone[:-1]}T00:00:00Z"
    try:
        d = datetime.fromisoformat(with_zone)
    except ValueError:
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.astimezone(timezone.utc)


def to_iso(ts: str | None) -> str | None:
    """LangSmith v1 returns naive UTC timestamps (no "Z"); normalize to ISO 8601."""
    d = parse_iso(ts)
    return iso_utc(d) if d else None


# --- mapping -----------------------------------------------------------------------------------


@dataclass
class TurnRuns:
    """A turn root (`invoke_agent`) with every run of its subtree (any depth, any order)."""

    root: LangSmithRun
    kids: list[LangSmithRun]


def map_runs_to_turns(runs: list[LangSmithRun]) -> list[Turn]:
    """Map a flat list of runs (roots and children, any order, possibly several traces) to turns.

    A turn is an `invoke_agent` run without an `invoke_agent` ancestor; every other run in the
    same subtree (including nested subagent `invoke_agent` runs) counts towards that turn.
    """
    turns = [_build_turn(g.root, g.kids) for g in group_turn_runs(runs)]
    return sorted(turns, key=lambda t: t.started_at)


def group_turn_runs(runs: list[LangSmithRun]) -> list[TurnRuns]:
    """Groups a flat run list into turns (same rules as `map_runs_to_turns`)."""
    by_id = {r["id"]: r for r in runs}
    ancestors = {r["id"]: _ancestors_of(r, by_id) for r in runs}

    def has_agent_ancestor(r: LangSmithRun) -> bool:
        for a in ancestors.get(r["id"], []):
            ar = by_id.get(a)
            if ar is not None and is_invoke_agent(ar):
                return True
        return False

    turn_roots = [r for r in runs if is_invoke_agent(r) and not has_agent_ancestor(r)]
    turn_ids = {r["id"] for r in turn_roots}
    turns_by_trace: dict[str, list[str]] = {}
    for r in turn_roots:
        t = _coalesce(r.get("trace_id"), r["id"])
        turns_by_trace.setdefault(t, []).append(r["id"])

    children: dict[str, list[LangSmithRun]] = {r["id"]: [] for r in turn_roots}
    for r in runs:
        if r["id"] in turn_ids:
            continue
        anc = ancestors.get(r["id"], [])
        owner = next((a for a in anc if a in turn_ids), None)
        if owner is None and len(anc) == 0 and not r.get("parent_run_id"):
            continue  # unrelated root
        if owner is None:
            # No usable ancestry: fall back to the single turn of its trace, if unambiguous.
            same_trace = turns_by_trace.get(_coalesce(r.get("trace_id"), ""), [])
            if len(same_trace) == 1:
                owner = same_trace[0]
        if owner is not None:
            children[owner].append(r)

    return [TurnRuns(root=root, kids=children.get(root["id"], [])) for root in turn_roots]


def _sum_children(kids: list[LangSmithRun], keys: list[str]) -> int | float:
    return sum((pick_number(k, keys) or 0) for k in kids)


def _copilot_usage(root: LangSmithRun, llm_kids: list[LangSmithRun]) -> tuple[int | None, float | None]:
    """Real Copilot usage of a turn: sum over child `chat` runs that report it.

    Unknown (None) when none reports it; coverage is the share of chat runs that did (None
    without chat runs). Without chat runs, a value on the root is used.
    """
    if not llm_kids:
        v = pick_number(root, K.copilot_nano_aiu)
        return (v if v is not None and v >= 0 else None), None
    nano: int | float = 0
    reported = 0
    for k in llm_kids:
        v = pick_number(k, K.copilot_nano_aiu)
        if v is None or v < 0:
            continue
        nano += v
        reported += 1
    return (nano if reported > 0 else None), reported / len(llm_kids)


def _build_turn(root: LangSmithRun, kids: list[LangSmithRun]) -> Turn:
    llm_kids = [k for k in kids if is_llm_call(k)]
    tool_kids = [k for k in kids if is_tool_call(k)]

    # Prefer the usage on the invoke_agent span (Copilot aggregates it there); otherwise sum the
    # child `chat` spans. Never add both (LangSmith may also roll child tokens up into the parent).
    # A zero on the root (e.g. LangSmith's default prompt_tokens=0) falls through to the children.
    def root_or_kids(keys: list[str]) -> Any:
        v = pick_number(root, keys)
        return v if v is not None and v > 0 else _sum_children(llm_kids, keys)

    child_model = next((m for m in (pick_string(k, K.model) for k in llm_kids) if m), None)
    turn_count = pick_number(root, K.turn_count)
    nano, coverage = _copilot_usage(root, llm_kids)

    return Turn(
        id=root["id"],
        trace_id=_coalesce(root.get("trace_id"), root["id"]),
        conversation_id=_coalesce(pick_string(root, K.conversation_id), root.get("thread_id")),
        started_at=to_iso(root.get("start_time")) or "1970-01-01T00:00:00.000Z",
        ended_at=to_iso(root.get("end_time")),
        user_name=pick_string(root, K.user_name),
        team_id=pick_string(root, K.team_id),
        project_hint=pick_string(root, K.project_id),
        repo_url=pick_string(root, K.repo),
        branch=pick_string(root, K.branch),
        commit_sha=pick_string(root, K.commit),
        github_org=pick_string(root, K.org),
        agent_name=pick_string(root, K.agent_name) or _agent_from_name(root.get("name")),
        model=pick_string(root, K.model) or child_model,
        input_tokens=root_or_kids(K.input_tokens),
        output_tokens=root_or_kids(K.output_tokens),
        cache_read_tokens=root_or_kids(K.cache_read),
        cache_creation_tokens=root_or_kids(K.cache_creation),
        reasoning_tokens=root_or_kids(K.reasoning),
        llm_calls=len(llm_kids) if llm_kids else (turn_count if turn_count is not None else 0),
        tool_calls=len(tool_kids),
        copilot_nano_aiu=nano,
        copilot_usage_coverage=coverage,
        source="langsmith",
    )


_AGENT_NAME_RE = re.compile(r"invoke_agent\s+(.+)")


def _agent_from_name(name: Any) -> str | None:
    m = _AGENT_NAME_RE.fullmatch(name if isinstance(name, str) else "")
    return m.group(1).strip() if m else None
