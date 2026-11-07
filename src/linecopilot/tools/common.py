"""Shared query helpers and scope resolution for the tools. Values are always bound; the
only SQL fragments interpolated are fixed strings chosen in code, never input."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
from pydantic import BaseModel, ConfigDict, Field

from linecopilot.tools.envelope import CITATION_CAP, Citation, Result, Window, cap_citations

# raw_table value on core.event -> schema-qualified table. Only these are ever read.
RAW_TABLES = {
    "brick_oee": "raw.brick_oee",
    "brick_downtime": "raw.brick_downtime",
    "piade_raw": "raw.piade_raw",
}
END_BEFORE_START = "end must be after start"
# Brick evidence: the production_count row plus the stops that count in OEE.
BRICK_EVIDENCE = (
    "AND (e.event_type = 'production_count' OR e.stop_type <> 'Planned - Not included in OEE')"
)


def rows(conn: psycopg.Connection, sql: str, params: tuple | dict = ()) -> list[dict[str, Any]]:
    cur = conn.execute(sql, params)
    cols = [d.name for d in cur.description]
    return [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]


def f(v: Any) -> float | None:
    return None if v is None else float(v)


def utc(d: datetime | None) -> datetime | None:
    """Datetimes without a zone are taken as UTC."""
    if d is None:
        return None
    return d if d.tzinfo else d.replace(tzinfo=UTC)


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


def line_rows(conn, line_id: str | None = None) -> list[dict[str, Any]]:
    """core.line with its machine ids; all lines, or the one asked for."""
    return rows(
        conn,
        """SELECT l.line_id, l.source_system, l.source_timezone, l.first_ts, l.last_ts,
                  l.event_count,
                  coalesce(array_agg(m.machine_id ORDER BY m.machine_id)
                           FILTER (WHERE m.machine_id IS NOT NULL), '{}') AS machines
           FROM core.line l LEFT JOIN core.machine m USING (line_id)
           WHERE %(id)s::text IS NULL OR l.line_id = %(id)s
           GROUP BY l.line_id, l.source_system, l.source_timezone, l.first_ts, l.last_ts,
                    l.event_count
           ORDER BY l.line_id""",
        {"id": line_id},
    )


def machine_rows(conn, machine_id: str | None = None) -> list[dict[str, Any]]:
    return rows(
        conn,
        "SELECT * FROM core.machine WHERE %(id)s::text IS NULL OR machine_id = %(id)s "
        "ORDER BY machine_id",
        {"id": machine_id},
    )


# Said in every scoped tool's description and argument descriptions: small models otherwise
# pass line_id='brick' with a PIADE machine_id.
SCOPE_HINT = (
    "Brick line: pass line_id='brick' and no machine_id. PIADE machines s_1..s_5: pass "
    "machine_id only. Dates: ISO; end is exclusive."
)
MONTH_GROUP_HINT = (
    "For a monthly figure use group='month' (or a whole-month window), not an average of "
    "shift or day rows."
)
MONTH_WINDOW_HINT = (
    "For a monthly figure use a whole-month window (start = first day, end = first day of "
    "next month), not an average of shift or day rows."
)
LINE_ID_DESC = "'brick' for the brick line (then no machine_id); leave empty for PIADE machines"
MACHINE_ID_DESC = "PIADE machine s_1..s_5: pass machine_id only (no line_id); empty for brick"
START_DESC = "ISO date or time, inclusive; no zone means UTC"
END_DESC = (
    "ISO date or time, exclusive (a month ends on the first day of the next); no zone means UTC"
)


class ScopeArgs(BaseModel):
    """Asset and window arguments shared by the tools that read a line or machine."""

    model_config = ConfigDict(extra="forbid")

    line_id: str | None = Field(default=None, description=LINE_ID_DESC)
    machine_id: str | None = Field(default=None, description=MACHINE_ID_DESC)
    start: datetime | None = Field(default=None, description=START_DESC)
    end: datetime | None = Field(default=None, description=END_DESC)


@dataclass(frozen=True)
class Scope:
    line_id: str
    machine_id: str | None
    source_system: str
    start: datetime
    end: datetime  # exclusive
    first_ts: datetime
    last_ts: datetime

    def window(self, group: str | None = None) -> Window:
        return Window(
            start=self.start,
            end=self.end,
            line_id=self.line_id,
            machine_id=self.machine_id,
            group=group,
        )


def resolve_scope(
    conn,
    line_id: str | None,
    machine_id: str | None,
    start: datetime | None,
    end: datetime | None,
) -> Scope | Result:
    """Check the asset ids and window; default start/end to the line's coverage.

    Returns an out_of_scope Result for missing or unknown ids, a machine not on the line,
    or end <= start. A PIADE line is one machine, so its machine_id defaults to the line."""
    lo, hi = utc(start), utc(end)
    win = Window(start=lo, end=hi, line_id=line_id, machine_id=machine_id)

    def out(msg: str) -> Result:
        return Result(status="out_of_scope", window=win, missing=msg)

    if lo is not None and hi is not None and hi <= lo:
        return out(END_BEFORE_START)
    if not line_id and not machine_id:
        return out("give line_id or machine_id")
    machine = None
    if machine_id:
        found = machine_rows(conn, machine_id)
        if not found:
            return out(f"unknown machine_id {machine_id!r}")
        machine = found[0]
    if line_id:
        lines = line_rows(conn, line_id)
        if not lines:
            return out(f"unknown line_id {line_id!r}")
        if machine and machine["line_id"] != line_id:
            return out(f"machine {machine_id!r} is not on line {line_id!r}")
    else:
        lines = line_rows(conn, machine["line_id"])
    line = lines[0]
    if line["source_system"] == "piade":
        machine_id = machine_id or line["line_id"]
    if lo is None:
        # The earliest shift start, not the first event: a shift belongs to a window by its
        # start, so starting at the first event would drop the shift that contains it.
        (first_shift,) = conn.execute(
            "SELECT min(shift_start) FROM core.shift WHERE line_id = %s", (line["line_id"],)
        ).fetchone()
        lo = min(x for x in (first_shift, line["first_ts"]) if x is not None)
    hi = hi or line["last_ts"] + timedelta(microseconds=1)
    if hi <= lo:
        win = Window(start=lo, end=hi, line_id=line["line_id"], machine_id=machine_id)
        return out(END_BEFORE_START)
    return Scope(
        line_id=line["line_id"],
        machine_id=machine_id,
        source_system=line["source_system"],
        start=lo,
        end=hi,
        first_ts=line["first_ts"],
        last_ts=line["last_ts"],
    )


def group_citations(
    conn, groups: list[tuple[str, list[str]]], brick: bool
) -> tuple[dict[str, tuple[list[Citation], int]], int]:
    """Evidence per group of shifts, capped per group at CITATION_CAP, with the number of
    distinct raw rows behind each group and behind all groups together.

    Events are ordered by the group's shift order, then (brick) the production_count event
    first, then event_id. Brick evidence is the production_count event plus the stops that
    count in OEE; PIADE evidence is the interval events in the shifts (R16)."""
    keys = [k for k, sids in groups for _ in sids]
    sids = [s for _, ss in groups for s in ss]
    if not sids:
        return {}, 0
    ords = [i for _, ss in groups for i in range(len(ss))]
    extra = BRICK_EVIDENCE if brick else ""
    p = {"keys": keys, "sids": sids, "ords": ords, "cap": CITATION_CAP}
    ev_sql = f"""SELECT g.key, g.ord, e.event_id, e.event_type, e.raw_table, e.source_file,
                        e.raw_row_ids
                 FROM unnest(%(keys)s::text[], %(sids)s::text[], %(ords)s::int[])
                      AS g(key, shift_id, ord)
                 JOIN core.event e ON e.shift_id = g.shift_id
                 WHERE true {extra}"""
    return keyed_citations(conn, ev_sql, p, "ord, (event_type = 'production_count') DESC, event_id")


def keyed_citations(
    conn, ev_sql: str, params: dict[str, Any], order: str
) -> tuple[dict[str, tuple[list[Citation], int]], int]:
    """Capped citations per key from `ev_sql` (columns key, ord, event_id, event_type,
    raw_table, source_file, raw_row_ids), ordered within a key by `order`, with the number
    of distinct raw rows per key and over all keys. `ev_sql` and `order` are fixed strings
    from code; `params` binds every value, including `cap`."""
    ev = rows(
        conn,
        f"""SELECT * FROM (
                SELECT ev.*, row_number() OVER (PARTITION BY key ORDER BY {order}) AS rn
                FROM ({ev_sql}) ev
            ) x WHERE rn <= %(cap)s ORDER BY key, rn""",
        params,
    )
    # GROUPING SETS: one count per key plus the overall count (key null).
    counts = {
        k: int(n)
        for k, n in conn.execute(
            f"""SELECT ev.key, count(DISTINCT (ev.raw_table, ev.source_file, rid))
                FROM ({ev_sql}) ev, unnest(ev.raw_row_ids) AS rid
                GROUP BY GROUPING SETS ((ev.key), ())""",
            params,
        ).fetchall()
    }
    by_key: dict[str, list[dict[str, Any]]] = {}
    for e in ev:
        by_key.setdefault(e["key"], []).append(e)
    per_key = {
        k: (cap_citations(citations_from_events(mine))[0], counts.get(k, 0))
        for k, mine in by_key.items()
    }
    return per_key, counts.get(None, 0)


def shift_citations(
    conn, shift_ids: list[str], brick: bool
) -> dict[str, tuple[list[Citation], int]]:
    """Per-shift evidence, capped per shift, with the distinct raw-row count."""
    return group_citations(conn, [(s, [s]) for s in shift_ids], brick)[0]
