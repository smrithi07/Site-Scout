.PHONY: up down logs ps health test psql

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

# migrate / ingest / seed targets arrive in Phases 1–3.
