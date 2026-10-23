"""Helpers over captured Copilot content (port of the functions in src/lib/content-types.ts).

The data types themselves (SkillUse, TurnContent, TurnEvent) live in bis_core.types.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from bis_core._js import num_str


def _js_json_loads(s: str) -> Any:
    """`JSON.parse`: like json.loads but rejects NaN / Infinity literals."""

    def bad_constant(name: str) -> Any:
        raise ValueError(f"invalid JSON constant {name}")

    return json.loads(s, parse_constant=bad_constant)


def _is_number(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _js_values(o: dict[str, Any]) -> list[Any]:
    """`Object.values` order: integer-like keys ascending first, then insertion order."""
    index_keys = sorted((k for k in o if re.fullmatch(r"0|[1-9][0-9]*", k) and int(k) < 2**32 - 1), key=int)
    index_set = set(index_keys)
    return [o[k] for k in index_keys] + [v for k, v in o.items() if k not in index_set]


def _short_path(p: str) -> str:
    parts = [x for x in p.replace("\\", "/").split("/") if x]
    return f"…/{'/'.join(parts[-4:])}" if len(parts) > 4 else p


def _clip(s: str, n: int = 90) -> str:
    return f"{s[: n - 1]}…" if len(s) > n else s


def summarize_args(args: str | None) -> str | None:
    """One-line human summary of tool arguments (file path, search query, command...)."""
    if not args:
        return None
    try:
        v = _js_json_loads(args)
    except ValueError:
        return _clip(args)
    if not isinstance(v, dict):
        return _clip(str(args))
    o = v

    def s(k: str) -> str | None:
        x = o.get(k)
        return x if isinstance(x, str) and x else None

    file = s("filePath") or s("path") or s("file") or s("uri")
    if file:
        sl, el = o.get("startLine"), o.get("endLine")
        rng = f":{num_str(sl)}-{num_str(el)}" if _is_number(sl) and _is_number(el) else ""
        return _clip(f"{_short_path(file)}{rng}")
    query = s("query") or s("pattern") or s("search")
    if query:
        scope = s("includePattern")
        return _clip(f"“{query}”" + (f" in {scope}" if scope else ""))
    command = s("command") or s("url") or s("operation")
    if command:
        return _clip(command)
    first = next((x for x in _js_values(o) if isinstance(x, str) and len(x) > 0), None)
    return _clip(first) if first else None


@dataclass
class FileRef:
    path: str
    start: int | None
    end: int | None


def args_file_ref(args: str | None) -> FileRef | None:
    """File path (and line range) a tool call targeted, from its JSON arguments; None when none."""
    if not args:
        return None
    try:
        v = _js_json_loads(args)
    except ValueError:
        return None
    if not isinstance(v, dict):
        return None
    o = v
    path = next((x for x in (o.get(k) for k in ("filePath", "path", "file", "uri")) if isinstance(x, str) and x), None)
    if not path:
        return None

    def num(k: str) -> int | None:
        x = o.get(k)
        return int(x) if _is_number(x) and float(x).is_integer() else None

    return FileRef(path=path, start=num("startLine"), end=num("endLine"))


def has_captured_content(c: Any) -> bool:
    """True when the turn carries real captured content (not just step metadata).
    Accepts a TurnContent, any object with user_prompt / final_answer, a mapping, or None."""
    if not c:
        return False
    if isinstance(c, Mapping):
        return bool(c.get("user_prompt") or c.get("final_answer"))
    return bool(getattr(c, "user_prompt", None) or getattr(c, "final_answer", None))
