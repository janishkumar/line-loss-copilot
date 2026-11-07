"""Database connection helper."""

from __future__ import annotations

import psycopg


def connect(url: str) -> psycopg.Connection:
    return psycopg.connect(url)
