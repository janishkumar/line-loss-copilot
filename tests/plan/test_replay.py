from datetime import UTC, datetime

from linecopilot.plan import dispatch
from linecopilot.plan.model import Assignment, Job, Machine, Plan, Problem, kpis
from linecopilot.plan.replay import (
    WINDOW_DAYS,
    Window,
    execute,
    merge,
    to_minutes,
    window_starts,
)


def co(fa, pa, fb, pb):
    return 0 if pa == pb else 10


def problem(avail=1.0):
    ms = (Machine("M1", 60, avail, frozenset({"A"})), Machine("M2", 60, avail, frozenset({"A"})))
    jobs = (
        Job("o1", "p1", "A", 60, 0, 100),  # 60 min
        Job("o2", "p2", "A", 60, 0, 100),  # 60 min, setup 10 after o1
        Job("o3", "p1", "A", 30, 50, 100, ready=70),
    )
    return Problem(jobs, ms, co)


def test_no_stops_equals_nominal_plan_at_availability_one():
    p = problem()
    for plan in (dispatch.fifo(p), dispatch.edd(p)):
        got = execute(p, plan, {})
        assert got == plan.assignments or sorted(got, key=lambda a: a.order_id) == sorted(
            plan.assignments, key=lambda a: a.order_id
        )
        assert kpis(p, got) == kpis(p, plan.assignments)


def test_stop_in_the_middle_of_a_job_delays_it_by_exactly_its_length():
    p = problem()
    plan = dispatch.edd(p)
    first = min((a for a in plan.assignments if a.machine_id == "M1"), key=lambda a: a.start)
    mid = first.start + 20
    got = {a.order_id: a for a in execute(p, plan, {"M1": [(mid, mid + 15)]})}
    base = {a.order_id: a for a in plan.assignments}
    assert got[first.order_id].start == first.start
    assert got[first.order_id].end == first.end + 15
    # the next job on that machine moves by the same amount, other machine untouched
    for a in plan.assignments:
        if a.machine_id == "M2":
            assert got[a.order_id] == base[a.order_id]


def test_sequence_and_machine_assignment_kept():
    p = problem()
    plan = dispatch.fifo(p)
    got = execute(p, plan, {"M1": [(5, 40)], "M2": [(0, 30)]})

    def seq(assigns):
        out = {}
        for a in sorted(assigns, key=lambda a: (a.start, a.order_id)):
            out.setdefault(a.machine_id, []).append(a.order_id)
        return out

    assert seq(got) == seq(plan.assignments)


def test_setup_only_progresses_while_machine_is_up():
    p = problem()
    plan = Plan(
        "x",
        [Assignment("o1", "M1", 0, 60, 0), Assignment("o2", "M1", 70, 130, 10)],
        [],
        "heuristic",
    )
    # a stop covers the first 5 minutes of the setup after job 1 ends
    got = {a.order_id: a for a in execute(p, plan, {"M1": [(60, 65)]})}
    assert (got["o2"].start, got["o2"].end) == (75, 135)
    # a stop during the setup that ends before it would have finished adds its length too
    got = {a.order_id: a for a in execute(p, plan, {"M1": [(63, 66)]})}
    assert got["o2"].start == 73


def test_job_never_starts_before_release_or_ready():
    p = problem()
    plan = dispatch.edd(p)
    got = execute(p, plan, {"M1": [(0, 3)], "M2": [(0, 3)]})
    jobs = {j.order_id: j for j in p.jobs}
    assert all(a.start >= max(jobs[a.order_id].release, jobs[a.order_id].ready) for a in got)


def test_starts_in_a_stop_wait_for_it_to_end():
    ms = (Machine("M1", 60, 1.0, frozenset({"A"})),)
    p = Problem((Job("o1", "p1", "A", 60, 10, 100),), ms, co)
    plan = dispatch.edd(p)
    (a,) = execute(p, plan, {"M1": [(0, 25)]})
    assert (a.start, a.end) == (25, 85)


def test_processing_uses_nominal_rate_not_availability():
    p = problem(avail=0.5)
    plan = dispatch.edd(p)
    got = execute(p, plan, {})
    assert max(a.end - a.start for a in got) < max(a.end - a.start for a in plan.assignments)
    assert {a.order_id: a.end - a.start for a in got}["o1"] == 60


def test_merge_and_to_minutes():
    assert merge([(5, 10), (8, 12), (20, 30), (30, 31), (2, 3)]) == [(2, 3), (5, 12), (20, 31)]
    w = Window(datetime(2021, 7, 1, tzinfo=UTC), datetime(2021, 7, 15, tzinfo=UTC))
    t0 = w.start
    assert to_minutes(w, [(t0.replace(hour=1), t0.replace(hour=1, minute=30))]) == [(60, 90)]
    # clipped to the window; a sub-half-minute stop rounds away, a 40 s stop to one minute
    before = datetime(2021, 6, 30, 23, 0, tzinfo=UTC)
    after = datetime(2021, 7, 15, 3, 0, tzinfo=UTC)
    assert to_minutes(
        w,
        [
            (before, t0.replace(minute=10)),
            (t0.replace(hour=2, minute=0, second=0), t0.replace(hour=2, second=10)),
        ],
    ) == [(0, 10)]
    assert to_minutes(w, [(w.end.replace(day=14, hour=23, minute=50), after)]) == [
        (20160 - 10, 20160)
    ]


def test_windows_start_dates():
    starts = window_starts()
    assert len(starts) == 8 and WINDOW_DAYS == 14
    assert starts[0] == datetime(2021, 7, 1, tzinfo=UTC)
    assert starts[1] == datetime(2021, 7, 15, tzinfo=UTC)
    assert all((b - a).days == 14 for a, b in zip(starts, starts[1:], strict=False))
    assert Assignment  # imported for type clarity
