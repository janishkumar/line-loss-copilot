"""Eval runners: each asks one prompt and returns a Reply."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# The tools the stage 2 answer eval offers, pinned by name so its results stay comparable when
# the registry grows. Used by the Ollama runner's tool list and the Claude runner's MCP
# allow-list; the safety eval and the apps use the whole registry.
STAGE2_TOOLS = (
    "list_assets",
    "get_oee",
    "get_source_rows",
    "shift_evidence",
    "loss_pareto",
    "breakdown",
    "repeat_failures",
    "reliability",
    "compare_periods",
    "get_events",
    "search_notes",
    "stop_risk",
)

# Added to every question's user message by evals.run (the same text for every runner, tools
# and no-tools, Ollama and Claude), so all are asked for the same last line. Not added to the
# before/after prompt, which asks for its own summary line. The system prompt keeps its rule.
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
    # Ollama only: prompt_eval_count / eval_count per model call, and whether any call came
    # within 256 tokens of num_ctx (where Ollama silently cuts the prompt).
    rounds_detail: list[dict[str, Any]] = field(default_factory=list)
    # None when the runner does not measure it (Claude).
    context_full: bool | None = None
    # Safety eval: ids of the proposals this reply's tool calls created; None when the runner
    # cannot see tool results (Claude), so the run falls back to its per-prompt tag.
    proposal_ids: list[int] | None = None
