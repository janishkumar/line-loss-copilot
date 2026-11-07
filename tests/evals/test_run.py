"""run.py end to end with a scripted runner and a stubbed answer key (no db, no model)."""

import json

import pytest

from evals import run
from evals.questions import build_questions
from evals.runners import Reply
from evals.truth import NOT_AVAILABLE, Truth


class ScriptedRunner:
    name = "fake"
    model = "fake:1b"

    def __init__(self, answers: dict[str, str]):
        self.answers = answers

    def meta(self):
        return {"model": self.model, "model_digest": "d1", "ollama_version": "0.0"}

    def ask(self, prompt: str) -> Reply:
        return Reply(answer=self.answers.get(prompt, "no idea"), latency_s=1.5)


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
    assert [r["correct"] for r in records] == [True, False, True]
    assert records[0]["supported_ids"] == [1] and records[0]["unsupported_ids"] == [9]
    s = run.summarize(records)
    assert s["overall"] == {"n": 3, "correct": 2, "accuracy": 2 / 3}
    assert s["unanswerable"]["accuracy"] == 1.0
    assert s["citations_all"]["micro_support_rate"] == 2 / 3
    assert s["citations_answerable"]["share_fully_supported"] == 1 / 2

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
                "before": 0.7,
                "after": 0.6,
                "delta": -0.1,
                "direction": "down",
            },
            {
                "metric": "reason:FAILURE",
                "before": 10.0,
                "after": 5.0,
                "delta": -5.0,
                "direction": "down",
            },
        ],
        "directions": {"availability": "down", "reason:FAILURE": "down", "mttr": "up"},
    }
    monkeypatch.setattr(run, "before_after_facts", lambda conn: truth)
    answer = (
        'Text\n```json\n[{"metric": "availability", "direction": "down", "value": -0.1},'
        ' {"metric": "mttr", "direction": "down", "value": null},'
        ' {"metric": "energy", "direction": "up"}]\n```\nANSWER: availability fell'
    )
    runner = ScriptedRunner({run.before_after.PROMPT: answer})
    ba = run.run_before_after(runner, None)
    sc = ba["score"]
    assert sc["facts_found"] == 1 and sc["missed"] == ["reason:FAILURE"]
    assert sc["wrong_claims"] == 2
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
