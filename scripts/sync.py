"""Incremental LangSmith -> SQLite sync of Copilot Chat turns (port of scripts/sync.ts).

    .venv/bin/python scripts/sync.py                              # since stored `langsmith.lastStartTime` (minus overlap), else 30 days
    .venv/bin/python scripts/sync.py --since=2026-10-01T00:00:00Z
    .venv/bin/python scripts/sync.py --full                       # ignore stored state, re-sync the last 30 days

Reads LANGSMITH_* (and DB_PATH) from the environment or `.env.local`.
The logic lives in bis_core/sync (also used by the app's "Sync" button).
"""

from __future__ import annotations

import re
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bis_core.db import close_db, get_db  # noqa: E402
from bis_core.langsmith.map import iso_utc, parse_iso  # noqa: E402
from bis_core.sync import LANGSMITH_STATE_KEY, LangSmithWindow, load_local_env, sync_langsmith  # noqa: E402


def parse_date(value: str) -> datetime | None:
    """`new Date(value)`: date-only and zoned values are UTC/explicit; naive date-times are local."""
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value) or re.search(r"([zZ]|[+-]\d\d:?\d\d)$", value):
        return parse_iso(value)
    try:
        return datetime.fromisoformat(value).astimezone()
    except ValueError:
        return None


def parse_args(argv: list[str]) -> tuple[datetime | None, bool]:
    since_arg = next((a[len("--since=") :] for a in argv if a.startswith("--since=")), None)
    since = parse_date(since_arg) if since_arg else None
    if since_arg and since is None:
        raise ValueError(f'Invalid --since value "{since_arg}" (expected ISO 8601)')
    return since, "--full" in argv


def on_start(w: LangSmithWindow) -> None:
    print(f'LangSmith project "{w.project}" @ {w.endpoint}')
    print(f"Window: {iso_utc(w.start)} -> {iso_utc(w.end)}{' (incremental)' if w.incremental else ''}")


def main() -> None:
    load_local_env()
    since, full = parse_args(sys.argv[1:])
    r = sync_langsmith(get_db(), full=full, since=since, on_start=on_start)

    print(f"Runs fetched: {r.runs}")
    print(f"Turns (invoke_agent): {r.turns}  upserted: {r.upserted}  new: {r.new_turns}")
    print(f"  with repo: {r.with_repo}  with tokens: {r.with_tokens}")
    print(f"  with content: {r.with_content}  agent steps: {r.events}  with skills: {r.with_skills}")
    print(f"State {LANGSMITH_STATE_KEY} = {r.state if r.state is not None else '(unset)'}")

    if r.runs > 0 and r.turns == 0:
        print("WARN: runs found but no invoke_agent turns — check run names/attributes (T1 mapping).", file=sys.stderr)
    elif r.turns > 0 and r.with_repo == 0:
        print(
            "WARN: no turn has github.copilot.git.repository — attribute location unverified (T1).", file=sys.stderr
        )


if __name__ == "__main__":
    exit_code = 0
    try:
        main()
    except Exception as err:  # noqa: BLE001 - CLI boundary: short message, no traceback
        print(f"sync failed: {err}", file=sys.stderr)
        exit_code = 1
    finally:
        close_db()
    sys.exit(exit_code)
