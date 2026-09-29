#!/usr/bin/env bash
# One command from a fresh clone to a running app with data (`make setup`). Safe to re-run:
# every step is idempotent (existing .env kept, verified files skipped, migrations up to date,
# ingest skipped when a ready snapshot exists).
set -euo pipefail
cd "$(dirname "$0")/.."

step() { printf '\n==> %s\n' "$1"; }

step "1/5 .env"
if [ -f .env ]; then
  echo "keeping the existing .env"
else
  cp .env.example .env
  secret=$(openssl rand -hex 24 2>/dev/null || python3 -c "import secrets; print(secrets.token_hex(24))")
  sed -i.bak "s/^APP_SECRET=.*/APP_SECRET=$secret/" .env && rm -f .env.bak
  echo "created .env from .env.example with a random APP_SECRET."
  echo "Add SAVO_STORES_TOKEN (needed once to download the store list) and, optionally, LLM keys."
fi

step "2/5 raw data (checksum-verified)"
scripts/fetch_data.sh

step "3/5 database + schema"
docker compose up -d --build --wait db
# Migrate in a one-off container: the api refuses to start until the schema (config registry) exists.
docker compose run --rm --build api alembic upgrade head

step "4/5 api, worker, web"
docker compose up -d --build -V
printf 'waiting for the api'
for _ in $(seq 1 60); do
  if curl -fs localhost:8000/health >/dev/null 2>&1; then echo " — up"; break; fi
  printf '.'; sleep 2
done
curl -fs localhost:8000/health >/dev/null || { echo; echo "api did not become healthy: docker compose logs api" >&2; exit 1; }

step "5/5 data snapshot"
docker compose exec -T api python -m ingest build --if-empty

cat <<'EOF'

SiteScout is running.
  Web  http://localhost:5173   (pick one of the four demo users)
  API  http://localhost:8000/docs
EOF
