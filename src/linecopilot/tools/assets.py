"""list_assets: the lines and machines loaded, with their coverage."""

from __future__ import annotations

from datetime import datetime

import psycopg
from pydantic import BaseModel, ConfigDict

from linecopilot.tools.common import line_rows, machine_rows
from linecopilot.tools.envelope import Result


class ListAssetsArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MachineInfo(BaseModel):
    machine_id: str
    line_id: str
    source_system: str
    first_ts: datetime
    last_ts: datetime
    event_count: int


class LineInfo(BaseModel):
    line_id: str
    source_system: str
    source_timezone: str
    first_ts: datetime
    last_ts: datetime
    event_count: int
    machines: list[str]


class AssetsData(BaseModel):
    lines: list[LineInfo]
    machines: list[MachineInfo]


def list_assets(conn: psycopg.Connection, args: ListAssetsArgs) -> Result[AssetsData]:
    return Result(
        status="ok",
        data=AssetsData(
            lines=[LineInfo(**r) for r in line_rows(conn)],
            machines=[MachineInfo(**r) for r in machine_rows(conn)],
        ),
        assumptions=[
            "Coverage is from first to last event start/end per asset; machines have "
            "different date ranges and gaps inside a range are not filled.",
            "Every line and machine listed here is real data; none is synthetic.",
        ],
    )
