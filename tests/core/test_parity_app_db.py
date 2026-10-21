"""Parity against the TypeScript app on a COPY of data/app.db.

Reference: /tmp/opencode/parity-ref.ts run with `npx tsx` in ~/code/ai-cost-tracker (main @
8724217, Node 24) against a backup copy of the same data/app.db. Its JSON output (keys converted
to snake_case and pruned as in `_prune`) is stored in fixtures/parity_ts.json.gz. Headline
numbers are also asserted literally below.
"""

from __future__ import annotations

import gzip
import json
import math
import re
import sqlite3
from dataclasses import fields, is_dataclass
from pathlib import Path
from typing import Any

import pytest

from bis_core.content_types import args_file_ref, summarize_args
from bis_core.cost import format_usd
from bis_core.db import get_sync_state, list_turns, open_db
from bis_core.markdown import parse_markdown
from bis_core.report import (
    by_day,
    by_issue,
    by_model,
    by_pr,
    by_project,
    by_team,
    by_user,
    compute_totals,
    list_conversations,
    load_report,
)
from bis_core.report.format import format_compact, format_credits, format_int, format_number, format_pct, format_tokens
from bis_core.report.people import person_detail, team_detail
from bis_core.report.skills import list_content_flags, list_skill_usage, skills_report

APP_DB = Path(__file__).resolve().parents[2] / "data" / "app.db"
FIXTURE = Path(__file__).parent / "fixtures" / "parity_ts.json.gz"

WINDOWS: dict[str, tuple[str | None, str | None]] = {
    "d7": ("2026-10-15T00:00:00.000Z", "2026-10-22T00:00:00.000Z"),
    "d30": ("2026-09-22T00:00:00.000Z", "2026-10-22T00:00:00.000Z"),
    "d90": ("2026-07-24T00:00:00.000Z", "2026-10-22T00:00:00.000Z"),
    "all": (None, None),
}

pytestmark = pytest.mark.skipif(not APP_DB.exists(), reason="data/app.db not present")


@pytest.fixture(scope="module")
def db(tmp_path_factory):
    """Copy data/app.db with the sqlite3 backup API (keeps WAL content) and open the copy."""
    target = tmp_path_factory.mktemp("parity") / "app.db"
    src = sqlite3.connect(f"file:{APP_DB}?mode=ro", uri=True)
    dst = sqlite3.connect(target)
    src.backup(dst)
    dst.close()
    src.close()
    conn = open_db(target)
    yield conn
    conn.close()


@pytest.fixture(scope="module")
def ts() -> dict[str, Any]:
    return json.loads(gzip.decompress(FIXTURE.read_bytes()).decode("utf-8"))


def _snake(k: str) -> str:
    return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", k).lower()


def plain(o: Any) -> Any:
    if is_dataclass(o) and not isinstance(o, type):
        return {_snake(f.name): plain(getattr(o, f.name)) for f in fields(o)}
    if isinstance(o, dict):
        return {_snake(str(k)): plain(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [plain(x) for x in o]
    return o


def assert_same(got: Any, want: Any, path: str = "$") -> None:
    if isinstance(want, bool) or isinstance(got, bool):
        assert got == want, path
    elif isinstance(want, (int, float)) and isinstance(got, (int, float)):
        assert math.isclose(got, want, rel_tol=1e-9, abs_tol=1e-9), f"{path}: {got!r} != {want!r}"
    elif isinstance(want, dict):
        assert isinstance(got, dict), path
        assert set(got) == set(want), f"{path}: keys {sorted(set(got) ^ set(want))}"
        for k in want:
            assert_same(got[k], want[k], f"{path}.{k}")
    elif isinstance(want, list):
        assert isinstance(got, list), path
        assert len(got) == len(want), f"{path}: len {len(got)} != {len(want)}"
        for i, (g, w) in enumerate(zip(got, want)):
            assert_same(g, w, f"{path}[{i}]")
    else:
        assert got == want, f"{path}: {got!r} != {want!r}"


def _prune(w: dict[str, Any], name: str) -> None:
    if name != "d7":
        w["conversations"] = w["conversations"][:20]
    for p in w["people"].values():
        if p:
            p["conversations"] = p["conversations"][:5]
            p["daily"] = p["daily"][-7:]
    w["by_day"] = w["by_day"][-14:]


def _title(b: dict[str, Any], key: str) -> dict[str, Any]:
    b[key] = b[key]["title"] if b[key] else None
    return b


def python_window(db: sqlite3.Connection, name: str) -> dict[str, Any]:
    from_, to = WINDOWS[name]
    r = load_report(db, from_, to)
    t = compute_totals(r)
    usage, flags = list_skill_usage(db), list_content_flags(db)
    out: dict[str, Any] = {
        "totals": t,
        "formatted": {
            "turns": format_int(t.turns),
            "ai_credits": format_credits(t.ai_credits),
            "ai_credits_usd": format_usd(t.ai_credits_usd),
            "api": format_usd(t.api_equivalent_usd),
            "subscription": format_usd(t.subscription_usd),
            "tokens": format_tokens(t.tokens),
            "compact_tokens": format_compact(t.tokens),
            "pct_with_issue": format_pct(t.pct_with_issue),
            "premium": format_number(t.premium_requests),
        },
        "by_team": by_team(r),
        "by_project": by_project(r),
        "by_model": by_model(r),
        "by_user": by_user(r),
        "by_issue": by_issue(r),
        "by_pr": by_pr(r),
        "by_day": by_day(r),
        "conversations": list_conversations(r.rows),
        "idle_seats": r.idle_seats,
        "credit_pools": r.credit_pools,
        "member_months": r.member_months,
        "unpriced_models": r.unpriced_models,
        "unmapped_repos": r.unmapped_repos,
        "turns_without_repo": r.turns_without_repo,
        "confidence": r.confidence,
        "sources": r.sources,
        "teams": {tm.id: team_detail(r, tm.id) for tm in r.refs.teams},
        "people": {u: person_detail(r, u) for u in [*(m.user_name for m in r.refs.members), "javieravacone"]},
        "skills": skills_report(r.rows, usage, flags),
    }
    if name == "d7":
        out["rows"] = [
            {
                "id": x.turn.id,
                "attribution": x.attribution,
                "cost": x.cost,
                "team_name": x.team_name,
                "project_name": x.project_name,
                "user_display_name": x.user_display_name,
                "conversation_key": x.conversation_key,
                "day": x.day,
                "tokens": x.tokens,
            }
            for x in r.rows
        ]
    p = plain(out)
    p["by_issue"] = [_title(b, "issue") for b in p["by_issue"]]
    p["by_pr"] = [_title(b, "pr") for b in p["by_pr"]]
    for team in p["teams"].values():
        team["issues"] = [_title(b, "issue") for b in team["issues"]]
    for person in p["people"].values():
        if person:
            person["issues"] = [_title(b, "issue") for b in person["issues"]]
    _prune(p, name)
    return p


def test_app_db_copy_counts(db, ts):
    turns = list_turns(db)
    assert len([t for t in turns if t.source == "langsmith"]) == 21
    assert len([t for t in turns if t.source == "seed"]) == 3000
    assert ts["counts"] == {"langsmith": 21, "seed": 3000}
    assert db.execute("PRAGMA user_version").fetchone()[0] == 3
    assert db.execute("SELECT COUNT(*) FROM turn_content").fetchone()[0] == 21
    assert db.execute("SELECT COUNT(*) FROM turn_events").fetchone()[0] == 117
    assert get_sync_state(db, "langsmith.tenantId") == ts["sync_tenant"]


# Headline numbers of the TS app for the same DB and windows (computeTotals + formatters).
HEADLINES = {
    "d7": dict(turns=174, conversations=29, users=10, ai_credits=2707.672363999999, api=30.50743638, subscription=52.05257563509996,
               formatted=("174", "2,708", "$27.08", "$30.51", "$52.05", "11.3 M", "76.4%")),
    "d30": dict(turns=1344, conversations=225, users=11, ai_credits=18333.60715399996, api=205.07543490499998, subscription=330.43359848955475,
                formatted=("1,344", "18,334", "$183.34", "$205.08", "$330.43", "85.0 M", "76.7%")),
    "d90": dict(turns=3021, conversations=496, users=11, ai_credits=53219.67075400013, api=587.2014592199994, subscription=916.4761290322691,
                formatted=("3,021", "53,220", "$532.20", "$587.20", "$916.48", "197.0 M", "78.7%")),
    "all": dict(turns=3021, conversations=496, users=11, ai_credits=53219.67075400013, api=587.2014592199994, subscription=851.9600000000111,
                formatted=("3,021", "53,220", "$532.20", "$587.20", "$851.96", "197.0 M", "78.7%")),
}  # fmt: skip


@pytest.mark.parametrize("name", list(WINDOWS))
def test_headline_totals_match_ts(db, name):
    from_, to = WINDOWS[name]
    t = compute_totals(load_report(db, from_, to))
    h = HEADLINES[name]
    assert (t.turns, t.conversations, t.users) == (h["turns"], h["conversations"], h["users"])
    assert t.ai_credits == pytest.approx(h["ai_credits"], rel=1e-12)
    assert t.api_equivalent_usd == pytest.approx(h["api"], rel=1e-12)
    assert t.subscription_usd == pytest.approx(h["subscription"], rel=1e-12)
    assert (
        format_int(t.turns),
        format_credits(t.ai_credits),
        format_usd(t.ai_credits_usd),
        format_usd(t.api_equivalent_usd),
        format_usd(t.subscription_usd),
        format_tokens(t.tokens),
        format_pct(t.pct_with_issue),
    ) == h["formatted"]


@pytest.mark.parametrize("name", list(WINDOWS))
def test_every_aggregation_matches_ts(db, ts, name):
    assert_same(python_window(db, name), ts[name], f"${name}")


def test_markdown_of_captured_answers_matches_ts(db, ts):
    rows = db.execute("SELECT turn_id, user_prompt, final_answer FROM turn_content ORDER BY turn_id").fetchall()
    got = [
        {
            "id": r[0],
            "prompt": parse_markdown(r[1]) if r[1] else None,
            "answer": parse_markdown(r[2]) if r[2] else None,
        }
        for r in rows
    ]
    assert_same(got, ts["markdown"])


def test_tool_argument_summaries_match_ts(db, ts):
    rows = db.execute("SELECT turn_id, seq, args FROM turn_events ORDER BY turn_id, seq").fetchall()
    got = [{"id": f"{r[0]}:{r[1]}", "summary": summarize_args(r[2]), "file": plain(args_file_ref(r[2]))} for r in rows]
    assert_same(got, ts["args"])
