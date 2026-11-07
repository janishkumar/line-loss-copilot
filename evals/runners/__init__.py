"""Eval runners: each asks one prompt and returns a Reply."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Added to every question's user message by every runner (tools and no-tools, Ollama and
# Claude), so all of them are asked for the same last line. The system prompt keeps its rule.
ANSWER_SUFFIX = (
    "Finish with one final line in the form `ANSWER: <value>` (or `ANSWER: NOT_AVAILABLE`)."
)


def build_prompt(question: str) -> str:
    return f"{question}\n\n{ANSWER_SUFFIX}"


@dataclass
class Reply:
    answer: str
    latency_s: float
    model_id: str | None = None
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    rounds: int | None = None
    error: str | None = None
    retries: int = 0
