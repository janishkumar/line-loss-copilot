"""reliability: failure counts, MTTR and MTBF for a brick line or a PIADE machine.

Failures are the failure episodes of mart.stop_episode that count in OEE (the same stops
loss_pareto ranks), so the figures here and in the loss tools cannot disagree."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Any, Literal
from zoneinfo import ZoneInfo

import psycopg
from pydantic import BaseModel, ConfigDict, Field

from linecopilot.tools.common import (
    END_DESC,
    LINE_ID_DESC,
    MACHINE_ID_DESC,
    START_DESC,
    Scope,
    ScopeArgs,
    resolve_scope,
    rows,
)
from linecopilot.tools.envelope import Citation, Result, Window
from linecopilot.tools.losses import (
    ASSUME_BRICK,
    ASSUME_PIADE,
    ASSUME_PIADE_REASON,
    ASSUME_WINDOW,
    BLANK,
    _by_size,
    _episodes,
    _lost,
    _no_stops,
    _ranked,
    _top_union,
    episode_citations,
    value,
)
from linecopilot.tools.oee import window_oee

Group = Literal["none", "month"]
ALL = "all"

ASSUME_RELIABILITY = (
    "MTTR = failure_s / failure_count and MTBF = run_s / failure_count, both null when "
    "there are no failures. Failures are failure episodes that count in OEE; stop_count "
    "is every stop episode that counts in OEE, and brick stops typed 'Planned - Not "
    "included in OEE' are excluded from both."
)
ASSUME_RUN_PIADE = (
    "PIADE run_s is the seconds of the machine's running intervals (production and "
    "performance-loss) starting in the window, with overlapping intervals clipped to the "
    "previous interval's end as in the OEE marts (mart.piade_interval_counts); each is "
    "bucketed by its clipped start."
)
ASSUME_RUN_BRICK = (
    "Brick run_s is, summed over the shifts starting in the window, the published planned "
    "seconds minus the union of stop seconds that count in OEE (mart.brick_shift_oee); "
    "shifts with no published planned time add no run time, though their failures are counted."
)
ASSUME_MONTH = (
    "Months are calendar months of the stop's start (brick: Europe/Nicosia, PIADE: UTC); "
    "run time is bucketed by the start of the interval (PIADE) or shift (brick)."
)


class ReliabilityArgs(ScopeArgs):
    group: Group = "none"


class ReliabilityRow(BaseModel):
    period: str = Field(description="'all' or a calendar month, YYYY-MM")
    failure_count: int
    stop_count: int
    failure_s: float
    run_s: float
    mttr_s: float | None = None
    mtbf_s: float | None = None
    citations: list[Citation] = Field(default_factory=list)
    citation_count: int = Field(default=0, description="distinct raw rows behind this row")


class ReliabilityData(BaseModel):
    source_system: str
    group: str
    rows: list[ReliabilityRow]


def run_seconds(conn: psycopg.Connection, scope: Scope, month: bool) -> dict[str, float]:
    """Run seconds per period ('all' or YYYY-MM) in the scope's window."""
    p: dict[str, Any] = {"s": scope.start, "e": scope.end, "m": scope.machine_id}
    if scope.source_system == "piade":
        key = "to_char(start_ts AT TIME ZONE 'UTC', 'YYYY-MM')" if month else "'all'"
        recs = rows(
            conn,
            f"""SELECT {key} AS period, sum(duration_s) AS run_s
                FROM mart.piade_interval_counts
                WHERE machine_id = %(m)s AND is_run
                  AND start_ts >= %(s)s AND start_ts < %(e)s
                GROUP BY 1""",
            p,
        )
    else:
        key = (
            "to_char(date_trunc('month', s.shift_start AT TIME ZONE 'Europe/Nicosia'), 'YYYY-MM')"
            if month
            else "'all'"
        )
        recs = rows(
            conn,
            f"""SELECT {key} AS period,
                       sum(m.planned_s_published - m.stop_s_union) AS run_s
                FROM mart.brick_shift_oee m JOIN core.shift s ON s.shift_id = m.shift_id
                WHERE m.planned_s_published IS NOT NULL
                  AND s.shift_start >= %(s)s AND s.shift_start < %(e)s
                GROUP BY 1""",
            p,
        )
    return {r["period"]: float(r["run_s"]) for r in recs}


def _month(scope: Scope, e: dict[str, Any]) -> str:
    tz = "Europe/Nicosia" if scope.source_system == "brick" else "UTC"

    return e["start_ts"].astimezone(ZoneInfo(tz)).strftime("%Y-%m")


def reliability_rows(
    conn, scope: Scope, month: bool
) -> tuple[list[ReliabilityRow], dict[str, list[dict]]]:
    """Reliability rows for the window, and each period's failure episodes."""
    stops = _episodes(conn, scope, include_all=False)
    runs = run_seconds(conn, scope, month)
    by_stops: dict[str, list[dict]] = defaultdict(list)
    for e in stops:
        by_stops[_month(scope, e) if month else ALL].append(e)
    periods = sorted(set(by_stops) | set(runs))
    out, fails = [], {}
    for per in periods:
        eps = by_stops.get(per, [])
        fe = [e for e in eps if e["is_failure"]]
        fails[per] = fe
        n, fs = len(fe), sum(e["duration_s"] for e in fe)
        run = runs.get(per, 0.0)
        out.append(
            ReliabilityRow(
                period=per,
                failure_count=n,
                stop_count=len(eps),
                failure_s=fs,
                run_s=run,
                mttr_s=fs / n if n else None,
                mtbf_s=run / n if n and run > 0 else None,
            )
        )
    return out, fails


def reliability_assumptions(scope: Scope, month: bool) -> list[str]:
    if scope.source_system == "piade":
        out = [ASSUME_PIADE, ASSUME_PIADE_REASON, ASSUME_RUN_PIADE]
    else:
        out = [ASSUME_BRICK, ASSUME_RUN_BRICK]
    out += [ASSUME_RELIABILITY, ASSUME_WINDOW]
    if month:
        out.append(ASSUME_MONTH)
    return out


def reliability(conn: psycopg.Connection, args: ReliabilityArgs) -> Result[ReliabilityData]:
    scope = resolve_scope(conn, args.line_id, args.machine_id, args.start, args.end)
    if isinstance(scope, Result):
        return scope
    month = args.group == "month"
    assumptions = reliability_assumptions(scope, month)
    rws, fails = reliability_rows(conn, scope, month)
    if not rws:
        return _no_stops(scope, "stops or run time", assumptions, include_not_in_oee=False)
    cites, n_raw = episode_citations(conn, [(k, _by_size(es)) for k, es in fails.items()])
    for r in rws:
        r.citations, r.citation_count = cites.get(r.period, ([], 0))
    if any(r.failure_count > 0 and r.run_s == 0 for r in rws):
        assumptions.append(
            "Periods with failures but no run time have null mtbf_s: run_s is 0, so a time "
            "between failures cannot be stated."
        )
    if any(r.failure_count == 0 for r in rws):
        assumptions.append(
            "Periods with no failures have null mttr_s and mtbf_s: with nothing to divide "
            "by, no time between failures can be stated."
        )
    return Result(
        status="ok",
        data=ReliabilityData(source_system=scope.source_system, group=args.group, rows=rws),
        citations=_top_union([r.citations for r in rws]),
        citation_count=n_raw,
        window=scope.window(args.group),
        assumptions=assumptions,
    )


# compare_periods ----------------------------------------------------------------------------


class CompareArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    line_id: str | None = Field(default=None, description=LINE_ID_DESC)
    machine_id: str | None = Field(default=None, description=MACHINE_ID_DESC)
    a_start: datetime = Field(description=f"period A start: {START_DESC}")
    a_end: datetime = Field(description=f"period A end: {END_DESC}")
    b_start: datetime = Field(description=f"period B start: {START_DESC}")
    b_end: datetime = Field(description=f"period B end: {END_DESC}")
    top: int = Field(default=5, ge=1, le=50, description="top reasons per period by lost time")


class ReasonLoss(BaseModel):
    reason: str
    lost_s: float
    stop_count: int
    share: float


class ReasonChange(BaseModel):
    reason: str
    a_lost_s: float
    b_lost_s: float
    delta_lost_s: float


class PeriodData(BaseModel):
    start: datetime
    end: datetime
    metrics: dict[str, float | None] = Field(
        description="OEE components, stop_s, stop_count, failure_count, mttr_s, mtbf_s"
    )
    top_reasons: list[ReasonLoss]


class CompareData(BaseModel):
    source_system: str
    a: PeriodData
    b: PeriodData
    deltas: dict[str, float | None] = Field(description="b minus a, null if either is missing")
    reason_changes: list[ReasonChange]


ASSUME_COMPARE = (
    "OEE components are those of get_oee, summed over the shifts that start in each period "
    "(ratios from sums). Stop figures (stop_s, stop_count, failures, MTTR, top reasons) use "
    "the stops that start in each period, so the two can cover slightly different time at "
    "the edges; brick stop_s can exceed the union of stop time behind availability. "
    "reliability_run_s is bucketed by interval start (PIADE) or shift (brick), so it can "
    "differ from the OEE run_s, which is split across shifts. Deltas are period B minus "
    "period A; reason_changes covers the top reasons of either period. Citations are the "
    "top reasons' stop events, A then B."
)


def _period(conn, scope: Scope, top: int) -> tuple[PeriodData, dict, list] | None:
    """One period's metrics and top reasons, its full reason -> (lost_s, count) map, and its
    top reason groups (name, episodes) for citations. None when no shift starts in it."""
    oee = window_oee(conn, scope)
    if oee is None:
        return None
    rel_rows, _ = reliability_rows(conn, scope, False)
    rel = rel_rows[0] if rel_rows else None
    eps = _episodes(conn, scope, include_all=False)
    groups: dict[str, list[dict]] = defaultdict(list)
    for e in eps:
        groups[value(e, "reason", scope.source_system) or BLANK].append(e)
    stop_s = _lost(eps)
    ranked = _ranked(groups)
    metrics: dict[str, float | None] = {
        **oee,
        "stop_s": stop_s,
        "stop_count": float(len(eps)),
        "failure_count": float(rel.failure_count) if rel else 0.0,
        "failure_s": rel.failure_s if rel else 0.0,
        "reliability_run_s": rel.run_s if rel else 0.0,
        "mttr_s": rel.mttr_s if rel else None,
        "mtbf_s": rel.mtbf_s if rel else None,
    }
    data = PeriodData(
        start=scope.start,
        end=scope.end,
        metrics=metrics,
        top_reasons=[
            ReasonLoss(
                reason=k,
                lost_s=_lost(es),
                stop_count=len(es),
                share=_lost(es) / stop_s if stop_s else 0.0,
            )
            for k, es in ranked[:top]
        ],
    )
    return data, {k: (_lost(es), len(es)) for k, es in groups.items()}, ranked[:top]


def compare_periods(conn: psycopg.Connection, args: CompareArgs) -> Result[CompareData]:
    sa = resolve_scope(conn, args.line_id, args.machine_id, args.a_start, args.a_end)
    if isinstance(sa, Result):
        sa.missing = f"period A: {sa.missing}"
        return sa
    sb = resolve_scope(conn, args.line_id, args.machine_id, args.b_start, args.b_end)
    if isinstance(sb, Result):
        sb.missing = f"period B: {sb.missing}"
        return sb
    win = Window(
        start=min(sa.start, sb.start),
        end=max(sa.end, sb.end),
        line_id=sa.line_id,
        machine_id=sa.machine_id,
    )
    if sa.start < sb.end and sb.start < sa.end:
        return Result(
            status="out_of_scope",
            window=win,
            missing="periods A and B overlap; give two periods that do not share any time",
        )
    assumptions = [*reliability_assumptions(sa, False), ASSUME_COMPARE]
    got = [(n, sc, _period(conn, sc, args.top)) for n, sc in (("A", sa), ("B", sb))]
    for n, sc, res in got:
        if res is None:
            return Result(
                status="insufficient_evidence",
                window=win,
                assumptions=assumptions,
                missing=(
                    f"no {sc.source_system} data for {sc.machine_id or sc.line_id} in period "
                    f"{n} ({sc.start.isoformat()} to {sc.end.isoformat()}); coverage is "
                    f"{sc.first_ts.isoformat()} to {sc.last_ts.isoformat()}"
                ),
            )
    (_, _, (pa, full_a, top_a)), (_, _, (pb, full_b, top_b)) = got
    deltas = {
        k: (
            pb.metrics[k] - pa.metrics[k]
            if pa.metrics.get(k) is not None and pb.metrics.get(k) is not None
            else None
        )
        for k in pa.metrics
    }
    names = {r.reason for r in pa.top_reasons} | {r.reason for r in pb.top_reasons}
    changes = [
        ReasonChange(
            reason=r,
            a_lost_s=full_a.get(r, (0.0, 0))[0],
            b_lost_s=full_b.get(r, (0.0, 0))[0],
            delta_lost_s=full_b.get(r, (0.0, 0))[0] - full_a.get(r, (0.0, 0))[0],
        )
        for r in names
    ]
    changes.sort(key=lambda c: (-abs(c.delta_lost_s), c.reason))
    cites, n_raw = episode_citations(
        conn,
        [(f"a:{k}", _by_size(es)) for k, es in top_a]
        + [(f"b:{k}", _by_size(es)) for k, es in top_b],
    )
    union = [c for k, es in top_a for c in cites.get(f"a:{k}", ([], 0))[0]] + [
        c for k, es in top_b for c in cites.get(f"b:{k}", ([], 0))[0]
    ]
    return Result(
        status="ok",
        data=CompareData(
            source_system=sa.source_system, a=pa, b=pb, deltas=deltas, reason_changes=changes
        ),
        citations=_top_union([union]),
        citation_count=n_raw,
        window=win,
        assumptions=assumptions,
    )
