"""Visual-inspection read tools (stage 5): the review queue, one inspection, and the simulated
quality events (`quality_events`, the registered tool).

The images are real (VisA) but their link to a production line is simulated: the stations
(`SIM-VIS-<subset>`) and the quality events rejected images create are SYNTHETIC. Every result
says so in `assumptions` and in `is_synthetic`, and none of them carries source-row citations
(there are no source rows behind synthetic data). Free text (a quality event's detail) is data.
Nothing here loads PyTorch or the models: it reads Postgres and checks heatmap files exist. A
missing table, an empty stream or a missing file is an `insufficient_evidence` envelope.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Literal

import psycopg
from pydantic import BaseModel, ConfigDict, Field

from linecopilot.config import get_settings
from linecopilot.tools.common import f, rows
from linecopilot.tools.envelope import Result
from linecopilot.vision.store import SYNTHETIC_NOTE

Decision = Literal["pass", "review", "reject"]
MAX_ROWS = 200
NO_STREAM = (
    "no inspections are stored: run `make data-visa`, `make train-vision`, then `make inspect`"
)
ASSUMPTIONS = [
    "The images are real VisA photographs; the inspection stream, the inspection stations "
    "(SIM-VIS-<subset>) and the quality events are SIMULATED and synthetic, because VisA is "
    "not from the PIADE or brick lines.",
    "Decisions use the per-subset cost threshold and review band chosen on validation images "
    "(data/models/vision/thresholds.json); the images are from the held-out test split.",
    "A quality event's detail is free text from this system, returned as data.",
]


def heatmap_dir() -> Path:
    return (get_settings().data_dir / "vision" / "heatmaps").resolve()


def heatmap_file(path: str | None) -> Path | None:
    """The stored heatmap as a file under data/vision/heatmaps/, or None if there is none, it is
    outside that folder, or it is missing. The path comes from the database, never a client."""
    if not path:
        return None
    root = heatmap_dir()
    target = (root / path).resolve()
    if not target.is_relative_to(root) or not target.is_file():
        return None
    return target


def _exists(conn: psycopg.Connection, name: str) -> bool:
    return bool(conn.execute("SELECT to_regclass(%s) IS NOT NULL", (name,)).fetchone()[0])


class ReviewOut(BaseModel):
    decision: str
    reviewer: str
    score_at_review: float
    created_at: datetime


class InspectionOut(BaseModel):
    inspection_id: int
    subset: str
    image_id: str
    split: str
    score: float
    decision: Decision
    threshold: float
    review_lower: float | None
    created_at: datetime
    source: str
    asset_id: str
    heatmap_url: str | None = Field(description="null when no heatmap file is available")
    review: ReviewOut | None
    quality_event_id: int | None
    is_synthetic: bool = True


class InspectionsData(BaseModel):
    label: str = "real VisA images, simulated stream"
    is_synthetic: bool = True
    counts: dict[str, int] = Field(description="inspections per decision, over the whole stream")
    total: int = Field(description="inspections matching the filter (rows is paged)")
    pending_review: int = Field(description="queued images with no reviewer decision yet")
    rows: list[InspectionOut]
    limit: int
    offset: int


class ListInspectionsArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Decision | None = None
    subset: str | None = Field(default=None, max_length=40)
    unreviewed: bool = Field(default=False, description="only queued images with no review yet")
    limit: int = Field(default=50, ge=1, le=MAX_ROWS)
    offset: int = Field(default=0, ge=0)


_SELECT = """
SELECT i.inspection_id, i.subset, i.image_id, i.split, i.score, i.decision, i.threshold,
       i.review_lower, i.created_at, i.source, i.heatmap_path,
       r.decision AS r_decision, r.reviewer AS r_reviewer, r.score_at_review AS r_score,
       r.created_at AS r_at, q.event_id AS quality_event_id
FROM vision.inspection i
LEFT JOIN vision.review r USING (inspection_id)
LEFT JOIN synthetic.quality_event q USING (inspection_id)
"""


def _row_out(rec: dict[str, Any]) -> InspectionOut:
    review = None
    if rec["r_decision"] is not None:
        review = ReviewOut(
            decision=rec["r_decision"],
            reviewer=rec["r_reviewer"],
            score_at_review=float(rec["r_score"]),
            created_at=rec["r_at"],
        )
    has_map = heatmap_file(rec["heatmap_path"]) is not None
    return InspectionOut(
        inspection_id=rec["inspection_id"],
        subset=rec["subset"],
        image_id=rec["image_id"],
        split=rec["split"],
        score=float(rec["score"]),
        decision=rec["decision"],
        threshold=float(rec["threshold"]),
        review_lower=f(rec["review_lower"]),
        created_at=rec["created_at"],
        source=rec["source"],
        asset_id=f"SIM-VIS-{rec['subset']}",
        heatmap_url=f"/api/inspections/{rec['inspection_id']}/heatmap" if has_map else None,
        review=review,
        quality_event_id=rec["quality_event_id"],
    )


def _stream_missing(conn: psycopg.Connection) -> bool:
    return not (
        _exists(conn, "vision.inspection")
        and _exists(conn, "vision.review")
        and _exists(conn, "synthetic.quality_event")
    )


def list_inspections(
    conn: psycopg.Connection, args: ListInspectionsArgs
) -> Result[InspectionsData]:
    if _stream_missing(conn):
        return Result(status="insufficient_evidence", assumptions=ASSUMPTIONS, missing=NO_STREAM)
    counts = {d: 0 for d in ("pass", "review", "reject")}
    for d, n in conn.execute("SELECT decision, count(*) FROM vision.inspection GROUP BY 1"):
        counts[d] = n
    if not sum(counts.values()):
        return Result(status="insufficient_evidence", assumptions=ASSUMPTIONS, missing=NO_STREAM)
    p = {
        "d": args.decision,
        "s": args.subset,
        "u": args.unreviewed,
        "lim": args.limit,
        "off": args.offset,
    }
    where = (
        "WHERE (%(d)s::text IS NULL OR i.decision = %(d)s) "
        "AND (%(s)s::text IS NULL OR i.subset = %(s)s) "
        "AND (NOT %(u)s OR (i.decision = 'review' AND r.review_id IS NULL))"
    )
    total = conn.execute(
        "SELECT count(*) FROM vision.inspection i LEFT JOIN vision.review r USING "
        f"(inspection_id) {where}",
        p,
    ).fetchone()[0]
    (pending,) = conn.execute(
        "SELECT count(*) FROM vision.inspection i LEFT JOIN vision.review r USING "
        "(inspection_id) WHERE i.decision = 'review' AND r.review_id IS NULL"
    ).fetchone()
    recs = rows(
        conn,
        f"{_SELECT} {where} ORDER BY i.inspection_id LIMIT %(lim)s OFFSET %(off)s",
        p,
    )
    return Result(
        status="ok",
        data=InspectionsData(
            counts=counts,
            total=total,
            pending_review=pending,
            rows=[_row_out(r) for r in recs],
            limit=args.limit,
            offset=args.offset,
        ),
        assumptions=ASSUMPTIONS,
    )


def get_inspection(conn: psycopg.Connection, inspection_id: int) -> Result[InspectionOut]:
    if _stream_missing(conn):
        return Result(status="insufficient_evidence", assumptions=ASSUMPTIONS, missing=NO_STREAM)
    recs = rows(conn, f"{_SELECT} WHERE i.inspection_id = %s", (inspection_id,))
    if not recs:
        return Result(
            status="insufficient_evidence",
            assumptions=ASSUMPTIONS,
            missing=f"no inspection {inspection_id}",
        )
    return Result(status="ok", data=_row_out(recs[0]), assumptions=ASSUMPTIONS)


# --- the registered tool -----------------------------------------------------------------------


class QualityEventsArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asset_id: str | None = Field(
        default=None,
        max_length=40,
        description="a simulated inspection station, for example SIM-VIS-cashew; omit for all",
    )
    start: datetime | None = Field(default=None, description="only events at or after this time")
    end: datetime | None = Field(default=None, description="only events before this time")
    limit: int = Field(default=50, ge=1, le=MAX_ROWS)
    offset: int = Field(default=0, ge=0)


class QualityEventOut(BaseModel):
    event_id: int = Field(description="usable as evidence_event_ids in a quality hold")
    event_key: str
    asset_id: str
    subset: str
    start_ts: datetime
    reason_code: str
    detail: str = Field(description="free text, data only")
    inspection_id: int | None
    score: float | None
    threshold: float | None
    path: str = Field(description="automatic reject, or rejected by a named reviewer")
    reviewer: str | None
    image_id: str | None
    heatmap_url: str | None
    is_synthetic: bool = True


class QualityEventsData(BaseModel):
    label: str = "simulated quality events from real VisA images"
    is_synthetic: bool = True
    notice: str = SYNTHETIC_NOTE
    total: int
    rows: list[QualityEventOut]
    limit: int
    offset: int


def quality_events(conn: psycopg.Connection, args: QualityEventsArgs) -> Result[QualityEventsData]:
    if not (
        _exists(conn, "core.event_all")
        and _exists(conn, "synthetic.quality_event")
        and _exists(conn, "vision.inspection")
    ):
        return Result(status="insufficient_evidence", assumptions=ASSUMPTIONS, missing=NO_STREAM)
    p = {"a": args.asset_id, "s": args.start, "e": args.end, "lim": args.limit, "off": args.offset}
    where = (
        "WHERE e.event_type = 'quality' AND e.is_synthetic "
        "AND (%(a)s::text IS NULL OR e.line_id = %(a)s) "
        "AND (%(s)s::timestamptz IS NULL OR e.start_ts >= %(s)s) "
        "AND (%(e)s::timestamptz IS NULL OR e.start_ts < %(e)s)"
    )
    (total,) = conn.execute(f"SELECT count(*) FROM core.event_all e {where}", p).fetchone()
    if not total:
        return Result(
            status="insufficient_evidence",
            assumptions=ASSUMPTIONS,
            missing="no simulated quality events match; reject an image (`make inspect` or a "
            "reviewer decision) to create one",
        )
    recs = rows(
        conn,
        f"""SELECT e.event_id, e.event_key, e.line_id AS asset_id, e.product AS subset,
                   e.start_ts, e.reason_code, e.reason_text AS detail, q.inspection_id,
                   i.score, i.threshold, i.image_id, i.heatmap_path, r.reviewer
            FROM core.event_all e
            LEFT JOIN synthetic.quality_event q ON q.event_id = e.event_id
            LEFT JOIN vision.inspection i ON i.inspection_id = q.inspection_id
            LEFT JOIN vision.review r ON r.inspection_id = q.inspection_id
            {where} ORDER BY e.start_ts, e.event_id LIMIT %(lim)s OFFSET %(off)s""",
        p,
    )
    out = [
        QualityEventOut(
            event_id=r["event_id"],
            event_key=r["event_key"],
            asset_id=r["asset_id"],
            subset=r["subset"],
            start_ts=r["start_ts"],
            reason_code=r["reason_code"],
            detail=r["detail"],
            inspection_id=r["inspection_id"],
            score=f(r["score"]),
            threshold=f(r["threshold"]),
            path=f"rejected by reviewer {r['reviewer']}" if r["reviewer"] else "automatic reject",
            reviewer=r["reviewer"],
            image_id=r["image_id"],
            heatmap_url=(
                f"/api/inspections/{r['inspection_id']}/heatmap"
                if heatmap_file(r["heatmap_path"])
                else None
            ),
        )
        for r in recs
    ]
    return Result(
        status="ok",
        data=QualityEventsData(total=total, rows=out, limit=args.limit, offset=args.offset),
        assumptions=ASSUMPTIONS,
    )
