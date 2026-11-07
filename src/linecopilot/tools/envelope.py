"""Result envelope returned by every tool and API route (design 6.1)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Status = Literal["ok", "insufficient_evidence", "out_of_scope"]
CITATION_CAP = 50


class Citation(BaseModel):
    """Points at one raw row: (raw_table, source_file, raw_row_id) per ruling R15."""

    raw_table: str
    source_file: str
    raw_row_id: int = Field(description="1-based line in source_file (source_row)")
    event_id: int | None = None
    field: str | None = None


class CitationRef(BaseModel):
    """A citation's identity, as given back to a tool to fetch the row it points at."""

    model_config = ConfigDict(extra="forbid")

    raw_table: str
    source_file: str
    raw_row_id: int


class Window(BaseModel):
    start: datetime | None = None
    end: datetime | None = Field(default=None, description="exclusive")
    line_id: str | None = None
    machine_id: str | None = None
    group: str | None = None


class Result[T](BaseModel):
    status: Status
    data: T | None = None
    citations: list[Citation] = Field(
        default_factory=list, description=f"at most {CITATION_CAP} of the cited raw rows"
    )
    citation_count: int = Field(
        default=0, description="distinct raw rows behind the result (citations is capped)"
    )
    window: Window | None = None
    assumptions: list[str] = Field(default_factory=list)
    missing: str | None = None


def cap_citations(cites: list[Citation]) -> tuple[list[Citation], int]:
    """Dedupe on (raw_table, source_file, raw_row_id) keeping the first, then cap at
    CITATION_CAP. Returns the capped list and the number of distinct citations."""
    seen: set[tuple[str, str, int]] = set()
    out: list[Citation] = []
    for c in cites:
        k = (c.raw_table, c.source_file, c.raw_row_id)
        if k not in seen:
            seen.add(k)
            out.append(c)
    return out[:CITATION_CAP], len(out)
