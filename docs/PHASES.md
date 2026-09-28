# Phase plan

Window: **Mon 28 Sep 2026 09:00 IST → Wed 30 Sep 2026 09:00 IST** (48h, git commit history is
the timing evidence). Each phase: what/why → files → exact commands → checkpoint → **stop and
wait for the result** before the next phase (see `CLAUDE.md` §How to work with me).

## Schedule reality check (update this as phases close)

Original Phase 0 estimate was ~3h. Chat timestamps show data acquisition/feasibility work
(pincode cross-checks, Stores API debugging, OSM verification) ran from ~10:06 to ~14:52 IST on
Mon 28 Sep — **roughly 5h50m spent on Phase 0**, about 3h over budget. Docker/scaffold (0b) had
not started as of the last message in this chat.

**Consequence**: assume we're already ~3h behind the original plan when picking up. Re-tighten
the cut order below accordingly, and don't let Phase 0b run long — it's mechanical, not a design
phase.

## Project structure

```
savomart-fullstack-hackathon-2026-22pd33/     # actual repo root (not "savo-sitescout/")
├── docker-compose.yml          # postgis, api, worker, web
├── .env.example                 # keys/token placeholders only — never real values
├── .env                         # gitignored — real keys/token
├── Makefile                     # up, migrate, ingest, seed, test
├── README.md                    # built up phase by phase; final version covers run
│                                 #   instructions, role-switcher usage, data citations,
│                                 #   mock-data labeling, AI-tool disclosure, trade-offs
├── config/
│   └── sitescout.yaml           # weights, thresholds, radii, caps — versioned
├── data/
│   ├── raw/                     # gitignored downloads — see docs/DATA.md for full manifest
│   └── MANIFEST.md              # citation-ready record: dataset, source, date, licence
├── scripts/
│   ├── check_data.py            # Overpass/Stores/GeoJSON feasibility checks (superseded —
│   │                             #   Overpass dropped in favour of the pinned Geofabrik file)
│   └── check_pincode.py         # pincode polygon/directory cross-check (already run once)
├── backend/
│   ├── Dockerfile
│   ├── pyproject.toml
│   ├── .venv/                   # gitignored — host venv for scripts, not the API/worker runtime
│   ├── alembic/                 # migrations — created in Phase 1, not yet
│   ├── app/
│   │   ├── main.py
│   │   ├── core/                # settings, config loader, db, auth/roles, audit, errors
│   │   ├── models/               # tables (GeoAlchemy2)
│   │   ├── schemas/              # request/response models — PER-ROLE MASKING LIVES HERE
│   │   ├── api/                  # thin routers per domain
│   │   ├── services/             # ALL business rules: selection, scoring, evaluation,
│   │   │                          #   pipeline, dedupe, reuse, units, rollup, diff
│   │   ├── jobs/                  # queue, worker loop, step runners
│   │   └── llm/                   # adapter, gemini, groq, template, factsheet, validator
│   ├── ingest/                    # offline CLI — never called at request time
│   └── tests/
└── frontend/
    ├── tailwind.config           # brand tokens: #782B90 purple, #FFF200 yellow
    └── src/
        ├── app/                   # router, role switcher, auth context
        ├── api/                   # client, query hooks
        ├── components/            # map, provenance badge, score breakdown, job progress
        └── features/              # areas, opportunities, scouting, properties, pipeline,
                                     #   studies, units, capture
```

**Structural decisions**: routers are thin, services hold the rules (testable without HTTP).
Masking lives only in `schemas/`, one builder per role, so no router can leak a field by
accident. Ingest is a separate CLI sharing models with the API but never running at request
time. Defaults unless challenged: SQLAlchemy 2 + GeoAlchemy2 + Alembic, `h3-py`, pytest,
TanStack Query on the frontend.

## Phase table

| # | Phase | Delivers | Checkpoint | Status |
|---|---|---|---|---|
| 0a | Env + scaffold + git | Repo skeleton, `.gitignore`, `.env.example`, Homebrew/Python/Node/Docker install commands, host venv, first commit | `git status` clean of `.env`/`.venv`, commit exists | **Done** (on the user's Mac — not visible from this session) |
| 0b | Data acquisition + feasibility | OSM extract, pincode polygons+directory, ward/zone/census downloads, Stores API call fixed and verified, pincode coverage cross-check | Every download verified (checksum/row-count/content spot-check); coverage gaps quantified, not assumed | **Done** — see `docs/DATA.md` for every number |
| 0c | Docker Compose + FastAPI scaffold + branded React shell | `docker-compose.yml` (postgis/api/worker/web), FastAPI health endpoint, Vite+React+Tailwind placeholder with brand colours, `data/MANIFEST.md` | `docker compose up` brings up all services; health endpoint responds; placeholder page renders with `#782B90`/`#FFF200` | **Done** — all 4 services up; `/health` → `{status: ok, postgis: 3.5.3, config_version: 0.1.0}`; page verified rendering brand colours. |
| 1 | Schema + reference data | Migrations, data-snapshot table, wards, pincodes (datameet + Voronoi fallback), post offices, locality index, Stores cache table, H3 grid setup | Locality search returns candidates with pincode/ward/zone; pincode geometries correctly tagged `datameet_2013` vs `voronoi_approx` | **Done** — snapshot build ~3s; 80 pincodes cover 99.8% of GCC (68 datameet parts + 41 Voronoi parts); 10 checkpoint tests pass. See `docs/DECISIONS.md` §Phase 1. |
| 2 | OSM ingest + features + **decision gate** | POIs, buildings, transit, roads, per-cell features, non-scoreable mask, road segments split at junctions. **Gate: measure OSM building/landuse coverage → decide Bhuvan in/out and metro-fringe in/out here, not by assumption.** | Feature counts for a known area look sane; segments have unique per-snapshot ids; mask correctly catches airport/Marina/Ennore-Manali | **Done** — 19 tests. Gate decided: Bhuvan out, fringe out, Microsoft ML buildings added as the demand source (GCC building-sparse 20.4% → 1.5%). See `docs/DECISIONS.md` §Phase 2 gate. |
| 3a | Platform core: config + access | Config versioning (registry + content hash), 4 seeded users + bearer tokens, role checks, per-role field masking | A wrong-role call returns 403; a masked field never appears in a disallowed role's response | **Done** — 67 tests (role matrix, forged tokens, masking with sentinel values, config version guard) |
| 3b | Platform core: audit + jobs | Audit writer (append-only), jobs table, worker with row locking + heartbeat + step resume | A test job fails at a step and resumes correctly from it; a stuck job is re-queued by heartbeat | **Done** — 81 tests (fail → retry → resume without re-running done steps; dead-worker re-queue; heartbeat keeps a slow step alive; 4 concurrent claimers → 1 winner; append-only enforced by DB trigger) |
| 4a | M1 backend: analysis | Selection→cells (caps, edits, non-contiguous flag), scoring engine, provenance, renormalization + facts-only rule, confidence, hotspots, fact sheet + template narrative, `area_report` job, immutable versioned reports, compare | An area report runs end to end and saves a versioned snapshot; re-run → v2; two reports compare | **Done** — 97 tests; T Nagar 65.8 Moderate fit vs Tondiarpet zone 51.7, compare explains the gap per factor |
| 4b | M1 backend: LLM | Gemini + Groq adapters, validator (every number/name traces to the fact sheet), fallback chain (retry → other provider → template), narrative source recorded | A forced LLM failure correctly falls back to the template; a real narrative passes the validator | **Done** — 108 tests (all on fake transports, 0 quota); live: Gemini 503 → retry → valid narrative, Groq valid first try, v2 re-run served from cache with 0 calls |
| 5a | Frontend shell + selection | Role switcher, brand theme, API client, map (GCC outline, selection grid with unscoreable cells greyed, Savomart stores), 3 selection modes + click-to-edit cells, preview, run with live job progress + failed-step retry, `/jobs/:id` page | BD Manager selects an area three ways, runs it, watches progress to a saved report | **Done** — verified in the browser: pincode 600018 + 1 added cell → report 43 (63.1, Gemini narrative); locality "Perambur" disambiguation; "Tambaram" shown as outside GCC; picked cells; failed job named + retried from UI; BD Executive gated. 123 backend tests |
| 5b | M1 report UI | Full report view (factor breakdown raw → normalized → weight → contribution, provenance badges, hotspot + cell-score map, facts, caveats, data-as-of, narrative source + degraded notice), report list + version history, compare view | BD Manager runs an area from the UI and compares two saved reports | **Done** — verified in the browser: report 43 (Teynampet) full view with heat map + numbered hotspots + "written by Gemini after HTTP 503"; list → tick two → compare Teynampet vs T Nagar (+2.7, flags: different area, different config 0.7.0 vs 0.6.0, per-factor deltas, both areas on the map) |
| 6a | M2 backend: scouting | Scout tasks (from report hotspots), save-first idempotent property create, pin validation (outside GCC / (0,0) / water → 422), warnings (GPS, distance, rent vs illustrative band, zero rent), missing fields, explicit duplicate resolution, notes, photos, versioned edits, location context, row-level access, audit | Bad pins/duplicates handled correctly; executives see only their own; stale edits 409 | **Done** — 152 tests (14 scouting) |
| 6b | M2 backend: evaluation + pipeline | Deterministic site evaluation job (immutable versions), rent vs band, hard flags, Strong/Consider/Weak/Needs Info, rule-based risks, completeness gate, re-eval on edit; pipeline stages (BD Manager only, reason required, optimistic lock, reject → reopen), follow-up loop | Every stage move requires and logs a reason; concurrent moves 409; edit → evaluation v2 | **Done** — 162 tests (10 pipeline/evaluation). Live: "Corner shop, Ranganathan St" → v1 Consider 64.2 (Medium); a shop 44 m from an existing Savomart store capped Consider → Weak Fit by the hard flag |
| 7 | M2 UI | BD Exec mobile task map + property form + photos, manager 30-second review card, pipeline board, history | An executive onboards a property from a phone-width view; manager moves it through stages | Not started |
| 8 | M3 backend | Study request, catchment→segments, reuse coverage + overrides, balanced contiguous unit generation, one-unit-per-segment enforcement, assignment | Reuse shows coverage % and oldest age; units are non-overlapping and balanced | Not started |
| 9 | M3 Survey Manager UI | Request inbox, reuse decision panel, unit map with split/merge/reassign, progress board | Survey Manager assigns units and sees progress | Not started |
| 10 | **M3 capture + roll-up** | Survey Exec mobile capture, autosaved drafts, idempotent submit, "could not survey," roll-up, Catchment Summary, v2 evaluation, v1→v2 diff, area-study overlay | **The full M1→M3 loop works end to end**, and the diff correctly explains *why* the score changed | Not started — **this is the phase that must not slip** |
| 11 | Bonus: opportunity map | City-wide surfacing of high-score, un-scouted pockets, reusing the M1 engine | Manager can start an analysis directly from a surfaced pocket | Not started |
| 12 | Hardening | Tests (scoring, reuse, access), edge-case pass, README, deploy (stretch) | Fresh clone runs with one command + demo data | Not started |

## Cut order if behind schedule

Given the current ~3h overrun on Phase 0, treat this as live guidance, not a fallback plan:
**deploy → opportunity map (11) → compare-view polish → metro fringe → area-study overlay.**
**Never cut**: any part of the M1→M3 loop, or any access-control rule in `docs/DESIGN.md` §4.

## Decision gates (don't guess these — measure them when the phase arrives)

- **End of Phase 2**: Overpass vs. Geofabrik (Geofabrik already chosen — this is now closed),
  metro fringe in/out, Bhuvan land-use cross-check needed or not.
- **Whenever convenient before Phase 4**: is the census 2011 join (via the 2008 155-ward map)
  worth the cleanup time, or does OSM building density alone suffice as the demand proxy?
