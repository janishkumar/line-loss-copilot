"""Approved-actions routes: session switcher, propose from the web form, inbox, decisions, audit.

Identity comes only from the `lc_session` cookie (a random token; only its sha256 is stored in
actions.web_session). No body or query field can name the acting user: bodies forbid extra
fields. The agent role has no route here: approve, reject, close, release and complete require a
human session, and `copilot-agent` can never hold one.

HTTP mapping of service outcomes:
  refused  -> 403 (bad code, wrong identity, not pending, role may not do this) with the Outcome
  blocked  -> 409 (a re-check blocks) with the Outcome, except a blocked decision whose blocking
              check is segregation_of_duties or role_may_approve: that is an identity rule, 403
  invalid arguments -> 422 with the Outcome (propose) or the blocked Preview (preview); the
              service still audits the attempt
  no or forged session -> 401; success -> 200
Malformed request bodies get FastAPI's normal 422.

Cookie: HttpOnly, SameSite=Strict, Path=/. It is not Secure because the demo runs on plain
http://localhost; behind TLS this must be set. SameSite=Strict plus the Origin check below are
the CSRF defence."""

import hashlib
import secrets
from collections.abc import Iterator
from dataclasses import asdict
from typing import Annotated, Any

import psycopg
from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from linecopilot.actions import args as argmod
from linecopilot.actions.identity import AGENT, ActionContext, get_user
from linecopilot.actions.service import ActionService, Outcome, Preview

COOKIE = "lc_session"
IDENTITY_CHECKS = {"segregation_of_duties", "role_may_approve"}
KINDS = {"work_orders": "work_order", "quality_holds": "quality_hold", "follow_ups": "follow_up"}


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def session_user_id(conn: psycopg.Connection, token: str | None) -> str | None:
    """The user a session token belongs to, or None. Never the agent."""
    if not token:
        return None
    row = conn.execute(
        "SELECT s.user_id FROM actions.web_session s JOIN demo.app_user u USING (user_id) "
        "WHERE s.token_sha256 = %s AND u.role <> 'agent' AND u.user_id <> %s",
        (token_hash(token), AGENT),
    ).fetchone()
    return row[0] if row else None


class SessionBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_id: str


class ProposeBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    args: dict[str, Any]
    code: str | None = None


class DecisionBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    note: str = ""


def _outcome_response(out: Outcome, status: int | None = None) -> JSONResponse:
    if status is None:
        status = 200
        if out.outcome == "refused":
            status = 403
        elif out.outcome == "blocked":
            identity = any(c.level == "block" and c.name in IDENTITY_CHECKS for c in out.checks)
            status = 403 if identity else 409
    return JSONResponse(jsonable_encoder(asdict(out)), status_code=status)


def make_router(
    db_url: str, agent_db_url: str, service: ActionService, allowed_origins: set[str]
) -> APIRouter:
    # agent_db_url is for agent-channel front ends (chat, wired separately); web-form actions
    # are a human acting and use the main role.
    router = APIRouter()
    router.agent_db_url = agent_db_url  # type: ignore[attr-defined]

    def writable() -> Iterator[psycopg.Connection]:
        with psycopg.connect(db_url, autocommit=True) as conn:
            yield conn

    Conn = Annotated[psycopg.Connection, Depends(writable)]

    def origin_guard(request: Request) -> None:
        origin = request.headers.get("origin")
        if origin is not None and origin not in allowed_origins:
            raise HTTPException(403, f"origin {origin} is not allowed")

    Guard = Depends(origin_guard)

    def current_user(conn: Conn, lc_session: Annotated[str | None, Cookie()] = None) -> str:
        user = session_user_id(conn, lc_session)
        if user is None:
            raise HTTPException(401, "sign in first (no valid session)")
        return user

    User = Annotated[str, Depends(current_user)]

    # --- session switcher -------------------------------------------------------------------

    @router.get("/api/users")
    def users(conn: Conn) -> list[dict]:
        rows = conn.execute(
            "SELECT user_id, display_name, role, source FROM demo.app_user "
            "WHERE role <> 'agent' AND user_id <> %s ORDER BY user_id",
            (AGENT,),
        ).fetchall()
        return [{"user_id": r[0], "display_name": r[1], "role": r[2], "source": r[3]} for r in rows]

    @router.post("/api/session", dependencies=[Guard])
    def start_session(body: SessionBody, conn: Conn, response: Response) -> dict:
        user = get_user(conn, body.user_id)
        if user is None or user.role == "agent" or user.user_id == AGENT:
            raise HTTPException(400, "unknown user or not a person")
        token = secrets.token_urlsafe(32)
        conn.execute(
            "INSERT INTO actions.web_session (token_sha256, user_id) VALUES (%s, %s)",
            (token_hash(token), user.user_id),
        )
        response.set_cookie(COOKIE, token, httponly=True, samesite="strict", path="/", secure=False)
        return {"user": asdict(user)}

    @router.get("/api/session")
    def get_session(conn: Conn, lc_session: Annotated[str | None, Cookie()] = None) -> dict:
        uid = session_user_id(conn, lc_session)
        user = get_user(conn, uid) if uid else None
        return {"user": asdict(user) if user else None}

    @router.delete("/api/session", dependencies=[Guard])
    def end_session(
        conn: Conn, response: Response, lc_session: Annotated[str | None, Cookie()] = None
    ) -> dict:
        if lc_session:
            conn.execute(
                "DELETE FROM actions.web_session WHERE token_sha256 = %s",
                (token_hash(lc_session),),
            )
        response.delete_cookie(COOKIE, path="/")
        return {"user": None}

    # --- preview and propose (a person acting through the form) -----------------------------

    def form_ctx(user: str) -> ActionContext:
        return ActionContext(principal=user, on_behalf_of=user, channel="web_form")

    def known(action: str) -> None:
        if action not in argmod.ACTION_ARGS:
            raise HTTPException(404, f"unknown action: {action}")

    @router.post("/api/actions/{action}/preview", dependencies=[Guard])
    def preview(action: str, raw: dict[str, Any], conn: Conn, user: User) -> JSONResponse:
        known(action)
        pv: Preview = service.preview(conn, form_ctx(user), action, raw)
        invalid = any(c.name == "valid_arguments" and c.level == "block" for c in pv.checks)
        return JSONResponse(jsonable_encoder(asdict(pv)), status_code=422 if invalid else 200)

    @router.post("/api/actions/{action}/propose", dependencies=[Guard])
    def propose(action: str, body: ProposeBody, conn: Conn, user: User) -> JSONResponse:
        known(action)
        out = service.propose(conn, form_ctx(user), action, body.args, body.code)
        invalid = out.outcome == "refused" and out.message.startswith("arguments refused")
        return _outcome_response(out, 422 if invalid else None)

    # --- inbox ------------------------------------------------------------------------------

    @router.get("/api/proposals")
    def proposals(conn: Conn, status: str | None = None) -> Any:
        return jsonable_encoder(service.list_proposals(conn, status))

    @router.get("/api/proposals/{proposal_id}")
    def proposal(proposal_id: int, conn: Conn) -> Any:
        row = service.get_proposal(conn, proposal_id)
        if row is None:
            raise HTTPException(404, "no such proposal")
        return jsonable_encoder(row)

    @router.post("/api/proposals/{proposal_id}/approve", dependencies=[Guard])
    def approve(
        proposal_id: int, conn: Conn, user: User, body: DecisionBody | None = None
    ) -> JSONResponse:
        note = body.note if body else ""
        return _outcome_response(service.approve(conn, user, proposal_id, note))

    @router.post("/api/proposals/{proposal_id}/reject", dependencies=[Guard])
    def reject(
        proposal_id: int, conn: Conn, user: User, body: DecisionBody | None = None
    ) -> JSONResponse:
        note = body.note if body else ""
        return _outcome_response(service.reject(conn, user, proposal_id, note))

    # --- approved actions and their status changes -----------------------------------------

    @router.get("/api/actions/{kind}")
    def list_actions(kind: str, conn: Conn) -> Any:
        if kind not in KINDS:
            raise HTTPException(404, f"unknown kind: {kind}")
        return jsonable_encoder(service.list_actions(conn, KINDS[kind]))

    @router.post("/api/actions/work_orders/{row_id}/close", dependencies=[Guard])
    def close(row_id: int, conn: Conn, user: User) -> JSONResponse:
        return _outcome_response(service.close_work_order(conn, user, row_id))

    @router.post("/api/actions/quality_holds/{row_id}/release", dependencies=[Guard])
    def release(row_id: int, conn: Conn, user: User) -> JSONResponse:
        return _outcome_response(service.release_hold(conn, user, row_id))

    @router.post("/api/actions/follow_ups/{row_id}/complete", dependencies=[Guard])
    def complete(row_id: int, conn: Conn, user: User) -> JSONResponse:
        return _outcome_response(service.complete_follow_up(conn, user, row_id))

    @router.get("/api/audit")
    def audit_log(conn: Conn, proposal_id: int | None = None, limit: int = 200) -> Any:
        rows = service.list_audit(conn, limit=min(max(limit, 1), 1000), proposal_id=proposal_id)
        return jsonable_encoder(rows)

    return router
