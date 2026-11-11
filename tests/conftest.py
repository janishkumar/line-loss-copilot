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

from linecopilot import schemas
from linecopilot.ingest.load import load_all


@pytest.fixture
def db_url() -> str:
    url = os.environ.get("LINECOPILOT_TEST_DB_URL")
    if not url:
        pytest.skip("LINECOPILOT_TEST_DB_URL is not set")
    return url


@pytest.fixture
def agent_url(db_url) -> str:
    """The test URL with the restricted agent role's credentials."""
    u = urlparse(db_url)
    host = u.hostname or "localhost"
    netloc = f"linecopilot_agent:linecopilot_agent@{host}" + (f":{u.port}" if u.port else "")
    return u._replace(netloc=netloc).geturl()


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


def copy_fixtures(root: Path) -> Path:
    """Lay the fixture files out under root/raw as the loader expects; returns root."""
    for dest, src in LAYOUT.items():
        target = root / "raw" / dest
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(FIX / src, target)
    return root


@pytest.fixture(scope="session")
def make_data_dir(tmp_path_factory):
    """Factory: a fresh data dir holding a copy of the fixture files."""
    return lambda: copy_fixtures(tmp_path_factory.mktemp("data"))


@pytest.fixture(scope="session")
def built(make_data_dir):
    url = os.environ.get("LINECOPILOT_TEST_DB_URL")
    if not url:
        pytest.skip("LINECOPILOT_TEST_DB_URL is not set")
    data_dir = make_data_dir()
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
    # Schemas and agent grants after dbt, as `make dbt` does (dbt drops grants on rebuilt tables).
    with psycopg.connect(url) as conn:
        schemas.apply(conn)
    # Autocommit so one failing query cannot abort the shared session for later tests.
    with psycopg.connect(url, autocommit=True) as conn:
        yield conn


def _wipe_vision(conn) -> None:
    """Remove everything the inspection tests create (children first)."""
    for table in (
        "actions.quality_hold",
        "actions.proposal_evidence",
    ):
        conn.execute(
            f"DELETE FROM {table} WHERE proposal_id IN "
            "(SELECT proposal_id FROM actions.proposal WHERE args->>'asset_id' LIKE 'SIM-VIS-%')"
        )
    conn.execute("DELETE FROM actions.proposal WHERE args->>'asset_id' LIKE 'SIM-VIS-%'")
    conn.execute("DELETE FROM synthetic.quality_event")
    conn.execute("DELETE FROM vision.review")
    conn.execute("DELETE FROM vision.inspection")
    conn.execute("DELETE FROM synthetic.sim_asset")


@pytest.fixture
def vision_clean(built):
    """The test connection with empty vision.* and synthetic quality tables, before and after."""
    _wipe_vision(built)
    yield built
    _wipe_vision(built)


@pytest.fixture
def make_inspection(vision_clean):
    """Insert one stored inspection through the real store functions (no model needed)."""
    import uuid

    from linecopilot.vision import store

    def make(subset="cashew", decision="review", score=0.9, reject_event=True, heatmap=None):
        image = f"{subset}/Data/Images/Anomaly/{uuid.uuid4().hex[:8]}.JPG"
        iid = store.insert_inspection(
            vision_clean,
            subset=subset,
            image_id=image,
            score=score,
            decision=decision,
            threshold=0.88,
            review_lower=0.87,
            heatmap_path=heatmap,
        )
        assert iid is not None
        if decision == "reject" and reject_event:
            store.create_quality_event(vision_clean, iid, "automatic")
        return iid

    return make
