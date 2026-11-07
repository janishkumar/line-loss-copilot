"""Shared result types for file parsers."""

from __future__ import annotations

from dataclasses import dataclass, field


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
