import pytest

pytestmark = pytest.mark.db


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


def test_event_citation_is_unique(built):
    dupes = scalar(
        built,
        """SELECT count(*) FROM (SELECT 1 FROM core.event
           GROUP BY raw_table, source_file, raw_row_ids[1], event_type HAVING count(*) > 1) d""",
    )
    assert dupes == 0
    assert (
        scalar(
            built,
            "SELECT count(DISTINCT source_file) FROM core.event WHERE source_system = 'brick'",
        )
        == 4
    )


def test_note_citation_is_unique(built):
    dupes = scalar(
        built,
        """SELECT count(*) FROM (SELECT 1 FROM core.note
           GROUP BY raw_table, source_file, raw_row_id HAVING count(*) > 1) d""",
    )
    assert dupes == 0
    assert scalar(built, "SELECT count(*) FROM core.note WHERE source_file IS NULL") == 0


def test_every_event_lineage_joins_to_exactly_one_raw_row(built):
    bad = scalar(
        built,
        """SELECT count(*) FROM (
             SELECT e.event_id FROM core.event e
             LEFT JOIN (
                 SELECT 'brick_downtime' AS t, source_file, source_row FROM raw.brick_downtime
                 UNION ALL SELECT 'brick_oee', source_file, source_row FROM raw.brick_oee
                 UNION ALL SELECT 'piade_raw', source_file, source_row FROM raw.piade_raw
             ) r ON r.t = e.raw_table AND r.source_file = e.source_file
                AND r.source_row = e.raw_row_ids[1]
             GROUP BY e.event_id HAVING count(r.source_row) <> 1) x""",
    )
    assert bad == 0
