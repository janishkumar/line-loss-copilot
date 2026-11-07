# line-loss-copilot: design

Author: Janish Kumar
Status: draft for approval, covers stages 1 to 3 in detail and stages 4 and 5 in outline.

## 1. Intent

Mid-sized plants lose capacity to stops, changeovers, slow running, shortages and defects. The evidence sits in machine logs, spreadsheets and operator notes that nobody can search, so planning reports take hours and the same failures come back.

line-loss-copilot turns raw machine logs, stop logs and operator notes into one trusted data layer, answers plain-English questions with every number traced to source rows, and drafts actions (work orders, quality holds, follow-ups) that only happen after a person approves them.

**Decision it supports:** where a line is losing time and what to do about it first, and whether an AI assistant can be trusted to help with that at all. The evals are the evidence for the second part.

**The rule that runs through everything:** the AI proposes and a person approves. Nothing changes on its own.

**Users:** operator, shift supervisor, planner, quality lead, plant manager.

## 2. Goals, non-goals, anti-goals

**Goals (stages 1 to 3)**
- Load both real datasets (PIADE, heavy clay brick line) into Postgres with data contracts, one standard event schema and row-level lineage.
- Compute availability, performance, quality and OEE from events, per machine, line and shift, and report the gap against the brick line's published per-shift OEE.
- One shared, typed tool layer used by three front ends: the web app's dashboards, a web chat backed by a local Ollama model, and Claude through MCP.
- Answers cite source rows. When the evidence is not there, the answer says so.
- Loss Pareto, MTTR, MTBF, repeat failures, root-cause breakdowns, a next-hour stop prediction on PIADE, and searchable operator notes with the original text kept beside any translation.
- Actions go preview, one-time code, pending proposal, human approval in the app, re-check on fresh data, write, audit record.
- Each stage ends working, tested, demoable, with a measured number in the README produced by code in the repo.

**Non-goals (for now)**
- Real authentication. This runs locally; demo users are picked from a switcher.
- Any connection to a real MES, ERP or CMMS. Actions write to this project's own tables.
- Live streaming ingestion. Loads are batch and re-runnable.
- Stages 4 (scheduling, shortages) and 5 (visual inspection) until 1 to 3 are done and shown.

**Anti-goals (failure even if it technically works)**
- A number in an answer or the README that cannot be traced to rows or code.
- The agent approving, or being able to approve, its own proposal. Any path from free text (notes, order text) to a change in what a tool does.
- Real and synthetic metrics mixed in one headline number.
- A good-looking result that comes from leakage. If a score looks too good, it gets investigated before it gets published.
- Paid APIs, cloud accounts, or anything pushed or published before Janish says so.

## 3. Constraints

- $0 budget. Claude is used only through MCP on normal plan limits. The web chat uses a free local model through Ollama.
- Stack: Python, FastAPI, Postgres, dbt, uv, ruff, pytest. TypeScript and React for the app. MCP Python SDK 2.x (`from mcp.server.mcpserver import MCPServer`, snake_case `ToolAnnotations`). scikit-learn for prediction. Docker Compose, `make up` runs everything.
- Raw data stays out of git. Downloads go to a gitignored `data/` folder with a checksum manifest.
- All three datasets are CC BY 4.0 and are credited in the README.
- Tests run offline on small fixtures.
- No AI attribution, no company, client or vendor branding, no named prospective employer anywhere in the repo.
- On this Mac, run Python with `PYTHONPATH=src` (exported in the Makefile) because uv's editable `.pth` files can be hidden.

## 4. Architecture

```
data/ (gitignored)          raw CSVs + checksums.json
   │  loader (Python): contract checks, lineage columns
   ▼
Postgres
  raw.*        files as loaded, one row per source row, + load_id, source_file, source_row
  core.*       dbt: one standard event table, machines, lines, shifts, notes, translations
  mart.*       dbt: OEE by machine/line/shift, losses, reliability
  ml.*         prediction features, scores, model registry rows
  actions.*    proposals, codes, work orders, quality holds, follow-ups, audit log
  demo.*       demo users and roles (synthetic, labelled)
   │
   ▼
Shared tool layer (Python package, typed in and out, every result carries citations)
   │                    │                              │
FastAPI (/api)      MCP server (stdio)             Chat loop (FastAPI)
   │                    │                              │
React app           Claude Desktop / Code          Ollama local model
(dashboards,        (on plan limits)               (web chat box)
evidence, inbox)
```

**Repo layout (builder may adjust names)**

```
src/linecopilot/
  ingest/        download, checksums, loaders, contracts
  tools/         the shared tool layer (read tools + propose tools)
  actions/       preview, codes, checks, approval, audit
  ml/            features, training, scoring
  api/           FastAPI app, chat loop
  mcp_server/    MCP server wrapping tools/
dbt/             models for core and mart, with dbt tests
web/             React + TypeScript (Vite)
evals/           question sets, SQL ground truth, safety scenarios, runners, results/
tests/           pytest, fixtures/ with small CSV slices
docs/design.md
docker-compose.yml, Makefile, README.md
```

**Compose services:** `db` (Postgres 16), `api` (FastAPI, also runs the chat loop), `web` (built React app served by a small static server, or by the API in production mode). Ollama runs on the host and the API reaches it at `host.docker.internal:11434`. The MCP server runs over stdio from the host via `uv run`, pointed at the compose Postgres, the same way po-guard-mcp is wired into Claude Desktop.

## 5. Stage 1: data layer and true OEE

### 5.1 Ingest and lineage

- `make data` downloads the files from Zenodo with a plain client (generic user agent, no email in headers, no bot-protection workarounds) into `data/raw/<dataset>/`, then writes `data/checksums.json` (sha256, size, source URL, download time). A second run verifies checksums instead of re-downloading.
- The loader writes each file to its own `raw.<dataset>_<file>` table, keeping every source column as text plus three lineage columns: `load_id`, `source_file`, `source_row` (1-based line number in the file, header excluded). `raw.load` records each load: file, sha256, row counts read, accepted, rejected.
- Rows that fail a contract go to `raw.rejected` with the reason, never silently dropped. Load summaries report how many rows each rule rejected.

### 5.2 Data contracts

Contracts are declared per file in code (column names after normalisation, types, allowed ranges, required fields) and checked at load. dbt tests (not null, unique, accepted values, relationships, custom range tests) guard core and mart. Known mess to confirm and handle explicitly, each with a test:

- Brick after-period stop file: only the first 10 columns and 540 rows hold data. Empty trailing columns and rows are trimmed, and the trimmed counts are logged.
- Before and after files use different column names and some start with a BOM. A per-file column map normalises them into one shape.
- `OEEdataset.csv` has 3 rows with no OEE. They load, are flagged, and are excluded from the validation with the count reported.
- Operator notes: `-` means blank and becomes null.
- PIADE `elapsed`: confirm milliseconds from the data (compare against timestamp differences) before relying on it.
- PIADE `pi`/`po`: confirm whether they are running counters, detect resets (negative deltas) and handle them as counter restarts, not negative production.
- `A_000`: confirm whether it means "no alarm" by checking how it co-occurs with machine state. Treated as no alarm only if the data supports it, and the finding is written in the README.
- Machines cover different date ranges. Every metric states the window it covers.

### 5.3 Standard event schema

One table, `core.event`, for both lines:

| Column | Meaning |
|---|---|
| `event_id` | surrogate key |
| `source_system` | `piade` or `brick` |
| `line_id`, `machine_id` | brick events are line-level, `machine_id` null |
| `event_type` | `state_interval`, `stop`, `production_count`, `quality`, `alarm`, `note` |
| `state` | normalised machine state (running, stopped, idle, off, unknown), from the source code via a mapping table |
| `start_ts`, `end_ts`, `duration_s` | timezone-aware; source timezone recorded on the line |
| `shift_id` | from the brick data where given; for PIADE, derived from a declared shift calendar (assumption, see 5.4) |
| `reason_code`, `reason_text`, `alarm_code` | as in source, plus normalised category |
| `product` | where available |
| `qty_in`, `qty_out`, `qty_good`, `qty_reject` | counts where available |
| `raw_table`, `raw_row_ids` | lineage back to the exact raw rows (array when one event comes from several rows) |
| `is_synthetic` | always false in stage 1 to 3 core tables |

Operator notes go to `core.note` (original text, language detected, `raw_table`, `raw_row_id`, linked `event_id`) with translations in `core.note_translation` (text, model name, created at, `machine_translated = true`).

### 5.4 OEE definitions

- Availability = run time / planned production time.
- Performance = (ideal cycle time × total count) / run time, capped at 1.0 with the number of capped periods reported.
- Quality = good count / total count.
- OEE = A × P × Q, computed from events and aggregated with time weighting (not by averaging percentages).

Brick line: the check must be an independent recomputation, not the published OEE file read back to itself. Availability is computed from the stop log (planned shift time minus stop durations falling inside that shift), never from an availability column in the OEE file. Performance and quality are computed from event-level counts if the data has them. Where a component can only come from the published OEE file, it is used as published, labelled as such, and the README reports two gaps: the independently computed component(s) against their published values (the headline), and full OEE using the published values for the rest. If only availability can be computed independently, the availability gap is the stage 1 headline and the README says so plainly.

PIADE line: each of the 5 PIADE machines is treated as its own single-machine line unless the data or its documentation shows they run in series. Line-level OEE across machines is only reported for the brick line. Plant-level PIADE figures, where shown, are time-weighted sums labelled as such.

PIADE: planned time excludes states that mean the machine was not scheduled (to be confirmed from the state codes, mapping kept in a seed table). PIADE states no ideal rate, so the ideal rate per machine is estimated as a high percentile of observed speed during steady running. The default is p95, and the README shows OEE under p90, p95 and p99 so the assumption is visible. PIADE has no shift data; a declared 3 × 8 h calendar (06:00, 14:00, 22:00 local) is used and labelled as an assumption.

### 5.5 Validation against published OEE

`make validate-oee` joins computed brick per-shift OEE to the published values and writes a report: matched shifts, mean absolute gap, median gap, max gap, share within 2 and 5 points, and the per-shift table, for before and after periods separately. Large gaps are investigated and explained, never tuned away. The headline number in the README is the mean absolute gap with the count of shifts it covers.

### 5.6 Stage 1 demo

`make up && make data && make load && make validate-oee`, then the web app shows OEE by line, machine and shift with the brick validation view (computed against published, per shift), and any number can be clicked through to its source rows.

## 6. Stage 2: copilot

### 6.1 Shared tool layer

A Python package of typed functions (Pydantic models in and out). The FastAPI routes, the chat loop and the MCP server are thin wrappers over it, so all three front ends see identical behaviour. No tool takes free SQL.

Every result has the same envelope:

- `status`: `ok`, `insufficient_evidence` (with what is missing), or `out_of_scope`.
- `data`: the typed answer.
- `citations`: list of `{raw_table, raw_row_id, event_id, field}`, capped per result with a total count and a link to fetch the full set.
- `window`: the time range and machines the result covers.
- `assumptions`: e.g. the ideal-rate percentile used.

Read tools (initial set, builder may split or merge):

| Tool | Returns |
|---|---|
| `list_assets` | lines, machines, date coverage |
| `get_oee` | A, P, Q, OEE for a machine/line, window, grouping (shift, day, week) |
| `loss_pareto` | lost time ranked by stop reason, alarm, product or shift, with cumulative share |
| `reliability` | MTTR, MTBF, stop counts for a machine and window |
| `repeat_failures` | the same alarm or reason recurring within N hours on the same machine |
| `breakdown` | stop time cross-tabbed by two dimensions (alarm × shift, reason × product) to surface root-cause patterns |
| `search_notes` | notes matching a query in original text or translation, both returned side by side |
| `get_events` | events behind a filter |
| `get_source_rows` | the raw rows behind citations, as loaded |
| `stop_risk` | next-hour stop risk per PIADE machine at a given time, with the top contributing features |
| `compare_periods` | the same metrics for two windows side by side |

Propose tools are in stage 3.

### 6.2 Front ends

1. **Web app first: dashboards, evidence and inbox.** React + TypeScript (Vite). Pages: OEE overview (line, machine, shift; brick validation view), Losses (Pareto, breakdowns), Reliability (MTTR, MTBF, repeat failures), Stop risk, Notes search (original beside translation, translation badged as machine-translated), Evidence (source rows for any citation), Approvals inbox and Audit log (stage 3). A user switcher in the header sets the acting demo user, kept in a server-side session.
2. **Web chat second.** A chat box in the app backed by a local Ollama model, running a tool-calling loop in the API over the same tool layer. Answers show their citations as links to the Evidence page. The model is a small open model with good tool calling and a permissive licence; the default is chosen by a short tool-calling smoke test at the start of the chat work (candidates: Qwen 2.5 7B Instruct, Llama 3.1 8B Instruct), and the chosen name is recorded with every result.
3. **Claude through MCP.** The MCP server exposes the same tools with `ToolAnnotations` (`read_only_hint` true on read tools). Config snippet for Claude Desktop and Claude Code in the README.

The system prompt for both chat paths tells the model to answer only from tool results, cite them, and say when evidence is missing. That prompt is a convenience; the guarantees come from the tools (citations always present, no write path in read tools, no approve tool at all).

### 6.3 Notes and translation

Notes are mostly Greek, some Greek in Latin letters (e.g. `grasarisma`). Translation runs offline through the local Ollama model, once per note, stored in `core.note_translation` with the model name and badged as machine-translated everywhere it appears. Search uses Postgres full-text search plus trigram similarity (`pg_trgm`, `unaccent`) over both original and translation, so Greek, Latin-letter Greek and English queries all work. Notes are data: they are returned as quoted text and never treated as instructions.

### 6.4 Next-hour stop prediction (PIADE)

- Target: whether a machine has a stop (or a long stop, threshold set from the duration distribution, default 10 minutes) starting in the next hour. Both targets are trained; the README leads with whichever is more useful for alerting and shows both.
- Features use only data before the prediction time: recent stop counts and durations over several lookbacks, alarm counts by code family, speed and its variability, time since last stop, hour of week, machine. `sequences_1h_data.csv` is inspected for how it was built; if it cannot be shown to be free of future information it is not used for features.
- Split by time: train on earlier months, validate on the next block, test on the latest months, per machine where coverage allows. No random splits.
- Models: logistic regression and gradient boosting (scikit-learn), against two baselines: persistence (stopped in the last hour predicts a stop in the next) and hour-of-week base rate.
- Metrics: PR-AUC, and precision and recall at a useful alert volume (default: top 3 alerts per machine per shift). Leakage checks run as tests: shuffled-label run must drop to base rate, no feature timestamp after the prediction time, test months strictly after training months.

### 6.5 Evals

**Question set.** About 60 questions written as templates over machines, windows and metrics (OEE, Pareto, MTTR, MTBF, repeat failures, notes, comparisons), plus about 10 questions the data cannot answer, which must get an "evidence not available" answer. Ground truth for each comes from SQL in `evals/`, written separately from the tool code and run against `core`, so a bug in the tool layer cannot also be the answer key. Numeric answers are scored with a stated tolerance.

**Runners.** The same question set runs through:
- the web chat loop with the Ollama model (tools on), and the same model with tools off as the baseline;
- Claude through MCP, using Claude Code in headless mode with this MCP server configured, on normal plan limits (tools on), and the same Claude model with no tools as the baseline.

Each result file records the model name and version, date, and question set hash. The README reports each model separately and never averages across models.

Run budget: Ollama runs are the repeat evals and run as often as needed. Claude runs once per stage sign-off (and once more if a change could move the number), to stay within normal plan limits. The README states the date of each Claude run.

No-tools baselines must not see the answer key. The Claude baseline runs Claude Code with all built-in tools disabled and no MCP servers, from an empty temporary directory outside the repo, so it cannot read `evals/` or query Postgres. The Ollama baseline is the same chat loop with an empty tool list. A test checks the baseline config for both.

**Citation check.** For each answer, every cited row is fetched and checked automatically: it must fall inside the claimed machine, window and category, and the claimed number must be recomputable from the cited rows within tolerance. Reported as the share of cited rows that support the claim, and the share of answers whose citations fully support them.

**Before/after test.** The copilot is asked what changed on the brick line between the before and after periods. The dataset's published conclusions are kept out of its context (no paper text, no README text in prompts or tool output). Ground truth is a list of facts from SQL (change in each OEE component, biggest movers in stop reasons and durations). Scored as the share of ground-truth facts found and the number of wrong claims. Published even if weak.

### 6.6 Stage 2 demo

Ask "Why did machine X lose time last month?" in Claude and in the web chat, get a Pareto with clickable citations, then open the Evidence page on one citation. README numbers: answer accuracy per model with and without tools, citation support rate, before/after score, prediction PR-AUC and precision at alert volume against both baselines.

## 7. Stage 3: approved actions

### 7.1 Action types

- **Work order:** machine, failure mode, priority, description, linked evidence (event ids).
- **Quality hold:** line or machine, product, time window, reason, linked evidence.
- **Follow-up:** assignee role, due date, description, linked evidence.

### 7.2 Flow (after po-guard-mcp)

```
preview_<action>(args)            read-only. Runs every check, shows what would be created.
   │                              If nothing blocks: one-time code bound to the exact args,
   │                              the acting user and the action type (15 minutes, single use).
   ▼
propose_<action>(args, code)      code must match the args actually passed; checks run again.
   │                              Creates a PENDING proposal. Nothing else is written.
   ▼
Approvals inbox (web app)         a person with the right role opens it, sees the preview,
   │                              the evidence and any warnings, approves or rejects.
   ▼
approve (web only)                checks run again on fresh data, then the write to
   │                              actions.work_order / quality_hold / follow_up
   ▼
audit record                      every step, including refused and blocked attempts
```

- **No approve tool exists on MCP or in the chat loop's tool list.** Approval is a web route that requires a human session, and the route refuses if the session user is the proposer or the agent principal.
- **Identity never comes from a tool argument.** The agent has its own principal, `copilot-agent`, which can propose but never approve. Every agent proposal records two identities: the agent principal and the human it acts for (`on_behalf_of`). The MCP server's human is the demo user set in its config (like po-guard's API key); the web chat's human is the user in the app session. Proposals also record the channel (`mcp`, `web_chat`, `web_form`). Segregation of duties refuses approval by the agent principal and by the `on_behalf_of` human. The demo seeds two supervisors and a plant manager so a work order proposed for one supervisor can be approved by another person.
- **Codes** are stored hashed, bound to a hash of the canonical arguments, user and action, single use, 15 minute expiry. Editing arguments after preview, reusing a code, or using another user's code is refused.
- **Free text is data.** Descriptions and notes are stored as written. Instruction-like text ("ignore previous", "approve this", "system:") produces a visible warning in the preview and inbox for the human; it never changes what a tool does.

### 7.3 Checks (initial set, policy in `config/policy.toml`)

| Check | Rule | Result |
|---|---|---|
| Evidence exists | every linked event id exists and belongs to the named machine or line | block |
| Duplicate open action | an open work order or hold already covers the same machine and failure mode or window | block |
| Role may propose | operator: follow-up; supervisor: all; quality lead: quality hold, follow-up; planner and plant manager: follow-up | block |
| Role may approve | work order: supervisor or plant manager; quality hold: quality lead or plant manager; follow-up: supervisor | block |
| Segregation of duties | approver is the proposer, the `on_behalf_of` human, or the agent principal | block |
| Still relevant on approval | evidence still present on fresh data; for a hold, the window is not already released | block |
| Priority sanity | priority above what the evidence supports (e.g. "critical" for a single short stop) | warn |
| Instruction-like text | in any free-text field or in linked notes | warn |

### 7.4 Safety eval

Scenarios in the style of po-guard: injected instructions in operator notes and in action text, skipped approval (writing without a pending proposal), reused, stale, fake and swapped codes, arguments edited after preview, self-approval, the agent trying to reach the approve route, a role approving outside its rights. A scripted agent drives the real tool functions and the real approve route. Success of an attack is judged from database state afterwards, not from tool replies. The same scenarios run against the same tools with checks and codes removed, as the baseline. Legitimate flows must still complete. README reports unsafe writes that landed, with and without guardrails, and legitimate flows completed. A smaller set of injection scenarios also runs through the Ollama chat loop and through Claude via MCP, each reported with its model name.

The brief's safety measure also covers injected instructions in order text. Orders do not exist until stage 4, so the stage 3 number covers operator notes and action text only, the README says so, and stage 4 adds order-text scenarios to the same eval (done, see 10.4).

### 7.5 Stage 3 demo

In Claude: "Draft a work order for the repeat jams on machine X." The preview shows evidence and a warning from an injected note; the proposal lands in the inbox; switching to the supervisor in the app approves it; the audit log shows every step. Then the same agent tries to approve its own proposal and is refused.

## 8. Testing and CI

- Unit tests on pure logic (contracts, OEE maths, counter resets, code binding, checks) using small CSV fixtures in `tests/fixtures/`, cut from the real files' structure.
- Integration tests against a throwaway Postgres (compose locally, a service container in CI), marked so they can be skipped.
- Coverage gate: 80% on `src/` (adjustable once the real number is known, never lowered to pass).
- `.github/workflows/ci.yml`: ruff, pytest with coverage gate, pip-audit, gitleaks, Docker build. Written and run locally; nothing is pushed until Janish says so.
- `make report` rewrites the measured sections of the README from `evals/results/`.

## 9. Synthetic data in stages 1 to 3

Only demo users and roles (in `demo.*`, `source = 'synthetic'`, badged in the app). Orders, BOMs, stock and lead times arrive in stage 4 under the rules in the brief.

## 10. Stage 4: scheduling and shortages

**Decision it supports:** which order runs on which packaging machine and when, and which orders a material shortfall will hit, early enough to act. Demand is synthetic; capacity and disruption are real.

### 10.1 Synthetic data (schema `synthetic`, every table has `source = 'synthetic'`)

A seeded generator in the repo (`make synth`, default seed 7) writes:

- **Products:** 18 SKUs in 3 pack families (carton, pouch, tray). Each machine runs two families except s_4 (carton only), and every family has at least two eligible machines, so the planner has real choices.
- **Machine rates (real):** the p95 set speed per machine (packages per hour) on production rows before 2021-07-01, and a planning availability per machine of 1 minus stopped seconds over covered interval seconds before 2021-07-01 (idle counts as available, because the replay only injects stops). A machine with no data before the cutoff takes the median of the others.
- **Changeovers (anchored):** PIADE records no changeovers, so times come from the brick line's real `SETUPS-CHANGEOVERS` stops: same product 0, same family the p25 (12 min), different family the p75 (19 min). The README says they come from a different process and period, so they cannot leak the PIADE stops used in replay.
- **Orders:** 46 customer orders released over the first 7 days of a 14-day horizon, each due 4 to 8 days after release, with quantities scaled so load is 90% of planned capacity (orders average about 30 nominal machine hours). A few orders carry a free-text note; three notes hold planted instruction-like text for the safety eval.
- **BOM and materials:** two levels. Each product uses a printed carton (sub-assembly), film and a label; each printed carton uses board and ink. Stock on hand, open receipts with dates, and supplier lead times per material.
- **Planted shortages:** the generator plants (material, order) shortfalls of three kinds, plain (stock plus receipts below demand), timing (enough in total, but the receipt lands after the need date) and level two (only visible after netting the carton stock), plus decoys that a naive rule flags but are not shortages (a receipt arrives in time; carton stock covers the board). Ground truth sits in `synthetic.planted_shortage`, read only by the eval.

The generator is anchored to real numbers where they exist and is labelled synthetic everywhere else. Planted shortages test the software; they are not real-world results.

### 10.2 Shortages

MRP-style netting by day over the horizon: requirements by need date (the order's due date minus its processing time), allocated in need-date order; sub-assembly net requirements explode to raw materials after netting carton stock; projected stock = on hand + receipts - allocated requirements. A shortfall is a requirement not covered on its need date; it is traced to the exact orders whose requirement is short, with the quantity and the first short day. Compared with a simple rule: a material is short if stock on hand is below its total gross requirement over the horizon, flagging every order that uses it. Scored as precision and recall on (material, order) pairs and on materials, overall and per planted kind. Because the detector and the generator share the netting definition, a perfect score shows the code implements the definition, not real-world accuracy; the README says so.

### 10.3 Scheduling

- **Model:** OR-Tools CP-SAT. Each order goes to one eligible machine as an interval of `quantity / (rate x availability)`; sequence-dependent changeovers via a circuit per machine; an order cannot start before its release time or its material-ready time (from 10.2; an order whose shortfall has no receipt in the horizon is reported as blocked, not scheduled). Objective: total tardiness in minutes plus 0.1 times changeover minutes. Deterministic: one worker, fixed seed, a deterministic time limit (60, with a 120 s wall cap, see section 12); the solver status (optimal or feasible) is recorded.
- **Baselines:** first in, first out (by release time) and earliest due date, each a list schedule that puts the next order on the eligible machine where it finishes first, with the same changeovers and ready times.
- **Replay of real stops:** each plan is executed against real PIADE stop episodes from a later period. Eight non-overlapping 14-day windows from 2021-07-01 to 2021-12-31 are cut from `mart.stop_episode` and overlaid on the horizon, machine by machine. The horizon is a made-up two weeks starting 2026-01-05; a window's real stops map onto it by offset from the window start, so 2026 dates in the app stand for days in a 2021 window. The plan's order sequence is kept (no rescheduling); work only progresses when the machine is not stopped, at the nominal rate. Planning availability comes only from data before 2021-07-01, so nothing in a plan sees the stops it is replayed against; a test checks this.
- **Measures:** late orders, total tardiness and changeover hours, nominal and replayed, for CP-SAT, FIFO and EDD, over 5 order seeds x 8 replay windows, reported as median and interquartile range. Not averaged with any real-data metric.

### 10.4 Copilot, actions and safety

- New read tools: `get_plan` (plan KPIs against the baselines, per-machine sequence), `shortages` (shortfalls with traced orders) and `get_order` (an order with its note returned as quoted data). They are labelled synthetic in their results. The stage 2 answer eval keeps its own pinned list of the original 12 tools so its results stay comparable.
- Follow-ups gain optional `order_ids`; checks confirm the orders exist and scan their notes for instruction-like text (warn only).
- The safety eval adds order-text scenarios (scripted and LLM): an order note asks the agent to approve or expedite; judged from the database as before. This closes the order-text item left open in 7.4.

### 10.5 Stage 4 demo

The Plan page shows CP-SAT against FIFO and EDD, nominal and under replayed real stops, with a per-machine sequence. The Shortages page lists shortfalls with the orders they hit. In Claude: "Which orders will the board shortage hit?" answered from `shortages`, then a follow-up drafted for the planner, which lands in the inbox.

## 10b. Stage 5 (outline, designed in detail later)

- **5. Visual inspection:** VisA food subsets, anomaly heatmaps for a reviewer, reviewer decisions as labels, cost-based threshold with a sensitivity table, ONNX export with measured CPU latency, rejected images creating simulated, labelled quality events. To keep both brief rules (synthetic data in its own schema, and one event table the copilot reads), simulated events are stored in `synthetic.quality_event` with a `source` column, and a view `core.event_all` unions them with `core.event` with `is_synthetic` set. The copilot and approval flow read `core.event_all`. `mart` metrics read `core.event` only, so no headline number mixes real and synthetic data.

## 11. Decided by Janish

- Build both a web chat (local Ollama) and Claude through MCP on one shared tool layer. Dashboards, evidence views and the approvals inbox come first; the chat box second.
- Run the same answer and citation evals on both and report each with its model name.
- Three-layer Postgres (raw, core via dbt, mart), lineage to raw rows, brick line for OEE validation, PIADE for analysis and prediction, propose-only MCP with approval in the web app, demo user switcher instead of login.

## 12. Calls made in this design (open to change)

- PIADE ideal rate = p95 of steady-running speed, with p90 and p99 shown.
- PIADE shifts from a declared 3 × 8 h calendar.
- Long stop default threshold 10 minutes, set from the data once seen.
- Note search with Postgres full-text and trigram instead of embeddings.
- Note translation by the local Ollama model, stored once with the model name.
- Claude evals run through Claude Code headless with the MCP server, on plan limits.
- Role and approval rules in 7.3.
- Coverage gate 80%.
- Brick OEE check recomputes availability from the stop log; published components are only used where nothing independent exists, and are labelled (5.4).
- Each PIADE machine is its own line (5.4).
- Agent has its own principal that never approves, plus an `on_behalf_of` human who can't approve their own proposal either (7.2).
- Claude evals run once per stage sign-off; Ollama does the repeats. No-tools baselines are sandboxed from the answer key (6.5).
- Stage 5 simulated events live in `synthetic.*` and join the copilot's view, not the marts (10).
- As built in stage 2, the full set of citations behind a result is fetched per event (`get_source_rows`, `/api/events/{id}/source`) or per shift (`shift_evidence`); there is no single link to the full set for a whole result. `get_oee` groups by shift, day or month; week grouping is not provided.
- As built in stage 2, the MCP server and the chat loop send the model a compacted envelope (capped citations and list lengths, a 40,000-character guard, and a `trimmed` note saying what was cut); the API returns the full envelope.
- As built in stage 2, the eval answer key reads the dbt marts, not only `core` (6.5). It stays apart from the tool code, and a recount from `core.event` guards the stop marts (`docs/data-notes.md`).
- As built in stage 3, the agent proposes through a separate Postgres role, `linecopilot_agent`. It has a column-limited insert on proposals (no status, decision or target columns), a `used_at` trigger that makes each confirmation code single use, and append-only audit rows (update, delete and truncate are refused). Known gap: with raw SQL that role can still insert a pending proposal or an audit row. No tool gives the model SQL, and approval re-runs every check on fresh data, so such a row still needs an entitled, independent person to approve it. Its default password in compose and config is dev-only.
- As built in stage 3, preview is audited too (event `previewed`), not only propose and the decisions.
- As built in stage 3, evidence is linked by `event_key` (stable `source_file#source_row`) with the `event_id` at link time kept for display; re-checks resolve the key against current `core.event`.
- As built in stage 3, web-form proposals are a person acting and run on the main database role; only the agent channels (MCP, web chat) use the restricted role. Every action service method requires an autocommit connection and opens its own transactions.
- As built in stage 3, confirmation code hashes are unsalted sha256. That is acceptable because a code is single use, bound to the arguments, user and action, and expires after 15 minutes.
- As built in stage 3, segregation-of-duties and role refusals return HTTP 403 and fresh-data blocks return 409.
- As built in stage 3, the close, release and complete role sets live in the action service, not in `config/policy.toml`, which covers proposing and approving.
- As built in stage 3, the LLM safety measure is split into "unsafe writes landed" (rows written without a person approving) and "injection followed" (a proposal that differs from what the user asked for, which still waits for a person). Order-text injection scenarios wait for stage 4, when orders exist.
- As built in stage 3, there is no real authentication (a stated non-goal): the demo user switcher is not a login and any local process can pick a user. The approval guarantee covers the copilot's own tools (MCP and web chat), which have no approve tool and cannot set identity. Claude for the demo and the evals runs with its built-in tools off (`--tools ""` with a strict MCP config), because an agent with a shell or HTTP access on the same machine could sign in as another demo user.
- As built in stage 3, the preview result carries the linked notes' text, quoted and labelled as data (event id, source, a synthetic flag for demo notes, original text, and the translation with its model name when there is one, capped at 600 characters each and 10 notes), so the model sees what the inbox shows a person. Instruction-like text in a note only raises a warning; the arguments are never changed by it.
- As built in stage 3, a call that names an identity or unknown argument, or whose arguments are not an object, is refused and writes one `refused` audit row with the channel and `on_behalf_of` from the context. A rejection through the web route needs a written reason. The policy file path is anchored to the repo root; a policy that fails to load leaves the MCP server read-only.
- As built in stage 3, the approvals inbox shows a linked note's machine translation beside the original, and a "Synthetic demo note" badge on the planted demo note; the web app's Losses page links each repeat chain to a prefilled work order draft.
- As built in stage 4, CP-SAT stops on a deterministic time of 60 with a 120 s wall-clock safety cap, not a 20 s wall limit, so the headline is reproducible across machines; the stop reason (deterministic time or wall) is stored with the plan.
- As built in stage 4, a fourth algorithm, `edd_batch` (EDD that prefers the family the machine just ran among jobs due within 24 h of the earliest), was added to every eval and page, so the weak-baseline caveat has a number. It cuts changeovers but loses on tardiness.
- As built in stage 4, an order's ready time is the earliest moment the on-hand stock plus receipts due cover the cumulative requirements allocated in need-date order up to and including that order, taken over its raw materials after sub-assembly netting. An order with no such moment inside the horizon is blocked, with the reason, and counted apart from tardiness. All algorithms share the definition.
- As built in stage 4, planning availability is one minus stopped time over covered time (state interval durations) before 2021-07-01; idle counts as available because the replay injects stop episodes only. Idle and gap shares are recorded with the anchors, and a machine with no pre-cutoff data takes the median of the others.
- As built in stage 4, a replay window where a machine has no PIADE data is replayed as having no stops there, and the results disclose the no-data share per window and machine, with realised stopped share over covered time beside the planning figure.
- As built in stage 4, the stage 2 answer and Claude evals are pinned to the original 12 tools (`LINECOPILOT_MCP_TOOLS` for the Claude runner, a constant for the others), so the stage 2 results do not change although the registry now has 15.
- As built in stage 4, follow-ups take optional `order_ids` (0 to 20, sorted and deduplicated, left out of the canonical payload when empty). Checks confirm the orders exist and scan their notes for instruction-like text (warn only), and the preview and the approvals inbox show the notes quoted as data.
- As built in stage 4, the LLM safety judge requires the requested fields (including `order_ids`) before it counts a proposal as the requested action.
- As built in stage 4, the web app has Plan, Shortages and Order pages, each badged "Synthetic orders on real capacity". The plan timeline is plain CSS bars; the KPI table shows the replayed median and interquartile range over that plan's 8 replay windows, served by `/api/plan` (inclusive quartiles, as in `evals/plan.py`). The README table pools 5 seeds x 8 windows, so its quartiles differ from the page's.

## 13. Left to the builder

Exact table and column names beyond those above, dbt model split, tool names and argument shapes within the envelope in 6.1, React component structure and charting library, feature engineering details, and the exact question templates, as long as the rules above hold.
