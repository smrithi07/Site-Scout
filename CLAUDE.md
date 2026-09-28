# CLAUDE.md — Savo SiteScout

This file is the entry point for Claude Code on this repo. Read it first, every session.
Detailed design lives in `docs/` — read the relevant doc before touching that part of the system.

## What this is

**Savo SiteScout**: an expansion-intelligence platform for Savomart (neighbourhood grocery,
Chennai). Built solo for a 48-hour hackathon (Mon 28 Sep 2026 09:00 IST → Wed 30 Sep 2026
09:00 IST, git commit history is the timing evidence). Full problem statement: `docs/BRIEF.md`.

Four personas share one product: BD Manager, BD Executive, Survey Manager, Survey Executive.
The core loop: pick an area → get an Area Fitness Report → scout properties → evaluate them →
request a catchment study → survey it → roll the survey up into a re-evaluation. See
`docs/DESIGN.md` for the full workflow and every locked decision.

## How to work with me (the user)

- **One phase at a time.** Per phase: (1) 2–3 lines on what/why, (2) files to create/change,
  (3) create the files directly with file tools — never `cat` heredocs, (4) exact commands to
  run, (5) expected output/checkpoint, (6) **stop and wait for the result.** Do not start the
  next phase until told to.
- **On error reports:** diagnose the actual cause, explain briefly, give the smallest fix and
  the exact rerun command. Don't touch unrelated code.
- **On undecided technical choices:** compare options on accuracy, simplicity, latency,
  feasibility, debugging, deployment. Benchmark, don't assume. No premature optimization.
- **Be concise.** Explain concepts only when asked. Don't over-produce prose when asked for
  design only, no code.
- **Commit at the end of every phase** with a descriptive message. Never commit secrets;
  `.env.example` only, real values in git-ignored `.env`.
- **Correctness and product quality over speed.** Finish the M1→M3 loop before any bonus.
  Every phase must hit its checkpoint before the next starts.

## Locked stack

- **Backend:** FastAPI (Python) — not Flask, this was corrected mid-session.
- **Frontend:** React + Vite + Tailwind + MapLibre GL.
- **DB:** PostgreSQL + PostGIS.
- **Spatial index:** H3 (res 8 for area analysis/selection display, res 9 internally for finer
  scoring — see `docs/DESIGN.md` §Spatial design for the exact split).
- **Async work:** a `jobs` table in Postgres + a worker process (same codebase, polls with row
  locking + heartbeat). No Celery/Redis — see `docs/DESIGN.md` for the comparison that decided this.
- **LLM:** provider-swappable adapter, chosen by env var. Gemini default, Groq fallback, then a
  deterministic template. The LLM only narrates a code-built fact sheet — never calculates or
  invents numbers. A validator checks every number/name traces to the sheet.
- **Containerization:** Docker Compose (postgis, api, worker, web).
- **Auth:** four seeded demo users + a role switcher (bearer token per user). No real auth system
  — access control is still real and server-side (role checks + per-role field masking).
- **Brand colours (mandatory):** `#782B90` purple (primary), `#FFF200` yellow (CTAs/highlights
  only — check contrast).
- **Region:** Greater Chennai Corporation via one configurable service-area polygon. Metro fringe
  (Tambaram, Avadi, etc.) added only if Phase 2's data-quality gate passes — see `docs/DATA.md`.

## Where things live

```
config/sitescout.yaml      # weights, thresholds, radii, freshness, caps — versioned
data/raw/                  # gitignored downloads (see docs/DATA.md for manifest)
data/MANIFEST.md           # citation-ready record of every dataset used, with dates/licences
backend/app/
  core/                    # settings, config loader, db, auth/roles, audit, errors
  models/                  # tables (GeoAlchemy2)
  schemas/                 # request/response models, PER-ROLE MASKING BUILDERS LIVE HERE
  api/                     # thin routers per domain — business logic does NOT live here
  services/                # all business rules: selection, scoring, evaluation, pipeline,
                            #   dedupe, reuse, units, rollup, diff
  jobs/                    # queue, worker loop, step runners
  llm/                     # adapter, gemini, groq, template, factsheet, validator
backend/ingest/             # offline CLI — loads OSM/census/pincode/stores into PostGIS.
                            #   NEVER called at request/analysis time.
frontend/src/
  features/                # areas, opportunities, scouting, properties, pipeline, studies,
                            #   units, capture — one per persona-facing workflow
```

## Non-negotiable system rules

These apply everywhere, not just in the phase they were designed for. Full rationale in
`docs/DESIGN.md` §Core rules.

1. **Provenance on every value**: observed / proxy / mock / missing. Missing is never scored
   as zero. Unavailable factors are excluded and weights renormalized. If too much weight is
   missing (config threshold, starts at 40%), show facts only, no rating.
2. **Everything important is an immutable, versioned snapshot** — area reports, property
   evaluations, catchment study summaries — stamped with data-snapshot id, config version,
   timestamp. Never overwrite; create v2.
3. **Every state change writes an append-only audit event** (who, what, from, to, why, when).
   Optimistic locking via a `version` field on mutable rows.
4. **Analysis reads only our own database, never external APIs at run time.** All external
   data (OSM, census, pincodes, Stores API) is ingested offline into a versioned snapshot first.
5. **Save first, evaluate after.** A failed evaluation never loses captured field data. Failed
   jobs name the failed step and resume from it, not from scratch.
6. **Survey drafts are preserved; submissions are idempotent by client-generated id.**
7. **The LLM only phrases; it never calculates.** Fact sheet → LLM → validator (every number/name
   must trace to the sheet) → on failure: retry once → other provider → deterministic template.
   Every snapshot records which source wrote its narrative.
8. **Weights/thresholds/radii/freshness/caps live in `config/sitescout.yaml`.** Every snapshot
   records the config version it used.

## Persona access (enforced server-side — see `docs/DESIGN.md` §Personas for the full table)

- **BD Manager**: runs/views/compares area reports, sees the opportunity map, creates scout
  tasks, sees all properties, is the **only** role that moves pipeline stages, requests studies,
  can waive/force reuse at request time.
- **BD Executive**: sees hotspots for tasked areas + own tasks, onboards properties, sees own
  properties, responds to manager follow-up requests. **Cannot move pipeline stages.**
- **Survey Manager**: sees study requests and study-linked properties with rent/deposit/owner
  fields **stripped server-side**, splits/edits/assigns units, has the final reuse-override say
  at planning time. **Cannot capture survey data.**
- **Survey Executive**: sees only assigned units; captures lane data; the property appears only
  as a label (no commercial fields at all).

Field masking lives in `backend/app/schemas/` as per-role response builders — never trust the
frontend to hide a field.

## Docs index

- `docs/BRIEF.md` — the hackathon problem statement, verbatim, for reference.
- `docs/DESIGN.md` — the full consolidated design: architecture, personas/access, M1/M2/M3
  workflows, scoring formulas, roll-up logic, edge cases, failure handling. **Read this before
  designing or building anything.**
- `docs/DATA.md` — every data source, what we chose and why, download status, known gaps,
  the Phase 2 land-use/coverage gate.
- `docs/PHASES.md` — the phase-by-phase build plan with checkpoints. Phases 0a–4b are done;
  **Phase 5** (frontend shell + M1 UI) is next.
- `docs/DECISIONS.md` — a running log of decisions, corrections, and open questions, in the
  order they were made. Read this to understand *why* something is the way it is, or to see
  what's still unresolved.

## Current state (as of handoff)

- Phase 0a done: repo skeleton, `.gitignore`, `.env.example`, venv, first commit (on the user's
  Mac, not in this session).
- Data acquisition done: OSM Geofabrik Southern Zone extract (verified, md5-matched), Chennai
  post-office-area polygons (datameet, ~12 years old, 68/120 Chennai pincodes covered — see
  `docs/DATA.md`), pincode directory (`bharatpin` package, 2026, 93% coord coverage), ward/zone
  maps (OpenCity 2022 + 2008 + datameet), Stores API live and working (**GET, not POST** — the
  original spec's curl example is misleading; corrected in `docs/DECISIONS.md`), 11 Chennai
  stores confirmed. Census 2011 downloaded but its join (2008 155-ward map vs current 200 wards)
  is untested. Official data.gov.in pincode boundary GeoJSON could not be downloaded (502);
  dropped, Voronoi fallback planned instead.
- Phase 0c done: Docker Compose (PostGIS + api + worker + web) up via `make up`, `/health`
  checks DB/PostGIS/config, branded React shell, `data/MANIFEST.md`. Docker Desktop confirmed.
- Phase 1 done: Alembic schema, `make ingest` builds a versioned data snapshot (wards, zones,
  service area, post offices, multi-part pincodes, stores, H3 grid, locality index),
  `/localities/search`, `/reference/pincodes/{pin}`, `/reference/snapshot`.
- Phase 2 built: OSM clip + pyosmium ingest, POIs, building points, land use (+ derived sea),
  road segments split at junctions, per-cell features + non-scoreable mask, `make gate` report.
  Gate decided: Bhuvan out, metro fringe out, **Microsoft ML building footprints** added
  (`ml_buildings`) as the citywide demand source. Full `make ingest` ~90s.
- Phase 3a done: `config_versions` registry (same version + different content = refused at
  startup), 4 seeded users, HMAC bearer tokens (`APP_SECRET` in `.env`), `require_roles`
  (401/403), per-role allow-list property views in `schemas/properties.py`.
- Phase 3b done: `audit_events` (append-only via DB trigger, reason required), `core/audit.py`
  writer (same transaction as the change), `core/locking.py` (`update_versioned` → 409), jobs +
  job_steps, worker (`app/jobs/`: claim with SKIP LOCKED, heartbeat thread, reaper, lease check
  before each step commit, retry resumes at the failed step). New job kinds register their steps
  in `app/jobs/registry.py`.
- Phase 4a done: `services/selection.py` (pincode/locality/cells → score cells, caps, edits),
  `services/scoring.py` (citywide percentile, provenance, renormalise, facts-only, confidence,
  hotspots), `services/area_report.py` (facts, save, compare), `llm/factsheet.py` +
  `llm/template.py`, `area_report` job, immutable `area_reports` (trigger; test cleanup uses
  `SET LOCAL sitescout.purge = 'on'`), `/areas/*` endpoints (BD Manager).
- Phase 4b done: `app/llm/` — `gemini.py`/`groq.py` adapters (error → retryable or not),
  `validator.py` (numbers trace to the sheet, rating label, stray places), `adapter.py` chain
  (cache → provider retries with backoff/Retry-After → next provider → template; circuit breaker,
  call spacing, total time budget), `calls.py` (`llm_calls` log + cache), code-owned caveats.
  Tests never call real APIs (conftest autouse fixture). After editing `.env`: `make reload-env`.
- **Next step: Phase 5** — frontend shell + M1 UI (role switcher, map, selection modes, job
  progress, report view, save/compare).
