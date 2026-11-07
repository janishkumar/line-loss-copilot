"""Scoring maths of the shortage eval on a fake truth, and the db run."""

import pytest

from evals import shortages as ev

TRUTH = [
    {"material_id": "M1", "order_id": "O1", "kind": "plain", "decoy": False},
    {"material_id": "M2", "order_id": "O2", "kind": "timing", "decoy": False},
    {"material_id": "M3", "order_id": "O3", "kind": "timing", "decoy": True},
    {"material_id": "M4", "order_id": "O4", "kind": "level_two", "decoy": False},
    {"material_id": "M5", "order_id": "O5", "kind": "level_two", "decoy": True},
]


def test_perfect_prediction():
    s = ev.score({("M1", "O1"), ("M2", "O2"), ("M4", "O4")}, TRUTH)
    assert s["pairs"]["overall"] == {
        "tp": 3, "fp": 0, "fn": 0, "precision": 1.0, "recall": 1.0
    }  # fmt: skip
    assert s["materials"]["overall"]["precision"] == 1.0
    assert s["pairs"]["by_kind"]["timing"]["recall"] == 1.0
    assert s["unplanted_flags"] == 0


def test_decoys_and_extras_are_false_positives():
    pred = {("M1", "O1"), ("M3", "O3"), ("M5", "O5"), ("M9", "O9")}
    s = ev.score(pred, TRUTH)
    o = s["pairs"]["overall"]
    assert (o["tp"], o["fp"], o["fn"]) == (1, 3, 2)
    assert o["precision"] == pytest.approx(0.25) and o["recall"] == pytest.approx(1 / 3)
    assert s["unplanted_flags"] == 1
    t = s["pairs"]["by_kind"]["timing"]
    assert (t["tp"], t["fp"], t["fn"]) == (0, 1, 1)  # the timing decoy is a timing false positive
    assert t["precision"] == 0.0 and t["recall"] == 0.0
    l2 = s["pairs"]["by_kind"]["level_two"]
    assert (l2["tp"], l2["fp"], l2["fn"]) == (0, 1, 1)
    p = s["pairs"]["by_kind"]["plain"]
    assert (p["tp"], p["fp"], p["fn"]) == (1, 0, 0)


def test_material_level_scoring():
    pred = {("M1", "O1"), ("M1", "OX"), ("M3", "O3")}
    s = ev.score(pred, TRUTH)
    m = s["materials"]["overall"]
    assert (m["tp"], m["fp"], m["fn"]) == (1, 1, 2)


def test_undefined_precision_is_none():
    s = ev.score(set(), TRUTH)
    assert s["pairs"]["overall"]["precision"] is None
    assert s["pairs"]["overall"]["recall"] == 0.0


def test_naive_scored_on_raw_materials_only():
    kinds = {"M1": "raw", "SA": "subassembly"}
    flagged = [("M1", "O1"), ("SA", "O1")]
    assert ev.raw_only(flagged, kinds) == {("M1", "O1")}


@pytest.mark.db
def test_eval_on_the_database_detector_perfect_naive_fooled(built):
    from linecopilot import schemas
    from linecopilot.synth.anchors import load_anchors
    from linecopilot.synth.generate import generate, write

    schemas.apply(built)
    a = load_anchors(built)
    write(built, generate(a, 7), a, 7)
    doc = ev.run(built)
    d, n = doc["detector"], doc["naive"]
    assert d["pairs"]["overall"]["precision"] == 1.0 and d["pairs"]["overall"]["recall"] == 1.0
    assert d["decoys_flagged"] == 0 and d["unplanted_flags"] == 0
    assert n["decoys_flagged"] == n["decoys"] > 0
    assert n["pairs"]["overall"]["precision"] < 1.0
    assert doc["meta"]["seed"] == 7 and doc["meta"]["generation_id"]


def test_markdown_states_shared_definition_and_provenance():
    doc = {
        "meta": {
            "generation_id": 3, "seed": 7, "content_sha256": "ab" * 32,
            "date": "2026-11-07T00:00:00+00:00", "git_commit": "abc (uncommitted changes)",
            "orders": 46, "planted": 8, "decoys": 4,
        },
        "detector": ev.score({("M1", "O1")}, TRUTH),
        "naive": ev.score({("M3", "O3")}, TRUTH),
    }  # fmt: skip
    md = ev.markdown(doc)
    assert "share the netting definition" in md
    assert "generation 3" in md and "seed 7" in md and "abcdefabcdef"[:0] == ""
    assert "synthetic" in md.lower()
