import itertools

import pytest
from ortools.sat.python import cp_model

from linecopilot.plan import cpsat, dispatch
from linecopilot.plan.model import (
    Assignment,
    Job,
    Machine,
    Problem,
    eligible,
    kpis,
    objective,
    process_minutes,
    setup_minutes,
)


def co(fa, pa, fb, pb):
    return 0 if pa == pb else (5 if fa == fb else 30)


def brute(problem):
    """Best objective over every machine assignment and per-machine order, jobs started as
    early as release, ready and setups allow."""
    jobs = list(problem.jobs)
    best = None
    choices = [eligible(problem, j) for j in jobs]
    for pick in itertools.product(*choices):
        for perm in itertools.permutations(range(len(jobs))):
            free, last, out = {}, {}, []
            for i in perm:
                m = pick[i].machine_id
                setup = setup_minutes(problem, last.get(m), jobs[i])
                st = max(free.get(m, 0) + setup, jobs[i].release, jobs[i].ready)
                en = st + process_minutes(jobs[i], pick[i])
                out.append(Assignment(jobs[i].order_id, m, st, en, setup))
                free[m], last[m] = en, jobs[i]
            v = objective(kpis(problem, out))
            best = v if best is None else min(best, v)
    return best


def three_by_two():
    ms = (Machine("M1", 60, 1.0, frozenset({"A", "B"})), Machine("M2", 30, 1.0, frozenset({"A"})))
    jobs = (
        Job("o1", "p1", "A", 60, 0, 70),
        Job("o2", "p2", "B", 60, 0, 75, ready=10),
        Job("o3", "p3", "A", 30, 5, 70),
    )
    return Problem(jobs, ms, co)


def test_matches_brute_force_optimum():
    p = three_by_two()
    plan = cpsat.solve(p, time_limit_s=5)
    assert plan.status == "OPTIMAL"
    assert objective(plan.kpis) == pytest.approx(brute(p))
    assert plan.objective == pytest.approx(brute(p))
    assert plan.bound == pytest.approx(plan.objective)


def test_never_worse_than_baselines():
    p = three_by_two()
    plan = cpsat.solve(p, time_limit_s=5)
    assert plan.objective <= dispatch.edd(p).objective + 1e-9
    assert plan.objective <= dispatch.fifo(p).objective + 1e-9


def test_eligibility_release_ready_and_setups_hold():
    p = three_by_two()
    plan = cpsat.solve(p, time_limit_s=5)
    jobs = {j.order_id: j for j in p.jobs}
    ms = {m.machine_id: m for m in p.machines}
    assert len(plan.assignments) == 3
    for a in plan.assignments:
        j = jobs[a.order_id]
        assert j.family in ms[a.machine_id].families
        assert a.start >= max(j.release, j.ready)
        assert a.end - a.start == process_minutes(j, ms[a.machine_id])
    for m in ms:
        seq = sorted((a for a in plan.assignments if a.machine_id == m), key=lambda a: a.start)
        for prev, cur in zip(seq, seq[1:], strict=False):
            want = setup_minutes(p, jobs[prev.order_id], jobs[cur.order_id])
            assert cur.setup_before == want and cur.start >= prev.end + want
        if seq:
            assert seq[0].setup_before == 0


def test_setup_between_families_is_present_when_forced():
    ms = (Machine("M1", 60, 1.0, frozenset({"A", "B"})),)
    jobs = (Job("o1", "p1", "A", 60, 0, 999), Job("o2", "p2", "B", 60, 0, 999))
    plan = cpsat.solve(Problem(jobs, ms, co), time_limit_s=5)
    assert plan.kpis["changeover_min"] == 30


def test_empty_problem():
    plan = cpsat.solve(Problem((), (Machine("M1", 1, 1, frozenset("A")),), co))
    assert plan.assignments == [] and plan.status == "OPTIMAL"


def test_blocked_orders_pass_through_and_are_not_scheduled():
    p = three_by_two()
    p = Problem(p.jobs, p.machines, co, blocked=(("o9", "no eligible machine"),))
    plan = cpsat.solve(p, time_limit_s=5)
    assert plan.blocked == [("o9", "no eligible machine")]
    assert "o9" not in {a.order_id for a in plan.assignments}


def test_no_solution_falls_back_to_edd_with_status(monkeypatch):
    class Dead(cp_model.CpSolver):
        def Solve(self, *a, **k):
            return cp_model.UNKNOWN

    monkeypatch.setattr(cpsat.cp_model, "CpSolver", Dead)
    p = three_by_two()
    plan = cpsat.solve(p, time_limit_s=1)
    assert plan.status == "fallback_edd"
    assert plan.assignments == dispatch.edd(p).assignments


def test_deterministic():
    p = three_by_two()
    a = cpsat.solve(p, time_limit_s=5)
    b = cpsat.solve(p, time_limit_s=5)
    assert a.assignments == b.assignments and a.objective == b.objective
