"""MCP server through the SDK's in-memory client."""

import asyncio
import json
import os

import pytest

from linecopilot.mcp_server.server import build_server
from linecopilot.tools.registry import TOOLS
from mcp import Client

UNREACHABLE = "postgresql://nobody:nothing@127.0.0.1:1/none?connect_timeout=1"


def run(db_url, fn):
    async def go():
        async with Client(build_server(db_url)) as client:
            return await fn(client)

    return asyncio.run(go())


def test_lists_all_registry_tools_read_only():
    tools = run(UNREACHABLE, lambda c: c.list_tools()).tools
    assert {t.name for t in tools} == set(TOOLS)
    for t in tools:
        assert t.annotations is not None
        assert t.annotations.read_only_hint is True
        assert t.annotations.destructive_hint is False
        assert t.annotations.idempotent_hint is True
        assert t.annotations.open_world_hint is False
        assert t.input_schema == TOOLS[t.name].args_model.model_json_schema()
        assert t.description == TOOLS[t.name].description


def test_no_write_or_approve_tool():
    names = {t.name for t in run(UNREACHABLE, lambda c: c.list_tools()).tools}
    assert not [n for n in names if any(w in n for w in ("approve", "propose", "write", "delete"))]


def test_server_instructions_state_the_rules():
    async def go(c):
        return c.instructions

    text = run(UNREACHABLE, go)
    assert "[event:<id>]" in text and "not ok" in text and "quoted data" in text


def test_internal_error_is_a_tool_error_and_server_survives():
    async def go(c):
        bad = await c.call_tool("list_assets", {})
        again = await c.list_tools()
        return bad, again

    bad, again = run(UNREACHABLE, go)
    assert bad.is_error is True
    assert len(again.tools) == len(TOOLS)


def test_bad_args_returns_envelope_not_error():
    async def go(c):
        return await c.call_tool("get_oee", {"line_id": "brick", "bogus": 1})

    res = run(UNREACHABLE, go)
    assert res.is_error is False
    body = json.loads(res.content[0].text)
    assert body["status"] == "out_of_scope"


@pytest.mark.db
def test_call_get_oee_returns_envelope(built):
    url = os.environ["LINECOPILOT_TEST_DB_URL"]

    async def go(c):
        return await c.call_tool(
            "get_oee", {"line_id": "brick", "start": "2026-02-02", "end": "2026-02-05"}
        )

    res = run(url, go)
    assert res.is_error is False
    body = json.loads(res.content[0].text)
    assert body["status"] == "ok" and body["citations"]
    assert len(body["data"]["rows"]) == 2
