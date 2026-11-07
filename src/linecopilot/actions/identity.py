"""Who is acting. The identity is built by the front end, never taken from a tool argument.

mcp and web_chat: principal is the agent, on_behalf_of is the human it serves.
web_form: principal and on_behalf_of are both the signed-in session user."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import psycopg

AGENT = "copilot-agent"

Channel = Literal["mcp", "web_chat", "web_form"]


@dataclass(frozen=True)
class ActionContext:
    principal: str
    on_behalf_of: str
    channel: Channel


@dataclass(frozen=True)
class AppUser:
    user_id: str
    display_name: str
    role: str


def get_user(conn: psycopg.Connection, user_id: str) -> AppUser | None:
    row = conn.execute(
        "SELECT user_id, display_name, role FROM demo.app_user WHERE user_id = %s", (user_id,)
    ).fetchone()
    return AppUser(*row) if row else None
