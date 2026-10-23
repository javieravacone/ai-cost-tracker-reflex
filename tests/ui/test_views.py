"""View-model builders of the Reflex pages (pure Python, on a copy of data/app.db)."""

from __future__ import annotations

import json

import pytest

from bis_core.db import list_manual_assignments
from bis_cost_tracker.views import issues, session, settings, skills

SESSION = "5cf21cef-0679-474a-b517-4914222f195d"
SEED_SESSION = "f7e926ce-1b80-407f-92a1-d158999020ae"
SEED_TURN = "ae2f2469-3030-4635-a153-eea6a5c1460f"


# --- pure helpers -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("ms", "text"),
    [(None, None), (7, "7 ms"), (999.6, "1000 ms"), (7100, "7.1 s"), (26_000, "26 s"), (81_000, "1 min 21 s")],
)
def test_format_duration(ms, text):
    assert session.format_duration(ms) == text


def test_prompt_preview_and_count_by():
    assert session.prompt_preview("  a\n  b ") == "a b"
    assert session.prompt_preview("") is None
    assert session.prompt_preview("x" * 120) == "x" * 99 + "…"
    assert session.count_by(["read_file", "grep", "read_file"]) == "read_file ×2, grep"


def test_optional_number_and_back_url():
    assert session.optional_number("") is None
    assert session.optional_number("#12") == 12
    assert session.optional_number("!7") == 7
    assert session.optional_number("0") is False
    assert session.optional_number("abc") is False
    assert session.back_url("a b", "7", {"ok": "saved", "turn": "t"}) == "/sesiones/a%20b?ok=saved&turn=t&days=7"
    assert session.back_url("k", "", {"error": "repo"}) == "/sesiones/k?error=repo"


def test_markdown_is_plain_text_leaves():
    """Captured answers are never HTML: tags stay text, unsafe links are not clickable."""
    blocks = session.md_blocks("Hi <script>alert(1)</script> **bold** [x](javascript:alert) [ok](https://a.dev)")
    leaves = blocks[0]["c"]
    assert leaves[0] == {"k": "text", "v": "Hi <script>alert(1)</script> ", "c": "", "h": "", "ti": ""}
    assert {"k": "text", "v": "bold", "c": "font-semibold text-label", "h": "", "ti": ""} in leaves
    dead = next(x for x in leaves if x["v"] == "x")
    assert dead["k"] == "text" and dead["ti"] == "javascript:alert"
    ok = next(x for x in leaves if x["v"] == "ok")
    assert ok["k"] == "link" and ok["h"] == "https://a.dev"


def test_markdown_blocks_shapes():
    src = "# T\n\n- a\n- b\n\n3. c\n\n```\nx < y\n```\n\n| h |\n|---|\n| v |"
    kinds = [b["t"] for b in session.md_blocks(src)]
    assert kinds == ["h", "ul", "ol", "code", "table"]
    ol = session.md_blocks("3. c")[0]
    assert ol["start"] == 3 and ol["items"][0]["c"][0]["v"] == "c"


# --- builders on the real data (copy) -----------------------------------------------------------


def test_session_detail(app_db):
    d = session.build(SESSION, {})
    assert d["found"] and d["title"] == "Session by Javier"
    assert [c["label"] for c in d["crumbs"]] == ["Teams", "Data Engineering", "Javier", "Session"]
    assert d["kpis"][0]["value"][0]["t"] == "1.25 credits"
    assert d["tx"]["summary"] == "3 turns · 45 agent steps · 1.25 credits"
    assert d["tx"]["open"] is False and d["tx"]["multi"] is True
    assert d["tx_title"] == "Transcript" and len(d["rows"]) == 3
    t1 = d["tx"]["turns"][0]
    assert t1["steps_hint"] == "13 tool calls · 6 model calls · 1 min 21 s"
    assert t1["skills"][0]["href"] == "/skills?skill=cost-tracker-guide"
    json.dumps(d)  # state must be serializable


def test_session_focus_turn_opens_and_scrolls(app_db):
    turn = session.build(SESSION, {})["rows"][0]["id"]
    d = session.build(SESSION, {"turn": turn})
    assert d["tx"]["open"] is True and d["tx"]["turns"][0]["open"] and d["tx"]["turns"][0]["focused"]
    assert d["scroll_to"] == f"transcript-{turn}"
    assert session.build(SESSION, {"turn": turn, "ok": "saved"})["scroll_to"] == ""


def test_session_not_found(app_db):
    assert session.build("does-not-exist", {})["found"] is False


def test_manual_assignment_roundtrip(app_db):
    form = {"turnId": SEED_TURN, "days": "", "repo": "https://github.com/Acme-Labs/Atlas-Web", "issue": "#50", "pr": "", "note": " n "}
    assert session.save_assignment(form) == f"/sesiones/{SEED_SESSION}?ok=saved&turn={SEED_TURN}"
    saved = {m.turn_id: m for m in list_manual_assignments(app_db)}[SEED_TURN]
    assert (saved.repo, saved.issue_number, saved.pr_number, saved.note) == ("acme-labs/atlas-web", 50, None, "n")
    row = next(r for r in session.build(SEED_SESSION, {"turn": SEED_TURN, "ok": "saved"})["rows"] if r["id"] == SEED_TURN)
    assert row["manual"] and row["form"]["issue"] == "50" and "bg-accent/8" in row["c"]

    assert session.save_assignment({**form, "issue": "x"}) == f"/sesiones/{SEED_SESSION}?error=issue&turn={SEED_TURN}"
    assert session.save_assignment({**form, "repo": ""}).endswith("error=repo&turn=" + SEED_TURN)
    assert session.save_assignment({**form, "note": "x" * 501}).endswith("error=note&turn=" + SEED_TURN)
    assert session.save_assignment({**form, "turnId": "nope"}) == "/sesiones?error=turn"

    assert session.remove_assignment({"turnId": SEED_TURN, "days": "7"}) == f"/sesiones/{SEED_SESSION}?ok=removed&turn={SEED_TURN}&days=7"
    assert SEED_TURN not in {m.turn_id for m in list_manual_assignments(app_db)}


def test_issues_prs_skills_settings(app_db):
    sp = {"days": "90"}
    i = issues.build_issues(sp)
    assert not i["empty"] and i["rows"] and i["subtitle"].startswith("How much does each issue cost? · Last 90 days")
    p = issues.build_prs(sp)
    assert not p["empty"] and p["rows"]
    s = skills.build({"days": "90", "skill": "cost-tracker-guide"})
    assert s["has_skills"] and s["rows"][0]["cells"][-1]["s"][0]["o"] is True
    st = settings.build()
    assert st["has_content"] and st["credit_rule"] == "1 credit = 1,000,000,000 nano = $0.01"
    assert st["prices_subtitle"].endswith("· USD per million tokens")
    for d in (i, p, s, st):
        json.dumps(d)
