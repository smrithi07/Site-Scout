# Data sources, decisions, and status

This is the working record of what data we use, why, and what state it's in. Feeds
`data/MANIFEST.md` (not yet written) and the README's citation section directly.

**Never put real tokens/keys in this file or any committed file.** The Stores API token goes
only in the git-ignored `.env` as `SAVO_STORES_TOKEN`.

## What we use from the hackathon's suggested sources

| Source (as given in the brief) | Decision | Used for |
|---|---|---|
| OSM (Geofabrik extract) | **Use.** Pinned Southern Zone extract, dated 2026-09-27. | POIs, roads/segments, buildings, transit, anchors, competition |
| Overpass API / Turbo | **Fallback only.** Small patch queries if the pinned extract is missing something specific. Not the primary ingest path — a downloaded, dated file is reproducible and has no rate limits, which fits "ingest offline, never call live APIs at analysis time." | — |
| Nominatim | **Not used.** The local locality index (built at ingest) replaces live geocoding entirely. | — |
| Pincode boundaries (data.gov.in) | **Attempted, failed (502 timeout).** Dropped. Using `datameet` Chennai boundary + Voronoi fallback instead. | Pincode selection geometry |
| Pincode directory (data.gov.in) | **Substituted.** The linked data.gov.in resource wasn't reliably scriptable; using the `bharatpin` PyPI package's bundled CSV instead (see below). | Locality index, directory cross-check |
| OSRM | **Skipped for now**, fallback = a radius buffer labeled "approximate (radius)" if implemented. Hosting OSRM is a time sink not worth it on this timeline; revisit only if catchment isochrones become a differentiator worth the hours. | Catchment shape (if implemented beyond radius) |
| Census of India | **Downloaded, join untested.** Only covers the 155 pre-2011 wards, current map has 200 — needs the 2008 ward map to join at all, and even then only covers the older "core" city. Gated: only used if Phase 2's join check passes; OSM building density is the always-available demand proxy either way. | Demand enrichment, core city only |
| TN OGD portal | **Skipped.** Low expected value for the time available. | — |
| Bhuvan (ISRO/NRSC) | **Deferred to a Phase 2 gate**, not skipped outright (see below). | Land-use mask cross-check, only if OSM coverage proves insufficient |

## Bhuvan decision (this was re-litigated once — keep the reasoning)

Initial instinct was to skip Bhuvan outright; on challenge, the honest answer is "defer, decide
on measured OSM coverage," not "skip."

- Bhuvan's LULC layers are from 2005-06 / 2011-12 / 2015-16 satellite imagery — 10-20 years
  stale for a fast-changing city like Chennai.
- Access is via WMS/WMTS (viewable, exportable through QGIS), not a clean downloadable file — a
  1:50K raster export requires manual class-decoding from the legend, and there are old (2016)
  forum reports of needing an MoU for analysis-ready rasters. Unconfirmed whether that's still
  true.
- OSM already carries landuse/water/aeroway/building tags that cover the same need (masking
  sea/airport/industrial cells as non-scoreable).

**Decision: gate at Phase 2.** After the OSM ingest, measure OSM land-use coverage against known
ground truth (does the non-scoreable mask correctly catch the airport, Marina Beach, and the
Ennore/Manali industrial belt?). If it does, skip Bhuvan and say so in the README with the
measured numbers. If there are real gaps, export the relevant Bhuvan layer for the Chennai bbox
via QGIS as an offline step, use it **only** for the mask/land-use cross-check (never as a
scoring weight), tagged provenance = "proxy, 2015-16 imagery-based, 30 m".

## Datasets actually downloaded (status)

| Dataset | Source | File(s) | Status |
|---|---|---|---|
| OSM Southern Zone extract | Geofabrik, dated 2026-09-27 | `data/raw/osm/southern-zone-260927.osm.pbf` (~558 MB) | **Verified.** md5 matches (`58841e22d4aa4e17f4420eea1eb8b2f2`). |
| Chennai pincode/post-office-area polygons | `datameet/PincodeBoundary` GitHub repo, Chennai folder (CC-BY-SA 2.5 India) | `data/raw/pincode/chennai_boundary_datameet.geojson` | **Downloaded, checked.** 68 polygons, valid GeoJSON, 0 invalid geometries, each with a `pin` field. **~12 years old** (Esri metadata shows created ~Nov 2013, last edited ~Mar 2014). Bounds only cover the old pre-2011 city core (80.161–80.300 E, 12.914–13.147 N) — **misses the expanded GCC zones entirely.** |
| Pincode directory | `bharatpin` PyPI package (third-party repackaging of "India Post 2026" data, MIT licence) | `data/raw/pincode/pincode_directory_bharatpin.csv` | **Downloaded, checked.** 165,627 rows total; 302 Chennai (600xxx) rows, 120 unique pincodes, all 302 have coordinates, 271 fall inside the Chennai bounding box (31 flagged as bad/out-of-area coordinates, to be dropped at ingest). |
| Ward/zone boundaries | OpenCity `data.opencity.in` (GCC Ward Information dataset) + `datameet/Municipal_Spatial_Data` | `data/raw/wards/wards_2022.kml`, `zones_2022.kml`, `wards_datameet.geojson`, `wards_2008.kml` | Downloaded (commands given, not independently reconfirmed in this doc). |
| Census 2011 ward-wise data | OpenCity (`Chennai - Census 2011 Data`), sourced from censusindia.gov.in | `data/raw/census/chennai_ward_census_2011.csv` | Downloaded. **Only covers 155 pre-2011 wards** — needs the 2008 ward map to join; current wards map has 200. Join untested. |
| Official all-India pincode boundary GeoJSON | data.gov.in | — | **Failed — 502 timeout on manual browser download.** Dropped. Not blocking; datameet + Voronoi covers the same need at lower quality. |
| Savomart stores | Internal Stores API | `data/raw/stores/stores_<date>.json` | **Verified, working.** See below. |

## Pincode geometry: the actual coverage numbers, and the fix

Cross-check script (`scripts/check_pincode.py`, already written and run) compared the 68
datameet polygons against the 120 unique Chennai pincodes in the `bharatpin` directory:

- **44% of Chennai pincodes (53 of 120) have no polygon at all** in the datameet file — this
  blows past the 15% threshold that would've let us just accept the file as-is.
- Of post-office points that do fall inside *some* polygon (105 of 271), 78% (82 of 105) land in
  the polygon with the *matching* pincode — the rest is likely 2013-boundary drift, not a data
  error worth chasing further.
- 1 polygon pincode (`600029`) isn't in the directory at all — probably a defunct/merged pincode;
  ignore.

**Decision**: use the datameet polygons for the ~68 pincodes they cover, tagged
`source: datameet_2013` (label in UI: "approximate, 2013–14 boundaries"). For the remaining ~53
pincodes, build Voronoi cell extents from the directory's post-office points, clipped to the
2022 GCC ward outline, tagged `source: voronoi_approx`. Every pincode geometry in the DB records
which of the two it is, and the UI shows that label. This is built into Phase 1 regardless of
whether the official data.gov.in file is ever obtained — it's not a stopgap, it's the design.

## Stores API: corrected usage

**The problem statement's curl example is misleading.** It uses `--data ''`, which forces curl
into `POST` — but the live endpoint only accepts `GET`. Confirmed by testing:
- `POST` → `HTTP 405`, body `{"detail":"Method Not Allowed"}`, response header `allow: GET`.
- `GET` with the same header → `HTTP 200`, JSON body.

**Corrected shape** (token from `.env`, never typed into a shared PDF-derived command literally):
```bash
curl -sS -X GET \
  'https://internal-service.savomart.in/bridge/api/store/list?is_operational=True' \
  -H "X-cron-token: $SAVO_STORES_TOKEN"
```

**Response shape**: `{"status":"success","data":[{...}]}`, each store object has
`store_code`, `name`, `address`, `location_url`, `geocoordinates.{latitude,longitude}`,
`is_operational`, `zone`.

**What it returned**: 63 stores in zone `BLR` (Bengaluru), 11 in zone `CHN` (Chennai). The 11
Chennai stores, with coordinates:

| store_code | name | lat | lon |
|---|---|---|---|
| *(11th store — paste of the list was cut off; re-run the ingest script and it'll be captured, no action needed)* | | | |

**Design consequence — important**: three of these stores sit **west of the datameet polygon boundary at
80.161 E** — i.e. plausibly outside the old-core service-area polygon, in the metro-fringe zone.
This means:
1. **Cannibalisation logic must query all stores near a site by geometry (radius), never
   filtered by "inside the service-area polygon."** A store just outside the boundary can still
   cannibalise a site near the edge. This was already the design in `docs/DESIGN.md` §6, and
   this data confirms it's not a theoretical edge case.
2. Savomart already operates in what would be the metro-fringe zone, which raises the practical
   stakes of the metro-fringe decision (see below).

**Ingest design**: keep every row from the API (all zones, not just Chennai) in a `stores` table
untouched, as the audit record. Filtering to "stores relevant to this analysis" happens by
geometry at query time, never by pre-filtering on `zone` at ingest.

## Metro fringe decision (still open, gated)

Locked earlier: **GCC core only, unless Phase 0/2 data quality supports adding the metro fringe
(Tambaram, Avadi, etc.) — if quality is poor, GCC alone is enough.**

Current lean, given the datameet-polygon gap and the fringe stores found above: the fringe is
looking more relevant than originally assumed. Revisit this explicitly once the Phase 2 OSM
building/landuse coverage check runs — don't decide it from the pincode-polygon gap alone.

## Mock data

- **Rent bands**: yes, ship them. Illustrative per-GCC-zone bands in `config/sitescout.yaml`,
  labeled "illustrative" everywhere they surface (UI + README).
- **Household income bands**: **dropped.** They fed nothing in the evaluation once designed in
  detail — see `docs/DECISIONS.md` for the reasoning. Don't add them back without a concrete use.

## Open items before Phase 1 can fully close

1. Verify the 11th Chennai store's `store_code` from the raw JSON (cosmetic — no design impact).
2. Decide, once Phase 2's OSM coverage numbers exist: metro fringe in or out.
3. Decide, once Phase 2's OSM coverage numbers exist: Bhuvan land-use cross-check needed or not.
4. Confirm whether the census 2011 join (2008 155-ward map) is worth the ~2-3 hours of cleanup —
   default lean is "only if trivial," since OSM building density is the always-available demand
   proxy regardless.
