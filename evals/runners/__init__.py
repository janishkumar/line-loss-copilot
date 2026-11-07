"""Eval runners: each asks one prompt and returns a Reply."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Reply:
    answer: str
    latency_s: float
    model_id: str | None = None
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    rounds: int | None = None
    error: str | None = None
