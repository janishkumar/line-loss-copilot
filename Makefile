export PYTHONPATH := src

LINECOPILOT_DB_PORT ?= 5434
TEST_DB_URL ?= postgresql://linecopilot:linecopilot@localhost:$(LINECOPILOT_DB_PORT)/linecopilot_test

.PHONY: demo-stage2 schemas eval-ollama eval-claude check-questions mcp train-risk translate-notes api setup up down lint test test-db data load dbt validate-oee report web demo-stage1 wait-db

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

# Schemas and grants outside dbt (enrich, ml, demo, actions); idempotent. dbt rebuilds core
# and mart tables and drops their grants, so `dbt` applies this again after the build.
schemas:
	uv run python -m linecopilot.schemas

dbt: schemas
	uv run dbt build --project-dir dbt --profiles-dir dbt
	$(MAKE) schemas

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

# Stage 1, then the stop-risk models, so every page has data (dbt runs inside validate-oee).
demo-stage2: demo-stage1 train-risk
	@echo "Web app: http://localhost:8080  API: http://localhost:8000/api/health"
	@echo "Chat needs Ollama on the host; MCP server: make mcp"

# Machine-translate operator notes with a local Ollama model; appends to the dbt seed.
translate-notes:
	uv run python -m linecopilot.notes.translate --model $(or $(NOTES_MODEL),qwen2.5:7b-instruct)

# Next-hour stop-risk models on PIADE: writes ml.* tables, data/models/ and evals/results/stop_risk.*.
train-risk:
	uv run python -m linecopilot.ml.train

# MCP server over stdio (read-only tools); the database comes from LINECOPILOT_DB_URL.
mcp:
	uv run python -m linecopilot.mcp_server

# Answer, citation and before/after evals (long; not run in CI). Results in evals/results/.
eval-ollama:
	uv run python -m evals.run --runner ollama
	uv run python -m evals.run --runner ollama-notools

# Claude Code headless on plan limits; needs a logged-in claude CLI. Run once per sign-off.
eval-claude:
	uv run python -m evals.run --runner claude
	uv run python -m evals.run --runner claude-notools

# Check every eval question has a well-defined answer on the live database.
check-questions:
	uv run python -m evals.questions --check
