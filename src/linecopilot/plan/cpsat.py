"""CP-SAT schedule: optional (job, machine) intervals, one circuit per machine for the sequence.

Objective (integers): 10 x total tardiness + changeover minutes, which is 10 x (tardiness +
0.1 x changeover). Hinted from the EDD plan. Deterministic: one worker, fixed seed.
"""

from __future__ import annotations

from ortools.sat.python import cp_model

from linecopilot.plan import dispatch
from linecopilot.plan.model import (
    Assignment,
    Plan,
    Problem,
    eligible,
    kpis,
    objective,
    process_minutes,
    setup_minutes,
    split_unschedulable,
)

SCALE = 10
# Stop on deterministic time so the result is reproducible across machines and load; the
# wall-clock limit is only a safety cap. On the live instance (42 jobs, 5 machines) 20 gives
# objective 6128, 60 gives 3617 (gap 0.8%, about 30 s wall on the dev Mac), 120 gives 3612 and
# 250 gives 3610 (bound 3589), so 60 is where returns flatten.
MAX_DETERMINISTIC_TIME = 60.0


def _det_time(solver: cp_model.CpSolver) -> float:
    try:
        return solver.ResponseProto().deterministic_time
    except RuntimeError:  # no response (solver never ran)
        return 0.0


def _wall_time(solver: cp_model.CpSolver) -> float:
    try:
        return solver.WallTime()
    except RuntimeError:
        return 0.0


def solve(
    problem: Problem,
    time_limit_s: float = 120,
    seed: int = 0,
    max_deterministic_time: float = MAX_DETERMINISTIC_TIME,
) -> Plan:
    problem = split_unschedulable(problem)
    base = dispatch.edd(problem)
    if not problem.jobs:
        return Plan(
            "cpsat",
            [],
            list(problem.blocked),
            "OPTIMAL",
            0.0,
            0.0,
            kpis(problem, []),
            "OPTIMAL",
            "optimal",
        )

    jobs = {j.order_id: j for j in problem.jobs}
    ub = max(max(j.release, j.ready) for j in problem.jobs)
    ub += sum(max(process_minutes(j, m) for m in eligible(problem, j)) for j in problem.jobs)
    ub += sum(max(setup_minutes(problem, p, j) for p in problem.jobs) for j in problem.jobs)
    ub = max(ub, base.kpis["makespan"])

    model = cp_model.CpModel()
    hint = {a.order_id: a for a in base.assignments}
    pres, start, end, intervals = {}, {}, {}, {}
    by_machine: dict[str, list[str]] = {m.machine_id: [] for m in problem.machines}
    for j in problem.jobs:
        opts = []
        for m in eligible(problem, j):
            key = (j.order_id, m.machine_id)
            p = process_minutes(j, m)
            pres[key] = model.NewBoolVar(f"p_{key}")
            start[key] = model.NewIntVar(max(j.release, j.ready), ub, f"s_{key}")
            end[key] = model.NewIntVar(0, ub, f"e_{key}")
            intervals[key] = model.NewOptionalIntervalVar(
                start[key], p, end[key], pres[key], f"i_{key}"
            )
            by_machine[m.machine_id].append(j.order_id)
            opts.append(pres[key])
            h = hint.get(j.order_id)
            model.AddHint(pres[key], int(h is not None and h.machine_id == m.machine_id))
            if h is not None and h.machine_id == m.machine_id:
                model.AddHint(start[key], h.start)
        model.AddExactlyOne(opts)

    tard = {}
    for j in problem.jobs:
        tard[j.order_id] = model.NewIntVar(0, ub, f"t_{j.order_id}")
        job_end = model.NewIntVar(0, ub, f"E_{j.order_id}")
        for m in eligible(problem, j):
            model.Add(job_end == end[(j.order_id, m.machine_id)]).OnlyEnforceIf(
                pres[(j.order_id, m.machine_id)]
            )
        model.Add(tard[j.order_id] >= job_end - j.due)

    setup_terms = []
    arcs_by_machine: dict[str, dict] = {}
    hint_next: dict[tuple[str, str], tuple[str, str]] = {}
    last: dict[str, str] = {}
    for a in sorted(base.assignments, key=lambda a: a.start):
        prev = last.get(a.machine_id)
        hint_next[(a.machine_id, prev or "")] = (a.machine_id, a.order_id)
        last[a.machine_id] = a.order_id
    for m in problem.machines:
        ids = by_machine[m.machine_id]
        if not ids:
            continue
        node = {oid: i + 1 for i, oid in enumerate(ids)}
        arcs = []
        used = {}
        empty = model.NewBoolVar(f"empty_{m.machine_id}")
        arcs.append((0, 0, empty))
        model.AddBoolOr([pres[(oid, m.machine_id)] for oid in ids]).OnlyEnforceIf(empty.Not())
        for oid in ids:
            key = (oid, m.machine_id)
            model.AddImplication(empty, pres[key].Not())
            arcs.append((node[oid], node[oid], pres[key].Not()))
            first = model.NewBoolVar(f"first_{key}")
            lastv = model.NewBoolVar(f"last_{key}")
            arcs.append((0, node[oid], first))
            arcs.append((node[oid], 0, lastv))
            hf = hint_next.get((m.machine_id, ""))
            model.AddHint(first, int(hf is not None and hf[1] == oid))
            model.AddHint(lastv, int(last.get(m.machine_id) == oid))
            for o2 in ids:
                if o2 == oid:
                    continue
                lit = model.NewBoolVar(f"a_{oid}_{o2}_{m.machine_id}")
                arcs.append((node[oid], node[o2], lit))
                s = setup_minutes(problem, jobs[oid], jobs[o2])
                model.Add(start[(o2, m.machine_id)] >= end[key] + s).OnlyEnforceIf(lit)
                setup_terms.append(s * lit)
                used[(oid, o2)] = lit
                hn = hint_next.get((m.machine_id, oid))
                model.AddHint(lit, int(hn is not None and hn[1] == o2))
        model.AddCircuit(arcs)
        model.AddNoOverlap([intervals[(oid, m.machine_id)] for oid in ids])
        arcs_by_machine[m.machine_id] = used

    model.Minimize(SCALE * sum(tard.values()) + sum(setup_terms))
    solver = cp_model.CpSolver()
    solver.parameters.num_workers = 1
    solver.parameters.random_seed = seed
    solver.parameters.max_time_in_seconds = time_limit_s
    solver.parameters.max_deterministic_time = max_deterministic_time
    status = solver.Solve(model)
    name = cp_model.CpSolver.StatusName(solver, status)
    if status == cp_model.OPTIMAL:
        stop = "optimal"
    elif _det_time(solver) >= max_deterministic_time * 0.99:
        stop = "deterministic_time"
    elif _wall_time(solver) >= time_limit_s * 0.99:
        stop = "wall_clock"
    else:
        stop = "other"
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        base.algorithm = "cpsat"
        base.status = "fallback_edd"
        base.solver_status, base.stop_reason = name, stop
        return base

    chosen: dict[str, list[tuple[int, str]]] = {m.machine_id: [] for m in problem.machines}
    for (oid, mid), p in pres.items():
        if solver.BooleanValue(p):
            chosen[mid].append((solver.Value(start[(oid, mid)]), oid))
    out = []
    for m in problem.machines:
        prev = None
        for st, oid in sorted(chosen[m.machine_id]):
            j = jobs[oid]
            out.append(
                Assignment(
                    oid,
                    m.machine_id,
                    st,
                    st + process_minutes(j, m),
                    setup_minutes(problem, prev, j),
                )
            )
            prev = j
    out.sort(key=lambda a: (a.start, a.machine_id, a.order_id))
    k = kpis(problem, out)
    return Plan(
        "cpsat",
        out,
        list(problem.blocked),
        cp_model.CpSolver.StatusName(solver, status),
        objective(k),
        solver.BestObjectiveBound() / SCALE,
        k,
        name,
        stop,
    )
