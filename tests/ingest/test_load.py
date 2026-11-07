import hashlib
import json
import shutil
from pathlib import Path

import psycopg
import pytest

from linecopilot.ingest.load import ChecksumMismatch, load_all

pytestmark = pytest.mark.db

FIX = Path(__file__).parent.parent / "fixtures"
LAYOUT = {
    "brick/OEEdataset.csv": "brick/oee_before.csv",
    "brick/OEEdataset_afterLSS.csv": "brick/oee_after.csv",
    "brick/DowntimeDataset.csv": "brick/downtime_before.csv",
    "brick/DowntimeDataset_afterLSS.csv": "brick/downtime_after.csv",
    "piade/raw_data.csv": "piade/raw_small.csv",
}


def copy_fixtures(root: Path) -> Path:
    for dest, src in LAYOUT.items():
        target = root / "raw" / dest
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(FIX / src, target)
    return root


@pytest.fixture
def data_dir(tmp_path) -> Path:
    return copy_fixtures(tmp_path)


@pytest.fixture
def conn(db_url, tmp_path_factory):
    with psycopg.connect(db_url) as c:
        c.execute("DROP SCHEMA IF EXISTS raw CASCADE")
        c.commit()
        yield c
        c.rollback()
        # Leave raw as the shared `built` fixture loaded it (the same fixture files, so the
        # same source_row lineage); later tests read raw rows behind core.event.
        c.execute("DROP SCHEMA IF EXISTS raw CASCADE")
        load_all(c, copy_fixtures(tmp_path_factory.mktemp("restore")))
        c.commit()


def count(conn, table):
    return conn.execute(f"SELECT count(*) FROM raw.{table}").fetchone()[0]


def table_counts(conn):
    return {t: count(conn, t) for t in ("brick_oee", "brick_downtime", "piade_raw", "rejected")}


def test_load_fixtures_counts(conn, data_dir):
    summaries = load_all(conn, data_dir)
    assert len(summaries) == 5
    for table in ("brick_oee", "brick_downtime", "piade_raw"):
        accepted = sum(s.rows_accepted for s in summaries if s.table == table)
        assert accepted > 0
        assert count(conn, table) == accepted
    assert count(conn, "piade_raw") == 37
    meta = conn.execute("SELECT count(*), sum(rows_accepted) FROM raw.load").fetchone()
    assert meta[0] == 5
    assert meta[1] == sum(s.rows_accepted for s in summaries)
    periods = conn.execute("SELECT DISTINCT period FROM raw.brick_oee ORDER BY 1").fetchall()
    assert periods == [("after",), ("before",)]


def test_rejected_rows_land_in_raw_rejected(conn, data_dir):
    summaries = load_all(conn, data_dir)
    expected = sum(s.rows_rejected for s in summaries)
    assert expected > 0
    assert count(conn, "rejected") == expected
    reasons = {r[0] for r in conn.execute("SELECT reason FROM raw.rejected").fetchall()}
    assert "empty_row" in reasons
    row = conn.execute(
        "SELECT source_file, source_row, raw FROM raw.rejected WHERE reason = 'empty_row' LIMIT 1"
    ).fetchone()
    assert row[0].startswith("brick/") and row[1] > 0
    assert isinstance(row[2], dict)


def test_reload_is_idempotent(conn, data_dir):
    load_all(conn, data_dir)
    first = table_counts(conn)
    load_all(conn, data_dir)
    assert table_counts(conn) == first
    assert count(conn, "load") == 10  # run history is kept, data rows are not doubled
    live = conn.execute("SELECT count(DISTINCT load_id) FROM raw.piade_raw").fetchone()[0]
    assert live == 1


def test_lineage_points_to_file_line(conn, data_dir):
    load_all(conn, data_dir)
    lines = (data_dir / "raw/brick/OEEdataset.csv").read_text(encoding="utf-8-sig").splitlines()
    shift_date = conn.execute(
        "SELECT shift_date FROM raw.brick_oee WHERE source_file = 'brick/OEEdataset.csv' "
        "AND source_row = 3"
    ).fetchone()[0]
    month, day, year = lines[3].split(",")[0].split("/")  # source_row 3 = file line 4
    assert shift_date == f"20{year}-{int(month):02d}-{int(day):02d}"
    piade = conn.execute(
        "SELECT start_raw, end_raw, machine_id FROM raw.piade_raw "
        "WHERE source_file = 'piade/raw_data.csv' AND source_row = 3"
    ).fetchone()
    fields = (data_dir / "raw/piade/raw_data.csv").read_text().splitlines()[3].split(",")
    assert piade == (fields[4], fields[5], fields[1])


def test_sha256_is_of_loaded_file(conn, data_dir):
    load_all(conn, data_dir)
    for dest in LAYOUT:
        filename = dest.split("/")[1]
        want = hashlib.sha256((data_dir / "raw" / dest).read_bytes()).hexdigest()
        got = conn.execute("SELECT sha256 FROM raw.load WHERE filename = %s", (filename,))
        assert got.fetchone()[0] == want


def test_manifest_mismatch_raises_and_loads_nothing(conn, data_dir):
    (data_dir / "checksums.json").write_text(
        json.dumps({"files": [{"filename": "raw_data.csv", "sha256": "0" * 64}]})
    )
    with pytest.raises(ChecksumMismatch):
        load_all(conn, data_dir)
    assert count(conn, "piade_raw") == 0


def test_rows_visible_from_second_connection(conn, data_dir, db_url):
    load_all(conn, data_dir)
    with psycopg.connect(db_url) as other:
        assert other.execute("SELECT count(*) FROM raw.piade_raw").fetchone()[0] == 37
        assert other.execute("SELECT count(*) FROM raw.load").fetchone()[0] == 5
