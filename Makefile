export PYTHONPATH := src

LINECOPILOT_DB_PORT ?= 5434
TEST_DB_URL ?= postgresql://linecopilot:linecopilot@localhost:$(LINECOPILOT_DB_PORT)/linecopilot_test

.PHONY: setup up down lint test test-db data load dbt validate-oee report web

setup:
	uv sync

up:
	docker compose up -d db

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
	@echo "not implemented yet (brick OEE validation)"

report:
	@echo "not implemented yet (results report)"

web:
	@echo "not implemented yet (web app)"
