from pathlib import Path

from linecopilot.ingest.brick import parse_brick_downtime, parse_brick_oee

FIX = Path(__file__).parent.parent / "fixtures" / "brick"


def test_oee_bom_and_column_map_before():
    parsed = parse_brick_oee(FIX / "oee_before.csv", "before")
    assert len(parsed.rows) == 5
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
    assert (6, "empty_row") in [(r.source_row, r.reason) for r in parsed.rejected]


def test_duplicate_date_keeps_first_and_rejects_later():
    # One shift per date (docs/data-notes.md): a second row for a date is rejected, not merged.
    parsed = parse_brick_oee(FIX / "oee_before.csv", "before")
    dates = [r["shift_date"] for r in parsed.rows]
    assert dates.count("2025-09-26") == 1
    kept = next(r for r in parsed.rows if r["shift_date"] == "2025-09-26")
    assert kept["oee"] == "0.6500"
    assert [(r.source_row, r.reason) for r in parsed.rejected] == [
        (6, "empty_row"),
        (7, "duplicate_shift"),
    ]
    assert parsed.rejected[1].raw["oee"] == "0.6600"


def test_duplicate_check_ignores_rejected_rows(tmp_path):
    path = _write(tmp_path, OEE_HDR, _oee_row(oee="abc"), _oee_row())
    parsed = parse_brick_oee(path, "after")
    assert len(parsed.rows) == 1
    assert [(r.source_row, r.reason) for r in parsed.rejected] == [(1, "bad_number:oee")]


def test_downtime_after_trims_padding():
    parsed = parse_brick_downtime(FIX / "downtime_after.csv", "after")
    assert parsed.trimmed_columns >= 30
    assert len(parsed.rows) == 9
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
    assert oee.source_rows == [1, 2, 3, 4, 5]
    down = parse_brick_downtime(FIX / "downtime_before.csv", "before")
    assert down.source_rows == list(range(1, 9))


# --- contract rejection tests (tmp_path files) ---

import pytest  # noqa: E402

from linecopilot.ingest.brick import DOWNTIME_COLUMNS, OEE_COLUMNS  # noqa: E402

OEE_HDR = ",".join(OEE_COLUMNS["after"])
DT_HDR = ",".join(DOWNTIME_COLUMNS["after"])
OEE_OK = "1/30/26,0.6,0.7,0.9,0.99,100,10,200,300,5,6,290,295"
DT_OK = (
    "1/30/26,KK250,MATERIALS,MANUAL BRICK HANDLING,Unplanned,HACKING STATION,-,"
    "2026-01-30 07:54,2026-01-30 07:58,4"
)


def _write(tmp_path, header, *lines):
    p = tmp_path / "f.csv"
    p.write_text(header + "\n" + "\n".join(lines) + "\n", encoding="utf-8")
    return p


def _oee_row(**over):
    cols = list(OEE_COLUMNS["after"].values())
    vals = dict(zip(cols, OEE_OK.split(","), strict=True)) | over
    return ",".join(vals[c] for c in cols)


def _dt_row(**over):
    cols = list(DOWNTIME_COLUMNS["after"].values())
    base = dict(zip(cols, DT_OK.split(","), strict=True))
    return ",".join((base | over)[c] for c in cols)


@pytest.mark.parametrize(
    ("over", "reason"),
    [
        ({"availability": ""}, "missing_required:availability"),
        ({"shift_date": ""}, "missing_required:shift_date"),
        ({"shift_date": "2026-01-30"}, "bad_date:shift_date"),
        ({"oee": "abc"}, "bad_number:oee"),
        ({"good_qty": "nan"}, "bad_number:good_qty"),
        ({"performance": "1.51"}, "out_of_range:performance"),
        ({"quality": "-0.01"}, "out_of_range:quality"),
        ({"total_qty": "-1"}, "out_of_range:total_qty"),
    ],
)
def test_oee_rejection_reasons(tmp_path, over, reason):
    path = _write(tmp_path, OEE_HDR, _oee_row(), _oee_row(**over))
    parsed = parse_brick_oee(path, "after")
    assert len(parsed.rows) == 1
    assert [(r.source_row, r.reason) for r in parsed.rejected] == [(2, reason)]


def test_oee_boundaries_accepted(tmp_path):
    path = _write(
        tmp_path,
        OEE_HDR,
        _oee_row(oee="0", availability="1.5", total_qty="0"),
    )
    parsed = parse_brick_oee(path, "after")
    assert len(parsed.rows) == 1 and parsed.rejected == []


@pytest.mark.parametrize(
    ("over", "reason"),
    [
        ({"product": ""}, "missing_required:product"),
        ({"shift_date": "31/31/26"}, "bad_date:shift_date"),
        ({"start_local": "2026-01-30"}, "bad_date:start_local"),
        ({"end_local": "yesterday"}, "bad_date:end_local"),
        ({"duration_min": "x"}, "bad_number:duration_min"),
        ({"duration_min": "-1"}, "out_of_range:duration_min"),
        ({"end_local": "2026-01-30 07:00"}, "end_before_start"),
    ],
)
def test_downtime_rejection_reasons(tmp_path, over, reason):
    path = _write(tmp_path, DT_HDR, _dt_row(), _dt_row(**over))
    parsed = parse_brick_downtime(path, "after")
    assert len(parsed.rows) == 1
    assert [(r.source_row, r.reason) for r in parsed.rejected] == [(2, reason)]


def test_downtime_boundary_zero_duration_and_equal_times(tmp_path):
    path = _write(
        tmp_path,
        DT_HDR,
        _dt_row(duration_min="0", end_local="2026-01-30 07:54"),
    )
    parsed = parse_brick_downtime(path, "after")
    assert len(parsed.rows) == 1 and parsed.rejected == []


def test_partial_blank_is_missing_required_not_empty_row(tmp_path):
    blank = "," * (len(OEE_COLUMNS["after"]) - 1)
    partial = "1/30/26" + blank
    path = _write(tmp_path, OEE_HDR, blank, partial)
    reasons = [r.reason for r in parse_brick_oee(path, "after").rejected]
    assert reasons == ["empty_row", "missing_required:oee"]


def test_unknown_column_raises_value_error(tmp_path):
    path = _write(tmp_path, OEE_HDR + ",Surprise", OEE_OK + ",1")
    with pytest.raises(ValueError, match="unexpected columns.*Surprise"):
        parse_brick_oee(path, "after")


def test_missing_column_raises_value_error(tmp_path):
    hdr = ",".join(list(OEE_COLUMNS["after"])[:-1])
    path = _write(tmp_path, hdr, OEE_OK.rsplit(",", 1)[0])
    with pytest.raises(ValueError, match="missing columns.*ideal_qty"):
        parse_brick_oee(path, "after")


def test_duplicate_column_raises_value_error(tmp_path):
    path = _write(tmp_path, OEE_HDR + ",OEE", OEE_OK + ",1")
    with pytest.raises(ValueError, match="duplicate columns.*OEE"):
        parse_brick_oee(path, "after")
