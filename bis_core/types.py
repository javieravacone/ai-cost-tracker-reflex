"""Shared domain contract (Python port of ai-cost-tracker src/lib/types.ts and content-types.ts).

Every module (db, sync, attribution, cost, report, UI) depends on these types. Field names are
the snake_case form of the TypeScript fields; semantics are identical. Change them only
deliberately and update all consumers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

Source = Literal["langsmith", "seed"]
Confidence = Literal["manual", "exact-branch", "exact-pr", "exact-commit", "inferred", "project"]
CONFIDENCE_LEVELS: tuple[Confidence, ...] = (
    "manual",
    "exact-branch",
    "exact-pr",
    "exact-commit",
    "inferred",
    "project",
)


@dataclass
class Turn:
    """One user request to the agent: a Copilot `invoke_agent` span."""

    id: str  # LangSmith run id (or seed id)
    trace_id: str
    conversation_id: str | None  # gen_ai.conversation.id
    started_at: str  # ISO 8601 UTC with "Z"
    ended_at: str | None
    user_name: str | None
    team_id: str | None  # resource attr team.id
    project_hint: str | None  # resource attr project.id
    repo_url: str | None  # github.copilot.git.repository
    branch: str | None
    commit_sha: str | None
    github_org: str | None
    agent_name: str | None
    model: str | None
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_creation_tokens: int
    reasoning_tokens: int
    llm_calls: int
    tool_calls: int
    # Real Copilot consumption in nano AI units (1 AI credit = 1e9 nano = $0.01).
    # None = unknown, which is NOT the same as 0.
    copilot_nano_aiu: int | None
    # Share 0..1 of child chat runs that reported the value; None when there were none.
    copilot_usage_coverage: float | None
    source: Source


@dataclass
class Team:
    id: str
    name: str


@dataclass
class Project:
    id: str
    name: str


@dataclass
class RepoMapping:
    repo: str  # "owner/name", lowercase
    project_id: str


@dataclass
class Member:
    user_name: str
    display_name: str
    team_id: str
    seat_plan_id: str


@dataclass
class Issue:
    repo: str  # "owner/name"
    number: int
    title: str
    state: Literal["open", "closed"]
    url: str
    created_at: str
    closed_at: str | None


@dataclass
class PullRequest:
    repo: str
    number: int
    title: str
    state: Literal["open", "closed", "merged"]
    head_branch: str
    url: str
    linked_issues: list[int]
    commit_shas: list[str]
    created_at: str
    merged_at: str | None


@dataclass
class ManualAssignment:
    turn_id: str
    repo: str
    issue_number: int | None
    pr_number: int | None
    note: str | None


@dataclass
class Attribution:
    turn_id: str
    project_id: str | None  # None = unmapped repo
    team_id: str | None
    user_name: str | None
    repo: str | None  # "owner/name"
    issue_key: str | None  # "owner/name#123"
    pr_key: str | None  # "owner/name!45"
    confidence: Confidence
    reason: str


@dataclass
class ModelPrice:
    model: str  # exact id or prefix ending in "*"
    input_per_mtok: float
    output_per_mtok: float
    cache_read_per_mtok: float
    cache_write_per_mtok: float
    premium_multiplier: float


@dataclass
class SeatPlan:
    id: str
    name: str
    monthly_price_usd: float
    included_premium_requests: int  # legacy billing unit
    overage_per_premium_request_usd: float
    included_ai_credits: int  # per seat and month, pooled


@dataclass
class TurnCost:
    turn_id: str
    api_equivalent_usd: float
    premium_requests: float
    subscription_usd: float
    ai_credits: float | None
    ai_credits_usd: float | None


# --- Captured content (only with Copilot content capture on) --------------------------------


@dataclass
class SkillUse:
    name: str  # skill folder name
    version: str | None  # 8-hex sha256 of the SKILL.md text read; None when unknown
    path: str | None


@dataclass
class TurnContent:
    turn_id: str
    user_prompt: str | None
    user_prompt_truncated: bool
    final_answer: str | None
    final_answer_truncated: bool
    error: str | None
    skills: list[SkillUse] = field(default_factory=list)
    feedback_stats: dict[str, Any] | None = None


@dataclass
class TurnEvent:
    turn_id: str
    seq: int
    run_id: str
    trace_id: str
    kind: Literal["llm", "tool"]
    name: str
    started_at: str | None
    duration_ms: int | None
    tokens_in: int | None
    tokens_out: int | None
    nano_aiu: int | None
    text: str | None
    text_truncated: bool
    tool_calls: list[str]
    args: str | None
    args_truncated: bool
    result: str | None
    result_truncated: bool
    error: str | None
