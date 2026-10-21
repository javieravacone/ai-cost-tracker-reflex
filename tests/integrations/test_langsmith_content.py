"""Port of src/lib/langsmith/content.test.ts.

Content extraction against one real, sanitized Copilot 0.69 turn captured with content on
(F3, 2026-10-21): home dir -> /home/user, host -> HOST, big prompts and file reads shortened.
"""

from __future__ import annotations

import json
import re
from typing import Any

import pytest

from bis_core.content_types import summarize_args
from bis_core.langsmith.content import (
    LIMITS,
    SKILL_PATH,
    ExtractedContent,
    extract_turn_content,
    node_text,
    skill_from_tool_run,
    skill_version,
    tool_result_text,
    truncate,
)
from bis_core.langsmith.map import map_runs_to_turns
from bis_core.types import SkillUse

from .conftest import CONTENT_FIXTURE, load_fixture

ROOT = "00000000-0000-0000-91c4-a4cc1c3ff57c"


def test_sanitized_fixture_contains_no_secrets_nor_the_real_home_dir_or_host() -> None:
    raw = CONTENT_FIXTURE.read_text(encoding="utf-8")
    assert not re.search(r"lsv2_|gho_|ghp_|github_pat_", raw)
    assert not re.search(r"javie_verdecia|DESKTOP-", raw)


@pytest.fixture(scope="module")
def runs() -> list[dict[str, Any]]:
    return load_fixture(CONTENT_FIXTURE)


@pytest.fixture(scope="module")
def extracted(runs: list[dict[str, Any]]) -> ExtractedContent:
    return extract_turn_content(runs)


class TestExtractTurnContentOnARealCapturedTurn:
    def test_yields_one_turn_keyed_like_map_runs_to_turns(self, runs: list[dict[str, Any]], extracted: ExtractedContent) -> None:
        assert len(extracted.contents) == 1
        assert extracted.contents[0].turn_id == ROOT
        assert [t.id for t in map_runs_to_turns(runs)] == [ROOT]

    def test_reads_the_user_prompt_and_the_final_answer(self, extracted: ExtractedContent) -> None:
        c = extracted.contents[0]
        assert c.user_prompt == "Resume qué hace src/lib/sync sin modificar nada"
        assert c.final_answer is not None and c.final_answer.startswith("`src/lib/sync` trae datos externos")
        assert c.user_prompt_truncated is False
        assert c.final_answer_truncated is False
        assert c.error is None
        assert c.feedback_stats is None

    def test_detects_the_skill_from_the_skill_md_read_versioned_by_the_text_read(self, extracted: ExtractedContent) -> None:
        assert extracted.contents[0].skills == [
            SkillUse(
                name="cost-tracker-guide",
                version="ecfcda53",
                path="/home/user/code/ai-cost-tracker/.github/skills/cost-tracker-guide/SKILL.md",
            )
        ]

    def test_orders_the_agent_steps_by_start_time(self, extracted: ExtractedContent) -> None:
        events = extracted.events
        assert [f"{e.seq}:{e.kind}:{e.name}" for e in events] == [
            "0:tool:manage_todo_list",
            "1:llm:chat gpt-6-luna",
            "2:tool:read_file",
            "3:tool:read_file",
            "4:tool:read_file",
            "5:tool:read_file",
            "6:tool:read_file",
            "7:llm:chat gpt-6-luna",
        ]
        first_llm = events[1]
        assert (first_llm.tokens_in, first_llm.tokens_out, first_llm.nano_aiu, first_llm.args, first_llm.result) == (
            46857,
            342,
            71_608_500,
            None,
            None,
        )
        assert first_llm.text is not None and first_llm.text.startswith("Voy a recorrer los módulos")
        assert "read_file" in first_llm.tool_calls
        last = events[7]
        assert (last.tokens_in, last.tokens_out, last.nano_aiu, last.tool_calls) == (52245, 562, 142_334_000, [])

        todo = events[0]
        assert todo.result == "No todo list found."
        assert todo.args is not None and json.loads(todo.args)["operation"] == "read"

        skill_read = next(e for e in events if e.args and "SKILL.md" in e.args)
        assert skill_read.result is not None and skill_read.result.startswith("---\nname: cost-tracker-guide\n")
        assert skill_read.result_truncated is False
        assert all(e.turn_id == ROOT and e.trace_id == ROOT for e in events)

    def test_sums_the_same_per_turn_tokens_as_the_turn_mapping(self, runs: list[dict[str, Any]], extracted: ExtractedContent) -> None:
        t = map_runs_to_turns(runs)[0]
        llm = [e for e in extracted.events if e.kind == "llm"]
        assert sum(e.tokens_in or 0 for e in llm) == t.input_tokens
        assert sum(e.nano_aiu or 0 for e in llm) == t.copilot_nano_aiu
        assert t.tool_calls == 6


def run(**over: Any) -> dict[str, Any]:
    return {"id": "r", **over}


class TestHelpers:
    def test_concatenates_text_leaves_in_document_order(self) -> None:
        assert node_text({"children": [{"text": "a\n", "children": []}, {"children": [{"text": "b"}, {"text": "c"}]}]}) == "a\nbc"
        assert tool_result_text({"result": "plain"}) == "plain"
        assert tool_result_text(None) is None

    def test_truncates_with_a_flag_and_never_splits_a_surrogate_pair(self) -> None:
        assert truncate("abc", 5) == ("abc", False)
        assert truncate("abcdef", 3) == ("abc", True)
        assert truncate("ab😀", 3) == ("ab", True)

    def test_caps_long_tool_results_and_arguments_for_storage(self) -> None:
        big = "x" * (LIMITS.result + 10)
        events = extract_turn_content(
            [
                run(id="t", name="invoke_agent GitHub Copilot Chat", run_type="chain"),
                run(id="k", name="read_file", run_type="tool", parent_run_ids=["t"], inputs={"q": "y" * 5000}, outputs={"result": big}),
            ]
        ).events
        assert events[0].result_truncated is True
        assert events[0].args_truncated is True
        assert len(events[0].result or "") == LIMITS.result
        assert len(events[0].args or "") == LIMITS.args

    def test_matches_repo_and_user_skill_folders_windows_paths_included(self) -> None:
        def name(p: str) -> str | None:
            m = SKILL_PATH.search(p)
            return m.group(2) if m else None

        assert name("/r/.github/skills/a/SKILL.md") == "a"
        assert name("/home/u/.copilot/skills/b/SKILL.md") == "b"
        assert name("/r/.claude/skills/c/SKILL.md") == "c"
        assert name("/r/docs/skills/c/SKILL.md") is None
        win = skill_from_tool_run(run(inputs={"filePath": "C:\\r\\.agents\\skills\\d\\SKILL.md"}, outputs={"result": "x\r\ny"}))
        assert win is not None and (win.name, win.version) == ("d", skill_version("x\ny"))
        assert skill_from_tool_run(run(inputs={"filePath": "/r/README.md"})) is None
        legacy = skill_from_tool_run(run(metadata={"otel.span.github.copilot.tool.parameters.skill_name": "legacy"}))
        assert legacy == SkillUse(name="legacy", version=None, path=None)

    def test_reports_the_first_error_and_falls_back_to_the_last_model_text_for_the_answer(self) -> None:
        contents = extract_turn_content(
            [
                run(id="t", name="invoke_agent X", run_type="chain", start_time="2026-10-21T07:00:00Z", metadata={"otel.span.copilot_chat.user_request": "do it"}),
                run(id="a", name="chat m", run_type="llm", parent_run_ids=["t"], start_time="2026-10-21T07:00:01Z", outputs={"messages": [{"role": "assistant", "content": "partial"}]}),
                run(id="b", name="run_in_terminal", run_type="tool", parent_run_ids=["t"], start_time="2026-10-21T07:00:02Z", status="error", error="exit 1"),
            ]
        ).contents
        c = contents[0]
        assert (c.user_prompt, c.final_answer, c.error) == ("do it", "partial", "run_in_terminal: exit 1")

    def test_summarizes_tool_arguments_in_one_line(self) -> None:
        assert (
            summarize_args('{"filePath":"/home/user/code/app/src/lib/sync/index.ts","startLine":1,"endLine":280}')
            == "…/src/lib/sync/index.ts:1-280"
        )
        assert summarize_args('{"query":"inferIssue","includePattern":"src/**","isRegexp":true}') == "“inferIssue” in src/**"
        assert summarize_args('{"operation":"read"}') == "read"
        assert summarize_args("not json") == "not json"
        assert summarize_args(None) is None
