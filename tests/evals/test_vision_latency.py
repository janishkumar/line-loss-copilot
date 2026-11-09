import json

from evals import vision_latency as VL


def test_schedule_covers_every_block_each_round_and_is_seeded():
    subs = ["a", "b", "c"]
    plan = VL.schedule(subs, rounds=3, seed=0)
    assert len(plan) == 3 * 3 * 4
    for r in range(3):
        blocks = [(s, c) for rr, s, c in plan if rr == r]
        assert len(set(blocks)) == 12
    assert plan == VL.schedule(subs, rounds=3, seed=0)
    order = lambda r: [(s, c) for rr, s, c in plan if rr == r]  # noqa: E731
    assert order(0) != order(1)  # shuffled differently each round
    assert [rr for rr, _, _ in plan] == sorted(rr for rr, _, _ in plan)


def test_wait_quiet_returns_load_when_quiet_and_none_when_never():
    assert VL.wait_quiet(2.0, load_fn=lambda: (1.0, 0, 0), sleep=lambda s: None) == 1.0
    seq = iter([5.0, 4.0, 1.2])
    assert VL.wait_quiet(2.0, load_fn=lambda: (next(seq), 0, 0), sleep=lambda s: None) == 1.2
    assert VL.wait_quiet(2.0, load_fn=lambda: (9.0, 0, 0), sleep=lambda s: None, retries=3) is None


def test_aggregate_median_of_round_medians_and_spread():
    blocks = [
        {"p50_ms": 100.0, "p95_ms": 110.0, "load": 1.0},
        {"p50_ms": 80.0, "p95_ms": 90.0, "load": 1.5},
        {"p50_ms": 90.0, "p95_ms": 120.0, "load": 0.5},
    ]
    a = VL.aggregate(blocks)
    assert a["p50_ms"] == 90.0 and a["p50_min_ms"] == 80.0 and a["p50_max_ms"] == 100.0
    assert a["p95_ms"] == 110.0 and a["rounds"] == 3 and a["load_max"] == 1.5


def _doc():
    return {"subsets": {"a": {"model_sha256": "x"}}, "blocks": {}}


def test_run_blocks_resumes_and_keeps_provenance(tmp_path):
    calls = []

    def measure(sub, cfg):
        calls.append((sub, cfg))
        return {"p50_ms": 1.0, "p95_ms": 2.0}

    doc = _doc()
    plan = VL.schedule(["a"], rounds=2, seed=0)
    saved = []
    ok = VL.run_blocks(
        doc,
        plan[:4],
        measure,
        limit=2.0,
        commit="c1",
        today="d1",
        load_fn=lambda: (0.5, 0, 0),
        sleep=lambda s: None,
        save=lambda: saved.append(1),
    )
    assert ok and len(calls) == 4 and len(saved) == 4
    ok = VL.run_blocks(
        doc,
        plan,
        measure,
        limit=2.0,
        commit="c2",
        today="d2",
        load_fn=lambda: (0.7, 0, 0),
        sleep=lambda s: None,
        save=lambda: None,
    )
    assert ok and len(calls) == 8  # only the missing four ran
    recs = doc["blocks"]["a"]["onnx-1"]
    assert [(r["round"], r["commit"], r["date"], r["load"]) for r in recs] == [
        (0, "c1", "d1", 0.5),
        (1, "c2", "d2", 0.7),
    ]


def test_run_blocks_stops_and_flags_when_load_stays_high():
    doc = _doc()
    plan = VL.schedule(["a"], rounds=1, seed=0)
    ok = VL.run_blocks(
        doc,
        plan,
        lambda s, c: {"p50_ms": 1.0, "p95_ms": 1.0},
        limit=2.0,
        commit="c",
        today="d",
        load_fn=lambda: (9.0, 0, 0),
        sleep=lambda s: None,
        save=lambda: None,
        retries=2,
    )
    assert not ok and doc["incomplete"] is True and not doc["blocks"]


def test_markdown_reports_breakdown_and_provenance():
    blk = lambda p, r: {  # noqa: E731
        "round": r,
        "p50_ms": p,
        "p95_ms": p + 5,
        "load": 1.0,
        "date": "2026-11-09",
        "commit": "abc",
    }
    cfgs = ["onnx-1", "onnx-4", "torch-1", "torch-4"]
    doc = {
        "machine": {
            "cpu": "Test CPU",
            "cpu_count": 8,
            "onnxruntime": "1",
            "torch": "2",
            "opset": 17,
            "platform": "p",
        },
        "protocol": {"rounds": 2, "runs": 40, "warmup": 20, "load_limit": 2.0, "seed": 0},
        "subsets": {
            "cashew": {
                "model_mb": 172.9,
                "bank_mb": 67.1,
                "backbone_mb": 105.8,
                "parity": {"max_rel_score_diff": 1e-6, "max_abs_map_diff": 1e-5},
                "preprocess": {"p50_ms": 10.0, "p95_ms": 11.0},
                "date": "2026-11-09",
                "commit": "abc",
                "load": 1.0,
            }
        },
        "blocks": {"cashew": {c: [blk(100.0, 0), blk(90.0, 1)] for c in cfgs}},
    }
    out = VL.markdown(doc)
    assert "67.1" in out and "105.8" in out and "not demonstrated" in out.lower()
    assert "Test CPU" in out and "abc" in out and "95.0" in out
    json.dumps(doc)
