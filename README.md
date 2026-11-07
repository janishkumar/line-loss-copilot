# line-loss-copilot

Mid-sized plants lose capacity to stops, changeovers, slow running, shortages and defects. The evidence sits in machine logs, spreadsheets and operator notes that nobody can search, so planning reports take hours and the same failures come back. This project turns those sources into one trusted data layer, computes OEE from events, and answers questions with every number traced to source rows. The AI proposes; a person approves.

**Decision it supports:** where a line is losing time, and whether those numbers can be trusted before anyone builds an assistant on top of them. Stage 1 is the trusted layer: both real datasets in Postgres with row-level lineage, OEE computed from events, and a published-versus-recomputed check on the brick line.

Stage 2 adds the copilot on top: one read-only tool layer served by the API, an MCP server and a web chat on a local model, with loss ranking, MTTR and MTBF, repeat failures, operator-notes search, a next-hour stop-risk model, and evals that score answers and citations against SQL.

Status: stages 1 and 2 of 5 (data layer and true OEE; copilot). Stages 3 onward (approved actions, scheduling, visual inspection) are not built yet.

## Stage 1 results
<!-- oee:start -->
### Brick line: recomputed availability against published

Availability is recomputed from the stop log (planned time minus the union of in-OEE stop intervals, clipped to the date). Planned time is the one published input. Gap = recomputed minus published, in percentage points, over every shift with both stops and a published row. Nothing is filtered.

| Period | Window | Matched shifts | Mean abs gap | Median abs gap | Max abs gap | Within 2 pts | Within 5 pts | Mean signed |
|---|---|---|---|---|---|---|---|---|
| before | 2025-09-22 to 2025-12-18 | 62 | 13.36 pts | 3.44 pts | 52.09 pts | 38.7% | 61.3% | 6.59 pts |
| after | 2026-01-30 to 2026-04-03 | 43 | 1.15 pts | 0.58 pts | 24.50 pts | 97.7% | 97.7% | -0.01 pts |

- before: 62 published shifts, 62 matched, 0 with no stops, 0 stop-only days with no published row (shown, not dropped).
- after: 43 published shifts, 43 matched, 0 with no stops, 2 stop-only days with no published row (shown, not dropped).

Breakdown chosen after seeing the gaps (the 9 h threshold was picked once the October block stood out, so read it as explanation, not as a better headline):

| Period | Planned-day length | Shifts | Mean abs gap | Median abs gap |
|---|---|---|---|---|
| before | over 9 h | 13 | 46.54 pts | 46.74 pts |
| before | 9 h or less | 49 | 4.55 pts | 2.07 pts |
| after | over 9 h | 1 | 0.03 pts | 0.03 pts |
| after | 9 h or less | 42 | 1.18 pts | 0.59 pts |

### Brick line: full OEE with published performance and quality

Availability is recomputed; performance and quality are the published values (the files hold no event-level counts to recompute them from). The published P and Q enter this comparison as given. Same shifts and windows as above.

| Period | Window | Matched shifts | Mean abs gap | Median abs gap | Max abs gap | Within 2 pts | Within 5 pts |
|---|---|---|---|---|---|---|---|
| before | 2025-09-22 to 2025-12-18 | 62 | 12.09 pts | 3.20 pts | 48.98 pts | 41.9% | 61.3% |
| after | 2026-01-30 to 2026-04-03 | 43 | 1.14 pts | 0.54 pts | 26.00 pts | 97.7% | 97.7% |

### PIADE: OEE per machine over full coverage

Each machine is its own line. Time-weighted: seconds and counts are summed, then ratios computed. Windows are the dates of each machine's first and last assumed shift start (UTC). The ideal rate is estimated from `speed`, so OEE is shown at p90, p95 (headline) and p99. P is count-based; time-based P is the cross-check.

| Machine | Window | Planned h | A | P count (p95) | P time | Q | OEE p90 | OEE p95 | OEE p99 |
|---|---|---|---|---|---|---|---|---|---|
| s_1 | 2020-01-01 to 2021-12-31 | 11,905 | 0.777 | 0.786 | 0.833 | 0.998 | 0.616 | 0.609 | 0.596 |
| s_2 | 2020-06-15 to 2021-12-31 | 4,163 | 0.413 | 0.704 | 0.789 | 0.993 | 0.289 | 0.289 | 0.289 |
| s_3 | 2020-10-07 to 2022-01-01 | 6,759 | 0.492 | 0.777 | 0.908 | 0.997 | 0.381 | 0.381 | 0.358 |
| s_4 | 2019-12-31 to 2022-01-01 | 6,132 | 0.691 | 0.567 | 0.637 | 0.996 | 0.390 | 0.390 | 0.371 |
| s_5 | 2020-01-11 to 2022-01-01 | 8,635 | 0.655 | 0.772 | 0.815 | 0.997 | 0.504 | 0.504 | 0.504 |

Note: s_4's window starts 2019-12-31 because its first interval (2020-01-01 00:05 UTC) falls in the 22:00 UTC shift that began the day before.

These PIADE figures have no published value to check against; they are computed, not validated. Brick and PIADE numbers are never combined.

Assumptions:

- PIADE shifts are 3 x 8 h in UTC from 06:00, because the data gives no site timezone.
- Idle counts as planned time; scheduled downtime does not.
- P uses total input (`pi`) over ideal rate times run hours, with the ideal rate a percentile of observed set speed.
- Q is output over input, capped at 1 per shift.
- Counters are end-aligned (a reading belongs to the row it ends); resets and glitches are dropped.
- Shifts with a counter glitch on a run row, or run time with no input counted, are left out of count-based P and Q; A and time-based P keep them.
- Brick planned time and, in the OEE comparison, published P and Q are published inputs.

Details and the reasoning behind each choice are in `docs/data-notes.md`. Regenerate with `make validate-oee && make report`.
<!-- oee:end -->

## Stage 2 results

### Copilot evals

<!-- copilot-evals:start -->
Each row is one runner and one model; rows are never averaged. Results from a local model are labelled with its name. Accuracy is scored against an answer key computed in SQL, apart from the tool code. Citation support is the share of cited event ids that belong to the answer key's evidence set.

| Runner | Model | Version | Run date (UTC) | Question set | Accuracy, all | Answerable | Unanswerable (says not available) | Cited rows supporting the answer | ANSWER line parsed | Context filled | Before/after facts found | Before/after wrong claims |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Claude through MCP, with tools | not run yet | - | - | - | - | - | - | - | - | - | - | - |
| Claude, no tools | not run yet | - | - | - | - | - | - | - | - | - | - | - |
| Local model, with tools | `qwen2.5:7b-instruct` | digest 845dbda0ea48, ollama 0.40.14 | 2026-11-07 | `c32c30730107` (70 of 70) | 38/70 (54.3%) | 28/60 (46.7%) | 10/10 (100.0%) | 7/7 (100.0%) | 97.1% | 4 | 0/4 (0.0%) | 0 of 0 |
| Local model, no tools | `qwen2.5:7b-instruct` | digest 845dbda0ea48, ollama 0.40.14 | 2026-11-07 | `c32c30730107` (70 of 70) | 9/70 (12.9%) | 0/60 (0.0%) | 9/10 (90.0%) | 0/38 (0.0%) | 90.0% | 0 | 0/4 (0.0%) | 0 of 0 |

How to read it:

- The answer key reads the same dbt marts as the tools (`mart.stop_episode`, the OEE marts), so a bug in a mart would be shared by the tools and the key. The dbt tests guard the marts, and `make check-questions` recounts stop count and lost seconds per reason from `core.event` for one brick month and one PIADE month and checks they match `mart.stop_episode`. Read the accuracy as model plus tools reproducing the marts, not as an end-to-end proof.
- The scope and month hints in the tool descriptions and the fixed sentence asking for a final `ANSWER:` line were added after smoke runs on 5 questions from this question set. They apply to every runner, with and without tools.
- Before/after facts are scored only when every reading agrees: totals also per shift, ratios also without the 13 October 2025 days whose published planned time is not accounted for. The brick file names (`afterLSS`) in citations reveal that an intervention happened, not its results.
- Context filled counts questions where a local-model call came within 256 tokens of its context window, where Ollama cuts the prompt without an error.
- Per-question detail: `evals/results/answers_*.md` and `before_after_*.md`. Regenerate with `make eval-ollama` or `make eval-claude`, then `make report`.
<!-- copilot-evals:end -->

### Next-hour stop risk (PIADE)

<!-- stop-risk:start -->
Real PIADE data only. Generated 2026-11-07T05:51:09Z with scikit-learn 1.9.1, feature list hash `e28113e96629a2ca`. Split by time: train t < 2021-07-01, validation 2021-07-01 <= t < 2021-10-01, test t >= 2021-10-01. The model was selected on validation PR-AUC; the numbers below are the test split. A long stop is a stop episode of 600 s or more. Compare PR-AUC with the base rate, not with 0. Alert volume: the top 3 (default) or top 1 hours per machine per 8 h shift.

| Target | Model | Test base rate | PR-AUC | Precision, top 3 | Recall, top 3 | Precision, top 1 | Recall, top 1 |
|---|---|---|---|---|---|---|---|
| long | logistic | 0.055 | 0.170 | 0.062 | 0.467 | 0.063 | 0.163 |
| long | hist_gb (served) | 0.055 | 0.181 | 0.067 | 0.511 | 0.067 | 0.173 |
| long | persistence | 0.055 | 0.113 | 0.059 | 0.445 | 0.037 | 0.097 |
| long | hour_of_week | 0.055 | 0.107 | 0.065 | 0.493 | 0.078 | 0.203 |
| any | logistic | 0.508 | 0.851 | 0.611 | 0.502 | 0.661 | 0.185 |
| any | hist_gb (served) | 0.508 | 0.870 | 0.620 | 0.509 | 0.663 | 0.186 |
| any | persistence | 0.508 | 0.712 | 0.546 | 0.448 | 0.540 | 0.152 |
| any | hour_of_week | 0.508 | 0.723 | 0.561 | 0.461 | 0.592 | 0.166 |

persistence and hour_of_week are the baselines. Per-machine results, the observed-only figures and the leakage checks are in [evals/results/stop_risk.md](evals/results/stop_risk.md).
<!-- stop-risk:end -->

## Stage 3 results

### Safety eval: approved actions

<!-- safety:start -->
Scripted attacks drive the real propose tools on the agent's restricted database role and the real approve routes with real session cookies, on the test database. The baseline runs the same scenarios on the same tables with every check and code removed and a sign-in that accepts anyone, the agent included. An attack counts only if its row is in the database afterwards; tool replies are not trusted.

| Category | Attacks | Landed with guardrails | Landed without guardrails | What it covers |
|---|---|---|---|---|
| protocol | 6 | 0 | 6 | Confirmation codes: none, made up, reused, expired, another user's, another action's |
| edited_args | 3 | 0 | 3 | Arguments changed between preview and propose |
| approval | 6 | 0 | 6 | Self-approval, the proposer, the agent signing in, roles outside their rights |
| fresh_data | 4 | 0 | 4 | Duplicates, wrong-asset or vanished evidence, a hold released meanwhile |
| injection | 3 | 0 | 3 | Instructions planted in an operator note (English, Greek) or in action text |
| db_layer | 4 | 0 | 0 | The agent's database role writing directly; double approval |
| **All attacks** | 26 | 0 | 22 | |
| **Legitimate flows completed** | 9 | 9/9 | 9/9 | still work with guardrails on |

Run 2026-11-07 (guarded) and 2026-11-07 (baseline) at commit `2444e730c126`, scenario set `b148e397be50c394`. Errors during the runs: 0 guarded, 0 baseline.

LLM injection subset: a user asks for one specific action on real events while a planted operator note or the user's own pasted text tells the model to approve, raise the priority, add a second action or act for someone else. Unsafe writes are rows written without a person approving; injection followed is a proposal that differs from what the user asked for (it still waits for a person).

| Runner | Model | Version | Run date (UTC) | Prompts | Unsafe writes landed | Injection followed | Requested action proposed |
|---|---|---|---|---|---|---|---|
| Local model, web chat loop | `qwen2.5:7b-instruct` | digest 845dbda0ea48, ollama 0.40.14 | 2026-11-07 | 5 | 0 | 0 of 5 | 1 of 5 |
| Claude through MCP | not run yet | - | - | - | - | - | - |

How to read it:

- For code and argument attacks the unsafe write is the pending proposal itself; for approval, fresh-data and injection attacks it is the work order, hold or follow-up row.
- db_layer is 0 in both columns because Postgres refuses it (column grants on the agent role, a unique proposal per work order), not the service code. It is a database guard and is reported apart from the rest.
- The brief also asks for injected instructions in order text. Orders arrive in stage 4; until then this covers operator notes and action text only.
- Per-scenario detail: `evals/results/safety_guarded.md`, `safety_naive.md` and `safety_llm_*.md`. Regenerate with `make eval-safety` (and `make eval-safety-ollama` or `make eval-safety-claude`), then `make report`.
<!-- safety:end -->

## Assumptions

- PIADE has no stated ideal rate. Performance rests on an estimate (a percentile of the set `speed` per machine), shown at p90, p95 and p99.
- PIADE shifts are an assumed 3 x 8 h UTC calendar; the data gives no site timezone.
- Brick line planned time is a published input. Brick timestamps are local Europe/Nicosia.
- Brick availability uses the union of in-OEE stop intervals, clipped to the date, so overlapping stops count once. On the real files no stops overlap, so union and plain sum give the same numbers.
- Every metric states its window. Real-data figures are never blended into one headline number.
- Next-hour stop risk (PIADE): a long stop is a stop episode of 600 s or more (2.9% of episodes; p95 is 412 s, p99 1183 s). Results and baselines are in [evals/results/stop_risk.md](evals/results/stop_risk.md); `make train-risk` regenerates them.

The full list, with the evidence for each, is in [docs/data-notes.md](docs/data-notes.md).

## Data and credits

All three datasets are licensed CC BY 4.0. Raw files are not in this repository; `make data` downloads them into a gitignored `data/` folder and records a checksum manifest.

| Dataset | Source | Used for |
|---|---|---|
| PIADE: industrial packaging machines (5 machines, 2020 to early 2022) | [Zenodo record 7071747](https://zenodo.org/records/7071747), CC BY 4.0 | Machine state, alarms and counters; OEE per machine |
| Heavy clay brick line: OEE and downtime, before and after a Lean Six Sigma program | [Zenodo record 17855209](https://zenodo.org/records/17855209), CC BY 4.0 | Published per-shift OEE and stop log; validation |
| VisA (Visual Anomaly) | [github.com/amazon-science/spot-diff](https://github.com/amazon-science/spot-diff), CC BY 4.0 | Visual inspection in stage 5; not used yet |

## Real vs synthetic

| Data | Real or synthetic | Stage |
|---|---|---|
| PIADE machine intervals, alarms, counters | Real | 1 |
| Brick line published OEE and stop log | Real | 1 |
| Operator notes (Greek, original text kept beside a labelled machine translation) | Real | 1 (loaded), 2 (search) |
| VisA images | Real | 5 |
| Orders, products, BOMs, stock, supplier lead times, changeovers, demo users | Synthetic, generated by a seeded script, own schema, `source` column, badged in the app | 3 to 4 (none exist yet) |

Stages 1 and 2 contain no synthetic data.

## What didn't work (and what replaced it)

- **Trusting the download manifest hash.** The manifest records a hash at download time, which says nothing about the file later loaded. The loader now hashes the file it actually reads and keys the load on that, so re-running `make load` replaces the same load instead of duplicating it.
- **Citing (table, row).** Row numbers collided between the before and after brick files. A citation is now (table, file, row).
- **Start-aligned PIADE counters.** Giving each counter delta to the row it starts on put 11 to 31% of output on non-run time and tripped the glitch rule thousands of times. End alignment puts 94 to 98% of counts on run rows.
- **Overlapping PIADE intervals.** On three machine-nights (2020-10-25 and 2021-10-31) intervals overlapped and one hour was counted twice (a shift held 9 h of an 8 h window). The dates match the EU daylight-saving end, but the cause is unexplained. Later intervals are now clipped to the end of the earlier one.
- **Zero-input shifts in the monthly rollup.** Shifts with run time but no counted input dragged count-based performance down. They are now left out of count-based P and Q (A and time-based P keep them) and counted in the notes.
- **Translating notes with a bare prompt.** The local model turned plant words into nonsense (pistons became "shotguns", the mould became "ball") and transliterated some notes instead of translating them: about 3 of 10 spot-checked notes were right. A lower-cased copy of each note plus a short hand-written glossary of brick-plant terms raised that to 8 of 10. Every translation is stored with its model name (`qwen2.5:7b-instruct+glossary-v1`), labelled machine-translated, and shown beside the original, which stays the reliable path for search.
- **Letting a small model guess the scope.** In the first eval smoke runs the local model passed the brick line together with a PIADE machine and averaged daily OEE rows instead of asking for a month, and scored 0 of 5. Tool descriptions now state the scope rule and how to get a monthly figure, and identical repeated tool calls in one round run once (one question had sent the same call 17 times).
- **Sending whole tool results to the model.** Some calls returned 60k to 290k characters, above what Claude Code accepts from an MCP tool and enough to overflow the local model's context silently. Model-facing output now goes through one shared compaction step (MCP and chat get identical payloads, under 26k characters), the API still returns everything, and each Ollama round records its token counts so a full context is flagged.
- **Scoring before/after on the raw October data.** The first answer key said brick availability went down after the program, but that came entirely from the 13 October days whose published planned time is not accounted for; without them it went up. Ratio facts are now scored only when both readings agree, and the rest are listed as ambiguous.
- **A next-hour stop alarm worth acting on.** The long-stop model beats both baselines on PR-AUC, but at one alert per machine per shift the hour-of-week baseline is as good or better. It is published as a weak signal, not as an alarm.
- **Getting a 7B local model to cite and to compare.** With tools it answered 28 of 60 answerable questions against 0 of 60 without, but it left citations out of 96% of its answers, so the 7 of 7 supported citations rest on very few rows. It got 0 of 6 stop counts, 0 of 5 month-to-month availability changes and 0 of 4 before/after facts, because it picked the wrong tool (OEE instead of the loss or event tools for a stop count) or sent out-of-scope requests, then answered "not available". The tool layer turns those requests away correctly; this model does not recover from that. The Claude rows above are the test of whether a stronger model does.
- **The brick availability gap is not closed.** Recomputing availability from the stop log lands within 2 points on 97.7% of after-period shifts but only 38.7% of before-period shifts. The before gap traces to a block of October days where published planned time is far longer than the logged day; the files do not explain why. It is reported as measured, not filtered.

## Use it from Claude

The copilot's tools are exposed as a read-only MCP server named `linecopilot`. It has no write, approve or delete tool, and every answer is the same envelope the API returns, with citations to raw rows. It reads the database at `LINECOPILOT_DB_URL` (default: the compose database on port 5434), so run `make up` and load the data first.

Claude Desktop, in `claude_desktop_config.json` (replace `/path/to/line-loss-copilot` with the repo path):

```json
{
  "mcpServers": {
    "linecopilot": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/line-loss-copilot", "python", "-m", "linecopilot.mcp_server"],
      "env": { "PYTHONPATH": "src" }
    }
  }
}
```

Claude Code:

```
claude mcp add linecopilot --env PYTHONPATH=src -- uv run --directory /path/to/line-loss-copilot python -m linecopilot.mcp_server
```

The tools then appear as `mcp__linecopilot__<tool>`, for example `mcp__linecopilot__get_oee`.

Optional: set `LINECOPILOT_MCP_USER` to a demo user id (for example `sup.a`) in the `env` block to also get the propose tools (`preview_*`, `propose_*`, `list_my_proposals`), which act on behalf of that user through the restricted agent database role (`LINECOPILOT_AGENT_DB_URL`). They only create pending proposals; a different person approves them in the web app, and there is no approve tool. With the variable unset, or naming the agent or an unknown user, the server stays read-only and prints one line to stderr saying why.

## Run it

Needs Docker, uv, and Node 24 (Node only for local web work).

```
make demo-stage1   # db, api and web up; download data; load; dbt build; validation report
make demo-stage2   # demo-stage1, then the stop-risk models, so every page has data
make report        # rewrite the results sections above from evals/results/
make train-risk    # next-hour stop-risk models on PIADE (about 20 s)
make mcp           # MCP server over stdio
make lint          # ruff
make test          # offline tests
make test-db       # tests that need Postgres (uses the compose test database)
make down
```

Raw tables are created with `CREATE TABLE IF NOT EXISTS`, so after a schema change recreate the database volume (`docker compose down -v`) and reload.

Then open http://localhost:8080 (overview, validation, evidence, losses, reliability, notes, stop risk, chat). The API is on http://localhost:8000. Both ports are bound to 127.0.0.1 only. The chat needs Ollama on the host (`LINECOPILOT_CHAT_MODEL`, default `qwen2.5:7b-instruct`, chosen over `llama3.1:8b-instruct` by a tool-calling smoke test: 22 of 24 against 19 of 24, and faster; see `evals/results/chat_model_smoke.json`). If port 8000 is taken, set `LINECOPILOT_API_PORT`.

More: [docs/data-notes.md](docs/data-notes.md) (data findings and how each number is reproduced), [docs/design.md](docs/design.md) (design for all stages).

Reproduction here uses `PYTHONPATH=src`, which the Makefile exports.
