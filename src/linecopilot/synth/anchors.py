"""Real anchors for the synthetic generator, read from the database at generation time.

Rates come from mart.piade_ideal_rate (p95, packages per hour). Availability is
1 - stopped seconds / window seconds from PIADE stop episodes using only data before CUTOFF, so
nothing from the replay period (on or after 2021-07-01) leaks into a plan input. Changeover
minutes are the p25 and p75 of the brick line's SETUPS-CHANGEOVERS stops.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

import psycopg

CUTOFF = datetime(2021, 7, 1, tzinfo=UTC)
DEFAULT_AVAILABILITY = 0.90  # only if the database holds no PIADE events at all

RATE_SQL = "select machine_id, p95 from mart.piade_ideal_rate where p95 is not null order by 1"

# Window = first PIADE event of the machine to the cutoff (or its last event if that is earlier).
# Stopped seconds: episodes that start before the cutoff, clipped so none runs past it.
AVAILABILITY_SQL = """
with cov as (
    select machine_id,
           min(start_ts) as t0,
           least(max(end_ts), %(cutoff)s::timestamptz) as t1
    from core.event
    where source_system = 'piade' and start_ts < %(cutoff)s
    group by machine_id
), stopped as (
    select machine_id,
           sum(least(duration_s, extract(epoch from %(cutoff)s::timestamptz - start_ts))) as s
    from mart.stop_episode
    where source_system = 'piade' and start_ts < %(cutoff)s
    group by machine_id
)
select c.machine_id, c.t0, c.t1, extract(epoch from c.t1 - c.t0) as window_s,
       coalesce(s.s, 0) as stopped_s
from cov c left join stopped s using (machine_id)
order by 1
"""

# Same-family (p25) and cross-family (p75) changeover minutes from real brick stops.
CHANGEOVER_SQL = """
select count(*),
       percentile_cont(0.25) within group (order by duration_s),
       percentile_cont(0.75) within group (order by duration_s)
from core.event
where source_system = 'brick' and event_type = 'stop' and reason_code = 'SETUPS-CHANGEOVERS'
"""

DEFAULT_CHANGEOVER_MIN = (12, 19)


@dataclass
class Anchors:
    rates: dict[str, float]
    availability: dict[str, float]
    changeover_same_family_min: int = 12
    changeover_cross_family_min: int = 19
    sources: dict = field(default_factory=dict)


def load_anchors(conn: psycopg.Connection) -> Anchors:
    rates = {m: float(r) for m, r in conn.execute(RATE_SQL).fetchall()}
    avail: dict[str, float] = {}
    windows: dict[str, str] = {}
    for m, t0, t1, window_s, stopped_s in conn.execute(
        AVAILABILITY_SQL, {"cutoff": CUTOFF}
    ).fetchall():
        if m in rates and window_s and window_s > 0:
            avail[m] = max(0.0, min(1.0, 1 - float(stopped_s) / float(window_s)))
            windows[m] = (
                f"{t0.date().isoformat()}..{t1.date().isoformat()} (before {CUTOFF.date()})"
            )
    # A machine with no data before the cutoff falls back to its availability over all its data,
    # and failing that to the mean of the other machines; the window records which.
    missing = [m for m in rates if m not in avail]
    if missing:
        rows = conn.execute(
            """
            with cov as (select machine_id, min(start_ts) t0, max(end_ts) t1 from core.event
                         where source_system = 'piade' group by 1),
            stopped as (select machine_id, sum(duration_s) s from mart.stop_episode
                        where source_system = 'piade' group by 1)
            select c.machine_id, c.t0, c.t1, extract(epoch from c.t1 - c.t0), coalesce(s.s, 0)
            from cov c left join stopped s using (machine_id)
            """
        ).fetchall()
        for m, t0, t1, window_s, stopped_s in rows:
            if m in missing and window_s and window_s > 0:
                avail[m] = max(0.0, min(1.0, 1 - float(stopped_s) / float(window_s)))
                windows[m] = (
                    f"{t0.date().isoformat()}..{t1.date().isoformat()} "
                    f"(fallback: all data, none before {CUTOFF.date()})"
                )
    for m in rates:
        if m not in avail:
            known = list(avail.values())
            avail[m] = sum(known) / len(known) if known else DEFAULT_AVAILABILITY
            windows[m] = "fallback: mean of other machines" if known else "fallback: default 0.90"
    n, p25, p75 = conn.execute(CHANGEOVER_SQL).fetchone()
    if n:
        same, cross = round(float(p25) / 60), round(float(p75) / 60)
    else:
        same, cross = DEFAULT_CHANGEOVER_MIN
    cross = max(cross, same)
    return Anchors(
        rates=rates,
        availability=avail,
        changeover_same_family_min=same,
        changeover_cross_family_min=cross,
        sources={
            "rate": "mart.piade_ideal_rate.p95 (packages per hour)",
            "availability_window": windows,
            "availability_cutoff": CUTOFF.isoformat(),
            "changeover": (
                f"brick SETUPS-CHANGEOVERS stops, n={n}, p25/p75 rounded to minutes"
                if n
                else "default (no brick changeover stops in the database)"
            ),
        },
    )
