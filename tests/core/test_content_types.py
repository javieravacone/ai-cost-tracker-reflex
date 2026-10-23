"""Tests for bis_core.content_types (expected values produced by the TS helpers on Node 24)."""

from __future__ import annotations

import json

from bis_core.content_types import has_captured_content, summarize_args
from bis_core.types import TurnContent

CASES = [
    None,
    "",
    "not json",
    "[1,2]",
    "42",
    '{"filePath":"/a/b/c/d/e/f.ts","startLine":3,"endLine":9}',
    '{"query":"foo","includePattern":"src/**"}',
    '{"command":"npm test"}',
    '{"2":"two","b":"bee","1":"one"}',
    '{"x":1}',
    json.dumps({"command": "y" * 120}),
    '{"path":"C:\\\\a\\\\b\\\\c\\\\d\\\\e.ts"}',
]
EXPECTED = [
    None,
    None,
    "not json",
    "[1,2]",
    "42",
    "…/c/d/e/f.ts:3-9",
    "“foo” in src/**",
    "npm test",
    "one",  # Object.values: integer-like keys first, ascending
    None,
    "y" * 89 + "…",
    "…/b/c/d/e.ts",
]


def test_summarize_args_matches_ts():
    assert [summarize_args(c) for c in CASES] == EXPECTED


def test_has_captured_content():
    assert has_captured_content(None) is False
    assert has_captured_content({"user_prompt": "", "final_answer": None}) is False
    assert has_captured_content({"user_prompt": "x", "final_answer": None}) is True
    content = TurnContent(turn_id="t", user_prompt=None, user_prompt_truncated=False, final_answer="ok", final_answer_truncated=False, error=None)
    assert has_captured_content(content) is True
