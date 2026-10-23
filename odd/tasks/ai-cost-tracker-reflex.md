# ai-cost-tracker-reflex — identical port of the BIS AI Cost Tracker to Reflex

## Objective
Rebuild the BIS AI Cost Tracker POC (`~/code/ai-cost-tracker`, Next.js 16 + TypeScript, main @ 8724217)
as an identical app in Reflex (pure Python), to show the BIS it can live on company technology.

## Why
The BIS asked whether the POC can move to https://reflex.dev. Python fits the team (dbt, Dagster,
SQL Server). An identical copy proves feasibility and measures the real effort.

## Scope
- Same pages, routes, data, behaviour and look: Overview `/`, `/equipos`, `/equipos/[id]`,
  `/proyectos`, `/personas`, `/personas/[user]`, `/issues`, `/prs`, `/sesiones`, `/sesiones/[id]`,
  `/skills`, `/ajustes`, not-found; English UI, en-US formatting; BIS red, logo, sidebar, glass,
  period selector, Sync button with last sync time, manual assignment, collapsible transcript,
  GitHub/LangSmith links.
- Same SQLite schema v3 and data: `data/app.db` is a consistent copy (VACUUM INTO) of the Next
  app DB (21 real turns, 3,000 seed turns, content for 3 turns). `DB_PATH` env overrides.
- Same sync (LangSmith + GitHub) with the same `.env.local` variables.
- Domain logic as a framework-independent package `bis_core/` with pytest; Reflex only for UI
  in `bis_cost_tracker/`.

## Out of scope
New features, auth/SSO, deployment, SQL Server (later), deleting or changing the Next app.

## Constraints / evidence
- Reflex 0.10.0 on Python 3.12 venv `.venv`; `reflex init --template blank` works; first
  `reflex run` compiled in ~10 s (bun + npm packages downloaded fine on this machine).
- Plugins: TailwindV4Plugin, RadixThemesPlugin, SitemapPlugin.
- Reflex skills (docs) cloned read-only at /tmp/opencode/reflex-agent-skills/skills (not installed).
- Shared contract `bis_core/types.py` (snake_case port of types.ts + content-types.ts).
- Source of truth for behaviour: the TS code and its 316 tests in ~/code/ai-cost-tracker.

## Mode
- TDD: off (no project config). Checks: `.venv/bin/pytest`, `reflex run` compile, page
  smoke (HTTP 200) and side-by-side screenshots against the Next app on :3000.
- RDD: on (default).
- Delivery: local repo only for now (push/remote is the user's decision).

## Tasks
| ID | Task | Route | Status |
|----|------|-------|--------|
| R0 | Scaffold, venv, Reflex init + compile check, DB copy, types contract | inline | [x] |
| R1 | Core domain: db (schema v3 + all queries), attribution, cost, links, format, markdown, report (index, people, skills) + ported tests | delegated (writer) | [x] |
| R2 | Integrations: LangSmith client/map/content, GitHub client/parse, db content layer, sync (+ CLI scripts) + ported tests | delegated (writer, parallel with R1) | [x] |
| R3 | Reflex UI: shell, design system, all pages, Sync button, manual assignment, transcript | delegated (writer, after R1+R2) | [x] |
| R4 | Parity check: side-by-side screenshots and route/feature checklist vs Next app; fix gaps | delegated + inline | [x] |

## Acceptance
Every page of the Next app exists in Reflex with the same numbers for the same DB and period,
the same links and the same look (screenshots side by side). Ported tests green.

## Progress / evidence
- R0: Reflex 0.10.0 installed; compile OK. DB copied with VACUUM INTO (user_version 3,
  langsmith:21 seed:3000, turn_content 21, turn_events 117). Plain file copy lost WAL changes.

- R1 (5aa05a2, d30d2b2, d32df70): bis_core db/attribution/cost/report/links/markdown/app_data; 276 core tests; parity with TS on a DB copy for 7/30/90/all windows (e.g. 30d: 1,344 turns, 18,334 credits, $205.08 API, $330.43 subscription, 76.7% with issue) with a gzipped TS reference fixture.
- R2 (efdf8dc): LangSmith/GitHub clients, map, content, db content, sync, CLI scripts; 79 integration tests; real --full sync on a copy produced rows byte-identical to the Next app (21 turns, 21 content, 117 events, 3 skills). `app.lastSync` keeps the TS camelCase shape so both apps share state.
- Full suite: 355 passed.

- R3 (283cda5 … 7f94275): first run interrupted, partial work committed (283cda5), second run finished all routes. views/ = pure data builders, pages/ = Reflex components + per-page State, components/ = shell + kit, assets/styles.css = ported tokens. rxconfig excludes data/ from hot reload (SQLite WAL changes were restarting the backend). 375 tests.
- R4: headless screenshots of all 12 pages + 404, expanded rows, ?turn=, dark mode compared with the Next app at 1440x1000: same numbers, copy and layout (0 or 1-px pixel diffs on most pages). Manual assignment verified (save, error). Screenshots /tmp/opencode/rx/ vs /tmp/opencode/ref/.
- Known differences: "Last synced" label computed on load (Next refreshes every 30 s, server time zone); unknown routes return 200 in dev; markdown link with bold text splits into adjacent links; expanded rows survive client-side period change. Sync spinner/toast not seen live (logic unit-tested with stubbed run_full_sync).
- Size: Python core 7,283 lines vs TS lib 5,303; Reflex UI 6,445 + 488 CSS vs Next UI 6,428; tests 4,899.

- Published (2026-10-21): private repo https://github.com/javieravacone/ai-cost-tracker-reflex; main @ 6207169 (scaffold), feat/port @ 7ad2cf8; PR #1 feat/port → main open. Secret scan clean; .env.local and data/ ignored. The gzipped parity fixture contains local file paths (/home/<user>/…) from captured transcripts — kept (private repo; sanitizing would break the parity test against the real DB).
- Storage decision: stay on SQLite (user, 2026-10-21).

## Next step
User decision: push to a GitHub repo, SQL Server backend, or packaging for the BIS (npm/bun build inside BIS network is the main open risk).
