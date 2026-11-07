"""First-in-first-out and earliest-due-date list schedules (the baselines)."""

from __future__ import annotations

from linecopilot.plan.model import (
    Assignment,
    Job,
    Plan,
    Problem,
    eligible,
    kpis,
    objective,
    process_minutes,
    setup_minutes,
    split_unschedulable,
)


def _list_schedule(problem: Problem, order: list[Job], name: str) -> Plan:
    free: dict[str, int] = {m.machine_id: 0 for m in problem.machines}
    last: dict[str, Job | None] = {m.machine_id: None for m in problem.machines}
    out: list[Assignment] = []
    for job in order:
        best = None
        for m in sorted(eligible(problem, job), key=lambda m: m.machine_id):
            setup = setup_minutes(problem, last[m.machine_id], job)
            start = max(free[m.machine_id] + setup, job.release, job.ready)
            end = start + process_minutes(job, m)
            if best is None or end < best[0]:
                best = (end, m, start, setup)
        if best is None:
            continue  # no eligible machine: the loader blocks these, so only a hand-built problem
        end, m, start, setup = best
        out.append(Assignment(job.order_id, m.machine_id, start, end, setup))
        free[m.machine_id], last[m.machine_id] = end, job
    k = kpis(problem, out)
    return Plan(name, out, list(problem.blocked), "heuristic", objective(k), None, k)


def fifo(problem: Problem) -> Plan:
    problem = split_unschedulable(problem)
    return _list_schedule(
        problem, sorted(problem.jobs, key=lambda j: (j.release, j.order_id)), "fifo"
    )


def edd(problem: Problem) -> Plan:
    problem = split_unschedulable(problem)
    return _list_schedule(problem, sorted(problem.jobs, key=lambda j: (j.due, j.order_id)), "edd")


# EDD with family batching: the slack window, in minutes (24 h) from the earliest due date among
# the jobs a machine could take next.
BATCH_SLACK_MIN = 1440


def edd_batch(problem: Problem, slack: int = BATCH_SLACK_MIN) -> Plan:
    """Dispatch rule, a stronger baseline than plain EDD because it looks at changeovers.

    Repeat until every job is placed: take the machine that frees up first (ties by id) among
    those with an eligible job left. Among that machine's eligible waiting jobs, find the one
    with the earliest due date; every job due within `slack` minutes of it is a candidate, and
    the machine takes the candidate of the same family as its last job if there is one (the
    earliest due such job, same product first), otherwise the earliest due job. It then starts
    at max(free + setup, release, ready). The window trades a little tardiness for fewer
    changeovers; 24 h is a round figure, not tuned on these instances."""
    problem = split_unschedulable(problem)
    free = {m.machine_id: 0 for m in problem.machines}
    last: dict[str, Job | None] = {m.machine_id: None for m in problem.machines}
    machines = {m.machine_id: m for m in problem.machines}
    waiting = sorted(problem.jobs, key=lambda j: (j.due, j.order_id))
    out: list[Assignment] = []
    while waiting:
        usable = [
            mid
            for mid in sorted(machines, key=lambda mid: (free[mid], mid))
            if any(waiting_job.family in machines[mid].families for waiting_job in waiting)
        ]
        if not usable:
            break  # unreachable after split_unschedulable
        mid = usable[0]
        m = machines[mid]
        cands = [j for j in waiting if j.family in m.families]
        window = [j for j in cands if j.due <= cands[0].due + slack]
        prev = last[mid]
        pick = window[0]
        if prev is not None:
            same = [j for j in window if j.family == prev.family]
            if same:
                pick = min(same, key=lambda j: (j.product_id != prev.product_id, j.due, j.order_id))
        setup = setup_minutes(problem, prev, pick)
        start = max(free[mid] + setup, pick.release, pick.ready)
        end = start + process_minutes(pick, m)
        out.append(Assignment(pick.order_id, mid, start, end, setup))
        free[mid], last[mid] = end, pick
        waiting.remove(pick)
    k = kpis(problem, out)
    return Plan("edd_batch", out, list(problem.blocked), "heuristic", objective(k), None, k)
