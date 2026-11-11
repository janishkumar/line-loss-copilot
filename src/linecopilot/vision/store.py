"""Database side of the inspection stream (no torch, no onnxruntime: the API imports this).

Tables are in sql/vision_schema.sql. Everything here is idempotent where the design says so:
an inspection is unique per (subset, image_id), a review is unique per inspection, and a quality
event is unique per inspection, so a repeated `make inspect`, a double click or a retried request
never adds a second row. Quality events are SYNTHETIC: VisA is not from this plant, so each
subset gets a simulated inspection station (`synthetic.sim_asset`) and a rejected image becomes a
`VISUAL_REJECT` event on it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import psycopg

ASSET_PREFIX = "SIM-VIS-"
SYNTHETIC_NOTE = (
    "SIMULATED: the image is a real VisA photograph, but VisA is not from the PIADE or brick "
    "lines, so this station and its quality events are synthetic."
)


def asset_id_for(subset: str) -> str:
    return f"{ASSET_PREFIX}{subset}"


def asset_name_for(subset: str) -> str:
    return (
        f"SIMULATED visual-inspection station for VisA '{subset}' images "
        "(synthetic; not a plant machine)"
    )


def ensure_sim_asset(conn: psycopg.Connection, subset: str) -> str:
    asset = asset_id_for(subset)
    conn.execute(
        "INSERT INTO synthetic.sim_asset (asset_id, subset, name) VALUES (%s, %s, %s) "
        "ON CONFLICT DO NOTHING",
        (asset, subset, asset_name_for(subset)),
    )
    return asset


def insert_inspection(
    conn: psycopg.Connection,
    *,
    subset: str,
    image_id: str,
    score: float,
    decision: str,
    threshold: float,
    review_lower: float | None,
    heatmap_path: str | None,
    split: str = "test",
) -> int | None:
    """Insert one scored image; None when (subset, image_id) is already stored."""
    row = conn.execute(
        "INSERT INTO vision.inspection (subset, image_id, split, score, decision, threshold, "
        "review_lower, heatmap_path) VALUES (%s, %s, %s, %s, %s, %s, %s, %s) "
        "ON CONFLICT (subset, image_id) DO NOTHING RETURNING inspection_id",
        (subset, image_id, split, score, decision, threshold, review_lower, heatmap_path),
    ).fetchone()
    return row[0] if row else None


def bare_name(image_id: str) -> str:
    """The file name of a VisA image id. The folders hold the class (Anomaly or Normal), so
    nothing a reviewer can see carries more than this."""
    return image_id.rsplit("/", 1)[-1]


def create_quality_event(
    conn: psycopg.Connection,
    inspection_id: int,
    how: str,
) -> tuple[int, bool]:
    """The quality event of an inspection: (event_id, created). Exactly one per inspection;
    a second call returns the existing event. `how` is 'automatic' or 'reviewer <user>'."""
    sub, image, score, thr = conn.execute(
        "SELECT subset, image_id, score, threshold FROM vision.inspection WHERE inspection_id = %s",
        (inspection_id,),
    ).fetchone()
    asset = ensure_sim_asset(conn, sub)
    detail = (
        f"VisA {sub} image {bare_name(image)} rejected ({how}); anomaly score {score:.4f} against "
        f"threshold {thr:.4f}. {SYNTHETIC_NOTE}"
    )
    row = conn.execute(
        "INSERT INTO synthetic.quality_event (asset_id, inspection_id, detail) "
        "VALUES (%s, %s, %s) ON CONFLICT (inspection_id) DO NOTHING RETURNING event_id",
        (asset, inspection_id, detail),
    ).fetchone()
    if row:
        return row[0], True
    existing = conn.execute(
        "SELECT event_id FROM synthetic.quality_event WHERE inspection_id = %s", (inspection_id,)
    ).fetchone()
    return existing[0], False


ReviewStatus = Literal["recorded", "not_found", "not_queued", "already_reviewed"]


@dataclass(frozen=True)
class ReviewResult:
    status: ReviewStatus
    message: str
    review_id: int | None = None
    quality_event_id: int | None = None


def record_review(
    conn: psycopg.Connection, inspection_id: int, decision: str, reviewer: str
) -> ReviewResult:
    """Store a reviewer's decision on a queued image (one review per inspection).

    'reject' also creates the image's quality event (idempotently); 'accept' never does. The
    row is locked while this runs, so two concurrent requests cannot both record a review."""
    if decision not in ("accept", "reject"):
        raise ValueError(f"decision must be accept or reject, not {decision!r}")
    with conn.transaction():
        row = conn.execute(
            "SELECT decision, score FROM vision.inspection WHERE inspection_id = %s FOR UPDATE",
            (inspection_id,),
        ).fetchone()
        if row is None:
            return ReviewResult("not_found", f"no inspection {inspection_id}")
        queued, score = row
        if queued != "review":
            return ReviewResult(
                "not_queued",
                f"inspection {inspection_id} was decided automatically ({queued}); "
                "only images in the review queue take a reviewer decision",
            )
        made = conn.execute(
            "INSERT INTO vision.review (inspection_id, decision, reviewer, score_at_review) "
            "VALUES (%s, %s, %s, %s) ON CONFLICT (inspection_id) DO NOTHING RETURNING review_id",
            (inspection_id, decision, reviewer, score),
        ).fetchone()
        if made is None:
            return ReviewResult(
                "already_reviewed", f"inspection {inspection_id} already has a review"
            )
        event_id = None
        if decision == "reject":
            event_id, _ = create_quality_event(conn, inspection_id, f"reviewer {reviewer}")
        return ReviewResult("recorded", f"review recorded: {decision}", made[0], event_id)
