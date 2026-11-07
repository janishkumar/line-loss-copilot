"""Build a scheduling Problem from the synthetic tables and the shortage engine's result."""

from __future__ import annotations

import math
from collections import defaultdict
from datetime import datetime

import psycopg

from linecopilot.plan.model import Job, Machine, Problem
from linecopilot.supply.load import load_supply
from linecopilot.supply.mrp import detect, material_ready
from linecopilot.synth.generate import HORIZON_START


def _minutes(t: datetime, start: datetime, up: bool) -> int:
    x = (t - start).total_seconds() / 60
    return max(0, math.ceil(x) if up else math.floor(x))


def load_problem(conn: psycopg.Connection, supply_result=None, start: datetime = HORIZON_START):
    """`supply_result` is `detect(load_supply(conn))`, computed here when omitted."""
    s = load_supply(conn)
    shortfalls, projection = supply_result if supply_result is not None else detect(s)
    ready = material_ready(shortfalls, projection)
    family = dict(conn.execute("SELECT product_id, family FROM synthetic.product").fetchall())
    caps: dict[str, set[str]] = defaultdict(set)
    for m, fam in conn.execute("SELECT machine_id, family FROM synthetic.machine_capability"):
        caps[m].add(fam)
    machines = tuple(
        Machine(m, float(r), float(a), frozenset(caps.get(m, ())))
        for m, r, a in conn.execute(
            "SELECT machine_id, rate_per_hour, availability FROM synthetic.machine_rate "
            "ORDER BY machine_id"
        )
    )
    able = {f for m in machines for f in m.families}
    table = {
        (a, b, bool(same)): int(mins)
        for a, b, same, mins in conn.execute(
            "SELECT from_family, to_family, same_product, minutes FROM synthetic.changeover"
        )
    }

    def changeover(fa: str, pa: str, fb: str, pb: str) -> int:
        if pa == pb:
            return 0
        return table[(fa, fb, False)]

    jobs, blocked = [], []
    for o in s.orders:
        fam = family.get(o.product_id)
        if fam is None or fam not in able:
            blocked.append((o.order_id, "no eligible machine"))
            continue
        at, missing = ready.get(o.order_id, (start, None))
        if at is None:
            blocked.append((o.order_id, f"material {missing} short with no receipt in horizon"))
            continue
        jobs.append(
            Job(
                o.order_id,
                o.product_id,
                fam,
                o.quantity,
                _minutes(o.release_at, start, True),
                _minutes(o.due_at, start, False),
                _minutes(at, start, True),
            )
        )
    return Problem(tuple(jobs), machines, changeover, 20160, tuple(blocked))
