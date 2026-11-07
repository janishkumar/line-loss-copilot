import os
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

import psycopg
import pytest

from linecopilot.ingest.load import load_all

pytestmark = pytest.mark.db

ROOT = Path(__file__).resolve().parents[2]
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


@pytest.fixture(scope="module")
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
        for schema in ("raw", "core", "staging"):
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
    with psycopg.connect(url) as conn:
        yield conn


def scalar(conn, sql):
    return conn.execute(sql).fetchone()[0]


def test_event_counts_match_raw(built):
    brick_stops = scalar(built, "SELECT count(*) FROM raw.brick_downtime")
    piade = scalar(built, "SELECT count(*) FROM raw.piade_raw")
    oee = scalar(built, "SELECT count(*) FROM raw.brick_oee")
    assert brick_stops > 0 and piade > 0 and oee > 0
    assert scalar(built, "SELECT count(*) FROM core.event") == brick_stops + piade + oee
    by_type = dict(
        built.execute("SELECT event_type, count(*) FROM core.event GROUP BY 1").fetchall()
    )
    assert by_type == {"stop": brick_stops, "state_interval": piade, "production_count": oee}


def test_every_event_has_lineage(built):
    assert scalar(built, "SELECT count(*) FROM core.event WHERE cardinality(raw_row_ids) = 0") == 0
    missing = scalar(
        built,
        """SELECT count(*) FROM core.event e WHERE e.raw_table = 'piade_raw' AND NOT EXISTS (
               SELECT 1 FROM raw.piade_raw r
               WHERE r.source_row = e.raw_row_ids[1]
                 AND r.source_file || '#' || r.source_row = e.event_key)""",
    )
    assert missing == 0


def test_notes_only_non_blank(built):
    expected = scalar(
        built,
        "SELECT count(*) FROM raw.brick_downtime WHERE btrim(coalesce(note, '')) NOT IN ('', '-')",
    )
    assert expected > 0
    assert scalar(built, "SELECT count(*) FROM core.note") == expected
    assert (
        scalar(built, "SELECT count(*) FROM core.note WHERE btrim(original_text) IN ('', '-')") == 0
    )
    assert scalar(built, "SELECT count(*) FROM core.note_translation") == 0


def test_event_ids_are_deterministic_and_keyed(built):
    first = built.execute("SELECT event_id, event_key FROM core.event ORDER BY event_id").fetchall()
    assert [r[0] for r in first] == list(range(1, len(first) + 1))
    assert len({r[1] for r in first}) == len(first)


def test_shift_and_timezone_rules(built):
    # Brick local 07:15 Europe/Nicosia in September (UTC+3) is 04:15 UTC.
    start = scalar(
        built,
        "SELECT min(start_ts) AT TIME ZONE 'UTC' FROM core.event"
        " WHERE shift_id = 'brick:2025-09-22' AND event_type = 'stop'",
    )
    assert (start.hour, start.minute) == (4, 15)
    assert (
        scalar(
            built,
            "SELECT count(*) FROM core.event e LEFT JOIN core.shift s USING (shift_id)"
            " WHERE s.shift_id IS NULL",
        )
        == 0
    )


def test_notes_language_detected(built):
    langs = {r[0] for r in built.execute("SELECT DISTINCT language FROM core.note").fetchall()}
    assert langs <= {"el", "latin"}
