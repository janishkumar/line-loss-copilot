"""Shared fixtures. `built` loads the fixtures into the test DB once and runs dbt build; the dbt
and api tests both use it."""

import os
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

import psycopg
import pytest

from linecopilot.ingest.load import load_all


@pytest.fixture
def db_url() -> str:
    url = os.environ.get("LINECOPILOT_TEST_DB_URL")
    if not url:
        pytest.skip("LINECOPILOT_TEST_DB_URL is not set")
    return url


ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures"
LAYOUT = {
    "brick/OEEdataset.csv": "brick/oee_before.csv",
    "brick/OEEdataset_afterLSS.csv": "brick/oee_after.csv",
    "brick/DowntimeDataset.csv": "brick/downtime_before.csv",
    "brick/DowntimeDataset_afterLSS.csv": "brick/downtime_after.csv",
    "piade/raw_data.csv": "piade/raw_small.csv",
}


def dbt_env(url: str) -> dict[str, str]:
    u = urlparse(url)
    return {
        **os.environ,
        "LINECOPILOT_DBT_HOST": u.hostname or "localhost",
        "LINECOPILOT_DBT_PORT": str(u.port or 5432),
        "LINECOPILOT_DBT_USER": u.username or "",
        "LINECOPILOT_DBT_PASSWORD": u.password or "",
        "LINECOPILOT_DBT_DBNAME": u.path.lstrip("/"),
    }


@pytest.fixture(scope="session")
def built(tmp_path_factory):
    url = os.environ.get("LINECOPILOT_TEST_DB_URL")
    if not url:
        pytest.skip("LINECOPILOT_TEST_DB_URL is not set")
    data_dir = tmp_path_factory.mktemp("data")
    for dest, src in LAYOUT.items():
        target = data_dir / "raw" / dest
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(FIX / src, target)
    with psycopg.connect(url) as conn:
        for schema in ("raw", "core", "staging", "mart"):
            conn.execute(f"DROP SCHEMA IF EXISTS {schema} CASCADE")
        conn.commit()
        load_all(conn, data_dir)
    dbt = Path(sys.executable).parent / "dbt"
    result = subprocess.run(
        [
            str(dbt),
            "build",
            "--project-dir",
            "dbt",
            "--profiles-dir",
            "dbt",
            "--target-path",
            str(data_dir / "target"),
            "--log-path",
            str(data_dir / "logs"),
        ],
        cwd=ROOT,
        env=dbt_env(url),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    # Autocommit so one failing query cannot abort the shared session for later tests.
    with psycopg.connect(url, autocommit=True) as conn:
        yield conn
