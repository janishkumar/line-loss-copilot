"""Database connection helper."""

from __future__ import annotations

import psycopg


def connect(url: str) -> psycopg.Connection:
    return psycopg.connect(url)


# API and MCP sessions: every transaction is read-only, so a read path can never write, even
# by mistake. Loaders, translation and training open their own writable connections.
READ_ONLY_OPTIONS = "-c default_transaction_read_only=on"


def connect_read_only(url: str) -> psycopg.Connection:
    return psycopg.connect(url, autocommit=True, options=READ_ONLY_OPTIONS)
