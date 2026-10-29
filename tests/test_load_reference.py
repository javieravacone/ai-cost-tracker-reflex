"""scripts/load_reference.py: fills reference tables from config + real turns, never reseeds."""

from __future__ import annotations

import importlib.util
import json
import sqlite3
from pathlib import Path

import pytest

from bis_core.db import open_db
from bis_core.report import compute_totals, load_report

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "load_reference.py"
_spec = importlib.util.spec_from_file_location("load_reference", SCRIPT)
assert _spec and _spec.loader
lr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(lr)

TURNS = [
    # id, user, team, repo_url, model, input, output
    ("t1", "alice", "data", "https://github.com/Acme/Atlas-API.git", "gpt-6-luna", 100_000, 20_000),
    ("t2", "alice", "data", "git@github.com:acme/nimbus.git", "claude-sonnet-4.5", 50_000, 5_000),
    ("t3", "bob", None, "https://bob@dev.azure.com/contoso/Payments/_git/billing-svc", "mystery-model-1", 10_000, 1_000),
    ("t4", "bob", None, None, None, 0, 0),
]


@pytest.fixture()
def db_path(tmp_path: Path) -> Path:
    path = tmp_path / "app.db"
    db = open_db(str(path))
    for tid, user, team, repo, model, inp, out in TURNS:
        db.execute(
            "INSERT INTO turns (id, trace_id, started_at, user_name, team_id, repo_url, model, input_tokens, output_tokens, source)"
            " VALUES (?, ?, '2026-10-05T10:00:00Z', ?, ?, ?, ?, ?, ?, 'langsmith')",
            (tid, tid, user, team, repo, model, inp, out),
        )
    db.close()
    return path


def run(db_path: Path, tmp_path: Path, *extra: str, config: dict | None = None) -> int:
    cfg = tmp_path / "reference.json"
    if config is not None:
        cfg.write_text(json.dumps(config), encoding="utf-8")
    return lr.main(["--db", str(db_path), "--config", str(cfg), *extra])


def rows(db_path: Path, sql: str) -> list[tuple]:
    db = sqlite3.connect(db_path)
    try:
        return db.execute(sql).fetchall()
    finally:
        db.close()


def snapshot(db_path: Path) -> dict[str, list[tuple]]:
    return {t: rows(db_path, f"SELECT * FROM {t} ORDER BY 1") for t in lr.TABLES}


def test_repo_key_rules() -> None:
    assert lr.repo_key("https://github.com/Acme/Atlas-API.git") == "acme/atlas-api"
    assert lr.repo_key("git@github.com:acme/nimbus.git") == "acme/nimbus"
    assert lr.repo_key("https://ghe.corp.example/team/svc") == "team/svc"
    assert lr.repo_key("ssh://git@ghe.corp.example:2222/team/svc.git") == "team/svc"
    assert lr.repo_key("https://bob@dev.azure.com/contoso/Payments/_git/billing-svc") == "contoso/billing-svc"
    assert lr.repo_key("git@ssh.dev.azure.com:v3/contoso/Payments/billing-svc") == "contoso/billing-svc"
    assert lr.repo_key("https://contoso.visualstudio.com/DefaultCollection/Payments/_git/billing-svc") == "contoso/billing-svc"
    assert lr.app_repo_key("https://dev.azure.com/contoso/Payments/_git/billing-svc") == "contoso/payments"
    assert lr.repo_key("not a url") is None


def test_auto_fills_everything_and_is_idempotent(db_path: Path, tmp_path: Path, capsys) -> None:
    assert run(db_path, tmp_path) == 0  # no config file -> built-in defaults
    out = capsys.readouterr().out
    assert "built-in defaults" in out and "mystery-model-1 (1 turns)" in out

    plans = {r[0] for r in rows(db_path, "SELECT id FROM seat_plans")}
    assert plans == {"copilot-business", "copilot-enterprise", "copilot-pro", "copilot-free"}
    assert {"gpt-6-luna", "gpt-6*", "gpt-5*", "claude-sonnet-4*"} <= {r[0] for r in rows(db_path, "SELECT model FROM model_prices")}
    assert rows(db_path, "SELECT id, name FROM teams ORDER BY id") == [("data", "data"), ("unassigned", "Unassigned")]
    assert dict(rows(db_path, "SELECT repo, project_id FROM repo_mappings")) == {
        "acme/atlas-api": "atlas-api",
        "acme/nimbus": "nimbus",
        "contoso/billing-svc": "billing-svc",
        "contoso/payments": "billing-svc",  # the key the app computes for the Azure URL today
    }
    assert {r[0] for r in rows(db_path, "SELECT id FROM projects")} == {"atlas-api", "nimbus", "billing-svc"}
    assert rows(db_path, "SELECT * FROM members ORDER BY 1") == [
        ("alice", "alice", "data", "copilot-business"),
        ("bob", "bob", "unassigned", "copilot-business"),
    ]

    before = snapshot(db_path)
    assert run(db_path, tmp_path) == 0
    assert "Changes: none" in capsys.readouterr().out
    assert snapshot(db_path) == before


def test_config_overrides_but_auto_does_not(db_path: Path, tmp_path: Path) -> None:
    db = sqlite3.connect(db_path)
    with db:
        db.execute("INSERT INTO members VALUES ('Bob', 'Bob Existing', 'web', 'copilot-enterprise')")
    db.close()
    assert run(db_path, tmp_path) == 0
    assert rows(db_path, "SELECT * FROM members WHERE lower(user_name) = 'bob'") == [("Bob", "Bob Existing", "web", "copilot-enterprise")]

    config = {"members": [{"user_name": "alice", "display_name": "Alice A.", "seat_plan_id": "copilot-pro"}], "teams": [{"id": "data", "name": "Data Eng"}]}
    assert run(db_path, tmp_path, config=config) == 0
    assert rows(db_path, "SELECT * FROM members WHERE user_name = 'alice'") == [("alice", "Alice A.", "data", "copilot-pro")]
    assert rows(db_path, "SELECT name FROM teams WHERE id = 'data'") == [("Data Eng",)]
    assert len(rows(db_path, "SELECT * FROM members")) == 2


def test_dry_run_writes_nothing(db_path: Path, tmp_path: Path, capsys) -> None:
    before = snapshot(db_path)
    assert run(db_path, tmp_path, "--dry-run") == 0
    out = capsys.readouterr().out
    assert "DRY RUN" in out and "+ seat_plans copilot-business" in out
    assert snapshot(db_path) == before


def test_no_auto_and_bad_inputs(db_path: Path, tmp_path: Path, capsys) -> None:
    assert run(db_path, tmp_path, "--no-auto") == 0
    assert rows(db_path, "SELECT COUNT(*) FROM members") == [(0,)]
    assert "alice, bob" in capsys.readouterr().out  # users without a member row

    assert run(db_path, tmp_path, config={"seat_plans": [{"id": "x"}]}) == 2
    assert "missing required field 'name'" in capsys.readouterr().err

    empty = tmp_path / "empty.db"
    sqlite3.connect(empty).close()
    assert lr.main(["--db", str(empty), "--config", str(tmp_path / "none.json")]) == 2
    assert "missing table 'seat_plans'" in capsys.readouterr().err
    assert lr.main(["--db", str(tmp_path / "missing.db")]) == 2


def test_report_has_costs_after_loading(db_path: Path, tmp_path: Path) -> None:
    db = open_db(str(db_path))
    totals = compute_totals(load_report(db))
    assert totals.subscription_usd == 0 and totals.api_equivalent_usd == 0
    db.close()

    assert run(db_path, tmp_path) == 0
    db = open_db(str(db_path))
    report = load_report(db)
    totals = compute_totals(report)
    db.close()
    assert totals.subscription_usd == pytest.approx(38)  # two Copilot Business seats, one month
    assert totals.api_equivalent_usd > 0
    assert {m.model for m in report.unpriced_models} == {"mystery-model-1", None}
    by_id = {r.turn.id: r for r in report.rows}
    assert by_id["t1"].project_name == "atlas-api"
    assert by_id["t3"].project_name == "billing-svc"
