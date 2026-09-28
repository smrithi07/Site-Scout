# Hackathon brief — Savo SiteScout (verbatim, reformatted from the PDF)

*Source: the official problem-statement PDF supplied by SAVOmart / Ebono Private Limited.
Reformatted to Markdown; content unchanged. Kept here so the full evaluation criteria and the
original data-source list are always at hand.*

## Overview

Every new Savomart store starts with a location decision. Today, our Business Development (BD)
executives drive around the city, spot vacant properties using their own judgement, and only
then do we check the rent, the site and the catchment. It works, but it is slow, hard to scale,
and depends on who happens to drive down which street.

We want to flip that around: let the data point BD teams to the right areas before anyone
leaves the office, then carry every property from first sighting to final decision in one
place, with the field survey teams working in the same loop.

Your task is to build the first version of this expansion intelligence platform (working title
Savo SiteScout; feel free to name it) for our Chennai region.

This is a real product with real users, not a toy. It is deliberately open-ended. We describe
what each user needs; the how (scoring, workflows, data model, UX) is yours to design. Aim for
a working end-to-end product that does the core loop well, and add extras only once that loop
works.

## Time + AI policy

- **Time**: 48 hours, Monday 28 September 2026 9:00 AM IST → Wednesday 30 September 2026
  9:00 AM IST. Git commit history is the source of truth for timing.
- **AI tools** (Claude, ChatGPT, Cursor, Copilot, Claude Code, etc.): fully allowed and
  encouraged. Disclose in the README which AI tools were used and how, and share AI chat
  sessions/history (see Deliverables).
- **Open source / libraries**: use freely. Cite the substantial ones in the README. For data,
  see Data Sources below.

## Tech stack (as specified)

- Backend: Python, FastAPI or Django. *(We chose FastAPI.)*
- Frontend: React.
- Database: your choice, heavily location-based — choose with that in mind. *(We chose
  PostgreSQL + PostGIS.)*
- Map library: your choice (Leaflet / MapLibre + OSM are fine free options; Mapbox / Google
  Maps also fine with your own key). *(We chose MapLibre GL.)*
- LLM: bring your own, any provider, keep it swappable via config, never commit API keys.
  *(We chose Gemini default, Groq fallback, deterministic template as final fallback.)*
- UI library: your choice. *(We chose Tailwind.)*

Not graded on which library — graded on how it was used.

## The problem

Build a web application that takes Savomart's expansion process from "which area?" through
"which property?" to "is the catchment right?", shared by four kinds of users:

| Persona | What they need from the product |
|---|---|
| BD Manager | Explore areas of Chennai without visiting them, see which are worth scouting, direct executives, review properties and decide what moves forward, and request catchment studies. |
| BD Executive | Know where to scout, then onboard properties they find in the field quickly from a phone. |
| Survey Manager | Receive catchment study requests, plan and split the work, assign it to the team and track progress. |
| Survey Executive | See their assigned work and capture lane-level ground data, mostly on a phone, on the street. |

**Color palette (mandatory):** `#782B90` (purple) and `#FFF200` (yellow) as primary visual
identity. How to apply them is our call.

**Focus region (mandatory):** Chennai (Greater Chennai / Chennai Metropolitan Area). Everything
built and demoed should work on real Chennai geography.

## Must-have: milestones

Build in this order. Each milestone should be demoable on its own; a complete M1–M3 loop beats
a polished M1 with nothing after it. The prompts under each milestone are questions to answer in
our own design — not hidden requirements, no single right answer.

**Users and roles:** keep it simple. Seeded demo users for the four personas, or a simple role
switcher, is enough (document how to use it). Spend time on M1–M3, not on an auth system. Each
persona should still see a view shaped around their job.

### M1 — Area Intelligence: virtual analysis

- A BD Manager selects any area of Chennai on an interactive map (mandatory) by pincode, by
  locality name, or by picking grid cells on the map.
- They trigger a virtual analysis that produces an Area Fitness Report: what the area is like
  (its people, homes, businesses, amenities, competition, and how close existing Savomart
  stores are).
- The report rates how well the area fits Savomart, explains why, and suggests where within the
  area executives should scout first.
- Reports are saved, can be revisited and compared, and are clearly timestamped with the data
  they used.

**Things to think about:** What makes an area a good fit for a neighbourhood grocery store?
Which signals can actually be got from public data? Why should a BD Manager trust the rating?
Can they see how it was reached? Where does AI add value here, and how do you stop it from
inventing numbers? Analysis may take a while — what does the user see while it runs, or if it
fails halfway?

### M2 — Property Scouting and Evaluation

- A BD Manager can direct executives to scout the areas or hotspots from M1.
- A BD Executive onboards a property from the field: its location, the commercial and physical
  details deemed to matter, and photos. Must work well on a phone.
- Each new property is automatically evaluated by combining public data around it with what the
  executive captured, and the evaluation returns insights, risks and a recommendation.
- The BD Manager moves properties through a pipeline of stages designed by us (for example,
  asking an executive to proceed to the next stage, or rejecting a property), with a clear
  history of who did what and why.

**Things to think about:** What does the BD Manager need to see to decide in 30 seconds? How do
you handle bad field input, like a wrong pin, missing rent or duplicate properties? Should a
property's evaluation change when new data arrives later (e.g. a catchment study)?

### M3 — Catchment Study: survey operations

- A BD Manager can request a catchment study against a property or against an area that has been
  virtually analysed.
- The Survey Manager sees incoming requests, breaks each one into smaller units of work, and
  assigns them to executives.
- A Survey Executive sees their assignments and captures data lane by lane. Content of capture
  is our call.
- Managers can see progress, and completed data rolls up into catchment insights linked back to
  the property or area.
- **Reuse**: if a property is scouted inside an area that already has a catchment study, that
  data should be reused rather than surveyed again.

**Things to think about:** How do you split a catchment into fair, non-overlapping chunks of
work? When is an existing study "close enough" and "fresh enough" to reuse? Where do you draw
the line? Lanes often have weak mobile network — what happens to a half-filled survey?

## Stores API (live)

Fetch Savomart's operational stores (proximity, coverage, cannibalisation) from the internal
service. **Note**: the curl example given in the spec uses `--data ''`, which forces curl into
POST — but the live endpoint only accepts **GET**. See `docs/DECISIONS.md` for the corrected
call and `docs/DATA.md` for what it returned. The real token belongs only in the git-ignored
`.env` (`SAVO_STORES_TOKEN`), never in code or docs.

## Data sources: OpenStreetMap + Indian Government Open Data (as given)

Starting points, not a checklist — which datasets are picked and how they're combined, cleaned
and interpreted is part of the challenge. Cite everything used in the README. Where no public
data exists (e.g. rents), sensible mock data is fine, clearly labeled in UI and README.

| Source | What it can give | Link |
|---|---|---|
| OpenStreetMap (Geofabrik extract) | Roads/lanes, shops, supermarkets, schools, hospitals, offices, transit. Southern Zone covers Tamil Nadu. | download.geofabrik.de |
| Overpass API / Overpass Turbo | Query OSM features for a specific area on demand. | overpass-turbo.eu |
| Nominatim | Geocoding/reverse geocoding on OSM data (respect usage policy). | nominatim.org |
| Pincode boundaries (OGD India) | All-India pincode boundary GeoJSON. | data.gov.in |
| Pincode directory (OGD India) | Post offices by pincode, with lat/long. | data.gov.in |
| OSRM (OSM routing) | Road-network routing and travel times on OSM data. | project-osrm.org |
| Census of India | Ward/town-level population, households, household amenities. | censusindia.gov.in |
| Tamil Nadu OGD portal | State-level open datasets from TN government departments. | tn.data.gov.in |
| Bhuvan (ISRO/NRSC) | Indian geoportal, thematic layers such as land use/land cover. | bhuvan.nrsc.gov.in |

See `docs/DATA.md` for which of these we actually used, what we substituted, and why.

## Bonus: nice-to-have (only once M1–M3 work end to end)

Pick what excites you; one well-shipped bonus beats three half-built ones.

- Conversational analyst — AI assistant across areas/properties/surveys, grounded in our data.
- **City-wide opportunity map** — proactively surface high-potential, un-scouted pockets across
  Chennai without picking an area first. **← This is the one we chose.**
- Offline-first field capture — survey/scouting flows that work without network, sync later.
- Shareable decision pack — one-click export (PDF or similar) of a property's full case.
- Notifications/activity feed.
- Deploy somewhere accessible with seeded demo data, share the URL. *(Stretch goal for us.)*
- Meaningful automated tests/CI around the parts that matter most. *(Stretch goal for us.)*

## How we'll evaluate (as given)

- Product thinking: did you understand the users and design flows around their real jobs?
- Frontend and UX: map interactions, role-specific experiences, mobile field flows, loading and
  error states.
- Backend and API design: structure, workflows and state, background processing, access control,
  error handling.
- Data and database: data model, spatial querying, how you ingested and cleaned public data.
- AI integration: useful, grounded, explainable, and not a wrapper that makes up numbers.
- Engineering hygiene: code quality, README, commit history, honest trade-offs.

## Original follow-up design brief (verbatim, given after the base problem statement)

*This second document narrowed seven specific design gaps left open by the base brief. All
seven are resolved in `docs/DESIGN.md`; this is kept as the original ask.*

> Close the remaining product-design gaps for Savo SiteScout. Design the missing parts of the
> M1–M3 workflow without changing the already-locked architecture, personas, failure-handling
> principles, or access-control decisions. Goal: one coherent end-to-end flow — Area Intelligence
> → Property Scouting → Property Evaluation → Catchment Study → Lane Survey → Catchment Roll-up
> → Property Re-evaluation.
>
> 1. **Catchment roll-up** — define exactly how lane-level survey data becomes catchment-level
>    insights and feeds back into the property's evaluation, across: residential
>    activity/density, commercial/business activity, observed pedestrian activity/footfall, road
>    and pedestrian accessibility, parking/access conditions, direct grocery/retail competition,
>    important anchors (schools, hospitals, transit, offices). For each: define what's captured,
>    how observations aggregate, weight by surveyed lane length where appropriate, calculate a
>    catchment-level value, retain provenance and coverage, distinguish observed from
>    estimate/proxy. Produce a Catchment Summary (coverage %, residential, commercial, observed
>    footfall, accessibility, competition, anchors, data confidence). A completed study creates
>    a new property evaluation version, with a v1→v2 diff (score change, factor changes, new
>    facts, new risks, reason for change). The LLM only explains calculated facts — never
>    calculates or invents the evaluation.
> 2. **Property fields and evaluation** — a minimal but useful mobile-first form (location,
>    commercial, physical, executive assessment fields listed). A deterministic evaluation using
>    area opportunity, demand, rent affordability, accessibility, visibility/frontage,
>    competition, data completeness, with configurable weights. Outcomes: Strong Fit / Consider /
>    Weak Fit / Needs Info (Needs Info when critical info is missing, rather than a misleading
>    recommendation). Explainable as raw → normalized → weight → contribution.
> 3. **Survey lane capture** — a minimal phone-friendly form per survey unit/lane: required
>    (status surveyed/could-not-survey + reason, timestamp, GPS), observed (pedestrian count over
>    a fixed period, residential buildings/units, businesses, grocery/food stores, anchors),
>    accessibility (road width band, pedestrian/vehicle access, parking), optional (photo, notes).
>    Executives capture raw observations only; backend calculates normalized metrics. A
>    "could not survey" unit is complete-with-gap, not blocking.
> 4. **Locality-name selection** — support pincode, locality name, and H3 cells, all converging
>    to the same internal representation: selection → geometry → H3 cells → M1 analysis. A local
>    searchable locality index; ambiguous/unavailable locality data must never be guessed — offer
>    pincode or grid-cell selection instead.
> 5. **Catchment study reuse** — freshness (fresh if <90 days, configurable) and spatial coverage
>    (≥80% fresh → allow reuse; below → partial reuse + survey the rest). UI shows fresh coverage
>    %, reused cells, uncovered/stale cells, age of oldest reused data (example: "83% covered by
>    fresh survey data · 17% requires new survey"). Manager can override with a required reason.
>    Never silently reuse stale data.
> 6. **Mock rent and income data** — clearly labelled illustrative bands, not false-precision
>    values (e.g. "illustrative rent: ₹60–₹90/sqft/month"). Never presented as observed. Drop a
>    mock signal if it doesn't actually help the evaluation.
> 7. **Roads/lanes crossing H3 boundaries** — H3 cells are not the final survey unit. Catchment
>    H3 cells → road/lane geometries inside the catchment → each road segment assigned to exactly
>    one survey unit → units balanced by lane length/workload. No segment duplicated across
>    units. Survey Manager gets auto-generated balanced units, can edit/split/merge before
>    assigning. Final units: non-overlapping, balanced, fully contained in the catchment,
>    individually trackable, reusable for progress tracking.
>
> **Final consistency requirements** given alongside: provenance on every value; missing data
> never zero; unavailable factors excluded + renormalized; too-much-missing → facts only, no
> rating; save-before-evaluate; failed evaluation never deletes captured data; survey drafts
> preserved; idempotent submissions; analysis uses ingested/cached data, never live external
> calls; failed jobs resume from the failed step; LLM output validated against the fact sheet;
> invalid/failed LLM output falls back to another provider then a deterministic template; every
> analysis/evaluation/study is versioned, never overwritten; all decisions/state changes are
> auditable.
