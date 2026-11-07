"""get_oee: OEE per shift, day or month for a brick line or a PIADE machine.

Every row cites the evidence events of the shifts aggregated into it; the top-level
citations are the capped union of the returned rows' citations, in row order."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

import psycopg
from pydantic import BaseModel, ConfigDict, Field

from linecopilot.tools.common import Scope, f, group_citations, resolve_scope, rows
from linecopilot.tools.envelope import Citation, Result, cap_citations

GroupBy = Literal["shift", "day", "month"]
MAX_ROWS = 2000

ASSUME_PIADE = [
    "PIADE ideal rate is the p95 of speed over production rows per machine (not stated by the "
    "dataset); p90 and p99 OEE are returned as oee_p90 and oee_p99.",
    "PIADE shifts are an assumed 3 x 8 h UTC calendar starting 06:00, 14:00, 22:00.",
    "Count-based performance and quality exclude shifts whose counters have glitches or that "
    "ran with no input counted (quality_reason set: pi_glitch, po_glitch or no_input); those "
    "shifts have null quality and oee. n_shifts_counts_excluded counts only shifts that ran.",
]
ASSUME_BRICK = [
    "Brick planned time is a published input; availability_calc is recomputed from the stop "
    "log (union of in-OEE stops), the other *_pub values are the published ones.",
    "Brick performance and quality are the published values (no independent source); "
    "oee_calc_with_pub_pq combines calculated availability with them.",
    "Brick has one shift per date (Europe/Nicosia local); window times without a zone are UTC.",
]
ASSUME_WINDOW = (
    "Window start is inclusive, end is exclusive; a shift belongs to the window by its start."
)
ASSUME_CITES = (
    "Each row cites the evidence events of the shifts in it (capped per row); top-level "
    "citations are the capped union of the returned rows' citations; citation_count is the "
    "number of distinct raw rows behind the returned rows."
)


class GetOeeArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    line_id: str | None = Field(default=None, description="brick, or a PIADE line s_1..s_5")
    machine_id: str | None = Field(default=None, description="PIADE machine s_1..s_5")
    start: datetime | None = Field(default=None, description="inclusive; no zone means UTC")
    end: datetime | None = Field(default=None, description="exclusive; no zone means UTC")
    group: GroupBy = "shift"
    limit: int = Field(default=200, ge=1, le=MAX_ROWS)


class OeeRow(BaseModel):
    """One group (shift, day or month). `metrics` holds the numbers, `details` labels."""

    key: str = Field(description="shift_id, or the day / month start for coarser groups")
    start: datetime | None = None
    metrics: dict[str, float | None]
    details: dict[str, str | int | None] = Field(default_factory=dict)
    citations: list[Citation] = Field(default_factory=list)
    citation_count: int = Field(default=0, description="distinct raw rows behind this row")


class OeeData(BaseModel):
    source_system: str
    group: str
    rows: list[OeeRow]
    row_count: int
    rows_truncated: bool = False


def get_oee(conn: psycopg.Connection, args: GetOeeArgs) -> Result[OeeData]:
    scope = resolve_scope(conn, args.line_id, args.machine_id, args.start, args.end)
    if isinstance(scope, Result):
        if scope.window is not None:
            scope.window.group = args.group
        return scope
    brick = scope.source_system == "brick"
    group, limit = args.group, args.limit
    win = scope.window(group)
    assumptions = [*(ASSUME_BRICK if brick else ASSUME_PIADE), ASSUME_WINDOW]

    if brick:
        data, shift_ids = _brick(conn, scope, group, limit)
    else:
        data, shift_ids = _piade(conn, scope, group, limit)
    if group == "month" and not brick:
        assumptions.append(
            "Month groups are whole UTC calendar months whose first day falls in the "
            "window (start rounded down to its month)."
        )
    if data.rows_truncated:
        assumptions.append(
            f"Showing the first {limit} of {data.row_count} rows; narrow the window or raise limit."
        )
    if not data.rows:
        return Result(
            status="insufficient_evidence",
            window=win,
            assumptions=assumptions,
            missing=(
                f"no {scope.source_system} data for {scope.machine_id or scope.line_id} "
                f"between {scope.start.isoformat()} and {scope.end.isoformat()}; coverage is "
                f"{scope.first_ts.isoformat()} to {scope.last_ts.isoformat()}"
            ),
        )
    cites, n_raw = group_citations(
        conn, [(r.key, shift_ids.get(r.key, [])) for r in data.rows], brick
    )
    for r in data.rows:
        r.citations, r.citation_count = cites.get(r.key, ([], 0))
    if brick:
        n_over, max_perf = _brick_performance_over_1(conn, scope)
        if n_over:
            assumptions.append(
                f"Published brick performance exceeds 1 on {n_over} shifts in this window "
                f"(maximum {max_perf:.3f}); used as published, not capped."
            )
    assumptions.append(ASSUME_CITES)
    top, _ = cap_citations([c for r in data.rows for c in r.citations])
    return Result(
        status="ok",
        data=data,
        citations=top,
        citation_count=n_raw,
        window=win,
        assumptions=assumptions,
    )


# Brick ------------------------------------------------------------------------------------

BRICK_SHIFT = (
    "planned_s_published stop_s_union availability_calc availability_pub availability_gap "
    "performance_pub quality_pub oee_calc_with_pub_pq oee_pub oee_gap"
).split()


def _brick_performance_over_1(conn, scope: Scope) -> tuple[int, float | None]:
    """Shifts in the window whose published performance exceeds 1, and the maximum."""
    n, mx = conn.execute(
        """SELECT count(*) FILTER (WHERE m.performance_pub > 1), max(m.performance_pub)
           FROM mart.brick_shift_oee m JOIN core.shift s ON s.shift_id = m.shift_id
           WHERE s.shift_start >= %s AND s.shift_start < %s""",
        (scope.start, scope.end),
    ).fetchone()
    return n, f(mx)


def _brick(conn, scope: Scope, group: str, limit: int) -> tuple[OeeData, dict[str, list[str]]]:
    p: dict[str, Any] = {"s": scope.start, "e": scope.end, "lim": limit}
    if group == "month":
        out, sids = [], {}
        for m in rows(
            conn,
            """SELECT to_char(date_trunc('month', s.shift_start AT TIME ZONE 'Europe/Nicosia'),
                              'YYYY-MM') AS month,
                      min(s.shift_start) AS start,
                      array_agg(m.shift_id ORDER BY s.shift_start) AS shift_ids,
                      count(*) AS n_shifts,
                      count(*) FILTER (WHERE m.planned_s_published IS NOT NULL)
                          AS n_with_published,
                      sum(m.planned_s_published) AS planned_s,
                      sum(m.stop_s_union) FILTER (WHERE m.planned_s_published IS NOT NULL)
                          AS stop_s_union,
                      sum(m.stop_s_implied_pub) AS stop_s_implied_pub,
                      sum(p.total_qty) AS total_qty,
                      sum(p.good_qty) AS good_qty,
                      sum(p.ideal_qty) AS ideal_qty
               FROM mart.brick_shift_oee m
               JOIN core.shift s ON s.shift_id = m.shift_id
               LEFT JOIN core.brick_shift_published p ON p.shift_id = m.shift_id
               WHERE s.shift_start >= %(s)s AND s.shift_start < %(e)s
               GROUP BY 1 ORDER BY 1""",
            p,
        ):
            planned = f(m["planned_s"])
            ideal, total = f(m["ideal_qty"]), f(m["total_qty"])
            a_calc = _ratio_1m(m["stop_s_union"], planned)
            a_pub = _ratio_1m(m["stop_s_implied_pub"], planned)
            perf = total / ideal if ideal and total is not None else None
            qual = f(m["good_qty"]) / total if total else None
            sids[m["month"]] = list(m["shift_ids"])
            out.append(
                OeeRow(
                    key=m["month"],
                    start=m["start"],
                    metrics={
                        "planned_s": planned,
                        "stop_s_union": f(m["stop_s_union"]),
                        "availability_calc": a_calc,
                        "availability_pub": a_pub,
                        "performance_pub": perf,
                        "quality_pub": qual,
                        "oee_calc_with_pub_pq": (
                            a_calc * perf * qual if None not in (a_calc, perf, qual) else None
                        ),
                    },
                    details={
                        "n_shifts": m["n_shifts"],
                        "n_with_published": m["n_with_published"],
                    },
                )
            )
        return OeeData(source_system="brick", group=group, rows=out, row_count=len(out)), sids
    # Brick has one shift per date, so day and shift are the same rows.
    base = """FROM mart.brick_shift_oee m
              JOIN core.shift s ON s.shift_id = m.shift_id
              WHERE s.shift_start >= %(s)s AND s.shift_start < %(e)s"""
    total = conn.execute(f"SELECT count(*) {base}", p).fetchone()[0]
    recs = rows(conn, f"SELECT m.*, s.shift_start {base} ORDER BY s.shift_start LIMIT %(lim)s", p)
    out = [
        OeeRow(
            key=r["shift_id"],
            start=r["shift_start"],
            metrics={k: f(r[k]) for k in BRICK_SHIFT},
            details={
                "period": r["period"],
                "match_status": r["match_status"],
                "shift_date": r["shift_date"].isoformat(),
            },
        )
        for r in recs
    ]
    data = OeeData(
        source_system="brick",
        group=group,
        rows=out,
        row_count=total,
        rows_truncated=total > len(out),
    )
    return data, {r.key: [r.key] for r in out}


def _ratio_1m(stop: Any, planned: float | None) -> float | None:
    if stop is None or not planned:
        return None
    return 1 - float(stop) / planned


# PIADE ------------------------------------------------------------------------------------

PIADE_SHIFT = (
    "planned_s run_s production_s input_qty output_qty availability performance_count_p95 "
    "performance_time quality oee oee_p90 oee_p99"
).split()

# Day = UTC date of shift start; sums over shifts, ratios recomputed (not averaged).
# Count-based P and Q use only shifts with complete counts, as in mart.piade_machine_oee.
PIADE_DAYS = """WITH s AS (
       SELECT *, quality_reason IS NULL AS ok,
              (shift_start AT TIME ZONE 'UTC')::date AS day
       FROM mart.piade_shift_oee
       WHERE machine_id = %(m)s AND shift_start >= %(s)s AND shift_start < %(e)s),
   a AS (
       SELECT day, min(shift_start) AS start, count(*) AS n_shifts,
              array_agg(shift_id ORDER BY shift_start) AS shift_ids,
              count(*) FILTER (WHERE NOT ok AND run_s > 0) AS n_shifts_counts_excluded,
              sum(planned_s) AS planned_s, sum(run_s) AS run_s,
              sum(production_s) AS production_s,
              sum(run_s) FILTER (WHERE ok) AS run_s_counted,
              sum(input_qty) FILTER (WHERE ok) AS input_qty,
              sum(output_qty) FILTER (WHERE ok) AS output_qty
       FROM s GROUP BY day),
   r AS (
       SELECT a.*, a.run_s / nullif(a.planned_s, 0) AS availability,
              a.production_s / nullif(a.run_s, 0) AS performance_time,
              a.input_qty / nullif(i.p95 * a.run_s_counted / 3600.0, 0) AS p95,
              a.input_qty / nullif(i.p90 * a.run_s_counted / 3600.0, 0) AS p90,
              a.input_qty / nullif(i.p99 * a.run_s_counted / 3600.0, 0) AS p99,
              a.output_qty / nullif(a.input_qty, 0) AS q
       FROM a JOIN mart.piade_ideal_rate i ON i.machine_id = %(m)s)
   SELECT day::text AS key, start, shift_ids, n_shifts, n_shifts_counts_excluded, planned_s,
          run_s, availability, performance_time,
          CASE WHEN p95 > 1 THEN 1 ELSE p95 END AS performance_count_p95,
          CASE WHEN q > 1 THEN 1 ELSE q END AS quality,
          CASE WHEN availability = 0 THEN 0 ELSE availability *
               (CASE WHEN p95 > 1 THEN 1 ELSE p95 END) *
               (CASE WHEN q > 1 THEN 1 ELSE q END) END AS oee,
          CASE WHEN availability = 0 THEN 0 ELSE availability *
               (CASE WHEN p90 > 1 THEN 1 ELSE p90 END) *
               (CASE WHEN q > 1 THEN 1 ELSE q END) END AS oee_p90,
          CASE WHEN availability = 0 THEN 0 ELSE availability *
               (CASE WHEN p99 > 1 THEN 1 ELSE p99 END) *
               (CASE WHEN q > 1 THEN 1 ELSE q END) END AS oee_p99
   FROM r ORDER BY day"""

# Whole calendar months from mart.piade_machine_oee: a month is included when its first day
# falls in [date_trunc('month', start), end). Its shifts are every shift of the machine whose
# start falls in the month (the mart's own grouping), so they may run past `end`.
PIADE_MONTHS = """SELECT m.*, (m.month::timestamp AT TIME ZONE 'UTC') AS start,
          array(SELECT x.shift_id FROM mart.piade_shift_oee x
                WHERE x.machine_id = m.machine_id
                  AND (date_trunc('month', x.shift_start AT TIME ZONE 'UTC'))::date = m.month
                ORDER BY x.shift_start) AS shift_ids
   FROM mart.piade_machine_oee m
   WHERE m.machine_id = %(m)s
     AND m.month >= (date_trunc('month', %(s)s AT TIME ZONE 'UTC'))::date
     AND m.month < %(e)s AT TIME ZONE 'UTC'
   ORDER BY m.month"""


def _piade(conn, scope: Scope, group: str, limit: int) -> tuple[OeeData, dict[str, list[str]]]:
    p: dict[str, Any] = {"m": scope.machine_id, "s": scope.start, "e": scope.end, "lim": limit}
    if group == "shift":
        base = (
            "FROM mart.piade_shift_oee WHERE machine_id = %(m)s "
            "AND shift_start >= %(s)s AND shift_start < %(e)s"
        )
        total = conn.execute(f"SELECT count(*) {base}", p).fetchone()[0]
        recs = rows(conn, f"SELECT * {base} ORDER BY shift_start LIMIT %(lim)s", p)
        out = [
            OeeRow(
                key=r["shift_id"],
                start=r["shift_start"],
                metrics={k: f(r[k]) for k in PIADE_SHIFT},
                details={"quality_reason": r["quality_reason"], "n_capped": r["n_capped"]},
            )
            for r in recs
        ]
        data = OeeData(
            source_system="piade",
            group=group,
            rows=out,
            row_count=total,
            rows_truncated=total > len(out),
        )
        return data, {r.key: [r.key] for r in out}
    if group == "day":
        recs = rows(conn, PIADE_DAYS, p)
    else:
        recs = rows(conn, PIADE_MONTHS, p)
        for r in recs:
            r["key"] = r["month"].isoformat()
    keys = [k for k in PIADE_SHIFT if recs and k in recs[0]]
    out = [
        OeeRow(
            key=r["key"],
            start=r["start"],
            metrics={k: f(r[k]) for k in keys},
            details={
                "n_shifts": r["n_shifts"],
                "n_shifts_counts_excluded": r["n_shifts_counts_excluded"],
            },
        )
        for r in recs
    ]
    data = OeeData(source_system="piade", group=group, rows=out, row_count=len(out))
    return data, {r["key"]: list(r["shift_ids"]) for r in recs}
