"""Read-only API. Routes are thin wrappers over the tools in linecopilot.tools; every route
returns the tool's Result envelope unchanged. Invalid query arguments on a tool route also get
the envelope (out_of_scope, HTTP 200), as the MCP server and the chat loop answer them.
Database sessions are read-only."""

import threading
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal

import httpx
import psycopg
from fastapi import Cookie, Depends, FastAPI, HTTPException, Query, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator

from linecopilot.actions.identity import AGENT, ActionContext
from linecopilot.actions.policy import load_policy
from linecopilot.actions.service import ActionService
from linecopilot.api.actions_routes import make_router, session_user_id
from linecopilot.chat.loop import ChatResult, run_chat
from linecopilot.chat.ollama import OllamaClient, OllamaError, OllamaUnreachable
from linecopilot.config import get_settings
from linecopilot.db import connect_read_only
from linecopilot.reports.oee_validation import validate_oee
from linecopilot.tools.assets import AssetsData, ListAssetsArgs, list_assets
from linecopilot.tools.envelope import Result, Window
from linecopilot.tools.events import EventsData, GetEventsArgs, get_events
from linecopilot.tools.evidence import (
    ShiftEvidenceArgs,
    ShiftEvidenceData,
    SourceData,
    event_source,
    shift_evidence,
)
from linecopilot.tools.losses import (
    BreakdownArgs,
    BreakdownData,
    LossParetoArgs,
    ParetoData,
    RepeatArgs,
    RepeatData,
    breakdown,
    loss_pareto,
    repeat_failures,
)
from linecopilot.tools.notes import NotesData, SearchNotesArgs, search_notes
from linecopilot.tools.oee import MAX_ROWS, GetOeeArgs, GroupBy, OeeData, get_oee
from linecopilot.tools.registry import format_errors
from linecopilot.tools.reliability import (
    CompareArgs,
    CompareData,
    ReliabilityArgs,
    ReliabilityData,
    compare_periods,
    reliability,
)
from linecopilot.tools.risk import (
    RiskData,
    RiskMetricsData,
    StopRiskArgs,
    risk_metrics,
    stop_risk,
)

CHAT_MAX_MESSAGES = 20
CHAT_MAX_CHARS = 4000
# One chat request can hold a worker and a database connection for minutes while the local
# model runs; more than this many at once get a 429 envelope.
CHAT_MAX_CONCURRENT = 2


class ChatMessage(BaseModel):
    """A user or assistant turn. There is no system role: the system prompt is the server's."""

    model_config = ConfigDict(extra="forbid")

    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=CHAT_MAX_CHARS)


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    messages: list[ChatMessage] = Field(min_length=1, max_length=CHAT_MAX_MESSAGES)

    @field_validator("messages")
    @classmethod
    def ends_with_user(cls, v: list[ChatMessage]) -> list[ChatMessage]:
        if v[-1].role != "user":
            raise ValueError("the last message must be from the user")
        return v


# Action routes keep FastAPI's normal 422 for malformed bodies; every other /api route answers
# invalid arguments with the out_of_scope envelope.
NORMAL_422_PREFIXES = ("/api/chat", "/api/session", "/api/actions", "/api/proposals", "/api/audit")


def create_app(
    db_url: str | None = None,
    ollama_transport: httpx.BaseTransport | None = None,
    agent_db_url: str | None = None,
) -> FastAPI:
    app = FastAPI(title="line-loss-copilot API", version="0.1.0")
    settings = get_settings()
    url = db_url or settings.database_url

    def get_conn() -> Iterator[psycopg.Connection]:
        with connect_read_only(url) as conn:
            yield conn

    Conn = Annotated[psycopg.Connection, Depends(get_conn)]
    origins = {o.strip() for o in settings.web_origins.split(",") if o.strip()}
    agent_url = agent_db_url or settings.agent_database_url
    action_service = ActionService(load_policy(settings.policy_path))
    app.include_router(make_router(url, agent_url, action_service, origins))
    chat_slots = threading.BoundedSemaphore(CHAT_MAX_CONCURRENT)

    @app.exception_handler(RequestValidationError)
    async def invalid_args(request: Request, exc: RequestValidationError) -> JSONResponse:
        path = request.url.path
        if not path.startswith("/api/") or path.startswith(NORMAL_422_PREFIXES):
            return await request_validation_exception_handler(request, exc)
        res = Result(
            status="out_of_scope",
            missing=f"invalid arguments for {path}: {format_errors(exc.errors())}",
        )
        return JSONResponse(res.model_dump(mode="json"), status_code=200)

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/assets")
    def assets(conn: Conn) -> Result[AssetsData]:
        return list_assets(conn, ListAssetsArgs())

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
        return get_oee(
            conn,
            GetOeeArgs(
                line_id=line_id,
                machine_id=machine_id,
                start=start,
                end=end,
                group=group,
                limit=limit,
            ),
        )

    @app.get("/api/losses/pareto")
    def pareto(conn: Conn, args: Annotated[LossParetoArgs, Query()]) -> Result[ParetoData]:
        return loss_pareto(conn, args)

    @app.get("/api/losses/breakdown")
    def breakdown_route(
        conn: Conn, args: Annotated[BreakdownArgs, Query()]
    ) -> Result[BreakdownData]:
        return breakdown(conn, args)

    @app.get("/api/losses/repeats")
    def repeats(conn: Conn, args: Annotated[RepeatArgs, Query()]) -> Result[RepeatData]:
        return repeat_failures(conn, args)

    @app.get("/api/reliability")
    def reliability_route(
        conn: Conn, args: Annotated[ReliabilityArgs, Query()]
    ) -> Result[ReliabilityData]:
        return reliability(conn, args)

    @app.get("/api/compare")
    def compare_route(conn: Conn, args: Annotated[CompareArgs, Query()]) -> Result[CompareData]:
        return compare_periods(conn, args)

    @app.get("/api/events")
    def events_route(conn: Conn, args: Annotated[GetEventsArgs, Query()]) -> Result[EventsData]:
        return get_events(conn, args)

    @app.get("/api/notes/search")
    def notes_search(conn: Conn, args: Annotated[SearchNotesArgs, Query()]) -> Result[NotesData]:
        return search_notes(conn, args)

    @app.get("/api/risk")
    def risk_route(conn: Conn, args: Annotated[StopRiskArgs, Query()]) -> Result[RiskData]:
        return stop_risk(conn, args)

    @app.get("/api/risk/metrics")
    def risk_metrics_route(conn: Conn) -> Result[RiskMetricsData]:
        return risk_metrics(conn)

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

    def chat_origin_guard(request: Request) -> None:
        # the chat can now create proposals, so it gets the same Origin check as the action routes
        origin = request.headers.get("origin")
        if origin is not None and origin not in origins:
            raise HTTPException(403, f"origin {origin} is not allowed")

    @app.post(
        "/api/chat",
        response_model=ChatResult,
        responses={429: {}, 502: {}, 503: {}},
        dependencies=[Depends(chat_origin_guard)],
    )
    def chat(
        body: ChatRequest, conn: Conn, lc_session: Annotated[str | None, Cookie()] = None
    ) -> ChatResult | JSONResponse:
        if not chat_slots.acquire(blocking=False):
            busy = Result(
                status="out_of_scope",
                missing=f"the chat is busy ({CHAT_MAX_CONCURRENT} requests already running); "
                "try again shortly",
            )
            return JSONResponse(busy.model_dump(mode="json"), status_code=429)
        client: OllamaClient | None = None
        try:
            client = OllamaClient(
                settings.ollama_url, settings.chat_model, transport=ollama_transport
            )
            user = session_user_id(conn, lc_session)
            action_ctx = (
                ActionContext(principal=AGENT, on_behalf_of=user, channel="web_chat")
                if user
                else None
            )
            return run_chat(
                conn,
                client,
                [m.model_dump() for m in body.messages],
                action_ctx=action_ctx,
                agent_conn_factory=lambda: psycopg.connect(agent_url, autocommit=True),
                action_service=action_service,
            )
        except OllamaUnreachable as e:
            return JSONResponse(
                Result(status="out_of_scope", missing=str(e)).model_dump(mode="json"),
                status_code=503,
            )
        except OllamaError as e:
            return JSONResponse(
                Result(status="out_of_scope", missing=str(e)).model_dump(mode="json"),
                status_code=502,
            )
        finally:
            if client is not None:
                client.close()
            chat_slots.release()

    @app.get("/api/shifts/{shift_id}/evidence")
    def shift_evidence_route(shift_id: str, conn: Conn) -> Result[ShiftEvidenceData]:
        return shift_evidence(conn, ShiftEvidenceArgs(shift_id=shift_id))

    @app.get("/api/events/{event_id}/source")
    def source(event_id: int, conn: Conn) -> Result[SourceData]:
        return event_source(conn, event_id)

    return app
