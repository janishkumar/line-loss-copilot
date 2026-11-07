"""Read-only API over the marts and raw rows. Every route returns the Result envelope."""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal

import psycopg
from fastapi import Depends, FastAPI, HTTPException, Query

from linecopilot.api import queries as q
from linecopilot.api.models import (
    AssetsData,
    EvidenceRow,
    LineInfo,
    MachineInfo,
    OeeData,
    OeeRow,
    Result,
    ShiftEvidenceData,
    SourceData,
    Window,
)
from linecopilot.config import get_settings
from linecopilot.reports.oee_validation import validate_oee

GroupBy = Literal["shift", "day", "month"]
MAX_ROWS = 2000
EVIDENCE_CAP = 5000  # events per shift; a shift holds far fewer (PIADE: tens to hundreds)

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


def create_app(db_url: str | None = None) -> FastAPI:
    app = FastAPI(title="line-loss-copilot API", version="0.1.0")
    url = db_url or get_settings().database_url

    def get_conn() -> Iterator[psycopg.Connection]:
        with psycopg.connect(url, autocommit=True) as conn:
            yield conn

    Conn = Annotated[psycopg.Connection, Depends(get_conn)]

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/assets")
    def assets(conn: Conn) -> Result[AssetsData]:
        lines = [LineInfo(**r) for r in q.get_lines(conn)]
        machines = [MachineInfo(**r) for r in q.get_machines(conn)]
        return Result(
            status="ok",
            data=AssetsData(lines=lines, machines=machines),
            assumptions=[
                "Coverage is from first to last event start/end per asset; machines have "
                "different date ranges and gaps inside a range are not filled.",
                "No synthetic data is loaded in stage 1.",
            ],
        )

    @app.get("/api/oee")
    def oee(
        conn: Conn,
        line_id: str | None = None,
        machine_id: str | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
        group: GroupBy = "shift",
        limit: Annotated[int, Query(ge=1, le=MAX_ROWS)] = 200,
    ) -> Result[OeeData]:
        win = Window(line_id=line_id, machine_id=machine_id, group=group)
        if not line_id and not machine_id:
            return Result(status="out_of_scope", window=win, missing="give line_id or machine_id")
        lines = {r["line_id"]: r for r in q.get_lines(conn)}
        machines = {r["machine_id"]: r for r in q.get_machines(conn)}
        if machine_id and machine_id not in machines:
            return Result(
                status="out_of_scope", window=win, missing=f"unknown machine_id {machine_id!r}"
            )
        if line_id and line_id not in lines:
            return Result(status="out_of_scope", window=win, missing=f"unknown line_id {line_id!r}")
        if machine_id and line_id and machines[machine_id]["line_id"] != line_id:
            return Result(
                status="out_of_scope",
                window=win,
                missing=f"machine {machine_id!r} is not on line {line_id!r}",
            )
        line = lines[line_id or machines[machine_id]["line_id"]]
        line_id = line["line_id"]
        if line["source_system"] == "piade":
            machine_id = machine_id or line_id  # each PIADE machine is its own line
        lo, hi = (
            _utc(start) or line["first_ts"],
            _utc(end) or line["last_ts"] + timedelta(microseconds=1),
        )
        if hi <= lo:
            raise HTTPException(422, "end must be after start")
        win = Window(start=lo, end=hi, line_id=line_id, machine_id=machine_id, group=group)
        brick = line["source_system"] == "brick"
        assumptions = [*(ASSUME_BRICK if brick else ASSUME_PIADE), ASSUME_WINDOW]

        if brick:
            data = _brick(conn, lo, hi, group, limit)
        else:
            data = _piade(conn, machine_id, lo, hi, group, limit)
        if group == "month" and not brick:
            assumptions.append(
                "Month groups are whole UTC calendar months whose first day falls in the "
                "window (start rounded down to its month)."
            )
        if data.rows_truncated:
            assumptions.append(
                f"Showing the first {limit} of {data.row_count} rows; narrow the window or "
                "raise limit."
            )
        if not data.rows:
            return Result(
                status="insufficient_evidence",
                window=win,
                assumptions=assumptions,
                missing=(
                    f"no {line['source_system']} data for {machine_id or line_id} between "
                    f"{lo.isoformat()} and {hi.isoformat()}; coverage is "
                    f"{line['first_ts'].isoformat()} to {line['last_ts'].isoformat()}"
                ),
            )
        if brick:
            n_over, max_perf = q.brick_performance_over_1(conn, lo, hi)
            if n_over:
                assumptions.append(
                    f"Published brick performance exceeds 1 on {n_over} shifts in this window "
                    f"(maximum {max_perf:.3f}); used as published, not capped."
                )
        cites, total = q.window_events(conn, line_id, machine_id if not brick else None, lo, hi)
        return Result(
            status="ok",
            data=data,
            citations=cites,
            citation_count=total,
            window=win,
            assumptions=assumptions,
        )

    @app.get("/api/oee/validation")
    def validation(conn: Conn) -> Result[dict[str, Any]]:
        # Computed from the marts on each call, not read from evals/results/oee_validation.json:
        # the file can be stale after a rebuild, and the image does not ship evals/.
        rep = validate_oee(conn).to_dict()
        return Result(
            status="ok",
            data=rep,
            window=Window(
                start=datetime.fromisoformat(rep["windows"]["before"]["first"]).replace(tzinfo=UTC),
                end=datetime.fromisoformat(rep["windows"]["after"]["last"]).replace(tzinfo=UTC)
                + timedelta(days=1),
                line_id="brick",
            ),
            assumptions=[
                "Computed availability uses the published planned time; performance and "
                "quality are the published values.",
                "Each row's shift_id matches the shift rows of /api/oee, which carry citations.",
            ],
        )

    @app.get("/api/shifts/{shift_id}/evidence")
    def shift_evidence(shift_id: str, conn: Conn) -> Result[ShiftEvidenceData]:
        system = q.shift_exists(conn, shift_id)
        if system is None:
            return Result(status="out_of_scope", missing=f"unknown shift_id {shift_id!r}")
        recs, n_events = q.shift_evidence(conn, shift_id, system == "brick", EVIDENCE_CAP)
        if not recs:
            return Result(
                status="insufficient_evidence",
                missing=f"shift {shift_id} has no events behind it",
            )
        rows = [EvidenceRow(**r) for r in recs]
        assumptions = [
            "Rows are the cited raw rows exactly as loaded (text columns), with source_row.",
            (
                "Brick: the shift's production_count row plus the stops that count in OEE."
                if system == "brick"
                else "PIADE: the interval rows that start in the shift."
            ),
        ]
        truncated = n_events > EVIDENCE_CAP
        if truncated:
            assumptions.append(f"Showing the first {EVIDENCE_CAP} of {n_events} events.")
        return Result(
            status="ok",
            data=ShiftEvidenceData(
                shift_id=shift_id,
                source_system=system,
                rows=rows,
                event_count=n_events,
                truncated=truncated,
            ),
            citations=q.citations_from_events(
                [
                    {
                        "event_id": r.event_id,
                        "raw_table": r.raw_table,
                        "source_file": r.source_file,
                        "raw_row_ids": [r.source_row],
                    }
                    for r in rows
                ]
            ),
            citation_count=n_events,
            assumptions=assumptions,
        )

    @app.get("/api/events/{event_id}/source")
    def source(event_id: int, conn: Conn) -> Result[SourceData]:
        ev = q.event_by_id(conn, event_id)
        if ev is None:
            return Result(status="out_of_scope", missing=f"no event with id {event_id}")
        raw = q.raw_rows(conn, ev)
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
                rows=raw,
            ),
            citations=q.citations_from_events([ev]),
            citation_count=len(raw),
            assumptions=["Raw rows are shown as loaded (text columns), with source_row."],
        )

    return app


def _utc(d: datetime | None) -> datetime | None:
    if d is None:
        return None
    return d if d.tzinfo else d.replace(tzinfo=UTC)


def _with_cites(conn, rows: list[OeeRow], brick: bool) -> list[OeeRow]:
    cites = q.shift_citations(conn, [r.key for r in rows], brick)
    for r in rows:
        r.citations, r.citation_count = cites.get(r.key, ([], 0))
    return rows


def _brick(conn, lo, hi, group: str, limit: int) -> OeeData:
    if group == "month":
        out = []
        for m in q.brick_months(conn, lo, hi):
            planned = q.f(m["planned_s"])
            ideal, total = q.f(m["ideal_qty"]), q.f(m["total_qty"])
            a_calc = _ratio_1m(m["stop_s_union"], planned)
            a_pub = _ratio_1m(m["stop_s_implied_pub"], planned)
            p = total / ideal if ideal and total is not None else None
            qual = q.f(m["good_qty"]) / total if total else None
            out.append(
                OeeRow(
                    key=m["month"],
                    start=m["start"],
                    metrics={
                        "planned_s": planned,
                        "stop_s_union": q.f(m["stop_s_union"]),
                        "availability_calc": a_calc,
                        "availability_pub": a_pub,
                        "performance_pub": p,
                        "quality_pub": qual,
                        "oee_calc_with_pub_pq": (
                            a_calc * p * qual if None not in (a_calc, p, qual) else None
                        ),
                    },
                    details={
                        "n_shifts": m["n_shifts"],
                        "n_with_published": m["n_with_published"],
                    },
                )
            )
        return OeeData(source_system="brick", group=group, rows=out, row_count=len(out))
    # Brick has one shift per date, so day and shift are the same rows.
    recs, total = q.brick_shifts(conn, lo, hi, limit)
    keys = (
        "planned_s_published stop_s_union availability_calc availability_pub availability_gap "
        "performance_pub quality_pub oee_calc_with_pub_pq oee_pub oee_gap"
    ).split()
    out = [
        OeeRow(
            key=r["shift_id"],
            start=r["shift_start"],
            metrics={k: q.f(r[k]) for k in keys},
            details={
                "period": r["period"],
                "match_status": r["match_status"],
                "shift_date": r["shift_date"].isoformat(),
            },
        )
        for r in recs
    ]
    return OeeData(
        source_system="brick",
        group=group,
        rows=_with_cites(conn, out, True),
        row_count=total,
        rows_truncated=total > len(out),
    )


def _ratio_1m(stop: Any, planned: float | None) -> float | None:
    if stop is None or not planned:
        return None
    return 1 - float(stop) / planned


PIADE_SHIFT = (
    "planned_s run_s production_s input_qty output_qty availability performance_count_p95 "
    "performance_time quality oee oee_p90 oee_p99"
).split()


def _piade(conn, machine_id: str, lo, hi, group: str, limit: int) -> OeeData:
    if group == "shift":
        recs, total = q.piade_shifts(conn, machine_id, lo, hi, limit)
        out = [
            OeeRow(
                key=r["shift_id"],
                start=r["shift_start"],
                metrics={k: q.f(r[k]) for k in PIADE_SHIFT},
                details={"quality_reason": r["quality_reason"], "n_capped": r["n_capped"]},
            )
            for r in recs
        ]
        return OeeData(
            source_system="piade",
            group=group,
            rows=_with_cites(conn, out, False),
            row_count=total,
            rows_truncated=total > len(out),
        )
    if group == "day":
        recs = q.piade_days(conn, machine_id, lo, hi)
        keys = [k for k in PIADE_SHIFT if k in recs[0]] if recs else []
    else:
        recs = q.piade_months(conn, machine_id, lo, hi)
        for r in recs:
            r["key"] = r["month"].isoformat()
        keys = [k for k in PIADE_SHIFT if recs and k in recs[0]]
    out = [
        OeeRow(
            key=r["key"],
            start=r["start"],
            metrics={k: q.f(r[k]) for k in keys},
            details={
                "n_shifts": r["n_shifts"],
                "n_shifts_counts_excluded": r["n_shifts_counts_excluded"],
            },
        )
        for r in recs
    ]
    return OeeData(source_system="piade", group=group, rows=out, row_count=len(out))
