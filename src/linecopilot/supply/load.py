"""Load the synthetic supply tables into the shortage engine's input."""

from __future__ import annotations

from collections import defaultdict

import psycopg

from linecopilot.supply.mrp import Order, Receipt, SupplyInput


def load_supply(conn: psycopg.Connection) -> SupplyInput:
    """Read `synthetic.*` as of the current content. Rates and availability come from
    `synthetic.machine_rate` (the stored, rounded values), never from raw anchors."""
    family = dict(conn.execute("SELECT product_id, family FROM synthetic.product").fetchall())
    eligible: dict[str, list[str]] = defaultdict(list)
    for machine, fam in conn.execute("SELECT machine_id, family FROM synthetic.machine_capability"):
        eligible[fam].append(machine)
    eff = {
        m: float(rate) * float(avail)
        for m, rate, avail in conn.execute(
            "SELECT machine_id, rate_per_hour, availability FROM synthetic.machine_rate"
        )
    }
    best_by_family = {
        fam: max(eff[m] for m in machines if m in eff)
        for fam, machines in eligible.items()
        if any(m in eff for m in machines)
    }  # a family with no rated machine is left out: its orders have no need date
    bom: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for parent, child, per in conn.execute(
        "SELECT parent_id, child_id, qty_per FROM synthetic.bom ORDER BY parent_id, child_id"
    ):
        bom[parent].append((child, float(per)))
    gen = conn.execute(
        "SELECT generation_id, seed, content_sha256 FROM synthetic.generation "
        "ORDER BY generation_id DESC LIMIT 1"
    ).fetchone()
    return SupplyInput(
        orders=[
            Order(oid, pid, float(q), rel, due)
            for oid, pid, q, rel, due in conn.execute(
                "SELECT order_id, product_id, quantity, release_at, due_at "
                "FROM synthetic.customer_order ORDER BY order_id"
            )
        ],
        bom=dict(bom),
        kinds=dict(conn.execute("SELECT material_id, kind FROM synthetic.material").fetchall()),
        stock={
            m: float(q) for m, q in conn.execute("SELECT material_id, on_hand FROM synthetic.stock")
        },
        receipts=[
            Receipt(m, float(q), due)
            for m, q, due in conn.execute(
                "SELECT material_id, qty, due_at FROM synthetic.receipt ORDER BY receipt_id"
            )
        ],
        best_rate={p: best_by_family[f] for p, f in family.items() if f in best_by_family},
        generation_id=gen[0] if gen else None,
        seed=gen[1] if gen else None,
        content_sha256=gen[2] if gen else None,
    )
