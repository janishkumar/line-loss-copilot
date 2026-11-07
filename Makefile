export PYTHONPATH := src

LINECOPILOT_DB_PORT ?= 5434
TEST_DB_URL ?= postgresql://linecopilot:linecopilot@localhost:$(LINECOPILOT_DB_PORT)/linecopilot_test

.PHONY: api setup up down lint test test-db data load dbt validate-oee report web demo-stage1 wait-db

setup:
	uv sync

api:
	uv run uvicorn linecopilot.api.app:create_app --factory --port 8000

up:
	docker compose up -d --build db api web

wait-db:
	@until docker compose exec -T db pg_isready -U linecopilot -d linecopilot >/dev/null 2>&1; do sleep 2; done

down:
	docker compose down

lint:
	uv run ruff check .
	uv run ruff format --check .

test:
	uv run pytest -m "not db"

test-db:
	LINECOPILOT_TEST_DB_URL=$(TEST_DB_URL) uv run pytest -m db

data:
	uv run python -m linecopilot.ingest.download

load:
	uv run python -m linecopilot.ingest.load

dbt:
	uv run dbt build --project-dir dbt --profiles-dir dbt

validate-oee:
	$(MAKE) dbt
	uv run python -m linecopilot.reports.oee_validation

report:
	uv run python -m linecopilot.reports.readme

web:
	cd web && npm ci && npm run build

# Stack up, download and load the real data, build marts, write the validation report.
demo-stage1: up wait-db data load validate-oee
	@echo "Web app: http://localhost:8080  API: http://localhost:8000/api/health"
