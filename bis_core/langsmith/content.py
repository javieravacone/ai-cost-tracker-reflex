"""Pure extraction of captured Copilot content from LangSmith runs (port of content.ts).

F3 shapes, 2026-10-21:
- `invoke_agent` root: inputs.messages[0].content[].text = user prompt; outputs.messages = answer.
- `chat <model>` (llm): outputs.messages[].content[].text + tool_calls[].function.name.
- tool runs: inputs = arguments; outputs.node = nested tree whose `text` leaves (document order)
  hold the result, or outputs.result as a plain string.
- Skills: no attribute. A skill is used when a tool reads `<dir>/skills/<name>/SKILL.md`.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any

from bis_core.langsmith.map import (
    K,
    LangSmithRun,
    group_turn_runs,
    is_llm_call,
    is_tool_call,
    parse_iso,
    pick_number,
    pick_string,
    to_iso,
)
from bis_core.types import SkillUse, TurnContent, TurnEvent


class LIMITS:
    """Storage caps (characters, UTF-16 units like the TS app). Truncated values keep a flag."""

    prompt = 32_000
    answer = 32_000
    text = 16_000
    args = 4_096
    result = 8_192
    error = 2_000


def _is_obj(v: Any) -> bool:
    return isinstance(v, dict)


def _js_jsonable(v: Any) -> Any:
    """Integral floats become ints so the output matches `JSON.stringify` (1.0 -> 1)."""
    if isinstance(v, float) and v.is_integer() and abs(v) < 1e21:
        return int(v)
    if isinstance(v, dict):
        return {k: _js_jsonable(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_js_jsonable(x) for x in v]
    return v


def js_stringify(v: Any) -> str:
    """Compact JSON identical to JavaScript's `JSON.stringify` for JSON-parsed values."""
    return json.dumps(_js_jsonable(v), ensure_ascii=False, separators=(",", ":"))


def _utf16_len(s: str) -> int:
    return len(s) + sum(1 for c in s if ord(c) > 0xFFFF)


def truncate(s: str | None, max_len: int) -> tuple[str | None, bool]:
    """Cut to `max_len` UTF-16 units without splitting a surrogate pair. Returns (value, truncated)."""
    if s is None or _utf16_len(s) <= max_len:
        return s, False
    units = 0
    end = 0
    for c in s:
        w = 2 if ord(c) > 0xFFFF else 1
        if units + w > max_len:
            break
        units += w
        end += 1
    return s[:end], True


def node_text(node: Any) -> str:
    """Concatenation of every `text` leaf of a prompt-tsx style node tree, in document order."""
    out: list[str] = []

    def walk(n: Any) -> None:
        if isinstance(n, list):
            for x in n:
                walk(x)
            return
        if not _is_obj(n):
            return
        if isinstance(n.get("text"), str):
            out.append(n["text"])
        if "children" in n and n["children"] is not None:
            walk(n["children"])

    walk(node)
    return "".join(out)


def _content_text(content: Any) -> str:
    """Text of a chat message `content`: a string or a list of `{type: "text", text}` parts."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for p in content:
            if isinstance(p, str):
                parts.append(p)
            elif _is_obj(p) and isinstance(p.get("text"), str):
                parts.append(p["text"])
        return "\n".join(p for p in parts if p)
    return ""


def _messages_of(io: Any) -> list[dict[str, Any]]:
    m = io.get("messages") if _is_obj(io) else None
    return [x for x in m if _is_obj(x)] if isinstance(m, list) else []


def _messages_text(io: Any, role: str | None = None) -> str | None:
    texts = [
        _content_text(m.get("content"))
        for m in _messages_of(io)
        if not role or "role" not in m or m["role"] == role
    ]
    text = "\n\n".join(t for t in texts if t)
    return text or None


def _tool_call_names(io: Any) -> list[str]:
    names: list[str] = []
    for m in _messages_of(io):
        calls = m.get("tool_calls")
        if not isinstance(calls, list):
            continue
        for tc in calls:
            name = None
            if _is_obj(tc):
                name = tc["function"].get("name") if _is_obj(tc.get("function")) else tc.get("name")
            if isinstance(name, str) and name:
                names.append(name)
    return names


def tool_result_text(outputs: Any) -> str | None:
    """Plain-text result of a tool run."""
    if outputs is None:
        return None
    if isinstance(outputs, str):
        return outputs or None
    if not _is_obj(outputs):
        return js_stringify(outputs)
    if isinstance(outputs.get("result"), str):
        return outputs["result"]
    if "node" in outputs:
        t = node_text(outputs["node"])
        if t:
            return t
    if isinstance(outputs.get("output"), str):
        return outputs["output"]
    return js_stringify(outputs) if outputs else None


def _error_text(run: LangSmithRun) -> str | None:
    e = run.get("error")
    if isinstance(e, str) and e.strip():
        return e.strip()
    if _is_obj(e):
        return e["message"] if isinstance(e.get("message"), str) else js_stringify(e)
    status = run.get("status")
    if isinstance(status, str) and status.lower() == "error":
        return "error"
    return None


def _duration_ms(run: LangSmithRun) -> int | None:
    s = to_iso(run.get("start_time"))
    e = to_iso(run.get("end_time"))
    if not s or not e:
        return None
    start, end = parse_iso(s), parse_iso(e)
    assert start is not None and end is not None
    d = round((end - start).total_seconds() * 1000)
    return d if d >= 0 else None


# --- skills ---------------------------------------------------------------------------------

# `<repo or home>/{.github,.claude,.agents,.copilot}/skills/<name>/SKILL.md`
SKILL_PATH = re.compile(r"(?:^|/)(\.github|\.claude|\.agents|\.copilot)/skills/([^/]+)/SKILL\.md\Z", re.IGNORECASE)

_LEGACY_SKILL_KEYS = [
    "otel.span.github.copilot.tool.parameters.skill_name",
    "github.copilot.tool.parameters.skill_name",
]


def skill_version(text: str) -> str:
    """Short content hash used as the skill version (line endings normalized)."""
    normalized = re.sub(r"\r\n?", "\n", text)
    # Lone surrogates become U+FFFD, as Node's UTF-8 encoder does.
    data = normalized.encode("utf-16", "surrogatepass").decode("utf-16", "replace").encode("utf-8")
    return hashlib.sha256(data).hexdigest()[:8]


def _strings(v: Any, out: list[str] | None = None) -> list[str]:
    """Every string value in `v` (any depth)."""
    if out is None:
        out = []
    if isinstance(v, str):
        out.append(v)
    elif isinstance(v, list):
        for x in v:
            _strings(x, out)
    elif _is_obj(v):
        for x in v.values():
            _strings(x, out)
    return out


def skill_from_tool_run(run: LangSmithRun) -> SkillUse | None:
    """Skill read by a tool run (path match on its arguments), with the version of the text read."""
    for raw in _strings(run.get("inputs")):
        path = raw.replace("\\", "/")
        if path.startswith("file://"):
            path = path[len("file://") :]
        m = SKILL_PATH.search(path)
        if not m:
            continue
        text = None if _error_text(run) else tool_result_text(run.get("outputs"))
        return SkillUse(name=m.group(2), version=skill_version(text) if text else None, path=raw)
    legacy = pick_string(run, _LEGACY_SKILL_KEYS)
    return SkillUse(name=legacy, version=None, path=None) if legacy else None


def _unique_skills(skills: list[SkillUse]) -> list[SkillUse]:
    seen: dict[tuple[str, str], SkillUse] = {}
    for s in skills:
        seen.setdefault((s.name, s.version or ""), s)
    values = list(seen.values())
    # A versioned read makes an unversioned mention of the same skill redundant.
    return [s for s in values if s.version is not None or not any(o.name == s.name and o.version for o in values)]


# --- turns ----------------------------------------------------------------------------------


def _by_start_key(run: LangSmithRun) -> tuple[str, str, str]:
    return (to_iso(run.get("start_time")) or "", run.get("dotted_order") or "", run["id"])


def _build_events(turn_id: str, kids: list[LangSmithRun]) -> list[TurnEvent]:
    steps = sorted((k for k in kids if is_llm_call(k) or is_tool_call(k)), key=_by_start_key)
    events: list[TurnEvent] = []
    for seq, run in enumerate(steps):
        llm = is_llm_call(run)
        text = truncate(_messages_text(run.get("outputs"), "assistant"), LIMITS.text) if llm else (None, False)
        inputs = run.get("inputs")
        args = (None, False) if llm or inputs is None else truncate(js_stringify(inputs), LIMITS.args)
        result = (None, False) if llm else truncate(tool_result_text(run.get("outputs")), LIMITS.result)
        name = run.get("name")
        events.append(
            TurnEvent(
                turn_id=turn_id,
                seq=seq,
                run_id=run["id"],
                trace_id=run.get("trace_id") if run.get("trace_id") is not None else turn_id,
                kind="llm" if llm else "tool",
                name=name if name is not None else ("chat" if llm else "tool"),
                started_at=to_iso(run.get("start_time")),
                duration_ms=_duration_ms(run),
                tokens_in=pick_number(run, K.input_tokens) if llm else None,
                tokens_out=pick_number(run, K.output_tokens) if llm else None,
                nano_aiu=pick_number(run, K.copilot_nano_aiu) if llm else None,
                text=text[0],
                text_truncated=text[1],
                tool_calls=_tool_call_names(run.get("outputs")) if llm else [],
                args=args[0],
                args_truncated=args[1],
                result=result[0],
                result_truncated=result[1],
                error=truncate(_error_text(run), LIMITS.error)[0],
            )
        )
    return events


def _build_content(root: LangSmithRun, kids: list[LangSmithRun]) -> TurnContent:
    prompt_text = _messages_text(root.get("inputs"), "user")
    if prompt_text is None:
        prompt_text = pick_string(root, ["otel.span.copilot_chat.user_request"])
    prompt = truncate(prompt_text, LIMITS.prompt)
    sorted_kids = sorted(kids, key=_by_start_key)
    llm_texts = [t for t in (_messages_text(k.get("outputs"), "assistant") for k in sorted_kids if is_llm_call(k)) if t]
    last_llm_text = llm_texts[-1] if llm_texts else None
    answer_text = _messages_text(root.get("outputs"), "assistant")
    answer = truncate(answer_text if answer_text is not None else last_llm_text, LIMITS.answer)
    failing = next((r for r in [root, *sorted_kids] if _error_text(r) is not None), None)
    error = None
    if failing is not None:
        label = "turn" if failing is root else (failing.get("name") if failing.get("name") is not None else "run")
        error = f"{label}: {_error_text(failing)}"
    skill_hits = [skill_from_tool_run(k) for k in sorted_kids if is_tool_call(k)]
    skills = _unique_skills([s for s in skill_hits if s is not None])
    feedback = root.get("feedback_stats")
    return TurnContent(
        turn_id=root["id"],
        user_prompt=prompt[0],
        user_prompt_truncated=prompt[1],
        final_answer=answer[0],
        final_answer_truncated=answer[1],
        error=truncate(error, LIMITS.error)[0],
        skills=skills,
        feedback_stats=feedback if _is_obj(feedback) and feedback else None,
    )


@dataclass
class ExtractedContent:
    contents: list[TurnContent]
    events: list[TurnEvent]


def extract_turn_content(runs: list[LangSmithRun]) -> ExtractedContent:
    """Content and ordered agent steps of every turn found in a flat run list."""
    contents: list[TurnContent] = []
    events: list[TurnEvent] = []
    for group in group_turn_runs(runs):
        contents.append(_build_content(group.root, group.kids))
        events.extend(_build_events(group.root["id"], group.kids))
    return ExtractedContent(contents=contents, events=events)

