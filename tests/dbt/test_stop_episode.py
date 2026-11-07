"""mart.stop_episode built by dbt on the fixture.

PIADE fixture stops: s_1 12:25-12:50 (A_012 then A_047, contiguous), s_1 16:45:28 (A_012);
s_2 12:40 (A_101), then 15:16:00, 15:21:04 (4 s gap) and 15:26:10 (6 s gap); s_3 07:00."""

import pytest

pytestmark = pytest.mark.db


def rows(conn, sql, *params) -> list[dict]:
    cur = conn.execute(sql, params)
    cols = [d.name for d in cur.description]
    return [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]


def episodes(conn, machine: str) -> list[dict]:
    return rows(
        conn,
        "SELECT * FROM mart.stop_episode WHERE machine_id = %s ORDER BY start_ts",
        machine,
    )


def test_episode_merge_gap(built):
    eps = episodes(built, "s_2")
    assert [e["start_ts"].strftime("%H:%M:%S") for e in eps] == ["12:40:00", "15:16:00", "15:26:10"]
    merged = eps[1]
    # 4 s gap merged: two intervals, duration is the sum (600), not end - start (604).
    assert merged["end_ts"].strftime("%H:%M:%S") == "15:26:04"
    assert float(merged["duration_s"]) == 600
    assert len(merged["event_ids"]) == 2
    assert merged["reason"] == "A_101"  # alarm of the first interval
    assert sorted(merged["alarm_codes"]) == ["A_005", "A_101"]
    # 6 s gap: a new episode.
    assert float(eps[2]["duration_s"]) == 300 and len(eps[2]["event_ids"]) == 1


def test_contiguous_stops_merge_and_take_first_alarm(built):
    eps = episodes(built, "s_1")
    assert len(eps) == 2
    first = eps[0]
    assert float(first["duration_s"]) == 900 + 600
    assert first["reason"] == "A_012" and sorted(first["alarm_codes"]) == ["A_012", "A_047"]
    assert first["shift_id"] == "piade:s_1:2020-01-01T06"
    assert first["in_oee"] and first["is_failure"]
    assert first["source_system"] == "piade" and first["line_id"] == "s_1"
    assert first["reason_detail"] is None and first["location"] is None


def test_piade_episode_seconds_match_stopped_events(built):
    got = dict(
        built.execute(
            "SELECT machine_id, sum(duration_s) FROM mart.stop_episode "
            "WHERE source_system = 'piade' GROUP BY 1"
        ).fetchall()
    )
    want = dict(
        built.execute(
            "SELECT machine_id, sum(duration_s) FROM core.event "
            "WHERE source_system = 'piade' AND state = 'stopped' GROUP BY 1"
        ).fetchall()
    )
    assert got == want and set(got) == {"s_1", "s_2", "s_3"}


def test_brick_one_episode_per_stop(built):
    (n_ep,) = built.execute(
        "SELECT count(*) FROM mart.stop_episode WHERE source_system = 'brick'"
    ).fetchone()
    (n_ev,) = built.execute(
        "SELECT count(*) FROM core.event WHERE source_system = 'brick' AND event_type = 'stop'"
    ).fetchone()
    assert n_ep == n_ev > 0
    (ep,) = rows(
        built,
        """SELECT s.*, e.reason_code, e.reason_text, e.stop_type AS ev_stop_type
           FROM mart.stop_episode s JOIN core.event e ON e.event_id = s.event_ids[1]
           WHERE s.source_system = 'brick' AND s.reason_detail = 'KILN CAR DERAILMENT'""",
    )
    assert ep["reason"] == ep["reason_code"] == "FAILURE" and ep["is_failure"]
    assert ep["machine_id"] is None and ep["line_id"] == "brick"
    assert ep["shift_id"] == "brick:2026-02-05" and float(ep["duration_s"]) == 1800
    (not_in,) = built.execute(
        "SELECT count(*) FROM mart.stop_episode WHERE source_system = 'brick' AND NOT in_oee"
    ).fetchone()
    assert not_in == 3
    (ids,) = built.execute(
        "SELECT array_agg(episode_id ORDER BY episode_id) FROM mart.stop_episode"
    ).fetchone()
    assert ids == list(range(1, len(ids) + 1))
