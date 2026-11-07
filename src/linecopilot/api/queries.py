"""Parameterised read queries behind the API. No SQL is built from request text except
fixed fragments chosen from allow-lists."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import psycopg

from linecopilot.api.models import CITATION_CAP, Citation

# raw_table value on core.event -> schema-qualified table. Only these are ever read.
RAW_TABLES = {
    "brick_oee": "raw.brick_oee",
    "brick_downtime": "raw.brick_downtime",
    "piade_raw": "raw.piade_raw",
}


def rows(conn: psycopg.Connection, sql: str, params: tuple | dict = ()) -> list[dict[str, Any]]:
    cur = conn.execute(sql, params)
    cols = [d.name for d in cur.description]
    return [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]


def f(v: Any) -> float | None:
    return None if v is None else float(v)


def citations_from_events(events: list[dict[str, Any]]) -> list[Citation]:
    return [
        Citation(
            raw_table=e["raw_table"],
            source_file=e["source_file"],
            raw_row_id=rid,
            event_id=e["event_id"],
        )
        for e in events
        for rid in e["raw_row_ids"]
    ]


def get_lines(conn) -> list[dict]:
    return rows(
        conn,
        """SELECT l.line_id, l.source_system, l.source_timezone, l.first_ts, l.last_ts,
                  l.event_count,
                  coalesce(array_agg(m.machine_id ORDER BY m.machine_id)
                           FILTER (WHERE m.machine_id IS NOT NULL), '{}') AS machines
           FROM core.line l LEFT JOIN core.machine m USING (line_id)
           GROUP BY l.line_id, l.source_system, l.source_timezone, l.first_ts, l.last_ts,
                    l.event_count
           ORDER BY l.line_id""",
    )


def get_machines(conn) -> list[dict]:
    return rows(conn, "SELECT * FROM core.machine ORDER BY machine_id")


def window_events(
    conn, line_id: str, machine_id: str | None, start: datetime, end: datetime
) -> tuple[list[Citation], int]:
    """First CITATION_CAP events (by event_id) starting in [start, end), plus the total."""
    where = "line_id = %(line)s AND start_ts >= %(s)s AND start_ts < %(e)s"
    p: dict[str, Any] = {"line": line_id, "s": start, "e": end, "cap": CITATION_CAP}
    if machine_id:
        where += " AND machine_id = %(m)s"
        p["m"] = machine_id
    total = conn.execute(f"SELECT count(*) FROM core.event WHERE {where}", p).fetchone()[0]
    ev = rows(
        conn,
        f"""SELECT event_id, raw_table, source_file, raw_row_ids FROM core.event
            WHERE {where} ORDER BY event_id LIMIT %(cap)s""",
        p,
    )
    return citations_from_events(ev), total


def _brick_extra() -> str:
    return "AND (event_type = 'production_count' OR stop_type <> 'Planned - Not included in OEE')"


def shift_exists(conn, shift_id: str) -> str | None:
    """source_system of the shift, or None when the shift is unknown."""
    r = conn.execute(
        "SELECT l.source_system FROM core.shift s JOIN core.line l USING (line_id) "
        "WHERE s.shift_id = %s",
        (shift_id,),
    ).fetchone()
    return r[0] if r else None


def shift_evidence(conn, shift_id: str, brick: bool, cap: int) -> tuple[list[dict[str, Any]], int]:
    """Every raw row behind a shift's numbers (same event set as shift_citations), with all
    raw columns as loaded. Returns (rows, event_count); rows cover the first `cap` events."""
    extra = _brick_extra() if brick else ""
    where = f"shift_id = %(id)s {extra}"
    total = conn.execute(
        f"SELECT count(*) FROM core.event WHERE {where}", {"id": shift_id}
    ).fetchone()[0]
    ev = rows(
        conn,
        f"""SELECT event_id, raw_table, source_file, raw_row_ids FROM core.event
            WHERE {where}
            ORDER BY (event_type = 'production_count') DESC, event_id LIMIT %(cap)s""",
        {"id": shift_id, "cap": cap},
    )
    raw: dict[tuple[str, str, int], dict[str, Any]] = {}
    for table, file in {(e["raw_table"], e["source_file"]) for e in ev}:
        ids = sorted(
            {
                i
                for e in ev
                if (e["raw_table"], e["source_file"]) == (table, file)
                for i in e["raw_row_ids"]
            }
        )
        for r in raw_rows(conn, {"raw_table": table, "source_file": file, "raw_row_ids": ids}):
            raw[(table, file, r["source_row"])] = r
    out = []
    for e in ev:
        for rid in e["raw_row_ids"]:
            r = raw.get((e["raw_table"], e["source_file"], rid))
            if r is not None:
                out.append(
                    {
                        "event_id": e["event_id"],
                        "raw_table": e["raw_table"],
                        "source_file": e["source_file"],
                        "source_row": rid,
                        "raw": r,
                    }
                )
    return out, total


def brick_performance_over_1(conn, start: datetime, end: datetime) -> tuple[int, float | None]:
    """Shifts in the window whose published performance exceeds 1, and the maximum."""
    n, mx = conn.execute(
        """SELECT count(*) FILTER (WHERE m.performance_pub > 1), max(m.performance_pub)
           FROM mart.brick_shift_oee m JOIN core.shift s ON s.shift_id = m.shift_id
           WHERE s.shift_start >= %s AND s.shift_start < %s""",
        (start, end),
    ).fetchone()
    return n, f(mx)


def shift_citations(
    conn, shift_ids: list[str], brick: bool
) -> dict[str, tuple[list[Citation], int]]:
    """Per-shift evidence (R16), capped per shift, with the true count.

    Brick: the shift's production_count event (always first, so the cap never drops it)
    plus its stops that count in OEE.
    PIADE: the interval events in the shift."""
    if not shift_ids:
        return {}
    extra = _brick_extra() if brick else ""
    ev = rows(
        conn,
        f"""SELECT * FROM (
                SELECT event_id, shift_id, raw_table, source_file, raw_row_ids,
                       row_number() OVER (
                           PARTITION BY shift_id
                           ORDER BY (event_type = 'production_count') DESC, event_id) AS rn,
                       count(*) OVER (PARTITION BY shift_id) AS n
                FROM core.event
                WHERE shift_id = ANY(%(ids)s) {extra}
            ) x WHERE rn <= %(cap)s ORDER BY shift_id, rn""",
        {"ids": shift_ids, "cap": CITATION_CAP},
    )
    out: dict[str, tuple[list[Citation], int]] = {}
    for sid in {e["shift_id"] for e in ev}:
        mine = [e for e in ev if e["shift_id"] == sid]
        out[sid] = (citations_from_events(mine), int(mine[0]["n"]))
    return out


# Brick ------------------------------------------------------------------------------------


def brick_shifts(conn, start: datetime, end: datetime, limit: int) -> tuple[list[dict], int]:
    base = """FROM mart.brick_shift_oee m
              JOIN core.shift s ON s.shift_id = m.shift_id
              WHERE s.shift_start >= %(s)s AND s.shift_start < %(e)s"""
    p = {"s": start, "e": end, "lim": limit}
    total = conn.execute(f"SELECT count(*) {base}", p).fetchone()[0]
    return rows(
        conn, f"SELECT m.*, s.shift_start {base} ORDER BY s.shift_start LIMIT %(lim)s", p
    ), total


def brick_months(conn, start: datetime, end: datetime) -> list[dict]:
    """Time-weighted from sums: stop and planned seconds, published quantities."""
    return rows(
        conn,
        """SELECT to_char(date_trunc('month', s.shift_start AT TIME ZONE 'Europe/Nicosia'),
                          'YYYY-MM') AS month,
                  min(s.shift_start) AS start,
                  count(*) AS n_shifts,
                  count(*) FILTER (WHERE m.planned_s_published IS NOT NULL) AS n_with_published,
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
        {"s": start, "e": end},
    )


# PIADE ------------------------------------------------------------------------------------


def piade_shifts(
    conn, machine_id: str, start: datetime, end: datetime, limit: int
) -> tuple[list[dict], int]:
    base = (
        "FROM mart.piade_shift_oee WHERE machine_id = %(m)s "
        "AND shift_start >= %(s)s AND shift_start < %(e)s"
    )
    p = {"m": machine_id, "s": start, "e": end, "lim": limit}
    total = conn.execute(f"SELECT count(*) {base}", p).fetchone()[0]
    return rows(conn, f"SELECT * {base} ORDER BY shift_start LIMIT %(lim)s", p), total


def piade_days(conn, machine_id: str, start: datetime, end: datetime) -> list[dict]:
    """Day = UTC date of shift start; sums over shifts, ratios recomputed (not averaged).
    Count-based P and Q use only shifts with complete counts, as in mart.piade_machine_oee."""
    return rows(
        conn,
        """WITH s AS (
               SELECT *, quality_reason IS NULL AS ok,
                      (shift_start AT TIME ZONE 'UTC')::date AS day
               FROM mart.piade_shift_oee
               WHERE machine_id = %(m)s AND shift_start >= %(s)s AND shift_start < %(e)s),
           a AS (
               SELECT day, min(shift_start) AS start, count(*) AS n_shifts,
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
           SELECT day::text AS key, start, n_shifts, n_shifts_counts_excluded, planned_s, run_s,
                  availability, performance_time,
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
           FROM r ORDER BY day""",
        {"m": machine_id, "s": start, "e": end},
    )


def piade_months(conn, machine_id: str, start: datetime, end: datetime) -> list[dict]:
    """From mart.piade_machine_oee. Whole calendar months: a month is included when its first
    day falls in [date_trunc('month', start), end)."""
    return rows(
        conn,
        """SELECT m.*, (m.month::timestamp AT TIME ZONE 'UTC') AS start
           FROM mart.piade_machine_oee m
           WHERE m.machine_id = %(m)s
             AND m.month >= (date_trunc('month', %(s)s AT TIME ZONE 'UTC'))::date
             AND m.month < %(e)s AT TIME ZONE 'UTC'
           ORDER BY m.month""",
        {"m": machine_id, "s": start, "e": end},
    )


def event_by_id(conn, event_id: int) -> dict | None:
    r = rows(
        conn,
        """SELECT event_id, event_key, raw_table, source_file, raw_row_ids
           FROM core.event WHERE event_id = %s""",
        (event_id,),
    )
    return r[0] if r else None


def raw_rows(conn, ev: dict) -> list[dict[str, Any]]:
    table = RAW_TABLES.get(ev["raw_table"])
    if table is None:  # never expected; refuse rather than build SQL from data
        raise ValueError(f"unknown raw table {ev['raw_table']!r}")
    return rows(
        conn,
        f"SELECT * FROM {table} WHERE source_file = %s AND source_row = ANY(%s) "
        "ORDER BY source_row",
        (ev["source_file"], list(ev["raw_row_ids"])),
    )
