"""Tiny, dependency-free Markdown subset parser for assistant answers (port of src/lib/markdown.ts).

It returns a plain AST (dicts, the same shape as the TS version) that the UI renders as
components, so raw content is never injected as HTML. Supported: paragraphs, ATX headings,
fenced code, bullet/numbered lists, block quotes, rules, pipe tables, inline code, **bold**,
*italic* and [links](url).

Inline nodes:
  {"t": "text", "v": str} | {"t": "code", "v": str} | {"t": "strong", "c": [Inline]}
  | {"t": "em", "c": [Inline]}
  | {"t": "link", "href": str | None, "target": str, "c": [Inline]}  (href None when unsafe)
Block nodes:
  {"t": "p", "c": [Inline]} | {"t": "h", "level": int, "c": [Inline]}
  | {"t": "code", "lang": str | None, "v": str} | {"t": "ul", "items": [[Inline]]}
  | {"t": "ol", "start": int, "items": [[Inline]]} | {"t": "quote", "c": [Inline]}
  | {"t": "hr"} | {"t": "table", "head": [[Inline]], "rows": [[[Inline]]]}
"""

from __future__ import annotations

import re
from typing import Any

Inline = dict[str, Any]
Block = dict[str, Any]

_SAFE_HREF = re.compile(r"(https?://|mailto:)", re.IGNORECASE)


def safe_href(url: str) -> str | None:
    """Only absolute http(s) and mailto links are clickable."""
    u = url.strip()
    return u if _SAFE_HREF.match(u) else None


# JS `\w` is ASCII-only; spelled out explicitly here.
_INLINE = re.compile(
    r"(`+)([\s\S]*?[^`])\1(?!`)"
    r"|\*\*(?=\S)([\s\S]*?\S)\*\*"
    r"|(?<![A-Za-z0-9_*])\*(?=\S)([^*\n]*?\S)\*(?![A-Za-z0-9_*])"
    r"|\[([^\]\n]+)\]\(([^)\s]+)\)"
)


def parse_inline(src: str) -> list[Inline]:
    out: list[Inline] = []
    last = 0

    def push(v: str) -> None:
        if not v:
            return
        if out and out[-1]["t"] == "text":
            out[-1]["v"] += v
        else:
            out.append({"t": "text", "v": v})

    for m in _INLINE.finditer(src):
        push(src[last : m.start()])
        if m.group(1):
            code = m.group(2)
            out.append({"t": "code", "v": code[1:-1] if len(code) > 2 and code.startswith(" ") and code.endswith(" ") else code})
        elif m.group(3) is not None:
            out.append({"t": "strong", "c": parse_inline(m.group(3))})
        elif m.group(4) is not None:
            out.append({"t": "em", "c": parse_inline(m.group(4))})
        else:
            out.append({"t": "link", "href": safe_href(m.group(6)), "target": m.group(6), "c": parse_inline(m.group(5))})
        last = m.end()
    push(src[last:])
    return out


_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})\s*([A-Za-z0-9_+#.-]*)")
_HEADING = re.compile(r"^ {0,3}(#{1,6})\s+(.*?)\s*#*\s*\Z")
_BULLET = re.compile(r"^\s*[-*+]\s+(.*)\Z")
_NUMBERED = re.compile(r"^\s*([0-9]{1,9})[.)]\s+(.*)\Z")
_RULE = re.compile(r"^ {0,3}([-*_])(\s*\1){2,}\s*\Z")
_TABLE_SEP = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*\Z")
_QUOTE = re.compile(r"^\s*>")
_QUOTE_PREFIX = re.compile(r"^\s*>\s?")
_CONTINUATION = re.compile(r"^\s+\S")


def _cells(line: str) -> list[list[Inline]]:
    s = line.strip()
    s = re.sub(r"^\|", "", s, count=1)
    s = re.sub(r"\|\Z", "", s, count=1)
    return [parse_inline(c.strip()) for c in s.split("|")]


def parse_markdown(src: str) -> list[Block]:
    lines = re.sub(r"\r\n?", "\n", src).split("\n")
    blocks: list[Block] = []
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        if not line.strip():
            i += 1
            continue
        fence = _FENCE.match(line)
        if fence:
            marker = fence.group(1)
            close = re.compile(rf"^ {{0,3}}{re.escape(marker[0])}{{{len(marker)},}}\s*\Z")
            body: list[str] = []
            i += 1
            while i < n and not close.match(lines[i]):
                body.append(lines[i])
                i += 1
            i += 1  # closing fence (or end of input)
            blocks.append({"t": "code", "lang": fence.group(2) or None, "v": "\n".join(body)})
            continue
        h = _HEADING.match(line)
        if h:
            blocks.append({"t": "h", "level": len(h.group(1)), "c": parse_inline(h.group(2))})
            i += 1
            continue
        if _RULE.match(line):
            blocks.append({"t": "hr"})
            i += 1
            continue
        if "|" in line and i + 1 < n and _TABLE_SEP.match(lines[i + 1]):
            head = _cells(line)
            rows: list[list[list[Inline]]] = []
            i += 2
            while i < n and "|" in lines[i] and lines[i].strip():
                rows.append(_cells(lines[i]))
                i += 1
            blocks.append({"t": "table", "head": head, "rows": rows})
            continue
        kind = "ul" if _BULLET.match(line) else "ol" if _NUMBERED.match(line) else None
        if kind:
            rx = _BULLET if kind == "ul" else _NUMBERED
            items: list[str] = []
            start = int(_NUMBERED.match(line).group(1)) if kind == "ol" else 1  # type: ignore[union-attr]
            while i < n and lines[i].strip():
                m = rx.match(lines[i])
                if m:
                    items.append(m.group(1) if kind == "ul" else m.group(2))
                elif _CONTINUATION.match(lines[i]) and items:
                    items[-1] += f" {lines[i].strip()}"
                else:
                    break
                i += 1
            parsed = [parse_inline(x) for x in items]
            blocks.append({"t": "ul", "items": parsed} if kind == "ul" else {"t": "ol", "start": start, "items": parsed})
            continue
        if _QUOTE.match(line):
            body = []
            while i < n and _QUOTE.match(lines[i]):
                body.append(_QUOTE_PREFIX.sub("", lines[i], count=1))
                i += 1
            blocks.append({"t": "quote", "c": parse_inline(" ".join(body))})
            continue
        para: list[str] = []
        while (
            i < n
            and lines[i].strip()
            and not _FENCE.match(lines[i])
            and not _HEADING.match(lines[i])
            and not _BULLET.match(lines[i])
            and not _NUMBERED.match(lines[i])
            and not _QUOTE.match(lines[i])
        ):
            para.append(lines[i].strip())
            i += 1
        if not para:
            para.append(line.strip())
            i += 1
        blocks.append({"t": "p", "c": parse_inline(" ".join(para))})
    return blocks
