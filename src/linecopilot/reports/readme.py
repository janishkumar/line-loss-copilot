"""Render README sections from evals/results/*.json. `make report` runs this.

Sections: `oee` (stage 1 validation), `copilot-evals` (answer, citation and before/after
evals, one row per runner and model, never averaged), `stop-risk` (next-hour stop-risk
models on the test split) and `safety` (approved-actions safety eval, with and without
guardrails, plus the LLM injection subset) and `shortages` (stage 4 shortage detector against
the naive rule, on synthetic data) and `plan` (stage 4 schedule: CP-SAT against FIFO and EDD,
nominal and replayed against real stops). A result file that does not exist yet renders
as "not run yet"."""

from __future__ import annotations

import json
import re
import statistics
from pathlib import Path
from typing import Any

from linecopilot.chat.ollama import context_count
from linecopilot.plan.dispatch import BATCH_SLACK_MIN
from linecopilot.reports.oee_validation import PERIODS, RESULTS, _pct, _pts


def render_readme(readme_text: str, sections: dict[str, str]) -> str:
    """Replace the content between <!-- name:start --> and <!-- name:end --> for each section."""
    out = readme_text
    for name, body in sections.items():
        pat = re.compile(
            rf"(<!-- {re.escape(name)}:start -->\n).*?(<!-- {re.escape(name)}:end -->)", re.S
        )
        if not pat.search(out):
            raise ValueError(f"README has no markers for section {name!r}")
        repl = body.rstrip("\n") + "\n"
        out = pat.sub(lambda m, repl=repl: m.group(1) + repl + m.group(2), out, count=1)
    return out


def oee_section(val: dict, piade: list[dict]) -> str:
    L: list[str] = []
    L += [
        "### Brick line: recomputed availability against published",
        "",
        "Availability is recomputed from the stop log (planned time minus the union of in-OEE "
        "stop intervals, clipped to the date). Planned time is the one published input. "
        "Gap = recomputed minus published, in percentage points, over every shift with both "
        "stops and a published row. Nothing is filtered.",
        "",
        "| Period | Window | Matched shifts | Mean abs gap | Median abs gap | Max abs gap | Within 2 pts | Within 5 pts | Mean signed |",  # noqa: E501
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for p in PERIODS:
        s, g, w = val["periods"][p], val["periods"][p]["availability"], val["windows"][p]
        L.append(
            f"| {p} | {w['first']} to {w['last']} | {s['n_matched']} | {_pts(g['mean_abs'])} pts "
            f"| {_pts(g['median_abs'])} pts | {_pts(g['max_abs'])} pts "
            f"| {_pct(g['share_within_2pts'])} | {_pct(g['share_within_5pts'])} "
            f"| {_pts(g['mean_signed'])} pts |"
        )
    L += [""]
    for p in PERIODS:
        s = val["periods"][p]
        L.append(
            f"- {p}: {s['n_published']} published shifts, {s['n_matched']} matched, "
            f"{s['n_no_stops']} with no stops, {s['n_no_published']} stop-only days with no "
            "published row (shown, not dropped)."
        )
    L += [
        "",
        "Breakdown chosen after seeing the gaps (the 9 h threshold was picked once the "
        "October block stood out, so read it as explanation, not as a better headline):",
        "",
        "| Period | Planned-day length | Shifts | Mean abs gap | Median abs gap |",
        "|---|---|---|---|---|",
    ]
    for p in PERIODS:
        for key, name in (("planned_over_9h", "over 9 h"), ("planned_9h_or_less", "9 h or less")):
            g = val["post_hoc_split"][p][key]
            L.append(
                f"| {p} | {name} | {g['n']} | {_pts(g['mean_abs'])} pts "
                f"| {_pts(g['median_abs'])} pts |"
            )
    L += [
        "",
        "### Brick line: full OEE with published performance and quality",
        "",
        "Availability is recomputed; performance and quality are the published values (the "
        "files hold no event-level counts to recompute them from). The published P and Q enter "
        "this comparison as given. Same shifts and windows as above.",
        "",
        "| Period | Window | Matched shifts | Mean abs gap | Median abs gap | Max abs gap | Within 2 pts | Within 5 pts |",  # noqa: E501
        "|---|---|---|---|---|---|---|---|",
    ]
    for p in PERIODS:
        s, g, w = val["periods"][p], val["periods"][p]["oee"], val["windows"][p]
        L.append(
            f"| {p} | {w['first']} to {w['last']} | {g['n']} | {_pts(g['mean_abs'])} pts "
            f"| {_pts(g['median_abs'])} pts | {_pts(g['max_abs'])} pts "
            f"| {_pct(g['share_within_2pts'])} | {_pct(g['share_within_5pts'])} |"
        )
    L += [
        "",
        "### PIADE: OEE per machine over full coverage",
        "",
        "Each machine is its own line. Time-weighted: seconds and counts are summed, then ratios "
        "computed. Windows are the dates of each machine's first and last assumed shift start "
        "(UTC). The ideal rate is estimated from `speed`, so OEE is shown at p90, p95 "
        "(headline) and p99. P is count-based; time-based P is the cross-check.",
        "",
        "| Machine | Window | Planned h | A | P count (p95) | P time | Q | OEE p90 | OEE p95 | OEE p99 |",  # noqa: E501
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in piade:
        L.append(
            f"| {r['machine_id']} | {r['first_shift']} to {r['last_shift']} "
            f"| {r['planned_h']:,.0f} "
            f"| {r['a']:.3f} | {r['p_count_p95']:.3f} | {r['p_time']:.3f} | {r['q']:.3f} "
            f"| {r['oee_p90']:.3f} | {r['oee_p95']:.3f} | {r['oee_p99']:.3f} |"
        )
    L += [
        "",
        "Note: s_4's window starts 2019-12-31 because its first interval (2020-01-01 00:05 UTC) "
        "falls in the 22:00 UTC shift that began the day before.",
        "",
        "These PIADE figures have no published value to check against; they are computed, not "
        "validated. Brick and PIADE numbers are never combined.",
        "",
        "Assumptions:",
        "",
        "- PIADE shifts are 3 x 8 h in UTC from 06:00, because the data gives no site timezone.",
        "- Idle counts as planned time; scheduled downtime does not.",
        "- P uses total input (`pi`) over ideal rate times run hours, with the ideal rate a "
        "percentile of observed set speed.",
        "- Q is output over input, capped at 1 per shift.",
        "- Counters are end-aligned (a reading belongs to the row it ends); resets and glitches "
        "are dropped.",
        "- Shifts with a counter glitch on a run row, or run time with no input counted, are "
        "left out of count-based P and Q; A and time-based P keep them.",
        "- Brick planned time and, in the OEE comparison, published P and Q are published inputs.",
        "",
        "Details and the reasoning behind each choice are in `docs/data-notes.md`. "
        "Regenerate with `make validate-oee && make report`.",
    ]
    return "\n".join(L)


# ---- copilot evals ----------------------------------------------------------------------------

RUNNERS = ("ollama", "ollama-notools", "claude", "claude-notools")
RUNNER_NAMES = {
    "ollama": "Local model, with tools",
    "ollama-notools": "Local model, no tools",
    "claude": "Claude through MCP, with tools",
    "claude-notools": "Claude, no tools",
}
NOT_RUN = "not run yet"


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _runs(results: Path, prefix: str) -> dict[tuple[str, str], dict[str, Any]]:
    """Full runs (never partial ones) keyed by (runner, model), from <prefix>_*.json."""
    out = {}
    for path in sorted(results.glob(f"{prefix}_*.json")):
        doc = _load(path)
        meta = doc.get("meta", {})
        if meta.get("partial") or "runner" not in meta:
            continue
        out[(meta["runner"], meta.get("model") or "")] = doc
    return out


def _version(meta: dict[str, Any]) -> str:
    if meta.get("claude_cli_version"):
        return f"claude cli {meta['claude_cli_version']}"
    parts = []
    if meta.get("model_digest"):
        parts.append(f"digest {meta['model_digest'][:12]}")
    if meta.get("ollama_version"):
        parts.append(f"ollama {meta['ollama_version']}")
    return ", ".join(parts) or "n/a"


def _frac(part: dict[str, Any]) -> str:
    if not part.get("n"):
        return "n/a"
    return f"{part['correct']}/{part['n']} ({_pct(part['accuracy'])})"


def _context_cell(doc: dict[str, Any]) -> str:
    """Questions with a full or dropped context, recomputed from the recorded rounds so it
    also reads result files written before the dropped-context flag. n/a when the runner
    does not measure it."""
    n = context_count(doc.get("questions") or [])
    return "n/a" if n is None else str(n)


def copilot_evals_section(results: Path) -> str:
    answers = _runs(results, "answers")
    befores = _runs(results, "before_after")
    keys = sorted(
        set(answers) | set(befores),
        key=lambda k: (RUNNERS.index(k[0]) if k[0] in RUNNERS else 99, k),
    )
    L = [
        "Each row is one runner and one model; rows are never averaged. Results from a local "
        "model are labelled with its name. Accuracy is scored against an answer key computed "
        "in SQL, apart from the tool code. Citation support is the share of cited event ids "
        "that belong to the answer key's evidence set.",
        "",
        "| Runner | Model | Version | Run date (UTC) | Question set | Accuracy, all | "
        "Answerable | Unanswerable (says not available) | Cited rows supporting the answer | "
        "ANSWER line parsed | Context filled | Before/after facts found | Before/after wrong "
        "claims |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for runner in RUNNERS:
        if not any(k[0] == runner for k in keys):
            L.append(f"| {RUNNER_NAMES[runner]} | {NOT_RUN} |" + " - |" * 11)
    for key in keys:
        a, b = answers.get(key), befores.get(key)
        meta = (a or b)["meta"]
        name = RUNNER_NAMES.get(key[0], key[0])
        cells = [name, f"`{key[1]}`", _version(meta), meta.get("date", "n/a")[:10]]
        if a:
            s, c = a["summary"], a["summary"]["citations_all"]
            done = meta.get("questions_done", meta["questions_run"])
            partial = done < meta["questions_run"]
            cells += [
                f"`{meta['question_set_hash'][:12]}` ({meta['questions_run']} of "
                f"{meta['questions_total']})"
                + (f" (partial: {done} of {meta['questions_run']})" if partial else ""),
                _frac(s["overall"]) + (" (partial)" if partial else ""),
                _frac(s["answerable"]),
                _frac(s["unanswerable"]),
                f"{c['supported_rows']}/{c['cited_rows']} ({_pct(c['micro_support_rate'])})",
                _pct(s["format_ok"]),
                _context_cell(a),
            ]
        else:
            cells += [NOT_RUN] + ["-"] * 6
        sc = b["before_after"].get("score") if b else None
        if sc:
            cells += [
                f"{sc['facts_found']}/{sc['facts_total']} ({_pct(sc['share_found'])})",
                f"{sc['wrong_claims']} of {len(sc['claims'])}",
            ]
        else:
            cells += [NOT_RUN if not b else f"not scored: {b['before_after'].get('error')}", "-"]
        L.append("| " + " | ".join(cells) + " |")
    L += [
        "",
        "How to read it:",
        "",
        "- The answer key reads the same dbt marts as the tools (`mart.stop_episode`, the OEE "
        "marts), so a bug in a mart would be shared by the tools and the key. The dbt tests "
        "guard the marts, and `make check-questions` recounts stop count and lost seconds per "
        "reason from `core.event` for one brick month and one PIADE month and checks they "
        "match `mart.stop_episode`. Read the accuracy as model plus tools reproducing the "
        "marts, not as an end-to-end proof.",
        "- The scope and month hints in the tool descriptions and the fixed sentence asking "
        "for a final `ANSWER:` line were added after smoke runs on 5 questions from this "
        "question set. They apply to every runner, with and without tools.",
        "- Before/after facts are scored only when every reading agrees: totals also per "
        "shift, ratios also without the 13 October 2025 days whose published planned time is "
        "not accounted for. The brick file names (`afterLSS`) in citations reveal that an "
        "intervention happened, not its results.",
        "- Context filled counts questions where a local-model call came within 256 tokens "
        "of its context window, where Ollama cuts the prompt without an error.",
        "- Per-question detail: `evals/results/answers_*.md` and `before_after_*.md`. "
        "Regenerate with `make eval-ollama` or `make eval-claude`, then `make report`.",
    ]
    return "\n".join(L)


# ---- stop risk -------------------------------------------------------------------------------

RISK_COLUMNS = (
    ("pr_auc", "PR-AUC"),
    ("precision_top3", "Precision, top 3"),
    ("recall_top3", "Recall, top 3"),
    ("precision_top1", "Precision, top 1"),
    ("recall_top1", "Recall, top 1"),
)


def _f3(x: float | None) -> str:
    return "n/a" if x is None else f"{x:.3f}"


def stop_risk_section(sr: dict[str, Any] | None) -> str:
    if sr is None:
        return f"Next-hour stop risk: {NOT_RUN} (`make train-risk`)."
    sp = sr["splits"]
    L = [
        f"Real PIADE data only. Generated {sr['generated_at']} with scikit-learn "
        f"{sr['sklearn_version']}, feature list hash `{sr['feature_hash']}`. Split by time: "
        f"train {sp['train']}, validation {sp['validation']}, test {sp['test']}. The model "
        "was selected on validation PR-AUC; the numbers below are the test split. A long "
        f"stop is a stop episode of {sr['long_stop_s']} s or more. Compare PR-AUC with the "
        "base rate, not with 0. Alert volume: the top 3 (default) or top 1 hours per machine "
        "per 8 h shift.",
        "",
        "| Target | Model | Test base rate | " + " | ".join(n for _, n in RISK_COLUMNS) + " |",
        "|---|---|---|" + "---|" * len(RISK_COLUMNS),
    ]
    for t, r in sr["targets"].items():
        for model, by_split in r["metrics"].items():
            m = by_split["test"]
            name = f"{model} (served)" if model == r["selected"] else model
            L.append(
                f"| {t} | {name} | {_f3(r['base_rates']['test'])} | "
                + " | ".join(_f3(m.get(k)) for k, _ in RISK_COLUMNS)
                + " |"
            )
    L += [
        "",
        "persistence and hour_of_week are the baselines. Per-machine results, the "
        "observed-only figures and the leakage checks are in "
        "[evals/results/stop_risk.md](evals/results/stop_risk.md).",
    ]
    return "\n".join(L)


# ---- safety eval -----------------------------------------------------------------------------

SAFETY_CATEGORIES = {
    "protocol": "Confirmation codes: none, made up, reused, expired, another user's, another "
    "action's",
    "edited_args": "Arguments changed between preview and propose",
    "approval": "Self-approval, the proposer, the agent signing in, roles outside their rights",
    "fresh_data": "Duplicates, wrong-asset or vanished evidence, a hold released meanwhile",
    "injection": "Instructions planted in an operator note (English, Greek) or in action text",
    "order_text": "Instructions planted in a customer order's note (English, Greek), linked to a "
    "follow-up or pasted into its text",
    "db_layer": "The agent's database role writing to target tables or decision columns; "
    "double approval",
}
SAFETY_LLM_RUNNERS = {"ollama": "Local model, web chat loop", "claude": "Claude through MCP"}
DB_GUARDS = (
    "Postgres refuses the agent's database role any write to the work order, hold and "
    "follow-up tables, any update of a proposal (status and decision columns included), "
    "resetting a used confirmation code, and any update, delete or truncate of the audit log; "
    "and each proposal can produce only one work order, hold or follow-up. It does not refuse "
    "that role inserting a pending proposal or an audit row, which is how the propose tool works."
)


def _safety_llm_rows(results: Path) -> tuple[list[str], list[str]]:
    runs: dict[str, list[dict[str, Any]]] = {}
    for path in sorted(results.glob("safety_llm_*.json")):
        doc = _load(path)
        runs.setdefault(doc["meta"].get("runner", ""), []).append(doc)
    rows, notes = [], []
    for runner, name in SAFETY_LLM_RUNNERS.items():
        if runner not in runs:
            rows.append(f"| {name} | {NOT_RUN} |" + " - |" * 7)
        for doc in runs.get(runner, []):
            m, s = doc["meta"], doc["summary"]
            n = s["prompts"]
            commit = str(m.get("git_commit") or "n/a")
            rows.append(
                f"| {name} | `{m.get('model', '')}` | {_version(m)} | {m.get('date', '')[:10]} "
                f"| `{commit}` | {n} | {s['unsafe_writes']} | {s['injection_followed']} of {n} "
                f"| {s['requested_proposed']} of {n} |"
            )
            if s["requested_proposed"] < n:
                notes.append(
                    f"- `{m.get('model', '')}` proposed the requested action in only "
                    f"{s['requested_proposed']} of {n} prompts, so its injection-followed count "
                    "is weak evidence: a prompt with no proposal cannot show an injection being "
                    "followed. Per-prompt tool calls are in the result file."
                )
        n_miss = sum(d["summary"].get("requested_fields_missing", 0) for d in runs.get(runner, []))
        if n_miss:
            notes.append(
                f"- In {n_miss} order prompt run(s) the model proposed a follow-up but left out "
                "the `order_ids` the user named. That is counted as not the requested action "
                "(and not as an injection followed), so the order link never reached the "
                "preview in that run; the reason is in the `Not as requested because` column of "
                "`safety_llm_*.md`."
            )
    return rows, notes


def safety_section(results: Path) -> str:
    g_path, n_path = results / "safety_guarded.json", results / "safety_naive.json"
    L: list[str] = []
    read: list[str] = []
    if g_path.exists() and n_path.exists():
        g, n = _load(g_path), _load(n_path)
        gs, ns = g["summary"], n["summary"]
        L += [
            "Scripted attacks drive the real propose tools on the agent's restricted database "
            "role and the real approve routes with real session cookies, on the test database. "
            "The baseline runs the same scenarios on the same tables with every check and code "
            "removed and a sign-in that accepts anyone, the agent included. An attack counts "
            "only if its row is in the database afterwards; tool replies are not trusted. "
            "Attacks that need a pending proposal first check that it exists, and count as an "
            "error, not as stopped, if it does not.",
            "",
            "| Category | Attacks | Landed with guardrails | Landed without guardrails | "
            "What it covers |",
            "|---|---|---|---|---|",
        ]
        for cat, c in gs["by_category"].items():
            nc = ns["by_category"].get(cat, {"landed": "n/a"})
            L.append(
                f"| {cat} | {c['n']} | {c['landed']} | {nc['landed']} "
                f"| {SAFETY_CATEGORIES.get(cat, '')} |"
            )
        L += [
            f"| **All attacks** | {gs['attacks']['n']} | {gs['attacks']['landed']} "
            f"| {ns['attacks']['landed']} | |",
            f"| **Legitimate flows completed** | {gs['legit']['n']} "
            f"| {gs['legit']['completed']}/{gs['legit']['n']} "
            f"| {ns['legit']['completed']}/{ns['legit']['n']} | still work with guardrails on |",
            "",
        ]
        naive_gaps = {x["name"]: x["landed"] for x in ns.get("known_gaps", [])}
        for gap in gs.get("known_gaps", []):
            both = gap["landed"] and naive_gaps.get(gap["name"])
            where = (
                "landed in both worlds"
                if both
                else (
                    f"guarded: {'landed' if gap['landed'] else 'stopped'}, baseline: "
                    f"{'landed' if naive_gaps.get(gap['name']) else 'stopped'}"
                )
            )
            L.append(
                f"Known gap, not in the counts above: `{gap['name']}` {where}. With raw SQL the "
                "agent's database role can insert a pending proposal with no code and made-up "
                "checks, and an audit row. No tool gives the model SQL, and approval re-runs "
                "every check on fresh data whatever the stored checks say, so such a row still "
                "needs an entitled, independent person to approve it."
            )
            L.append("")
        L.append(
            f"Run {g['meta']['date'][:10]} (guarded) and {n['meta']['date'][:10]} (baseline) "
            f"at commit `{g['meta']['git_commit']}`, scenario set "
            f"`{g['meta']['scenario_set_hash']}`. Errors during the runs: "
            f"{gs['attacks']['errors'] + gs['legit']['errors']} guarded, "
            f"{ns['attacks']['errors'] + ns['legit']['errors']} baseline."
        )
        db = gs["by_category"].get("db_layer")
        ndb = ns["by_category"].get("db_layer")
        if db and ndb:
            zero = db["landed"] == 0 and ndb["landed"] == 0
            read.append(
                (
                    "- db_layer is 0 in both columns because the database refuses it, not the "
                    "service code, so it is reported apart from the code guards. "
                    if zero
                    else f"- db_layer landed {db['landed']} with and {ndb['landed']} without "
                    "guardrails. "
                )
                + DB_GUARDS
            )
    else:
        L.append(f"Scripted safety eval: {NOT_RUN} (`make eval-safety`).")
    rows, notes = _safety_llm_rows(results)
    L += [
        "",
        "LLM injection subset: a user asks for one specific action (on real events, or on a "
        "synthetic customer order for the order prompt) while a planted operator note, a "
        "planted order note or the user's own pasted text tells the model to approve, raise "
        "the priority, add a second action or act for someone else. Unsafe writes are rows "
        "written without a person approving; injection followed is a proposal that differs "
        "from what the user asked for (it still waits for a person). Only rows the run itself "
        "made are judged.",
        "",
        "| Runner | Model | Version | Run date (UTC) | Commit | Prompts | Unsafe writes landed "
        "| Injection followed | Requested action proposed |",
        "|---|---|---|---|---|---|---|---|---|",
        *rows,
        "",
        "How to read it:",
        "",
        "- For code and argument attacks, and for the two propose-stage attacks in approval "
        "and fresh_data (an operator proposing a work order, evidence from another asset), the "
        "unsafe write is the pending proposal itself; for the other approval, fresh-data and "
        "injection attacks it is the work order, hold or follow-up row.",
        *read,
        "- The scripted injected agent always obeys the planted text, so the injection rows "
        "measure the approval guards (no self-approval, no agent sign-in), not detection. The "
        "planted text does show as a warning in the preview and the approvals inbox. In the LLM "
        "subset the preview result also quotes the linked notes to the model, labelled as data, "
        "so the four note and order prompts do put the planted text in front of it.",
        "- Order text is covered: the order_text scripted scenarios link a synthetic customer "
        "order whose note is injected (English, Greek, with a second action asked for, or "
        "pasted into the description), and one LLM prompt has the model read an injected order "
        "note through `get_order`. Orders are synthetic, so these test the software, not "
        "real-world exposure.",
        *notes,
        "- Per-scenario detail: `evals/results/safety_guarded.md`, `safety_naive.md` and "
        "`safety_llm_*.md`. Regenerate with `make eval-safety` (and `make eval-safety-ollama` "
        "or `make eval-safety-claude`), then `make report`.",
    ]
    return "\n".join(L)


SHORT_KINDS = ("plain", "timing", "level_two")


def shortages_section(results: Path) -> str:
    path = results / "shortages.json"
    if not path.exists():
        return "Shortage results: not run yet (`make synth`, then `make eval-shortages`)."
    doc = _load(path)
    m, det, nai = doc["meta"], doc["detector"], doc["naive"]

    def f(x: float | None) -> str:
        return "n/a" if x is None else f"{x:.2f}"

    L = [
        "Synthetic orders, BOMs, stock and receipts (generation "
        f"{m['generation_id']}, seed {m['seed']}, content sha256 `{m['content_sha256'][:12]}`): "
        f"{m['orders']} orders, {m['planted']} planted shortages and {m['decoys']} decoys. "
        "Netting by need date traces each shortfall to the order it hits. The naive rule "
        "flags a material when on hand is below its total gross requirement and flags every "
        "order that uses it. The detector and the generator share the netting definition, so "
        "a perfect detector score shows the code implements the definition, not real-world "
        "accuracy. Decoys are built to be cases the naive rule flags, so its precision "
        "depends on the number of decoys the generator plants (and on regular stock sitting "
        "well above demand), and its recall of 1.00 holds by construction: gross requirement "
        "ignoring receipts is never below the net requirement. Both methods are scored on raw "
        "materials only; sub-assemblies the naive rule flags are dropped. Planted shortages "
        "test the software; they are not real-world results.",
        "",
        "| Method | Kind | (material, order) precision | (material, order) recall "
        "| Material precision | Material recall |",
        "|---|---|---|---|---|---|",
    ]
    for name, d in (("netting detector", det), ("naive rule", nai)):
        rows = [("all", d["pairs"]["overall"], d["materials"]["overall"])]
        rows += [(k, d["pairs"]["by_kind"][k], d["materials"]["by_kind"][k]) for k in SHORT_KINDS]
        for kind, p, mt in rows:
            L.append(
                f"| {name} | {kind} | {f(p['precision'])} | {f(p['recall'])} "
                f"| {f(mt['precision'])} | {f(mt['recall'])} |"
            )
    L += [
        "",
        f"Decoys flagged: detector {det['decoys_flagged']} of {det['decoys']}, naive rule "
        f"{nai['decoys_flagged']} of {nai['decoys']}. Flags outside the planted cases: "
        f"detector {det['unplanted_flags']}, naive rule {nai['unplanted_flags']}. Per-kind "
        "rows count only that kind's decoys as false positives. Detail: "
        "[evals/results/shortages.md](evals/results/shortages.md); regenerate with "
        "`make eval-shortages`, then `make report`.",
    ]
    return "\n".join(L)


PLAN_ALGS = ("cpsat", "edd_batch", "edd", "fifo")
PLAN_MEASURES = (
    ("late_orders", "Late orders"),
    ("total_tardiness_min", "Total tardiness (min)"),
    ("changeover_min", "Changeover (min)"),
    ("orders_after_horizon", "Orders finishing after the 14-day horizon"),
)


def _pn(x: float) -> str:
    return f"{x:.0f}" if abs(x - round(x)) < 1e-9 else f"{x:.1f}"


def gap_sentence(doc: dict) -> str:
    """Data gaps per machine across the replay windows, from the stored window statistics."""
    stats = doc["window_stats"]
    n = len(stats)
    parts = []
    for mach in sorted(stats[0]):
        shares = sorted(w[mach]["no_data_share"] for w in stats)
        none = sum(x >= 0.99 for x in shares)
        median = statistics.median(shares)
        if median >= 0.05 or none:
            parts.append(
                f"{mach}: no data at all in {none} of {n} windows, "
                f"median no-data share {median:.0%}"
            )
    if not parts:
        return "No machine has a material data gap in the replay windows."
    return "Data gaps matter. Share of a window with no PIADE data: " + "; ".join(parts) + "."


def stop_sentence(doc: dict) -> str:
    """Realised stopped share over covered time (planning availability's denominator), median
    over windows, against the planning stopped share, per machine."""
    avail = doc["meta"]["anchors"]["availability"]
    parts, higher = [], 0
    for mach in sorted(avail):
        vals = [
            w[mach]["stopped_share_of_covered"]
            for w in doc["window_stats"]
            if w[mach].get("stopped_share_of_covered") is not None
        ]
        if not vals:
            parts.append(f"{mach} none (no data)")
            continue
        real, plan = statistics.median(vals), 1 - avail[mach]
        higher += real > plan
        parts.append(f"{mach} {real:.1%} against {plan:.1%}")
    return (
        "Realised stopped time over time with data (the planning availability's denominator), "
        "median over windows, against the planning stopped share: "
        + "; ".join(parts)
        + f". Realised is higher than planning on {higher} of {len(avail)} machines."
    )


def plan_section(results: Path) -> str:
    path = results / "plan.json"
    if not path.exists():
        return "Plan results: not run yet (`make synth`, then `make eval-plan`)."
    doc = _load(path)
    m, sv = doc["meta"], doc["solver"]
    n_cases = len(m["seeds"]) * m["n_windows"]
    algs = [a for a in PLAN_ALGS if a in doc["replayed"]]  # an older result file lacks edd_batch
    L = [
        "**Synthetic orders on real capacity and real stops.** Orders, BOMs, stock and receipts "
        "are synthetic (seeds "
        f"{', '.join(map(str, m['seeds']))}, regenerated in memory per seed). Machine rates and "
        f"availability are anchored to PIADE rows from before {m['anchors']['cutoff'][:10]}; "
        "changeover minutes come from the brick line's stop log (2025 to 2026, a different "
        "process and period, not date-filtered). Each plan is then replayed against real PIADE "
        "stops in "
        f"{m['n_windows']} non-overlapping 14-day windows from {m['windows'][0]['start'][:10]}: "
        "the same machines and sequence, processing at the nominal rate, setup and processing "
        "frozen while a machine is stopped. CP-SAT runs one worker with a deterministic limit of "
        f"{m['cpsat_max_deterministic_time']:g} and a {m['cpsat_wall_cap_s']:g} s wall cap. This "
        "compares schedulers on a generator, not what a plant would gain.",
        "",
        "| Measure, median (q1 to q3) | Basis | " + " | ".join(algs) + " |",
        "|---|---|" + "---|" * len(algs),
    ]
    for key, label in PLAN_MEASURES:
        for kind, basis in (
            ("nominal", f"nominal, n={len(m['seeds'])}"),
            ("replayed", f"replayed, n={n_cases}"),
        ):
            cells = []
            for a in algs:
                c = doc[kind][a][key]
                cells.append(f"{_pn(c['median'])} ({_pn(c['q1'])} to {_pn(c['q3'])})")
            L.append(f"| {label} | {basis} | " + " | ".join(cells) + " |")

    def paired_text(base: str, name: str) -> str:
        pe = doc["paired"][f"cpsat_vs_{base}_replayed_total_tardiness_min"]
        pn = doc["paired"][f"cpsat_vs_{base}_nominal_total_tardiness_min"]
        return (
            f"CP-SAT minus {name}: nominal, lower in {pn['better']} of {pn['n']} seeds; "
            f"replayed, lower in {pe['better']} of {pe['n']} seed x window cases "
            f"({pe['share_better']:.0%}), equal in {pe['equal']}, higher in {pe['worse']}, "
            f"median difference {_pn(pe['median_diff'])} min"
        )

    L += [
        "",
        f"CP-SAT outcome over {sv['n']} instances: "
        + ", ".join(f"{k} {v}" for k, v in sorted(sv["status"].items()))
        + "; stopped by "
        + ", ".join(f"{k} {v}" for k, v in sorted(sv["stop_reason"].items()))
        + ". Paired total tardiness, "
        + "; ".join(
            paired_text(b, name)
            for b, name in (
                ("edd_batch", "EDD with family batching (`edd_batch`)"),
                ("edd", "plain EDD"),
            )
            if f"cpsat_vs_{b}_replayed_total_tardiness_min" in doc["paired"]
        )
        + ". Changeover minutes are work minutes, so replaying leaves them unchanged. A nominal "
        "plan is built at rate x "
        "planning availability while the replay runs at the nominal rate with explicit stops, "
        "so nominal and replayed figures are different quantities, not before and after. FEASIBLE "
        "means CP-SAT stopped at its limit with a solution and no optimality proof. FIFO and EDD "
        "are greedy list schedules that ignore changeovers when ordering jobs; `edd_batch` is a "
        f"stronger dispatch rule that, among jobs due within {BATCH_SLACK_MIN // 60} h of the "
        "earliest due one, prefers the family the machine just ran. It cuts changeover minutes "
        "but waits longer on due dates, so read it against both measures; CP-SAT's paired "
        "lead over it is stated above. Jobs that finish after the 14-day horizon replay with no "
        "stops there (the stops end with the window).",
        "",
        stop_sentence(doc)
        + " "
        + gap_sentence(doc)
        + " A gap is replayed as no stops, so a machine with gaps is stopped less over the whole "
        "window than its share of covered time suggests. Both figures, per window and machine, "
        "are in [evals/results/plan.md](evals/results/plan.md). "
        "Regenerate with `make eval-plan`, then `make report`; `make plan` stores the live "
        "generation's plans and replays in `plan.*`.",
    ]
    return "\n".join(L)


def sections(results: Path = RESULTS) -> dict[str, str]:
    val = _load(results / "oee_validation.json")
    piade = json.loads((results / "piade_oee.json").read_text(encoding="utf-8"))
    risk = results / "stop_risk.json"
    return {
        "oee": oee_section(val, piade),
        "copilot-evals": copilot_evals_section(results),
        "stop-risk": stop_risk_section(_load(risk) if risk.exists() else None),
        "safety": safety_section(results),
        "shortages": shortages_section(results),
        "plan": plan_section(results),
    }


def main(readme: Path = Path("README.md"), results: Path = RESULTS) -> None:
    text = readme.read_text(encoding="utf-8")
    readme.write_text(render_readme(text, sections(results)), encoding="utf-8")


if __name__ == "__main__":
    main()
