.PHONY: up down logs ps health test psql migrate ingest gate

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
