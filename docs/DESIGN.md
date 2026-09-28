# Savo SiteScout — consolidated design

This is the single source of truth for *what* to build and *why*. `docs/PHASES.md` says *when*
to build each part. `docs/DATA.md` says what data feeds it. Anything here supersedes an earlier,
looser version of the same idea discussed anywhere else.

## 1. Architecture

```
React SPA ──▶ FastAPI ──▶ PostGIS
                 │            ▲
                 ▼            │
            LLM adapter   Worker (jobs table, heartbeat, resumable steps)
                              ▲
                              │
                    Ingestion job (offline) ◀── OSM / census / pincode / Stores API
```

- **React SPA**: MapLibre map, role-specific views, local drafts (survey/property forms).
- **FastAPI**: thin routers per domain → auth/role dependency → service layer (business rules)
  → PostGIS. Field masking happens in `schemas/`, one response builder per role — never trust
  the frontend to hide a field.
- **Worker**: same codebase, polls a `jobs` table with row locking + heartbeat. Steps persist
  their own output, so a failed job resumes from the failed step, not from scratch.
- **PostGIS**: the only store — spatial layers, workflow state, immutable snapshots, append-only
  audit log, the job queue itself.
- **Ingestion**: a separate offline CLI in the same codebase. Loads OSM/census/pincode/Stores
  data into a versioned data snapshot. **Never called at request/analysis time** — this is the
  rule that removes most runtime failure modes.
- **LLM adapter**: the only component allowed to call an external AI provider. It receives a
  code-built fact sheet, returns structured narrative text, and everything it returns is
  validated before being trusted.

**Why a Postgres job table + worker loop, not Celery/RQ+Redis**: compared on simplicity,
debugging, deploy cost. A job-table worker needs no extra service, is fully inspectable with SQL,
and is the right complexity for a 48-hour solo build. RQ+Redis is a reasonable upgrade path;
Celery is overkill here.

## 2. Core rules (apply everywhere, always)

1. **Provenance on every value**: `observed` / `proxy` / `mock` / `missing`. Missing is never
   scored as zero. A factor with unavailable data is excluded from scoring and remaining weights
   are renormalized. If more than a config threshold of total weight is missing (starting value:
   **40%**), the report shows facts only, no rating.
2. **Everything meaningful is an immutable, versioned snapshot**: area reports, property
   evaluations, catchment study summaries. Each is stamped with a data-snapshot id, a config
   version, and a timestamp. Re-running never overwrites — it creates a new version. Comparison
   = diffing two snapshots.
3. **Every state change writes an append-only audit event**: who, what, from-state, to-state,
   why (a required reason string), when. Mutable rows carry a `version` field for optimistic
   locking (protects against two managers moving the same property at once).
4. **Analysis reads only our own database.** All external data (OSM, census, pincode
   directory/boundaries, Stores API) is ingested offline first. This is what lets a job's steps
   be deterministic and retryable.
5. **Save first, evaluate after.** A property or survey submission is persisted before any
   evaluation/scoring job runs. A failed evaluation job never deletes or blocks the saved data —
   it leaves the record in a "pending"/"stale" state and can be retried.
6. **Survey drafts are preserved** (local autosave) and **submissions are idempotent** by a
   client-generated UUID — a duplicate submit is a no-op, not a duplicate record.
7. **The LLM only narrates; it never calculates or invents facts.** Flow: code builds a JSON
   fact sheet → LLM turns it into prose → a validator rejects any number/name in the prose that
   doesn't trace back to the fact sheet → on failure: retry once → switch provider
   (Gemini → Groq) → fall back to a deterministic template. Every snapshot records which source
   (`gemini` / `groq` / `template`) actually wrote its narrative.
8. **Config, not code, for tunables.** Weights, thresholds, radii, freshness windows, cell-count
   caps all live in `config/sitescout.yaml`. Every snapshot records the config version it used,
   so re-scoring a stale report with new weights is a visible, auditable act, not silent drift.

## 3. Spatial design

- **Score grid vs. selection grid**: features are computed at a fine H3 resolution (~res 9,
  ~0.1 km² / ~175 m edge — hotspot-level detail). The grid a BD Manager actually *picks cells
  on* is the coarser parent resolution (~res 8, ~0.7 km² / ~460 m edge) — fine enough for
  meaningful selection, coarse enough to be usable to click on. Hotspots surfaced in a report are
  always the fine cells.
- **Non-scoreable cells** (sea, airport, industrial estates, zero buildings) are masked out —
  excluded from area averages and from the opportunity map, so empty land doesn't drag down
  scores that should be about actual neighbourhoods.
- **Selection always converges**: pincode, locality name, or hand-picked cells on the map all
  resolve to the same pipeline — `selection → geometry → H3 cells → M1 analysis`. A cell-count
  cap and floor are both configurable (prevents someone selecting all of Chennai, or a single
  cell that's too small to mean anything).
- **The survey atom is the road segment, not the H3 cell.** This supersedes an earlier draft
  that tried to make cells the survey unit — it broke down because H3 cell boundaries cut roads
  in half. OSM roads are split at junctions at ingest; each resulting segment gets a stable id
  (per data snapshot) and belongs to **exactly one** survey unit, enforced by the system on every
  edit a Survey Manager makes.

## 4. Personas and access

**Principle**: managers see everything in their domain; executives see only what's assigned to
them or created by them. Enforced **server-side** — a role decorator/dependency plus ownership
checks, plus per-role response schemas that strip fields before serialization. The frontend
hiding a button is never the enforcement mechanism.

| Capability | BD Mgr | BD Exec | Survey Mgr | Survey Exec |
|---|---|---|---|---|
| Run / view / compare area reports | ✅ | 👁 hotspots of tasked areas only | ❌ | ❌ |
| City-wide opportunity map (bonus) | ✅ | ❌ | ❌ | ❌ |
| Create scout tasks | ✅ | ❌ | ❌ | ❌ |
| See scout tasks | all | own | ❌ | ❌ |
| Onboard property | ✅ | ✅ | ❌ | ❌ |
| See properties | all | own | 👁 study-linked, rent/deposit/owner stripped | ❌ (label only) |
| **Move pipeline stage** | **✅ only role that can** | ❌ (can request a "Needs follow-up" response) | ❌ | ❌ |
| Request study | ✅ | ❌ | ❌ | ❌ |
| Reuse override | at request time | ❌ | **final say, at planning time** | ❌ |
| See / split / assign study requests | 👁 status only | ❌ | ✅ | ❌ |
| Capture lane data | ❌ | ❌ | ❌ (cannot capture) | ✅ own units only |
| Progress dashboards | BD-side | ❌ | ✅ | own only |

**Field masking specifics**: rent, deposit, and owner/broker contact are **BD-only fields**,
stripped server-side for every other role. Survey Manager sees location, study scope, and
operational notes (address, landmark, access notes) — never commercial fields. Survey Executive
sees only their assigned units/segments; the property itself is just a label to them.

**Home screens per persona**:
- **BD Manager**: map + review queue.
- **BD Executive**: "my scouting tasks" + a prominent "Add property" action.
- **Survey Manager**: request inbox + progress board.
- **Survey Executive**: "my units today" list.

**Auth mechanism**: four seeded users, a role switcher sets the acting user, the API takes
`Authorization: Bearer <user-id token>`. Deliberately simple — this is not where hackathon time
should go — but the 403s it produces on a wrong-role call are real, not cosmetic.

## 5. M1 — Area Intelligence

**Selection** (see §3): pincode / locality name / picked cells, all converging to the same
cell-set representation.

- **Locality search** runs against a **local index built at ingest** (post offices, OSM place
  names, ward boundaries, pincode polygons) — never a live geocoding call. Fuzzy matching;
  results show pincode, ward, and zone to disambiguate. If a name is ambiguous or has no usable
  geometry, **never guess** — offer pincode or cell selection instead. An extent derived from a
  bare point (no polygon available) is explicitly labeled "approximate".
- **Geometry priority**: pincode polygon → ward polygon → point-derived radius (labeled
  approximate), in that order, with the option to add/remove cells before running analysis.

**Scoring — starting weights** (all in `config/sitescout.yaml`, tunable):

| Factor | Weight | Computed from |
|---|---|---|
| Demand | 30 | Census ward density (core city, if the join is usable) → else OSM building/residential density (proxy) |
| Footfall anchors | 20 | OSM transit stops, schools, hospitals, offices, markets |
| Competition | 20 | OSM supermarkets/grocery/convenience. **Always labeled a lower bound** — OSM under-tags kirana shops; say so in the UI. |
| Cannibalisation | 15 | Distance to nearest Savomart store + count within a configurable radius (Stores API cache) |
| Accessibility | 15 | Road density, main-road access |

- Each factor is **percentile-normalized across the service area**, and the report shows
  **raw value → normalized value → weight → contribution** for every factor — this is the whole
  answer to "why should a BD Manager trust the rating."
- Missing/unavailable factors are excluded and the remaining weights renormalized (Core rule 1).
- **Hotspots**: the top-scoring fine cells inside the selected area, each with a short "why
  scout here" built from its top contributing factors.
- **Confidence label** (High / Medium / Low): derived from the mix of observed vs. proxy vs.
  mock values that went into the score.
- **Job steps** (visible progress, each independently retryable): `resolve → gather → score →
  hotspots → narrative → validate → save`. A failed step is named in the UI with a retry button.
- **Reports are immutable, timestamped, versioned, comparable** — saving a new run for the same
  area never overwrites an old one; comparison is a diff of two saved reports, flagged if they
  used different data-snapshot or config versions.

## 6. M2 — Property Scouting and Evaluation

### Scout tasks
BD Manager turns hotspots/opportunity pockets into scout tasks (assignee, target cells, note,
due date). BD Executive sees them on a map with a one-tap route to the "Add property" form.

### Property form (mobile-first)
- **Location**: GPS coordinates (auto), GPS accuracy, locality/address (prefilled from the local
  index), nearby road/landmark.
- **Commercial** (BD-only field, stripped for other roles): monthly rent, rent unit, property
  area, security deposit (if available), availability.
- **Physical**: frontage, road width, floor.
- **Executive assessment** (self-reported, provenance = "observed (self-reported)"): visibility
  (poor/fair/good), accessibility (poor/fair/good), parking (none/limited/good), condition
  (poor/fair/good).
- **Photos**: upload separately from the form submit; the property can be saved without them and
  is flagged incomplete if so.
- **Owner/broker contact** (BD-only field): name, phone.

### Validation
- Pin must be inside the configured service-area polygon; reject water or `(0,0)`.
- Warn (don't block) on poor GPS accuracy or a pin far from the executive's own location.
- Sanity-check rent against the illustrative mock band for the area; flag far-outside values.
- **Duplicate detection**: a match within ~25 m *and* name similarity produces a warning with
  two explicit choices — "same property, add my notes" or "different property" — never a
  silent block or a silent merge.

### Deterministic evaluation

| Factor | Weight | Notes |
|---|---|---|
| Site demand | 25 | Computed at **site level** (radius around the property, configurable 500–600 m) — not the area-level M1 score, to avoid double-counting |
| Competition | 15 | Site-level |
| Cannibalisation | 15 | Site-level; a hard flag if an operational store sits within ~400 m (configurable) |
| Rent affordability | 15 | Rent normalized to ₹/sqft/month, positioned within the illustrative mock band |
| Accessibility | 10 | Site-level |
| Visibility / frontage | 10 | From executive assessment |
| Area opportunity | 10 | The M1 area score, used only as a low-weight context prior |

- **Completeness is a gate and a confidence label — never a scoring weight.** Scoring
  "completeness" as a factor would silently penalize missing data twice; instead, missing
  critical fields (rent, area, a valid location) routes straight to the **Needs Info** outcome.
- **Outcomes**: Strong Fit / Consider / Weak Fit / Needs Info, by score thresholds. A **hard
  flag** (e.g. an operational store within the cannibalisation distance) caps the outcome one
  level regardless of the numeric score.
- **Risks**: deterministic rule-based (rule id, severity, evidence) — not LLM-generated.
- Explainable the same way as M1: raw → normalized → weight → contribution, per factor.
- **The manager review card** (must support a decision in ~30 seconds): rating, top three risks,
  rent vs. band, completeness, duplicate flags. Full detail sits below the fold.

### Pipeline

```
Scouted → Under Review → Shortlisted → Study Requested → Study In Progress →
Study Complete → { Approved | Rejected | On Hold }
```

- **Only the BD Manager moves stages.** The BD Executive cannot; instead there's a manager→
  executive **"Needs follow-up"** loop (more photos, a revisit, a rent check) — the executive
  responds and the property returns to Under Review. This is the design's answer to the spec's
  "asking an executive to proceed to the next stage."
- **Every move requires a reason**, written to the audit log.
- Reject → reopen is allowed, with a reason.
- **Rejecting a property with an open study cancels the study but keeps its captured data** —
  the data stays reusable for anything else that overlaps it later.
- Concurrent stage moves are guarded by optimistic locking (Core rule 3).

## 7. M3 — Catchment Study

### Request
BD Manager requests a study against a property or an already-analysed area. The catchment is a
configurable radius (500–600 m, same value as the M2 site radius) converted to road segments
inside it (see §3 — segments, not H3 cells, are the survey atom).

### Reuse

- **Freshness**: a segment is fresh if captured within a configurable window, starting at
  **90 days**. Freshness is tracked **per segment capture timestamp**, not per study.
- **Coverage**: length-weighted — the % of total catchment segment length that's covered by
  fresh captures.
- **≥80% fresh coverage** → default is reuse + survey only the gap; "reuse only" is also allowed,
  with a lower confidence label on the resulting summary.
- **<80% fresh coverage** → partial reuse + mandatory survey of the rest. "Reuse only" here needs
  an explicit override.
- UI always shows: fresh coverage %, reused segments, uncovered/stale segments, and the age of
  the oldest reused data (example string: *"83% covered by fresh survey data · 17% requires new
  survey."*).
- **Overrides**: BD Manager can waive/force reuse at request time; Survey Manager has final say
  at planning time. **Both require a reason, and both are audited. Stale data is never reused
  silently** — this is a hard rule, not a default that can be silently bypassed.

### Unit generation
- **Contiguous walks over the road graph**, weighted by walking time + a fixed per-segment
  capture-time constant, clipped to the catchment boundary.
- **Every segment belongs to exactly one unit** — enforced by the system on every edit, not just
  at generation time.
- The Survey Manager can split, merge, or reassign segments/units before assigning them to
  executives; the system re-validates the one-segment-one-unit invariant after every edit.
- Final units must be: non-overlapping, balanced by workload, fully contained in the catchment,
  individually trackable, and reusable for future progress tracking.

### Lane capture (one form per segment)
- **Required**: status (surveyed / could not survey + reason), automatic timestamp, GPS, time
  band (auto-stamped — footfall varies by time of day, and mixed-band summaries get flagged).
- **Observed**: timed pedestrian count (fixed observation period), residential buildings/units,
  businesses, grocery/food stores, anchors (schools, hospitals, transit, offices).
- **Accessibility**: road width band, pedestrian access, vehicle access, parking availability.
- **Optional**: photo, notes.
- **Executives capture raw observations only** — no normalization or scoring happens on the
  phone. The backend does all normalization.
- **"Could not survey" = complete-with-gap**, not a blocker. It counts toward "handled," not
  toward "covered," and isn't retried until stale.
- Drafts autosave locally; submission is idempotent by client-generated id (Core rule 6).

### Roll-up (lane data → Catchment Summary)

| Signal | Captured as | Aggregation | Catchment-level value |
|---|---|---|---|
| Residential | buildings/units per segment | sum ÷ surveyed length | density per 100 m |
| Commercial | businesses per segment | sum ÷ surveyed length | density per 100 m |
| Footfall | timed count → hourly rate | length-weighted mean + time-band mix | observed footfall; flagged if from a single time band |
| Accessibility | width band + access ratings | length-weighted ordinal mean + share rated poor | accessibility score |
| Parking | availability rating | length-weighted + share with parking | parking score |
| Competition | grocery/food stores per segment | count ÷ surveyed length | **observed competition — replaces the OSM proxy**, and the gap between them shows how much OSM undercounts |
| Anchors | anchors by type | deduplicated by proximity + name | anchor list by type |

- Computed **over surveyed segments only**; extending to unsurveyed segments is an explicit
  estimate, labeled as such.
- Normalization uses config thresholds shown in the UI (stated in the README as uncalibrated
  assumptions — there's no citywide baseline to calibrate against on this timeline).
- **Catchment Summary** = coverage %, residential, commercial, observed footfall, accessibility,
  competition, anchors, data confidence. Confidence depends on coverage, freshness, share of
  reused data, and time-band diversity. **Below 50% coverage (configurable), show facts only.**

### Property re-evaluation (v1 → v2)
- A completed study triggers a **new evaluation version through a job** — never an overwrite of
  v1.
- Observed catchment signals **replace** the corresponding proxies (demand, competition,
  accessibility); observed footfall joins as a newly-included factor (it had no proxy before).
- **The diff shows**: overall score change, per-factor changes (raw/normalized/contribution),
  newly observed facts, newly discovered risks, and — for every change — a classification:
  `data change` / `config change` / `factor newly included` / `renormalization`. This
  classification is what stops the diff from being a confusing wall of numbers.
- **The LLM only narrates the already-calculated diff.** It never computes any part of it.
- An **area study** (requested against an already-analysed area, not a single property) creates
  a new area report version with an observed overlay, and every property inside it gets
  re-evaluated.
- A failed re-evaluation keeps the old version live, marks it "stale," and offers a retry — never
  silently drops back to nothing.

## 8. Edge cases in scope

**Property input**: pin outside the service area or in water; poor/absent GPS; pin far from
executive; duplicate detection (25 m + name similarity); the same shop entered twice by two
executives; rent zero/negative/wrong unit; photo upload failure (property still saves); property
edited after evaluation (triggers re-evaluation).

**Pipeline**: two managers moving the same property concurrently (optimistic lock); reject →
reopen (allowed, reason required); requesting a study on an already fresh-covered property (a
reuse path, not an error); a rejected property with an open study (cancel the study, keep the
data).

**Analysis**: area selection too small/large (capped); area mostly sea or with no usable data
("insufficient data," no score, never a fabricated one); the same area analysed twice (a new
snapshot, not an overwrite); LLM timeout/invalid JSON (retry → other provider → template); Stores
API down (use cache, stamp its age, exclude cannibalisation if the cache is too stale).

**Survey**: an assigned executive becomes unavailable (reassign, captured data kept); a unit
submitted twice (idempotent no-op); a gated/inaccessible lane ("could not survey" + reason); a
survey unit's property later gets rejected (data stays, stays reusable).

## 9. Failure handling summary

| Failure | Behaviour |
|---|---|
| LLM timeout / invalid JSON | Retry once → switch provider (Gemini↔Groq) → deterministic template. Report flagged "narrative: template". |
| Narrative fails number-validation | Same fallback chain; rejections logged to measure the model over time. |
| Stores API down | Use cache, stamp its age; exclude cannibalisation if the cache is too stale. |
| Geocoding/local-index lookup fails | Local index built at ingest is the only path anyway — no live geocoding dependency to fail. |
| A worker crashes mid-job | Steps persist their outputs; retry resumes from the failed step. A heartbeat re-queues stuck jobs. |
| Property evaluation job fails | Property already saved (Core rule 5); status = "evaluation pending"; retry available; manager sees a partial card built from captured fields alone. |
| Photo upload fails | Photos queued separately; property saves without them, flagged incomplete. |

**What the user always sees**: step-by-step job progress, a named failed step with a retry
button, a "degraded" banner listing every fallback actually used, and a "data as of" stamp on
every panel that shows analysis output.

## 10. Bad-input policy (summary)

- Missing property fields → save + list what's missing; recommendation becomes **Needs Info**,
  never a false precision.
- Evaluation states are exactly: Strong Fit / Consider / Weak Fit / Needs Info.
- Failed re-evaluation → keep the old version, show "stale," offer retry.
- Ambiguous locality → disambiguation list, never a guess.
- Pincode spilling outside the service area → clipped.
- Non-contiguous picked cells → allowed, but flagged.
- Oversized area selection → capped with an explanatory message.
- A "could not survey" lane → needs a reason, counts as complete-with-gap.

## 11. Features by priority

| Priority | Scope |
|---|---|
| **Must (M1–M3)** | Three selection modes; explainable area report + hotspots; saved/comparable reports; scout tasks; mobile property form; deterministic evaluation; pipeline with audit; study request; reuse logic; unit generation + editing; lane capture; roll-up; v1→v2 diff |
| **Bonus (chosen)** | City-wide opportunity map — reuses the M1 scoring engine over the whole service area; surfaces high-score pockets with no existing properties/tasks, marked proxy-only, with a "start analysis" action. BD Manager only. |
| **Stretch** | Deploy with seeded demo data; tests around scoring/reuse/access rules; activity feed |
| **Explicitly not building** | Conversational analyst; PDF decision pack; full offline sync (idempotent API + local drafts is the floor, full offline is a stretch); a real auth system; mock income data (dropped — see `docs/DECISIONS.md`) |

## 12. Known assumptions and risks (say these in the README)

1. Data feasibility (pincode boundary quality, census join, OSM building coverage) is verified
   incrementally at named gates — see `docs/DATA.md`, `docs/PHASES.md`.
2. OSM under-tags small kirana shops — competition is always a **lower bound**, stated in the UI.
3. Survey normalization thresholds are uncalibrated (no citywide baseline exists on this
   timeline) — visible, configurable, and stated as assumptions.
4. Mock rent bands are illustrative, labeled everywhere they appear.
5. Percentile scoring is relative to the chosen service-area boundary — adding the metro fringe
   later means every existing score needs recomputing, not just new ones.
