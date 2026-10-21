"""Port of src/lib/langsmith/map.test.ts."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from bis_core.langsmith.map import map_runs_to_turns, pick, to_iso

TRACE = "0e01bf50-474d-4536-810f-67d3ee7ea3e7"
ROOT = TRACE
CHAT1 = "a8024e23-5b82-47fd-970e-f6a5ba3f5097"
TOOL1 = "0ec6b845-18b9-4aa1-8f1b-6ba3f9fdefd6"
CHAT2 = "1ec6b845-18b9-4aa1-8f1b-6ba3f9fdefd7"

# v2-style root: attributes land in `metadata` (flat dotted keys).
ROOT_V2: dict[str, Any] = {
    "id": ROOT,
    "name": "invoke_agent GitHub Copilot Chat",
    "run_type": "CHAIN",
    "start_time": "2026-10-15T09:00:00.000Z",
    "end_time": "2026-10-15T09:00:42.000Z",
    "trace_id": TRACE,
    "parent_run_ids": [],
    "dotted_order": f"20261015T090000000000Z{ROOT}",
    "is_root": True,
    "prompt_tokens": 0,
    "metadata": {
        "gen_ai.operation.name": "invoke_agent",
        "gen_ai.agent.name": "GitHub Copilot Chat",
        "gen_ai.conversation.id": "conv-123",
        "gen_ai.request.model": "claude-sonnet-4.5",
        "gen_ai.response.model": "claude-sonnet-4.5-20250929",
        "gen_ai.usage.input_tokens": 12000,
        "gen_ai.usage.output_tokens": 800,
        "gen_ai.usage.cache_read.input_tokens": 9000,
        "gen_ai.usage.cache_creation.input_tokens": 1500,
        "github.copilot.git.repository": "https://github.com/acme-labs/atlas.git",
        "github.copilot.git.branch": "feat/123-login",
        "github.copilot.git.commit_sha": "abc123",
        "github.copilot.github.org": "acme-labs",
        "copilot_chat.repo.remote_url": "https://github.com/legacy/wrong.git",
        "copilot_chat.turn_count": 2,
        "user.name": "jdoe",
        "team.id": "platform",
        "project.id": "atlas",
        "service.name": "copilot-chat",
    },
}


def chat(run_id: str, parent_ids: list[str], **extra: Any) -> dict[str, Any]:
    return {
        "id": run_id,
        "name": "chat claude-sonnet-4.5",
        "run_type": "LLM",
        "trace_id": TRACE,
        "parent_run_ids": parent_ids,
        "start_time": "2026-10-15T09:00:01.000Z",
        **extra,
    }


class TestPick:
    def test_finds_flat_dotted_keys_underscore_variants_and_nested_paths(self) -> None:
        assert pick({"id": "1", "metadata": {"a.b": 1}}, ["a.b"]) == 1
        assert pick({"id": "1", "extra": {"metadata": {"a_b": 2}}}, ["a.b"]) == 2
        assert pick({"id": "1", "extra": {"metadata": {"a": {"b": 3}}}}, ["a.b"]) == 3
        assert pick({"id": "1", "extra": {"invocation_params": {"model": "m"}}}, ["invocation_params.model"]) == "m"

    def test_respects_key_priority_over_location_priority(self) -> None:
        run = {"id": "1", "metadata": {"second": "meta"}, "extra": {"metadata": {"first": "extra"}}}
        assert pick(run, ["first", "second"]) == "extra"

    def test_never_resolves_project_id_to_the_runs_langsmith_project_id(self) -> None:
        assert pick({"id": "1", "project_id": "ls-uuid"}, ["project.id"]) is None


class TestToIso:
    def test_treats_naive_langsmith_v1_timestamps_as_utc(self) -> None:
        assert to_iso("2026-10-15T09:00:00.123456") == "2026-10-15T09:00:00.123Z"
        assert to_iso("2026-10-15T11:00:00+02:00") == "2026-10-15T09:00:00.000Z"
        assert to_iso(None) is None
        assert to_iso("garbage") is None


class TestMapRunsToTurns:
    def test_maps_a_v2_style_trace_to_one_turn(self) -> None:
        runs = [
            chat(CHAT1, [ROOT], metadata={"gen_ai.usage.reasoning.output_tokens": 100}),
            {"id": TOOL1, "name": "execute_tool read_file", "run_type": "TOOL", "trace_id": TRACE, "parent_run_ids": [ROOT]},
            chat(CHAT2, [ROOT], metadata={"gen_ai.usage.reasoning.output_tokens": 50}),
            ROOT_V2,
        ]
        turn, *rest = map_runs_to_turns(runs)
        assert rest == []
        assert asdict(turn) == {
            "id": ROOT,
            "trace_id": TRACE,
            "conversation_id": "conv-123",
            "started_at": "2026-10-15T09:00:00.000Z",
            "ended_at": "2026-10-15T09:00:42.000Z",
            "user_name": "jdoe",
            "team_id": "platform",
            "project_hint": "atlas",
            "repo_url": "https://github.com/acme-labs/atlas.git",  # github.copilot.* wins over legacy
            "branch": "feat/123-login",
            "commit_sha": "abc123",
            "github_org": "acme-labs",
            "agent_name": "GitHub Copilot Chat",
            "model": "claude-sonnet-4.5-20250929",  # response model wins
            "input_tokens": 12000,
            "output_tokens": 800,
            "cache_read_tokens": 9000,
            "cache_creation_tokens": 1500,
            "reasoning_tokens": 150,  # summed from chat children
            "llm_calls": 2,
            "tool_calls": 1,
            "copilot_nano_aiu": None,  # no chat child reported it: unknown, not 0
            "copilot_usage_coverage": 0,
            "source": "langsmith",
        }

    def test_maps_a_v1_style_trace(self) -> None:
        root = {
            "id": "r1",
            "name": "invoke_agent",
            "run_type": "chain",
            "start_time": "2026-10-15T10:00:00.5",  # naive UTC
            "end_time": None,
            "trace_id": "r1",
            "parent_run_id": None,
            "extra": {
                "metadata": {
                    "gen_ai_operation_name": "invoke_agent",
                    "copilot_chat": {"repo": {"remote_url": "git@github.com:acme-labs/nimbus.git"}},
                    "copilot_chat.repo.head_branch_name": "fix/77-crash",
                    "copilot_chat.repo.head_commit_hash": "def456",
                },
                "invocation_params": {"model": "gpt-5"},
            },
        }
        c1 = {
            "id": "c1",
            "name": "chat gpt-5",
            "run_type": "llm",
            "trace_id": "r1",
            "parent_run_id": "r1",
            "prompt_tokens": 1000,
            "completion_tokens": 200,
            "outputs": {"usage_metadata": {"input_tokens": 1000, "output_tokens": 200, "input_token_details": {"cache_read": 400}}},
        }
        c2 = {
            "id": "c2",
            "name": "chat gpt-5",
            "run_type": "llm",
            "trace_id": "r1",
            "parent_run_id": "r1",
            "prompt_tokens": 3000,
            "completion_tokens": 100,
            "completion_token_details": {"reasoning": 60},
        }
        [turn] = map_runs_to_turns([root, c1, c2])
        assert turn.started_at == "2026-10-15T10:00:00.500Z"
        assert turn.ended_at is None
        assert turn.repo_url == "git@github.com:acme-labs/nimbus.git"
        assert turn.branch == "fix/77-crash"
        assert turn.commit_sha == "def456"
        assert turn.model == "gpt-5"
        assert turn.agent_name is None
        assert turn.input_tokens == 4000
        assert turn.output_tokens == 300
        assert turn.cache_read_tokens == 400
        assert turn.reasoning_tokens == 60
        assert turn.llm_calls == 2
        assert turn.tool_calls == 0
        assert turn.team_id is None

    def test_counts_nested_subagent_invoke_agent_runs_inside_the_outer_turn(self) -> None:
        sub = "22222222-2222-2222-2222-222222222222"
        sub_chat = "33333333-3333-3333-3333-333333333333"
        runs = [
            ROOT_V2,
            {
                "id": sub,
                "name": "invoke_agent explore",
                "trace_id": TRACE,
                "dotted_order": f"20261015T090000000000Z{ROOT}.20261015T090001000000Z{sub}",
            },
            {
                "id": sub_chat,
                "name": "chat gpt-5-mini",
                "run_type": "LLM",
                "trace_id": TRACE,
                "dotted_order": f"20261015T090000000000Z{ROOT}.20261015T090001000000Z{sub}.20261015T090002000000Z{sub_chat}",
            },
        ]
        turns = map_runs_to_turns(runs)
        assert len(turns) == 1
        assert turns[0].llm_calls == 1

    def test_falls_back_to_turn_count_when_no_chat_children_were_fetched(self) -> None:
        [turn] = map_runs_to_turns([ROOT_V2])
        assert turn.llm_calls == 2
        assert turn.reasoning_tokens == 0

    def test_returns_several_turns_sorted_by_start_time_and_ignores_orphan_children(self) -> None:
        later = {**ROOT_V2, "id": "later", "trace_id": "later", "start_time": "2026-10-16T00:00:00Z"}
        orphan = chat("orphan", ["not-fetched-root"], trace_id="other-trace")
        turns = map_runs_to_turns([later, orphan, ROOT_V2])
        assert [t.id for t in turns] == [ROOT, "later"]
        assert turns[1].llm_calls == 2  # turn_count fallback, orphan not attached

    def test_defaults_every_token_count_to_0_when_nothing_is_reported(self) -> None:
        [turn] = map_runs_to_turns([{"id": "x", "name": "invoke_agent", "start_time": "2026-10-15T00:00:00Z"}])
        assert (
            turn.input_tokens,
            turn.output_tokens,
            turn.cache_read_tokens,
            turn.cache_creation_tokens,
            turn.reasoning_tokens,
            turn.llm_calls,
            turn.tool_calls,
            turn.model,
            turn.trace_id,
        ) == (0, 0, 0, 0, 0, 0, 0, None, "x")

    def test_sums_copilot_usage_nano_aiu_over_chat_children_nested_subagent_calls_included(self) -> None:
        sub = "sub-agent"

        def nano(v: Any) -> dict[str, Any]:
            return {"metadata": {"otel.span.copilot_chat.copilot_usage_nano_aiu": v}}

        runs = [
            ROOT_V2,
            chat(CHAT1, [ROOT], **nano(280_880_000)),
            {"id": sub, "name": "invoke_agent explore", "run_type": "chain", "trace_id": TRACE, "parent_run_ids": [ROOT]},
            chat(CHAT2, [ROOT, sub], **nano("3000000000")),  # numeric string, above 2^31
            chat("chat-3", [ROOT], extra={"metadata": {"copilot_chat.copilot_usage_nano_aiu": 1_000}}),  # fallback key
        ]
        [turn] = map_runs_to_turns(runs)
        assert turn.llm_calls == 3
        assert turn.copilot_nano_aiu == 280_880_000 + 3_000_000_000 + 1_000
        assert isinstance(turn.copilot_nano_aiu, int)
        assert turn.copilot_usage_coverage == 1

    def test_reports_partial_coverage_when_some_chat_children_lack_the_value(self) -> None:
        runs = [
            ROOT_V2,
            chat(CHAT1, [ROOT], metadata={"otel.span.copilot_chat.copilot_usage_nano_aiu": 0}),
            chat(CHAT2, [ROOT]),
        ]
        [turn] = map_runs_to_turns(runs)
        assert turn.copilot_nano_aiu == 0  # a reported 0 stays 0
        assert turn.copilot_usage_coverage == 0.5

    def test_has_null_usage_and_null_coverage_when_there_are_no_chat_children(self) -> None:
        [turn] = map_runs_to_turns([ROOT_V2])
        assert turn.copilot_nano_aiu is None
        assert turn.copilot_usage_coverage is None
