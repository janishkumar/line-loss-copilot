"""MCP server: one read-only tool per registry entry, same names and argument schemas.

Every call opens its own connection and goes through `registry.call_tool`, so the answer is the
same Result envelope the API and the chat loop return. The envelope is compacted exactly as the
chat loop compacts it (`tools.compact`), so a client's tool-output cap is not reached; the
`trimmed` list says what was cut, and the API serves the full envelope. An internal error is
raised, which the SDK reports to the client as a tool error without stopping the server."""

from __future__ import annotations

from typing import Any

import psycopg
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.tools.base import Tool
from mcp.server.mcpserver.utilities.func_metadata import ArgModelBase, FuncMetadata
from mcp_types import ToolAnnotations
from pydantic import ConfigDict, ValidationError

from linecopilot.prompting import BASE_INSTRUCTIONS
from linecopilot.tools import registry
from linecopilot.tools.compact import compact_json

SERVER_NAME = "linecopilot"

INSTRUCTIONS = BASE_INSTRUCTIONS

READ_ONLY = ToolAnnotations(
    read_only_hint=True,
    destructive_hint=False,
    idempotent_hint=True,
    open_world_hint=False,
)


class _RawArgs(ArgModelBase):
    """Accepts any arguments untouched; validation happens in registry.call_tool, which answers
    bad arguments with an out_of_scope envelope instead of a protocol error."""

    model_config = ConfigDict(extra="allow")

    def model_dump_one_level(self) -> dict[str, Any]:
        return dict(self.model_extra or {})


def _make_tool(spec: registry.ToolSpec, db_url: str) -> Tool:
    def run(**kwargs: Any) -> str:
        try:
            spec.args_model.model_validate(kwargs)
        except ValidationError:
            # invalid arguments never touch the database; call_tool builds the envelope
            return compact_json(registry.call_tool(None, spec.name, kwargs))
        with psycopg.connect(db_url, autocommit=True) as conn:
            result = registry.call_tool(conn, spec.name, kwargs)
        return compact_json(result)

    return Tool(
        fn=run,
        name=spec.name,
        description=spec.description,
        parameters=spec.args_model.model_json_schema(),
        fn_metadata=FuncMetadata(arg_model=_RawArgs),
        is_async=False,
        annotations=READ_ONLY,
    )


def build_server(db_url: str) -> MCPServer:
    tools = [_make_tool(spec, db_url) for spec in registry.TOOLS.values()]
    return MCPServer(SERVER_NAME, instructions=INSTRUCTIONS, tools=tools)
