"""Ground truth for the answer evals, in plain SQL over core.* and mart.*.

Written apart from the tool layer (no import of linecopilot.tools, api or chat; a test
checks this), so a bug in a tool cannot also be the answer key. The definitions are the
ones the tools state in their assumptions:

- A stop is a mart.stop_episode row that counts in OEE, placed in a window by its start.
- Months: brick in Europe/Nicosia, PIADE in UTC. Brick shifts run 04:15 to 13:00 UTC, so a
  UTC month window holds the same brick stops and shifts as the local month.
- MTTR = failure seconds / failures; MTBF = run seconds / failures.
- PIADE run seconds: mart.piade_interval_counts running intervals starting in the month.
- Brick run seconds: published planned minus union of in-OEE stop seconds, over shifts with
  a published planned time.
- Availability: PIADE sum(run_s) / sum(planned_s) over shifts starting in the month; brick
  1 - sum(stop_s_union) / sum(planned_s_published) over shifts with a published planned time.

Every function returns a Truth: the expected answer and the core.event ids that
legitimately support it (used by the citation check)."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

NOT_AVAILABLE = "NOT_AVAILABLE"
BRICK = "brick"
BRICK_TZ = "Europe/Nicosia"
NOT_IN_OEE = "Planned - Not included in OEE"


@dataclass
class Truth:
    expected: float | str
    evidence_event_ids: frozenset[int] = frozenset()
    detail: dict[str, Any] = field(default_factory=dict)


class NoTruth(ValueError):
    """The data cannot give a well-defined answer for these parameters."""


def _rows(conn, sql: str, params: dict[str, Any]) -> list[dict[str, Any]]:
    cur = conn.execute(sql, params)
    cols = [d.name for d in cur.description]
    return [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]


def _tz(asset: str) -> str:
    return BRICK_TZ if asset == BRICK else "UTC"


def month_bounds(month: str) -> tuple[datetime, datetime]:
    """[first day, first day of next month) in UTC for 'YYYY-MM'."""
    y, m = (int(x) for x in month.split("-"))
    lo = datetime(y, m, 1, tzinfo=UTC)
    hi = datetime(y + (m == 12), m % 12 + 1, 1, tzinfo=UTC)
    return lo, hi


# ---- stop episodes ---------------------------------------------------------------------------

EPISODES_IN_MONTH = """
SELECT episode_id, reason, duration_s::float8 AS duration_s, is_failure, event_ids
FROM mart.stop_episode
WHERE line_id = %(asset)s AND in_oee
  AND to_char(start_ts AT TIME ZONE %(tz)s, 'YYYY-MM') = %(month)s
"""


def _episodes(conn, asset: str, month: str) -> list[dict[str, Any]]:
    return _rows(conn, EPISODES_IN_MONTH, {"asset": asset, "tz": _tz(asset), "month": month})


def _ids(eps: list[dict[str, Any]]) -> frozenset[int]:
    return frozenset(int(i) for e in eps for i in e["event_ids"])


def _reason_groups(eps: list[dict[str, Any]]) -> list[tuple[str | None, float, list[dict]]]:
    groups: dict[str | None, list[dict]] = defaultdict(list)
    for e in eps:
        groups[e["reason"]].append(e)
    out = [(k, sum(e["duration_s"] for e in v), v) for k, v in groups.items()]
    return sorted(out, key=lambda t: (-t[1], -len(t[2]), t[0] or ""))


def top_reason(conn, asset: str, month: str) -> Truth:
    """The reason (brick stop group, PIADE alarm code) with the most lost time."""
    ranked = _reason_groups(_episodes(conn, asset, month))
    if not ranked or ranked[0][0] is None:
        raise NoTruth(f"no named top reason for {asset} {month}")
    (name, lost, eps), runner = ranked[0], ranked[1] if len(ranked) > 1 else None
    return Truth(
        expected=name,
        evidence_event_ids=_ids(eps),
        detail={
            "lost_s": lost,
            "runner_up": runner[0] if runner else None,
            "runner_up_lost_s": runner[1] if runner else 0.0,
            "alternatives": [k for k, _, _ in ranked[1:6] if k is not None],
        },
    )


def top_reason_lost_s(conn, asset: str, month: str) -> Truth:
    t = top_reason(conn, asset, month)
    return Truth(
        expected=t.detail["lost_s"],
        evidence_event_ids=t.evidence_event_ids,
        detail={"reason": t.expected, "runner_up_lost_s": t.detail["runner_up_lost_s"]},
    )


def stop_count(conn, asset: str, month: str) -> Truth:
    eps = _episodes(conn, asset, month)
    if not eps:
        raise NoTruth(f"no stops for {asset} {month}")
    return Truth(expected=float(len(eps)), evidence_event_ids=_ids(eps))


def _run_seconds(conn, asset: str, month: str) -> tuple[float, frozenset[int]]:
    """Run seconds in the month and the events behind them (PIADE running intervals; brick
    production_count rows of the shifts)."""
    if asset == BRICK:
        recs = _rows(
            conn,
            """SELECT sum(m.planned_s_published - m.stop_s_union)::float8 AS run_s,
                      array_agg(m.shift_id) AS shift_ids
               FROM mart.brick_shift_oee m JOIN core.shift s USING (shift_id)
               WHERE m.planned_s_published IS NOT NULL
                 AND to_char(s.shift_start AT TIME ZONE %(tz)s, 'YYYY-MM') = %(month)s""",
            {"tz": BRICK_TZ, "month": month},
        )
        ids = _rows(
            conn,
            """SELECT event_id FROM core.event
               WHERE event_type = 'production_count' AND shift_id = ANY(%(sids)s)""",
            {"sids": recs[0]["shift_ids"] or []},
        )
        return float(recs[0]["run_s"] or 0.0), frozenset(int(r["event_id"]) for r in ids)
    recs = _rows(
        conn,
        """SELECT duration_s::float8 AS d, event_id FROM mart.piade_interval_counts
           WHERE machine_id = %(m)s AND is_run
             AND to_char(start_ts AT TIME ZONE 'UTC', 'YYYY-MM') = %(month)s""",
        {"m": asset, "month": month},
    )
    return sum(r["d"] for r in recs), frozenset(int(r["event_id"]) for r in recs)


def _failures(conn, asset: str, month: str) -> list[dict[str, Any]]:
    fails = [e for e in _episodes(conn, asset, month) if e["is_failure"]]
    if not fails:
        raise NoTruth(f"no failures for {asset} {month}")
    return fails


def mttr_s(conn, asset: str, month: str) -> Truth:
    fails = _failures(conn, asset, month)
    total = sum(e["duration_s"] for e in fails)
    return Truth(
        expected=total / len(fails),
        evidence_event_ids=_ids(fails),
        detail={"failure_count": len(fails), "failure_s": total},
    )


def mtbf_s(conn, asset: str, month: str) -> Truth:
    fails = _failures(conn, asset, month)
    run, run_ids = _run_seconds(conn, asset, month)
    if run <= 0:
        raise NoTruth(f"no run time for {asset} {month}")
    return Truth(
        expected=run / len(fails),
        evidence_event_ids=_ids(fails) | run_ids,
        detail={"failure_count": len(fails), "run_s": run},
    )


# ---- repeat failures -------------------------------------------------------------------------


def repeat_chain_count(
    conn, asset: str, month: str, within_hours: float = 24, min_repeats: int = 3
) -> Truth:
    """Chains of failure stops with the same reason on the same asset, each starting at most
    `within_hours` after the latest end so far in the chain, of at least `min_repeats` stops,
    with at least one stop starting in the month. Stops within `within_hours` either side of
    the month are followed. Failures are taken whether or not they count in OEE."""
    lo, hi = month_bounds(month)
    gap = timedelta(hours=within_hours)
    eps = _rows(
        conn,
        """SELECT episode_id, reason, start_ts, end_ts, event_ids FROM mart.stop_episode
           WHERE line_id = %(asset)s AND is_failure AND reason IS NOT NULL
             AND start_ts >= %(lo)s AND start_ts < %(hi)s
           ORDER BY reason, start_ts, episode_id""",
        {"asset": asset, "lo": lo - gap, "hi": hi + gap},
    )
    chains: list[list[dict]] = []
    cur: list[dict] = []
    cur_end = None
    for e in eps:
        if cur and e["reason"] == cur[0]["reason"] and e["start_ts"] - cur_end <= gap:
            cur.append(e)
            cur_end = max(cur_end, e["end_ts"])
            continue
        if cur:
            chains.append(cur)
        cur, cur_end = [e], e["end_ts"]
    if cur:
        chains.append(cur)
    kept = [c for c in chains if len(c) >= min_repeats and any(lo <= e["start_ts"] < hi for e in c)]
    n_inside = sum(lo <= e["start_ts"] < hi for e in eps)
    if not n_inside:
        raise NoTruth(f"no failures for {asset} {month}")
    return Truth(
        expected=float(len(kept)),
        evidence_event_ids=_ids([e for c in kept for e in c]),
        detail={"failures_in_month": n_inside},
    )


# ---- OEE and availability --------------------------------------------------------------------


def _shift_event_ids(conn, asset: str, month: str) -> frozenset[int]:
    """Events behind a month's OEE: PIADE intervals of its shifts; brick production_count
    rows and in-OEE stops of its shifts."""
    recs = _rows(
        conn,
        """SELECT e.event_id FROM core.event e JOIN core.shift s USING (shift_id)
           WHERE s.line_id = %(asset)s
             AND to_char(s.shift_start AT TIME ZONE %(tz)s, 'YYYY-MM') = %(month)s
             AND (%(asset)s <> 'brick' OR e.event_type = 'production_count'
                  OR e.stop_type IS DISTINCT FROM %(not_in)s)""",
        {"asset": asset, "tz": _tz(asset), "month": month, "not_in": NOT_IN_OEE},
    )
    return frozenset(int(r["event_id"]) for r in recs)


def availability(conn, asset: str, month: str) -> Truth:
    if asset == BRICK:
        (val,) = conn.execute(
            """SELECT 1 - sum(m.stop_s_union)::float8 / nullif(sum(m.planned_s_published), 0)
               FROM mart.brick_shift_oee m JOIN core.shift s USING (shift_id)
               WHERE m.planned_s_published IS NOT NULL
                 AND to_char(s.shift_start AT TIME ZONE %(tz)s, 'YYYY-MM') = %(month)s""",
            {"tz": BRICK_TZ, "month": month},
        ).fetchone()
    else:
        (val,) = conn.execute(
            """SELECT sum(run_s)::float8 / nullif(sum(planned_s), 0)
               FROM mart.piade_shift_oee
               WHERE machine_id = %(m)s
                 AND to_char(shift_start AT TIME ZONE 'UTC', 'YYYY-MM') = %(month)s""",
            {"m": asset, "month": month},
        ).fetchone()
    if val is None:
        raise NoTruth(f"no availability for {asset} {month}")
    return Truth(expected=float(val), evidence_event_ids=_shift_event_ids(conn, asset, month))


def piade_oee(conn, asset: str, month: str) -> Truth:
    """PIADE monthly OEE at the p95 ideal rate, as stored by the OEE mart."""
    (val,) = conn.execute(
        """SELECT oee FROM mart.piade_machine_oee
           WHERE machine_id = %(m)s AND to_char(month, 'YYYY-MM') = %(month)s""",
        {"m": asset, "month": month},
    ).fetchone() or (None,)
    if val is None:
        raise NoTruth(f"no OEE for {asset} {month}")
    return Truth(expected=float(val), evidence_event_ids=_shift_event_ids(conn, asset, month))


def availability_delta(conn, asset: str, month_a: str, month_b: str) -> Truth:
    """Availability in month_b minus month_a, as a fraction."""
    a, b = availability(conn, asset, month_a), availability(conn, asset, month_b)
    return Truth(
        expected=float(b.expected) - float(a.expected),
        evidence_event_ids=a.evidence_event_ids | b.evidence_event_ids,
        detail={"a": a.expected, "b": b.expected},
    )


# ---- notes -----------------------------------------------------------------------------------


def note_date(conn, word: str) -> Truth:
    """The local date (YYYY-MM-DD) of the one stop whose note mentions `word` in its
    original text or translation (case and accents ignored)."""
    recs = _rows(
        conn,
        """SELECT n.event_id,
                  to_char(e.start_ts AT TIME ZONE %(tz)s, 'YYYY-MM-DD') AS day
           FROM core.note n JOIN core.event e USING (event_id)
           LEFT JOIN core.note_translation t USING (note_id)
           WHERE enrich.fold(n.original_text) LIKE '%%' || enrich.fold(%(w)s) || '%%'
              OR enrich.fold(coalesce(t.translated_text, '')) LIKE
                 '%%' || enrich.fold(%(w)s) || '%%'""",
        {"tz": BRICK_TZ, "w": word},
    )
    days = {r["day"] for r in recs}
    if len(days) != 1:
        raise NoTruth(f"{word!r} is in notes on {len(days)} dates")
    return Truth(
        expected=days.pop(),
        evidence_event_ids=frozenset(int(r["event_id"]) for r in recs),
        detail={"notes": len(recs)},
    )


# ---- unanswerable ----------------------------------------------------------------------------


def not_available(conn, asset: str | None = None, month: str | None = None) -> Truth:
    """Expected NOT_AVAILABLE. With asset and month, also checks that the asset really has
    no events in that month (PIADE's shift calendar has shifts in months with no data)."""
    if asset is not None and month is not None:
        (n,) = conn.execute(
            """SELECT count(*) FROM core.event
               WHERE line_id = %(asset)s
                 AND to_char(start_ts AT TIME ZONE %(tz)s, 'YYYY-MM') = %(month)s""",
            {"asset": asset, "tz": _tz(asset), "month": month},
        ).fetchone()
        if n:
            raise NoTruth(f"{asset} has {n} events in {month}; the question is answerable")
    return Truth(expected=NOT_AVAILABLE)


TRUTH_FNS = {
    fn.__name__: fn
    for fn in (
        top_reason,
        top_reason_lost_s,
        stop_count,
        mttr_s,
        mtbf_s,
        repeat_chain_count,
        availability,
        piade_oee,
        availability_delta,
        note_date,
        not_available,
    )
}


def compute(conn, expected_fn: str, params: dict[str, Any]) -> Truth:
    return TRUTH_FNS[expected_fn](conn, **params)


# ---- before/after facts (brick) --------------------------------------------------------------

BEFORE = ("2025-09-01", "2026-01-01")
AFTER = ("2026-01-01", "2026-05-01")
TOP_REASON_FACTS = 5
RATIOS = ("availability", "performance", "quality", "oee")
TOTALS = ("stop_time", "stop_count")
RATIO_MIN_DELTA = 0.01  # one percentage point
REL_MIN_DELTA = 0.05


def _brick_window(conn, lo: str, hi: str) -> tuple[dict[str, float], dict[str, float]]:
    """Brick metrics and lost seconds per stop group for shifts / stops starting in [lo, hi)
    (UTC dates)."""
    p = {"lo": lo, "hi": hi}
    oee = _rows(
        conn,
        """SELECT count(*) AS shifts, sum(m.planned_s_published)::float8 AS planned,
                  sum(m.stop_s_union) FILTER (WHERE m.planned_s_published IS NOT NULL)::float8
                      AS stop_union,
                  sum(p.total_qty)::float8 AS total, sum(p.good_qty)::float8 AS good,
                  sum(p.ideal_qty)::float8 AS ideal
           FROM mart.brick_shift_oee m JOIN core.shift s USING (shift_id)
           LEFT JOIN core.brick_shift_published p USING (shift_id)
           WHERE s.shift_start >= %(lo)s::timestamptz AND s.shift_start < %(hi)s::timestamptz""",
        p,
    )[0]
    eps = _rows(
        conn,
        """SELECT reason, duration_s::float8 AS d, is_failure FROM mart.stop_episode
           WHERE line_id = 'brick' AND in_oee
             AND start_ts >= %(lo)s::timestamptz AND start_ts < %(hi)s::timestamptz""",
        p,
    )
    a = 1 - oee["stop_union"] / oee["planned"]
    perf = oee["total"] / oee["ideal"]
    qual = oee["good"] / oee["total"]
    fails = [e["d"] for e in eps if e["is_failure"]]
    metrics = {
        "availability": a,
        "performance": perf,
        "quality": qual,
        "oee": a * perf * qual,
        "stop_time": sum(e["d"] for e in eps),
        "stop_count": float(len(eps)),
        "mttr": sum(fails) / len(fails),
        "shifts": float(oee["shifts"]),
    }
    reasons: dict[str, float] = defaultdict(float)
    for e in eps:
        reasons[e["reason"] or "(blank)"] += e["d"]
    return metrics, dict(reasons)


def _direction(kind: str, before: float, after: float) -> str:
    """up / down past the minimum effect size, else flat: 1 percentage point for ratios,
    5% relative for everything else."""
    delta = after - before
    if kind == "ratio":
        big = abs(delta) >= RATIO_MIN_DELTA
    elif before == 0:
        big = after != 0
    else:
        big = abs(delta) / abs(before) >= REL_MIN_DELTA
    if not big:
        return "flat"
    return "up" if delta > 0 else "down"


def _fact(metric: str, kind: str, b: float, a: float, shifts: tuple[float, float]) -> dict:
    """One fact with a direction per reading. Totals are read as totals and per shift; the
    fact is scored only when every reading gives the same up/down direction."""
    out: dict[str, Any] = {"metric": metric, "kind": kind, "before": b, "after": a}
    out["delta"] = a - b
    readings = {"value": _direction(kind, b, a)}
    if kind == "total":
        pb, pa = b / shifts[0], a / shifts[1]
        out["before_per_shift"], out["after_per_shift"] = pb, pa
        readings = {"total": readings["value"], "per_shift": _direction(kind, pb, pa)}
    out["readings"] = readings
    dirs = set(readings.values())
    if dirs == {"flat"}:
        out["status"] = "flat"
    elif len(dirs) == 1:
        out["status"] = "scored"
    else:
        out["status"] = "ambiguous"
    out["direction"] = dirs.pop() if out["status"] == "scored" else None
    return out


def before_after_facts(conn) -> dict[str, Any]:
    """Facts on what changed on the brick line, before -> after: each OEE component (ratio),
    MTTR (a mean), stop time and stop count (totals, also read per shift), and the lost time
    of the stop groups with the largest absolute change. Only `scored` facts count; `flat`
    (below the minimum effect size) and `ambiguous` (totals and per-shift disagree) facts are
    listed but not scored. `status` covers every metric and stop group, so any claim can be
    judged."""
    mb, rb = _brick_window(conn, *BEFORE)
    ma, ra = _brick_window(conn, *AFTER)
    shifts = (mb.pop("shifts"), ma.pop("shifts"))
    kinds = {k: "ratio" for k in RATIOS} | {k: "total" for k in TOTALS} | {"mttr": "mean"}
    metric_facts = [_fact(k, kinds[k], mb[k], ma[k], shifts) for k in mb]
    reason_facts = [
        _fact(f"reason:{r}", "total", rb.get(r, 0.0), ra.get(r, 0.0), shifts)
        for r in sorted(set(rb) | set(ra))
    ]
    reason_facts.sort(key=lambda x: (-abs(x["delta"]), x["metric"]))
    facts = metric_facts + reason_facts[:TOP_REASON_FACTS]
    return {
        "before_window": list(BEFORE),
        "after_window": list(AFTER),
        "shifts": {"before": shifts[0], "after": shifts[1]},
        "min_effect": {"ratio_abs": RATIO_MIN_DELTA, "other_rel": REL_MIN_DELTA},
        "facts": facts,
        "status": {
            x["metric"]: x["direction"] if x["status"] == "scored" else x["status"]
            for x in metric_facts + reason_facts
        },
    }
