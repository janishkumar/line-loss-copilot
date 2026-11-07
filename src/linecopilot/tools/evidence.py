"""Raw-row tools: the rows behind a shift, by citation or event id, exactly as loaded."""

from __future__ import annotations

from typing import Any, Self

import psycopg
from pydantic import BaseModel, ConfigDict, Field, model_validator

from linecopilot.tools.common import BRICK_EVIDENCE, RAW_TABLES, citations_from_events, rows
from linecopilot.tools.envelope import Citation, CitationRef, Result, cap_citations

EVIDENCE_CAP = 5000  # events per shift; a shift holds far fewer (PIADE: tens to hundreds)
MAX_REFS = 200
AS_LOADED = "Rows are the cited raw rows exactly as loaded (text columns), with source_row."

Key = tuple[str, str, int]


class SourceData(BaseModel):
    event_id: int
    event_key: str
    raw_table: str
    source_file: str
    rows: list[dict[str, Any]]


class EvidenceRow(BaseModel):
    event_id: int
    raw_table: str
    source_file: str
    source_row: int
    raw: dict[str, Any] = Field(description="all raw columns as loaded")


class ShiftEvidenceData(BaseModel):
    shift_id: str
    source_system: str
    rows: list[EvidenceRow]
    event_count: int
    truncated: bool = False
    missing_rows: list[CitationRef] = Field(
        default_factory=list, description="cited raw rows not found in the raw tables"
    )


class SourceRow(BaseModel):
    raw_table: str
    source_file: str
    raw_row_id: int
    event_id: int | None = None
    raw: dict[str, Any] = Field(description="all raw columns as loaded")


class SourceRowsData(BaseModel):
    rows: list[SourceRow]
    not_found: list[CitationRef] = Field(default_factory=list)
    not_found_event_ids: list[int] = Field(default_factory=list)


class ShiftEvidenceArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    shift_id: str = Field(description="e.g. brick:2026-02-02 or s_1:2020-01-01T06")


class GetSourceRowsArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    citations: list[CitationRef] = Field(default_factory=list, max_length=MAX_REFS)
    event_ids: list[int] = Field(default_factory=list, max_length=MAX_REFS)

    @model_validator(mode="after")
    def _some(self) -> Self:
        if not self.citations and not self.event_ids:
            raise ValueError("give citations or event_ids")
        return self


def _ref_text(k: Key) -> str:
    return f"{k[0]} {k[1]} row {k[2]}"


def fetch_raw(conn, keys: list[Key]) -> dict[Key, dict[str, Any]]:
    """Raw rows for the given (raw_table, source_file, source_row) keys, as loaded. Keys on
    a table outside RAW_TABLES are never queried and come back absent."""
    want: dict[tuple[str, str], set[int]] = {}
    for table, file, rid in keys:
        if table in RAW_TABLES:
            want.setdefault((table, file), set()).add(rid)
    out: dict[Key, dict[str, Any]] = {}
    for (table, file), ids in want.items():
        for r in rows(
            conn,
            f"SELECT * FROM {RAW_TABLES[table]} WHERE source_file = %s "
            "AND source_row = ANY(%s) ORDER BY source_row",
            (file, sorted(ids)),
        ):
            out[(table, file, r["source_row"])] = r
    return out


def event_rows(conn, event_ids: list[int]) -> list[dict[str, Any]]:
    return rows(
        conn,
        """SELECT event_id, event_key, raw_table, source_file, raw_row_ids
           FROM core.event WHERE event_id = ANY(%s) ORDER BY event_id""",
        (event_ids,),
    )


def event_source(conn: psycopg.Connection, event_id: int) -> Result[SourceData]:
    """One event and its raw rows (route /api/events/{event_id}/source)."""
    found = event_rows(conn, [event_id])
    if not found:
        return Result(status="out_of_scope", missing=f"no event with id {event_id}")
    ev = found[0]
    raw = fetch_raw(conn, [(ev["raw_table"], ev["source_file"], i) for i in ev["raw_row_ids"]])
    if not raw:
        return Result(
            status="insufficient_evidence",
            missing=f"event {event_id} points at rows not found in {ev['raw_table']}",
        )
    return Result(
        status="ok",
        data=SourceData(
            event_id=ev["event_id"],
            event_key=ev["event_key"],
            raw_table=ev["raw_table"],
            source_file=ev["source_file"],
            rows=[raw[k] for k in sorted(raw, key=lambda k: k[2])],
        ),
        citations=citations_from_events([ev]),
        citation_count=len(raw),
        assumptions=["Raw rows are shown as loaded (text columns), with source_row."],
    )


def get_source_rows(conn: psycopg.Connection, args: GetSourceRowsArgs) -> Result[SourceRowsData]:
    """The raw rows behind citations or event ids. References that match nothing are listed
    in data.not_found / data.not_found_event_ids and named in `missing`."""
    wanted: dict[Key, int | None] = {}
    for c in args.citations:
        wanted.setdefault((c.raw_table, c.source_file, c.raw_row_id), None)
    evs = event_rows(conn, list(dict.fromkeys(args.event_ids))) if args.event_ids else []
    known = {e["event_id"] for e in evs}
    for e in evs:
        for rid in e["raw_row_ids"]:
            k = (e["raw_table"], e["source_file"], rid)
            if wanted.get(k) is None:
                wanted[k] = e["event_id"]
    lost_events = [i for i in dict.fromkeys(args.event_ids) if i not in known]
    raw = fetch_raw(conn, list(wanted))
    found = [
        SourceRow(raw_table=k[0], source_file=k[1], raw_row_id=k[2], event_id=eid, raw=raw[k])
        for k, eid in wanted.items()
        if k in raw
    ]
    lost = [k for k in wanted if k not in raw]
    data = SourceRowsData(
        rows=found,
        not_found=[CitationRef(raw_table=t, source_file=f, raw_row_id=i) for t, f, i in lost],
        not_found_event_ids=lost_events,
    )
    gaps = [_ref_text(k) for k in lost] + [f"event {i}" for i in lost_events]
    missing = f"not found: {'; '.join(gaps)}" if gaps else None
    cites, total = cap_citations(
        [
            Citation(
                raw_table=r.raw_table,
                source_file=r.source_file,
                raw_row_id=r.raw_row_id,
                event_id=r.event_id,
            )
            for r in found
        ]
    )
    return Result(
        status="ok" if found else "insufficient_evidence",
        data=data,
        citations=cites,
        citation_count=total,
        assumptions=[AS_LOADED],
        missing=missing,
    )


def shift_evidence(conn: psycopg.Connection, args: ShiftEvidenceArgs) -> Result[ShiftEvidenceData]:
    """Every raw row behind a shift's numbers (the same event set as the shift's OEE
    citations), with all raw columns as loaded. Cited rows absent from the raw tables are
    reported in data.missing_rows, never dropped silently."""
    shift_id = args.shift_id
    found = conn.execute(
        "SELECT l.source_system FROM core.shift s JOIN core.line l USING (line_id) "
        "WHERE s.shift_id = %s",
        (shift_id,),
    ).fetchone()
    if found is None:
        return Result(status="out_of_scope", missing=f"unknown shift_id {shift_id!r}")
    system = found[0]
    extra = BRICK_EVIDENCE if system == "brick" else ""
    where = f"e.shift_id = %(id)s {extra}"
    n_events = conn.execute(
        f"SELECT count(*) FROM core.event e WHERE {where}", {"id": shift_id}
    ).fetchone()[0]
    if not n_events:
        return Result(
            status="insufficient_evidence", missing=f"shift {shift_id} has no events behind it"
        )
    ev = rows(
        conn,
        f"""SELECT e.event_id, e.raw_table, e.source_file, e.raw_row_ids FROM core.event e
            WHERE {where}
            ORDER BY (e.event_type = 'production_count') DESC, e.event_id LIMIT %(cap)s""",
        {"id": shift_id, "cap": EVIDENCE_CAP},
    )
    keys = [(e["raw_table"], e["source_file"], rid) for e in ev for rid in e["raw_row_ids"]]
    raw = fetch_raw(conn, keys)
    out: list[EvidenceRow] = []
    lost: list[Key] = []
    for e in ev:
        for rid in e["raw_row_ids"]:
            k = (e["raw_table"], e["source_file"], rid)
            if k in raw:
                out.append(
                    EvidenceRow(
                        event_id=e["event_id"],
                        raw_table=k[0],
                        source_file=k[1],
                        source_row=rid,
                        raw=raw[k],
                    )
                )
            else:
                lost.append(k)
    missing_rows = [CitationRef(raw_table=t, source_file=f, raw_row_id=i) for t, f, i in lost]
    assumptions = [
        AS_LOADED,
        (
            "Brick: the shift's production_count row plus the stops that count in OEE."
            if system == "brick"
            else "PIADE: the interval rows that start in the shift."
        ),
    ]
    truncated = n_events > EVIDENCE_CAP
    if truncated:
        assumptions.append(f"Showing the first {EVIDENCE_CAP} of {n_events} events.")
    if lost:
        assumptions.append(
            f"{len(lost)} cited raw row(s) not found in the raw tables: "
            f"{'; '.join(_ref_text(k) for k in lost)}. They are listed in data.missing_rows."
        )
    if not out:
        return Result(
            status="insufficient_evidence",
            assumptions=assumptions,
            missing=f"the raw rows behind shift {shift_id} were not found",
        )
    return Result(
        status="ok",
        data=ShiftEvidenceData(
            shift_id=shift_id,
            source_system=system,
            rows=out,
            event_count=n_events,
            truncated=truncated,
            missing_rows=missing_rows,
        ),
        citations=[
            Citation(
                raw_table=r.raw_table,
                source_file=r.source_file,
                raw_row_id=r.source_row,
                event_id=r.event_id,
            )
            for r in out
        ],
        citation_count=n_events,
        assumptions=assumptions,
    )
