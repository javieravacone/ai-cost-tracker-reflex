"""SQLite schema for the local POC database (port of src/lib/db/schema.ts).

Idempotent: every statement uses IF NOT EXISTS so `migrate` can run on every open, and columns
added after v1 are back-filled with ALTER TABLE ADD COLUMN on existing databases
(see ADDED_COLUMNS).
"""

from __future__ import annotations

import sqlite3

# v2: AI-credit columns. v3: captured content tables (turn_content, turn_events, skill_usage).
SCHEMA_VERSION = 3

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS turns (
  id                    TEXT PRIMARY KEY,
  trace_id              TEXT NOT NULL,
  conversation_id       TEXT,
  started_at            TEXT NOT NULL,
  ended_at              TEXT,
  user_name             TEXT,
  team_id               TEXT,
  project_hint          TEXT,
  repo_url              TEXT,
  branch                TEXT,
  commit_sha            TEXT,
  github_org            TEXT,
  agent_name            TEXT,
  model                 TEXT,
  input_tokens          INTEGER NOT NULL DEFAULT 0,
  output_tokens         INTEGER NOT NULL DEFAULT 0,
  cache_read_tokens     INTEGER NOT NULL DEFAULT 0,
  cache_creation_tokens INTEGER NOT NULL DEFAULT 0,
  reasoning_tokens      INTEGER NOT NULL DEFAULT 0,
  llm_calls             INTEGER NOT NULL DEFAULT 0,
  tool_calls            INTEGER NOT NULL DEFAULT 0,
  copilot_nano_aiu      INTEGER,
  copilot_usage_coverage REAL,
  source                TEXT NOT NULL CHECK (source IN ('langsmith', 'seed'))
);
CREATE INDEX IF NOT EXISTS idx_turns_started_at ON turns(started_at);
CREATE INDEX IF NOT EXISTS idx_turns_conversation_id ON turns(conversation_id);
CREATE INDEX IF NOT EXISTS idx_turns_user_name ON turns(user_name);

CREATE TABLE IF NOT EXISTS teams (
  id   TEXT PRIMARY KEY,
  name TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS projects (
  id   TEXT PRIMARY KEY,
  name TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS repo_mappings (
  repo       TEXT PRIMARY KEY,
  project_id TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS members (
  user_name    TEXT PRIMARY KEY,
  display_name TEXT NOT NULL,
  team_id      TEXT NOT NULL,
  seat_plan_id TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS issues (
  repo       TEXT NOT NULL,
  number     INTEGER NOT NULL,
  title      TEXT NOT NULL,
  state      TEXT NOT NULL CHECK (state IN ('open', 'closed')),
  url        TEXT NOT NULL,
  created_at TEXT NOT NULL,
  closed_at  TEXT,
  PRIMARY KEY (repo, number)
);

CREATE TABLE IF NOT EXISTS pull_requests (
  repo          TEXT NOT NULL,
  number        INTEGER NOT NULL,
  title         TEXT NOT NULL,
  state         TEXT NOT NULL CHECK (state IN ('open', 'closed', 'merged')),
  head_branch   TEXT NOT NULL,
  url           TEXT NOT NULL,
  linked_issues TEXT NOT NULL DEFAULT '[]',
  commit_shas   TEXT NOT NULL DEFAULT '[]',
  created_at    TEXT NOT NULL,
  merged_at     TEXT,
  PRIMARY KEY (repo, number)
);
CREATE INDEX IF NOT EXISTS idx_pull_requests_head_branch ON pull_requests(head_branch);

CREATE TABLE IF NOT EXISTS model_prices (
  model                TEXT PRIMARY KEY,
  input_per_mtok       REAL NOT NULL,
  output_per_mtok      REAL NOT NULL,
  cache_read_per_mtok  REAL NOT NULL DEFAULT 0,
  cache_write_per_mtok REAL NOT NULL DEFAULT 0,
  premium_multiplier   REAL NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS seat_plans (
  id                              TEXT PRIMARY KEY,
  name                            TEXT NOT NULL,
  monthly_price_usd               REAL NOT NULL,
  included_premium_requests       INTEGER NOT NULL,
  overage_per_premium_request_usd REAL NOT NULL,
  included_ai_credits             INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS manual_assignments (
  turn_id      TEXT PRIMARY KEY REFERENCES turns(id) ON DELETE CASCADE,
  repo         TEXT NOT NULL,
  issue_number INTEGER,
  pr_number    INTEGER,
  note         TEXT
);

CREATE TABLE IF NOT EXISTS sync_state (
  key        TEXT PRIMARY KEY,
  value      TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

-- v3: captured content (only with Copilot content capture on). Replaced per turn on every sync.
CREATE TABLE IF NOT EXISTS turn_content (
  turn_id                TEXT PRIMARY KEY REFERENCES turns(id) ON DELETE CASCADE,
  user_prompt            TEXT,
  user_prompt_truncated  INTEGER NOT NULL DEFAULT 0,
  final_answer           TEXT,
  final_answer_truncated INTEGER NOT NULL DEFAULT 0,
  error                  TEXT,
  skills_json            TEXT NOT NULL DEFAULT '[]',
  feedback_json          TEXT,
  captured_at            TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS turn_events (
  turn_id          TEXT NOT NULL REFERENCES turns(id) ON DELETE CASCADE,
  seq              INTEGER NOT NULL,
  run_id           TEXT NOT NULL,
  trace_id         TEXT NOT NULL,
  kind             TEXT NOT NULL CHECK (kind IN ('llm', 'tool')),
  name             TEXT NOT NULL,
  started_at       TEXT,
  duration_ms      INTEGER,
  tokens_in        INTEGER,
  tokens_out       INTEGER,
  nano_aiu         INTEGER,
  text             TEXT,
  text_truncated   INTEGER NOT NULL DEFAULT 0,
  tool_calls       TEXT NOT NULL DEFAULT '[]',
  args             TEXT,
  args_truncated   INTEGER NOT NULL DEFAULT 0,
  result           TEXT,
  result_truncated INTEGER NOT NULL DEFAULT 0,
  error            TEXT,
  PRIMARY KEY (turn_id, seq)
);

-- One row per (turn, skill, version); version '' = unknown (legacy attribute or unreadable text).
CREATE TABLE IF NOT EXISTS skill_usage (
  turn_id TEXT NOT NULL REFERENCES turns(id) ON DELETE CASCADE,
  skill   TEXT NOT NULL,
  version TEXT NOT NULL DEFAULT '',
  path    TEXT,
  PRIMARY KEY (turn_id, skill, version)
);
CREATE INDEX IF NOT EXISTS idx_skill_usage_skill ON skill_usage(skill);
"""

# All data tables, ordered so that children come before parents (safe delete order).
TABLES: tuple[str, ...] = (
    "skill_usage",
    "turn_events",
    "turn_content",
    "manual_assignments",
    "turns",
    "repo_mappings",
    "members",
    "issues",
    "pull_requests",
    "model_prices",
    "seat_plans",
    "teams",
    "projects",
    "sync_state",
)

# Columns added after schema v1. `CREATE TABLE IF NOT EXISTS` does not touch existing tables, so
# databases created before them get the column via ALTER TABLE (no reseed needed). New columns
# must be nullable or have a DEFAULT (SQLite requirement for ADD COLUMN).
ADDED_COLUMNS: tuple[dict[str, str], ...] = (
    {"table": "turns", "column": "copilot_nano_aiu", "ddl": "INTEGER"},
    {"table": "turns", "column": "copilot_usage_coverage", "ddl": "REAL"},
    {"table": "seat_plans", "column": "included_ai_credits", "ddl": "INTEGER NOT NULL DEFAULT 0"},
)

# Monthly AI credits per seat for the plan ids this POC ships (seed / register-repo), back-filled
# once when `included_ai_credits` is first added so existing databases get a sensible pool.
# Other plans keep 0 until edited. Source: GitHub Copilot billing docs (2026).
KNOWN_PLAN_CREDITS: dict[str, int] = {
    "copilot-business": 1900,
    "copilot-enterprise": 3900,
    "copilot-free": 0,
}


def _columns_of(db: sqlite3.Connection, table: str) -> set[str]:
    return {str(r[1]) for r in db.execute(f"PRAGMA table_info({table})").fetchall()}


def migrate(db: sqlite3.Connection) -> None:
    db.executescript(SCHEMA_SQL)
    for added in ADDED_COLUMNS:
        table, column, ddl = added["table"], added["column"], added["ddl"]
        if column in _columns_of(db, table):
            continue
        db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")
        if table == "seat_plans" and column == "included_ai_credits":
            for plan_id, credits in KNOWN_PLAN_CREDITS.items():
                db.execute("UPDATE seat_plans SET included_ai_credits = ? WHERE id = ?", (credits, plan_id))
    db.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
