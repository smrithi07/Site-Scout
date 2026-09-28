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
4. **Gemini/Groq API keys**: not yet created as of handoff. Needed before Phase 4 (M1 backend,
   which wires up the LLM adapter) can be checkpointed end-to-end.
5. ~~**11th Chennai store's `store_code`**~~ — **closed in Phase 1** (captured by the ingest).: cut off in a chat paste, cosmetic only — will surface
   naturally once the Stores ingest script runs against the saved JSON file.
