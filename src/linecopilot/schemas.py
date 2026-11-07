"""Apply the schemas dbt does not build: enrich (notes search) and ml (stop-risk tables).

Both files are idempotent, so `make dbt` runs this before every build; a database first
built at an earlier stage gets the schemas without a full reload.

    python -m linecopilot.schemas"""

from __future__ import annotations

from pathlib import Path

import psycopg

from linecopilot.config import get_settings

SQL_DIR = Path(__file__).resolve().parents[2] / "sql"
FILES = (SQL_DIR / "enrich_schema.sql", SQL_DIR / "ml_schema.sql")


def apply(conn: psycopg.Connection) -> list[str]:
    """Run each schema file in one transaction; returns the file names applied."""
    with conn.transaction():
        for f in FILES:
            conn.execute(f.read_text())
    return [f.name for f in FILES]


def main() -> int:
    with psycopg.connect(get_settings().database_url) as conn:
        print("applied", ", ".join(apply(conn)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
