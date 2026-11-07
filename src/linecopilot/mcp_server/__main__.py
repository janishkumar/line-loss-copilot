"""Run the MCP server over stdio: python -m linecopilot.mcp_server."""

from linecopilot.config import get_settings
from linecopilot.mcp_server.server import build_server


def main() -> None:
    s = get_settings()
    build_server(s.database_url, s.agent_database_url, s.mcp_user).run("stdio")


if __name__ == "__main__":
    main()
