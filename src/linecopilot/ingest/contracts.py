"""Shared result types for file parsers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Rejected:
    """A source row that failed its contract. `source_row` is the 1-based data line."""

    source_row: int
    reason: str
    raw: dict[str, str]


@dataclass
class ParsedFile:
    """Rows that passed the contract, with lineage back to the source file."""

    rows: list[dict[str, str | None]]
    source_rows: list[int]
    rejected: list[Rejected] = field(default_factory=list)
    trimmed_columns: int = 0
    trimmed_rows: int = 0
    # Optional bulk form of `rows` (a pandas DataFrame indexed by source_row) for large files.
    frame: Any = None
