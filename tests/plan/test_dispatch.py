from linecopilot.plan import dispatch
from linecopilot.plan.model import Job, Machine, Problem, kpis


def co(fa, pa, fb, pb):
    return 0 if pa == pb else (5 if fa == fb else 30)


def prob(jobs, machines=None):
    machines = machines or (Machine("M1", 60, 1.0, frozenset({"A", "B"})),)
    return Problem(tuple(jobs), tuple(machines), co)


def test_fifo_orders_by_release_and_edd_by_due():
    jobs = [
        Job("o1", "p1", "A", 60, release=0, due=500),
        Job("o2", "p2", "A", 60, release=10, due=100),
    ]
    f = dispatch.fifo(prob(jobs))
    e = dispatch.edd(prob(jobs))
    assert [a.order_id for a in sorted(f.assignments, key=lambda a: a.start)] == ["o1", "o2"]
    assert [a.order_id for a in sorted(e.assignments, key=lambda a: a.start)] == ["o2", "o1"]
    assert f.kpis["late_orders"] == 1 and e.kpis["late_orders"] == 0


def test_release_ready_and_setup_respected_first_job_has_no_setup():
    jobs = [
        Job("o1", "p1", "A", 60, release=20, due=999, ready=50),
        Job("o2", "p2", "B", 60, release=0, due=999),
    ]
    plan = dispatch.edd(prob(jobs))
    a = {x.order_id: x for x in plan.assignments}
    assert a["o1"].start == 50 and a["o1"].setup_before == 0
    assert a["o2"].setup_before == 30 and a["o2"].start == a["o1"].end + 30


def test_eligibility_and_earliest_finish_machine():
    ms = (
        Machine("M1", 60, 1.0, frozenset({"A"})),
        Machine("M2", 120, 1.0, frozenset({"A", "B"})),
    )
    plan = dispatch.fifo(prob([Job("o1", "p", "B", 120, 0, 999)], ms))
    assert plan.assignments[0].machine_id == "M2"
    plan = dispatch.fifo(prob([Job("o1", "p", "A", 60, 0, 999)], ms))
    assert plan.assignments[0].machine_id == "M2" and plan.assignments[0].end == 30


def test_kpis_and_blocked_are_carried():
    p = Problem(
        (Job("o1", "p", "A", 60, 0, 10),),
        (Machine("M1", 60, 1.0, frozenset("A")),),
        co,
        blocked=(("o9", "why"),),
    )
    plan = dispatch.fifo(p)
    assert plan.blocked == [("o9", "why")]
    assert kpis(p, plan.assignments)["total_tardiness_min"] == 50
