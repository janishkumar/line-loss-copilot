"""Problem loader on the test database (live generation)."""

import pytest

from linecopilot import schemas
from linecopilot.plan import cpsat, dispatch
from linecopilot.plan.load import load_problem
from linecopilot.supply.load import load_supply
from linecopilot.supply.mrp import detect
from linecopilot.synth.anchors import load_anchors
from linecopilot.synth.generate import generate, write

pytestmark = pytest.mark.db


@pytest.fixture
def loaded(built):
    schemas.apply(built)
    a = load_anchors(built)
    data = generate(a, 7)
    write(built, data, a, 7)
    return built, data


def test_problem_matches_tables_and_blocks_are_reported(loaded):
    conn, data = loaded
    p = load_problem(conn)
    assert len(p.jobs) + len(p.blocked) == len(data.customer_order)
    assert {m.machine_id for m in p.machines} == {r["machine_id"] for r in data.machine_rate}
    assert all(j.due >= 0 and j.ready >= 0 for j in p.jobs)
    # shortfalls with a covering receipt delay readiness, never beyond a receipt time
    short = {f.order_id for f in detect(load_supply(conn))[0]}
    delayed = {j.order_id for j in p.jobs if j.ready > 0}
    assert delayed <= short
    same = load_problem(conn, detect(load_supply(conn)))
    assert same.jobs == p.jobs and same.blocked == p.blocked


def test_changeover_is_shared_zero_for_same_product(loaded):
    conn, _ = loaded
    p = load_problem(conn)
    j = p.jobs[0]
    assert p.changeover(j.family, j.product_id, j.family, j.product_id) == 0
    assert p.changeover(j.family, j.product_id, j.family, "other") > 0


def test_all_three_schedule_the_loaded_problem(loaded):
    conn, _ = loaded
    p = load_problem(conn)
    plans = [dispatch.fifo(p), dispatch.edd(p), cpsat.solve(p, time_limit_s=2)]
    for plan in plans:
        assert len(plan.assignments) == len(p.jobs)
    assert plans[2].status in ("OPTIMAL", "FEASIBLE", "fallback_edd")
