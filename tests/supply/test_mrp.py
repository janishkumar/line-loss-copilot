"""Shortage netting on tiny hand-built cases (no database)."""

from datetime import UTC, datetime, timedelta

from linecopilot.supply.mrp import (
    Order,
    Receipt,
    Requirement,
    explode,
    naive_rule,
    net,
)

T0 = datetime(2026, 1, 5, tzinfo=UTC)
KINDS = {"RAW": "raw", "RAW2": "raw", "SA": "subassembly", "CARTON": "subassembly"}


def order(oid, qty, due_days=5, product="P"):
    return Order(oid, product, qty, T0, T0 + timedelta(days=due_days))


def run(orders, bom, stock, receipts=(), rate=100.0, kinds=KINDS):
    reqs = explode(orders, bom, {o.product_id: rate for o in orders})
    return net(reqs, stock, list(receipts), bom, kinds)


def keys(shortfalls):
    return {(s.material_id, s.order_id) for s in shortfalls}


def test_need_date_is_due_minus_processing_on_fastest_machine():
    # 250 units at 100/h = 150 min
    [r] = explode([order("O1", 250)], {"P": [("RAW", 1.0)]}, {"P": 100.0})
    assert r == Requirement("O1", "RAW", 250.0, T0 + timedelta(days=5) - timedelta(minutes=150))


def test_explode_is_level_one_only():
    bom = {"P": [("SA", 1.0), ("RAW", 2.0)], "SA": [("RAW2", 1.0)]}
    reqs = explode([order("O1", 10)], bom, {"P": 100.0})
    assert {(r.material_id, r.qty) for r in reqs} == {("SA", 10.0), ("RAW", 20.0)}


def test_plain_shortage_traced_to_the_order():
    s, _ = run([order("O1", 100)], {"P": [("RAW", 1.0)]}, {"RAW": 40.0})
    [f] = s
    assert (f.material_id, f.order_id, f.short_qty, f.level) == ("RAW", "O1", 60.0, 1)


def test_covered_requirement_has_no_shortfall():
    s, _ = run([order("O1", 100)], {"P": [("RAW", 1.0)]}, {"RAW": 100.0})
    assert s == []


def test_timing_receipt_after_need_date_is_short_but_in_time_is_not():
    bom = {"P": [("RAW", 1.0)]}
    o = order("O1", 100)
    need = explode([o], bom, {"P": 100.0})[0].need_at
    late, _ = run([o], bom, {"RAW": 30.0}, [Receipt("RAW", 70.0, need + timedelta(days=1))])
    assert keys(late) == {("RAW", "O1")} and late[0].short_qty == 70.0
    early, _ = run([o], bom, {"RAW": 30.0}, [Receipt("RAW", 70.0, need - timedelta(days=1))])
    assert early == []


def test_receipt_exactly_at_need_time_counts_as_in_time():
    bom = {"P": [("RAW", 1.0)]}
    o = order("O1", 100)
    need = explode([o], bom, {"P": 100.0})[0].need_at
    s, _ = run([o], bom, {"RAW": 30.0}, [Receipt("RAW", 70.0, need)])
    assert s == []
    s, _ = run([o], bom, {"RAW": 30.0}, [Receipt("RAW", 70.0, need + timedelta(seconds=1))])
    assert keys(s) == {("RAW", "O1")}


def test_level_two_only_after_netting_subassembly_stock():
    bom = {"P": [("SA", 1.0)], "SA": [("RAW", 2.0)]}
    # SA stock covers 60 of 100, remaining 40 SA need 80 raw; raw stock 50 -> short 30
    s, _ = run([order("O1", 100)], bom, {"SA": 60.0, "RAW": 50.0})
    [f] = s
    assert (f.material_id, f.order_id, f.level) == ("RAW", "O1", 2)
    assert f.short_qty == 30.0
    # gross explosion would need 200 raw; with SA fully stocked there is no shortage at all
    s, _ = run([order("O1", 100)], bom, {"SA": 100.0, "RAW": 0.0})
    assert s == []


def test_subassembly_itself_is_never_reported():
    bom = {"P": [("SA", 1.0)], "SA": [("RAW", 1.0)]}
    s, _ = run([order("O1", 100)], bom, {"SA": 0.0, "RAW": 1000.0})
    assert s == []


def test_level_two_sharing_raw_with_direct_use_is_one_shortfall():
    bom = {"P": [("SA", 1.0), ("RAW", 1.0)], "SA": [("RAW", 1.0)]}
    s, _ = run([order("O1", 100)], bom, {"SA": 0.0, "RAW": 150.0})
    [f] = s
    assert f.short_qty == 50.0 and f.level == 1


def test_allocation_in_need_date_then_order_id_order():
    bom = {"P": [("RAW", 1.0)]}
    # A is due earlier so needs first: it is covered, B (later need) is short
    a, b = order("B-late", 100, due_days=6), order("A-early", 100, due_days=3)
    s, _ = run([a, b], bom, {"RAW": 100.0})
    assert keys(s) == {("RAW", "B-late")}
    # same need time: order_id breaks the tie
    x, y = order("O2", 100), order("O1", 100)
    s, _ = run([x, y], bom, {"RAW": 100.0})
    assert keys(s) == {("RAW", "O2")}


def test_first_short_at_is_the_orders_need_time():
    bom = {"P": [("RAW", 1.0)]}
    o = order("O1", 100)
    s, _ = run([o], bom, {"RAW": 0.0})
    assert s[0].first_short_at == explode([o], bom, {"P": 100.0})[0].need_at


def test_projection_tracks_receipts_and_allocations():
    bom = {"P": [("RAW", 1.0)]}
    o = order("O1", 100)
    need = explode([o], bom, {"P": 100.0})[0].need_at
    _, proj = run([o], bom, {"RAW": 30.0}, [Receipt("RAW", 80.0, need - timedelta(hours=1))])
    pts = proj["RAW"]
    assert pts[0].projected == 30.0
    assert pts[-1].projected == 10.0 and pts[-1].at == need
    assert [p.at for p in pts] == sorted(p.at for p in pts)


def test_naive_rule_flags_decoys_the_detector_does_not():
    bom = {"P": [("RAW", 1.0)], "Q": [("CARTON", 1.0)], "CARTON": [("RAW2", 1.0)]}
    o1, o2 = order("O1", 100), order("O2", 100, product="Q")
    # RAW: stock 30 plus an in-time receipt of 70 covers O1; naive ignores receipts
    # RAW2: carton stock covers the need, so no board is needed; naive explodes gross
    stock = {"RAW": 30.0, "CARTON": 100.0, "RAW2": 20.0}
    need = explode([o1], bom, {"P": 100.0})[0].need_at
    reqs = explode([o1, o2], bom, {"P": 100.0, "Q": 100.0})
    s, _ = net(reqs, stock, [Receipt("RAW", 70.0, need)], bom, KINDS)
    assert s == []
    flagged = set(naive_rule([o1, o2], bom, stock))
    assert ("RAW", "O1") in flagged and ("RAW2", "O2") in flagged


def test_naive_rule_flags_every_order_using_a_short_material():
    bom = {"P": [("RAW", 1.0)]}
    flagged = set(naive_rule([order("O1", 100), order("O2", 100)], bom, {"RAW": 150.0}))
    assert flagged == {("RAW", "O1"), ("RAW", "O2")}
    assert naive_rule([order("O1", 100)], bom, {"RAW": 100.0}) == []


def test_material_with_no_stock_row_counts_as_zero():
    s, _ = run([order("O1", 10)], {"P": [("RAW", 1.0)]}, {})
    assert keys(s) == {("RAW", "O1")}


def test_fully_covered_subassembly_adds_no_raw_requirement():
    bom = {"P": [("SA", 1.0)], "SA": [("RAW", 1.0)]}
    o1, o2 = order("O1", 100, due_days=3), order("O2", 100, due_days=6)
    s, _ = run([o1, o2], bom, {"SA": 200.0, "RAW": 0.0})
    assert s == []


# ---- contention between orders -------------------------------------------------------------

RAWBOM = {"P": [("RAW", 1.0)]}


def shorts(s):
    return {f.order_id: f.short_qty for f in s}


def test_partial_cover_across_orders_later_order_short_by_the_remainder():
    a, b = order("A", 100, due_days=3), order("B", 100, due_days=6)
    s, _ = run([a, b], RAWBOM, {"RAW": 150.0})
    assert shorts(s) == {"B": 50.0}


def test_earlier_order_that_is_itself_short_still_consumes_its_full_requirement():
    # A (earlier) needs 150 of 100 and is short 50; it is promised all 100, so B gets none
    a, b = order("A", 150, due_days=3), order("B", 10, due_days=6)
    s, _ = run([a, b], RAWBOM, {"RAW": 100.0})
    assert shorts(s) == {"A": 50.0, "B": 10.0}


def test_receipt_between_two_needs_covers_only_the_later_order():
    a, b = order("A", 100, due_days=3), order("B", 100, due_days=6)
    mid = T0 + timedelta(days=4)
    s, _ = run([a, b], RAWBOM, {"RAW": 100.0}, [Receipt("RAW", 100.0, mid)])
    assert s == []
    # the same receipt landing after both needs covers neither
    late = T0 + timedelta(days=9)
    s, _ = run([a, b], RAWBOM, {"RAW": 100.0}, [Receipt("RAW", 100.0, late)])
    assert shorts(s) == {"B": 100.0}
    # a receipt before A's need is available to both
    s, _ = run([a, b], RAWBOM, {"RAW": 0.0}, [Receipt("RAW", 200.0, T0 + timedelta(days=1))])
    assert s == []


def test_subassembly_stock_partly_covering_across_two_orders():
    bom = {"P": [("SA", 1.0)], "SA": [("RAW", 2.0)]}
    a, b = order("A", 100, due_days=3), order("B", 100, due_days=6)
    # SA stock 150: A fully covered (no raw), B gets 50 of 100 and needs 50 SA = 100 raw
    s, _ = run([a, b], bom, {"SA": 150.0, "RAW": 60.0})
    assert shorts(s) == {"B": 40.0}
    assert s[0].level == 2


def test_receipt_exactly_at_need_time_with_two_competing_orders():
    a, b = order("A", 100, due_days=5), order("B", 100, due_days=5)
    need = explode([a], RAWBOM, {"P": 100.0})[0].need_at
    # one receipt of 100 on the need time: A (first by id) takes it, B is short
    s, _ = run([a, b], RAWBOM, {"RAW": 0.0}, [Receipt("RAW", 100.0, need)])
    assert shorts(s) == {"B": 100.0}
    s, _ = run([a, b], RAWBOM, {"RAW": 0.0}, [Receipt("RAW", 200.0, need)])
    assert s == []


# ---- hazards ---------------------------------------------------------------------------------


def test_product_without_an_eligible_machine_is_reported_not_a_crash():
    from linecopilot.supply.mrp import no_need_date

    o1, o2 = order("O1", 100), order("O2", 100, product="GHOST")
    bom = {"P": [("RAW", 1.0)], "GHOST": [("RAW", 1.0)]}
    rates = {"P": 100.0}
    assert [r.order_id for r in explode([o1, o2], bom, rates)] == ["O1"]
    assert [(o.order_id, why) for o, why in no_need_date([o1, o2], rates)] == [
        ("O2", "no eligible machine")
    ]
    assert [o.order_id for o, _ in no_need_date([o1], {"P": 0.0})] == ["O1"]


def test_bom_cycle_raises_a_clear_error():
    import pytest

    bom = {"P": [("SA", 1.0)], "SA": [("CARTON", 1.0)], "CARTON": [("SA", 1.0)]}
    with pytest.raises(ValueError, match="cycle"):
        run([order("O1", 10)], bom, {})
    with pytest.raises(ValueError, match="cycle"):
        naive_rule([order("O1", 10)], bom, {})


def test_material_ready_is_first_receipt_after_the_short_allocation():
    from datetime import datetime, timedelta

    from linecopilot.supply.mrp import (
        Order,
        Receipt,
        SupplyInput,
        detect,
        material_ready,
    )

    t0 = datetime(2026, 1, 5, tzinfo=UTC)
    s = SupplyInput(
        orders=[
            Order("o1", "p", 100, t0, t0 + timedelta(days=2)),
            Order("o2", "p", 100, t0, t0 + timedelta(days=3)),
            Order("o3", "q", 10, t0, t0 + timedelta(days=3)),
        ],
        bom={"p": [("m", 1.0)], "q": [("z", 1.0)]},
        kinds={"m": "raw", "z": "raw"},
        stock={"m": 100.0, "z": 0.0},
        receipts=[Receipt("m", 100.0, t0 + timedelta(days=4))],
        best_rate={"p": 100.0, "q": 100.0},
    )
    ready = material_ready(*detect(s))
    assert "o1" not in ready
    assert ready["o2"] == (t0 + timedelta(days=4), None)
    assert ready["o3"] == (None, "z")
