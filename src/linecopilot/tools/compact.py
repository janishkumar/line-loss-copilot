"""The Result envelope as a model sees it, shared by the MCP server and the chat loop.

The API returns the full envelope. Model-facing front ends get a compacted copy: every key is
kept, top-level citations are cut to MODEL_CITATIONS, citations inside data rows to
MODEL_NESTED_CITATIONS, long lists to MODEL_LIST_ROWS items, and floats to 6 significant
digits. If the JSON is still over MAX_CHARS, lists are cut further, step by step. A `trimmed`
list says what was cut, so a model can tell a short list from a cut one and ask a narrower
question or fetch rows by citation."""

from __future__ import annotations

import json
from typing import Any

from linecopilot.tools.envelope import Result

MODEL_CITATIONS = 10
MODEL_NESTED_CITATIONS = 3
MODEL_LIST_ROWS = 30
MAX_CHARS = 40_000
# List lengths tried in turn until the JSON fits in MAX_CHARS.
ROW_STEPS = (MODEL_LIST_ROWS, 15, 8, 4, 2, 1)


def dumps(obj: Any) -> str:
    """Compact JSON, the exact text a model receives."""
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"), default=str)


def _compact(value: Any, path: str, rows: int, notes: dict[str, int], nested: list[int]) -> Any:
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if k == "citations" and isinstance(v, list):
                if len(v) > MODEL_NESTED_CITATIONS:
                    nested[0] += 1
                out[k] = v[:MODEL_NESTED_CITATIONS]
            else:
                out[k] = _compact(v, f"{path}.{k}", rows, notes, nested)
        return out
    if isinstance(value, list):
        if len(value) > rows:
            notes[path] = max(notes.get(path, 0), len(value))
            value = value[:rows]
        return [_compact(x, f"{path}[]", rows, notes, nested) for x in value]
    if isinstance(value, float):
        return float(f"{value:.6g}")
    return value


def _build(d: dict[str, Any], rows: int) -> dict[str, Any]:
    notes: dict[str, int] = {}
    nested = [0]
    data = _compact(d["data"], "data", rows, notes, nested)
    count = max(d["citation_count"], len(d["citations"]))
    out = {
        "status": d["status"],
        "data": data,
        "citations": d["citations"][:MODEL_CITATIONS],
        "citation_count": count,
        "window": d["window"],
        "assumptions": d["assumptions"],
        "missing": d["missing"],
    }
    trimmed = [f"{p}: showing {rows} of {n}" for p, n in notes.items()]
    if len(d["citations"]) > MODEL_CITATIONS:
        trimmed.append(f"citations: showing {MODEL_CITATIONS} of {count}")
    if nested[0]:
        trimmed.append(
            f"citations inside data: at most {MODEL_NESTED_CITATIONS} per item "
            f"({nested[0]} items cut)"
        )
    if trimmed:
        out["trimmed"] = trimmed
    return out


def compact_result(res: Result) -> dict[str, Any]:
    """The compacted envelope (see the module docstring)."""
    d = res.model_dump(mode="json")
    for rows in ROW_STEPS:
        out = _build(d, rows)
        if len(dumps(out)) <= MAX_CHARS:
            break
    if rows < MODEL_LIST_ROWS:
        out.setdefault("trimmed", []).append(
            f"size guard: lists cut to {rows} items to keep this result under "
            f"{MAX_CHARS} characters; narrow the window or filters for more"
        )
    if len(dumps(out)) > MAX_CHARS:
        out.setdefault("trimmed", []).append(
            f"size guard: still over {MAX_CHARS} characters with 1 item per list"
        )
    return out


def compact_json(res: Result) -> str:
    return dumps(compact_result(res))
