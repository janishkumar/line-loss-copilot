"""Build a scheduling Problem from the synthetic tables and the shortage engine's result."""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Iterable
from datetime import datetime, timedelta

import psycopg

from linecopilot.plan.model import Job, Machine, Problem
from linecopilot.supply.load import load_supply, supply_from_synth
from linecopilot.supply.mrp import SupplyInput, detect, material_ready
from linecopilot.synth.generate import HORIZON_START, SynthData


def _minutes(t: datetime, start: datetime, up: bool) -> int:
    x = (t - start).total_seconds() / 60
    return max(0, math.ceil(x) if up else math.floor(x))


def build_problem(
    s: SupplyInput,
    supply_result,
    family: dict[str, str],
    capability: Iterable[tuple[str, str]],
    machine_rows: Iterable[tuple[str, float, float]],
    changeover_rows: Iterable[tuple[str, str, bool, int]],
    start: datetime = HORIZON_START,
) -> Problem:
    """The pure core shared by the database loader and the in-memory (eval) path.

    `machine_rows` are (machine_id, rate_per_hour, availability) as stored, `capability` is
    (machine_id, family) and `changeover_rows` (from_family, to_family, same_product, minutes)."""
    _, projection = supply_result if supply_result is not None else detect(s)
    ready = material_ready(projection, s.kinds, start + timedelta(minutes=20160))
    caps: dict[str, set[str]] = defaultdict(set)
    for m, fam in capability:
        caps[m].add(fam)
    machines = tuple(
        Machine(
            m, float(r), float(a), frozenset(caps.get(m, ())) if r > 0 and a > 0 else frozenset()
        )
        for m, r, a in sorted(machine_rows)
    )
    able = {f for m in machines for f in m.families}
    table = {(a, b, bool(same)): int(mins) for a, b, same, mins in changeover_rows}

    def changeover(fa: str, pa: str, fb: str, pb: str) -> int:
        if pa == pb:
            return 0
        return table[(fa, fb, False)]

    jobs, blocked = [], []
    for o in s.orders:
        fam = family.get(o.product_id)
        if o.quantity <= 0:
            blocked.append((o.order_id, "non-positive quantity"))
            continue
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


def load_problem(conn: psycopg.Connection, supply_result=None, start: datetime = HORIZON_START):
    """`supply_result` is `detect(load_supply(conn))`, computed here when omitted."""
    s = load_supply(conn)
    return build_problem(
        s,
        supply_result,
        dict(conn.execute("SELECT product_id, family FROM synthetic.product").fetchall()),
        conn.execute("SELECT machine_id, family FROM synthetic.machine_capability").fetchall(),
        conn.execute(
            "SELECT machine_id, rate_per_hour, availability FROM synthetic.machine_rate"
        ).fetchall(),
        conn.execute(
            "SELECT from_family, to_family, same_product, minutes FROM synthetic.changeover"
        ).fetchall(),
        start,
    )


def problem_from_synth(data: SynthData, start: datetime = HORIZON_START) -> Problem:
    """The same Problem `load_problem` gives after `write(data)`, built without the database."""
    return build_problem(
        supply_from_synth(data),
        None,
        {p["product_id"]: p["family"] for p in data.product},
        [(c["machine_id"], c["family"]) for c in data.machine_capability],
        [(r["machine_id"], r["rate_per_hour"], r["availability"]) for r in data.machine_rate],
        [
            (c["from_family"], c["to_family"], c["same_product"], c["minutes"])
            for c in data.changeover
        ],
        start,
    )
