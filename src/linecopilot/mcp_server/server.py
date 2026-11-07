"""MCP server: one read-only tool per registry entry, same names and argument schemas.

Every call opens its own connection and goes through `registry.call_tool`, so the answer is the
same Result envelope the API and the chat loop return; sessions are read-only. The envelope is
compacted exactly as the chat loop compacts it (`tools.compact`), so a client's tool-output cap
is not reached; the `trimmed` list says what was cut, and the API serves the full envelope. An
internal error is raised, which the SDK reports to the client as a tool error without stopping
the server."""

from __future__ import annotations

import sys
from collections.abc import Collection
from typing import Any

import psycopg
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.tools.base import Tool
from mcp.server.mcpserver.utilities.func_metadata import ArgModelBase, FuncMetadata
from mcp_types import ToolAnnotations
from pydantic import ConfigDict, ValidationError

from linecopilot.actions.identity import AGENT, ActionContext, get_user
from linecopilot.actions.policy import load_policy
from linecopilot.actions.service import ActionService
from linecopilot.actions.tools import ACTION_TOOLS, ActionToolSpec, call_action_tool
from linecopilot.config import get_settings
from linecopilot.db import connect_read_only
from linecopilot.prompting import ACTION_INSTRUCTIONS, BASE_INSTRUCTIONS
from linecopilot.tools import registry
from linecopilot.tools.compact import compact_json, dumps

SERVER_NAME = "linecopilot"

INSTRUCTIONS = BASE_INSTRUCTIONS

READ_ONLY = ToolAnnotations(
    read_only_hint=True,
    destructive_hint=False,
    idempotent_hint=True,
    open_world_hint=False,
)


def _action_annotations(spec: ActionToolSpec) -> ToolAnnotations:
    """Previews write a code row and an audit row and proposals write a proposal, so only the
    list tool is read-only; none of them destroys or overwrites anything."""
    return ToolAnnotations(
        read_only_hint=spec.read_only,
        destructive_hint=False,
        idempotent_hint=spec.read_only,
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
        with connect_read_only(db_url) as conn:
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


def _make_action_tool(
    spec: ActionToolSpec, agent_db_url: str, ctx: ActionContext, service: ActionService
) -> Tool:
    def run(**kwargs: Any) -> str:
        # one autocommit agent-role connection per call; the identity is the server's, fixed at
        # start-up from the environment, never from the arguments
        with psycopg.connect(agent_db_url, autocommit=True) as conn:
            return dumps(call_action_tool(conn, ctx, service, spec.name, kwargs))

    return Tool(
        fn=run,
        name=spec.name,
        description=spec.description,
        parameters=spec.args_model.model_json_schema(),
        fn_metadata=FuncMetadata(arg_model=_RawArgs),
        is_async=False,
        annotations=_action_annotations(spec),
    )


def _log(reason: str) -> None:
    print(f"linecopilot mcp: read-only, no action tools: {reason}", file=sys.stderr, flush=True)


def resolve_context(agent_db_url: str | None, user_id: str | None) -> ActionContext | None:
    """The identity for action tools, or None (and one stderr line saying why) when the server
    should start read-only: no user, the agent itself, an unknown or non-human user, or no
    database to check against."""
    if not user_id:
        _log("LINECOPILOT_MCP_USER is unset")
        return None
    if user_id == AGENT:
        _log(f"{user_id!r} is the agent, not a human user")
        return None
    if not agent_db_url:
        _log("no agent database URL")
        return None
    try:
        with psycopg.connect(agent_db_url, autocommit=True, connect_timeout=5) as conn:
            user = get_user(conn, user_id)
    except Exception as e:
        _log(f"could not look up user {user_id!r} ({type(e).__name__})")
        return None
    if user is None:
        _log(f"unknown user {user_id!r}")
        return None
    if user.role == "agent":
        _log(f"user {user_id!r} is not a human")
        return None
    return ActionContext(AGENT, user.user_id, "mcp")


def build_server(
    db_url: str,
    agent_db_url: str | None = None,
    mcp_user: str | None = None,
    service: ActionService | None = None,
    only_tools: Collection[str] | None = None,
) -> MCPServer:
    """Read tools always; the propose-side action tools only when `mcp_user` names a human demo
    user, on an agent-role connection from `agent_db_url`. `only_tools` registers just those read
    tools (the stage 2 eval pins its tool set this way, so the model never sees the others)."""
    tools = [
        _make_tool(spec, db_url)
        for name, spec in registry.TOOLS.items()
        if only_tools is None or name in only_tools
    ]
    instructions = INSTRUCTIONS
    ctx = resolve_context(agent_db_url, mcp_user)
    svc = service
    if ctx is not None and svc is None:
        try:
            svc = ActionService(load_policy(get_settings().policy_path))
        except Exception as e:
            # a policy that will not load takes the action tools down, never the read tools
            _log(f"policy did not load ({type(e).__name__}: {e})")
            ctx = None
    if ctx is not None and svc is not None and agent_db_url is not None:
        tools += [_make_action_tool(s, agent_db_url, ctx, svc) for s in ACTION_TOOLS.values()]
        instructions = f"{INSTRUCTIONS} {ACTION_INSTRUCTIONS}"
    return MCPServer(SERVER_NAME, instructions=instructions, tools=tools)
