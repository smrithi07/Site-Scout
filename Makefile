.PHONY: up down logs ps health test psql migrate ingest gate reload-env llm-smoke

up:
	docker compose up -d --build

down:
	docker compose down

logs:
	docker compose logs -f

ps:
	docker compose ps

health:
	curl -s localhost:8000/health; echo

test:
	docker compose exec api pytest -q

psql:
	docker compose exec db sh -c 'psql -U $$POSTGRES_USER -d $$POSTGRES_DB'

migrate:
	docker compose exec api alembic upgrade head

# Offline ingest: builds a new data snapshot from data/raw (never runs at request time).
ingest:
	docker compose exec api python -m ingest build

# Phase 2 data-quality gate report (read-only) on the active snapshot.
gate:
	docker compose exec api python -m ingest gate

# Containers read .env only when created; `restart` keeps the old values. Run after editing .env.
reload-env:
	docker compose up -d --force-recreate api worker

# One live LLM call against a saved report (repeat runs are served from the cache for free).
# Usage: make llm-smoke REPORT=3 PROVIDER=gemini
llm-smoke:
	docker compose exec api python -m app.llm.smoke --report $(REPORT) --provider $(PROVIDER)
