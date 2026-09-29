#!/usr/bin/env bash
# Build a clean deployment database and dump it (`make deploy-export`): schema + demo users, one fresh
# data snapshot, the demo story. Runs in a throwaway compose project with its own volume (no ports),
# so the dev stack is untouched. The building tables are only used by the ingest (their counts live
# in cell_features), so their rows are left out to fit a small hosted database.
#
#   scripts/export_db.sh           # clean: fresh snapshot + demo story (make deploy-export)
#   scripts/export_db.sh --local   # your dev database as it is, all history (make deploy-export-local)
set -euo pipefail
cd "$(dirname "$0")/.."
OUT=data/processed/sitescout_deploy.dump

if [ "${1:-}" = "--local" ]; then
  DC=(docker compose)                                     # the running dev stack
  "${DC[@]}" exec -T api python -m ingest prune          # drop failed snapshots (partial rows)
else
  DC=(docker compose -p sitescout_export -f docker-compose.yml -f docker-compose.export.yml)
  scripts/fetch_data.sh
  trap '"${DC[@]}" down -v >/dev/null 2>&1 || true' EXIT
  "${DC[@]}" up -d --build --wait db
  "${DC[@]}" run --rm --build api alembic upgrade head
  "${DC[@]}" run --rm api python -m ingest build
  "${DC[@]}" run --rm api python -m app.demo.story
fi

mkdir -p "$(dirname "$OUT")"
"${DC[@]}" exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc --no-owner --no-acl \
    --extension=postgis --extension=pg_trgm --exclude-schema=tiger --exclude-schema=tiger_data \
    --exclude-schema=topology --exclude-table-data=osm_buildings --exclude-table-data=ml_buildings' > "$OUT"
echo "wrote $OUT ($(du -h "$OUT" | cut -f1))"
