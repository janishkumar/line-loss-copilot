"""The same tool call through the API, the MCP server and the chat loop gives the same status
and data: the API in full, MCP and chat after the shared compaction."""

import asyncio
import json
import os

import pytest
from fastapi.testclient import TestClient

from linecopilot.api.app import create_app
from linecopilot.chat.loop import _tool_payload
from linecopilot.mcp_server.server import build_server
from linecopilot.tools.compact import compact_result, dumps
from linecopilot.tools.envelope import Result
from mcp import Client

pytestmark = pytest.mark.db

CASES = [
    ("get_oee", "/api/oee", {"line_id": "brick", "start": "2026-02-01", "end": "2026-03-01"}),
    ("get_oee", "/api/oee", {"machine_id": "s_2", "group": "day"}),
    ("loss_pareto", "/api/losses/pareto", {"machine_id": "s_2", "by": "reason"}),
    ("breakdown", "/api/losses/breakdown", {"line_id": "brick", "rows": "reason", "cols": "month"}),
    ("reliability", "/api/reliability", {"line_id": "brick", "group": "month"}),
    ("get_events", "/api/events", {"machine_id": "s_2", "limit": 50}),
    ("search_notes", "/api/notes/search", {"query": "grasarisma"}),
    ("get_oee", "/api/oee", {"line_id": "brick", "group": "week"}),  # invalid argument
    ("loss_pareto", "/api/losses/pareto", {"line_id": "brick"}),  # missing argument
    ("get_oee", "/api/oee", {"machine_id": "s_99"}),  # unknown machine
]


@pytest.fixture(scope="module")
def api(built):
    return TestClient(create_app(os.environ["LINECOPILOT_TEST_DB_URL"]))


def mcp_body(name: str, args: dict) -> dict:
    async def go():
        async with Client(build_server(os.environ["LINECOPILOT_TEST_DB_URL"])) as client:
            res = await client.call_tool(name, args)
            assert res.is_error is False
            return res.content[0].text

    return json.loads(asyncio.run(go()))


@pytest.mark.parametrize(("name", "path", "args"), CASES)
def test_same_status_and_data_on_every_front_end(api, built, name, path, args):
    r = api.get(path, params=args)
    assert r.status_code == 200, r.text
    full = r.json()
    via_mcp = mcp_body(name, args)
    via_chat = _tool_payload(built, {"function": {"name": name, "arguments": args}})[2]
    assert full["status"] == via_mcp["status"] == via_chat["status"]
    compacted = compact_result(Result.model_validate(full))
    assert compacted["data"] == via_mcp["data"] == via_chat["data"]
    if full["status"] == "ok":
        # the whole compacted envelope is the same text on MCP and chat
        assert dumps(via_mcp) == dumps(via_chat) == dumps(compacted)
