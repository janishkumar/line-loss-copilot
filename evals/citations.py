"""Citation check: is each cited event among the events that support the answer?

A cited row is an `[event:<id>]` in the answer (parsed by linecopilot.chat.loop.cited_ids).
It is supported iff it is in the question's `evidence_event_ids` from evals/truth.py, which
encode the machine, window and category the answer is about. An unanswerable question has
no evidence, so any citation on it is unsupported."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from linecopilot.chat.loop import cited_ids


@dataclass
class CitationCheck:
    cited: list[int]
    supported: list[int]

    @property
    def unsupported(self) -> list[int]:
        s = set(self.supported)
        return [i for i in self.cited if i not in s]


def check(answer: str, evidence: Iterable[int]) -> CitationCheck:
    ids = cited_ids(answer)
    ev = set(evidence)
    return CitationCheck(cited=ids, supported=[i for i in ids if i in ev])


def summarize(checks: list[CitationCheck]) -> dict[str, Any]:
    """Micro support rate over all cited rows, share of answers whose citations are all
    supported (and non-empty), and share of answers with no citations."""
    n = len(checks)
    cited = sum(len(c.cited) for c in checks)
    supported = sum(len(c.supported) for c in checks)
    full = sum(1 for c in checks if c.cited and len(c.supported) == len(c.cited))
    none = sum(1 for c in checks if not c.cited)
    return {
        "answers": n,
        "cited_rows": cited,
        "supported_rows": supported,
        "micro_support_rate": supported / cited if cited else None,
        "share_fully_supported": full / n if n else None,
        "share_no_citations": none / n if n else None,
    }
