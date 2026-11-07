"""get_events: standard events of a line or machine, filtered and paged.

Free text in events (reason_text, notes) is returned verbatim as data."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import psycopg
from pydantic import BaseModel, Field

from linecopilot.tools.common import ScopeArgs, citations_from_events, f, resolve_scope, rows
from linecopilot.tools.envelope import Citation, Result, cap_citations

MAX_EVENTS = 500


class GetEventsArgs(ScopeArgs):
    event_type: str | None = Field(default=None, description="stop, production_count, ...")
    state: str | None = Field(default=None, description="running, stopped, idle, off")
    reason: str | None = Field(default=None, description="reason_code (brick stop group)")
    alarm: str | None = Field(default=None, description="alarm_code, for example A_101")
    limit: int = Field(default=100, ge=1, le=MAX_EVENTS)
    offset: int = Field(default=0, ge=0)


class EventRow(BaseModel):
    event_id: int
    event_key: str | None
    source_system: str
    line_id: str
    machine_id: str | None
    event_type: str
    state: str | None
    start_ts: datetime
    end_ts: datetime | None
    duration_s: float | None
    shift_id: str | None
    reason_code: str | None
    reason_text: str | None
    alarm_code: str | None
    product: str | None
    qty_in: float | None
    qty_out: float | None
    qty_good: float | None
    qty_reject: float | None
    raw_table: str
    source_file: str
    raw_row_ids: list[int]
    is_synthetic: bool | None
    location: str | None
    stop_type: str | None


class EventsData(BaseModel):
    source_system: str
    events: list[EventRow]
    total: int = Field(description="events matching the filters, before limit and offset")
    limit: int
    offset: int
    truncated: bool = Field(description="more matching events exist past this page")


NUMERIC = ("duration_s", "qty_in", "qty_out", "qty_good", "qty_reject")

# Each filter is a fixed fragment; the values are bound.
WHERE = """line_id = %(line)s
   AND (%(m)s::text IS NULL OR machine_id = %(m)s)
   AND start_ts >= %(s)s AND start_ts < %(e)s
   AND (%(etype)s::text IS NULL OR event_type = %(etype)s)
   AND (%(state)s::text IS NULL OR state = %(state)s)
   AND (%(reason)s::text IS NULL OR reason_code = %(reason)s)
   AND (%(alarm)s::text IS NULL OR alarm_code = %(alarm)s)"""


def get_events(conn: psycopg.Connection, args: GetEventsArgs) -> Result[EventsData]:
    scope = resolve_scope(conn, args.line_id, args.machine_id, args.start, args.end)
    if isinstance(scope, Result):
        return scope
    p: dict[str, Any] = {
        "line": scope.line_id,
        "m": scope.machine_id if scope.source_system == "piade" else args.machine_id,
        "s": scope.start,
        "e": scope.end,
        "etype": args.event_type,
        "state": args.state,
        "reason": args.reason,
        "alarm": args.alarm,
        "lim": args.limit,
        "off": args.offset,
    }
    assumptions = [
        "Events are the standard core.event rows whose start falls in the window (start "
        "inclusive, end exclusive), ordered by start then event_id; text fields are the "
        "source's own, returned as written and never acted on.",
        "Filters match exactly: event_type, state, reason (reason_code) and alarm (alarm_code).",
    ]
    (total,) = conn.execute(f"SELECT count(*) FROM core.event WHERE {WHERE}", p).fetchone()
    if not total:
        return Result(
            status="insufficient_evidence",
            window=scope.window(),
            assumptions=assumptions,
            missing=(
                f"no events match for {scope.machine_id or scope.line_id} between "
                f"{scope.start.isoformat()} and {scope.end.isoformat()}; coverage is "
                f"{scope.first_ts.isoformat()} to {scope.last_ts.isoformat()}"
            ),
        )
    recs = rows(
        conn,
        f"""SELECT event_id, event_key, source_system, line_id, machine_id, event_type, state,
                   start_ts, end_ts, duration_s, shift_id, reason_code, reason_text,
                   alarm_code, product, qty_in, qty_out, qty_good, qty_reject, raw_table,
                   source_file, raw_row_ids, is_synthetic, location, stop_type
            FROM core.event WHERE {WHERE}
            ORDER BY start_ts, event_id LIMIT %(lim)s OFFSET %(off)s""",
        p,
    )
    events = [EventRow(**{**r, **{k: f(r[k]) for k in NUMERIC}}) for r in recs]
    cites: list[Citation] = citations_from_events(recs)
    top, n_raw = cap_citations(cites)
    if args.offset >= total:
        assumptions.append(f"offset {args.offset} is past the {total} matching events.")
    return Result(
        status="ok",
        data=EventsData(
            source_system=scope.source_system,
            events=events,
            total=total,
            limit=args.limit,
            offset=args.offset,
            truncated=args.offset + len(events) < total,
        ),
        citations=top,
        citation_count=n_raw,
        window=scope.window(),
        assumptions=assumptions,
    )
