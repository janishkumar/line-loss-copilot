"""Typed read tools shared by the API, the MCP server and the chat loop (design 6).

Every tool is `fn(conn, args) -> Result[...]`; `registry.call_tool` dispatches by name."""
