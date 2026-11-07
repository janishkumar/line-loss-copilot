"""Result envelope shared by the API and (in stage 2) the copilot tools (design 6.1)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

Status = Literal["ok", "insufficient_evidence", "out_of_scope"]
CITATION_CAP = 50


class Citation(BaseModel):
    """Points at one raw row: (raw_table, source_file, raw_row_id) per ruling R15."""

    raw_table: str
    source_file: str
    raw_row_id: int = Field(description="1-based line in source_file (source_row)")
    event_id: int | None = None
    field: str | None = None


class Window(BaseModel):
    start: datetime | None = None
    end: datetime | None = Field(default=None, description="exclusive")
    line_id: str | None = None
    machine_id: str | None = None
    group: str | None = None


class Result[T](BaseModel):
    status: Status
    data: T | None = None
    citations: list[Citation] = Field(default_factory=list)
    citation_count: int = 0
    window: Window | None = None
    assumptions: list[str] = Field(default_factory=list)
    missing: str | None = None


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


class OeeRow(BaseModel):
    """One group (shift, day or month). `metrics` holds the numbers, `details` labels."""

    key: str = Field(description="shift_id, or the day / month start for coarser groups")
    start: datetime | None = None
    metrics: dict[str, float | None]
    details: dict[str, str | int | None] = Field(default_factory=dict)
    citations: list[Citation] = Field(default_factory=list)
    citation_count: int = 0


class OeeData(BaseModel):
    source_system: str
    group: str
    rows: list[OeeRow]
    row_count: int
    rows_truncated: bool = False


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
