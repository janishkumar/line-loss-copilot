"""Run the MCP server over stdio: python -m linecopilot.mcp_server."""

import os

from linecopilot.config import get_settings
from linecopilot.mcp_server.server import build_server


def main() -> None:
    s = get_settings()
    # LINECOPILOT_MCP_TOOLS: comma-separated read tool names to register (default: all)
    raw = os.environ.get("LINECOPILOT_MCP_TOOLS", "")
    only = {n.strip() for n in raw.split(",") if n.strip()} or None
    build_server(s.database_url, s.agent_database_url, s.mcp_user, only_tools=only).run("stdio")


if __name__ == "__main__":
    main()
