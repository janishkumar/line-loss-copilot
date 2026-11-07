"""Before/after test: can the copilot work out what changed on the brick line?

The prompt names only the two windows. Nothing from the dataset's own write-up is in the
prompt, the tool descriptions or the tool output. Ground truth is evals.truth.
before_after_facts. A fact is found when a claim names its metric with the right direction;
a claim is wrong when its direction is wrong or its metric is not one the data supports.
The claimed value is recorded but not scored."""

from __future__ import annotations

import json
import re
from typing import Any

METRICS = ("availability", "performance", "quality", "oee", "stop_time", "stop_count", "mttr")
PROMPT = (
    "What changed on the brick line between September-December 2025 (before) and "
    "January-April 2026 (after)? Compare the two periods using the data. End your answer "
    "with a JSON block of claims, a list of objects like "
    '{"metric": "...", "direction": "up" or "down", "value": <number or null>}, where '
    "metric is one of availability, performance, quality, oee, stop_time, stop_count, mttr, "
    "or reason:<STOP_GROUP> for the lost time of a stop group. Then finish with a separate "
    "last line 'ANSWER: <one-sentence summary>'."
)
CAVEATS = [
    "In the before period, 13 days in October 2025 have a published planned time 7 to 8 hours "
    "larger than production plus stops (docs/data-notes.md). Availability recomputed from "
    "the stop log is inflated on those days, so the before availability and OEE facts carry "
    "that error. The facts are what the data says; nothing is corrected.",
    "Brick performance and quality are the published per-shift values (no independent "
    "source); oee here is recomputed availability times published performance and quality.",
    "stop_time, stop_count and reason:<group> are totals over each window, and the windows "
    "hold different numbers of shifts (see truth.shifts). A total can fall while the "
    "per-shift rate rises; before_per_shift and after_per_shift are given for reading "
    "them but the score uses the totals.",
    "Windows are calendar months by shift or stop start (UTC). The before data covers "
    "2025-09-22 to 2025-12-18 and the after data 2026-01-30 to 2026-04-03.",
]
_FENCE = re.compile(r"```(?:json)?\s*(\[.*?\])\s*```", re.DOTALL)


def _json_lists(answer: str) -> list[list]:
    """JSON lists in the answer, last first: fenced blocks, then any bare list."""
    out = []
    for raw in reversed(_FENCE.findall(answer)):
        try:
            out.append(json.loads(raw))
        except ValueError:
            continue
    dec = json.JSONDecoder()
    for i in reversed([i for i, ch in enumerate(answer) if ch == "["]):
        try:
            val, _ = dec.raw_decode(answer, i)
        except ValueError:
            continue
        out.append(val)
    return [x for x in out if isinstance(x, list)]


def parse_claims(answer: str) -> list[dict[str, Any]]:
    """The last JSON list of claims in the answer (fenced block first, then a bare list).
    Items without a metric and an up/down direction are dropped."""
    for items in _json_lists(answer):
        out = []
        for it in items:
            if not isinstance(it, dict):
                continue
            metric = str(it.get("metric", "")).strip()
            direction = str(it.get("direction", "")).strip().lower()
            if metric and direction in ("up", "down"):
                out.append({"metric": metric, "direction": direction, "value": it.get("value")})
        if out:
            return out
    return []


def _key(metric: str) -> str:
    """Normalise a claimed metric: lower-case names; reason:<GROUP> keeps the group upper."""
    m = metric.strip()
    if m.lower().startswith("reason:"):
        return "reason:" + m.split(":", 1)[1].strip().upper()
    return m.lower()


def score_claims(claims: list[dict[str, Any]], truth: dict[str, Any]) -> dict[str, Any]:
    directions = {_key(k): v for k, v in truth["directions"].items()}
    facts = truth["facts"]
    judged = []
    for c in claims:
        k = _key(c["metric"])
        actual = directions.get(k)
        ok = actual is not None and actual == c["direction"]
        judged.append({**c, "metric": k, "actual": actual, "correct": ok})
    found = [
        f["metric"]
        for f in facts
        if any(j["metric"] == _key(f["metric"]) and j["correct"] for j in judged)
    ]
    wrong = [j for j in judged if not j["correct"]]
    return {
        "facts_total": len(facts),
        "facts_found": len(found),
        "share_found": len(found) / len(facts) if facts else None,
        "found": found,
        "missed": [f["metric"] for f in facts if f["metric"] not in found],
        "claims": judged,
        "wrong_claims": len(wrong),
    }
