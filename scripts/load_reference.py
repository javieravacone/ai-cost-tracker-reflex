#!/usr/bin/env python3
"""Load reference tables (seat plans, model prices, teams, projects, repo mappings, members)
into an existing AI Cost Tracker database WITHOUT reseeding.

LangSmith (and the app's Sync button / sync scripts) only fill `turns`. The three cost inputs
come from reference tables: `seat_plans` (subscription), `members` (who has which seat) and
`model_prices` (API-equivalent). This script fills them from a JSON config plus, with --auto,
from the real turns already in the database. It never deletes anything.

    python scripts/load_reference.py --dry-run                 # show what would change
    python scripts/load_reference.py                           # apply
    python scripts/load_reference.py --db path/to/app.db --config reference.json --no-auto

Self-contained on purpose (Python standard library only, no `bis_core` import): copy this one
file to any environment whose database uses schema v3.

Write rules:
- Entries from the config file overwrite existing rows (INSERT ... ON CONFLICT DO UPDATE).
- Built-in defaults (used for a section missing from the config) and --auto derivations only
  insert rows that do not exist yet; existing rows are never overwritten by them.

Repo rule (--auto): repo_url -> lowercase "owner/name". https/http/ssh/git URLs, scp-like
`git@host:owner/name.git` and GitHub Enterprise hosts keep the first two path segments (host
dropped, ".git" removed). Azure DevOps (`dev.azure.com/{org}/{project}/_git/{repo}`,
`{org}.visualstudio.com/[DefaultCollection/]{project}/_git/{repo}`,
`git@ssh.dev.azure.com:v3/{org}/{project}/{repo}`) -> "{org}/{repo}". The app itself currently
reads Azure URLs as the first two path segments, so for Azure repos an extra mapping under the
app's key is added when that key is unambiguous (see the summary warnings).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Built-in defaults.
# ILLUSTRATIVE LIST PRICES ONLY. Check them against your company's GitHub contract and
# https://docs.github.com/en/copilot/reference/copilot-billing/models-and-pricing
# before trusting any cost figure. Override them in reference.json.

DEFAULT_SEAT_PLAN = "copilot-business"
DEFAULT_TEAM = "unassigned"

DEFAULT_SEAT_PLANS = [
    # included_premium_requests / overage_per_premium_request_usd = legacy premium-request model.
    {"id": "copilot-business", "name": "Copilot Business", "monthly_price_usd": 19, "included_premium_requests": 300, "overage_per_premium_request_usd": 0.04, "included_ai_credits": 1900},
    {"id": "copilot-enterprise", "name": "Copilot Enterprise", "monthly_price_usd": 39, "included_premium_requests": 1000, "overage_per_premium_request_usd": 0.04, "included_ai_credits": 3900},
    {"id": "copilot-pro", "name": "Copilot Pro", "monthly_price_usd": 10, "included_premium_requests": 300, "overage_per_premium_request_usd": 0.04, "included_ai_credits": 1500},
    {"id": "copilot-free", "name": "Copilot Free", "monthly_price_usd": 0, "included_premium_requests": 50, "overage_per_premium_request_usd": 0, "included_ai_credits": 0},
]

# USD per 1M tokens + legacy Copilot premium multiplier. Entries ending in "*" are prefixes
# (longest prefix wins; an exact match always wins), same rule as the app.
DEFAULT_MODEL_PRICES = [
    {"model": "gpt-4.1", "input_per_mtok": 2, "output_per_mtok": 8, "cache_read_per_mtok": 0.5, "cache_write_per_mtok": 0, "premium_multiplier": 0},
    {"model": "gpt-5-mini", "input_per_mtok": 0.25, "output_per_mtok": 2, "cache_read_per_mtok": 0.025, "cache_write_per_mtok": 0, "premium_multiplier": 0},
    {"model": "gpt-5*", "input_per_mtok": 1.25, "output_per_mtok": 10, "cache_read_per_mtok": 0.125, "cache_write_per_mtok": 0, "premium_multiplier": 1},
    {"model": "claude-sonnet-4*", "input_per_mtok": 3, "output_per_mtok": 15, "cache_read_per_mtok": 0.3, "cache_write_per_mtok": 3.75, "premium_multiplier": 1},
    {"model": "claude-opus-4*", "input_per_mtok": 15, "output_per_mtok": 75, "cache_read_per_mtok": 1.5, "cache_write_per_mtok": 18.75, "premium_multiplier": 10},
    {"model": "gemini-2.5-pro", "input_per_mtok": 1.25, "output_per_mtok": 10, "cache_read_per_mtok": 0.31, "cache_write_per_mtok": 0, "premium_multiplier": 1},
    {"model": "gpt-6-luna", "input_per_mtok": 0.1, "output_per_mtok": 0.5, "cache_read_per_mtok": 0.01, "cache_write_per_mtok": 0.125, "premium_multiplier": 0},
    {"model": "gpt-6*", "input_per_mtok": 0.1, "output_per_mtok": 0.5, "cache_read_per_mtok": 0.01, "cache_write_per_mtok": 0.125, "premium_multiplier": 0},
]

# table -> (key column, {column: (type, default or REQUIRED)}) — schema v3 column names.
REQUIRED = object()
TABLES = {
    "seat_plans": ("id", {"id": (str, REQUIRED), "name": (str, REQUIRED), "monthly_price_usd": (float, REQUIRED), "included_premium_requests": (int, 0), "overage_per_premium_request_usd": (float, 0.0), "included_ai_credits": (int, 0)}),
    "model_prices": ("model", {"model": (str, REQUIRED), "input_per_mtok": (float, REQUIRED), "output_per_mtok": (float, REQUIRED), "cache_read_per_mtok": (float, 0.0), "cache_write_per_mtok": (float, 0.0), "premium_multiplier": (float, 0.0)}),
    "teams": ("id", {"id": (str, REQUIRED), "name": (str, REQUIRED)}),
    "projects": ("id", {"id": (str, REQUIRED), "name": (str, REQUIRED)}),
    "repo_mappings": ("repo", {"repo": (str, REQUIRED), "project_id": (str, REQUIRED)}),
    "members": ("user_name", {"user_name": (str, REQUIRED), "display_name": (str, REQUIRED), "team_id": (str, REQUIRED), "seat_plan_id": (str, REQUIRED)}),
}
TURN_COLUMNS = ("source", "user_name", "team_id", "repo_url", "model")


class ConfigError(Exception):
    pass


# ---------------------------------------------------------------------------
# Repo normalization (mirror of bis_core.attribution.repo.normalize_repo + Azure DevOps).

_OWNER_RE = re.compile(r"[a-z0-9](?:[a-z0-9_-]*[a-z0-9_])?")
_NAME_RE = re.compile(r"[a-z0-9._-]+")
_URL_RE = re.compile(r"^[a-z][a-z0-9+.-]*://(?:[^@/]+@)?([^/]+)/(.*)\Z", re.IGNORECASE | re.DOTALL)
_SCHEME_RE = re.compile(r"^[a-z][a-z0-9+.-]*://", re.IGNORECASE)
_SCP_RE = re.compile(r"^[^@/\s:]+@([^/\s:]+):(.*)\Z", re.DOTALL)


def _host_and_path(value: str) -> tuple[str, str] | None:
    m = _URL_RE.match(value) or _SCP_RE.match(value)
    if m:
        return m.group(1).lower(), m.group(2)
    if _SCHEME_RE.match(value):
        return None
    segs = [s for s in value.split("/") if s]
    if len(segs) >= 3 and "." in segs[0]:
        return segs[0].lower(), "/".join(segs[1:])
    return "", value


def _owner_name(owner: str, name: str) -> str | None:
    owner, name = owner.lower(), re.sub(r"\.git\Z", "", name.lower())
    if not _OWNER_RE.fullmatch(owner) or not _NAME_RE.fullmatch(name) or name in (".", ".."):
        return None
    return f"{owner}/{name}"


def _segments(path: str) -> list[str]:
    return [s for s in re.sub(r"[?#].*\Z", "", path, flags=re.DOTALL).split("/") if s]


def app_repo_key(url: str | None) -> str | None:
    """What the app computes today: first two path segments, lowercase (normalize_repo)."""
    value = (url or "").strip()
    if not value or re.search(r"\s", value):
        return None
    hp = _host_and_path(value)
    segs = _segments(hp[1]) if hp else []
    return _owner_name(segs[0], segs[1]) if len(segs) >= 2 else None


def repo_key(url: str | None) -> str | None:
    """Canonical "owner/name"; Azure DevOps URLs become "org/repo"."""
    value = (url or "").strip()
    hp = _host_and_path(value) if value and not re.search(r"\s", value) else None
    if hp:
        host, segs = hp[0].split(":")[0], _segments(hp[1])
        if host.endswith("dev.azure.com"):  # dev.azure.com or ssh.dev.azure.com (v3/org/project/repo)
            segs = segs[1:] if segs and segs[0].lower() == "v3" else segs
            if len(segs) >= 4 and segs[2] == "_git":
                return _owner_name(segs[0], segs[3])
            if len(segs) == 3:
                return _owner_name(segs[0], segs[2])
        elif host.endswith("visualstudio.com"):  # {org}.visualstudio.com or vs-ssh (v3/org/project/repo)
            if "_git" in segs and segs.index("_git") + 1 < len(segs):
                return _owner_name(host.split(".")[0], segs[segs.index("_git") + 1])
            if len(segs) == 4 and segs[0].lower() == "v3":
                return _owner_name(segs[1], segs[3])
    return app_repo_key(value)


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "repo"


def _fold(v: str) -> str:
    return v.strip().lower()


# ---------------------------------------------------------------------------
# Config + state


def load_config(path: Path) -> tuple[dict, bool]:
    if not path.exists():
        return {}, False
    try:
        cfg = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ConfigError(f"{path}: invalid JSON ({e})") from e
    if not isinstance(cfg, dict):
        raise ConfigError(f"{path}: top level must be an object")
    return cfg, True


def coerce(table: str, entry: dict, where: str) -> dict:
    """Validates one config entry against the table columns (keys starting with "_" ignored)."""
    if not isinstance(entry, dict):
        raise ConfigError(f"{where}: expected an object, got {entry!r}")
    cols = TABLES[table][1]
    unknown = [k for k in entry if not k.startswith("_") and k not in cols]
    if unknown:
        raise ConfigError(f"{where}: unknown field(s) {unknown}; expected {list(cols)}")
    row = {}
    for col, (typ, default) in cols.items():
        value = entry.get(col, default)
        if value is REQUIRED or value is None:
            raise ConfigError(f"{where}: missing required field '{col}'")
        try:
            row[col] = typ(value) if typ is not str else str(value).strip()
        except (TypeError, ValueError) as e:
            raise ConfigError(f"{where}: field '{col}' must be {typ.__name__}, got {value!r}") from e
    return row


class Plan:
    """In-memory copy of the reference tables; records every change so --dry-run never writes."""

    def __init__(self, db: sqlite3.Connection) -> None:
        self.rows: dict[str, dict[str, dict]] = {}
        for table, (key, cols) in TABLES.items():
            cur = db.execute(f"SELECT {', '.join(cols)} FROM {table}")
            self.rows[table] = {_fold(r[0]): dict(zip(cols, r)) for r in cur.fetchall()}
        self.ops: list[tuple[str, dict, bool]] = []
        self.log: list[str] = []
        self.counts = {t: {"inserted": 0, "updated": 0} for t in TABLES}

    def get(self, table: str, key: str) -> dict | None:
        return self.rows[table].get(_fold(key))

    def put(self, table: str, row: dict, overwrite: bool) -> None:
        key_col = TABLES[table][0]
        old = self.get(table, row[key_col])
        if old is not None:
            row = {**row, key_col: old[key_col]}  # keep the stored spelling of the key
            if not overwrite or old == row:
                return
            diff = ", ".join(f"{c}: {old[c]!r} -> {row[c]!r}" for c in row if old[c] != row[c])
            self.log.append(f"  ~ {table} {row[key_col]}: {diff}")
            self.counts[table]["updated"] += 1
        else:
            self.log.append(f"  + {table} {row[key_col]}: " + ", ".join(f"{c}={v!r}" for c, v in row.items() if c != key_col))
            self.counts[table]["inserted"] += 1
        self.rows[table][_fold(row[key_col])] = row
        self.ops.append((table, row, overwrite))

    def apply(self, db: sqlite3.Connection) -> None:
        with db:  # one transaction
            for table, row, overwrite in self.ops:
                key_col, cols = TABLES[table][0], list(row)
                action = "DO UPDATE SET " + ", ".join(f"{c} = excluded.{c}" for c in cols if c != key_col) if overwrite else "DO NOTHING"
                db.execute(
                    f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)}) ON CONFLICT({key_col}) {action}",
                    [row[c] for c in cols],
                )


def check_schema(db: sqlite3.Connection) -> None:
    needed = {t: set(c) for t, (_, c) in TABLES.items()}
    needed["turns"] = set(TURN_COLUMNS)
    problems = []
    for table, cols in needed.items():
        have = {r[1] for r in db.execute(f"PRAGMA table_info({table})")}
        if not have:
            problems.append(f"missing table '{table}'")
        elif cols - have:
            problems.append(f"table '{table}' lacks column(s) {sorted(cols - have)}")
    if problems:
        raise ConfigError("database does not have the expected schema (v3): " + "; ".join(problems) + ". Open it once with the app (or run a sync) to create the schema.")


def price_for(model: str | None, prices: list[str]) -> str | None:
    """Same resolution as the app: exact (case-insensitive) match, else longest "prefix*"."""
    m = _fold(model or "")
    if not m:
        return None
    if m in prices:
        return m
    best = [p for p in prices if p.endswith("*") and m.startswith(p[:-1])]
    return max(best, key=len) if best else None


# ---------------------------------------------------------------------------
# Main


def build_plan(db: sqlite3.Connection, cfg: dict, auto: bool) -> tuple[Plan, list[str]]:
    plan, warnings = Plan(db), []
    default_plan = str(cfg.get("default_seat_plan") or DEFAULT_SEAT_PLAN)
    default_team = str(cfg.get("default_team") or DEFAULT_TEAM)
    config_teams = [coerce("teams", t, f"teams[{i}]") for i, t in enumerate(cfg.get("teams") or [])]
    config_team_names = {_fold(t["id"]): t["name"] for t in config_teams}

    for table, defaults in (("seat_plans", DEFAULT_SEAT_PLANS), ("model_prices", DEFAULT_MODEL_PRICES)):
        if table in cfg:
            for i, entry in enumerate(cfg[table] or []):
                plan.put(table, coerce(table, entry, f"{table}[{i}]"), overwrite=True)
        else:
            for entry in defaults:
                plan.put(table, coerce(table, entry, f"default {table}"), overwrite=False)
    for table in ("teams", "projects"):
        for i, entry in enumerate(cfg.get(table) or []):
            plan.put(table, coerce(table, entry, f"{table}[{i}]"), overwrite=True)
    for i, entry in enumerate(cfg.get("repo_mappings") or []):
        row = coerce("repo_mappings", entry, f"repo_mappings[{i}]")
        row["repo"] = repo_key(row["repo"]) or _fold(row["repo"])
        plan.put("repo_mappings", row, overwrite=True)

    turns = db.execute("SELECT user_name, team_id, repo_url FROM turns WHERE source = 'langsmith'").fetchall()
    user_teams: dict[str, set] = {}
    for user, team, _ in turns:
        if user:
            user_teams.setdefault(user.strip(), set()).update([team] if team else [])

    def ensure_team(team_id: str) -> None:
        name = config_team_names.get(_fold(team_id)) or ("Unassigned" if team_id == DEFAULT_TEAM else team_id)
        plan.put("teams", {"id": team_id, "name": name}, overwrite=False)

    def derived_team(user: str) -> str:
        teams = {t for u, ts in user_teams.items() if _fold(u) == _fold(user) for t in ts}
        return teams.pop() if len(teams) == 1 else default_team

    for i, entry in enumerate(cfg.get("members") or []):
        if not isinstance(entry, dict) or not entry.get("user_name"):
            raise ConfigError(f"members[{i}]: missing required field 'user_name'")
        old = plan.get("members", str(entry["user_name"])) or {}
        merged = {
            "user_name": str(entry["user_name"]).strip(),
            "display_name": entry.get("display_name") or old.get("display_name") or str(entry["user_name"]).strip(),
            "team_id": entry.get("team_id") or old.get("team_id") or derived_team(str(entry["user_name"])),
            "seat_plan_id": entry.get("seat_plan_id") or old.get("seat_plan_id") or default_plan,
        }
        row = coerce("members", {**entry, **merged}, f"members[{i}]")
        ensure_team(row["team_id"])
        plan.put("members", row, overwrite=True)

    if auto:
        for team in sorted({t for _, t, _ in turns if t}):
            ensure_team(team)
        by_app_key: dict[str, set] = {}
        for url in sorted({u for _, _, u in turns if u}):
            canonical, app_key = repo_key(url), app_repo_key(url)
            if canonical is None:
                warnings.append(f"repo_url not recognized, skipped: {url}")
                continue
            if app_key and app_key != canonical:
                by_app_key.setdefault(app_key, set()).add(canonical)
            if plan.get("repo_mappings", canonical):
                continue
            name = canonical.split("/", 1)[1]
            plan.put("projects", {"id": slug(name), "name": name}, overwrite=False)
            plan.put("repo_mappings", {"repo": canonical, "project_id": slug(name)}, overwrite=False)
        for app_key, canonicals in sorted(by_app_key.items()):
            if len(canonicals) == 1:
                canonical = next(iter(canonicals))
                if plan.get("repo_mappings", app_key) is None:
                    target = plan.get("repo_mappings", canonical)
                    plan.put("repo_mappings", {"repo": app_key, "project_id": target["project_id"]}, overwrite=False)
                    warnings.append(f"Azure DevOps repo {canonical}: the app reads it as '{app_key}', mapped that key too")
            else:
                warnings.append(f"Azure DevOps repos {sorted(canonicals)} all read as '{app_key}' by the app; not mapped (ambiguous)")
        for user in sorted(user_teams, key=_fold):
            if plan.get("members", user) is None:
                team = derived_team(user)
                ensure_team(team)
                plan.put("members", {"user_name": user, "display_name": user, "team_id": team, "seat_plan_id": default_plan}, overwrite=False)

    if plan.get("seat_plans", default_plan) is None:
        warnings.append(f"default_seat_plan '{default_plan}' is not a seat plan")
    return plan, warnings


def summarize(db: sqlite3.Connection, plan: Plan, warnings: list[str], dry_run: bool, config_path: Path, config_found: bool) -> None:
    print("DRY RUN: nothing was written." if dry_run else "Applied.")
    print(f"Config: {config_path}" + ("" if config_found else " (not found, built-in defaults used)"))
    print("Changes:" if plan.log else "Changes: none (everything already up to date)")
    for line in plan.log:
        print(line)
    print("Summary (" + ("would be " if dry_run else "") + "inserted / updated):")
    for table, c in plan.counts.items():
        print(f"  {table:<14} {c['inserted']:>4} / {c['updated']:>4}   (total after: {len(plan.rows[table])})")

    plans = set(plan.rows["seat_plans"])
    no_plan = [m["user_name"] for m in plan.rows["members"].values() if _fold(m["seat_plan_id"]) not in plans]
    users = {_fold(u): u for (u,) in db.execute("SELECT DISTINCT user_name FROM turns WHERE source = 'langsmith' AND user_name IS NOT NULL")}
    no_member = [u for k, u in users.items() if k not in plan.rows["members"]]
    print("Members without a valid seat plan: " + (", ".join(sorted(no_plan)) or "none"))
    print("Real-turn users without a member row (no subscription cost): " + (", ".join(sorted(no_member)) or "none"))
    prices = list(plan.rows["model_prices"])
    unpriced = [(m or "(no model)", n) for m, n in db.execute("SELECT model, COUNT(*) FROM turns WHERE source = 'langsmith' GROUP BY model ORDER BY 2 DESC") if price_for(m, prices) is None]
    print("Models in real turns without a price: " + (", ".join(f"{m} ({n} turns)" for m, n in unpriced) or "none"))
    for w in warnings:
        print(f"Warning: {w}")
    print("Hint: edit reference.json (see reference.example.json) for real plans, members and prices, then run again.")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Load reference tables without reseeding.")
    ap.add_argument("--db", default=os.environ.get("DB_PATH") or "data/app.db", help="SQLite database (default: $DB_PATH or data/app.db)")
    ap.add_argument("--config", default="reference.json", help="JSON config (default: reference.json; built-in defaults if missing)")
    ap.add_argument("--auto", action=argparse.BooleanOptionalAction, default=True, help="derive teams, projects, repo mappings and members from real turns (default: on)")
    ap.add_argument("--dry-run", action="store_true", help="print what would change, write nothing")
    args = ap.parse_args(argv)

    db_path, config_path = Path(args.db), Path(args.config)
    if not db_path.is_file():
        print(f"error: database not found: {db_path}", file=sys.stderr)
        return 2
    uri = f"{db_path.resolve().as_uri()}?mode=ro" if args.dry_run else str(db_path)
    db = sqlite3.connect(uri, uri=args.dry_run)
    try:
        db.execute("PRAGMA busy_timeout = 5000")
        check_schema(db)
        cfg, found = load_config(config_path)
        plan, warnings = build_plan(db, cfg, args.auto)
        if not args.dry_run:
            plan.apply(db)
        summarize(db, plan, warnings, args.dry_run, config_path, found)
        return 0
    except (ConfigError, sqlite3.DatabaseError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
