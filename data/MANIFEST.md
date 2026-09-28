# Data manifest

Citation-ready record of every dataset SiteScout uses. Raw files live in `data/raw/` (git-ignored).
Working notes, coverage numbers, and the reasoning behind each choice: `docs/DATA.md`.

| # | Dataset | Source | Licence | Retrieved | Local file | Verification |
|---|---|---|---|---|---|---|
| 1 | OpenStreetMap — India Southern Zone extract, dated 2026-09-27 | Geofabrik (download.geofabrik.de/asia/india/southern-zone.html) | ODbL 1.0 — © OpenStreetMap contributors | 2026-09-28 | `raw/osm/southern-zone-260927.osm.pbf` (557,764,780 B) | md5 `58841e22d4aa4e17f4420eea1eb8b2f2` matches Geofabrik's published `.md5`. Clipped to 79.95–80.36 E, 12.75–13.35 N at ingest: 390,662 buildings, 138,531 road ways → 301,483 segments, 5,906 land-use polygons, 5,519 POIs/places |
| 2 | Chennai pincode / post-office-area polygons (~2013–14) | datameet/PincodeBoundary (GitHub) | CC-BY-SA 2.5 India | 2026-09-28 | `raw/pincode/chennai_boundary_datameet.geojson` | 68 polygons, 0 invalid; covers 67 of 120 Chennai pincodes (old core only) |
| 3 | Pincode directory ("India Post 2026" repackaged) | `bharatpin` PyPI package, bundled CSV | MIT (package); underlying data India Post | 2026-09-28 | `raw/pincode/pincode_directory_bharatpin.csv` | 165,627 rows; 306 Chennai (600xxx) rows / 123 pincodes; 141 offices fall inside the GCC service area (the rest are kept, flagged out-of-area). Coordinates often only 3 decimals (~110 m) |
| 4 | GCC ward boundaries (200 wards, 2022) and zones | OpenCity — GCC Ward Information (data.opencity.in) | per OpenCity dataset page | 2026-09-28 | `raw/wards/wards_2022.kml`, `raw/wards/zones_2022.kml` | Downloaded; row counts checked at Phase 1 ingest |
| 5 | Chennai ward boundaries (155 wards, 2008) | OpenCity / datameet Municipal_Spatial_Data | ODbL (datameet) / per OpenCity page | 2026-09-28 | `raw/wards/wards_2008.kml`, `raw/wards/wards_datameet.geojson` | Downloaded; needed only for the census join |
| 6 | Census of India 2011 — Chennai ward-wise | OpenCity "Chennai – Census 2011 Data", sourced from censusindia.gov.in | Government Open Data Licence – India | 2026-09-28 | `raw/census/chennai_ward_census_2011.csv` | Downloaded; join untested (gated, see `docs/DATA.md`) |
| 8 | Microsoft Global ML Building Footprints, release 2026-02-03 (India, quadkeys 123312201, 123312203, 123312210, 123312212) | minedbuildings.z5.web.core.windows.net (index: `global-buildings/dataset-links.csv`, copy of the Chennai rows in `raw/buildings_ms/dataset-links_chennai.csv`) | ODbL 1.0 — © Microsoft | 2026-09-28 | `raw/buildings_ms/india_<quadkey>.csv.gz` (69.7 MB total) | 4 files, gzip-valid, 869,486 buildings; 807,931 inside the clip box. Sizes match the index |
| 7 | Savomart store list (all zones; 11 in CHN) | Savomart internal Stores API (`GET`, token auth) | Internal — hackathon use only | 2026-09-28 | `raw/stores/stores_20260928.json` | HTTP 200; 63 BLR + 11 CHN stores (codes and locations not committed) |

**Not used**: data.gov.in all-India pincode boundaries (502 on download), Nominatim (replaced by local
locality index), OSRM (radius catchments instead), TN OGD, Bhuvan (not needed: the OSM mask was validated at the Phase 2
gate), Google Open Buildings v3 (Microsoft footprints passed the gate; 1.12 GB tile not needed).

**Mock data**: none yet. Any mock data added later is listed here and labelled `mock` in provenance.
