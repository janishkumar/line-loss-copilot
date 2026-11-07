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
