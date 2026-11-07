from pathlib import Path

import pytest

from linecopilot.ingest.piade import parse_piade_raw, piade_quality_report

FIX = Path(__file__).parent.parent / "fixtures" / "piade" / "raw_small.csv"
HEADER = "interval_start,equipment_ID,alarm,type,start,end,elapsed,pi,po,speed"
GOOD = (
    "2020-01-01 12:00:00+00:00,s_1,A_000,production,1577880000.000,1577880600.000,600000,10,9,4000"
)


def write(tmp_path, *lines, header=HEADER):
    p = tmp_path / "raw.csv"
    p.write_text("\n".join([header, *lines]) + "\n")
    return p


def row(**over):
    cols = HEADER.split(",")
    vals = dict(zip(cols, GOOD.split(","), strict=True)) | {k: str(v) for k, v in over.items()}
    return ",".join(vals[c] for c in cols)


def test_fixture_parses_clean():
    parsed = parse_piade_raw(FIX)
    assert len(parsed.rows) == 36
    assert parsed.rejected == []
    assert parsed.source_rows == list(range(1, 37))
    assert set(parsed.rows[0]) == {
        "machine_id", "alarm", "state", "start_utc", "end_utc",
        "elapsed_ms", "pi", "po", "speed",
    }  # fmt: skip


def test_a000_becomes_none():
    parsed = parse_piade_raw(FIX)
    by_state = {r["state"]: r for r in parsed.rows}
    assert by_state["production"]["alarm"] is None
    assert by_state["idle"]["alarm"] is None
    downtime = [r for r in parsed.rows if r["state"] == "downtime"]
    assert [r["alarm"] for r in downtime] == ["A_012", "A_047", "A_012", "A_101", "A_012"]


def test_elapsed_is_ms():
    first = parse_piade_raw(FIX).rows[0]
    assert first["elapsed_ms"] == "600000"
    assert first["start_utc"] == "2020-01-01T12:00:00.000Z"
    assert first["end_utc"] == "2020-01-01T12:10:00.000Z"
    assert first["machine_id"] == "s_1"
    assert first["pi"] == "100" and first["po"] == "95" and first["speed"] == "4000"


def test_frame_matches_rows():
    parsed = parse_piade_raw(FIX)
    assert parsed.frame is not None
    assert len(parsed.frame) == len(parsed.rows)
    assert parsed.frame.iloc[3]["alarm"] == "A_012"
    assert parsed.frame.iloc[0]["alarm"] is None


def test_frame_keeps_original_start_end_strings():
    parsed = parse_piade_raw(FIX)
    assert parsed.frame.iloc[0]["start_raw"] == "1577880000.000"
    assert parsed.frame.iloc[0]["end_raw"] == "1577880600.000"
    assert "start_raw" not in parsed.rows[0]


def test_elapsed_mismatch_rejected(tmp_path):
    ok = row()
    bad = row(elapsed=600006)
    edge = row(elapsed=600005)
    parsed = parse_piade_raw(write(tmp_path, ok, bad, edge))
    assert [(r.source_row, r.reason) for r in parsed.rejected] == [(2, "elapsed_mismatch")]
    assert parsed.source_rows == [1, 3]
    assert len(parsed.rows) == 2


def test_unknown_state_rejected(tmp_path):
    parsed = parse_piade_raw(write(tmp_path, row(), row(type="maintenance")))
    assert [(r.source_row, r.reason) for r in parsed.rejected] == [(2, "unknown_state")]
    assert parsed.rejected[0].raw["type"] == "maintenance"
    assert len(parsed.rows) == 1


def test_downtime_without_alarm_rejected(tmp_path):
    parsed = parse_piade_raw(write(tmp_path, row(), row(type="downtime", alarm="A_000")))
    assert [(r.source_row, r.reason) for r in parsed.rejected] == [(2, "downtime_without_alarm")]
    assert len(parsed.rows) == 1


def test_alarm_outside_downtime_rejected(tmp_path):
    parsed = parse_piade_raw(write(tmp_path, row(), row(type="idle", alarm="A_012")))
    assert [(r.source_row, r.reason) for r in parsed.rejected] == [(2, "alarm_outside_downtime")]
    assert len(parsed.rows) == 1


@pytest.mark.parametrize("col", ["equipment_ID", "alarm", "type", "start", "end", "elapsed",
                                 "pi", "po", "speed"])  # fmt: skip
def test_missing_required_rejected(tmp_path, col):
    parsed = parse_piade_raw(write(tmp_path, row(), row(**{col: ""})))
    assert [(r.source_row, r.reason) for r in parsed.rejected] == [(2, f"missing_required:{col}")]
    assert len(parsed.rows) == 1


@pytest.mark.parametrize("col", ["start", "end", "elapsed", "pi", "po", "speed"])
def test_bad_number_rejected(tmp_path, col):
    parsed = parse_piade_raw(write(tmp_path, row(), row(**{col: "abc"})))
    assert [(r.source_row, r.reason) for r in parsed.rejected] == [(2, f"bad_number:{col}")]
    assert len(parsed.rows) == 1


def test_nan_and_inf_are_bad_numbers(tmp_path):
    parsed = parse_piade_raw(write(tmp_path, row(pi="nan"), row(po="inf")))
    assert [(r.source_row, r.reason) for r in parsed.rejected] == [
        (1, "bad_number:pi"),
        (2, "bad_number:po"),
    ]
    assert parsed.rows == []


@pytest.mark.parametrize("col", ["elapsed", "pi", "po", "speed"])
def test_negative_rejected(tmp_path, col):
    parsed = parse_piade_raw(write(tmp_path, row(), row(**{col: -1})))
    assert [(r.source_row, r.reason) for r in parsed.rejected] == [(2, f"out_of_range:{col}")]
    assert len(parsed.rows) == 1


def test_end_before_start_rejected(tmp_path):
    bad = row(start="1577880600.000", end="1577880000.000", elapsed=0)
    parsed = parse_piade_raw(write(tmp_path, row(), bad))
    assert [(r.source_row, r.reason) for r in parsed.rejected] == [(2, "end_before_start")]
    assert len(parsed.rows) == 1


def test_empty_row_rejected(tmp_path):
    parsed = parse_piade_raw(write(tmp_path, row(), ",,,,,,,,,", row()))
    assert [(r.source_row, r.reason) for r in parsed.rejected] == [(2, "empty_row")]
    assert parsed.source_rows == [1, 3]


def test_first_failing_rule_wins(tmp_path):
    parsed = parse_piade_raw(write(tmp_path, row(type="nope", alarm="A_012", elapsed=1)))
    assert [r.reason for r in parsed.rejected] == ["unknown_state"]


def test_unknown_column_raises(tmp_path):
    p = write(tmp_path, GOOD + ",x", header=HEADER + ",extra")
    with pytest.raises(ValueError, match=r"unexpected columns \['extra'\]"):
        parse_piade_raw(p)


def test_missing_column_raises(tmp_path):
    p = write(tmp_path, "a,b", header="interval_start,equipment_ID")
    with pytest.raises(ValueError, match="missing columns"):
        parse_piade_raw(p)


def test_empty_file_raises(tmp_path):
    p = tmp_path / "raw.csv"
    p.write_text("")
    with pytest.raises(ValueError, match="empty file"):
        parse_piade_raw(p)


def test_quality_report_counts():
    report = piade_quality_report(parse_piade_raw(FIX))
    assert report == {
        "s_1": {
            "rows": 18,
            "gaps_over_60s": 1,
            "max_gap_s": 7200.0,
            "overlaps_over_1s": 1,
            "counter_resets_pi": 1,
            "counter_resets_po": 2,
        },
        "s_2": {
            "rows": 14,
            "gaps_over_60s": 2,
            "max_gap_s": 3600.0,
            "overlaps_over_1s": 0,
            "counter_resets_pi": 1,  # the glitch jump back down
            "counter_resets_po": 0,
        },
        "s_3": {
            "rows": 4,
            "gaps_over_60s": 0,
            "max_gap_s": 0.0,
            "overlaps_over_1s": 0,
            "counter_resets_pi": 0,
            "counter_resets_po": 0,
        },
    }


def test_quality_report_uses_start_order_not_file_order(tmp_path):
    a = row(start="1577880000.000", end="1577880600.000", pi=50)
    b = row(start="1577880600.000", end="1577881200.000", pi=60)
    parsed = parse_piade_raw(write(tmp_path, b, a))
    assert piade_quality_report(parsed)["s_1"]["counter_resets_pi"] == 0
