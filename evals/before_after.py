"""Before/after test: can the copilot work out what changed on the brick line?

The prompt names the two windows and the definitions the answer key uses. Nothing from the
dataset's own write-up is in the prompt, the tool descriptions or the tool output. Ground
truth is evals.truth.before_after_facts.

Only `scored` facts count: past the minimum effect size (1 percentage point for ratios, 5%
relative otherwise), for totals the same direction as a total and per shift, and for ratios
the same direction with and without the October days whose published planned time is not
accounted for. A fact is
found when a claim names its metric with its direction. A claim is wrong when it contradicts
a scored fact or names a metric that is not recognised; a claim on a flat or ambiguous
metric is neither found nor wrong. The claimed value is recorded but not scored."""

from __future__ import annotations

import json
import re
from typing import Any

METRICS = ("availability", "performance", "quality", "oee", "stop_time", "stop_count", "mttr")
PROMPT = (
    "What changed on the brick line between September-December 2025 (before) and "
    "January-April 2026 (after)? Compare the two periods using the data. "
    "Definitions: availability is recomputed from the stop log (availability_calc); "
    "performance and quality are the published per-shift values; oee is availability_calc "
    "times performance times quality; mttr is mean failure stop seconds. stop_time (stop "
    "seconds) and stop_count are totals over each window, and the windows hold different "
    "numbers of shifts, so also look at them per shift; the same holds for the lost time of "
    "each stop group. A change counts only if it is at least 1 percentage point for a ratio "
    "or 5% otherwise, and, for totals, only if the total and the per-shift figure move the "
    "same way. End your answer with a JSON block of claims, a list of objects like "
    '{"metric": "...", "direction": "up" or "down", "value": <number or null>}, where '
    "metric is one of availability, performance, quality, oee, stop_time, stop_count, mttr, "
    "or reason:<STOP_GROUP> for the lost time of a stop group. Then finish with a separate "
    "last line 'ANSWER: <one-sentence summary>'."
)
CAVEATS = [
    "In the before period, 13 days in October 2025 have a published planned time 2.9 to 8.1 "
    "hours larger than published production plus stops (docs/data-notes.md). Availability "
    "recomputed from the stop log is inflated on those days. Each ratio fact (availability, "
    "performance, quality, oee) is therefore also read without the days picked by that rule "
    "(truth.planned_gap_days); where the two readings disagree the fact is ambiguous and not "
    "scored. Both values are kept in the facts.",
    "Brick performance and quality are the published per-shift values (no independent "
    "source); oee here is recomputed availability times published performance and quality.",
    "stop_time, stop_count and reason:<group> are totals over windows with different numbers "
    "of shifts (truth.shifts). Each is read as a total and per shift; where the two readings "
    "disagree the fact is ambiguous and not scored.",
    "Facts below the minimum effect size (1 percentage point for ratios, 5% relative "
    "otherwise) are flat and not scored.",
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
    status = {_key(k): v for k, v in truth["status"].items()}
    scored = [f for f in truth["facts"] if f["status"] == "scored"]
    judged = []
    for c in claims:
        k = _key(c["metric"])
        actual = status.get(k)
        if actual in ("up", "down"):
            verdict = "correct" if actual == c["direction"] else "wrong"
        elif actual in ("flat", "ambiguous"):
            verdict = "neutral"
        else:  # not a recognised metric or stop group
            verdict = "wrong"
        judged.append({**c, "metric": k, "actual": actual, "verdict": verdict})
    found = [
        f["metric"]
        for f in scored
        if any(j["metric"] == _key(f["metric"]) and j["verdict"] == "correct" for j in judged)
    ]
    return {
        "facts_total": len(scored),
        "facts_found": len(found),
        "share_found": len(found) / len(scored) if scored else None,
        "found": found,
        "missed": [f["metric"] for f in scored if f["metric"] not in found],
        "not_scored": {f["metric"]: f["status"] for f in truth["facts"] if f["status"] != "scored"},
        "claims": judged,
        "wrong_claims": sum(j["verdict"] == "wrong" for j in judged),
        "neutral_claims": sum(j["verdict"] == "neutral" for j in judged),
    }
