"""Plan the live synthetic generation, replay it against real stops and store the result.

python -m linecopilot.plan

Builds the shortage result and the problem from `synthetic.*`, solves with CP-SAT, EDD with family
batching, EDD and FIFO, replays each plan in the 8 windows of real PIADE stops and writes
`plan.*`."""

from __future__ import annotations

import statistics

import psycopg

from linecopilot.config import get_settings
from linecopilot.plan import cpsat, dispatch, replay, store
from linecopilot.plan.load import load_problem
from linecopilot.plan.model import kpis, split_unschedulable


def main() -> int:
    with psycopg.connect(get_settings().database_url) as conn:
        gen = conn.execute(
            "SELECT generation_id, seed FROM synthetic.generation "
            "ORDER BY generation_id DESC LIMIT 1"
        ).fetchone()
        if gen is None:
            raise SystemExit("no synthetic data: run `make synth`")
        problem = split_unschedulable(load_problem(conn))
        plans = [
            cpsat.solve(problem),
            dispatch.edd_batch(problem),
            dispatch.edd(problem),
            dispatch.fifo(problem),
        ]
        wins = replay.windows(conn)
        machines = [m.machine_id for m in problem.machines]
        stops = [replay.stops(conn, w) for w in wins]
        stats = [replay.window_stats(conn, w, machines) for w in wins]
        replays = {
            p.algorithm: [
                (w, kpis(problem, replay.execute(problem, p, st)), s)
                for w, st, s in zip(wins, stops, stats, strict=True)
            ]
            for p in plans
        }
        ids = store.save(conn, plans, gen[0], f"make plan, seed {gen[1]}", replays)
    print(f"generation {gen[0]} seed {gen[1]}: {len(problem.jobs)} orders planned")
    for p in plans:
        k = p.kpis
        rep = [r[1]["total_tardiness_min"] for r in replays[p.algorithm]]
        print(
            f"  {p.algorithm:9s} run {ids[p.algorithm]} {p.status:12s} late {k['late_orders']:2d} "
            f"tardiness {k['total_tardiness_min']:6d} changeover {k['changeover_min']:4d} min; "
            f"replayed tardiness median {statistics.median(rep)}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
