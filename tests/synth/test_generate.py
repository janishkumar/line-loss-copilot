"""Synthetic generator on a hand-built Anchors (no database)."""

import math
from datetime import timedelta

import pytest

from linecopilot.supply.mrp import Order, Receipt, SupplyInput, detect, naive_rule
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


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_load_in_range_other_seeds(seed):
    assert 0.85 <= load_factor(generate(ANCHORS, seed), ANCHORS) <= 0.95


def _need_at(d, order):
    """Independent need date: due minus processing on the fastest eligible machine."""
    fam = next(p["family"] for p in d.product if p["product_id"] == order["product_id"])
    eligible = {c["machine_id"] for c in d.machine_capability if c["family"] == fam}
    best = max(
        r["rate_per_hour"] * r["availability"]
        for r in d.machine_rate
        if r["machine_id"] in eligible
    )
    return order["due_at"] - timedelta(minutes=math.ceil(order["quantity"] / best * 60))


def _netting(d):
    """Small independent MRP netting by need date. Returns {(raw material, order): shortfall}."""
    bom = {}
    for b in d.bom:
        bom.setdefault(b["parent_id"], []).append((b["child_id"], float(b["qty_per"])))
    kind = {m["material_id"]: m["kind"] for m in d.material}
    stock = {s["material_id"]: float(s["on_hand"]) for s in d.stock}
    receipts = [(r["material_id"], float(r["qty"]), r["due_at"]) for r in d.receipt]
    used: dict[str, float] = {}  # raw allocated so far, in need-date order
    short = {}
    for o in sorted(d.customer_order, key=lambda o: (_need_at(d, o), o["order_id"])):
        need_at = _need_at(d, o)
        req: dict[str, float] = {}

        def explode(parent, qty, req=req):
            for child, per in bom.get(parent, []):
                need = qty * per
                if kind[child] == "subassembly":
                    take = min(stock[child], need)  # net stock, explode the rest
                    stock[child] -= take
                    explode(child, need - take)
                else:
                    req[child] = req.get(child, 0.0) + need

        explode(o["product_id"], o["quantity"])
        for m, q in req.items():
            avail = stock[m] + sum(r for mm, r, due in receipts if mm == m and due <= need_at)
            avail -= used.get(m, 0.0)
            if q > avail + 1e-9:
                short[(m, o["order_id"])] = q - avail
            used[m] = used.get(m, 0.0) + q
    return short


def _naive(d):
    """Stock-below-gross-demand rule: material short if stock < total gross requirement."""
    bom = {}
    for b in d.bom:
        bom.setdefault(b["parent_id"], []).append((b["child_id"], float(b["qty_per"])))
    gross: dict[str, float] = {}
    users: dict[str, set] = {}

    def explode(parent, qty, order):
        for child, per in bom.get(parent, []):
            gross[child] = gross.get(child, 0.0) + qty * per
            users.setdefault(child, set()).add(order)
            explode(child, qty * per, order)

    for o in d.customer_order:
        explode(o["product_id"], o["quantity"], o["order_id"])
    stock = {s["material_id"]: float(s["on_hand"]) for s in d.stock}
    return {(m, o) for m in gross if stock[m] < gross[m] for o in users[m]}


@pytest.mark.parametrize("seed", [7, 1, 2])
def test_planted_labels_match_independent_netting(seed):
    d = generate(ANCHORS, seed)
    truth = {(p["material_id"], p["order_id"]) for p in d.planted_shortage if not p["decoy"]}
    decoys = {(p["material_id"], p["order_id"]) for p in d.planted_shortage if p["decoy"]}
    assert truth and decoys
    found = set(_netting(d))
    assert found == truth  # no regular shortage, no decoy, every planted one found
    assert not (found & decoys)
    kinds = {(p["material_id"], p["order_id"]): p["kind"] for p in d.planted_shortage}
    assert {kinds[k] for k in truth} == {"plain", "timing", "level_two"}
    # decoys fool the naive rule, which is why they exist
    assert decoys <= _naive(d)


def test_need_date_edge_cases():
    d = generate(ANCHORS, 7)
    orders = {o["order_id"]: o for o in d.customer_order}
    receipts = {}
    for r in d.receipt:
        receipts.setdefault(r["material_id"], []).append(r)
    for p in d.planted_shortage:
        if p["kind"] != "timing":
            continue
        need = _need_at(d, orders[p["order_id"]])
        assert need > orders[p["order_id"]]["release_at"]
        dues = [r["due_at"] for r in receipts[p["material_id"]]]
        if p["decoy"]:
            assert all(t <= need for t in dues)
        else:
            assert all(t > need for t in dues)
    # one decoy receipt lands exactly on the need date, and still counts as in time
    assert any(
        r["due_at"] == _need_at(d, orders[p["order_id"]])
        for p in d.planted_shortage
        if p["decoy"] and p["kind"] == "timing"
        for r in receipts[p["material_id"]]
    )


def test_changeover_never_zero_for_a_different_product():
    a = Anchors(rates={"s_1": 4500.0}, availability={"s_1": 0.9}, changeover_same_family_min=0)
    d = generate(a, 7)
    assert all(c["minutes"] >= 1 for c in d.changeover if not c["same_product"])


def _supply_input(d):
    fam = {p["product_id"]: p["family"] for p in d.product}
    eff = {
        r["machine_id"]: float(r["rate_per_hour"]) * float(r["availability"])
        for r in d.machine_rate
    }
    best_f = {}
    for c in d.machine_capability:
        best_f[c["family"]] = max(best_f.get(c["family"], 0.0), eff[c["machine_id"]])
    bom = {}
    for b in d.bom:
        bom.setdefault(b["parent_id"], []).append((b["child_id"], float(b["qty_per"])))
    return SupplyInput(
        orders=[
            Order(o["order_id"], o["product_id"], o["quantity"], o["release_at"], o["due_at"])
            for o in d.customer_order
        ],
        bom=bom,
        kinds={m["material_id"]: m["kind"] for m in d.material},
        stock={s["material_id"]: float(s["on_hand"]) for s in d.stock},
        receipts=[Receipt(r["material_id"], float(r["qty"]), r["due_at"]) for r in d.receipt],
        best_rate={p: best_f[f] for p, f in fam.items()},
    )


@pytest.mark.parametrize("seed", [7, 1, 2])
def test_production_engine_agrees_with_independent_netting_and_naive(seed):
    d = generate(ANCHORS, seed)
    s = _supply_input(d)
    short, _ = detect(s)
    ref = _netting(d)
    assert {(f.material_id, f.order_id) for f in short} == set(ref)
    for f in short:
        assert f.short_qty == pytest.approx(ref[(f.material_id, f.order_id)])
    assert set(naive_rule(s.orders, s.bom, s.stock)) == _naive(d)
