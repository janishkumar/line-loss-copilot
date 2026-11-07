export PYTHONPATH := src

LINECOPILOT_DB_PORT ?= 5434
TEST_DB_URL ?= postgresql://linecopilot:linecopilot@localhost:$(LINECOPILOT_DB_PORT)/linecopilot_test

.PHONY: plan eval-plan eval-shortages synth demo-stage3 demo-stage4 demo-note-remove eval-safety eval-safety-ollama eval-safety-claude demo-stage2 schemas eval-ollama eval-claude check-questions mcp train-risk translate-notes api setup up down lint test test-db data load dbt validate-oee report web demo-stage1 wait-db

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

# Seeded synthetic orders, BOMs and stock on real capacity (stage 4); needs the marts built.
synth: schemas
	uv run python -m linecopilot.synth

# Shortage detector and naive rule against the planted truth, on the main database.
eval-shortages:
	uv run python -m evals.shortages

# Plan the live synthetic generation (CP-SAT, FIFO, EDD), replay it against real PIADE stops and
# store it in plan.*; needs `make synth`.
plan: schemas
	uv run python -m linecopilot.plan

# CP-SAT against FIFO and EDD over seeds 7 to 11, nominal and replayed; writes evals/results/plan.*
eval-plan:
	uv run python -m evals.plan

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

# Stage 2, then one clearly labelled synthetic injected note on a real repeat-failure stop.
demo-stage3: demo-stage2
	uv run python scripts/demo_injected_note.py
	@echo "Open http://localhost:8080 , pick a demo user (top right), then Approvals."
	@echo "Claude with propose tools: set LINECOPILOT_MCP_USER=sup.a in the MCP server env, for example"
	@echo "  claude mcp add linecopilot --env PYTHONPATH=src --env LINECOPILOT_MCP_USER=sup.a -- uv run --directory /path/to/line-loss-copilot python -m linecopilot.mcp_server"
	@echo "Run Claude with its built-in tools off (claude --tools \"\"): the demo user switcher is not a login."
	@echo "Then ask: draft a work order for the repeat stops on the machine named in the line above."
	@echo "Remove the demo note with: make demo-note-remove"

# Stage 3, then the seeded synthetic orders and the stored plan (needs the stage 1 data loaded).
demo-stage4: demo-stage3 synth plan
	@echo "Open http://localhost:8080 : Plan, Shortages, then an order from either page."
	@echo "Ask Claude: Which orders will the board shortage hit?"

demo-note-remove:
	uv run python scripts/demo_injected_note.py --remove

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

# Scripted safety eval, with guardrails and against the naive baseline, on the TEST database
# (needs its fixtures: run `make test-db` once first). Writes evals/results/safety_*.
eval-safety:
	LINECOPILOT_TEST_DB_URL=$(TEST_DB_URL) uv run python -m evals.safety.run --mode both

# LLM injection subset on the main database (real events): the local model through the web
# chat loop, or Claude Code headless through the MCP server (needs a logged-in claude CLI).
eval-safety-ollama:
	uv run python -m evals.safety.llm --runner ollama

eval-safety-claude:
	uv run python -m evals.safety.llm --runner claude
