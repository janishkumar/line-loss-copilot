"""Real anchors for the synthetic generator, read from the database at generation time.

Every anchor uses only rows that start before the cutoff (default 2021-07-01), so nothing from
the replay period reaches a plan input. The cutoff is a parameter so a test can show that.

- Rate: p95 of set speed over production intervals with speed above zero (packages per hour).
- Availability: 1 - stopped seconds / covered seconds. Covered seconds are the summed durations
  of the machine's PIADE state intervals (clipped at the cutoff); idle and planned off time
  count as available, and gaps with no data are not in the denominator. The idle, off and gap
  shares are recorded next to the figure.
- A machine with no pre-cutoff data gets the median of the other machines' values, recorded.
- Changeover minutes: p25 and p75 of the brick line's SETUPS-CHANGEOVERS stops (a different
  process, brick not PIADE), floored at 1 minute.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from datetime import UTC, datetime

import psycopg

CUTOFF = datetime(2021, 7, 1, tzinfo=UTC)
DEFAULT_AVAILABILITY = 0.90  # only if the database holds no pre-cutoff PIADE data at all

MACHINES_SQL = "select distinct machine_id from core.event where source_system = 'piade' order by 1"

RATE_SQL = """
select machine_id,
       percentile_cont(0.95) within group (order by speed) filter (where speed > 0) as p95
from mart.piade_interval_counts
where source_state = 'production' and start_ts < %(cutoff)s
group by machine_id
"""

COVERED_SQL = """
select machine_id,
       min(start_ts) as t0,
       least(max(end_ts), %(cutoff)s::timestamptz) as t1,
       sum(d) as covered_s,
       coalesce(sum(d) filter (where source_state = 'idle'), 0) as idle_s,
       coalesce(sum(d) filter (where source_state = 'scheduled_downtime'), 0) as off_s
from (
    select machine_id, source_state, start_ts, end_ts,
           least(duration_s, extract(epoch from %(cutoff)s::timestamptz - start_ts)) as d
    from mart.piade_interval_counts
    where start_ts < %(cutoff)s
) x
group by machine_id
"""

STOPPED_SQL = """
select machine_id,
       sum(least(duration_s, extract(epoch from %(cutoff)s::timestamptz - start_ts))) as stopped_s
from mart.stop_episode
where source_system = 'piade' and start_ts < %(cutoff)s
group by machine_id
"""

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


def load_anchors(conn: psycopg.Connection, cutoff: datetime = CUTOFF) -> Anchors:
    p = {"cutoff": cutoff}
    machines = [r[0] for r in conn.execute(MACHINES_SQL).fetchall()]
    rate = {m: float(v) for m, v in conn.execute(RATE_SQL, p).fetchall() if v is not None}
    stopped = {m: float(v) for m, v in conn.execute(STOPPED_SQL, p).fetchall()}
    avail: dict[str, float] = {}
    window: dict[str, str] = {}
    stats: dict[str, dict] = {}
    for m, t0, t1, covered, idle, off in conn.execute(COVERED_SQL, p).fetchall():
        covered = float(covered or 0)
        if covered <= 0:
            continue
        span = (t1 - t0).total_seconds()
        st = stopped.get(m, 0.0)
        avail[m] = max(0.0, min(1.0, 1 - st / covered))
        stats[m] = {
            "covered_s": covered,
            "stopped_s": st,
            "idle_share": float(idle) / covered,
            "off_share": float(off) / covered,
            "gap_share": max(0.0, 1 - covered / span) if span > 0 else 0.0,
        }
        window[m] = (
            f"{t0.date().isoformat()}..{t1.date().isoformat()} (before {cutoff.date()}); "
            f"idle {stats[m]['idle_share']:.3f}, planned off {stats[m]['off_share']:.3f}, "
            f"gaps {stats[m]['gap_share']:.3f} of the span"
        )
    if not rate:
        raise ValueError(f"no PIADE production data before {cutoff.date()}: cannot anchor rates")
    basis = {m: f"p95 of set speed, production rows before {cutoff.date()}" for m in rate}
    med_rate = statistics.median(rate.values())
    known_avail = list(avail.values())
    med_avail = statistics.median(known_avail) if known_avail else DEFAULT_AVAILABILITY
    fb = f"fallback: median of the other machines (no data before {cutoff.date()})"
    for m in machines:
        if m not in rate:
            rate[m] = med_rate
            basis[m] = fb
        if m not in avail:
            avail[m] = med_avail
            window[m] = fb if known_avail else f"fallback: default {DEFAULT_AVAILABILITY}"
    for m in list(avail):  # machines seen only in the interval table
        if m not in rate:
            rate[m] = med_rate
            basis[m] = fb
    n, p25, p75 = conn.execute(CHANGEOVER_SQL).fetchone()
    if n:
        same, cross = max(1, round(float(p25) / 60)), max(1, round(float(p75) / 60))
    else:
        same, cross = DEFAULT_CHANGEOVER_MIN
    cross = max(cross, same)
    return Anchors(
        rates=dict(sorted(rate.items())),
        availability=dict(sorted(avail.items())),
        changeover_same_family_min=same,
        changeover_cross_family_min=cross,
        sources={
            "rate": f"p95 set speed, production rows before {cutoff.date()} (packages per hour)",
            "rate_basis": dict(sorted(basis.items())),
            "availability_window": dict(sorted(window.items())),
            "availability_stats": dict(sorted(stats.items())),
            "availability_cutoff": cutoff.isoformat(),
            "changeover": (
                f"brick SETUPS-CHANGEOVERS stops, n={n}, p25/p75 rounded to minutes"
                if n
                else "default (no brick changeover stops in the database)"
            ),
        },
    )
