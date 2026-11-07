"""Replay real PIADE stops against a plan.

Planning used only data before 2021-07-01 (see `synth.anchors`). The replay windows are 8
non-overlapping 14-day windows starting on 2021-07-01, so the stops here come from a later
period than every plan input. A window's stops are mapped onto horizon minutes (offset from
the window start) per machine, clipped to the window; overlapping episodes are merged.

`execute` keeps each machine's job sequence and each job's machine from the plan and walks it
forward: a job's processing starts no earlier than its release and ready time, nor before the
previous job ends and its setup has been done; setup and processing only progress while the
machine is up; processing runs at the nominal rate (quantity over rate, no availability
factor), because the stops are explicit now. Past the end of the window there are no stops.

A machine with no PIADE data in part of a window is treated as having no stops there. The share
of the window with no data is recorded next to the realised stopped share, since a machine with
gaps would otherwise look more reliable than it was.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import psycopg

from linecopilot.plan.model import (
    Assignment,
    Plan,
    Problem,
    split_unschedulable,
)
from linecopilot.synth.anchors import CUTOFF

WINDOW_DAYS = 14
N_WINDOWS = 8
FIRST_WINDOW = datetime(2021, 7, 1, tzinfo=UTC)
assert FIRST_WINDOW >= CUTOFF  # replay starts on or after the last planning input

Stops = dict[str, list[tuple[int, int]]]

STOP_SQL = """
select machine_id, start_ts, end_ts
from mart.stop_episode
where source_system = 'piade' and start_ts < %(end)s and end_ts > %(start)s
order by machine_id, start_ts
"""

COVER_SQL = """
select machine_id, start_ts, end_ts
from mart.piade_interval_counts
where start_ts < %(end)s and end_ts > %(start)s
order by machine_id, start_ts
"""


@dataclass(frozen=True)
class Window:
    start: datetime
    end: datetime

    @property
    def minutes(self) -> int:
        return int((self.end - self.start).total_seconds() // 60)


def window_starts() -> list[datetime]:
    return [FIRST_WINDOW + timedelta(days=WINDOW_DAYS * i) for i in range(N_WINDOWS)]


def windows(conn: psycopg.Connection | None = None) -> list[Window]:
    """The 8 replay windows. `conn` is accepted for the interface; the windows are fixed by
    design (the first 8 14-day windows from 2021-07-01, all before 2021-12-31)."""
    return [Window(s, s + timedelta(days=WINDOW_DAYS)) for s in window_starts()]


def merge(intervals: list[tuple[int, int]]) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    for a, b in sorted(intervals):
        if out and a <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], b))
        else:
            out.append((a, b))
    return out


def to_minutes(window: Window, spans: list[tuple[datetime, datetime]]) -> list[tuple[int, int]]:
    """Clip to the window, offset from its start, round both ends to the nearest minute (a stop
    of d seconds then lasts d/60 minutes in expectation), drop empty ones, merge."""
    out = []
    for a, b in spans:
        a, b = max(a, window.start), min(b, window.end)
        if b <= a:
            continue
        lo = round((a - window.start).total_seconds() / 60)
        hi = round((b - window.start).total_seconds() / 60)
        if hi > lo:
            out.append((lo, hi))
    return merge(out)


def stops(conn: psycopg.Connection, window: Window) -> Stops:
    """PIADE stop episodes in the window, per machine, in horizon minutes."""
    by: dict[str, list[tuple[datetime, datetime]]] = {}
    for m, a, b in conn.execute(STOP_SQL, {"start": window.start, "end": window.end}):
        by.setdefault(m, []).append((a, b))
    return {m: to_minutes(window, spans) for m, spans in by.items()}


def window_stats(conn: psycopg.Connection, window: Window, machines: list[str]) -> dict:
    """Per machine: `stopped_share` of the whole window, `stopped_share_of_covered` (stopped
    minutes over minutes with data, the denominator planning availability uses) and
    `no_data_share` (share of the window with no PIADE data at all)."""
    st = stops(conn, window)
    seen: dict[str, list[tuple[datetime, datetime]]] = {}
    for m, a, b in conn.execute(COVER_SQL, {"start": window.start, "end": window.end}):
        seen.setdefault(m, []).append((a, b))
    total = window.minutes
    out = {}
    for m in machines:
        stopped = sum(b - a for a, b in st.get(m, []))
        covered_s = 0.0
        last = None
        for a, b in sorted(seen.get(m, [])):  # union of intervals, clipped to the window
            a, b = max(a, window.start), min(b, window.end)
            if last is not None and a < last:
                a = last
            if b > a:
                covered_s += (b - a).total_seconds()
                last = b
        covered = covered_s / 60
        out[m] = {
            "stopped_share": stopped / total,
            "stopped_share_of_covered": min(1.0, stopped / covered) if covered > 0 else None,
            "no_data_share": max(0.0, 1 - covered_s / 60 / total),
        }
    return out


def _next_up(t: int, stop: list[tuple[int, int]]) -> int:
    for a, b in stop:
        if a <= t < b:
            t = b
    return t


def _advance(t: int, work: int, stop: list[tuple[int, int]]) -> int:
    """The time at which `work` up-minutes have passed since `t`. With no work it returns t, or
    the end of the stop t lies in when work is positive."""
    t = _next_up(t, stop) if work > 0 else t
    for a, b in stop:
        if b <= t:
            continue
        if a >= t + work:
            break
        work -= max(0, a - t)
        t = b
    return t + work


def execute(problem: Problem, plan: Plan, stops: Stops) -> list[Assignment]:
    """Actual start and end of every planned job under the given stops (see module doc)."""
    problem = split_unschedulable(problem)
    jobs = {j.order_id: j for j in problem.jobs}
    machines = {m.machine_id: m for m in problem.machines}
    by: dict[str, list[Assignment]] = {}
    for a in sorted(plan.assignments, key=lambda a: (a.start, a.order_id)):
        by.setdefault(a.machine_id, []).append(a)
    out: list[Assignment] = []
    for mid, rows in by.items():
        stop = merge(stops.get(mid, []))
        rate = machines[mid].rate_per_hour
        free = 0
        for a in rows:
            j = jobs[a.order_id]
            ready_at = _advance(free, a.setup_before, stop)
            start = _next_up(max(ready_at, j.release, j.ready), stop)
            end = _advance(start, math.ceil(j.quantity / rate * 60), stop)
            out.append(Assignment(a.order_id, mid, start, end, a.setup_before))
            free = end
    out.sort(key=lambda a: (a.start, a.machine_id, a.order_id))
    return out
