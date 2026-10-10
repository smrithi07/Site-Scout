# Decision log

Chronological record of decisions, corrections, and why. Read this when something in
`docs/DESIGN.md` or `docs/DATA.md` seems arbitrary — the reasoning is here. Newest open
questions are at the bottom.

## Stack and framing

- **FastAPI, not Flask.** An early message used Flask by mistake; corrected mid-session and
  used consistently from then on. If anything in old scratch notes says Flask, it's wrong.
- **Solo developer, ~48h window.** Every complexity trade-off in this project (job table vs.
  Celery, GET-based single OSM extract vs. a tile server, etc.) is made against that constraint,
  not against "what would be best at scale."
- **LLM providers**: Gemini (native structured output, good fit for the report narrative) as
  default; Groq (fast Llama/Qwen-class models) as fallback, benchmarked against Gemini on the
  validator's pass rate once both are wired up; deterministic template as the final floor.
  Neither key exists yet as of handoff — user still needs to create both.

## Persona/access corrections

Two corrections were made against an earlier, looser draft of the access table — both are now
authoritative in `docs/DESIGN.md` §4:

1. **Survey Manager cannot capture lane data.** An early draft table briefly allowed it; the
   spec assigns capture to the Survey Executive only. Survey Manager's job is split/assign/track.
2. **City-wide opportunity map is BD Manager only.** It's the chosen bonus feature; keeping its
   surface small (one role) was a deliberate scope-control choice, not an oversight.
3. **BD Executive cannot move pipeline stages, period** — not even early ones. This was asked
   explicitly by the user ("BD Executive can only propose a stage change; BD Manager has
   authority to actually move the property... make sure we follow the strict needs the hackathon
   says"). The resolution is the **"Needs follow-up" loop**: manager asks exec for more info
   (photos/revisit/rent check), exec responds, property returns to Under Review. This satisfies
   the spec's "asking an executive to proceed to the next stage" without giving the executive
   stage-move authority.
4. **Survey Manager sees location + study scope + operational info, never commercial fields**
   (rent, owner) — explicit user decision, enforced as server-side field stripping in
   `schemas/`, not a UI-only hide.

## Design-gap resolution (the second brief, `docs/BRIEF.md` §Original follow-up)

All seven gaps in the follow-up brief were resolved in one pass and are now part of
`docs/DESIGN.md` — the review also surfaced conflicts against the *first* pass of decisions,
which were fixed before locking:

- **Cells vs. segments conflict**: an early draft measured survey reuse in "fresh cells," which
  contradicted making the road segment the atomic survey unit. **Resolved: segment is the atom,
  always.** H3 cells are display/area-analysis only, never the survey unit.
- **"Data completeness" as a scoring factor conflicted with the provenance/renormalization
  rule** (scoring missing data would double-penalize it). **Resolved: completeness is a gate +
  confidence label, never a weight.**
- **The 80% reuse threshold was ambiguous** between "reuse allowed" and "reuse-only allowed."
  **Resolved**: ≥80% → default reuse+survey-gap, "reuse only" allowed as an explicit choice with
  lower confidence; <80% → partial reuse + mandatory survey of the rest, "reuse only" needs an
  override.
- **Freshness scope was ambiguous** (per-study vs. per-segment) given a study spans several
  days. **Resolved: freshness is per-segment capture timestamp**, not per-study.
- **Override authority was underspecified.** **Resolved**: BD Manager waives/forces reuse at
  request time; Survey Manager has final say at planning time. Both require a reason, both
  audited.
- **Cannibalisation/store-proximity was missing from the property evaluation factors** despite
  being the whole point of the Stores API. **Resolved**: added as both a weighted factor and a
  hard flag (operational store within ~400 m caps the outcome one level).
- **Owner/broker contact was missing from the property form** despite BD needing it. **Resolved:
  added as a BD-only field**, stripped server-side for other roles.
- **Locality→geometry for a bare point (no polygon) needed an explicit approximate-extent
  policy** — resolved as: never guess, show a map preview, mark it approximate, let the manager
  edit the cell selection before running analysis.
- Several smaller refinements also locked in this pass: visibility/accessibility/parking/
  condition captured once as executive-rated fields (not duplicated between "physical" and
  "executive assessment" sections); area-level demand/competition/accessibility/cannibalisation
  moved to *site-level* radius computation to avoid double-counting the M1 area score inside M2;
  one survey form per *segment*, not per lane/unit; footfall auto-stamped with a time band;
  normalization thresholds explicitly acknowledged as config-driven and uncalibrated;
  **household income mock data dropped** (fed nothing in the actual evaluation once designed —
  rent band alone is the useful mock signal, and unused mock data shouldn't ship just for
  appearances); v1→v2 diff reasons classified into `data change` / `config change` /
  `factor newly included` / `renormalization` so the diff reads as an explanation, not a wall of
  numbers.

## Data corrections

- **Stores API is GET, not POST.** The spec's curl example uses `--data ''`, which forces curl
  into POST, and the live endpoint returns `405 Method Not Allowed` for POST with
  `allow: GET`. Confirmed by direct testing. This is a **correction to the spec itself**, not
  just to our client code — flag it in the README's honest-trade-offs section, since anyone
  copy-pasting the spec's example verbatim will hit the same wall.
- **Official pincode boundary GeoJSON (data.gov.in) dropped** after a manual browser attempt
  timed out (502). Not chased further — the `datameet` polygons + Voronoi fallback cover the
  same need at acceptable quality for a 48h build, and this was decided as non-blocking from the
  start (see `docs/DATA.md`).
- **Bhuvan: deferred, not skipped.** First instinct was "skip" with no real investigation; on
  being challenged directly, the honest resolution was to defer the decision to a measured gate
  (Phase 2, after OSM ingest) rather than assume OSM is sufficient without checking. This is
  the model for how *every* "skip this source" call should be made in future work — measure
  first if a check is cheap, don't just reason from priors.
- **OSM ingest source: Geofabrik pinned extract, not live Overpass.** Reconsidered mid-session:
  the Southern Zone `.osm.pbf` is only ~558 MB, well within a normal download, and a dated file
  is reproducible with no rate limits — a better fit for "ingest offline once" than repeated
  Overpass queries against a live server. Overpass demoted to fallback-only for gap-filling.

## Phase 0c scaffold decisions

- **PostGIS image: `imresamu/postgis:17-3.5`, not `postgis/postgis`.** Checked with
  `docker manifest inspect`: the official image publishes amd64 only, so on the Apple-Silicon
  Mac it would run under emulation — slow for the ~558 MB OSM ingest. `imresamu/postgis` is the
  multi-arch (native arm64) build of the same Dockerfiles by a docker-postgis maintainer.
  Revisit only if deploying to amd64, where either works.
- **Docker Desktop confirmed installed and running** (Docker 29.8.0, Compose v5.5.1) — open
  question 3 below is closed.
- **Frontend: Tailwind v4 via `@tailwindcss/vite`**; brand tokens live in `frontend/src/index.css`
  (`@theme`), not a `tailwind.config` file (v4 is CSS-first). JSX, not TypeScript, for speed.
- **Code is bind-mounted** into api/worker/web with reload, so later phases never need a rebuild
  unless dependencies change. `data/` and `config/` are mounted read-only.

## Phase 1 decisions (schema + reference data)

- **One data snapshot per ingest build.** `python -m ingest build` creates a new `data_snapshots`
  row, runs every loader (each step commits on its own), and marks it `ready`. A failure marks it
  `failed` with the step name. Old snapshots are never modified; analysis reads the latest
  `ready` one. Every raw file's sha256, size, mtime and row count goes into `data_sources`.
  Phase 2 adds OSM steps to the same build (re-running the reference steps takes ~3s).
- **Pincode geometry is multi-part, not either/or.** Measured: the original rule (datameet
  polygon *or* Voronoi) left **89 km² (21%) of GCC in no pincode**, 43 km² of it in
  Sholinganallur zone, because datameet's 2013 shapes stop at the old city limits while their
  post offices' neighbourhoods extend into the expanded GCC. Now each pincode has one row per
  source: a `datameet_2013` part (clipped to GCC) and/or a `voronoi_approx` part (Voronoi cells
  of its own in-area post offices, minus datameet coverage). Result: 80 pincodes, 29 of them
  datameet + a Voronoi extension, **99.8% of GCC covered, 0 overlap**. Provenance stays per
  part, and the API returns both so the map can shade them differently. Voronoi fragments
  under 0.05 km² are dropped as slivers (config).
- **8 in-area pincodes still have no geometry.** Their post offices sit inside another
  pincode's 2013 polygon (boundary drift or re-assignment). They fall back to the ward
  polygon, per the geometry-priority rule. Not chased further.
- **Service area = union of the 200 wards (2022), with digitising slivers filled.** The raw
  union had 2,150 holes: 2,149 slivers (0.1 km² in total) and **one real 5.9 km² enclave at
  13.007 N, 80.194 E (St. Thomas Mount cantonment, not GCC)**. Holes under 0.1 km² are filled
  (config); the cantonment stays out. GCC = 432.2 km².
- **Ward tagging uses the nearest ward**, so points in a filled sliver and border res-8 cells
  (whose centre falls just outside GCC) still get a ward/zone. 0 untagged cells.
- **Only 141 of the 306 Chennai-pincode post offices are inside GCC.** The rest (Tambaram,
  Avadi, Pallavaram…) are kept in the locality index flagged "outside service area", so a
  search says so instead of "not found". Relevant to the metro-fringe gate.
- **Locality search**: pg_trgm similarity over a normalised name (lowercase, punctuation and
  B.O/S.O/H.O suffixes stripped); an exact 6-digit query matches the pincode. Candidates that
  resolve to the same geometry are collapsed (e.g. "Velachery" pincode and "Velacheri" post
  office). Each candidate carries pincode/ward/zone plus the geometry it would resolve to and
  that geometry's approximation label. OSM place names join the index in Phase 2.
- **Reference endpoints have no role checks yet**; auth arrives in Phase 3.

## Phase 2 decisions (OSM ingest + features)

- **OSM tooling: osmium-tool clip + pyosmium**, over osm2pgsql (Lua, fixed output tables to remap
  into snapshots) and GDAL (weaker relation handling). Same libosmium multipolygon assembly as
  osm2pgsql, but everything stays in the Python ingest. Measured: clip 558 MB → 22 MB in 5s;
  parse + load 33s; 0 unassemblable geometries.
- **Clip box includes the metro fringe** (79.95–80.36 E, 12.75–13.35 N) so the fringe could be
  measured; per-cell features still cover only the service area.
- **Sea polygon derived from `natural=coastline`** (OSM has no sea polygon): the clip box is split
  along the merged coastline, and pieces touching the east edge are sea (505.7 km² in the box).
- **Road segments**: configured road classes (no motorways/tracks/footpaths, no driveways/parking
  aisles), split at every node shared with another road way. `segment_id = '<way_id>:<piece>'`,
  unique per snapshot. 301,483 segments (126,640 touch GCC), median 50 m. Segments under 1 m
  (duplicate-node artefacts) are dropped. The longest is 15 km, an elevated/bypass road with no
  junctions; M3 clips segments to the catchment, so that's not a survey problem.
- **Non-scoreable mask**: a cell is masked if sea/water/wetland/beach/aeroway/industrial/military
  cover ≥ 50% of it, or it has 0 buildings and < 50 m of local street. Street length (not
  buildings) is the emptiness test because OSM roads are far better mapped than buildings here.
  847 of 3,838 cells masked (359 industrial, 159 wetland, 139 empty, 114 water, 27 military,
  25 airport, 20 sea, 4 beach).
- **Mask validation uses OSM's own named polygons as ground truth** (hand-picked coordinates
  proved unreliable): Pallikaranai Marsh 87/87 cells masked, airport 22/23, Chennai Port 20/20,
  CPCL 6/6, Ennore Thermal 9/9, Manali Fertilizers 13/13, Marina Beach 3/3, Ennore Creek 24/27;
  the misses are edge cells that are majority land. The dense T Nagar core has 0 masked cells.
  Masked cells have a median of 0–6 buildings vs 75 for scoreable cells; the built-up masked
  cells are industrial estates (SIDCO, Nehru Nagar), whose buildings are sheds.
- **Performance trap, fixed**: freshly inserted snapshot rows have no planner statistics, so the
  per-cell spatial joins used the `snapshot_id` btree and scanned all 390k buildings per cell
  (550s). `ANALYZE` after each bulk load → 5s. Full `make ingest` is now ~46s.
- **OSM place names** (941 suburb/neighbourhood/locality/… names) joined the locality index.
- **`python -m ingest prune`** deletes failed snapshots and their partial rows (cascade).

### Phase 2 gate — measured (`make gate`)

A "roaded" cell has ≥ 300 m of local street, so people clearly live there. It is **building-sparse**
if OSM has < 10 buildings in it: the buildings exist but aren't mapped.

| Area | Roaded cells | Building-sparse | Median buildings / roaded cell |
|---|---|---|---|
| GCC, all scoreable cells | 2,719 | 20.4% | 87 |
| Central zones (Anna Nagar, Kodambakkam, Teynampet, Adyar, Ambattur, Alandur, Perunkudi, Valasarvakkam, Thiru-Vi-Ka Nagar) | — | 0.5–6.5% | 92–177 |
| Royapuram / Madhavaram | 126 / 220 | 16.7% / 30.5% | 66 / 58 |
| **Tondiarpet** | 143 | **52.4%** | **5** |
| **Sholinganallur** | 268 | **52.2%** | **7** |
| **Thiruvottriyur** | 101 | **88.1%** | **1** |
| **Manali** | 118 | **94.9%** | **0** |
| Metro fringe ring (10 km around GCC) | 4,111 | 70.4% | 0 |
| Fringe, within 2 km of a Savomart store | 238 | 68.1% | 2 |

Land-use polygons (any class) cover 29.3% of GCC.

**Reading**: (1) the mask works on OSM alone → Bhuvan adds nothing for masking. (2) The fringe has
almost no building data. (3) **OSM building density is not a usable demand proxy in the four
northern/southern zones**, which is where several of Savomart's
existing stores are. Scored naively, these zones would look like low demand purely because of missing
mapping.

### Phase 2 gate — decisions (signed off by the user)

- **Bhuvan: out.** The mask catches every named non-neighbourhood site from OSM alone.
- **Metro fringe: out.** Decided on the OSM numbers above. Note: with ML buildings (below) the
  fringe within 2 km of a Savomart store is only 2.5% building-sparse (whole 10 km ring: 26.6%),
  so building data alone no longer rules it out. It stays out because there's no fringe
  boundary/ward/pincode geometry ingested and the time is better spent on M1→M3. Fringe stores
  still count for cannibalisation (radius query, not a service-area filter).
- **Demand source: Microsoft Global ML Building Footprints** (option C of three: A = mark
  under-mapped cells as missing demand, B = street-density proxy, C = ingest an ML building
  dataset). Chosen over Google Open Buildings v3 on size (69 MB vs 1.12 GB for the covering
  tile) and recency (Feb 2026 vs Jun 2023); Google was the fallback if Microsoft failed the
  re-measure. Loaded as its own table (`ml_buildings`, provenance `observed (ML-derived)`), not
  merged into OSM, because many OSM buildings in India were imported from such datasets and a
  merge would double count. **Re-measured with the same gate:**

  | Area | OSM building-sparse | ML building-sparse | ML median buildings / roaded cell |
  |---|---|---|---|
  | GCC, all scoreable cells | 20.4% | **1.5%** | 134 |
  | Manali | 94.9% | **8.5%** | 74 |
  | Thiruvottriyur | 88.1% | **1.0%** | 209 |
  | Tondiarpet | 52.4% | **1.4%** | 176 |
  | Sholinganallur | 52.2% | **4.5%** | 76 |
  | Every other zone | 0.5–30.5% | 0–2.8% | 95–179 |

  Every zone is now ≤ 8.5% (Manali's residue is its industrial belt). **Phase 4 uses ML buildings
  as the single citywide demand source** (one consistent measure keeps percentile normalisation
  fair); OSM building counts stay in `cell_features` as a cross-check. The ~15-minute flag from
  option A (mark a cell's demand `missing` when it is building-sparse in the chosen source) is
  still built into Phase 4 scoring as the safety net.
- **Mask "empty" rule now needs zero buildings in *both* sources**: 139 → 84 empty cells. 55 cells
  had real buildings that OSM never mapped.

## Phase 3a decisions (config versioning, auth, masking)

Phase 3 was split at the user's request: **3a** = config versioning + users/roles + masking,
**3b** = audit log + jobs/worker.

- **Config versioning**: every loaded config is registered in `config_versions` (version, sha256
  of the parsed content, full content). Registering a version whose content differs from what's
  stored is refused, so a forgotten `version` bump stops the API, worker and ingest at startup
  instead of silently producing snapshots whose `config_version` lies. The hash is of the parsed
  YAML, so comment/whitespace edits don't need a bump. `/config` serves the active config + hash
  (for the UI's "weights in force" panel); `/health` shows the version + short hash.
- **Demo auth**: four users seeded by migration 0004 with fixed ids. Tokens are
  `<user_id>.<HMAC-SHA256(APP_SECRET, user id)>`: nothing stored, nothing committed; `APP_SECRET`
  lives in `.env` (min 16 chars, enforced). `POST /auth/demo-login` issues a token for the role
  switcher and exists only while `DEMO_AUTH=true`; `/auth/demo-users` lists names/roles, never
  tokens. No expiry: deliberately out of scope (docs/DESIGN.md §4).
- **Role checks**: `require_roles(...)` dependency → 401 missing/invalid token, 403 wrong role.
  Applied now: locality search = BD roles; pincode shapes = BD roles + Survey Manager;
  snapshot/config/me = any signed-in user; `/health` public.
- **Field masking = allow-lists, not deny-lists.** `schemas/properties.py` has one response model
  per role listing exactly what it may see; a field added to the property record later is
  invisible to every role until a view opts in. `BD_ONLY_FIELDS` states the intent and a test
  keeps it and the models in sync. Built ahead of the property table (Phase 6) from the §6 form
  fields, and tested with a record carrying every field plus sentinel values (so a leak under a
  renamed key is still caught). Row-level rules (executives see only their own) are ownership
  checks in services, not masking.

## Phase 3b decisions (audit log, jobs, worker)

- **Audit log is append-only in the database**, not by convention: a trigger rejects UPDATE,
  DELETE and TRUNCATE on `audit_events`, and a CHECK rejects a blank reason. The writer
  (`core/audit.py`) takes the caller's session, so an event commits or rolls back with the change
  it describes. System actions (worker, reaper) are recorded with `actor_role = 'system'`.
- **Every job status change is audited** (created, started, failed, retried, requeued,
  succeeded); step-level progress lives in `job_steps`, not the audit log, to keep the log readable.
- **Step = transaction.** A step's DB writes and its `done` mark + persisted output commit
  together. A crash mid-step therefore loses nothing that was marked done and leaves nothing
  half-written; resume skips done steps and hands later steps the persisted outputs.
- **Claiming**: `UPDATE … WHERE id = (SELECT … FOR UPDATE SKIP LOCKED LIMIT 1)`. Tested with 4
  concurrent claimers on one job → exactly 1 winner.
- **Heartbeat + reaper + lease**: a thread refreshes `heartbeat_at` every 5s; any worker's poll
  re-queues running jobs silent for 30s (fails them after 3 such losses). Before committing a
  step the runner row-locks the job and checks it still owns it, so a worker that was presumed
  dead but wakes up can't commit into a job someone else now runs.
- **Retry is manual** (the UI's retry button, reason required, audited, optional optimistic
  `version`); automatic retries happen only for lost heartbeats. Rationale: an LLM or data
  failure repeated automatically just burns time; the fallback chains (Core rule 7) handle the
  transient cases inside the step.
- **Optimistic locking helper** `update_versioned` (`core/locking.py`) → `StaleVersion` → HTTP 409.
  Used by job retry now, by pipeline moves in Phase 6.
- **Tests use queue `test`**; the worker container serves `default` only (config `jobs.queues`).
  Test jobs are deleted after each test, but their audit events stay (the log can't be pruned,
  by design). They're identifiable by `entity_type = 'test'` or by job ids no longer in `jobs`.
- **Worker poll interval moved from settings to `config/sitescout.yaml` (`jobs:`)** with the
  other tunables (config 0.5.0).

## Phase 4a decisions (M1 analysis)

Phase 4 was split at the user's request: **4a** = selection, scoring, report job, versioning,
compare with the template narrative; **4b** = LLM adapters, validator, fallback chain (needs keys).

- **Selection** resolves to res-9 score cells whose centre lies in the chosen geometry; selection
  cells (res 8) are their parents. Caps in score cells: min 7 (≈ one map cell), max 600 (≈ 60 km²,
  big enough for any single zone). Edits (add/remove) happen on selection cells. The `area_key` is
  a hash of the final score-cell set, so the same area → the same key → v1, v2, ….
- **Factor raw values** (all config): demand = Microsoft footprint m² in the cell (proxy);
  anchors = weighted transit/market/school/hospital/office within 1 ring (~350 m); competition =
  OSM grocery shops within 2 rings (~650 m, lower bound, inverted); cannibalisation = metres to the
  nearest operational Savomart, capped at 5 km; accessibility = road metres within 1 ring, main
  roads ×2. Neighbour rings count features in masked cells too (a bus stop by a factory still
  serves the street next to it); percentiles use scoreable cells only.
- **Normalisation = mid-rank percentile across all scoreable GCC cells**, so ties (e.g. the many
  zero-competitor cells) share a value instead of ranking arbitrarily, and scores compare across
  areas. The city model is ~0.3 s to build and cached per (snapshot, config version) in-process.
- **Missing, not zero, at two levels**: a cell's demand is `missing` when it has ≥ 300 m of local
  street but no footprints (the Phase 2 safety net); a factor counts at area level only if ≥ 50%
  of scoreable cells have it. Missing weight is renormalised away; > 40% missing → facts only.
  < 5 scoreable cells or < 30% of the selection scoreable → insufficient data (e.g. the airport).
- **Confidence** = weight-averaged data quality (observed 1.0, lower-bound 0.7, proxy 0.6,
  mock 0.3, missing 0): High ≥ 0.75, Medium ≥ 0.5.
- **Hotspots**: top cell scores, no two within 1 ring of each other, each with its two strongest
  contributing factors as the "why".
- **Reports are immutable at the DB level** (trigger rejects UPDATE always). DELETE is allowed only
  with `SET LOCAL sitescout.purge = 'on'` — used by test teardown and once to purge a report
  created during a dev defect (audited as `purged`). App code never sets it.
- **Runner fix found by this phase**: step outputs are persisted as JSON, but later steps used to
  receive the raw Python object (e.g. `Decimal`), so a first run and a resumed run could see
  different values. Later steps now receive the JSON round-trip of what was persisted. Postgres
  `numeric` results are converted to floats at the source.
- **First results** (snapshot 10, config 0.6.0): T Nagar (600017) 65.8 Moderate fit / High
  confidence: strong anchors (89) and demand (68), weak competition (16). Tondiarpet zone 51.7:
  close to existing Savomart stores (cannibalisation 10) with sparse OSM anchors.

## Phase 4b decisions (LLM narrative)

The user asked for careful use of API calls, with fallbacks and retries.

- **Providers**: Gemini `gemini-3.1-flash-lite` (primary), Groq `openai/gpt-oss-120b` (fallback),
  from `.env`. Both checked first via their free model-listing endpoints (no generation quota).
  Plain `httpx` against the REST APIs, not the vendor SDKs: one dependency, same error handling
  for both, easy to fake in tests.
- **Spend protection** (config `llm:`):
  - *Cache*: a validated response is reused for the same fact sheet + provider + model + prompt
    version; re-running an unchanged area costs nothing. Cached answers are re-validated before use.
  - *Retries*: at most 1 retry per provider, only for transient errors (timeouts, connection
    errors, 408/409/425/429/5xx), with exponential backoff + jitter; `Retry-After` (and Google's
    `retryDelay`) honoured. If the wait would exceed the remaining time budget, skip to the next
    provider rather than sleep.
  - *Permanent errors* (400/401/403/404, blocked prompt): no retry, next provider immediately.
  - *Invalid output* (bad JSON or validator rejection): 1 retry on the same provider with the
    validator's reasons included in the prompt, then next provider.
  - *Circuit breaker*: 3 straight failures → provider skipped for 5 min. *Spacing*: ≥ 4s between
    Gemini calls, ≥ 2s for Groq. *Total budget*: 90s for the whole chain, then template.
  - Breaker and spacing are per process (one worker). Several workers would need them in Postgres.
- **Validator**: every number in the text must equal a fact-sheet number or be a rounding of one
  (65.8 → 66 ok; 72.3 rejected), plus the 0/100 scale; a rating label must be the sheet's; known
  places/stores (zones, Savomart stores, in-area locality names, minus generic single words)
  mentioned in the text must appear in the sheet. The `validate` job step re-checks the final
  narrative independently and substitutes the template if it ever fails.
- **Caveats are code-owned**: the model writes summary/why/where-to-scout only; caveats (lower-bound
  competition, proxy demand, approximate boundary, masked cells) are always appended by code.
- **Every call is logged** in `llm_calls` (status ok/invalid/error/cached, HTTP status, latency,
  tokens, validator errors), committed outside the job step so a crash never loses a paid-for
  answer. Reports record `narrative_source` + model, cached flag and the full attempt list.
- **Tests never spend quota**: an autouse fixture makes every test template-only unless it passes
  fake providers (real adapters over `httpx.MockTransport`). Live checks: `make llm-smoke`.
- **Measured live**: Gemini returned 503 "high demand" on 2 of 3 first attempts; each time one
  retry succeeded (~9s). Groq succeeded first try (~5s). ~1.3–1.4k input / ~340 output tokens
  per narrative. Re-run of an unchanged area: served from cache, 0 calls.
- **Ops gotcha (hit twice now)**: containers read `.env` only at creation; `docker compose
  restart` keeps stale values, so the worker ran with no keys and silently used the template.
  Fixes: `make reload-env`, and the attempt log now states "no LLM provider configured".

## Phase 5a decisions (frontend shell + selection)

Phase 5 split like 3 and 4: **5a** = shell, map, selection, run + progress; **5b** = report view,
list/history, compare.

- **Libraries**: React Router (linkable report/job URLs), TanStack Query (fetching + job polling
  at 1s until terminal; no retries on 401/403/404/422), MapLibre GL 6, h3-js (5b).
- **Base map: OpenFreeMap "positron"** — free, no key, MapLibre-native, muted so purple overlays
  read clearly. It's the only thing the browser loads from outside our API; all analysis data is
  ours (Core rule 4 is about analysis inputs, not base-map tiles).
- **maplibre-gl 6 gotchas**: named exports only (`import { Map }`), and its web worker is loaded via
  `new URL(<name>, import.meta.url)`, which Vite's dependency pre-bundling breaks (blank map,
  "Worker failed to load"). Fix: `optimizeDeps.exclude: ['maplibre-gl']`. A production build will
  need the worker files served as static assets — Phase 12 (deploy).
- **Selection UX**: every mode ends in a server preview (`/areas/preview`), so the UI never
  computes geometry itself. After a pincode/locality preview, clicking a map cell adds or removes
  it (tracked as `add_cells`/`remove_cells`, undoable). Outside-GCC localities are listed but
  disabled with the reason, rather than hidden. The map flies to an area once per new base
  selection, not on every edit. Mostly-unscoreable cells (< 30% scoreable land) are greyed.
- **Jobs have their own page** (`/jobs/:id`) so a running or failed analysis can be reopened; the
  retry form requires a reason (audited) and sends the job `version` (409 → refresh).
- **Demo auth in the browser**: the session (token + user) lives in localStorage; switching role
  clears the query cache so one role's data never shows on another's screen. Access is still
  enforced by the API; the UI only hides what a role can't use.
- **`make up` now uses `-V`** (renew anonymous volumes): the web container's `node_modules` is an
  anonymous volume that otherwise survives a dependency change. The database volume is named and kept.
- `/areas/grid` (613 cells, 240 KB) is gzip-compressed by the API → 38 KB.

## Phase 5b decisions (report view + compare)

- **Report page order follows the manager's questions**: verdict (score, rating, confidence, data
  as of) → why (narrative) → how it was reached (factor table) → where to scout (hotspots, click to
  fly there) → what's there (facts) → caveats → versions. Map beside it: per-cell score heat
  (res-9 cells drawn in the browser with h3-js from the saved `cell_scores`), area outline,
  numbered hotspots, Savomart stores.
- **The narrative's origin is always shown**: "Written by Gemini (model) from the fact sheet",
  plus "after Gemini: HTTP 503" when it took a retry, "reused from an identical earlier analysis"
  on a cache hit, and an amber **Degraded** notice when the template stood in for a failed AI.
- **Factor table**: provenance badge per factor (observed / lower bound / proxy / mock / missing),
  raw value with unit and source, normalised bar, configured vs effective weight (shown when
  renormalisation changed it), points; missing factors stay listed as "not scored → weight
  redistributed" instead of disappearing.
- **Compare** works for two versions of one area or two different areas. The API's flags are
  spelled out: different area / different data snapshot / different config ("part of any
  difference is the rules changing"). Both areas are drawn on one map.
- **Cells-mode labels** now name the nearest in-area locality and zone ("3 cells near Venus Colony
  (Teynampet zone)") so the report list says where hand-picked areas are. Existing reports keep
  their labels (immutable).

## Phase 6a decisions (scout tasks + properties)

Phase 6 split: **6a** = tasks, save-first properties, validation, duplicates, photos, access;
**6b** = evaluation job, pipeline, follow-up loop.

- **Scout tasks** are created by the BD Manager, usually from a report's hotspots (their res-8
  parents become the target cells); only BD Executives can be assignees. An executive sees only
  their tasks and, inside each, only the hotspots it covers (docs/DESIGN.md §4: "hotspots of
  tasked areas only"). Executives move tasks open → in_progress → done; only the manager cancels
  or reassigns. Onboarding the first property under a task moves it to in_progress (audited).
- **Save first, idempotent**: `client_id` (UUID from the phone) is unique, so a retried submit
  returns the saved record (200) instead of creating a second one.
- **Reject vs warn**: only truly unusable input is rejected (422, nothing saved): pin at (0,0),
  outside GCC, inside a water/sea polygon, negative money, rent without a unit. Everything else is
  saved with warnings: GPS accuracy > 50 m, pin > 500 m from the executive's own position, rent
  of 0 (treated as unknown), rent/sq ft outside 0.5× – 2× the illustrative zone band. Missing
  critical fields (rent, area) and photos are listed, never guessed.
- **Duplicates never merge or block silently**: a save within 25 m of a property with a similar
  name (trigram ≥ 0.35) is stored as `possible_duplicate` with its candidates. The executive
  chooses "same" (their entry is kept but marked merged, and its location notes are attached to
  the original as a note) or "different" (flag cleared). Both are audited.
- **Row-level access** (BD Manager: all; BD Executive: own) lives in services; field masking stays
  in the per-role builders. Survey roles get 403 on property endpoints for now; they'll reach
  study-linked properties through M3 study endpoints with their own masked views.
- **Photos** upload separately (jpeg/png/webp, ≤ 8 MB) to the git-ignored `uploads/` volume;
  a property without photos is saved and flagged `photos` missing until one arrives.
- **Location context** (`/reference/locate`): in GCC? in water? ward, zone, pincode, nearest
  neighbourhood name (OSM place names preferred over raw post-office strings) and the
  illustrative rent band — used to prefill the form and by the validator.
- **Rent bands are mock** (`mock_rent_bands` in config; see `data/MANIFEST.md`).

## Phase 6b decisions (evaluation + pipeline)

- **Site-level measures use H3 rings**, not an exact radius: the pin's cell + 2 rings (≈ 600 m;
  the design asks for 500–600 m) for demand, the M1 ring measures for competition (~650 m) and
  accessibility (~350 m). The same measure for every scoreable cell is the citywide distribution,
  so percentiles are consistent with M1 and cost nothing extra (cached on the city model).
  Cannibalisation is the exception: the exact distance from the pin to the nearest operational
  store, because the 400 m hard flag must be precise.
- **Factors** (weights from design §6): site demand 25 (proxy), competition 15 (lower bound),
  cannibalisation 15, rent affordability 15 (**mock** — the entered rent is real but the band it's
  positioned in is illustrative, so the factor is honestly labelled mock and lowers confidence),
  accessibility 10, visibility/frontage 10 (self-reported; poor/fair/good → 20/60/100, frontage
  10–20 ft → 0–100), area opportunity 10 (derived: the M1 score of the pin's cell).
- **Completeness is a gate**: missing rent or area → Needs Info (score still shown, marked
  provisional); > 40% of weight missing → Needs Info. **Hard flag** (Savomart within 400 m) caps
  the outcome one level and says so ("capped from Consider to Weak Fit by hard flag").
- **Risks are rules** with id, severity, evidence: R-CANNIBAL, R-DATA (high); R-RENT-HIGH,
  R-RENT-UNVERIFIED, R-COMPETITION, R-DUPLICATE, R-LANDUSE, R-VISIBILITY (medium); R-ROAD-NARROW,
  R-ACCESS, R-PARKING, R-GPS (low). Sorted by severity; the review card shows the top three.
- **Evaluations are immutable versions** (DB trigger, same rule as reports): v1 on onboarding,
  v2… after any real edit ("edited"), a manual re-run, or (M3) a completed study. The `load` step
  freezes the property's fields, so an edit mid-job gets its own next version; the property is
  marked `current` only if nothing changed since `load`.
- **Pipeline rules** live in `services/pipeline.py`: BD Manager only; reason + version on every
  move (409 on a stale version — tested with two moves on one version); illegal jumps refused with
  the allowed list; study stages reserved for M3's Request study; reject → reopen allowed.
- **Follow-up loop**: the manager's request moves the property to `needs_follow_up` and assigns it
  to the onboarding executive (a manager-added property can't have one — 422). The executive's
  response adds a note and the system returns the property to `under_review`, audited with the
  executive as actor and `system_transition: true`. The manager moving it on withdraws open requests.
- **Engineering**: the job registry is now lazy (`registry.kinds()`), because job modules import
  services and services enqueue jobs. Services enqueue on `queue.DEFAULT_QUEUE`, which the test
  suite points at the test queue so the live worker never evaluates test data.

## Phase 7a decisions (BD Executive mobile flow)

- **Scout tasks start from a report**: the manager's Create scout task panel sits on the report
  page and carries the report's cells + hotspots, so the executive's task map shows exactly what
  was analysed, with the reason per hotspot and a directions link.
- **Pin first, then the form**: GPS when allowed; if denied or unavailable the form says so and
  falls back to tapping the map (framed on the task area, not all of GCC). Every pin is checked
  live via `/reference/locate` (outside GCC / water → shown before submit) and prefills locality,
  pincode, ward and zone. Rent shows ₹/sq ft against the illustrative band as a hint, never a block.
- **Drafts on the device**: the form autosaves to localStorage once it has a pin or a label
  (empty drafts are not kept); the draft's client id is the submit id, so a retried submit
  returns the saved property instead of a duplicate (Core rule 6 applied to M2).
- **Duplicates are the executive's call**: a flagged property shows the candidate with
  Same property / Different property. A merged entry gets a short page pointing to the original
  instead of a stale evaluation card.
- **Photos** load through an authenticated blob fetch (the API requires the bearer token, so a
  plain `<img src>` can't be used).
- **List endpoint returns the latest outcome + score** (one max-version join), so My properties
  and the 7b board need no per-row requests.
- **Phones**: the header nav gets its own row under the brand + role switcher.

## Phase 7b decisions (BD Manager pipeline UI)

- **The API says what's allowed next.** The manager's property response carries
  `pipeline: {moves, follow_up: {allowed, why | assignee}}` from `services/pipeline.actions`, so the
  stage rules exist only in `pipeline.py` and the UI can't offer a move the server would refuse.
  Executives never receive it.
- **Moves happen on the review page, not by dragging on the board.** Every move needs a reason, so
  a drag would have to open the same dialog anyway; the board is for triage (by stage, best-rated
  first, search + outcome filter, duplicate / missing / no-photo flags; merged entries hidden).
- **409 handling**: on a stale version the dialog stays open with the reason kept, the property is
  re-read, and the manager confirms again on current data; if the move is no longer legal from the
  new stage the confirm button is disabled and says why. Tested with a second-tab move in the browser.
- **Reason presets** are shortcuts that fill the textarea; the manager can always edit them.
- **Evaluation versions**: the breakdown shows the latest, with a picker for older versions
  (fetched on demand) and a Re-evaluate button; older versions are labelled as such, never replaced.
- **History** shows actor names (joined in the history endpoint), from → to, the reason, and marks
  the executive-answer return to review as *automatic*.
- Nav: the manager's "Properties" link became "Pipeline" (`/properties` still lists everything).

## Phase 8a decisions (catchment studies: request + reuse)

- **Catchment = segments whose midpoint is within 600 m** (not clipped): segments keep their stable
  ids and a lane mostly outside the circle isn't surveyed. Measured: 315–540 segments,
  25–33 km of road per catchment. A bounding-box prefilter on the GiST index took the catchment
  query from 1.3 s to 53 ms.
- **Reuse state per segment**, from its captures: `fresh` (surveyed within 90 days → reused,
  covered), `fresh_gap` (recent could-not-survey → handled, not covered, not retried until
  stale), `stale` (only older captures → surveyed again, never reused), `uncovered`. Coverage is
  length-weighted fresh length. A newer capture always wins; an older one never hides a fresh one.
- **Captures outlive snapshots**: a capture made on an older data snapshot is reused only if its
  segment id matches and the geometry is unchanged within 10 m (Hausdorff in UTM 44N) — ids are
  only stable within one snapshot. Tested both ways.
- **Three reuse modes**: `reuse_and_fill` (default: reuse fresh, survey stale + uncovered),
  `reuse_only` (survey nothing; lower-confidence summary), `full_survey` (waive reuse). Any
  non-default mode needs a reason from the BD Manager at request. The Survey Manager's plan is
  final; changing the requested mode, or reuse-only below 80%, needs their own reason. Coverage is
  re-checked at planning (captures may have aged). Both decisions are audited with coverage.
- **Study stages are entered only by the study workflow** (`pipeline.study_transition`):
  shortlisted → study requested (on request) → in progress (8b, on assignment) → complete
  (Phase 10). Cancelling returns the property to shortlisted; rejecting / putting on hold mid-study
  cancels the study. Captured data always stays (captures are append-only).
- **One open study per property** (partial unique index + 409). A study request carries the
  property version (optimistic lock) like every other stage change.
- **Survey Manager** sees studies with the property through the masked survey view; the BD
  Manager sees the status and reuse summary, not the segment map. Survey executives: 8b.
- **Lane observation schema** is defined now (`schemas/studies.LaneObservations`) so the demo seed
  and Phase 10's capture form share it. Time band is auto-stamped from the capture time (IST).
- **Demo seed captures** (`make seed-captures`) are synthetic, marked `source = demo_seed`, listed
  in `data/MANIFEST.md` as mock data. They exist only so reuse can be shown before any survey.
- The BD Manager's Request-study button + coverage preview dialog is UI work for Phase 9
  (`GET /studies/preview` and `pipeline.study` in the property response are ready for it).

## Phase 8b decisions (survey units)

- **Partitioning benchmarked, not assumed** (4 real catchments at full survey + the gaps-only
  study #52; both methods scored by the same nearest-neighbour walk estimate):

  | Method | worst unit ÷ mean | walking share | pieces / unit | time |
  |---|---|---|---|---|
  | DFS order cut into equal chunks | 1.15–1.38 | 5–20% | 2.0–7.9 | ≤16 ms |
  | Balanced region growing | 1.06–1.11 | 9–13% | 3.2–4.3 | ≤170 ms |
  | **Region growing + smoothing (chosen)** | 1.12–1.17, every unit 121–180 min | 5–9% | 1.5–2.1 | ≤1.3 s |

  Growing: k = ⌈total ÷ 150 min⌉ seeds by farthest-point network distance; the least-loaded unit
  repeatedly takes the nearest unassigned to-survey segment along the road graph. Smoothing hands a
  unit's stray pieces to a unit they touch when both stay within 120–180 min by the same
  estimate the UI shows. All catchment segments are walkable; only to-survey ones are assigned.
- **Workload** = length ÷ 70 m/min + 6 min per segment (5-min count + form) + walking between the
  unit's segments. Parameters in `studies.units` (config 0.11.0). Gaps-only studies stay in
  many pieces by nature (the gaps are scattered); the walking time is counted in their minutes.
- **One segment, one unit**: `study_segments.unit_id` holds at most one unit by construction;
  after every generate / move / split / merge the service re-validates in the same transaction
  that every to-survey segment has a unit, no reused segment does, no segment points at another
  study's unit and no unit is empty — any violation is a 422 and nothing is saved (tested by
  corrupting the plan directly and making an edit).
- **Edits lock the whole study plan** (`studies.version`): one Survey Manager edits a plan at a
  time; a stale edit is 409. Estimates are recomputed for every unit an edit touches.
- **Units are generated at planning** (and can be regenerated with a reason) until the first unit
  is assigned; from then on the plan is fixed and only edits apply. The first assignment moves
  the study to in progress and the property to study in progress (via the study workflow).
- **Reassign keeps captured data** (captures belong to the segment); unassign is refused once a
  unit has captures; merging units held by different executives is refused. Captured segments
  can't be moved.
- **Survey executive** sees `/my/units` (in-progress studies only) with the property as
  `{id, label}`, and the segment map of their own units only.

## Phase 9a decisions (study request + reuse decision UI)

- **One reuse vocabulary** (`features/studies/reuse.jsx`): the four segment states with fixed
  colours, the three modes with one-line explanations, a length-weighted coverage bar plus the
  design's one-line message and the oldest reused age. The BD dialog, the Survey Manager's page and
  the BD study card all render the API's summary through it, so they can't disagree.
- **The request dialog previews before writing** (`/studies/preview`), and says up front when a
  reason is required and why (override; below the reuse threshold). The UI mirrors the server's
  rule only to explain it — the server still enforces it.
- **The Survey Manager's page leads with the evidence** (coverage + catchment map: to-survey
  lanes drawn thick) and the decision shows what BD asked for and why, so an override is informed.
  Confirming re-checks coverage and generates units; the unit table is read-only until 9b.
- **BD sees status only**: the study card shows coverage, both decisions with reasons (flagged
  when the Survey Manager changed the mode), lanes to survey, unit counts and hours, and cancel.
- **App shell fix**: the shell is one screen tall, so `<main>` is now the scroll container and
  `body` carries the brand background — long pages no longer run past the background.
- **Test isolation**: study tests moved to a site no demo property uses (Perambur), with a guard
  that fails loudly if non-test captures appear there (the demo seed around #52 had broken them).

## Phase 9b decisions (unit planner, progress, survey executive's units)

- **One map, two views** on the study page: *Reuse* (lanes by reuse state) and *Units* (lanes by
  unit, reused lanes thin grey). In the unit view the Survey Manager taps lanes to select them
  (yellow), then moves them to a unit or splits them into a new one; tapping a unit row highlights
  it and offers merge. Every edit goes to the API, which re-validates one-lane-one-unit; a 409
  reloads the plan and keeps the selection.
- **Clickable overlays** in `MapView`: layers marked `clickable` get click + pointer handlers. Thin
  lanes are hard to tap, so each clickable lane layer has a wide invisible hit layer (opacity
  0.01, not 0, so it is certainly queryable).
- **Map layers attach on `style.load`, not `load`**: `load` also waits for the first base-map
  tiles — OpenFreeMap cold loads kept lanes/grid invisible for 10–15 s. Warm: style.load 11–16 ms
  vs load ~115 ms. The analysis map was re-checked after the change.
- **Progress** counts each lane once by its latest capture in this study (surveyed / could not
  survey); per unit and rolled up on the study (`handled / lanes`, %). Shown to the Survey
  Manager per unit, to BD in the study card, to the executive per unit.
- **Walking order**: a unit's lanes are listed and numbered on the map in the nearest-neighbour
  route that its time estimate assumes (starting from the lane farthest from the unit's centre),
  so the estimate and the field route agree. `partition.walk()` is shared by both.
- **Survey executive**: home = "My units today" (units on in-progress studies, to do first); a unit
  page with the numbered lane map, the lane list, directions, and the property only as a label.
  Capture itself is Phase 10.
- Survey roles no longer request `/reference/stores` (BD-only on the API) — no 403 noise.

## Unit fragmentation fix (after Phase 9b review)

Reported: a 0.8 km unit in 17 disconnected parts (study #52). Measured before changing anything:

- **The partitioner was not the cause of that case.** Pieces equalled the floor — the number of
  connected stretches among the to-survey lanes (study #52: 57 lanes in 41 stretches, 33 of them
  single lanes; #173: 51 stretches) — and no stretch was split across units. The fragmentation was
  in the **demo seed**: it marked a uniformly random 85% of lanes fresh, so the leftover gaps were
  isolated single lanes. Real past surveys cover contiguous walks, so stale/never-surveyed areas
  come in blocks.
- **Seed fixed**: `make seed-captures` now grows contiguous past-unit clusters (~2.5 km, one field
  day each) over the road graph, folds 1–2-lane remnants into a neighbouring cluster, marks whole
  clusters fresh / stale / never surveyed, and puts could-not-survey as single gated lanes inside
  surveyed walks. Over 5 random seeds: #197's stretches went 48 → 1.6 (avg 76 m → 1.7 km).
- **With realistic data the partitioner did over-split**: its all-units-at-once growth (least-loaded
  takes nearest) made units interleave along one long stretch (1.6–2.4 stretches → 5–10 pieces,
  worst unit 9 parts). Replaced (config `studies.units.method: peel`, 0.12.0) by **stretch-first
  peeling**: short stretches (< 120 min) attach to the nearest long stretch by road; each group is
  one unit if its estimate (including walks to attached stubs) is ≤ 180 min, else it is peeled
  into ⌈minutes / 150⌉ contiguous units — one at a time from the edge of what's left, growing only
  through lanes touching the unit, each aiming at what's left ÷ units left and stopping where it is
  closest to that share. Benchmark (5 seeds × 2 demo properties + 4 full-survey catchments, same
  estimate for both):

  | | grow (old) | peel (new) |
  |---|---|---|
  | demo: pieces / unit (worst) | 1.7–2.0 (9) | 1.3 (2–4) |
  | full survey: pieces / unit (worst) | 1.4–2.0 (5) | 1.3–1.7 (5) |
  | unit minutes range | 92–180 | 91–180 (91 only where the whole study is ~4.5 h) |
  | walking share | 5–8% | 3–5% |
  | time | ≤ 1.2 s | ≤ 0.6 s |

  Pure tests (`tests/test_partition.py`) pin it: one long street → every unit one piece; 8×8 and
  12×12 street grids → ≤ 2 pieces per unit and balanced; a stale block inside reused lanes stays
  whole. `grow` stays selectable so the benchmark can be re-run.
- A mis-step, recorded: I first read study #479 as "3 stretches → ideally 3 units" and lowered the
  stub threshold; it was one 331-min stretch + two 20-min stubs (optimum 5 pieces for 3 units; we
  make 6), and the lower threshold hurt balance elsewhere — reverted.
- Demo studies were cancelled with a reason and rebuilt on the new seed through the API: #479
  (property 197, 3 units of ~2.1 h) and #480 (property 52, 5 units of 2.4–2.5 h, 1–2 parts each).

## Phase 10a decisions (lane capture)

- **One form per lane, raw observations only** (`schemas/studies.LaneObservations`, bounds that
  reject typos not unusual lanes; unknown fields refused). Surveyed needs observations; could-not-
  survey needs a reason and carries none (schema-level rule). Nothing is scored on the phone.
- **Who/when**: only the unit's assignee, only lanes of that unit, only while the study is in
  progress and the unit isn't submitted — the Survey Manager and BD roles get 403. A cancelled study
  closes capture (409).
- **Idempotent by client id** generated when the lane's draft is created; a re-send returns the
  saved capture with 200 (`created: false`). A client id reused by another user is a 409.
- **Time**: the device's capture time is kept (offline drafts are sent later) but checked: > 10 min
  in the future or > 7 days old is refused (`studies.capture`, config 0.13.0). The time band is
  stamped server-side from it (IST), never typed.
- **GPS required; distance checked server-side** (new `gps_distance_m`): > 75 m from the lane is
  saved and flagged, never refused. When location is blocked the executive taps their position on
  the map; it is recorded with no accuracy (manual).
- **Corrections**: a lane can be captured again until the unit is submitted; captures stay
  append-only, the latest counts (progress + roll-up), and the re-capture is audited.
- **Unit submit** only when every lane has a capture (surveyed or could not survey); idempotent;
  audited with the counts. Units move draft → assigned → in progress (first capture) → submitted.
- **Field UX**: a 5-minute timer with a large +1 tap counter (start time is in the draft, so a
  reload keeps counting), undo / cancel, or "I counted another way"; steppers; anchor chips;
  segmented ratings; a sticky Save listing what's still needed; next lane in walking order after
  each save, with the previous save's confirmation and any GPS warning.
- **Offline**: every change autosaves (localStorage); a failed network call marks the draft queued
  and the unit page offers "Send now" (same client ids); a refused re-send un-queues it for fixing.
  Found in testing and fixed: a failed background refetch replaced the unit page with "Failed to
  fetch" — cached data now stays on screen with a "No connection" note.
- Cut: capture photos (design: optional). Notes cover it for now.

## Phase 10b decisions (roll-up → Catchment Summary)

- **Which capture counts per lane**: its latest capture in this study; otherwise the fresh capture
  the plan reused (never under full survey). Aggregates use **surveyed lanes only**; could-not-
  survey lanes are handled but carry no data; unsurveyed lanes are never filled in. The single
  labelled exception is the competition estimate across the whole catchment ("assumes unsurveyed
  lanes are similar").
- **Signals** (hand-checked in `tests/test_rollup.py`): residential and commercial per 100 m
  (sum ÷ surveyed length); footfall = timed count → hourly rate, length-weighted, with the time-band
  mix, flagged when ≥ 85% of length is one band; accessibility = ordinal mean of road width,
  pedestrian and vehicle access + share rated poor; parking = ordinal mean + share with parking;
  competition = stores per km of surveyed lane, catchment estimate, and OSM's competitor count in
  the same 600 m; anchors de-duplicated (same type, same or unknown name, within 120 m).
- **Provenance per lane** (observed / observed · reused survey / mock); a signal takes a source's
  label when it is ≥ 90% of surveyed length, else "mixed", with exact shares always shown.
- **Scores** use `studies.rollup.normalize` thresholds — **uncalibrated assumptions**, said so in
  config and UI. **Below 50% coverage: facts only** — every score is withheld, the numbers remain.
- **Confidence**: coverage (≥ 80% high, ≥ 50% medium, else low), then one level down for each of:
  single time band, reuse only, > 50% reused data, > 50% demo data. Reasons are listed.
- **A job** (`study_rollup`: collect → aggregate (pure) → save) writes an **immutable, versioned
  summary** (DB trigger) and completes the study (property → study complete via the study
  workflow). Triggers: the last unit submitted; planning with nothing to survey (reuse only); the
  Survey Manager closing early (reason required) or re-running (reason, new version). A second
  roll-up while one is queued/running is a 409.
- **Robustness found while testing**: the worker ran old code (no reload), met the new job kind,
  raised out of its loop and **died**, leaving the job "running". Fixed three ways — the runner
  fails an unknown kind cleanly, the worker loop survives any per-job error, and compose restarts
  the worker (`restart: unless-stopped`) and reloads it on code/config changes (`watchfiles`; the
  api reload now also watches `/config`). The new worker's reaper re-queued the stuck job, which
  then succeeded — the designed recovery path.
- **Demo seed corrected again**: counts were drawn per lane regardless of length (avg lane ≈ 75 m),
  giving 586 pedestrians/h and "OSM undercounts 63×". Counts are now Poisson draws from per-length
  rates by road type (homes 8–25 / 100 m residential, 4–12 main; businesses 0.5–2 / 4–12 per
  100 m; grocery 1–3 / 4–8 per km; footfall 40–180 / 240–720 per hour). Demo studies were rebuilt
  through the API with reasons: #795 (property 197, in progress, U1 → Arjun) and #796 (property 52,
  closed early → summary v1). The old #480 summary stays on record (immutable).

## Phase 10c decisions (v2 evaluation + diff — the M1→M3 loop)

- **Trigger**: saving a Catchment Summary completes the study and enqueues a `property_evaluation`
  with trigger `study_complete` (after the study transition, same code path as any re-evaluation).
  The job's steps are load (latest summary + previous evaluation) → evaluate → diff → narrative →
  save. v1 is never touched; v2 is a new immutable version (migration 0014 adds `study_id`,
  `summary_id`, `diff`, `narrative`, `narrative_source`, `narrative_meta`).
- **What the study replaces** (`evaluation.study.replaces`, config 0.15.0): site demand ← observed
  residential density, competition ← observed competition, accessibility ← observed accessibility,
  each with the summary's provenance (observed / mixed) and source "Catchment study #N (summary vX)".
  **Footfall** joins as a new factor (weight 15). Other factors keep their estimates; weights
  renormalise as always. **A facts-only summary replaces nothing** — estimates stay, and
  R-STUDY-THIN says why. New study risks: R-COMPETITION-OBSERVED, R-FOOTFALL-LOW,
  R-FOOTFALL-BAND (single time band), R-ACCESS-OBSERVED (share of lanes rated poor).
- **Diff classification** (`services/diff.py`, pure): every changed factor gets all causes that
  apply and a primary one in the order newly included > dropped > data change > config change >
  renormalization. Same raw value normalising differently is a data change if the data snapshot
  moved, else a config change. **Renormalization** is primary only when nothing about the factor
  itself changed. Per-factor point changes must add up to the score change; the diff carries the
  rounding gap and the UI shows it.
- **Honesty fix found live**: competition "improved" (+7.2) although the survey found ≈12× OSM's
  store count — because the estimate is a citywide percentile and the study value is scored on
  uncalibrated thresholds. Rather than hide it, the explanation for any proxy → study switch says
  the scales differ, the fact sheet carries that caveat, and the review page shows a "Not
  like-for-like" note pointing at the observed facts. Calibrating thresholds needs real surveys.
- **Narrative**: the adapter was generalised to a `NarrativeSpec` (system prompt, schema, user
  message, validator, template, finish) so the diff reuses the whole chain (cache → Gemini → Groq
  → template, retries, breaker). The diff validator checks numbers (absolute values allowed, so
  "down 8" traces to −8.0), ratings, causes (no cause the sheet doesn't give) and place names. The
  template passes its own validator (tested). Bump `llm.diff_prompt_version` when the prompt changes.
- **UI**: `DiffCard` on the BD review page — before/after score and rating, cause chips, the
  narrative with its source, the factor table (normalised, weight, points) with the sum check,
  newly observed facts, new and resolved risks.

## Phase 11 decisions (bonus: city-wide opportunity map)

- **Pocket formation, benchmarked** on the live snapshot (410 rated selection cells): connected
  components of top-10% score cells gave blobs of up to 90 cells plus 29 fragments under 3 cells;
  greedy growth over selection cells (seed = best open cell, add the best adjacent cell above the
  citywide 80th percentile, ≤ 3 cells ≈ 2 km² = one scouting trip, pocket + ring closed afterwards)
  gave 23 compact pockets in 34 ms. Chose greedy growth.
- **One engine, one number**: a selection cell is rated by the mean of its scoreable score cells,
  but a pocket's displayed score is `scoring.score_area` over its score cells — exactly what the
  area report computes, so "Run analysis" reproduces it (tested; live: Pudupet 77.3 both ways).
- **Live view, not a snapshot**: citywide scoring costs ~20 ms once the city model is cached, so
  the map is recomputed on request and stamped with data snapshot + config version. The immutable
  record is the area report started from a pocket (Core rule 2 applies there).
- **"Un-scouted"** = no property (any stage, not merged), no scout task that isn't cancelled, no
  operational Savomart store in the selection cell. Skipped cells are shown grey with the reason.
  Cells already covered by an area report stay eligible and are labelled "already analysed" —
  analysed is not scouted.
- **Honesty**: every pocket is labelled a desk estimate (proxy), nobody has visited; competition is
  an OSM lower bound; "why" names the top two factors as "top N% of Chennai".
- **UI**: `/opportunities` (BD Manager nav + home link). Run analysis = the existing
  `POST /areas/reports` with the pocket's cells; Adjust cells = the analyse page pre-filled via
  router state. Found in testing: on phones the list squeezed the map (fixed height now), and
  pocket fill looked like the grey scouted cells (pockets are outline-only unless selected).
- **Test hygiene found**: two concurrent `make test` runs share the test DB and "test" queue — they
  steal each other's jobs (lease_lost), deadlock, and purge each other's fixtures. Run one at a time.

## Phase 12b decisions (fresh clone → running app)

- **Every raw file re-traced to a public, byte-identical source** and pinned by sha256 in
  `scripts/fetch_data.sh`: Geofabrik dated extract, Microsoft tiles (URLs from the release index),
  OpenCity KML resource URLs (via its CKAN API), datameet `Chennai/boundary.geojson`, and the
  pincode CSV inside the `bharatpin` 1.0.1 wheel. A mismatch is an error, never accepted. The Stores
  API stays token-gated (read from `.env`). A guessed URL for one Microsoft tile was wrong — found
  by checking the index, which is why every URL is verified by checksum rather than trusted.
- **`make setup` is idempotent**: `.env` from the example with a random `APP_SECRET`; verified files
  skipped; migrations run in a one-off container **before** the api starts (the api registers the
  config at startup and can't boot on an empty schema, and `--reload` wouldn't restart it after a
  later migrate); ingest `--if-empty` skips when a ready snapshot exists.
- **Tested for real**: a clean clone under a separate compose project and volume (`sitescout_fresh`),
  the main stack stopped meanwhile (its volume untouched) and restarted after. Result: 1 m 48 s to a
  running app, opportunity map identical (Pudupet 77.3), 225 tests pass + 1 skip by design (needs two
  snapshots), re-run 16 s. The test project was removed with its volume.

## Phase 12c decisions (demo story)

- **Through the real API, in-process** (`TestClient`, each persona's own token, a reason on every
  change) rather than SQL inserts: the audit trail, validation, versions, jobs, reuse and roll-up
  are genuine, and the story breaks loudly if the product does.
- **Three demo-only switches, all in-process, none exposed by the API**: jobs on a private `demo`
  queue drained by the script (the live worker never sees them); no LLM providers (template
  narratives, zero API calls; `--llm` opts in); `captures.SOURCE = "demo_seed"` so synthetic lanes
  roll up as **mock** — a synthetic capture must never read as observed field data.
- **Found while testing**: (1) client ids must be UUID v4 — deterministic ids are uuid5 bytes with
  the version bits set to 4, so re-runs stay idempotent; (2) the second site sat 1.65 km from the
  first, so no catchment overlap and 22 units — moved to ~450 m so study 2 reuses study 1's fresh
  lanes (9 units), which also demonstrates cross-study reuse; (3) street names in labels could be
  wrong (pins are hotspot centres; the locality lookup said Chintadripet for a "Pudupet" label), so
  labels name only what's true by construction (area / pocket).
- **Verified on a fresh install** (separate compose project + volume): 4.5 s, every persona's home
  populated as described, purge → reseed works, a second run is a no-op, tests 225 + 1 skip.

## Phase 12d decisions (production build, edge-case pass)

- **MapLibre's worker was missing from the production bundle.** MapLibre 6 builds the worker URL
  from a variable (`new URL(e, import.meta.url)`), which Vite can't analyse, so `dist/` had no worker
  and a production map would stay blank; the dev server (serving node_modules as-is) hid it. Fix:
  import the worker with `?worker&url` (ES format — MapLibre starts a module worker) and call
  `setWorkerUrl`; Vite then bundles it with its shared chunk. Verified in the browser in both modes.
- **`make prod`** is a compose override, not a second stack: nginx serves the static build on the
  same port (SPA fallback, immutable hashed assets, gzip), the api runs without `--reload` (2
  workers), the worker without `watchfiles`. `VITE_API_URL` is a build arg (Vite bakes it in).
- **Edge-case audit** (`docs/EDGE_CASES.md`): every case in DESIGN.md §8–§10 mapped to its handling
  and test, with the names verified by a script. One gap: a stale Stores cache was handled (factor
  excluded with its age, weights renormalised) but untested — test added. Decided: the hard flag
  keeps using the last known store list even when stale (dropping a store next door because the list
  is old is the worse error). One case stays untested: reassigning a unit mid-survey (one seeded
  Survey Executive). Found along the way: the stores file ages out 30 days after download, so the
  README now says how to refresh it.

## Open questions carried into the next session

1. **Metro fringe: in or out?** Locked rule is "GCC core, add fringe only if data quality
   supports it." The pincode-polygon coverage gap (44% missing) and the fact that 3 of 11
   Chennai stores sit near/past the old-core boundary both lean toward "in," but the actual
   decision is gated on Phase 2's OSM coverage numbers for the fringe area specifically — don't
   decide from the pincode-polygon gap alone, that's a different dataset.
2. **Census 2011 join**: is the cleanup (2008 155-ward map → current 200-ward map) worth ~2-3h,
   or does OSM building density alone suffice as the demand proxy? Not yet tested either way.
3. ~~**Docker Desktop status on the user's Mac**~~ — **closed in Phase 0c** (installed, running). Was: last confirmed as "not installed" during Phase
   0a. Must be verified again before Phase 0c (Docker Compose scaffold) can proceed —
   `docker run --rm hello-world` was the agreed checkpoint and was never confirmed as run.
4. ~~**Gemini/Groq API keys**~~ — **closed in Phase 4b** (both configured and verified). Was: not yet created as of handoff. Needed before Phase 4 (M1 backend,
   which wires up the LLM adapter) can be checkpointed end-to-end.
5. ~~**11th Chennai store's `store_code`**~~ — **closed in Phase 1** (captured by the ingest).
6. ~~**Demand proxy where OSM buildings are unmapped**~~ — **closed**: Microsoft ML buildings
   (see §Phase 2 gate — decisions).
7. ~~**Metro fringe and Bhuvan**~~ — **closed**: both out (user sign-off, measured).: cut off in a chat paste, cosmetic only — will surface
   naturally once the Stores ingest script runs against the saved JSON file.
