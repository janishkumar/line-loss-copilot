"""Render README sections from evals/results/*.json. `make report` runs this.

Sections: `oee` (stage 1 validation), `copilot-evals` (answer, citation and before/after
evals, one row per runner and model, never averaged) and `stop-risk` (next-hour stop-risk
models on the test split). A result file that does not exist yet renders as "not run yet"."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

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
            cells += [
                f"`{meta['question_set_hash'][:12]}` ({meta['questions_run']} of "
                f"{meta['questions_total']})",
                _frac(s["overall"]),
                _frac(s["answerable"]),
                _frac(s["unanswerable"]),
                f"{c['supported_rows']}/{c['cited_rows']} ({_pct(c['micro_support_rate'])})",
                _pct(s["format_ok"]),
                str(s["context_full"]) if "context_full" in s else "not recorded",
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


def sections(results: Path = RESULTS) -> dict[str, str]:
    val = _load(results / "oee_validation.json")
    piade = json.loads((results / "piade_oee.json").read_text(encoding="utf-8"))
    risk = results / "stop_risk.json"
    return {
        "oee": oee_section(val, piade),
        "copilot-evals": copilot_evals_section(results),
        "stop-risk": stop_risk_section(_load(risk) if risk.exists() else None),
    }


def main(readme: Path = Path("README.md"), results: Path = RESULTS) -> None:
    text = readme.read_text(encoding="utf-8")
    readme.write_text(render_readme(text, sections(results)), encoding="utf-8")


if __name__ == "__main__":
    main()
