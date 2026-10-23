"""Port of src/lib/attribution/attribution.test.ts."""

from __future__ import annotations

import itertools
import time
import pytest

from bis_core.attribution import (
    AttributionContext,
    InferredIssue,
    attribute,
    normalize_repo,
    parse_issue_from_branch,
    summarize_confidence,
)
from bis_core.types import Issue, ManualAssignment, Member, PullRequest, RepoMapping, Turn

REPO_URL = "https://github.com/acme-labs/atlas.git"
REPO = "acme-labs/atlas"

_seq = itertools.count(1)


def turn(**over) -> Turn:
    n = next(_seq)
    base = dict(
        id=f"t{n}",
        trace_id=f"tr{n}",
        conversation_id="c1",
        started_at="2026-10-10T10:00:00Z",
        ended_at=None,
        user_name="ana",
        team_id=None,
        project_hint=None,
        repo_url=REPO_URL,
        branch="main",
        commit_sha=None,
        github_org="acme-labs",
        agent_name=None,
        model="gpt-5",
        input_tokens=0,
        output_tokens=0,
        cache_read_tokens=0,
        cache_creation_tokens=0,
        reasoning_tokens=0,
        llm_calls=1,
        tool_calls=0,
        copilot_nano_aiu=None,
        copilot_usage_coverage=None,
        source="seed",
    )
    base.update(over)
    return Turn(**base)


def pr(number: int, **over) -> PullRequest:
    base = dict(
        repo=REPO,
        number=number,
        title=f"PR {number}",
        state="open",
        head_branch=f"branch-{number}",
        url=f"https://github.com/{REPO}/pull/{number}",
        linked_issues=[],
        commit_shas=[],
        created_at="2026-10-01T00:00:00Z",
        merged_at=None,
    )
    base.update(over)
    return PullRequest(**base)


def ctx(**over) -> AttributionContext:
    base = dict(
        repo_mappings=[RepoMapping(repo=REPO, project_id="atlas"), RepoMapping(repo="acme-labs/nimbus", project_id="nimbus")],
        members=[
            Member(user_name="ana", display_name="Ana", team_id="team-core", seat_plan_id="biz"),
            Member(user_name="Bob", display_name="Bob", team_id="team-web", seat_plan_id="biz"),
        ],
        issues=[
            Issue(
                repo=REPO,
                number=123,
                title="Login",
                state="open",
                url="",
                created_at="2026-09-01T00:00:00Z",
                closed_at=None,
            )
        ],
        pull_requests=[],
        manual_assignments=[],
    )
    base.update(over)
    return AttributionContext(**base)


def one(t: Turn, c: AttributionContext | None = None):
    return attribute([t], c or ctx())[0]


def has(a, **expected) -> bool:
    return all(getattr(a, k) == v for k, v in expected.items())


# --- normalize_repo --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("https://github.com/Owner/Name", "owner/name"),
        ("https://github.com/Owner/Name.git", "owner/name"),
        ("https://github.com/Owner/Name/", "owner/name"),
        ("https://github.com/Owner/Name.git/", "owner/name"),
        ("http://github.com/owner/name", "owner/name"),
        ("git@github.com:Owner/Name.git", "owner/name"),
        ("git@github.com:owner/name", "owner/name"),
        ("ssh://git@github.com/owner/name.git", "owner/name"),
        ("ssh://git@github.com:22/owner/name.git", "owner/name"),
        ("git://github.com/owner/name.git", "owner/name"),
        ("https://user@github.com/Owner/Name.git", "owner/name"),
        ("https://user:token@github.com/owner/name", "owner/name"),
        ("https://github.acme.io/Team/Repo.git", "team/repo"),
        ("git@ghe.acme.internal:team/repo.git", "team/repo"),
        ("github.com/owner/name", "owner/name"),
        ("Owner/Name", "owner/name"),
        ("acme-labs/atlas", "acme-labs/atlas"),
        ("  https://github.com/owner/my.repo_x-1  ", "owner/my.repo_x-1"),
        ("https://github.com/owner/name/tree/main", "owner/name"),
        ("https://github.com/owner/name?tab=readme", "owner/name"),
    ],
)
def test_normalize_repo(value, expected):
    assert normalize_repo(value) == expected


@pytest.mark.parametrize(
    "value",
    [
        None,
        "",
        "   ",
        "not a repo",
        "justname",
        "https://github.com/",
        "https://github.com/owner",
        "https://",
        "owner/..",
        "-bad/name",
        "owner/na me",
        "owner/name$",
    ],
)
def test_normalize_repo_rejects(value):
    assert normalize_repo(value) is None


# --- parse_issue_from_branch -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("branch", "n"),
    [
        ("feat/123-login", 123),
        ("fix/123", 123),
        ("feature/issue-123-x", 123),
        ("bugfix/GH-123-x", 123),
        ("123-some-thing", 123),
        ("users/ana/123-x", 123),
        ("issue-123", 123),
        ("issues/45", 45),
        ("feat/#123-x", 123),
        ("fix/issue123", 123),
        ("fix/123_snake_case", 123),
        ("refs/heads/feat/77-x", 77),
        ("feat/2001-login", 2001),
        ("7", 7),
    ],
)
def test_parse_issue_from_branch(branch, n):
    assert parse_issue_from_branch(branch) == n


@pytest.mark.parametrize(
    "branch",
    [
        None,
        "",
        "main",
        "master",
        "develop",
        "Main",
        "release/2026.10",
        "release/1.2.3",
        "releases/123",
        "v1.2",
        "v2",
        "hotfix/2026-10-16",
        "2026-10-16-fix",
        "feat/2026_10_cleanup",
        "chore/2026/10/16-bump",
        "dependabot/npm_and_yarn/next-16.4.2",
        "dependabot/github_actions/123-x",
        "renovate/react-19.x",
        "renovate/123-x",
        "revert-45-feat/123-login",
        "feat/ABC-123-x",
        "PROJ-123",
        "feat/login",
        "fix/123-456",
        "fix/1.2",
        "fix/0",
        "fix/0123-x",
        "fix/12345678-x",
        "feat/v2-123",
    ],
)
def test_parse_issue_from_branch_rejects(branch):
    assert parse_issue_from_branch(branch) is None


# --- attribute: project/team basics ----------------------------------------------------------


def test_maps_project_from_repo_team_from_member_user_passthrough():
    a = one(turn(branch="main"))
    assert has(
        a,
        project_id="atlas",
        team_id="team-core",
        user_name="ana",
        repo=REPO,
        issue_key=None,
        pr_key=None,
        confidence="project",
    )
    assert a.reason == "branch main: default branch"


def test_member_lookup_is_case_insensitive():
    assert one(turn(user_name="bob")).team_id == "team-web"


def test_turn_team_id_wins_over_member_team():
    assert one(turn(team_id="team-x")).team_id == "team-x"


def test_unknown_user_and_no_team_gives_none_team():
    assert one(turn(user_name="zoe")).team_id is None
    assert one(turn(user_name=None)).team_id is None


def test_project_hint_overrides_repo_mapping():
    assert one(turn(project_hint="nimbus")).project_id == "nimbus"


def test_project_hint_applies_even_for_unmapped_repos():
    a = one(turn(repo_url="git@github.com:other/x.git", project_hint="atlas"))
    assert a.project_id == "atlas"
    assert "repo not mapped" not in a.reason


def test_unmapped_repo_gives_none_project_confidence_project():
    a = one(turn(repo_url="https://github.com/other/thing", branch="develop"))
    assert a.project_id is None
    assert a.repo == "other/thing"
    assert a.confidence == "project"
    assert a.reason == "branch develop: default branch; repo not mapped"


def test_repo_mappings_given_in_url_form_are_normalized():
    c = ctx(repo_mappings=[RepoMapping(repo="https://github.com/Acme-Labs/Atlas.git", project_id="atlas")])
    assert one(turn(), c).project_id == "atlas"


def test_project_reasons():
    assert one(turn(branch=None)).reason == "no branch"
    assert has(
        one(turn(repo_url=None, branch="feat/123-x")),
        repo=None,
        project_id=None,
        issue_key=None,
        confidence="project",
        reason="no repo",
    )
    assert one(turn(repo_url="garbage")).reason == "unrecognized repo garbage"
    assert one(turn(branch="feat/login")).reason == "branch feat/login: no issue/PR match"


# --- attribute: cascade levels ---------------------------------------------------------------


def test_manual_issue_and_pr_in_assignment_repo():
    m = ManualAssignment(turn_id="m1", repo="Acme-Labs/Nimbus", issue_number=9, pr_number=10, note="pairing")
    a = one(turn(id="m1"), ctx(manual_assignments=[m]))
    assert has(
        a,
        confidence="manual",
        repo="acme-labs/nimbus",
        project_id="nimbus",
        issue_key="acme-labs/nimbus#9",
        pr_key="acme-labs/nimbus!10",
    )
    assert "pairing" in a.reason


def test_manual_pr_only_with_one_linked_issue_fills_issue_key():
    m = ManualAssignment(turn_id="m2", repo=REPO, issue_number=None, pr_number=5, note=None)
    a = one(turn(id="m2"), ctx(manual_assignments=[m], pull_requests=[pr(5, linked_issues=[77])]))
    assert a.issue_key == f"{REPO}#77"
    assert a.pr_key == f"{REPO}!5"


def test_manual_pr_with_several_linked_issues_leaves_issue_empty():
    m = ManualAssignment(turn_id="m3", repo=REPO, issue_number=None, pr_number=5, note=None)
    a = one(turn(id="m3"), ctx(manual_assignments=[m], pull_requests=[pr(5, linked_issues=[1, 2])]))
    assert a.issue_key is None
    assert "2 linked issues" in a.reason


def test_manual_unmapped_manual_repo_keeps_turn_project():
    m = ManualAssignment(turn_id="m4", repo="x/y", issue_number=1, pr_number=None, note=None)
    a = one(turn(id="m4"), ctx(manual_assignments=[m]))
    assert a.project_id == "atlas"
    assert a.issue_key == "x/y#1"


def test_exact_branch_synced_issue():
    a = one(turn(branch="feat/123-login"))
    assert has(a, confidence="exact-branch", issue_key=f"{REPO}#123", pr_key=None)
    assert a.reason == "branch feat/123-login → #123"


def test_exact_branch_issue_not_synced_is_still_attributed_and_explained():
    a = one(turn(branch="fix/999"))
    assert a.issue_key == f"{REPO}#999"
    assert "issue not synced" in a.reason


def test_exact_branch_also_sets_pr_when_branch_is_a_pr_head():
    c = ctx(pull_requests=[pr(45, head_branch="feat/123-login")])
    a = one(turn(branch="feat/123-login"), c)
    assert has(a, confidence="exact-branch", issue_key=f"{REPO}#123", pr_key=f"{REPO}!45")


def test_exact_branch_pr_in_another_repo_with_same_head_is_ignored():
    c = ctx(pull_requests=[pr(45, repo="acme-labs/nimbus", head_branch="feat/123-login")])
    assert one(turn(branch="feat/123-login"), c).pr_key is None


def test_exact_pr_branch_equals_pr_head_single_linked_issue():
    c = ctx(pull_requests=[pr(46, head_branch="feat/login", linked_issues=[123])])
    a = one(turn(branch="feat/login"), c)
    assert has(a, confidence="exact-pr", pr_key=f"{REPO}!46", issue_key=f"{REPO}#123")
    assert "head of PR !46" in a.reason


def test_exact_pr_zero_or_many_linked_issues():
    a0 = one(turn(branch="feat/login"), ctx(pull_requests=[pr(46, head_branch="feat/login")]))
    assert a0.issue_key is None
    assert "no linked issue" in a0.reason
    a2 = one(turn(branch="feat/login"), ctx(pull_requests=[pr(46, head_branch="feat/login", linked_issues=[1, 2, 3])]))
    assert a2.issue_key is None
    assert "3 linked issues" in a2.reason


def test_exact_commit_full_sha_case_insensitive():
    sha = "abcdef1234567890abcdef1234567890abcdef12"
    c = ctx(pull_requests=[pr(47, head_branch="x", commit_shas=[sha], linked_issues=[8])])
    a = one(turn(branch="main", commit_sha=sha.upper()), c)
    assert has(a, confidence="exact-commit", pr_key=f"{REPO}!47", issue_key=f"{REPO}#8")
    assert "commit abcdef1" in a.reason


def test_exact_commit_7_char_prefix_matches_shorter_does_not():
    sha = "0123456789abcdef0123456789abcdef01234567"
    c = ctx(pull_requests=[pr(48, commit_shas=[sha])])
    assert one(turn(commit_sha="0123456"), c).pr_key == f"{REPO}!48"
    assert one(turn(commit_sha="0123456789ab"), c).pr_key == f"{REPO}!48"
    assert one(turn(commit_sha="012345"), c).confidence == "project"
    assert one(turn(commit_sha="0123457"), c).confidence == "project"


def test_exact_commit_same_commit_in_another_repo_does_not_match():
    sha = "0123456789abcdef0123456789abcdef01234567"
    c = ctx(pull_requests=[pr(48, repo="acme-labs/nimbus", commit_shas=[sha])])
    assert one(turn(commit_sha=sha), c).confidence == "project"


def test_inferred_hook_result_used_when_nothing_exact_matches():
    c = ctx(
        infer_issue=lambda t: InferredIssue(issue_key=f"{REPO}#5", reason="title similarity")
        if t.branch == "feat/login"
        else None
    )
    a = one(turn(branch="feat/login"), c)
    assert has(a, confidence="inferred", issue_key=f"{REPO}#5", pr_key=None)
    assert a.reason == "inferred: title similarity"
    assert one(turn(branch="main"), c).confidence == "project"


def test_inferred_hook_is_not_called_when_an_exact_level_matched():
    calls = []

    def hook(_t):
        calls.append(1)
        return {"issue_key": "x/y#1", "reason": "r"}

    one(turn(branch="feat/123-x"), ctx(infer_issue=hook))
    assert calls == []


# --- attribute: precedence -------------------------------------------------------------------


def test_manual_beats_branch():
    m = ManualAssignment(turn_id="p1", repo=REPO, issue_number=7, pr_number=None, note=None)
    a = one(turn(id="p1", branch="feat/123-login"), ctx(manual_assignments=[m]))
    assert a.confidence == "manual"
    assert a.issue_key == f"{REPO}#7"


def test_branch_beats_pr_linked_issue():
    c = ctx(pull_requests=[pr(50, head_branch="feat/123-login", linked_issues=[9])])
    a = one(turn(branch="feat/123-login"), c)
    assert a.confidence == "exact-branch"
    assert a.issue_key == f"{REPO}#123"
    assert a.pr_key == f"{REPO}!50"


def test_pr_head_beats_commit_match():
    sha = "1111111222222233333334444444555555566666"
    c = ctx(pull_requests=[pr(51, head_branch="feat/login"), pr(52, head_branch="other", commit_shas=[sha])])
    assert has(one(turn(branch="feat/login", commit_sha=sha), c), confidence="exact-pr", pr_key=f"{REPO}!51")


def test_conversation_switching_branch_mid_way_yields_two_issues():
    res = attribute(
        [
            turn(conversation_id="conv", branch="feat/123-login", started_at="2026-10-10T10:00:00Z"),
            turn(conversation_id="conv", branch="feat/123-login", started_at="2026-10-10T10:05:00Z"),
            turn(conversation_id="conv", branch="fix/200-crash", started_at="2026-10-10T10:10:00Z"),
        ],
        ctx(),
    )
    assert [r.issue_key for r in res] == [f"{REPO}#123", f"{REPO}#123", f"{REPO}#200"]


# --- attribute: PR selection when a head branch is reused ------------------------------------

REUSED = ctx(
    pull_requests=[
        pr(60, head_branch="feat/login", created_at="2026-09-01T00:00:00Z", merged_at="2026-09-10T00:00:00Z", linked_issues=[1]),
        pr(61, head_branch="feat/login", created_at="2026-10-01T00:00:00Z", merged_at="2026-10-05T00:00:00Z", linked_issues=[2]),
    ]
)


def test_picks_the_pr_whose_window_contains_the_turn():
    assert one(turn(branch="feat/login", started_at="2026-09-05T00:00:00Z"), REUSED).pr_key == f"{REPO}!60"
    assert has(
        one(turn(branch="feat/login", started_at="2026-10-03T00:00:00Z"), REUSED),
        pr_key=f"{REPO}!61",
        issue_key=f"{REPO}#2",
    )


def test_between_windows_most_recent_created_before_the_turn():
    assert one(turn(branch="feat/login", started_at="2026-09-20T00:00:00Z"), REUSED).pr_key == f"{REPO}!60"
    assert one(turn(branch="feat/login", started_at="2026-12-01T00:00:00Z"), REUSED).pr_key == f"{REPO}!61"


def test_before_all_prs_most_recent_overall():
    assert one(turn(branch="feat/login", started_at="2026-01-01T00:00:00Z"), REUSED).pr_key == f"{REPO}!61"


def test_open_pr_window_extends_to_now():
    c = ctx(
        pull_requests=[
            pr(70, head_branch="feat/x", created_at="2026-09-01T00:00:00Z"),
            pr(71, head_branch="feat/x", created_at="2026-08-01T00:00:00Z", merged_at="2026-08-02T00:00:00Z"),
        ]
    )
    assert one(turn(branch="feat/x", started_at="2026-10-15T00:00:00Z"), c).pr_key == f"{REPO}!70"


def test_commit_present_in_two_prs_uses_the_same_time_window_rule():
    sha = "abcabcabcabcabcabcabcabcabcabcabcabcabca"
    c = ctx(
        pull_requests=[
            pr(80, commit_shas=[sha], created_at="2026-09-01T00:00:00Z", merged_at="2026-09-10T00:00:00Z"),
            pr(81, commit_shas=[sha], created_at="2026-10-01T00:00:00Z"),
        ]
    )
    assert one(turn(commit_sha=sha, started_at="2026-09-05T00:00:00Z"), c).pr_key == f"{REPO}!80"
    assert one(turn(commit_sha=sha, started_at="2026-10-05T00:00:00Z"), c).pr_key == f"{REPO}!81"


# --- attribute: order, summary, performance --------------------------------------------------


def test_preserves_input_order():
    ts = [turn(branch="fix/1"), turn(branch="main"), turn(branch="fix/3")]
    assert [a.turn_id for a in attribute(ts, ctx())] == [t.id for t in ts]


def test_empty_input_gives_empty_output():
    assert attribute([], ctx()) == []


def test_summarize_confidence_counts_every_level_zero_filled():
    m = ManualAssignment(turn_id="s1", repo=REPO, issue_number=1, pr_number=None, note=None)
    res = attribute(
        [turn(id="s1"), turn(branch="fix/1"), turn(branch="fix/2"), turn(branch="main")],
        ctx(manual_assignments=[m]),
    )
    assert summarize_confidence(res) == {
        "manual": 1,
        "exact-branch": 2,
        "exact-pr": 0,
        "exact-commit": 0,
        "inferred": 0,
        "project": 1,
    }


def test_10k_turns_against_2k_prs_quickly():
    state = 42

    def hex_() -> str:
        nonlocal state
        s = ""
        for _ in range(5):
            state = (state * 1664525 + 1013904223) & 0xFFFFFFFF
            s += f"{state:08x}"
        return s

    all_shas: list[str] = []
    prs: list[PullRequest] = []
    for i in range(1, 2001):
        shas = [hex_() for _ in range(10)]
        all_shas.extend(shas)
        prs.append(pr(i, head_branch=f"topic-{i}", linked_issues=[i], commit_shas=shas))
    c = ctx(pull_requests=prs, infer_issue=lambda _t: None)
    branches = ["main", "feat/123-x", "topic-17", "feat/login", None]
    ts = []
    for i in range(10_000):
        sha = all_shas[(i * 7) % len(all_shas)]
        ts.append(turn(branch=branches[i % len(branches)], commit_sha=sha if i % 2 else sha[:10]))
    start = time.perf_counter()
    res = attribute(ts, c)
    ms = (time.perf_counter() - start) * 1000
    assert len(res) == 10_000
    assert len([a for a in res if a.confidence == "exact-commit"]) > 0
    # Generous bound (Python is slower than V8): catches quadratic regressions.
    assert ms < 3000


def test_degenerate_shared_sha_prefixes_stay_fast_for_full_sha_lookups():
    prs = [pr(i, commit_shas=[f"{i:x}".rjust(40, "b")]) for i in range(1, 2001)]
    ts = [turn(commit_sha=f"{(i % 2000) + 1:x}".rjust(40, "b")) for i in range(10_000)]
    start = time.perf_counter()
    res = attribute(ts, ctx(pull_requests=prs))
    assert (time.perf_counter() - start) * 1000 < 3000
    assert res[0].pr_key == f"{REPO}!1"

