"""shift_evidence and get_source_rows against the fixture database."""

import os

import psycopg
import pytest

from linecopilot.tools.envelope import CitationRef
from linecopilot.tools.evidence import (
    GetSourceRowsArgs,
    ShiftEvidenceArgs,
    get_source_rows,
    shift_evidence,
)

pytestmark = pytest.mark.db


def test_shift_evidence_reports_missing_raw_row(built):
    # Delete one cited raw row inside a transaction that is rolled back, so the shared
    # fixture database is untouched for other tests.
    with psycopg.connect(os.environ["LINECOPILOT_TEST_DB_URL"]) as conn:
        before = shift_evidence(conn, ShiftEvidenceArgs(shift_id="brick:2026-02-02"))
        assert before.status == "ok" and before.data.missing_rows == []
        gone = before.data.rows[-1]
        conn.execute(
            f"DELETE FROM raw.{gone.raw_table} WHERE source_file = %s AND source_row = %s",
            (gone.source_file, gone.source_row),
        )
        r = shift_evidence(conn, ShiftEvidenceArgs(shift_id="brick:2026-02-02"))
        conn.rollback()
    ref = CitationRef(
        raw_table=gone.raw_table, source_file=gone.source_file, raw_row_id=gone.source_row
    )
    assert r.status == "ok"
    assert r.data.missing_rows == [ref]
    assert len(r.data.rows) == len(before.data.rows) - 1
    assert any(str(gone.source_row) in a and "not found" in a for a in r.assumptions)
    assert all(
        c.raw_row_id != gone.source_row or c.raw_table != gone.raw_table for c in r.citations
    )


def test_get_source_rows_not_found(built):
    eid, table, file, rid = built.execute(
        "SELECT event_id, raw_table, source_file, raw_row_ids[1] FROM core.event "
        "WHERE raw_table = 'brick_downtime' ORDER BY event_id LIMIT 1"
    ).fetchone()
    real = CitationRef(raw_table=table, source_file=file, raw_row_id=rid)
    fake = CitationRef(raw_table="brick_downtime", source_file=file, raw_row_id=999999)
    r = get_source_rows(built, GetSourceRowsArgs(citations=[real, fake]))
    assert r.status == "ok"
    assert r.data.not_found == [fake]
    assert "999999" in r.missing
    (row,) = r.data.rows
    assert (row.raw_table, row.source_file, row.raw_row_id) == (table, file, rid)
    cur = built.execute(
        f"SELECT * FROM raw.{table} WHERE source_file = %s AND source_row = %s", (file, rid)
    )
    cols = [d.name for d in cur.description]
    assert row.raw == dict(zip(cols, cur.fetchone(), strict=True))
    assert [(c.raw_table, c.raw_row_id) for c in r.citations] == [(table, rid)]


def test_get_source_rows_by_event_and_none_found(built):
    eid, rid = built.execute(
        "SELECT event_id, raw_row_ids[1] FROM core.event WHERE raw_table = 'piade_raw' LIMIT 1"
    ).fetchone()
    r = get_source_rows(built, GetSourceRowsArgs(event_ids=[eid, 999999999]))
    assert r.status == "ok" and r.data.rows[0].raw_row_id == rid
    assert r.data.rows[0].event_id == eid and r.data.not_found_event_ids == [999999999]
    assert "999999999" in r.missing
    bad_table = CitationRef(raw_table="pg_user", source_file="x", raw_row_id=1)
    none = get_source_rows(built, GetSourceRowsArgs(citations=[bad_table]))
    assert none.status == "insufficient_evidence" and none.data.not_found == [bad_table]
