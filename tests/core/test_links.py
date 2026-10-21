"""Port of src/lib/links.test.ts."""

from __future__ import annotations

from bis_core.content_types import FileRef, args_file_ref
from bis_core.links import (
    LangsmithRef,
    blob_url,
    branch_url,
    commit_url,
    compare_url,
    file_url,
    github_profile_url,
    github_repo_url,
    issue_key_url,
    issue_url,
    langsmith_host,
    langsmith_project_url,
    langsmith_trace_url,
    linkable_repo,
    pr_key_url,
    pr_url,
    repo_relative_path,
)

REAL = "javieravacone/ai-cost-tracker"


# --- real vs fictional repos -----------------------------------------------------------------


def test_normalizes_real_repos_from_any_remote_form():
    assert linkable_repo("https://github.com/JavierAvacone/ai-cost-tracker.git") == REAL
    assert linkable_repo("git@github.com:javieravacone/ai-cost-tracker.git") == REAL
    assert github_repo_url(REAL) == "https://github.com/javieravacone/ai-cost-tracker"


def test_treats_the_seed_org_as_fictional():
    assert linkable_repo("acme-labs/atlas-api") is None
    assert linkable_repo("git@github.com:acme-labs/sandbox.git") is None
    assert github_repo_url("acme-labs/atlas-api") is None
    assert issue_url("acme-labs/atlas-api", 101) is None
    assert pr_url("acme-labs/atlas-api", 7) is None
    assert branch_url("acme-labs/atlas-api", "main") is None
    assert commit_url("acme-labs/atlas-api", "abcdef1") is None
    assert issue_key_url("acme-labs/atlas-api#101") is None


def test_returns_none_for_missing_or_unparseable_input():
    assert linkable_repo(None) is None
    assert linkable_repo("not a repo") is None
    assert issue_url(REAL, 0) is None
    assert commit_url(REAL, "not-a-sha") is None


# --- GitHub URLs -----------------------------------------------------------------------------


def test_builds_issue_pr_commit_and_compare_links():
    assert issue_url(REAL, 20) == "https://github.com/javieravacone/ai-cost-tracker/issues/20"
    assert pr_url(REAL, 17) == "https://github.com/javieravacone/ai-cost-tracker/pull/17"
    assert issue_key_url(f"{REAL}#6") == "https://github.com/javieravacone/ai-cost-tracker/issues/6"
    assert pr_key_url(f"{REAL}!8") == "https://github.com/javieravacone/ai-cost-tracker/pull/8"
    assert (
        commit_url(REAL, "58F260CBBDEF252D736F5D10B8C539B1687B98D7")
        == "https://github.com/javieravacone/ai-cost-tracker/commit/58f260cbbdef252d736f5d10b8c539b1687b98d7"
    )
    assert (
        compare_url(REAL, "main", "feat/20-links")
        == "https://github.com/javieravacone/ai-cost-tracker/compare/main...feat/20-links"
    )


def test_keeps_slashes_in_branch_names_and_encodes_the_rest():
    assert (
        branch_url(REAL, "feat/20-links-collapsible")
        == "https://github.com/javieravacone/ai-cost-tracker/tree/feat/20-links-collapsible"
    )
    assert branch_url(REAL, "fix/a b#1") == "https://github.com/javieravacone/ai-cost-tracker/tree/fix/a%20b%231"
    assert branch_url(REAL, None) is None


def test_links_github_profiles_only_for_valid_user_names():
    assert github_profile_url("javieravacone") == "https://github.com/javieravacone"
    assert github_profile_url("ana.ruiz") is None
    assert github_profile_url(None) is None


# --- file links ------------------------------------------------------------------------------

SHA = "58f260cbbdef252d736f5d10b8c539b1687b98d7"


def test_resolves_local_paths_relative_to_the_repo_folder():
    assert repo_relative_path(REAL, "/home/me/code/ai-cost-tracker/src/lib/sync/index.ts") == "src/lib/sync/index.ts"
    assert repo_relative_path(REAL, "C:\\Users\\me\\AI-Cost-Tracker\\src\\app\\page.tsx") == "src/app/page.tsx"
    assert repo_relative_path(REAL, "file:///home/me/ai-cost-tracker/README.md") == "README.md"
    assert repo_relative_path(REAL, "src/lib/links.ts") == "src/lib/links.ts"


def test_returns_none_outside_the_repo_folder_or_for_traversal():
    assert repo_relative_path(REAL, "/home/me/.copilot/skills/x/SKILL.md") is None
    assert repo_relative_path(REAL, "/home/me/ai-cost-tracker") is None
    assert repo_relative_path(REAL, "/home/me/ai-cost-tracker/../secrets.txt") is None
    assert repo_relative_path(None, "/x/y") is None


def test_builds_blob_links_at_a_commit_with_optional_line_ranges():
    assert (
        file_url(REAL, SHA, "/home/me/code/ai-cost-tracker/src/lib/sync/index.ts", {"start": 1, "end": 280})
        == f"https://github.com/javieravacone/ai-cost-tracker/blob/{SHA}/src/lib/sync/index.ts#L1-L280"
    )
    assert (
        blob_url(REAL, "HEAD", ".github/skills/cost-tracker-guide/SKILL.md")
        == "https://github.com/javieravacone/ai-cost-tracker/blob/HEAD/.github/skills/cost-tracker-guide/SKILL.md"
    )
    assert file_url("acme-labs/atlas-api", SHA, "/w/atlas-api/src/a.ts") is None
    assert file_url(REAL, None, "/w/ai-cost-tracker/src/a.ts") is None


def test_reads_the_target_file_of_a_tool_call_from_its_arguments():
    assert args_file_ref('{"endLine":280,"filePath":"/w/ai-cost-tracker/src/lib/sync/index.ts","startLine":1}') == FileRef(
        path="/w/ai-cost-tracker/src/lib/sync/index.ts", start=1, end=280
    )
    assert args_file_ref('{"query":"x"}') is None
    assert args_file_ref("not json") is None
    assert args_file_ref(None) is None


# --- LangSmith URLs --------------------------------------------------------------------------


def test_maps_the_api_host_to_the_ui_host():
    assert langsmith_host("https://api.smith.langchain.com") == "https://smith.langchain.com"
    assert langsmith_host("https://eu.api.smith.langchain.com") == "https://eu.smith.langchain.com"
    assert langsmith_host(None) == "https://smith.langchain.com"
    assert langsmith_host("https://langsmith.example.com/api") == "https://langsmith.example.com"
    assert langsmith_host("not a url") is None


def test_builds_project_and_trace_links_only_when_the_ids_are_known():
    ref = LangsmithRef(endpoint="https://eu.api.smith.langchain.com", tenant_id="org", project_id="p")
    assert langsmith_project_url(ref) == "https://eu.smith.langchain.com/o/org/projects/p/p"
    assert langsmith_trace_url(ref, "r", "t") == "https://eu.smith.langchain.com/o/org/projects/p/p/r/r?trace_id=t"
    assert langsmith_trace_url(LangsmithRef(endpoint=ref.endpoint, tenant_id=None, project_id="p"), "r", "t") is None
    assert langsmith_project_url(LangsmithRef(tenant_id="org", project_id=None)) is None
