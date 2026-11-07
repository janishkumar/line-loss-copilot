"""MRP-style shortage netting traced to orders (synthetic data, design 10.2).

Pure functions, no database. Definitions (shared with the generator, so a perfect eval score
shows the code implements them, not real-world accuracy):

- Need time of an order: due_at minus its processing minutes (ceil, whole minutes) on the
  fastest eligible machine at rate x availability.
- Orders are netted in (need time, order_id) order. Per order, sub-assemblies are netted first
  against stock plus receipts due at or before the need time (minus what earlier orders took);
  what is uncovered explodes to its children, which are then netted the same way. Only raw
  materials are reported as shortfalls, one per (material, order), with the first short time
  (the order's need time), the short quantity and the BOM level that created the requirement.
- A receipt due exactly at the need time counts as in time.
- An earlier order consumes its full requirement even when it is itself short, so a later order
  never sees stock an earlier one was already promised.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

EPS = 1e-9
Bom = Mapping[str, Sequence[tuple[str, float]]]


@dataclass(frozen=True)
class Order:
    order_id: str
    product_id: str
    quantity: float
    release_at: datetime
    due_at: datetime


@dataclass(frozen=True)
class Receipt:
    material_id: str
    qty: float
    due_at: datetime


@dataclass(frozen=True)
class Requirement:
    order_id: str
    material_id: str
    qty: float
    need_at: datetime


@dataclass(frozen=True)
class Shortfall:
    material_id: str
    order_id: str
    short_qty: float
    first_short_at: datetime
    level: int


@dataclass(frozen=True)
class ProjectedPoint:
    at: datetime
    projected: float  # stock after this event
    delta: float
    reason: str  # opening stock, receipt:<id> or allocation:<order>


def need_time(due_at: datetime, quantity: float, best_rate_per_hour: float) -> datetime:
    return due_at - timedelta(minutes=math.ceil(quantity / best_rate_per_hour * 60))


def no_need_date(
    orders: Iterable[Order], best_rate: Mapping[str, float]
) -> list[tuple[Order, str]]:
    """Orders that cannot be given a need date (their product has no eligible machine, or a
    rate of zero), with the reason. `explode` leaves them out; they are unschedulable."""
    return [
        (o, "no eligible machine" if o.product_id not in best_rate else "rate is zero")
        for o in orders
        if not best_rate.get(o.product_id, 0) > 0
    ]


def explode(orders: Iterable[Order], bom: Bom, best_rate: Mapping[str, float]) -> list[Requirement]:
    """Level-one requirements: the direct BOM children of each order's product, at the order's
    need time. `best_rate` is product_id -> rate x availability of its fastest eligible machine
    (packages per hour). Deeper levels are found by `net`, after netting sub-assembly stock."""
    out = []
    for o in orders:
        if not best_rate.get(o.product_id, 0) > 0:
            continue  # reported by no_need_date
        need = need_time(o.due_at, o.quantity, best_rate[o.product_id])
        for child, per in bom.get(o.product_id, []):
            out.append(Requirement(o.order_id, child, o.quantity * per, need))
    return out


def net(
    requirements: Iterable[Requirement],
    stock: Mapping[str, float],
    receipts: Sequence[Receipt],
    bom: Bom,
    kinds: Mapping[str, str],
) -> tuple[list[Shortfall], dict[str, list[ProjectedPoint]]]:
    """Net level-one requirements against stock and receipts, in (need time, order_id) order.
    Returns the traced raw-material shortfalls and, per material, the projected stock after each
    receipt and allocation. A material with no stock row counts as zero on hand."""
    by_order: dict[str, list[Requirement]] = defaultdict(list)
    for r in requirements:
        by_order[r.order_id].append(r)
    receipts_by: dict[str, list[Receipt]] = defaultdict(list)
    for rc in receipts:
        receipts_by[rc.material_id].append(rc)

    used: dict[str, float] = defaultdict(float)
    allocations: dict[str, list[tuple[datetime, str, float]]] = defaultdict(list)
    shortfalls: list[Shortfall] = []

    def available(material: str, at: datetime) -> float:
        got = float(stock.get(material, 0.0))
        got += sum(rc.qty for rc in receipts_by[material] if rc.due_at <= at)
        return got - used[material]

    for oid, reqs in sorted(by_order.items(), key=lambda kv: (kv[1][0].need_at, kv[0])):
        at = reqs[0].need_at
        raw: dict[str, list[float]] = {}  # material -> [qty, shallowest level]

        def need(material: str, qty: float, level: int, path=(), oid=oid, at=at, raw=raw) -> None:
            if material in path:
                raise ValueError(f"BOM cycle through {material}: {' > '.join((*path, material))}")
            if qty <= EPS:
                return
            if kinds.get(material, "raw") == "subassembly":
                take = min(max(available(material, at), 0.0), qty)
                used[material] += take
                if take:
                    allocations[material].append((at, oid, take))
                for child, per in bom.get(material, []):
                    need(child, (qty - take) * per, level + 1, (*path, material))
            else:
                cur = raw.setdefault(material, [0.0, level])
                cur[0] += qty
                cur[1] = min(cur[1], level)

        for r in reqs:
            need(r.material_id, r.qty, 1)
        for material, (qty, level) in sorted(raw.items()):
            avail = available(material, at)
            if qty > avail + EPS:
                shortfalls.append(Shortfall(material, oid, min(qty, qty - avail), at, level))
            used[material] += qty
            allocations[material].append((at, oid, qty))

    projection: dict[str, list[ProjectedPoint]] = {}
    for material in sorted(set(allocations) | set(receipts_by) | set(stock)):
        events = [(rc.due_at, 0, rc.qty, "receipt") for rc in receipts_by[material]]
        events += [(a, 1, -q, f"allocation:{o}") for a, o, q in allocations[material]]
        events.sort(key=lambda e: (e[0], e[1], e[3]))
        level = float(stock.get(material, 0.0))
        if events:
            pts = [ProjectedPoint(events[0][0], level, 0.0, "opening stock")]
            for t, _, delta, why in events:
                level += delta
                pts.append(ProjectedPoint(t, level, delta, why))
            projection[material] = pts
    return shortfalls, projection


@dataclass(frozen=True)
class SupplyInput:
    """Everything the shortage engine reads, from `synthetic.*` (or built by hand in tests)."""

    orders: list[Order]
    bom: dict[str, list[tuple[str, float]]]
    kinds: dict[str, str]
    stock: dict[str, float]
    receipts: list[Receipt]
    best_rate: dict[str, float]  # product_id -> fastest eligible rate x availability, per hour
    generation_id: int | None = None
    seed: int | None = None
    content_sha256: str | None = None


def detect(s: SupplyInput) -> tuple[list[Shortfall], dict[str, list[ProjectedPoint]]]:
    return net(explode(s.orders, s.bom, s.best_rate), s.stock, s.receipts, s.bom, s.kinds)


def naive_rule(
    orders: Iterable[Order], bom: Bom, stock: Mapping[str, float]
) -> list[tuple[str, str]]:
    """The simple baseline: a material is short if on hand is below its total gross requirement
    (explosion through every BOM level, no stock netting between levels, no receipts, no
    timing). Every order that uses the material is flagged, sub-assemblies included. Returns
    sorted (material, order_id) pairs."""
    gross: dict[str, float] = defaultdict(float)
    users: dict[str, set[str]] = defaultdict(set)

    def walk(parent: str, qty: float, oid: str, path: tuple[str, ...] = ()) -> None:
        if parent in path:
            raise ValueError(f"BOM cycle through {parent}: {' > '.join((*path, parent))}")
        for child, per in bom.get(parent, []):
            gross[child] += qty * per
            users[child].add(oid)
            walk(child, qty * per, oid, (*path, parent))

    for o in orders:
        walk(o.product_id, o.quantity, o.order_id)
    return sorted(
        (m, oid) for m in gross if float(stock.get(m, 0.0)) < gross[m] for oid in users[m]
    )
