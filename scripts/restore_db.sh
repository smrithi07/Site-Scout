#!/usr/bin/env bash
# Load the deployment dump into a hosted Postgres (`make deploy-restore`). The connection string is
# read from DEPLOY_DATABASE_URL (Render: the database's *External* Database URL). It is never
# printed. Replaces an empty SiteScout schema (the app migrates on start); refuses real data unless
# DEPLOY_REPLACE=yes.
set -euo pipefail
cd "$(dirname "$0")/.."
DUMP=data/processed/sitescout_deploy.dump
[ -f "$DUMP" ] || { echo "no $DUMP — run make deploy-export first" >&2; exit 1; }
[ -n "${DEPLOY_DATABASE_URL:-}" ] || { echo "set DEPLOY_DATABASE_URL (Render → database → External Database URL)" >&2; exit 1; }
URL=$DEPLOY_DATABASE_URL
case $URL in
  postgres://*|postgresql://*) ;;
  *) echo "DEPLOY_DATABASE_URL must be the full postgres://… URL (Render → database → Connect → External Database URL)" >&2; exit 1 ;;
esac
case $URL in *sslmode=*) ;; *\?*) URL="$URL&sslmode=require" ;; *) URL="$URL?sslmode=require" ;; esac
[ "${DEPLOY_SSLMODE:-}" = "disable" ] && URL=${URL/sslmode=require/sslmode=disable}   # local rehearsal only

PG=(docker run --rm -i ${DEPLOY_DOCKER_NETWORK:+--network "$DEPLOY_DOCKER_NETWORK"} -e URL="$URL" -e PGOPTIONS="-c client_min_messages=warning"
    -v "$PWD/$DUMP:/dump:ro" imresamu/postgis:17-3.5)

# What's there? none = no SiteScout schema; empty = the schema the app creates on its first start
# (migrations + the 4 demo users) but no data; data = snapshots or properties. A failed check stops.
STATE_SQL="SELECT CASE WHEN to_regclass('public.data_snapshots') IS NULL THEN 'none'
  WHEN (SELECT count(*) FROM data_snapshots) + (SELECT count(*) FROM properties) = 0 THEN 'empty' ELSE 'data' END"
if ! state=$("${PG[@]}" sh -c 'psql "$URL" -Atc "$0"' "$STATE_SQL"); then
  echo "could not connect to the target database — check the URL (and that it's the External one)" >&2; exit 1
fi
if [ "$state" = "data" ] && [ "${DEPLOY_REPLACE:-}" != "yes" ]; then
  echo "the target database already has SiteScout data — set DEPLOY_REPLACE=yes to replace it" >&2; exit 1
fi
if [ "$state" != "none" ]; then
  echo "clearing the target's existing schema ($state)"
  "${PG[@]}" sh -c 'psql "$URL" -qc "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"'
fi
echo "restoring $(du -h "$DUMP" | cut -f1) … (a few minutes)"
"${PG[@]}" sh -c 'psql "$URL" -qc "CREATE EXTENSION IF NOT EXISTS postgis; CREATE EXTENSION IF NOT EXISTS pg_trgm;" \
                  && pg_restore --no-owner --no-acl -d "$URL" /dump'
"${PG[@]}" sh -c 'psql "$URL" -Atc "SELECT '"'"'snapshots ready: '"'"' || count(*) FROM data_snapshots WHERE status = '"'"'ready'"'"'"'
echo "done — restart the Render service (Manual Deploy → Restart), then open its URL"
