#!/usr/bin/env bash
# Download every raw dataset the ingest needs into data/raw/, each checked against a pinned sha256
# (the exact files the data snapshot was built and validated on — see data/MANIFEST.md).
# Idempotent: a file already present with the right checksum is skipped. A mismatch is an error,
# never silently accepted. The Savomart store list needs SAVO_STORES_TOKEN (read from .env).
#
#   scripts/fetch_data.sh            # everything (~630 MB on a first run)
set -euo pipefail
cd "$(dirname "$0")/.."
RAW=data/raw

sha256() { if command -v sha256sum >/dev/null; then sha256sum "$1" | cut -d' ' -f1; else shasum -a 256 "$1" | cut -d' ' -f1; fi; }
say() { printf '  %-55s %s\n' "$1" "$2"; }

# path | sha256 | url   (bharatpin: the CSV inside the package wheel)
FILES=$(cat <<'EOF'
osm/southern-zone-260927.osm.pbf|a8880e6ece6ff184ec288d0278eb80293361c13b2725dfdbfe0142da0645f0f4|https://download.geofabrik.de/asia/india/southern-zone-260927.osm.pbf
buildings_ms/india_123312201.csv.gz|eeee8b1dedfb4d3bfdb8dd326e692a42e71c8ea1fc6538cb3942aaafb91b064f|https://minedbuildings.z5.web.core.windows.net/global-buildings/2026-02-03/global-buildings.geojsonl/RegionName=India/quadkey=123312201/part-00170-4feead82-d499-422b-94cb-c036c212127a.c000.csv.gz
buildings_ms/india_123312203.csv.gz|69a8f1f2a621e697c8b8661227d4fbe0ddc900dad8138fba10f8b377fed2b296|https://minedbuildings.z5.web.core.windows.net/global-buildings/2026-02-03/global-buildings.geojsonl/RegionName=India/quadkey=123312203/part-00159-4feead82-d499-422b-94cb-c036c212127a.c000.csv.gz
buildings_ms/india_123312210.csv.gz|5be372773b05ed659590955a49a0b3bb901dd1cc15e1072d496585fd9c6b3c60|https://minedbuildings.z5.web.core.windows.net/global-buildings/2026-02-03/global-buildings.geojsonl/RegionName=India/quadkey=123312210/part-00175-4feead82-d499-422b-94cb-c036c212127a.c000.csv.gz
buildings_ms/india_123312212.csv.gz|949969ad2e5ae614814b5cd8f566cd2e4b9071463af647e5ec3e2c84ab889a75|https://minedbuildings.z5.web.core.windows.net/global-buildings/2026-02-03/global-buildings.geojsonl/RegionName=India/quadkey=123312212/part-00010-4feead82-d499-422b-94cb-c036c212127a.c000.csv.gz
wards/wards_2022.kml|be48ef7eb4320279e790f59da1691ece9efc92b34459ca73c492957943c347e0|https://data.opencity.in/dataset/c77de7f8-e377-4990-90fc-4f0f8ca0e2d2/resource/e90176d4-319a-45bd-918e-ecce4f048c4d/download/6a8a05ed-a41c-492a-aade-ff7517e1a4b1.kml
wards/zones_2022.kml|5939657bf539b4c708758232cf8c77129a67928df3f74699d5b8c3660aef951d|https://data.opencity.in/dataset/c77de7f8-e377-4990-90fc-4f0f8ca0e2d2/resource/00b3ea2e-e3a4-4b28-aec2-769a01404e5b/download/0f0ccbda-9485-4964-b3b1-6ce53af82bbb.kml
pincode/chennai_boundary_datameet.geojson|445fb40d1ad645bd25caeb8d8811c22996d91bcfc2cfcb7a9a6cf0f02d344bd2|https://raw.githubusercontent.com/datameet/PincodeBoundary/master/Chennai/boundary.geojson
pincode/pincode_directory_bharatpin.csv|5d23478002a8b1127a46a90a934bf5c1e9598953714617b3f6639b3371c47b08|WHEEL:https://files.pythonhosted.org/packages/py3/b/bharatpin/bharatpin-1.0.1-py3-none-any.whl:bharatpin/data/pincodes.csv
EOF
)

fetch() {  # fetch <dest> <url-spec>
  local dest=$1 spec=$2 tmp="$1.part"
  mkdir -p "$(dirname "$dest")"
  case $spec in
    WHEEL:*)
      local rest=${spec#WHEEL:} whl="$dest.whl"
      local url=${rest%:*} member=${rest##*:}
      curl -fL --progress-bar --retry 3 --retry-delay 2 -o "$whl" "$url"
      if command -v unzip >/dev/null; then unzip -p "$whl" "$member" > "$tmp"
      else python3 -c "import sys, zipfile; sys.stdout.buffer.write(zipfile.ZipFile(sys.argv[1]).read(sys.argv[2]))" "$whl" "$member" > "$tmp"; fi
      rm -f "$whl" ;;
    *) curl -fL --progress-bar --retry 3 --retry-delay 2 -C - -o "$tmp" "$spec" ;;
  esac
  mv "$tmp" "$dest"
}

echo "Fetching raw data into $RAW/"
failed=0
while IFS='|' read -r path want url; do
  dest="$RAW/$path"
  if [ -f "$dest" ] && [ "$(sha256 "$dest")" = "$want" ]; then say "$path" "ok (already present)"; continue; fi
  if [ -f "$dest" ]; then say "$path" "checksum differs — re-downloading"; rm -f "$dest"; fi
  say "$path" "downloading…"
  if ! fetch "$dest" "$url"; then say "$path" "FAILED to download ($url)"; failed=1; continue; fi
  got=$(sha256 "$dest")
  if [ "$got" != "$want" ]; then
    say "$path" "FAILED checksum (got $got)"; mv "$dest" "$dest.bad"; failed=1
  else say "$path" "ok"; fi
done <<< "$FILES"

# Savomart stores: internal API, token-gated. Keep any list already fetched (the ingest uses the newest).
if ls "$RAW"/stores/stores_*.json >/dev/null 2>&1; then
  say "stores/$(basename "$(ls "$RAW"/stores/stores_*.json | tail -1)")" "ok (already present)"
else
  token=${SAVO_STORES_TOKEN:-$( [ -f .env ] && grep -E '^SAVO_STORES_TOKEN=' .env | cut -d= -f2- || true)}
  if [ -z "$token" ]; then
    say "stores/stores_<date>.json" "MISSING: set SAVO_STORES_TOKEN in .env and re-run"; failed=1
  else
    mkdir -p "$RAW/stores"; out="$RAW/stores/stores_$(date +%Y%m%d).json"
    # GET, not POST: the endpoint answers 405 to the brief's POST example (docs/DATA.md).
    if curl -fsS --retry 3 -H "X-cron-token: $token" -o "$out.part" \
         'https://internal-service.savomart.in/bridge/api/store/list?is_operational=True' \
       && grep -q '"status": *"success"' "$out.part"; then
      mv "$out.part" "$out"; say "stores/$(basename "$out")" "ok"
    else
      rm -f "$out.part"; say "stores/stores_<date>.json" "FAILED (check the token)"; failed=1
    fi
  fi
fi

if [ $failed -ne 0 ]; then echo "Some files are missing or wrong — see above." >&2; exit 1; fi
echo "All raw data present and verified."
