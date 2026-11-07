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


SCOPED = (
    "get_oee",
    "loss_pareto",
    "breakdown",
    "repeat_failures",
    "reliability",
    "compare_periods",
    "get_events",
)


def test_scope_hint_reaches_mcp_and_chat_schemas():
    from linecopilot.chat.loop import tool_schemas
    from linecopilot.tools.common import SCOPE_HINT

    assert "pass line_id='brick' and no machine_id" in SCOPE_HINT
    assert "pass machine_id only" in SCOPE_HINT and "end is exclusive" in SCOPE_HINT
    mcp_tools = {t.name: t for t in run(UNREACHABLE, lambda c: c.list_tools()).tools}
    chat = {s["function"]["name"]: s["function"] for s in tool_schemas()}
    for name in SCOPED:
        assert SCOPE_HINT in mcp_tools[name].description, name
        assert SCOPE_HINT in chat[name]["description"], name
        for props in (
            mcp_tools[name].input_schema["properties"],
            chat[name]["parameters"]["properties"],
        ):
            assert "machine_id only" in props["machine_id"]["description"], name
            assert "'brick'" in props["line_id"]["description"], name


def test_month_hint_reaches_mcp_and_chat_schemas():
    from linecopilot.chat.loop import tool_schemas
    from linecopilot.tools.common import MONTH_GROUP_HINT, MONTH_WINDOW_HINT

    assert "group='month'" in MONTH_GROUP_HINT and "group" not in MONTH_WINDOW_HINT
    mcp_tools = {t.name: t for t in run(UNREACHABLE, lambda c: c.list_tools()).tools}
    chat = {s["function"]["name"]: s["function"] for s in tool_schemas()}
    expected = {
        "get_oee": MONTH_GROUP_HINT,
        "reliability": MONTH_GROUP_HINT,
        "loss_pareto": MONTH_WINDOW_HINT,
        "breakdown": MONTH_WINDOW_HINT,
        "repeat_failures": MONTH_WINDOW_HINT,
    }
    for name, hint in expected.items():
        assert hint in mcp_tools[name].description, name
        assert hint in chat[name]["description"], name


def test_hints_only_name_fields_the_tool_has():
    import re

    from linecopilot.tools.common import MONTH_GROUP_HINT, MONTH_WINDOW_HINT, SCOPE_HINT

    for name, spec in TOOLS.items():
        fields = set(spec.args_model.model_fields)
        for hint in (SCOPE_HINT, MONTH_GROUP_HINT, MONTH_WINDOW_HINT):
            if hint not in spec.description:
                continue
            named = set(re.findall(r"\b([a-z_]+)\s*=", hint)) | set(
                re.findall(r"\b(\w+_id)\b", hint)
            )
            assert named, hint
            assert named <= fields, (name, named - fields)
