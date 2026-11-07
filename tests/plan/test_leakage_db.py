"""Replay leakage: nothing a plan is built from may come from the replay period."""

from datetime import UTC, datetime, timedelta

import psycopg
import pytest

from linecopilot import schemas
from linecopilot.plan import replay
from linecopilot.plan.load import load_problem, problem_from_synth
from linecopilot.synth import anchors as anchors_mod
from linecopilot.synth.anchors import CUTOFF, load_anchors
from linecopilot.synth.generate import generate, write

pytestmark = pytest.mark.db


def test_anchor_queries_are_bounded_by_the_cutoff():
    for sql in (anchors_mod.RATE_SQL, anchors_mod.COVERED_SQL, anchors_mod.STOPPED_SQL):
        assert "start_ts < %(cutoff)s" in sql
    assert CUTOFF.isoformat().startswith("2021-07-01")


def test_every_window_starts_on_or_after_the_cutoff_and_none_overlap():
    ws = replay.windows()
    assert len(ws) == 8
    assert all(w.start >= CUTOFF for w in ws)
    assert all(a.end <= b.start for a, b in zip(ws, ws[1:], strict=False))
    assert all(replay.WINDOW_DAYS == (w.end - w.start).days for w in ws)


def test_plan_inputs_do_not_change_when_replay_period_rows_are_added(db_url, built):
    """The fixture has no PIADE rows after the cutoff, so add a 30-minute stop on 2021-07-02
    (rolled back): the replay sees it, while anchors and the problem built from them are
    identical. Planning cannot see the period it is tested on."""
    schemas.apply(built)
    before_anchors = load_anchors(built)
    before_problem = problem_from_synth(generate(before_anchors, 7))
    w = replay.windows()[0]
    assert replay.stops(built, w) == {}
    t0 = datetime(2021, 7, 2, 10, 0, tzinfo=UTC)
    t1 = t0 + timedelta(minutes=30)
    with psycopg.connect(db_url) as c:
        c.execute(
            "insert into mart.piade_interval_counts "
            "(machine_id, source_state, start_ts, end_ts, duration_s, speed) "
            "values ('s_1', 'stopped', %s, %s, 1800, 0)",
            (t0, t1),
        )
        c.execute(
            "insert into mart.stop_episode "
            "(episode_id, source_system, machine_id, start_ts, end_ts, duration_s) "
            "values (-1, 'piade', 's_1', %s, %s, 1800)",
            (t0, t1),
        )
        after_anchors = load_anchors(c)
        after_problem = problem_from_synth(generate(after_anchors, 7))
        got = replay.stops(c, w)
        stats = replay.window_stats(c, w, ["s_1"])
        c.rollback()
    assert got == {"s_1": [(1440 + 600, 1440 + 630)]}
    assert stats["s_1"]["stopped_share"] == pytest.approx(30 / w.minutes)
    # same denominator as planning availability: stopped over covered time (only the 30 stopped
    # minutes are covered here), and the no-data share is everything else
    assert stats["s_1"]["stopped_share_of_covered"] == pytest.approx(1.0)
    assert stats["s_1"]["no_data_share"] == pytest.approx(1 - 30 / w.minutes)
    assert after_anchors == before_anchors
    assert after_problem.machines == before_problem.machines
    assert after_problem.jobs == before_problem.jobs


def test_problem_from_synth_matches_the_loaded_problem(built):
    schemas.apply(built)
    a = load_anchors(built)
    data = generate(a, 7)
    write(built, data, a, 7)
    db, mem = load_problem(built), problem_from_synth(data)
    assert mem.jobs == db.jobs and mem.machines == db.machines and mem.blocked == db.blocked
    for j in db.jobs[:5]:
        k = db.jobs[-1]
        assert mem.changeover(j.family, j.product_id, k.family, k.product_id) == db.changeover(
            j.family, j.product_id, k.family, k.product_id
        )


def test_window_stats_and_stops_on_the_fixture(built):
    machines = [
        r[0]
        for r in built.execute(
            "select distinct machine_id from core.event where source_system='piade'"
        )
    ]
    for w in replay.windows():
        st = replay.stops(built, w)
        for ms in st.values():
            assert all(0 <= a < b <= w.minutes for a, b in ms)
            assert all(b < c for (_, b), (c, _) in zip(ms, ms[1:], strict=False))
        stats = replay.window_stats(built, w, machines)
        assert set(stats) == set(machines)
        assert all(
            0 <= v["stopped_share"] <= 1 and 0 <= v["no_data_share"] <= 1 for v in stats.values()
        )
