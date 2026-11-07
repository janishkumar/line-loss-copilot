"""Read-only API. Routes are thin wrappers over the tools in linecopilot.tools; every route
returns the tool's Result envelope unchanged."""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal

import httpx
import psycopg
from fastapi import Depends, FastAPI, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator

from linecopilot.chat.loop import ChatResult, run_chat
from linecopilot.chat.ollama import OllamaClient, OllamaError, OllamaUnreachable
from linecopilot.config import get_settings
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


def create_app(
    db_url: str | None = None, ollama_transport: httpx.BaseTransport | None = None
) -> FastAPI:
    app = FastAPI(title="line-loss-copilot API", version="0.1.0")
    settings = get_settings()
    url = db_url or settings.database_url

    def get_conn() -> Iterator[psycopg.Connection]:
        with psycopg.connect(url, autocommit=True) as conn:
            yield conn

    Conn = Annotated[psycopg.Connection, Depends(get_conn)]

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

    @app.post("/api/chat", response_model=ChatResult, responses={502: {}, 503: {}})
    def chat(body: ChatRequest, conn: Conn) -> ChatResult | JSONResponse:
        client = OllamaClient(settings.ollama_url, settings.chat_model, transport=ollama_transport)
        try:
            return run_chat(conn, client, [m.model_dump() for m in body.messages])
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
            client.close()

    @app.get("/api/shifts/{shift_id}/evidence")
    def shift_evidence_route(shift_id: str, conn: Conn) -> Result[ShiftEvidenceData]:
        return shift_evidence(conn, ShiftEvidenceArgs(shift_id=shift_id))

    @app.get("/api/events/{event_id}/source")
    def source(event_id: int, conn: Conn) -> Result[SourceData]:
        return event_source(conn, event_id)

    return app
