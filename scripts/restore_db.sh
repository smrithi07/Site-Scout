#!/usr/bin/env bash
# Load the deployment dump into a hosted Postgres (`make deploy-restore`). The connection string is
# read from DEPLOY_DATABASE_URL (Render: the database's *External* Database URL). It is never
# printed. Refuses a database that already has SiteScout data.
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

PG=(docker run --rm -i ${DEPLOY_DOCKER_NETWORK:+--network "$DEPLOY_DOCKER_NETWORK"} -e URL="$URL"
    -v "$PWD/$DUMP:/dump:ro" imresamu/postgis:17-3.5)

# Can we connect, and is the database empty? A failed check stops here (it used to fall through).
if ! existing=$("${PG[@]}" sh -c 'psql "$URL" -Atc "SELECT to_regclass('"'"'public.data_snapshots'"'"') IS NOT NULL"'); then
  echo "could not connect to the target database — check the URL (and that it's the External one)" >&2; exit 1
fi
if [ "$existing" = "t" ]; then
  echo "the target database already has SiteScout tables — refusing to overwrite it" >&2; exit 1
fi
echo "restoring $(du -h "$DUMP" | cut -f1) … (a few minutes)"
"${PG[@]}" sh -c 'psql "$URL" -qc "CREATE EXTENSION IF NOT EXISTS postgis; CREATE EXTENSION IF NOT EXISTS pg_trgm;" \
                  && pg_restore --no-owner --no-acl -d "$URL" /dump'
"${PG[@]}" sh -c 'psql "$URL" -Atc "SELECT '"'"'snapshots ready: '"'"' || count(*) FROM data_snapshots WHERE status = '"'"'ready'"'"'"'
echo "done — open the Render service URL (the first request after idle takes ~1 min on the free plan)"
