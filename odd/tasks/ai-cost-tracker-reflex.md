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
| R1 | Core domain: db (schema v3 + all queries), attribution, cost, links, format, markdown, report (index, people, skills) + ported tests | delegated (writer) | [ ] |
| R2 | Integrations: LangSmith client/map/content, GitHub client/parse, db content layer, sync (+ CLI scripts) + ported tests | delegated (writer, parallel with R1) | [ ] |
| R3 | Reflex UI: shell, design system, all pages, Sync button, manual assignment, transcript | delegated (writer, after R1+R2) | [ ] |
| R4 | Parity check: side-by-side screenshots and route/feature checklist vs Next app; fix gaps | delegated + inline | [ ] |

## Acceptance
Every page of the Next app exists in Reflex with the same numbers for the same DB and period,
the same links and the same look (screenshots side by side). Ported tests green.

## Progress / evidence
- R0: Reflex 0.10.0 installed; compile OK. DB copied with VACUUM INTO (user_version 3,
  langsmith:21 seed:3000, turn_content 21, turn_events 117). Plain file copy lost WAL changes.

## Next step
Launch R1 and R2 in parallel.
