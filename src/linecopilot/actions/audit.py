"""The audit writer. One row per outcome, including refused and blocked attempts.

`actions.audit_log` is append-only (triggers refuse UPDATE and DELETE), and the agent role may
insert into it, so every path, agent or human, can record what happened."""

from __future__ import annotations

from collections.abc import Sequence

import psycopg
from psycopg.types.json import Jsonb

from linecopilot.actions.checks import CheckResult


def write(
    conn: psycopg.Connection,
    *,
    event: str,
    outcome: str,
    principal: str,
    on_behalf_of: str | None = None,
    channel: str | None = None,
    action: str | None = None,
    proposal_id: int | None = None,
    payload_sha256: str | None = None,
    checks: Sequence[CheckResult] = (),
    detail: str = "",
) -> int:
    """Insert one audit row and return its id. Joins whatever transaction the caller has open."""
    row = conn.execute(
        "INSERT INTO actions.audit_log (event, action, proposal_id, principal, on_behalf_of, "
        "channel, payload_sha256, outcome, checks, detail) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING audit_id",
        (
            event,
            action,
            proposal_id,
            principal,
            on_behalf_of,
            channel,
            payload_sha256,
            outcome,
            Jsonb([c.to_dict() for c in checks]),
            detail,
        ),
    ).fetchone()
    return row[0]
