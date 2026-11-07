"""PIADE counter deltas, shift split and OEE marts, built by dbt on the fixture.

Counter rules live in dbt SQL (mart.piade_interval_counts): the delta x[i] - x[i-1] belongs
to row i (end alignment, chosen by scripts/probe_piade_counts.py); a negative delta is a
reset and a delta above 3 x max speed x row hours is a glitch, both null.
"""

from datetime import date

import pytest

pytestmark = pytest.mark.db


def rows(conn, sql, *params) -> list[dict]:
    cur = conn.execute(sql, params)
    cols = [d.name for d in cur.description]
    return [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]


def interval(conn, machine: str, start: str) -> dict:
    (row,) = rows(
        conn,
        "SELECT * FROM mart.piade_interval_counts WHERE machine_id = %s"
        " AND start_ts = %s::timestamptz",
        machine,
        start,
    )
    return row


def shift(conn, shift_id: str) -> dict:
    (row,) = rows(conn, "SELECT * FROM mart.piade_shift_oee WHERE shift_id = %s", shift_id)
    return row


def test_reset_gives_none(built):
    # s_1 15:45: pi 260 -> 40 and po 240 -> 30 after scheduled downtime.
    row = interval(built, "s_1", "2020-01-01 15:45:00+00")
    assert row["pi_delta"] is None and row["pi_flag"] == "reset"
    assert row["po_delta"] is None and row["po_flag"] == "reset"
    # The next row counts again from the new base.
    nxt = interval(built, "s_1", "2020-01-01 15:55:00+00")
    assert nxt["pi_delta"] == 50 and nxt["pi_flag"] == "ok"


def test_glitch_gives_none(built):
    # s_2 12:20: pi jumps to 340,000,000 in a 10-minute row (limit 3 x 6000 x 1/6 = 3000).
    row = interval(built, "s_2", "2020-01-01 12:20:00+00")
    assert row["pi_delta"] is None and row["pi_flag"] == "glitch"
    assert float(row["glitch_limit"]) == pytest.approx(3000)
    assert row["po_delta"] == 40 and row["po_flag"] == "ok"
    # The jump back down is a negative delta, so a reset, also null.
    back = interval(built, "s_2", "2020-01-01 12:30:00+00")
    assert back["pi_delta"] is None and back["pi_flag"] == "reset"
    # No surviving delta anywhere is negative or above its limit.
    bad = built.execute(
        "SELECT count(*) FROM mart.piade_interval_counts"
        " WHERE pi_delta < 0 OR po_delta < 0"
        " OR pi_delta > glitch_limit OR po_delta > glitch_limit"
    ).fetchone()[0]
    assert bad == 0


def test_alignment_start_vs_end(built):
    first = interval(built, "s_1", "2020-01-01 12:00:00+00")
    second = interval(built, "s_1", "2020-01-01 12:10:00+00")
    # End alignment (used): x[i] - x[i-1]; the first row of a machine has no delta.
    assert first["pi_delta"] is None and first["pi_flag"] == "none"
    assert second["pi_delta"] == 150 - 100
    # Start alignment (kept for comparison only): x[i+1] - x[i].
    assert first["pi_delta_start"] == 150 - 100
    assert second["pi_delta_start"] == 170 - 150
    last = interval(built, "s_1", "2020-01-01 16:50:28+00")
    assert last["pi_delta_start"] is None


def test_interval_split_across_shift(built):
    # s_3 05:00-07:00 UTC production (pi +6000, po +5900) crosses the 06:00 boundary.
    night = shift(built, "piade:s_3:2020-01-01T22")
    day = shift(built, "piade:s_3:2020-01-02T06")
    # Night: 04:00-05:00 (first row, no counter delta) + 1 h of the split row.
    assert float(night["production_s"]) == 3600 + 3600
    assert float(night["input_qty"]) == 3000
    assert float(night["output_qty"]) == 2950
    # Day: 1 h of the split row + 30 min downtime + 30 min production.
    assert float(day["production_s"]) == 3600 + 1800
    assert float(day["downtime_s"]) == 1800
    assert float(day["planned_s"]) == 7200
    assert float(day["input_qty"]) == 3000 + 5000
    assert float(day["output_qty"]) == 2950 + 4990
    # Seconds are conserved by the split.
    total = built.execute(
        "SELECT sum(planned_s + scheduled_s) FROM mart.piade_shift_oee WHERE machine_id = 's_3'"
    ).fetchone()[0]
    assert float(total) == 3600 + 7200 + 1800 + 1800 + 3600 + 21600  # + the 6 h stop on 2020-02-01


def test_overlap_clipped_to_previous_end(built):
    # s_1 16:04:58-16:09:58 starts 2 s before the previous row ends (16:05:00).
    (row,) = rows(
        built,
        "SELECT * FROM mart.piade_interval_counts WHERE machine_id = 's_1'"
        " AND start_ts_source = '2020-01-01 16:04:58+00'",
    )
    assert row["start_ts"].isoformat() == "2020-01-01T16:05:00+00:00"
    assert float(row["duration_s"]) == 298
    assert float(row["clipped_s"]) == 2
    total = built.execute(
        "SELECT sum(planned_s + scheduled_s) FROM mart.piade_shift_oee"
        " WHERE shift_id = 'piade:s_1:2020-01-01T14'"
    ).fetchone()[0]
    assert float(total) == 5100 - 2 + 1800


def test_run_without_input_excluded_from_counts(built):
    # s_3 14:00-15:00 performance_loss, counters unchanged: ran, counted nothing.
    zero = shift(built, "piade:s_3:2020-01-02T14")
    assert float(zero["run_s"]) == 3600 and float(zero["input_qty"]) == 0
    assert zero["quality_reason"] == "no_input"
    assert zero["performance_count_p95"] is None and zero["quality"] is None
    assert zero["oee"] is None
    (month,) = rows(
        built,
        "SELECT * FROM mart.piade_machine_oee WHERE machine_id = 's_3' AND month = %s",
        date(2020, 1, 1),
    )
    assert float(month["run_s"]) == 7200 + 5400 + 3600
    assert float(month["run_s_counted"]) == 7200 + 5400
    assert month["n_shifts_counts_excluded"] == 1
    assert float(month["performance_count_p95_raw"]) == pytest.approx(11000 / (4800 * 3.5))


def test_performance_capped_and_counted(built):
    day = shift(built, "piade:s_3:2020-01-02T06")
    # 8000 in over 1.5 run hours at an ideal 4800/h = 1.111, capped at 1.
    assert float(day["performance_count_p95_raw"]) == pytest.approx(8000 / 7200)
    assert float(day["performance_count_p95"]) == 1.0
    assert day["n_capped"] == 1
    assert float(day["availability"]) == pytest.approx(5400 / 7200)
    assert float(day["quality"]) == pytest.approx(7940 / 8000)
    assert float(day["oee"]) == pytest.approx(0.75 * 1.0 * 7940 / 8000)
    night = shift(built, "piade:s_3:2020-01-01T22")
    assert night["n_capped"] == 0
    assert float(night["performance_count_p95"]) == pytest.approx(3000 / 9600)


def test_quality_null_when_pi_glitchy(built):
    glitchy = shift(built, "piade:s_2:2020-01-01T06")
    assert glitchy["quality"] is None
    assert glitchy["quality_reason"] == "pi_glitch"
    assert glitchy["performance_count_p95"] is None
    assert glitchy["oee"] is None
    assert glitchy["availability"] is not None
    # A clean shift: run-row deltas 50 + 20 + 50 in, 45 + 20 + 45 out.
    clean = shift(built, "piade:s_1:2020-01-01T06")
    assert clean["quality_reason"] is None
    assert float(clean["input_qty"]) == 120
    assert float(clean["output_qty"]) == 110
    assert float(clean["quality"]) == pytest.approx(110 / 120)
    assert float(clean["availability"]) == pytest.approx(2100 / 3900)
    assert float(clean["performance_time"]) == pytest.approx(1800 / 2100)


def test_rollup_is_time_weighted(built):
    shifts = rows(
        built,
        "SELECT availability FROM mart.piade_shift_oee WHERE machine_id = 's_1'"
        " AND shift_start >= '2020-01-01' AND shift_start < '2020-02-01'",
    )
    assert len(shifts) == 2
    (month,) = rows(
        built,
        "SELECT * FROM mart.piade_machine_oee WHERE machine_id = 's_1' AND month = %s",
        date(2020, 1, 1),
    )
    # Run 2100 + 4500 s over planned 3900 + 5100 s, less the 2 s overlap clipped off the
    # 16:04:58 performance_loss row.
    assert float(month["availability"]) == pytest.approx(6598 / 8998)
    mean_of_shifts = sum(float(s["availability"]) for s in shifts) / 2
    assert float(month["availability"]) != pytest.approx(mean_of_shifts)
    assert float(month["planned_s"]) == 8998


def test_ideal_rate_ignores_zero_speed(built):
    rate = {r["machine_id"]: r for r in rows(built, "SELECT * FROM mart.piade_ideal_rate")}
    assert set(rate) == {"s_1", "s_2", "s_3"}
    assert float(rate["s_3"]["p95"]) == 4800
    assert float(rate["s_3"]["max_speed"]) == 4800
    assert float(rate["s_1"]["p90"]) == 4000


def test_ratios_within_bounds(built):
    bad = built.execute(
        "SELECT count(*) FROM mart.piade_shift_oee WHERE availability NOT BETWEEN 0 AND 1"
        " OR quality NOT BETWEEN 0 AND 1 OR performance_count_p95 NOT BETWEEN 0 AND 1"
        " OR oee NOT BETWEEN 0 AND 1"
    ).fetchone()[0]
    assert bad == 0
