"""Inspection routes: the review queue, one inspection, its heatmap, and the reviewer decision.

Reads use read-only sessions and answer with the Result envelope. The decision route is the one
write: it needs a human session (`lc_session`, the demo user switcher), passes the same Origin
check as the action routes, and takes the reviewer from the session, never from the body (the
body forbids extra fields). One review per inspection; a second one is a 409 with the envelope.
A reviewer 'reject' creates exactly one simulated (synthetic) quality event; 'accept' creates
none. The heatmap route serves only the file stored for that inspection under
data/vision/heatmaps/, never a client-supplied path. Nothing here imports PyTorch.
"""

from collections.abc import Iterator
from typing import Annotated, Literal

import psycopg
from fastapi import APIRouter, Cookie, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict

from linecopilot.api.actions_routes import session_user_id
from linecopilot.db import connect_read_only
from linecopilot.tools.envelope import Result
from linecopilot.tools.inspection import (
    ASSUMPTIONS,
    InspectionOut,
    InspectionsData,
    ListInspectionsArgs,
    get_inspection,
    heatmap_file,
    list_inspections,
)
from linecopilot.vision import store


class ReviewBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: Literal["accept", "reject"]


class ReviewData(BaseModel):
    inspection: InspectionOut
    review_id: int
    quality_event_id: int | None
    is_synthetic: bool = True


def _envelope(res: Result, status: int) -> JSONResponse:
    return JSONResponse(res.model_dump(mode="json"), status_code=status)


def make_router(db_url: str, allowed_origins: set[str]) -> APIRouter:
    router = APIRouter()

    def reader() -> Iterator[psycopg.Connection]:
        with connect_read_only(db_url) as conn:
            yield conn

    def writer() -> Iterator[psycopg.Connection]:
        with psycopg.connect(db_url, autocommit=True) as conn:
            yield conn

    Read = Annotated[psycopg.Connection, Depends(reader)]
    Write = Annotated[psycopg.Connection, Depends(writer)]

    def origin_guard(request: Request) -> None:
        origin = request.headers.get("origin")
        if origin is not None and origin not in allowed_origins:
            raise HTTPException(403, f"origin {origin} is not allowed")

    @router.get("/api/inspections")
    def inspections(
        conn: Read, args: Annotated[ListInspectionsArgs, Query()]
    ) -> Result[InspectionsData]:
        return list_inspections(conn, args)

    @router.get("/api/inspections/{inspection_id}", response_model=None)
    def inspection(inspection_id: int, conn: Read) -> Result[InspectionOut] | JSONResponse:
        res = get_inspection(conn, inspection_id)
        return res if res.status == "ok" else _envelope(res, 404)

    @router.get("/api/inspections/{inspection_id}/heatmap", response_model=None)
    def heatmap(inspection_id: int, conn: Read) -> FileResponse | JSONResponse:
        row = (
            conn.execute(
                "SELECT heatmap_path FROM vision.inspection WHERE inspection_id = %s",
                (inspection_id,),
            ).fetchone()
            if _has_table(conn)
            else None
        )
        path = heatmap_file(row[0]) if row else None
        if path is None:
            res = Result(
                status="insufficient_evidence",
                assumptions=ASSUMPTIONS,
                missing=f"no heatmap file for inspection {inspection_id}"
                + ("" if row else " (no such inspection)"),
            )
            return _envelope(res, 404)
        return FileResponse(path, media_type="image/png")

    @router.post(
        "/api/inspections/{inspection_id}/review",
        dependencies=[Depends(origin_guard)],
        response_model=None,
    )
    def review(
        inspection_id: int,
        body: ReviewBody,
        conn: Write,
        lc_session: Annotated[str | None, Cookie()] = None,
    ) -> Result[ReviewData] | JSONResponse:
        reviewer = session_user_id(conn, lc_session)
        if reviewer is None:
            raise HTTPException(401, "sign in first (no valid session)")
        if not _has_table(conn):
            return _envelope(
                Result(
                    status="insufficient_evidence", assumptions=ASSUMPTIONS, missing="no stream"
                ),
                404,
            )
        out = store.record_review(conn, inspection_id, body.decision, reviewer)
        if out.status != "recorded":
            code = 404 if out.status == "not_found" else 409
            return _envelope(Result(status="out_of_scope", missing=out.message), code)
        insp = get_inspection(conn, inspection_id)
        return Result(
            status="ok",
            data=ReviewData(
                inspection=insp.data,
                review_id=out.review_id,
                quality_event_id=out.quality_event_id,
            ),
            assumptions=ASSUMPTIONS,
        )

    return router


def _has_table(conn: psycopg.Connection) -> bool:
    return bool(
        conn.execute(
            "SELECT to_regclass('vision.inspection') IS NOT NULL "
            "AND to_regclass('vision.review') IS NOT NULL "
            "AND to_regclass('synthetic.quality_event') IS NOT NULL"
        ).fetchone()[0]
    )
