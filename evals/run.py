"""Run the answer, citation and before/after evals through one runner.

    python -m evals.run --runner ollama|ollama-notools|claude|claude-notools
                        [--limit N] [--ids a,b] [--model M] [--no-before-after]

A full run writes evals/results/answers_<runner>_<model-slug>.{json,md} and
before_after_<runner>_<model-slug>.{json,md}. A run with --limit or --ids writes the same
files under evals/results/partial/ (not committed), so a smoke test never replaces a full
result."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from collections.abc import Callable
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from evals import before_after, citations
from evals.questions import Question, build_questions, question_set_hash
from evals.runners import Reply
from evals.score import answer_line, score
from evals.truth import NOT_AVAILABLE, before_after_facts, compute

RESULTS = Path(__file__).resolve().parent / "results"
RUNNERS = ("ollama", "ollama-notools", "claude", "claude-notools")
DEFAULT_TIMEOUT_S = 600.0  # per model call (Ollama) or per question (Claude)


def slug(model: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", model.lower()).strip("-")


def select(qs: list[Question], limit: int | None, ids: list[str] | None) -> list[Question]:
    if ids:
        want = set(ids)
        unknown = want - {q.id for q in qs}
        if unknown:
            raise SystemExit(f"unknown question ids: {', '.join(sorted(unknown))}")
        qs = [q for q in qs if q.id in want]
    return qs[:limit] if limit else qs


def display(q: Question, expected: Any) -> str:
    if q.kind == "na":
        return NOT_AVAILABLE
    if q.unit == "ratio":
        return f"{100 * expected:.2f}%"
    if q.unit == "pp":
        return f"{100 * expected:+.2f} pp"
    if q.unit == "s_as_h":
        return f"{expected / 3600:.3f} h"
    if q.unit == "s_as_min":
        return f"{expected / 60:.2f} min"
    if q.unit == "count":
        return f"{expected:g}"
    return str(expected)


def _record(q: Question) -> dict[str, Any]:
    return {
        "id": q.id,
        "template": q.template,
        "kind": q.kind,
        "question": q.text,
        "expected": None,
        "expected_display": None,
        "answer": "",
        "extracted": None,
        "parsed_value": None,
        "correct": False,
        "format_ok": False,
        "cited_ids": [],
        "supported_ids": [],
        "unsupported_ids": [],
        "evidence_event_count": 0,
        "tool_calls": [],
        "rounds": None,
        "latency_s": 0.0,
        "error": None,
        "retries": 0,
    }


def evaluate_one(runner: Any, conn: Any, q: Question) -> dict[str, Any]:
    """One question, never raising: a failure in the answer key, the runner or scoring is
    recorded in `error` and the answer counts as wrong."""
    rec = _record(q)
    stage = "truth"
    try:
        truth = compute(conn, q.expected_fn, q.params)
        rec["expected"] = truth.expected
        rec["expected_display"] = display(q, truth.expected)
        rec["evidence_event_count"] = len(truth.evidence_event_ids)
        stage = "runner"
        reply = runner.ask(q.text)
        rec.update(
            answer=reply.answer,
            tool_calls=reply.tool_calls,
            rounds=reply.rounds,
            latency_s=round(reply.latency_s, 2),
            error=reply.error,
            retries=reply.retries,
            format_ok=answer_line(reply.answer) is not None,
        )
        stage = "scoring"
        s = score(
            reply.answer,
            q.kind,
            truth.expected,
            q.unit,
            q.tolerance,
            truth.detail.get("alternatives"),
        )
        cc = citations.check(reply.answer, truth.evidence_event_ids)
        rec.update(
            extracted=s.extracted,
            parsed_value=s.value,
            correct=s.correct,
            cited_ids=cc.cited,
            supported_ids=cc.supported,
            unsupported_ids=cc.unsupported,
        )
    except Exception as e:  # recorded, never fatal to the run
        rec["error"] = f"{stage}: {type(e).__name__}: {e}"
        rec["correct"] = False
    return rec


def evaluate(
    runner: Any,
    conn: Any,
    qs: list[Question],
    on_record: Callable[[list[dict[str, Any]]], None] | None = None,
) -> list[dict[str, Any]]:
    """Every question in order; `on_record` gets the records so far after each one."""
    out: list[dict[str, Any]] = []
    for i, q in enumerate(qs, 1):
        rec = evaluate_one(runner, conn, q)
        out.append(rec)
        mark = "ok " if rec["correct"] else ("ERR" if rec["error"] else "BAD")
        print(f"[{i}/{len(qs)}] {mark} {q.id} ({rec['latency_s']:.0f} s)", file=sys.stderr)
        if on_record:
            on_record(out)
    return out


def summarize(records: list[dict[str, Any]]) -> dict[str, Any]:
    def acc(rs: list[dict]) -> dict[str, Any]:
        n = len(rs)
        c = sum(r["correct"] for r in rs)
        return {"n": n, "correct": c, "accuracy": c / n if n else None}

    by_kind: dict[str, list] = defaultdict(list)
    by_tpl: dict[str, list] = defaultdict(list)
    for r in records:
        by_kind[r["kind"]].append(r)
        by_tpl[r["template"]].append(r)

    def cc(rs: list[dict]) -> dict[str, Any]:
        return citations.summarize(
            [citations.CitationCheck(r["cited_ids"], r["supported_ids"]) for r in rs]
        )

    answerable = [r for r in records if r["kind"] != "na"]
    return {
        "overall": acc(records),
        "answerable": acc(answerable),
        "unanswerable": acc(by_kind.get("na", [])),
        "by_kind": {k: acc(v) for k, v in sorted(by_kind.items())},
        "by_template": {k: acc(v) for k, v in by_tpl.items()},
        "citations_all": cc(records),
        "citations_answerable": cc(answerable),
        "format_ok": (sum(r["format_ok"] for r in records) / len(records)) if records else None,
        "errors": sum(1 for r in records if r["error"]),
        "median_latency_s": sorted(r["latency_s"] for r in records)[len(records) // 2]
        if records
        else None,
    }


def run_before_after(runner: Any, conn: Any) -> dict[str, Any]:
    truth = before_after_facts(conn)
    try:
        reply = runner.ask(before_after.PROMPT)
    except Exception as e:  # recorded, never fatal
        reply = Reply(answer="", latency_s=0.0, error=f"runner: {type(e).__name__}: {e}")
    claims = before_after.parse_claims(reply.answer)
    return {
        "prompt": before_after.PROMPT,
        "answer": reply.answer,
        "latency_s": round(reply.latency_s, 2),
        "tool_calls": reply.tool_calls,
        "error": reply.error,
        "retries": reply.retries,
        "truth": truth,
        "score": before_after.score_claims(claims, truth),
        "caveats": before_after.CAVEATS,
    }


def _pct(x: float | None) -> str:
    return "n/a" if x is None else f"{100 * x:.1f}%"


def answers_markdown(doc: dict[str, Any]) -> str:
    m, s = doc["meta"], doc["summary"]
    c = s["citations_all"]
    lines = [
        f"# Answer eval: {m['runner']} / {m['model']}",
        "",
        f"- Model: `{m['model']}` (digest/version: {m.get('model_digest') or 'n/a'}; "
        f"ollama {m.get('ollama_version') or 'n/a'}; claude cli "
        f"{m.get('claude_cli_version') or 'n/a'})",
        f"- Date (UTC): {m['date']}",
        f"- Question set hash: `{m['question_set_hash']}` ({m['questions_run']} of "
        f"{m['questions_total']} questions)",
        "",
        "| Measure | Value |",
        "|---|---|",
        f"| Accuracy, all | {s['overall']['correct']}/{s['overall']['n']} "
        f"({_pct(s['overall']['accuracy'])}) |",
        f"| Accuracy, answerable | {s['answerable']['correct']}/{s['answerable']['n']} "
        f"({_pct(s['answerable']['accuracy'])}) |",
        f"| Accuracy, unanswerable (says not available) | {s['unanswerable']['correct']}/"
        f"{s['unanswerable']['n']} ({_pct(s['unanswerable']['accuracy'])}) |",
        f"| Cited rows that support the answer (micro) | {c['supported_rows']}/"
        f"{c['cited_rows']} ({_pct(c['micro_support_rate'])}) |",
        f"| Answers fully supported by their citations | {_pct(c['share_fully_supported'])} |",
        f"| Answers with no citations | {_pct(c['share_no_citations'])} |",
        f"| Answers with a parseable ANSWER line (format_ok) | {_pct(s['format_ok'])} |",
        f"| Errors (answer key, runner or scoring) | {s['errors']} |",
        "",
        "| Template | Correct |",
        "|---|---|",
    ]
    lines += [f"| {k} | {v['correct']}/{v['n']} |" for k, v in s["by_template"].items()]
    lines += [
        "",
        "| Id | Expected | Extracted | Correct | Cited / supported | Latency s |",
        "|---|---|---|---|---|---|",
    ]
    for r in doc["questions"]:
        ext = (r["extracted"] or "").replace("|", "/")[:60]
        lines.append(
            f"| {r['id']} | {r['expected_display']} | {ext} | {'yes' if r['correct'] else 'no'} "
            f"| {len(r['cited_ids'])} / {len(r['supported_ids'])} | {r['latency_s']} |"
        )
    return "\n".join(lines) + "\n"


def before_after_markdown(doc: dict[str, Any]) -> str:
    m, ba = doc["meta"], doc["before_after"]
    sc = ba["score"]
    lines = [
        f"# Before/after eval: {m['runner']} / {m['model']}",
        "",
        f"- Date (UTC): {m['date']}",
        f"- Facts found (right direction): {sc['facts_found']}/{sc['facts_total']} "
        f"({_pct(sc['share_found'])})",
        f"- Wrong claims: {sc['wrong_claims']} of {len(sc['claims'])} "
        f"(neutral, on flat or ambiguous metrics: {sc['neutral_claims']})",
        "",
        "| Fact | Before | After | Readings | Status | Found |",
        "|---|---|---|---|---|---|",
    ]
    for f in ba["truth"]["facts"]:
        readings = ", ".join(f"{k}: {v}" for k, v in f["readings"].items())
        found = "yes" if f["metric"] in sc["found"] else "no"
        lines.append(
            f"| {f['metric']} | {f['before']:.4g} | {f['after']:.4g} | {readings} | "
            f"{f['status']} | {found if f['status'] == 'scored' else '-'} |"
        )
    lines += ["", "Caveats:", ""] + [f"- {c}" for c in ba["caveats"]]
    return "\n".join(lines) + "\n"


def make_runner(
    name: str, model: str | None, conn: Any, db_url: str, timeout_s: float = DEFAULT_TIMEOUT_S
) -> Any:
    if name.startswith("ollama"):
        from evals.runners.ollama import OllamaRunner
        from linecopilot.chat.ollama import OllamaClient
        from linecopilot.config import get_settings

        st = get_settings()
        client = OllamaClient(st.ollama_url, model or st.chat_model, timeout=timeout_s)
        return OllamaRunner(conn, client, tools_enabled=name == "ollama")
    from evals.runners.claude import ClaudeRunner

    return ClaudeRunner(db_url, tools_enabled=name == "claude", model=model, timeout_s=timeout_s)


def write(doc: dict[str, Any], stem: str, md: str, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{stem}.json"
    path.write_text(json.dumps(doc, indent=2, ensure_ascii=False, default=str) + "\n")
    (out_dir / f"{stem}.md").write_text(md)
    return path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Run the answer and before/after evals.")
    ap.add_argument("--runner", required=True, choices=RUNNERS)
    ap.add_argument("--limit", type=int)
    ap.add_argument("--ids", help="comma-separated question ids")
    ap.add_argument("--model", help="model name (default: config chat_model / Claude default)")
    ap.add_argument("--no-before-after", action="store_true")
    ap.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT_S,
        help="seconds per Ollama call (one retry on timeout) or per Claude question",
    )
    args = ap.parse_args(argv)

    import psycopg

    from linecopilot.config import get_settings

    db_url = get_settings().database_url
    all_qs = build_questions()
    qs = select(all_qs, args.limit, args.ids.split(",") if args.ids else None)
    partial = bool(args.limit or args.ids)
    out_dir = RESULTS / "partial" if partial else RESULTS
    with psycopg.connect(db_url, autocommit=True) as conn:
        runner = make_runner(args.runner, args.model, conn, db_url, args.timeout)
        meta = {
            "runner": runner.name,
            **runner.meta(),
            "date": datetime.now(UTC).isoformat(timespec="seconds"),
            "question_set_hash": question_set_hash(all_qs),
            "questions_total": len(all_qs),
            "questions_run": len(qs),
            "partial": partial,
        }
        written: list[Path] = []

        def save(records: list[dict[str, Any]]) -> dict[str, Any]:
            # Written after every question, so a long run that dies keeps what it has. The
            # file name follows the model id, which a Claude run learns from its first reply.
            meta["model"] = runner.model
            if hasattr(runner, "models_seen"):  # Claude: every model in the usage blocks
                meta["models_seen"] = sorted(runner.models_seen)
            meta["questions_done"] = len(records)
            meta["retries_total"] = sum(r["retries"] for r in records)
            doc = {
                "meta": meta,
                "summary": summarize(records),
                "questions": records,
                "question_defs": [asdict(q) for q in qs],
            }
            path = write(doc, f"answers_{stem()}", answers_markdown(doc), out_dir)
            for old in [w for w in written if w != path]:
                old.unlink(missing_ok=True)
                old.with_suffix(".md").unlink(missing_ok=True)
                written.remove(old)
            if path not in written:
                written.append(path)
            return doc

        def stem() -> str:
            return f"{runner.name}_{slug(runner.model)}"

        records = evaluate(runner, conn, qs, on_record=save)
        doc = save(records)
        print(f"wrote {written[-1]}", file=sys.stderr)
        if not args.no_before_after:
            ba_doc = {"meta": meta, "before_after": run_before_after(runner, conn)}
            path = write(ba_doc, f"before_after_{stem()}", before_after_markdown(ba_doc), out_dir)
            print(f"wrote {path}", file=sys.stderr)
    print(json.dumps(doc["summary"]["overall"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
