"""Plan storage round trip on the test database."""

from datetime import UTC, datetime, timedelta

import pytest

from linecopilot import schemas
from linecopilot.plan import dispatch
from linecopilot.plan import store as plan_store
from linecopilot.plan.model import Job, Machine, Problem
from linecopilot.plan.replay import Window
from linecopilot.synth.generate import HORIZON_START

pytestmark = pytest.mark.db


def co(fa, pa, fb, pb):
    return 0 if pa == pb else 10


def tiny():
    ms = (Machine("M1", 60, 1.0, frozenset({"A"})),)
    jobs = (Job("o1", "p1", "A", 60, 0, 100), Job("o2", "p2", "A", 60, 0, 100))
    return Problem(jobs, ms, co, blocked=(("o9", "no eligible machine"),))


def test_round_trip(built):
    schemas.apply(built)
    try:
        p = tiny()
        plans = [dispatch.fifo(p), dispatch.edd(p)]
        plans[1].solver_status, plans[1].stop_reason = "FEASIBLE", "deterministic_time"
        w = Window(datetime(2021, 7, 1, tzinfo=UTC), datetime(2021, 7, 15, tzinfo=UTC))
        replays = {
            "fifo": [(w, {"late_orders": 1}, {"M1": {"stopped_share": 0.1, "no_data_share": 0.0}})],
            "edd": [],
        }
        ids = plan_store.save(built, plans, None, "test", replays)
        assert set(ids) == {"fifo", "edd"}
        got = plan_store.latest(built)
        runs = {r["algorithm"]: r for r in got}
        assert runs["fifo"]["plan_run_id"] == ids["fifo"]
        assert runs["fifo"]["is_synthetic"] is True
        assert runs["edd"]["solver_status"] == "FEASIBLE"
        assert runs["edd"]["stop_reason"] == "deterministic_time"
        a = runs["fifo"]["assignments"]
        assert [x["order_id"] for x in a] == [x.order_id for x in plans[0].assignments]
        assert a[0]["start_at"] == HORIZON_START + timedelta(minutes=plans[0].assignments[0].start)
        assert runs["fifo"]["blocked"] == [{"order_id": "o9", "reason": "no eligible machine"}]
        r = runs["fifo"]["replays"][0]
        assert r["window_start"] == w.start and r["kpis"] == {"late_orders": 1}
        assert r["machine_stats"]["M1"]["stopped_share"] == 0.1
        # a second save does not disturb the first, and latest returns the newest run per algorithm
        ids2 = plan_store.save(built, [plans[0]], None, "again", {})
        assert {r["plan_run_id"] for r in plan_store.latest(built)} == {ids2["fifo"], ids["edd"]}
        for tbl in ("plan_run", "assignment", "blocked", "replay_result"):
            assert (
                built.execute(f"select count(*) from plan.{tbl} where not is_synthetic").fetchone()[
                    0
                ]
                == 0
            )
    finally:
        built.execute("delete from plan.plan_run where label in ('test','again')")


def test_agent_can_read_but_not_write(built, agent_url):
    import psycopg

    schemas.apply(built)
    with psycopg.connect(agent_url) as c:
        c.execute("select count(*) from plan.plan_run")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            c.execute("delete from plan.plan_run")
