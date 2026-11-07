"""Model-facing compaction, shared by the MCP server and the chat loop."""

import asyncio
import json

from linecopilot.chat.loop import _tool_payload
from linecopilot.mcp_server.server import build_server
from linecopilot.tools import compact
from linecopilot.tools.compact import MAX_CHARS, compact_json, compact_result, dumps
from linecopilot.tools.envelope import Citation, Result
from mcp import Client

UNREACHABLE = "postgresql://nobody:nothing@127.0.0.1:1/none?connect_timeout=1"


def cite(event_id: int) -> Citation:
    return Citation(
        raw_table="brick_downtime",
        source_file="brick/x.csv",
        raw_row_id=event_id,
        event_id=event_id,
    )


def test_caps_citations_and_lists():
    res = Result(
        status="ok",
        data={
            "rows": [{"i": i, "citations": [cite(i).model_dump()] * 8} for i in range(45)],
            "total": 45,
        },
        citations=[cite(i) for i in range(50)],
        citation_count=120,
    )
    out = compact_result(res)
    assert set(out) >= {"status", "data", "citations", "citation_count", "window", "missing"}
    assert len(out["citations"]) == 10 and out["citation_count"] == 120
    assert len(out["data"]["rows"]) == 30 and out["data"]["total"] == 45
    assert len(out["data"]["rows"][0]["citations"]) == 3
    assert "citations: showing 10 of 120" in out["trimmed"]
    assert "data.rows: showing 30 of 45" in out["trimmed"]
    assert any("(30 items cut)" in t for t in out["trimmed"])
    assert not any("size guard" in t for t in out["trimmed"])


def test_small_result_has_no_note():
    out = compact_result(Result(status="ok", data={"rows": [1, 2]}, citations=[cite(1)]))
    assert "trimmed" not in out and out["data"] == {"rows": [1, 2]}


def test_size_guard_cuts_lists_further_and_says_so():
    # 30 rows of ~3k chars each is ~90k chars: over the guard even after the usual 30-row cut.
    rows = [{"i": i, "text": "x" * 3000} for i in range(100)]
    out = compact_result(Result(status="ok", data={"rows": rows}))
    assert len(dumps(out)) <= MAX_CHARS
    n = len(out["data"]["rows"])
    assert n < compact.MODEL_LIST_ROWS and n in compact.ROW_STEPS
    assert f"data.rows: showing {n} of 100" in out["trimmed"]
    assert any(t.startswith(f"size guard: lists cut to {n} items") for t in out["trimmed"])


def test_size_guard_reports_when_it_cannot_fit():
    out = compact_result(Result(status="ok", data={"blob": "y" * (MAX_CHARS + 10)}))
    assert any("still over" in t for t in out["trimmed"])


def _mcp_text(name: str, args: dict) -> str:
    async def go():
        async with Client(build_server(UNREACHABLE)) as client:
            return (await client.call_tool(name, args)).content[0].text

    return asyncio.run(go())


def _chat_text(name: str, args: dict, conn=None) -> str:
    tc = {"function": {"name": name, "arguments": args}}
    return dumps(_tool_payload(conn, tc)[2])


def test_mcp_and_chat_send_the_same_text_for_bad_args():
    args = {"line_id": "brick", "bogus": 1}
    assert _mcp_text("get_oee", args) == _chat_text("get_oee", args)
    assert json.loads(_mcp_text("get_oee", args))["status"] == "out_of_scope"


def test_compact_json_is_dumps_of_compact_result():
    res = Result(status="ok", data={"rows": list(range(40))})
    assert compact_json(res) == dumps(compact_result(res))
