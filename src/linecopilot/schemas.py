"""Apply the schemas dbt does not build: enrich (notes search), ml (stop-risk tables), demo
(synthetic users), actions (approved actions, audit log, agent role grants), then synthetic
(stage 4 orders, BOMs, stock), plan (plan outputs) and vision (inspections, review labels,
simulated quality events and the core.event_all view), which grant the agent role SELECT.

All files are idempotent. `make dbt` runs this before and after every build: dbt recreates
core and mart tables, which drops their grants, so the second run restores the agent's
read access.

    python -m linecopilot.schemas"""

from __future__ import annotations

from pathlib import Path

import psycopg

from linecopilot.config import get_settings

SQL_DIR = Path(__file__).resolve().parents[2] / "sql"
FILES = (
    SQL_DIR / "enrich_schema.sql",
    SQL_DIR / "ml_schema.sql",
    SQL_DIR / "demo_schema.sql",
    SQL_DIR / "actions_schema.sql",
    SQL_DIR / "synthetic_schema.sql",
    SQL_DIR / "plan_schema.sql",
    SQL_DIR / "vision_schema.sql",
)


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
