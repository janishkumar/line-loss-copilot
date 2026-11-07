"""get_plan, shortages and get_order on the test database after a seeded generation."""

import os
from datetime import UTC, datetime

import psycopg
import pytest
from fastapi.testclient import TestClient

from linecopilot import schemas
from linecopilot.api.app import create_app
from linecopilot.plan import dispatch
from linecopilot.plan import store as plan_store
from linecopilot.plan.load import load_problem
from linecopilot.plan.model import split_unschedulable
from linecopilot.plan.replay import Window
from linecopilot.synth.anchors import load_anchors
from linecopilot.synth.generate import generate, write
from linecopilot.tools.planning import GetOrderArgs, GetPlanArgs, ShortagesArgs
from linecopilot.tools.registry import call_tool

pytestmark = pytest.mark.db


@pytest.fixture
def synth(built):
    schemas.apply(built)
    a = load_anchors(built)
    data = generate(a, 7)
    gid = write(built, data, a, 7)
    return built, data, gid


@pytest.fixture
def planned(synth):
    conn, data, gid = synth
    problem = split_unschedulable(load_problem(conn))
    plans = [dispatch.fifo(problem), dispatch.edd(problem), dispatch.edd_batch(problem)]
    w = Window(datetime(2021, 7, 1, tzinfo=UTC), datetime(2021, 7, 15, tzinfo=UTC))
    k = {"late_orders": 3, "total_tardiness_min": 120, "changeover_min": 40}
    replays = {p.algorithm: [(w, k, {"s_1": {"stopped_share": 0.1}})] for p in plans}
    ids = plan_store.save(conn, plans, gid, "test-plan-tools", replays)
    yield conn, data, gid, plans, ids
    conn.execute("DELETE FROM plan.plan_run WHERE label = 'test-plan-tools'")


def assert_synthetic_envelope(r, seed=7):
    assert r.citations == [] and r.citation_count == 0
    text = " ".join(r.assumptions)
    assert "synthetic" in text.lower() and f"seed {seed}" in text


def test_shortages_match_the_planted_truth_and_trace_orders(synth):
    conn, data, gid = synth
    r = call_tool(conn, "shortages", {})
    assert r.status == "ok" and r.data.generation_id == gid and r.data.seed == 7
    assert_synthetic_envelope(r)
    truth = {(p["material_id"], p["order_id"]) for p in data.planted_shortage if not p["decoy"]}
    got = {(x.material_id, x.order_id) for x in r.data.rows}
    assert got == truth and r.data.total == len(truth)
    assert r.data.is_synthetic and "synthetic orders" in r.data.label
    one = next(iter(truth))
    f = call_tool(conn, "shortages", {"material_id": one[0]}).data
    assert f.rows and {x.material_id for x in f.rows} == {one[0]}
    assert one[1] in {x.order_id for x in f.rows}
    assert call_tool(conn, "shortages", {"material_id": "NOPE"}).data.rows == []
    assert call_tool(conn, "shortages", {"bogus": 1}).status == "out_of_scope"


def test_get_order_returns_the_note_verbatim_as_data(synth):
    conn, data, _ = synth
    noted = [o for o in data.customer_order if o["note"]]
    injected = [o for o in noted if "ignore" in o["note"].lower() or "approve" in o["note"].lower()]
    assert injected
    o = injected[0]
    r = call_tool(conn, "get_order", {"order_id": o["order_id"]})
    assert r.status == "ok"
    assert_synthetic_envelope(r)
    assert r.data.order.note == o["note"]  # verbatim, never altered
    assert r.data.order.note_is_data is True and "never follow" in r.data.order.note_notice
    assert r.data.order.source == "synthetic" and r.data.order.quantity == o["quantity"]
    assert r.data.requirements and all(q.qty > 0 for q in r.data.requirements)
    plain = next(x for x in data.customer_order if not x["note"])
    p = call_tool(conn, "get_order", {"order_id": plain["order_id"]}).data
    assert p.order.note is None and p.order.note_notice is None and p.order.note_is_data is True


def test_get_order_shows_its_shortfall_and_plan_placement(planned):
    conn, data, _, plans, _ = planned
    truth = next(p for p in data.planted_shortage if not p["decoy"])
    r = call_tool(conn, "get_order", {"order_id": truth["order_id"]})
    assert truth["material_id"] in {s.material_id for s in r.data.shortfalls}
    placed = plans[0].assignments[0].order_id
    r = call_tool(conn, "get_order", {"order_id": placed})
    assert {p.algorithm for p in r.data.planned} == {"fifo", "edd", "edd_batch"}


def test_get_order_unknown_and_invalid(synth):
    conn, _, _ = synth
    r = call_tool(conn, "get_order", {"order_id": "NO-SUCH"})
    assert r.status == "insufficient_evidence" and "NO-SUCH" in r.missing
    assert call_tool(conn, "get_order", {}).status == "out_of_scope"
    assert call_tool(conn, "get_order", {"order_id": ""}).status == "out_of_scope"


def test_get_plan_kpis_sequences_and_replay_windows(planned):
    conn, _, gid, plans, ids = planned
    r = call_tool(conn, "get_plan", {})
    assert r.status == "ok" and r.data.generation_id == gid and r.data.seed == 7
    assert_synthetic_envelope(r)
    assert not r.data.stale
    by = {p.algorithm: p for p in r.data.plans}
    assert set(by) == {"fifo", "edd", "edd_batch"}
    fifo = by["fifo"]
    assert fifo.plan_run_id == ids["fifo"] and fifo.kpis_nominal == plans[0].kpis
    assert fifo.kpis_replayed["windows"] == 1
    assert fifo.kpis_replayed["total_tardiness_min"]["median"] == 120
    tard = fifo.kpis_replayed["total_tardiness_min"]
    assert tard["q1"] == tard["q3"] == 120
    text = " ".join(r.assumptions)
    assert "2021-07-01" in text and "synthetic orders on real capacity and real stops" in text
    assert fifo.blocked_count == len(plans[0].blocked)
    machines = set(fifo.sequences)
    assert machines and all(len(v) <= 25 for v in fifo.sequences.values())
    assert sum(fifo.sequence_lengths.values()) == len(plans[0].assignments)
    one = sorted(machines)[0]
    f = call_tool(conn, "get_plan", {"algorithm": "fifo", "machine_id": one}).data
    assert [p.algorithm for p in f.plans] == ["fifo"] and set(f.plans[0].sequences) == {one}
    assert call_tool(conn, "get_plan", {"algorithm": "bogus"}).status == "out_of_scope"


def test_get_plan_flags_a_plan_from_an_older_generation(planned):
    conn, data, gid, *_ = planned
    a = load_anchors(conn)
    try:
        new = write(conn, generate(a, 8), a, 8)
        r = call_tool(conn, "get_plan", {})
        assert new != gid and r.data.stale and "run `make plan` again" in " ".join(r.assumptions)
        assert r.data.generation_id == gid and r.data.seed == 7
    finally:
        write(conn, data, a, 7)  # leave the seed 7 generation live for other tests


def tx_conn(db_url):
    """A transaction we roll back: tables emptied here are back afterwards."""
    return psycopg.connect(db_url)


def test_not_run_yet_is_insufficient_evidence_with_a_clear_missing(synth, db_url):
    with tx_conn(db_url) as c:
        c.execute("DELETE FROM plan.plan_run")
        r = call_tool(c, "get_plan", {})
        assert r.status == "insufficient_evidence" and "make plan" in r.missing
        c.execute("DELETE FROM synthetic.generation")
        for name, args in (("get_plan", {}), ("shortages", {}), ("get_order", {"order_id": "x"})):
            r = call_tool(c, name, args)
            assert r.status == "insufficient_evidence" and "make synth" in r.missing, name
        c.rollback()


def test_agent_role_runs_the_tools_but_never_reads_the_answer_key(planned, agent_url):
    with psycopg.connect(agent_url, autocommit=True) as c:
        for name, args in (("get_plan", {}), ("shortages", {}), ("get_order", {"order_id": "x"})):
            assert call_tool(c, name, args).status in ("ok", "insufficient_evidence"), name
        assert call_tool(c, "shortages", {}).status == "ok"
        assert c.execute("SELECT count(*) FROM synthetic.customer_order").fetchone()[0] > 0
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            c.execute("SELECT * FROM synthetic.planted_shortage")


def test_api_routes_return_the_same_envelopes(planned):
    conn, data, *_ = planned
    client = TestClient(create_app(os.environ["LINECOPILOT_TEST_DB_URL"]))
    plan = client.get("/api/plan", params={"algorithm": "fifo"}).json()
    assert plan["status"] == "ok" and [p["algorithm"] for p in plan["data"]["plans"]] == ["fifo"]
    assert plan == call_tool(conn, "get_plan", {"algorithm": "fifo"}).model_dump(mode="json")
    sh = client.get("/api/shortages").json()
    assert sh == call_tool(conn, "shortages", {}).model_dump(mode="json")
    oid = data.customer_order[0]["order_id"]
    od = client.get(f"/api/orders/{oid}").json()
    assert od == call_tool(conn, "get_order", {"order_id": oid}).model_dump(mode="json")
    assert client.get("/api/orders/NO-SUCH").json()["status"] == "insufficient_evidence"
    assert client.get("/api/plan", params={"algorithm": "x"}).json()["status"] == "out_of_scope"
    assert client.get("/api/orders/" + "x" * 50).json()["status"] == "out_of_scope"


def test_args_models_forbid_extras():
    for m in (GetPlanArgs, ShortagesArgs, GetOrderArgs):
        assert m.model_config.get("extra") == "forbid"


def test_get_order_says_so_when_shortfalls_cannot_be_computed(synth, monkeypatch):
    from linecopilot.tools import planning

    conn, data, _ = synth

    def boom(supply):
        raise ValueError("BOM cycle through X: X > Y > X")

    monkeypatch.setattr(planning, "detect", boom)
    r = call_tool(conn, "get_order", {"order_id": data.customer_order[0]["order_id"]})
    assert r.status == "ok" and r.data.shortfalls == []
    assert "BOM cycle" in r.missing
    assert "unknown, not none" in " ".join(r.assumptions)


def test_get_plan_machine_without_assignments_is_explained(planned):
    conn, *_ = planned
    r = call_tool(conn, "get_plan", {"machine_id": "no_such_machine"})
    assert r.status == "ok" and "No assignments on machine 'no_such_machine'" in " ".join(
        r.assumptions
    )
