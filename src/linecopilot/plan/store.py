"""Store plans and their replays in the `plan` schema (owner writes, agent reads)."""

from __future__ import annotations

from datetime import timedelta

import psycopg
from psycopg.types.json import Jsonb

from linecopilot.plan.model import Plan
from linecopilot.plan.replay import Window
from linecopilot.synth.generate import HORIZON_START

Replays = dict[str, list[tuple[Window, dict, dict]]]  # algorithm -> (window, kpis, stats)


def save(
    conn: psycopg.Connection,
    plans: list[Plan],
    generation_id: int | None,
    label: str,
    replays: Replays | None = None,
) -> dict[str, int]:
    """Insert one plan_run per plan with its assignments, blocked orders and replay results, in
    one transaction. Returns algorithm -> plan_run_id. Earlier runs are kept."""
    replays = replays or {}
    ids: dict[str, int] = {}
    with conn.transaction():
        for p in plans:
            rid = conn.execute(
                "INSERT INTO plan.plan_run (generation_id, algorithm, status, solver_status, "
                "stop_reason, objective, bound, kpis, label) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING plan_run_id",
                (
                    generation_id,
                    p.algorithm,
                    p.status,
                    p.solver_status,
                    p.stop_reason,
                    p.objective,
                    p.bound,
                    Jsonb(p.kpis),
                    label,
                ),
            ).fetchone()[0]
            ids[p.algorithm] = rid
            with conn.cursor() as cur:
                cur.executemany(
                    "INSERT INTO plan.assignment (plan_run_id, order_id, machine_id, start_at, "
                    "end_at, setup_min) VALUES (%s, %s, %s, %s, %s, %s)",
                    [
                        (
                            rid,
                            a.order_id,
                            a.machine_id,
                            HORIZON_START + timedelta(minutes=a.start),
                            HORIZON_START + timedelta(minutes=a.end),
                            a.setup_before,
                        )
                        for a in p.assignments
                    ],
                )
                cur.executemany(
                    "INSERT INTO plan.blocked (plan_run_id, order_id, reason) VALUES (%s, %s, %s)",
                    [(rid, o, why) for o, why in p.blocked],
                )
                cur.executemany(
                    "INSERT INTO plan.replay_result (plan_run_id, window_start, window_end, "
                    "kpis, machine_stats) VALUES (%s, %s, %s, %s, %s)",
                    [
                        (rid, w.start, w.end, Jsonb(k), Jsonb(s))
                        for w, k, s in replays.get(p.algorithm, [])
                    ],
                )
    return ids


def latest(conn: psycopg.Connection) -> list[dict]:
    """The newest plan_run of each algorithm, with assignments, blocked and replays."""
    out = []
    runs = conn.execute(
        "SELECT DISTINCT ON (algorithm) plan_run_id, generation_id, algorithm, status, "
        "solver_status, stop_reason, objective, bound, kpis, label, created_at, is_synthetic "
        "FROM plan.plan_run ORDER BY algorithm, plan_run_id DESC"
    ).fetchall()
    for r in runs:
        rid = r[0]
        out.append(
            {
                "plan_run_id": rid,
                "generation_id": r[1],
                "algorithm": r[2],
                "status": r[3],
                "solver_status": r[4],
                "stop_reason": r[5],
                "objective": r[6],
                "bound": r[7],
                "kpis": r[8],
                "label": r[9],
                "created_at": r[10],
                "is_synthetic": r[11],
                "assignments": [
                    {
                        "order_id": o,
                        "machine_id": m,
                        "start_at": s,
                        "end_at": e,
                        "setup_min": u,
                    }
                    for o, m, s, e, u in conn.execute(
                        "SELECT order_id, machine_id, start_at, end_at, setup_min "
                        "FROM plan.assignment WHERE plan_run_id = %s ORDER BY start_at, order_id",
                        (rid,),
                    )
                ],
                "blocked": [
                    {"order_id": o, "reason": why}
                    for o, why in conn.execute(
                        "SELECT order_id, reason FROM plan.blocked WHERE plan_run_id = %s "
                        "ORDER BY order_id",
                        (rid,),
                    )
                ],
                "replays": [
                    {"window_start": ws, "window_end": we, "kpis": k, "machine_stats": ms}
                    for ws, we, k, ms in conn.execute(
                        "SELECT window_start, window_end, kpis, machine_stats "
                        "FROM plan.replay_result WHERE plan_run_id = %s ORDER BY window_start",
                        (rid,),
                    )
                ],
            }
        )
    return out
