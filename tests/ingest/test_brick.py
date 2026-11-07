from pathlib import Path

from linecopilot.ingest.brick import parse_brick_downtime, parse_brick_oee

FIX = Path(__file__).parent.parent / "fixtures" / "brick"


def test_oee_bom_and_column_map_before():
    parsed = parse_brick_oee(FIX / "oee_before.csv", "before")
    assert len(parsed.rows) == 6
    first = parsed.rows[0]
    assert first["shift_date"] == "2025-09-22"
    assert first["good_production_s"] == "14604"
    assert first["ideal_qty"] == "38626.75"
    assert first["period"] == "before"


def test_oee_column_map_after():
    before = parse_brick_oee(FIX / "oee_before.csv", "before")
    after = parse_brick_oee(FIX / "oee_after.csv", "after")
    assert len(after.rows) == 3
    assert set(after.rows[0]) == set(before.rows[0])
    assert after.rows[0]["shift_date"] == "2026-01-30"
    assert after.rows[0]["planned_s"] == "27900"


def test_empty_oee_row_rejected():
    parsed = parse_brick_oee(FIX / "oee_before.csv", "before")
    assert [(r.source_row, r.reason) for r in parsed.rejected] == [(6, "empty_row")]


def test_duplicate_date_kept_both():
    parsed = parse_brick_oee(FIX / "oee_before.csv", "before")
    dates = [r["shift_date"] for r in parsed.rows]
    assert dates.count("2025-09-26") == 2


def test_downtime_after_trims_padding():
    parsed = parse_brick_downtime(FIX / "downtime_after.csv", "after")
    assert parsed.trimmed_columns >= 30
    assert len(parsed.rows) == 4
    assert parsed.trimmed_rows == 5
    assert parsed.rejected == []
    assert parsed.rows[0]["duration_min"] == "9"
    assert parsed.rows[0]["start_local"] == "2026-01-30T07:15"


def test_dash_note_is_none():
    parsed = parse_brick_downtime(FIX / "downtime_before.csv", "before")
    assert parsed.rows[0]["note"] is None  # "-"
    assert parsed.rows[1]["note"] is None  # empty
    assert parsed.rows[4]["location"] is None  # "-"


def test_greek_note_kept_verbatim():
    parsed = parse_brick_downtime(FIX / "downtime_before.csv", "before")
    assert parsed.rows[3]["note"] == "ΤΟΥΒΛΑ ΕΣΠΑΖΑΝ"
    assert parsed.rows[4]["note"] == "grasarisma"


def test_overlapping_and_not_included_stops_are_kept():
    parsed = parse_brick_downtime(FIX / "downtime_before.csv", "before")
    assert len(parsed.rows) == 8
    assert parsed.rows[0]["stop_type"] == "Planned - Not included in OEE"


def test_source_rows_are_file_lines():
    oee = parse_brick_oee(FIX / "oee_before.csv", "before")
    assert oee.source_rows == [1, 2, 3, 4, 5, 7]
    down = parse_brick_downtime(FIX / "downtime_before.csv", "before")
    assert down.source_rows == list(range(1, 9))
