"""Port of src/lib/langsmith/map.real.test.ts.

Real runs captured in T1 (Copilot Chat 0.69.0 -> LangSmith EU, 2026-10-16), host/OS user anonymized.
"""

from __future__ import annotations

import pytest

from bis_core.langsmith.map import map_runs_to_turns
from bis_core.types import Turn

from .conftest import EU_FIXTURE, load_fixture


@pytest.fixture(scope="module")
def turns() -> list[Turn]:
    return map_runs_to_turns(load_fixture(EU_FIXTURE))


def test_yields_one_turn_per_invoke_agent_and_ignores_the_ui_timing_root(turns: list[Turn]) -> None:
    assert len(turns) == 1


def test_reads_git_identity_and_team_from_otel_metadata(turns: list[Turn]) -> None:
    t = turns[0]
    assert t.repo_url == "https://github.com/javieravacone/ai-cost-tracker.git"
    assert t.branch == "feat/1-prueba-telemetria"
    assert t.commit_sha == "79a2392112f40e9dbbe80dcac946072eda748be9"
    assert t.github_org == "javieravacone"
    assert t.user_name == "javieravacone"
    assert t.team_id == "data"
    assert t.project_hint is None
    assert t.conversation_id == "b313632d-ec1a-4827-b700-3cc22cbb946c"
    assert t.agent_name == "GitHub Copilot Chat"


def test_sums_tokens_from_the_child_chat_run(turns: list[Turn]) -> None:
    t = turns[0]
    assert t.model == "gpt-6-luna"
    assert t.input_tokens == 17707
    assert t.output_tokens == 1191
    assert t.cache_read_tokens == 0
    assert t.reasoning_tokens == 111
    assert t.llm_calls == 1
    assert t.tool_calls == 1


def test_reads_the_real_copilot_usage_from_the_chat_run(turns: list[Turn]) -> None:
    t = turns[0]
    # 280,880,000 nano = 0.28088 AI credits ~ $0.0028. Consistent with GPT-6 Luna list price if
    # uncached input is charged at the cache-write rate: 17707 x $0.125/M + 1191 x $0.50/M.
    assert t.copilot_nano_aiu == 280_880_000
    assert t.copilot_usage_coverage == 1
    assert (17707 * 0.125 + 1191 * 0.5) / 1e6 == pytest.approx(t.copilot_nano_aiu * 1e-11, abs=5e-7)
