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
| 7a | M2 UI: BD Executive (mobile) | Manager creates a scout task from report hotspots; exec home (tasks, follow-ups, drafts), task map with hotspots, property form (GPS or tap-to-pin, live pin check, locality prefill, rent-band hint, autosaved drafts, idempotent submit), duplicate resolution, photos, notes, follow-up answers, my properties with outcomes | An executive onboards a property from a phone-width view | **Done** — 162 tests. Browser at 375×812: task #12 from report 43 → property #197 saved → v1 Consider 65.2 (Medium); duplicate #198 resolved as same property (note merged into #197); photo upload + thumbnail |
| 7b | M2 UI: BD Manager | Pipeline board by stage, property review page (30-second card, evaluation breakdown, risks, map, photos, notes, history), stage moves with reason + 409 handling, follow-up requests | Manager moves a property through stages with reasons; follow-up loop round-trips | **Done** — 163 tests. Browser: #197 moved by a second tab while the dialog was open → 409, page re-read, reason kept, confirm again OK; rent-check follow-up → Karthik answered on phone → automatic return to under review → shortlisted with reason; re-evaluate → v2, v1 still viewable; full history with actors |
| 8a | M3 backend: study request + reuse | Studies (one open per property), catchment → road segments (midpoint within 600 m), per-segment reuse state (fresh / could-not-survey / stale / uncovered), length-weighted coverage + oldest reused age, reuse modes with reasons (BD at request, Survey Manager final say at planning), study stages via the study workflow only, reject/on-hold cancels the study and keeps captures, append-only `segment_captures`, lane observation schema, demo-seed captures | Reuse shows coverage % and oldest age; stale data never reused; overrides need reasons and are audited | **Done** — 178 tests (10 studies). Live #197: "85.3% covered by fresh survey data · 13.6% requires new survey · 1.1% could not be surveyed recently", oldest reused 80.7 days, 57 of 419 segments to survey; Survey Manager sees no commercial fields |
| 8b | M3 backend: survey units | Balanced contiguous unit generation over the road graph, split/merge/move with the one-segment-one-unit invariant re-checked on every edit, assignment to survey executives (→ study in progress), survey executive's own-units view | Units are non-overlapping and balanced | **Done** — 190 tests (7 units). Benchmarked on 4 catchments: region growing + smoothing keeps every unit within 121–180 min (target 150), 1.5–2.1 pieces/unit, 6–9% walking, ≤1.3 s — better than DFS chunking on balance and walking. Live study #52: 3 units of 161–177 min; U1 assigned to Arjun → study in progress; his /my/units shows only U1 with the property as a label |
| 9a | M3 UI: request + reuse decision | BD Manager: Request-study dialog (coverage preview, reuse mode, reason on override) and a study card on the review page (status, both decisions, units, cancel). Survey Manager: study inbox as home, study page with the catchment map by reuse state, coverage, and the final-say plan that generates units | BD requests with an override; Survey Manager overrides it back with a reason and units appear | **Done** — 190 tests. Browser: #52 (60.5% fresh, below 80%) requested as reuse-only with a reason → Divya re-planned to reuse + gaps with her reason → 131 lanes in 7 units of 2.2–2.7 h; Meera's card shows both reasons, “changed by the Survey Manager” |
| 9b | M3 UI: units + progress | Unit map (select lanes on the map → move / split / merge), assign units to survey executives, progress board, survey executive's “my units today” | Survey Manager assigns units and sees progress | **Done** — 191 tests. Browser, study #173: tapped a U4 lane on the map → split into U8 (1 lane) → merged back into U4; assigned U1 + U2 to Arjun → study “surveying”, 0/131 lanes; Arjun's phone home lists his 3 units across 2 studies; unit page shows lanes numbered in walking order on the map and list |
| 10a | M3 lane capture | Survey executive's one-lane phone form (status, GPS or tap-to-place, timed 5-min pedestrian count with a tap counter, counts, anchors, access ratings, notes), drafts autosaved on the phone, idempotent submit by client id, could-not-survey with a reason, offline queue + send now, re-capture (latest counts), unit submit when every lane is handled | An executive captures lanes on a phone, including offline, and submits the unit | **Done** — 203 tests (8 capture). Browser at 375×812 on #480 U1: timer + tap counter survive a reload; lane 1 surveyed, lane 2 could not survey (reason required); lane 3 saved with the API stopped → queued → API back → sent with the same client id; offline the unit page keeps its data |
| 10b | M3 roll-up | Captures → Catchment Summary (residential/commercial density, observed footfall + time-band mix, accessibility, parking, observed vs OSM competition, anchors, confidence; facts-only below 50% coverage) as a job when all units are submitted | Summary explains itself and flags single-time-band footfall | **Done** — 212 tests (8 roll-up, hand-computed). Live: study #796 (property 52) closed early → summary v1, 68% surveyed, low confidence (99% demo data named), footfall 252/h with its time-band mix, ≈73 grocery/food stores vs OSM's 6 (estimate labelled); property → study complete |
| 10c | **M3 re-evaluation + diff** | v2 evaluation with observed signals replacing proxies, v1→v2 diff classified (data / config / newly included / renormalisation), LLM narrates the diff (validator), BD review | **The full M1→M3 loop works end to end**, and the diff correctly explains *why* the score changed | **Done** — 217 tests (5 re-evaluation). Live: property 52 v1 Consider 64.2 → v2 Consider 61.2 via study #796 (summary v2); factor changes sum to −3.0 exactly (site demand data change −10.1, footfall newly included +7.9, competition data change +7.2, accessibility data change −3.2, four factors renormalization −4.8); R-COMPETITION resolved, R-COMPETITION-OBSERVED raised; Gemini narrative passed the validator first try. **M1→M3 loop complete.** |
| 11 | Bonus: opportunity map | City-wide surfacing of high-score, un-scouted pockets, reusing the M1 engine | Manager can start an analysis directly from a surfaced pocket | **Done** — 226 tests (4 opportunity + access row). 11a: `GET /opportunities` (≈24 ms warm), pockets scored with the area-report engine. 11b: `/opportunities` page (heat, scouted cells greyed with reasons, numbered pockets, Run analysis / Adjust cells). Live: 410 cells rated, 12 scouted skipped, 12 pockets; Run analysis on #1 (Pudupet) → area report 77.3 Strong fit, same as the pocket |
| 12 | Hardening | Tests (scoring, reuse, access), edge-case pass, README, deploy (stretch) | Fresh clone runs with one command + demo data | **In progress** — 12a README + diagrams; 12b `make setup`: fresh clone → running app with snapshot in 1 m 48 s (data present), checksum-verified `make fetch-data`, idempotent re-run 16 s, 225 pass + 1 skip on a fresh DB. Next: 12c demo seed, 12d production build + edge cases |

## Cut order if behind schedule

Given the current ~3h overrun on Phase 0, treat this as live guidance, not a fallback plan:
**deploy → opportunity map (11) → compare-view polish → metro fringe → area-study overlay.**
**Never cut**: any part of the M1→M3 loop, or any access-control rule in `docs/DESIGN.md` §4.

## Decision gates (don't guess these — measure them when the phase arrives)

- **End of Phase 2**: Overpass vs. Geofabrik (Geofabrik already chosen — this is now closed),
  metro fringe in/out, Bhuvan land-use cross-check needed or not.
- **Whenever convenient before Phase 4**: is the census 2011 join (via the 2008 155-ward map)
  worth the cleanup time, or does OSM building density alone suffice as the demand proxy?
