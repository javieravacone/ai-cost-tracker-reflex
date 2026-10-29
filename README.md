# BIS AI Cost Tracker (Reflex)

Python/Reflex port of the BIS AI Cost Tracker POC. Domain logic lives in `bis_core/`
(framework-independent, tested with pytest); the Reflex UI lives in `bis_cost_tracker/`.
The SQLite database is `data/app.db` (override with `DB_PATH`).

## Real data: reference tables

The Sync button and the sync scripts (`scripts/sync.py`, `scripts/sync_github.py`) only fill
`turns` (LangSmith) and issues / pull requests (GitHub). They **never** fill the reference
tables, and the costs depend on three of them:

| Cost input | Table | Without it |
|---|---|---|
| Seat plans (price per seat and month, included AI credits) | `seat_plans` | no subscription cost |
| Members (who has which seat, in which team) | `members` | the user's turns carry no subscription cost |
| Model prices (USD per 1M tokens, `prefix*` allowed) | `model_prices` | API-equivalent shows "no price" |

Teams, projects and repo mappings are only needed to group turns by team and project.

Do not run the seed to fill them: it wipes the database. Use `scripts/load_reference.py`
instead. It never deletes rows:

```bash
cp reference.example.json reference.json      # optional; edit plans, members and prices
.venv/bin/python scripts/load_reference.py --dry-run   # shows what would change
.venv/bin/python scripts/load_reference.py             # applies it
```

- Options: `--db` (default `$DB_PATH` or `data/app.db`), `--config` (default `reference.json`),
  `--no-auto`, `--dry-run`.
- Entries in `reference.json` overwrite existing rows. Sections missing from it fall back to
  built-in defaults (Copilot Business / Enterprise / Pro / Free and common model prices),
  which only insert rows that do not exist yet.
- `--auto` (on by default) derives from real LangSmith turns: teams from `team_id`, one project
  and repo mapping per repo (`owner/name`; Azure DevOps URLs become `org/repo`), and one member
  per user name with `default_seat_plan` (default `copilot-business`). Existing members and
  mappings are not changed by `--auto`.
- The summary lists members without a valid plan and models in real turns without a price.
  Fix them in `reference.json` and run the script again.
- The built-in prices are illustrative list prices. Check them against your GitHub contract and
  [GitHub Copilot models and pricing](https://docs.github.com/en/copilot/reference/copilot-billing/models-and-pricing).

The script uses only the Python standard library, so you can copy that one file to any
environment whose database uses the same schema (v3). `reference.json` is git-ignored because
it is company-specific.

## Tests

```bash
.venv/bin/pytest -q
```
