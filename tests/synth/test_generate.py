"""Synthetic generator on a hand-built Anchors (no database)."""

import pytest

from linecopilot.synth.anchors import Anchors
from linecopilot.synth.generate import (
    HORIZON_START,
    INJECTED_NOTES,
    content_hash,
    generate,
    load_factor,
)

ANCHORS = Anchors(
    rates={"s_1": 4500.0, "s_2": 6500.0, "s_3": 4500.0, "s_4": 6176.0, "s_5": 6500.0},
    availability={"s_1": 0.85, "s_2": 0.9, "s_3": 0.88, "s_4": 0.93, "s_5": 0.95},
    changeover_same_family_min=12,
    changeover_cross_family_min=19,
    sources={"rate": "test"},
)


def test_horizon_start_is_a_monday():
    assert HORIZON_START.weekday() == 0
    assert HORIZON_START.isoformat() == "2026-01-05T00:00:00+00:00"


def test_deterministic_per_seed():
    a, b = generate(ANCHORS, 7), generate(ANCHORS, 7)
    assert content_hash(a) == content_hash(b)
    assert content_hash(generate(ANCHORS, 8)) != content_hash(a)


def test_every_family_has_an_eligible_machine():
    d = generate(ANCHORS, 7)
    families = {p["family"] for p in d.product}
    capable = {c["family"] for c in d.machine_capability}
    assert families <= capable
    assert {c["machine_id"] for c in d.machine_capability} <= set(ANCHORS.rates)
    assert {r["machine_id"] for r in d.machine_rate} == set(ANCHORS.rates)


def test_every_order_has_a_product_and_a_bom():
    d = generate(ANCHORS, 7)
    products = {p["product_id"] for p in d.product}
    parents = {b["parent_id"] for b in d.bom}
    assert {o["product_id"] for o in d.customer_order} <= products
    assert products <= parents
    materials = {m["material_id"] for m in d.material}
    assert {b["child_id"] for b in d.bom} <= materials
    assert {s["material_id"] for s in d.stock} == materials


def test_load_in_range_for_default_seed():
    assert 0.85 <= load_factor(generate(ANCHORS, 7), ANCHORS) <= 0.95


def test_order_times_inside_horizon():
    d = generate(ANCHORS, 7)
    end = HORIZON_START.replace(day=HORIZON_START.day + 14)
    for o in d.customer_order:
        assert HORIZON_START <= o["release_at"] < o["due_at"] <= end


def test_planted_kinds_and_decoys():
    d = generate(ANCHORS, 7)
    real = [p for p in d.planted_shortage if not p["decoy"]]
    decoys = [p for p in d.planted_shortage if p["decoy"]]
    for kind in ("plain", "timing", "level_two"):
        assert sum(p["kind"] == kind for p in real) >= 2
    for kind in ("timing", "level_two"):
        assert sum(p["kind"] == kind for p in decoys) >= 2
    orders = {o["order_id"] for o in d.customer_order}
    assert {p["order_id"] for p in d.planted_shortage} <= orders


def test_timing_receipts_relative_to_need_date():
    d = generate(ANCHORS, 7)
    rel = {o["order_id"]: o["release_at"] for o in d.customer_order}
    receipts = {}
    for r in d.receipt:
        receipts.setdefault(r["material_id"], []).append(r)
    late = [p for p in d.planted_shortage if p["kind"] == "timing" and not p["decoy"]]
    ok = [p for p in d.planted_shortage if p["kind"] == "timing" and p["decoy"]]
    for p in late:
        assert all(r["due_at"] > rel[p["order_id"]] for r in receipts[p["material_id"]])
    for p in ok:
        assert any(r["due_at"] <= rel[p["order_id"]] for r in receipts[p["material_id"]])
    # one decoy lands exactly on the need date
    assert any(r["due_at"] == rel[p["order_id"]] for p in ok for r in receipts[p["material_id"]])


def test_instruction_like_notes_present():
    d = generate(ANCHORS, 7)
    notes = [o["note"] for o in d.customer_order if o["note"]]
    assert sum(n in INJECTED_NOTES for n in notes) == 3
    assert any("SYSTEM:" in n and "approve" in n for n in notes)
    assert len(notes) > 3


def test_changeover_rules():
    d = generate(ANCHORS, 7)
    cross = [c for c in d.changeover if c["from_family"] != c["to_family"]]
    same = [c for c in d.changeover if c["from_family"] == c["to_family"] and not c["same_product"]]
    assert cross and {c["minutes"] for c in cross} == {19}
    assert {c["minutes"] for c in same} == {12}
    assert all(c["minutes"] == 0 for c in d.changeover if c["same_product"])


def test_single_machine_anchors_still_generate():
    a = Anchors(rates={"s_1": 4500.0}, availability={"s_1": 0.9}, sources={})
    d = generate(a, 7)
    assert {c["family"] for c in d.machine_capability} == {p["family"] for p in d.product}
    assert 0.85 <= load_factor(d, a) <= 0.95


def test_all_rows_carry_synthetic_source():
    d = generate(ANCHORS, 7)
    for name in d.TABLES:
        for row in getattr(d, name):
            assert row.get("source", "synthetic") == "synthetic"


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_load_in_range_other_seeds(seed):
    assert 0.85 <= load_factor(generate(ANCHORS, seed), ANCHORS) <= 0.95
