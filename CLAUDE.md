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
- `docs/PHASES.md` — the phase-by-phase build plan with checkpoints. Phases 0a–11 are done (M1,
  M2 and M3 complete, plus the opportunity-map bonus); Phase 12 (hardening) remains.
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
- Phase 5a done: `frontend/src/` — `api/client.js` (token, ApiError), `app/` (auth context, role
  switcher, layout), `components/MapView.jsx` (MapLibre + OpenFreeMap base, grid feature-state,
  `overlays` prop for 5b), `components/JobProgress.jsx`, `features/areas/AnalysePage.jsx` (3 modes
  + cell edits + preview + run), `features/jobs/JobPage.jsx`. New API: `/areas/grid`,
  `/reference/service-area`, `/reference/stores`; GZip middleware.
- Phase 5b done: `features/areas/ReportPage.jsx` (verdict, data-as-of, narrative source +
  degraded notice, `components/ScoreBreakdown.jsx` + `ProvenanceBadge.jsx`, hotspots, facts,
  caveats, versions, run again), `reportLayers.js` (h3-js heat + hotspots), `ReportsPage.jsx`
  (grouped by area, tick two), `ComparePage.jsx`. Cells-mode labels name the nearest locality.
- **M1 is complete end to end.**
- Phase 6a done: `models/scouting.py` (scout_tasks, properties, property_notes, property_photos),
  `services/locate.py` (point context + illustrative rent band), `services/properties.py`
  (save-first create, assess → 422 rejects / warnings / missing, duplicates + explicit
  resolution, versioned edits, photos), `services/tasks.py`, `api/scouting.py`. Shared
  `Unprocessable` (422) / `Forbidden` (403) errors in `core/errors.py`. Photos in `uploads/`.
- Phase 6b done: `services/evaluation.py` (7 site factors, completeness gate, hard flags, rule
  risks, review card), `jobs/property_evaluation.py` (load → evaluate → save; immutable
  `property_evaluations` versions), `services/pipeline.py` (stage rules, reason + version, study
  stages reserved for M3, reject → reopen, follow-up loop), endpoints in `api/scouting.py`.
  Job registry is lazy (`registry.kinds()`); services enqueue on `queue.DEFAULT_QUEUE` (tests
  point it at "test"). Test cleanup: `tests/conftest.purge_scouting_test_data()`.
- **M2 backend complete.**
- Phase 7a done: `frontend/src/features/scouting/` — `CreateTaskPanel` (on the report page),
  `ExecHome` (tasks, open follow-ups, drafts), `TaskPage` (task cells + numbered hotspots),
  `PropertyForm` (GPS / tap-to-pin, live `/reference/locate` check, rent-band hint, localStorage
  drafts via `drafts.js`, client_id idempotent submit), `PropertyPage` (evaluation card, duplicate
  resolution, photos via authenticated blob, notes, follow-up answers), `PropertiesPage`.
  `/properties` list returns latest `outcome` + `score`. `api/client.js` has `apiBlob`/`apiUpload`.
- Phase 7b done: `frontend/src/features/pipeline/` — `BoardPage` (`/pipeline`, by stage, best-rated
  first), `ReviewPage` (manager's `/properties/:id`: 30-second card, next step, breakdown with
  version picker + re-evaluate, map, photos, details, notes, history), `Dialogs` (stage move with
  reason, follow-up request; 409 → re-read, keep the reason, confirm again), `History`. Shared UI in
  `features/scouting/shared.jsx`. API adds `pipeline` (allowed moves, follow-up) for the manager
  and `actor_name` in history.
- **M2 is complete end to end.**
- Phase 8a done: `models/studies.py` (studies, study_segments, append-only segment_captures),
  `services/studies.py` (catchment segments, per-segment reuse state, length-weighted coverage,
  reuse modes + override reasons, request / plan / cancel), `pipeline.study_transition` (study
  stages only via the study workflow; reject/on-hold cancels the study), `api/studies.py`,
  `schemas/studies.py` (LaneObservations, per-role study response). Config `studies` (0.10.0).
  `make seed-captures PROPERTY=197` seeds mock past captures (`source = demo_seed`).
- Phase 8b done: `services/partition.py` (pure: balanced region growing + smoothing over the
  catchment road graph, `estimate()`), `services/units.py` (generate at plan, move / split / merge
  with the one-segment-one-unit check after every edit, assign → study in progress), `survey_units`
  (migration 0011), unit endpoints under `/studies/{id}/units`, `/my/units`, `/units/{id}/segments`.
  Config `studies.units` (0.11.0).
- Phase 9a done: `frontend/src/features/studies/` — `reuse.jsx` (states, modes, CoverageBar,
  catchment overlays), `RequestStudyDialog` + `StudyCard` (BD review page), `InboxPage` (Survey
  Manager home), `StudyPage` (`/studies/:id`: coverage, catchment map, final-say plan, units table).
  `<main>` is the scroll container. Study tests run at a dedicated site (Perambur).
- Phase 9b done: `features/studies/UnitPanel.jsx` (units table, assign, move / split / merge of
  lanes selected on the map, progress), StudyPage Units/Reuse views, `features/units/`
  (`MyUnitsPage` = survey executive home, `UnitPage` = numbered lane map in walking order).
  `MapView` supports `clickable` overlay layers and attaches layers on `style.load`. API: unit
  progress, `GET /units/{id}`, lanes in walking order (`partition.walk`).
- Fragmentation fix: demo seed = contiguous past-unit clusters; partitioner = stretch-first
  peeling (`studies.units.method: peel`, config 0.12.0), pinned by `tests/test_partition.py`.
  Demo studies now #479 (property 197) and #480 (property 52), U1 of each assigned to Arjun.
- Phase 10a done: `services/captures.py` (assignee-only capture, idempotent client id, device
  time checks, server time band, GPS distance flag, latest capture counts, unit submit),
  `POST /captures`, `POST /units/{id}/submit`, migration 0012 (`gps_distance_m`), config
  `studies.capture` (0.13.0). Frontend `features/units/CaptureForm.jsx` (+ `captureDrafts.js`,
  offline queue) and the capture-aware `UnitPage`.
- Phase 10b done: `services/rollup.py` (collect → pure `aggregate` → save), `jobs/study_rollup.py`,
  immutable `catchment_summaries` (migration 0013), triggers (last unit submitted / reuse-only
  plan / Survey Manager close-early or re-run), `GET /studies/{id}/summary`, `SummaryCard`.
  Worker now survives unknown job kinds and reloads on code/config changes (compose). Demo:
  study #796 (property 52) has summary v1; #795 (property 197) is in progress.
- Phase 10c done: study complete → `property_evaluation` (trigger `study_complete`) → v2 with
  observed site demand / competition / accessibility + footfall (`evaluation.study`, config
  0.15.0); `services/diff.py` (pure, classified v1→v2 diff whose points add up);
  `llm/diff_narrative.py` on the generalised adapter (`NarrativeSpec`); migration 0014;
  `features/pipeline/DiffCard.jsx`. Demo: property 52 v1 64.2 → v2 61.2 via study #796.
- **The M1→M3 loop is complete end to end.**
- Phase 11 done (bonus: city-wide opportunity map): `services/opportunities.py` (res-8 cells rated
  by mean res-9 cell score, greedy pockets ≤ 3 cells above the citywide 80th percentile, each scored
  with `scoring.score_area` so "start analysis" reproduces it; scouted cells skipped with reasons),
  `GET /opportunities` (BD Manager), config `opportunities` (0.16.0);
  `features/opportunities/OpportunitiesPage.jsx`; AnalysePage accepts `state.cells` (Adjust cells).
- Don't run two `make test`s at once: they share the test DB and "test" job queue (deadlocks,
  lease_lost, purged fixtures).
- Next step: **Phase 12** — hardening (README, fresh-clone one-command run + demo data,
  production build incl. the MapLibre worker asset, edge-case pass).
