"""Loading the supply tables and detecting shortages on the test database (live generation)."""

import pytest

from linecopilot import schemas
from linecopilot.supply.load import load_supply
from linecopilot.supply.mrp import detect, naive_rule
from linecopilot.synth.anchors import load_anchors
from linecopilot.synth.generate import generate, write

pytestmark = pytest.mark.db


@pytest.fixture
def supply(built):
    schemas.apply(built)
    a = load_anchors(built)
    data = generate(a, 7)
    gid = write(built, data, a, 7)
    return built, data, gid


def test_load_matches_the_written_rows(supply):
    conn, data, gid = supply
    s = load_supply(conn)
    assert s.generation_id == gid and s.seed == 7
    assert len(s.orders) == len(data.customer_order)
    assert set(s.stock) == {m["material_id"] for m in data.material}
    assert set(s.best_rate) == {p["product_id"] for p in data.product}
    assert all(v > 0 for v in s.best_rate.values())
    assert {o.product_id for o in s.orders} <= set(s.bom)


def test_detector_finds_exactly_the_planted_shortages_on_the_database(supply):
    conn, data, _ = supply
    s = load_supply(conn)
    truth = {(p["material_id"], p["order_id"]) for p in data.planted_shortage if not p["decoy"]}
    decoys = {(p["material_id"], p["order_id"]) for p in data.planted_shortage if p["decoy"]}
    found = {(f.material_id, f.order_id) for f in detect(s)[0]}
    assert found == truth
    assert decoys <= set(naive_rule(s.orders, s.bom, s.stock))
