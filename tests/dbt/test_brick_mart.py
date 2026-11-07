"""mart.brick_shift_oee: availability recomputed from the stop log against published values."""

import json
from pathlib import Path

import pytest

pytestmark = pytest.mark.db

EXPECTED = json.loads(
    (
        Path(__file__).resolve().parents[1] / "fixtures" / "brick" / "expected_availability.json"
    ).read_text(encoding="utf-8")
)


def mart(conn) -> dict[str, dict]:
    cur = conn.execute("SELECT * FROM mart.brick_shift_oee")
    cols = [d.name for d in cur.description]
    return {r[0]: dict(zip(cols, r, strict=True)) for r in cur.fetchall()}


def test_overlapping_stops_counted_once(built):
    # 2026-02-02: a 12-min stop plus two 10-min stops overlapping by 5 min.
    row = mart(built)["brick:2026-02-02"]
    assert row["stop_s_union"] == 12 * 60 + 15 * 60
    assert row["stop_s_sum"] - row["stop_s_union"] == 5 * 60


def test_not_included_stops_excluded(built):
    # 2026-02-02 also has a 120-min "Planned - Not included in OEE" stop; it must not count.
    row = mart(built)["brick:2026-02-02"]
    assert row["stop_s_sum"] == (12 + 10 + 10) * 60
    # 2025-09-22 starts with a 196-min not-included stop.
    assert mart(built)["brick:2025-09-22"]["stop_s_union"] == 40 * 60


def test_date_without_stops_is_no_stops(built):
    rows = mart(built)
    for shift_id in ("brick:2025-09-24", "brick:2025-09-25", "brick:2026-02-03"):
        row = rows[shift_id]
        assert row["match_status"] == "no_stops"
        assert row["stop_s_union"] == 0
        assert row["availability_calc"] == 1


def test_stops_without_published_row_kept_as_no_published(built):
    row = mart(built)["brick:2026-02-05"]
    assert row["match_status"] == "no_published"
    assert row["planned_s_published"] is None
    assert row["availability_calc"] is None
    assert row["availability_gap"] is None
    assert row["period"] == "after"


def test_date_with_only_not_included_stops_is_kept(built):
    # A no-production day: stops logged, none count in OEE, no published row.
    row = mart(built)["brick:2026-02-09"]
    assert row["match_status"] == "no_published"
    assert row["stop_s_union"] == 0
    assert row["period"] == "after"


def test_stop_crossing_midnight_is_clipped(built):
    # 23:50 to 00:20 next day: only the 10 minutes on the shift date count.
    row = mart(built)["brick:2026-02-05"]
    assert row["stop_s_union"] == 10 * 60
    assert row["stop_s_clipped_off"] == 20 * 60
    assert row["stops_outside_nominal"] == 1
    assert row["stop_s_outside_nominal"] == 10 * 60


def test_availability_matches_hand_calc(built):
    rows = mart(built)
    assert set(rows) == set(EXPECTED)
    for shift_id, exp in EXPECTED.items():
        row = rows[shift_id]
        for col in ("period", "match_status"):
            assert row[col] == exp[col], (shift_id, col)
        for col in ("stop_s_union", "stop_s_sum", "planned_s_published"):
            assert row[col] == exp[col], (shift_id, col)
        for col in ("availability_calc", "availability_gap"):
            if exp[col] is None:
                assert row[col] is None, (shift_id, col)
            else:
                assert float(row[col]) == pytest.approx(exp[col], abs=1e-9), (shift_id, col)


def test_published_components_carried_and_oee_uses_calc_availability(built):
    row = mart(built)["brick:2025-09-23"]
    assert float(row["availability_pub"]) == pytest.approx(0.6236)
    assert float(row["performance_pub"]) == pytest.approx(0.9447)
    assert float(row["quality_pub"]) == pytest.approx(0.9975)
    assert float(row["oee_calc_with_pub_pq"]) == pytest.approx(
        float(row["availability_calc"]) * 0.9447 * 0.9975, abs=1e-12
    )
    assert float(row["oee_gap"]) == pytest.approx(float(row["oee_calc_with_pub_pq"]) - 0.5891)
    # Stop time implied by the published run time (planned - good - slow production seconds).
    assert row["stop_s_implied_pub"] == 29700 - 17398 - 1123


def test_duplicate_published_date_rejected_not_doubled(built):
    n = built.execute(
        "SELECT count(*) FROM raw.rejected WHERE reason = 'duplicate_shift'"
    ).fetchone()[0]
    assert n == 1
    assert float(mart(built)["brick:2025-09-26"]["availability_pub"]) == pytest.approx(0.70)
