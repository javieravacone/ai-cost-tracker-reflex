"""Fetch issues + PRs (+ PR commits) for every mapped repo (port of scripts/sync-github.ts).

    .venv/bin/python scripts/sync_github.py                       # incremental per repo (state `github.<repo>.lastSync`)
    .venv/bin/python scripts/sync_github.py --full                # ignore stored state
    .venv/bin/python scripts/sync_github.py --repo=owner/name     # only one mapped repo

Reads GITHUB_TOKEN (and DB_PATH) from the environment or `.env.local`.
The logic lives in bis_core/sync (also used by the app's "Sync" button).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bis_core.db import close_db, get_db  # noqa: E402
from bis_core.github.client import get_github_config  # noqa: E402
from bis_core.sync import load_local_env, sync_github  # noqa: E402


def main() -> int:
    load_local_env()
    argv = sys.argv[1:]
    full = "--full" in argv
    only_arg = next((a[len("--repo=") :] for a in argv if a.startswith("--repo=")), None)
    only = only_arg.lower() if only_arg is not None else None

    get_github_config()  # fail fast with the usual message when GITHUB_TOKEN is missing
    results = sync_github(get_db(), full=full, repo=only, scope="mapped")
    if not results:
        print(
            f'Repo "{only}" is not mapped to any project.'
            if only
            else "No repo mappings found (run the seed or add mappings).",
            file=sys.stderr,
        )
        return 0

    failures = 0
    for r in results:
        if r.error:
            failures += 1
            print(f"{r.repo}: FAILED — {r.error}", file=sys.stderr)
        else:
            print(f"{r.repo}: {r.issues} issues, {r.pull_requests} PRs{f' (since {r.since})' if r.since else ''}")
    return 1 if failures > 0 else 0


if __name__ == "__main__":
    exit_code = 0
    try:
        exit_code = main()
    except Exception as err:  # noqa: BLE001 - CLI boundary: short message, no traceback
        print(f"sync:github failed: {err}", file=sys.stderr)
        exit_code = 1
    finally:
        close_db()
    sys.exit(exit_code)
