"""run.py end to end with a scripted runner and a stubbed answer key (no db, no model)."""

import json

import pytest

from evals import run
from evals.questions import build_questions
from evals.runners import ANSWER_SUFFIX, Reply, build_prompt
from evals.truth import NOT_AVAILABLE, Truth


class ScriptedRunner:
    name = "fake"
    model = "fake:1b"

    def __init__(self, answers: dict[str, str]):
        self.answers = answers

    def meta(self):
        return {"model": self.model, "model_digest": "d1", "ollama_version": "0.0"}

    def ask(self, prompt: str) -> Reply:
        self.prompts = [*getattr(self, "prompts", []), prompt]
        key = prompt.removesuffix("\n\n" + ANSWER_SUFFIX)
        return Reply(answer=self.answers.get(key, "no idea"), latency_s=1.5)


def test_context_full_is_recorded_and_counted(monkeypatch):
    q = build_questions()[0]
    monkeypatch.setattr(run, "compute", lambda conn, fn, params: Truth(0.5))
    detail = [{"prompt_eval_count": 16200, "eval_count": 9, "context_full": True}]

    class Full(ScriptedRunner):
        def ask(self, prompt):
            return Reply(
                answer="ANSWER: 50%", latency_s=1.0, rounds_detail=detail, context_full=True
            )

    rec = run.evaluate_one(Full({}), None, q)
    assert rec["rounds_detail"] == detail and rec["context_full"] is True
    assert run.summarize([rec, run.evaluate_one(ScriptedRunner({}), None, q)])["context_full"] == 1


def test_summary_counts_dropped_context_from_rounds_detail(monkeypatch):
    q = build_questions()[0]
    monkeypatch.setattr(run, "compute", lambda conn, fn, params: Truth(0.5))
    detail = [
        {"prompt_eval_count": 9000, "eval_count": 9, "context_full": False},
        {"prompt_eval_count": 7000, "eval_count": 9, "context_full": False},
    ]

    class Dropped(ScriptedRunner):
        def ask(self, prompt):
            return Reply(
                answer="ANSWER: 50%", latency_s=1.0, rounds_detail=detail, context_full=False
            )

    rec = run.evaluate_one(Dropped({}), None, q)
    assert rec["context_full"] is False
    assert run.summarize([rec])["context_full"] == 1
    assert "| 1 |" in run.answers_markdown(
        {
            "meta": {
                "runner": "x",
                "model": "m",
                "date": "d",
                "question_set_hash": "h",
                "questions_run": 1,
                "questions_total": 1,
            },
            "summary": run.summarize([rec]),
            "questions": [rec],
        }
    )


def test_evaluate_summary_and_markdown(monkeypatch, tmp_path):
    qs = build_questions()
    pick = [qs[0], next(q for q in qs if q.template == "top_reason"), qs[-1]]
    key = {
        pick[0].id: Truth(0.5, frozenset({1, 2})),
        pick[1].id: Truth("A_065", frozenset({3}), {"alternatives": ["A_066"]}),
        pick[2].id: Truth(NOT_AVAILABLE),
    }
    by_params = {json.dumps(q.params, sort_keys=True) + q.expected_fn: q.id for q in pick}

    def fake_compute(conn, fn, params):
        return key[by_params[json.dumps(params, sort_keys=True) + fn]]

    monkeypatch.setattr(run, "compute", fake_compute)
    runner = ScriptedRunner(
        {
            pick[0].text: "OEE [event:1] [event:9]\nANSWER: 50.2%",
            pick[1].text: "Top [event:3]\nANSWER: A_066",
            pick[2].text: "ANSWER: NOT_AVAILABLE",
        }
    )
    records = run.evaluate(runner, None, pick)
    assert runner.prompts == [build_prompt(q.text) for q in pick]
    assert [r["correct"] for r in records] == [True, False, True]
    assert records[0]["supported_ids"] == [1] and records[0]["unsupported_ids"] == [9]
    s = run.summarize(records)
    assert s["overall"] == {"n": 3, "correct": 2, "accuracy": 2 / 3}
    assert s["unanswerable"]["accuracy"] == 1.0
    assert s["format_ok"] == 1.0 and all(r["format_ok"] for r in records)
    assert s["citations_all"]["micro_support_rate"] == 2 / 3
    assert s["citations_answerable"]["share_fully_supported"] == 1 / 2
    assert s["context_full"] is None and records[0]["rounds_detail"] == []
    assert records[0]["context_full"] is None

    meta = {
        "runner": "fake",
        "model": "fake:1b",
        "date": "2026-11-07T00:00:00+00:00",
        "question_set_hash": "h",
        "questions_total": 70,
        "questions_run": 3,
    }
    doc = {"meta": meta, "summary": s, "questions": records}
    md = run.answers_markdown(doc)
    assert "fake:1b" in md and "2/3" in md and pick[0].id in md
    assert "filled the context (Ollama) | n/a |" in md
    path = run.write(doc, "answers_fake_x", md, tmp_path)
    assert json.loads(path.read_text())["summary"]["overall"]["correct"] == 2


def test_before_after_run_and_markdown(monkeypatch):
    truth = {
        "before_window": ["a", "b"],
        "after_window": ["c", "d"],
        "shifts": {"before": 2, "after": 2},
        "facts": [
            {
                "metric": "availability",
                "kind": "ratio",
                "before": 0.7,
                "after": 0.6,
                "delta": -0.1,
                "readings": {"value": "down"},
                "status": "scored",
                "direction": "down",
            },
            {
                "metric": "reason:FAILURE",
                "kind": "total",
                "before": 10.0,
                "after": 5.0,
                "delta": -5.0,
                "readings": {"total": "down", "per_shift": "down"},
                "status": "scored",
                "direction": "down",
            },
            {
                "metric": "mttr",
                "kind": "mean",
                "before": 10.0,
                "after": 10.1,
                "delta": 0.1,
                "readings": {"value": "flat"},
                "status": "flat",
                "direction": None,
            },
        ],
        "status": {"availability": "down", "reason:FAILURE": "down", "mttr": "flat"},
    }
    monkeypatch.setattr(run, "before_after_facts", lambda conn: truth)
    answer = (
        'Text\n```json\n[{"metric": "availability", "direction": "down", "value": -0.1},'
        ' {"metric": "mttr", "direction": "down", "value": null},'
        ' {"metric": "energy", "direction": "up"}]\n```\nANSWER: availability fell'
    )
    runner = ScriptedRunner({run.before_after.PROMPT: answer})
    ba = run.run_before_after(runner, None)
    assert runner.prompts == [run.before_after.PROMPT]  # no ANSWER suffix here
    sc = ba["score"]
    assert sc["facts_found"] == 1 and sc["missed"] == ["reason:FAILURE"]
    assert sc["wrong_claims"] == 1 and sc["neutral_claims"] == 1
    md = run.before_after_markdown(
        {"meta": {"runner": "fake", "model": "m", "date": "d"}, "before_after": ba}
    )
    assert "1/2" in md and "Caveats" in md


def test_helpers():
    assert run.slug("qwen2.5:7b-instruct") == "qwen2-5-7b-instruct"
    qs = build_questions()
    assert [q.id for q in run.select(qs, 2, None)] == [qs[0].id, qs[1].id]
    assert [q.id for q in run.select(qs, None, ["na_01"])] == ["na_01"]
    with pytest.raises(SystemExit):
        run.select(qs, None, ["nope"])
    q = qs[0]
    assert run.display(q, 0.5) == "50.00%"


class Boom(ScriptedRunner):
    def ask(self, prompt):
        raise RuntimeError("model went away")


def test_errors_are_recorded_per_question(monkeypatch):
    qs = build_questions()[:2]

    def compute(conn, fn, params):
        if params == qs[0].params:
            raise ValueError("no truth")
        return Truth(0.5, frozenset())

    monkeypatch.setattr(run, "compute", compute)
    seen = []
    records = run.evaluate(Boom({}), None, qs, on_record=lambda rs: seen.append(len(rs)))
    assert seen == [1, 2]
    assert records[0]["error"].startswith("truth: ValueError")
    assert records[1]["error"].startswith("runner: RuntimeError")
    assert not any(r["correct"] for r in records)
    s = run.summarize(records)
    assert s["errors"] == 2 and s["format_ok"] == 0


class Stopped(ScriptedRunner):
    def ask(self, prompt):
        return Reply(answer="x\nANSWER: 0.5", latency_s=1.0, error="budget")


def test_loop_cutoff_counts_wrong_and_is_reported(monkeypatch):
    q = build_questions()[0]
    monkeypatch.setattr(run, "compute", lambda conn, fn, params: Truth(0.005, frozenset()))
    rec = run.evaluate_one(Stopped({}), None, q)
    assert rec["error"] == "budget" and rec["correct"] is False
    s = run.summarize([rec])
    assert s["stopped_on_budget"] == 1 and s["stopped_on_rounds"] == 0


def test_before_after_truth_failure_is_recorded(monkeypatch):
    def boom(conn):
        raise RuntimeError("db down")

    monkeypatch.setattr(run, "before_after_facts", boom)
    ba = run.run_before_after(ScriptedRunner({}), None)
    assert ba["error"].startswith("truth: RuntimeError") and ba["score"] is None
    md = run.before_after_markdown(
        {"meta": {"runner": "r", "model": "m", "date": "d"}, "before_after": ba}
    )
    assert "Not scored" in md
