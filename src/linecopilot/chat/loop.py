"""Tool-calling chat loop: the model asks for read tools, the registry runs them, and the
model answers from the results.

The tools offered are fixed per call (every registry entry, or none for the no-tools
baseline), so nothing a tool returns can add, remove or change a tool. Tool results reach the
model only as `tool` messages, compacted by `tools.compact.compact_result` (the same text the
MCP server returns); the full citations are kept for the caller."""

from __future__ import annotations

import json
import logging
import re
import time
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, Field

from linecopilot.chat.ollama import OllamaClient, context_full
from linecopilot.chat.prompt import SYSTEM_PROMPT
from linecopilot.tools.compact import compact_result, dumps
from linecopilot.tools.envelope import Citation, cap_citations
from linecopilot.tools.registry import TOOLS, call_tool

log = logging.getLogger(__name__)

# A round can still take the 180 s client timeout: 400 + 180 < the 600 s proxy timeout.
TIME_BUDGET_S = 400.0
NO_ANSWER = "The model returned no answer."
# [event:12], and the grouped forms small models write: [event:12, event:13] or [event:12, 13].
# The bracket body is matched by a bounded class (no nested quantifiers), then checked by split.
EVENT_REF = re.compile(r"\[event:([^\[\]\n]{1,200})\]")


class ToolCall(BaseModel):
    name: str
    args: dict[str, Any] | str
    status: str
    missing: str | None = None


class RoundStat(BaseModel):
    prompt_eval_count: int | None = Field(None, description="prompt tokens Ollama read")
    eval_count: int | None = Field(None, description="tokens Ollama generated")
    context_full: bool = Field(
        False, description="prompt_eval_count reached num_ctx - 256: the prompt may be cut"
    )


def _count(reply: Any, key: str) -> int | None:
    v = reply.get(key) if isinstance(reply, dict) else None
    return v if isinstance(v, int) and not isinstance(v, bool) else None


class ChatResult(BaseModel):
    answer: str
    citations: list[Citation] = Field(description="capped union of the tool results' citations")
    citation_count: int = 0
    cited_event_ids: list[int] = Field(description="ids cited as [event:<id>] in the answer")
    unsupported_cited_ids: list[int] = Field(
        description="cited ids that appear in no tool result citation"
    )
    tool_calls: list[ToolCall]
    model: str
    rounds: int
    stop_reason: str = Field(
        default="answer", description="answer, rounds, budget or malformed: why the loop ended"
    )
    rounds_detail: list[RoundStat] = Field(default_factory=list)
    context_full: bool = Field(False, description="any round filled the model's context")


# ---- tool schemas ----------------------------------------------------------------------


def _flatten(node: Any, defs: dict[str, Any]) -> Any:
    """Inline `$ref`s, turn `anyOf [X, null]` into X and drop titles: small models handle a
    flat schema better. Property names are never touched."""
    if isinstance(node, list):
        return [_flatten(x, defs) for x in node]
    if not isinstance(node, dict):
        return node
    if "$ref" in node:
        target = defs[node["$ref"].rsplit("/", 1)[-1]]
        rest = {k: v for k, v in node.items() if k != "$ref"}
        return _flatten({**target, **rest}, defs)
    if "anyOf" in node:
        options = [o for o in node["anyOf"] if o != {"type": "null"}]
        if len(options) == 1:
            rest = {k: v for k, v in node.items() if k != "anyOf"}
            return _flatten({**options[0], **rest}, defs)
    out: dict[str, Any] = {}
    for k, v in node.items():
        if k in ("$defs", "title"):
            continue
        if k == "properties":
            out[k] = {name: _flatten(sub, defs) for name, sub in v.items()}
        else:
            out[k] = _flatten(v, defs)
    return out


def tool_schemas() -> list[dict[str, Any]]:
    """Ollama tool definitions for every registry entry, same names and argument names."""
    out = []
    for spec in TOOLS.values():
        schema = spec.args_model.model_json_schema()
        out.append(
            {
                "type": "function",
                "function": {
                    "name": spec.name,
                    "description": spec.description,
                    "parameters": _flatten(schema, schema.get("$defs", {})),
                },
            }
        )
    return out


# ---- tool results ---------------------------------------------------------------------


def _event_ids(node: Any, into: set[int]) -> None:
    """Every event_id found in any `citations` list of a dumped result."""
    if isinstance(node, dict):
        for k, v in node.items():
            if k == "citations" and isinstance(v, list):
                into.update(
                    c["event_id"]
                    for c in v
                    if isinstance(c, dict) and c.get("event_id") is not None
                )
            else:
                _event_ids(v, into)
    elif isinstance(node, list):
        for x in node:
            _event_ids(x, into)


def _ref_ids(body: str) -> list[int] | None:
    """Ids in one bracket body after "event:", or None if it is not a list of ids."""
    ids = []
    for part in body.split(","):
        part = part.strip()
        part = part.removeprefix("event:").strip() if ids else part
        if not part.isascii() or not part.isdigit():
            return None
        ids.append(int(part))
    return ids


def cited_ids(answer: str) -> list[int]:
    ids = (i for body in EVENT_REF.findall(answer) for i in (_ref_ids(body) or []))
    return list(dict.fromkeys(ids))


def _parse_args(raw: Any) -> tuple[dict[str, Any] | str, str | None]:
    """Arguments arrive as a dict or a JSON string. Returns (args, error)."""
    if raw is None:
        return {}, None
    if isinstance(raw, str):
        try:
            raw = json.loads(raw) if raw.strip() else {}
        except ValueError:
            return raw, "arguments were not valid JSON"
    if not isinstance(raw, dict):
        return str(raw), "arguments must be a JSON object"
    return raw, None


# ---- the loop ------------------------------------------------------------------------------


def _tool_payload(conn: Any, tc: Any) -> tuple[str, dict[str, Any] | str, dict[str, Any], Any]:
    """Run one requested tool call. Returns (name, args, payload for the model, Result or
    None). Nothing here raises: every failure is an out_of_scope payload."""
    fn = tc.get("function") if isinstance(tc, dict) else None
    if not isinstance(fn, dict):
        return "", "", {"status": "out_of_scope", "missing": "malformed tool call"}, None
    name = str(fn.get("name") or "")
    args, err = _parse_args(fn.get("arguments"))
    if err is not None:
        return name, args, {"status": "out_of_scope", "missing": err}, None
    try:
        res = call_tool(conn, name, args)  # type: ignore[arg-type]
    except Exception:
        log.exception("tool %s failed", name)
        return name, args, {"status": "out_of_scope", "missing": f"internal error in {name}"}, None
    return name, args, compact_result(res), res


def _unique_calls(requested: list) -> list:
    """Drop repeated identical calls (same name and arguments) within one round. Small models
    sometimes emit the same call many times, which multiplies the next request's size."""
    seen: set[str] = set()
    out = []
    for tc in requested:
        fn = tc.get("function") if isinstance(tc, dict) else None
        key = dumps(fn) if isinstance(fn, dict) else repr(tc)
        if key not in seen:
            seen.add(key)
            out.append(tc)
    return out


def run_chat(
    conn: Any,
    client: OllamaClient,
    messages: list[dict],
    tools_enabled: bool = True,
    max_rounds: int = 6,
    time_budget_s: float = TIME_BUDGET_S,
    clock: Callable[[], float] = time.monotonic,
) -> ChatResult:
    """Run the conversation until the model answers without a tool call, `max_rounds` model
    calls have been made, or `time_budget_s` has passed (checked between rounds). `messages`
    holds user and assistant turns only; the system prompt is always ours."""
    tools = tool_schemas() if tools_enabled else []
    convo: list[dict[str, Any]] = [{"role": "system", "content": SYSTEM_PROMPT}]
    convo += [{"role": m["role"], "content": m["content"]} for m in messages]
    cites: list[Citation] = []
    supported: set[int] = set()
    calls: list[ToolCall] = []
    answer: str | None = None
    stop = "answer"
    rounds = 0
    stats: list[RoundStat] = []
    started = clock()
    while answer is None:
        if rounds >= max_rounds:
            answer = (
                f"The tool loop stopped after {max_rounds} rounds without a final answer. "
                "Try a narrower question."
            )
            stop = "rounds"
            break
        if rounds and clock() - started > time_budget_s:
            answer = (
                f"The tool loop stopped after {int(time_budget_s)} s without a final answer. "
                "Try a narrower question."
            )
            stop = "budget"
            break
        rounds += 1
        reply = client.chat(convo, tools)
        pec = _count(reply, "prompt_eval_count")
        stats.append(
            RoundStat(
                prompt_eval_count=pec,
                eval_count=_count(reply, "eval_count"),
                context_full=context_full(pec),
            )
        )
        msg = reply.get("message") if isinstance(reply, dict) else None
        requested = msg.get("tool_calls") if isinstance(msg, dict) else None
        if not isinstance(msg, dict) or not isinstance(requested, list | None):
            answer = "The model returned a malformed reply."
            stop = "malformed"
            break
        content = str(msg.get("content") or "")
        requested = (requested or []) if tools_enabled else []
        if not requested:
            answer = content if content.strip() else NO_ANSWER
            break
        requested = _unique_calls(requested)
        convo.append({"role": "assistant", "content": content, "tool_calls": requested})
        for tc in requested:
            name, args, payload, res = _tool_payload(conn, tc)
            if res is not None:
                cites.extend(res.citations)
                _event_ids(res.model_dump(mode="json"), supported)
            calls.append(
                ToolCall(name=name, args=args, status=payload["status"], missing=payload["missing"])
            )
            convo.append({"role": "tool", "tool_name": name, "content": dumps(payload)})
    capped, count = cap_citations(cites)
    ids = cited_ids(answer)
    return ChatResult(
        answer=answer,
        citations=capped,
        citation_count=count,
        cited_event_ids=ids,
        unsupported_cited_ids=[i for i in ids if i not in supported],
        tool_calls=calls,
        model=client.model,
        rounds=rounds,
        stop_reason=stop,
        rounds_detail=stats,
        context_full=any(r.context_full for r in stats),
    )
