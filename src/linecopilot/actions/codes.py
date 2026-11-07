"""One-time confirmation codes.

A code is shown once, stored only as a sha256, bound to the action, the acting identity and the
hash of the canonical arguments, and burned by the first redeem attempt that finds it, whether
that attempt succeeds or is refused. The clock is passed in."""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta

import psycopg

from linecopilot.actions.identity import ActionContext

ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
CODE_LENGTH = 8


def normalise(code: str | None) -> str:
    return (code or "").strip().upper()


def hash_code(code: str) -> str:
    return hashlib.sha256(normalise(code).encode("utf-8")).hexdigest()


def new_code() -> str:
    return "".join(secrets.choice(ALPHABET) for _ in range(CODE_LENGTH))


def issue(
    conn: psycopg.Connection,
    action: str,
    ctx: ActionContext,
    payload_sha256: str,
    now: datetime,
    ttl: timedelta,
) -> str:
    """Store a hashed code for this action, identity and arguments; return the plain code.
    `ttl` has no default: callers pass the policy value (`confirmation.ttl_minutes`)."""
    code = new_code()
    conn.execute(
        "INSERT INTO actions.confirmation_code (code_sha256, action, principal, on_behalf_of, "
        "payload_sha256, expires_at, created_at) VALUES (%s, %s, %s, %s, %s, %s, %s)",
        (hash_code(code), action, ctx.principal, ctx.on_behalf_of, payload_sha256, now + ttl, now),
    )
    return code


def redeem(
    conn: psycopg.Connection,
    code: str | None,
    action: str,
    ctx: ActionContext,
    payload_sha256: str,
    now: datetime,
) -> str | None:
    """None if the code is good, else the refusal text.

    One UPDATE burns the code and returns its binding, so a second or concurrent attempt finds
    nothing. The comparisons run after the burn: a wrong guess still spends the code.

    The caller must commit the burn whatever the outcome (autocommit, or a transaction of its
    own for the redeem): a rollback later in the same transaction would un-burn a refused code."""
    if not normalise(code):
        return "missing code"
    row = conn.execute(
        "UPDATE actions.confirmation_code SET used_at = %s "
        "WHERE code_sha256 = %s AND used_at IS NULL "
        "RETURNING action, principal, on_behalf_of, payload_sha256, expires_at",
        (now, hash_code(code or "")),
    ).fetchone()
    if row is None:
        return "unknown or already used code"
    c_action, c_principal, c_behalf, c_hash, expires_at = row
    if now >= expires_at:
        return "code expired"
    if (c_action, c_principal, c_behalf) != (action, ctx.principal, ctx.on_behalf_of):
        return "code was issued for a different action or user"
    if c_hash != payload_sha256:
        return "arguments differ from the preview"
    return None
