"""Scheduling data model and the shared definitions every algorithm uses.

Times are integer minutes from the horizon start. Processing minutes are
ceil(quantity / (rate x availability) x 60). Changeover semantics, shared by CP-SAT, FIFO and
EDD through `setup_minutes`: the first job on a machine has no setup (the machine is assumed
set up for it at the horizon start); between consecutive jobs the setup is `problem.changeover`,
which is zero for the same product. A setup runs on the machine immediately before the job, so
a job starts no earlier than the previous end plus the setup.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Job:
    order_id: str
    product_id: str
    family: str
    quantity: float
    release: int
    due: int
    ready: int = 0  # materials covered from this minute


@dataclass(frozen=True)
class Machine:
    machine_id: str
    rate_per_hour: float
    availability: float
    families: frozenset[str]


@dataclass(frozen=True)
class Problem:
    jobs: tuple[Job, ...]
    machines: tuple[Machine, ...]
    changeover: Callable[[str, str, str, str], int]  # (fam_a, prod_a, fam_b, prod_b) -> minutes
    horizon: int = 20160
    blocked: tuple[tuple[str, str], ...] = ()  # (order_id, reason), not schedulable


@dataclass(frozen=True)
class Assignment:
    order_id: str
    machine_id: str
    start: int
    end: int
    setup_before: int


@dataclass
class Plan:
    algorithm: str
    assignments: list[Assignment]
    blocked: list[tuple[str, str]]
    status: str
    objective: float | None = None
    bound: float | None = None
    kpis: dict = field(default_factory=dict)


def process_minutes(job: Job, machine: Machine) -> int:
    return math.ceil(job.quantity / (machine.rate_per_hour * machine.availability) * 60)


def eligible(problem: Problem, job: Job) -> list[Machine]:
    return [m for m in problem.machines if job.family in m.families]


def setup_minutes(problem: Problem, prev: Job | None, job: Job) -> int:
    if prev is None:
        return 0
    return int(problem.changeover(prev.family, prev.product_id, job.family, job.product_id))


def kpis(problem: Problem, assignments: list[Assignment]) -> dict:
    due = {j.order_id: j.due for j in problem.jobs}
    late = [a for a in assignments if a.end > due[a.order_id]]
    return {
        "late_orders": len(late),
        "total_tardiness_min": sum(a.end - due[a.order_id] for a in late),
        "changeover_min": sum(a.setup_before for a in assignments),
        "makespan": max((a.end for a in assignments), default=0),
        "scheduled_orders": len(assignments),
        "blocked_orders": len(problem.blocked),
    }


def objective(k: dict) -> float:
    return k["total_tardiness_min"] + 0.1 * k["changeover_min"]
