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


def _best_placement(problem: Problem, job: Job, free, last):
    """The eligible machine where `job` finishes first (ties by machine id): the rule FIFO, EDD
    and edd_batch all use. Returns (end, machine, start, setup) or None."""
    best = None
    for m in sorted(eligible(problem, job), key=lambda m: m.machine_id):
        setup = setup_minutes(problem, last[m.machine_id], job)
        start = max(free[m.machine_id] + setup, job.release, job.ready)
        end = start + process_minutes(job, m)
        if best is None or end < best[0]:
            best = (end, m, start, setup)
    return best


def _list_schedule(problem: Problem, order: list[Job], name: str) -> Plan:
    free: dict[str, int] = {m.machine_id: 0 for m in problem.machines}
    last: dict[str, Job | None] = {m.machine_id: None for m in problem.machines}
    out: list[Assignment] = []
    for job in order:
        best = _best_placement(problem, job, free, last)
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
# the jobs still waiting.
BATCH_SLACK_MIN = 1440


def edd_batch(problem: Problem, slack: int = BATCH_SLACK_MIN) -> Plan:
    """EDD with changeover-aware job order. Machines are chosen exactly as in EDD (earliest
    finish); only the order of jobs differs.

    Repeat until every job is placed: take the earliest due waiting job and the machine where it
    would finish first. Every waiting job due within `slack` minutes of it and eligible on that
    machine is a candidate; if the machine's last job has a family and a candidate shares it,
    the pick is the earliest due such candidate (same product first), otherwise the earliest due
    job. The pick is then placed on its own earliest-finish machine. When batching changes
    nothing, the schedule equals plain EDD. The window trades a little tardiness for fewer
    changeovers; 24 h is a round figure, not tuned on these instances."""
    problem = split_unschedulable(problem)
    free = {m.machine_id: 0 for m in problem.machines}
    last: dict[str, Job | None] = {m.machine_id: None for m in problem.machines}
    waiting = sorted(problem.jobs, key=lambda j: (j.due, j.order_id))
    out: list[Assignment] = []
    while waiting:
        head = waiting[0]
        first = _best_placement(problem, head, free, last)
        if first is None:
            waiting.pop(0)  # unreachable after split_unschedulable
            continue
        m0 = first[1]
        prev = last[m0.machine_id]
        pick = head
        if prev is not None:
            same = [
                j
                for j in waiting
                if j.due <= head.due + slack and j.family in m0.families and j.family == prev.family
            ]
            if same:
                pick = min(same, key=lambda j: (j.product_id != prev.product_id, j.due, j.order_id))
        end, m, start, setup = _best_placement(problem, pick, free, last)
        out.append(Assignment(pick.order_id, m.machine_id, start, end, setup))
        free[m.machine_id], last[m.machine_id] = end, pick
        waiting.remove(pick)
    k = kpis(problem, out)
    return Plan("edd_batch", out, list(problem.blocked), "heuristic", objective(k), None, k)
