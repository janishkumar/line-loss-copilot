"""Run the MCP server over stdio: python -m linecopilot.mcp_server."""

from linecopilot.config import get_settings
from linecopilot.mcp_server.server import build_server


def main() -> None:
    build_server(get_settings().database_url).run("stdio")


if __name__ == "__main__":
    main()
