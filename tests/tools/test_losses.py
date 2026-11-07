"""Loss tools (Pareto, breakdown, repeat failures) against the fixture database."""

from datetime import UTC, datetime

import pytest

from linecopilot.tools.envelope import CITATION_CAP
from linecopilot.tools.losses import (
    BreakdownArgs,
    LossParetoArgs,
    RepeatArgs,
    breakdown,
    loss_pareto,
    repeat_failures,
)

pytestmark = pytest.mark.db


def assert_citations_in_scope(conn, r, line_id: str, start=None, end=None):
    """Every citation resolves to a core.event row of the scope, inside the window, and
    to the raw row it names."""
    assert r.citations and len(r.citations) <= CITATION_CAP
    for c in r.citations:
        ev = conn.execute(
            "SELECT line_id, raw_table, source_file, raw_row_ids FROM core.event "
            "WHERE event_id = %s",
            (c.event_id,),
        ).fetchone()
        assert ev is not None
        assert ev[0] == line_id
        assert (ev[1], ev[2]) == (c.raw_table, c.source_file) and c.raw_row_id in ev[3]
    # The cited events' episodes start inside the window.
    eids = [c.event_id for c in r.citations]
    lo, hi = conn.execute(
        "SELECT min(start_ts), max(start_ts) FROM mart.stop_episode "
        "WHERE event_ids && %s::bigint[]",
        (eids,),
    ).fetchone()
    if start is not None:
        assert lo >= start
    if end is not None:
        assert hi < end


def test_pareto_shares_sum_to_one(built):
    for args in (
        LossParetoArgs(line_id="brick", by="reason_detail", top=2),
        LossParetoArgs(line_id="brick", by="reason", include_not_in_oee=True),
        LossParetoArgs(machine_id="s_2", by="alarm", top=1),
    ):
        r = loss_pareto(built, args)
        assert r.status == "ok", r.missing
        d = r.data
        total = sum(row.share for row in d.rows) + d.other_lost_s / d.total_lost_s
        assert total == pytest.approx(1, abs=1e-9)
        cums = [row.cumulative_share for row in d.rows]
        assert cums == sorted(cums) and cums[-1] <= 1 + 1e-12
        assert len(d.rows) <= args.top
        assert sum(row.lost_s for row in d.rows) + d.other_lost_s == pytest.approx(d.total_lost_s)


def test_pareto_brick_matches_sql(built):
    r = loss_pareto(built, LossParetoArgs(line_id="brick", by="reason"))
    assert r.status == "ok"
    want = {
        k: (float(s), n)
        for k, s, n in built.execute(
            """SELECT reason_code, sum(extract(epoch FROM end_ts - start_ts)), count(*)
               FROM core.event
               WHERE source_system = 'brick' AND event_type = 'stop'
                 AND stop_type <> 'Planned - Not included in OEE'
               GROUP BY 1"""
        ).fetchall()
    }
    got = {row.category: (row.lost_s, row.stop_count) for row in r.data.rows}
    assert set(got) == set(want)
    for k, (lost, n) in want.items():
        assert got[k][0] == pytest.approx(lost) and got[k][1] == n
    assert [row.lost_s for row in r.data.rows] == sorted(
        (row.lost_s for row in r.data.rows), reverse=True
    )
    assert r.data.other_lost_s == 0
    # Each row cites exactly its own category's stop events.
    for row in r.data.rows:
        reasons = {
            x
            for (x,) in built.execute(
                "SELECT reason_code FROM core.event WHERE event_id = ANY(%s)",
                ([c.event_id for c in row.citations],),
            ).fetchall()
        }
        assert reasons == {row.category}
        assert row.citation_count == want[row.category][1]
    assert r.citation_count == sum(n for _, n in want.values())
    assert_citations_in_scope(built, r, "brick")
    assert any("FAILURE" in a or "failure" in a for a in r.assumptions)


def test_pareto_piade_shift_and_window(built):
    start = datetime(2020, 1, 1, 14, tzinfo=UTC)
    end = datetime(2020, 1, 2, tzinfo=UTC)
    r = loss_pareto(built, LossParetoArgs(machine_id="s_2", by="shift", start=start, end=end))
    assert r.status == "ok"
    assert [(row.category, row.lost_s, row.stop_count) for row in r.data.rows] == [
        ("B 14-22", 900, 2)
    ]
    assert_citations_in_scope(built, r, "s_2", start, end)
    assert any("idle" in a for a in r.assumptions)


def test_pareto_invalid_dim_for_piade(built):
    r = loss_pareto(built, LossParetoArgs(machine_id="s_1", by="location"))
    assert r.status == "out_of_scope"
    assert "location" in r.missing
    for dim in ("reason", "alarm", "shift"):
        assert dim in r.missing
    r = loss_pareto(built, LossParetoArgs(line_id="brick", by="alarm"))
    assert r.status == "out_of_scope" and "reason_detail" in r.missing


def test_pareto_empty_window(built):
    r = loss_pareto(
        built,
        LossParetoArgs(line_id="brick", by="reason", start="2015-01-01", end="2015-02-01"),
    )
    assert r.status == "insufficient_evidence" and r.data is None
    assert "coverage is" in r.missing
    assert r.window.line_id == "brick"


def test_pareto_unknown_machine(built):
    r = loss_pareto(built, LossParetoArgs(machine_id="s_99", by="reason"))
    assert r.status == "out_of_scope"


def test_breakdown_cells_sum_to_total(built):
    r = breakdown(built, BreakdownArgs(line_id="brick", rows="reason", cols="month", top=2))
    assert r.status == "ok", r.missing
    d = r.data
    assert sum(c.lost_s for c in d.cells) == pytest.approx(d.total_lost_s)
    assert sum(c.stop_count for c in d.cells) == d.total_stop_count
    (want,) = built.execute(
        """SELECT sum(extract(epoch FROM end_ts - start_ts)) FROM core.event
           WHERE source_system = 'brick' AND event_type = 'stop'
             AND stop_type <> 'Planned - Not included in OEE'"""
    ).fetchone()
    assert d.total_lost_s == pytest.approx(float(want))
    assert len(d.row_keys) <= 3 and "other" in d.row_keys  # 4 reasons, top 2 + other
    assert len({(c.row, c.col) for c in d.cells}) == len(d.cells)
    assert_citations_in_scope(built, r, "brick")


def test_breakdown_piade_and_invalid(built):
    r = breakdown(built, BreakdownArgs(machine_id="s_2", rows="alarm", cols="shift_slot"))
    assert r.status == "ok"
    cells = {(c.row, c.col): (c.lost_s, c.stop_count) for c in r.data.cells}
    assert cells == {("A_101", "A 06-14"): (600, 1), ("A_101", "B 14-22"): (900, 2)}
    assert_citations_in_scope(built, r, "s_2")
    bad = breakdown(built, BreakdownArgs(machine_id="s_2", rows="location", cols="month"))
    assert bad.status == "out_of_scope" and "shift_slot" in bad.missing
    same = breakdown(built, BreakdownArgs(line_id="brick", rows="month", cols="month"))
    assert same.status == "out_of_scope"


def test_repeat_failures_piade(built):
    r = repeat_failures(built, RepeatArgs(machine_id="s_2"))
    assert r.status == "ok"
    (chain,) = r.data.chains
    assert chain.machine_id == "s_2" and chain.key == "A_101" and chain.count == 3
    assert chain.lost_s == 600 + 600 + 300
    assert len(chain.episode_ids) == 3
    assert chain.citation_count == 4  # the merged episode has two intervals
    assert_citations_in_scope(built, r, "s_2")
    none = repeat_failures(built, RepeatArgs(machine_id="s_2", within_hours=1))
    assert none.status == "ok" and none.data.chains == []


def test_repeat_failures_brick_detail(built):
    r = repeat_failures(
        built, RepeatArgs(line_id="brick", key="reason_detail", min_repeats=2, within_hours=24)
    )
    assert r.status == "ok"
    keys = {(c.key, c.count) for c in r.data.chains}
    # CUTTER JAM 2025-09-22 12:00-12:20 then 09-23 09:00; and 2026-02-02 09:00 then 10:05.
    assert ("CUTTER JAM", 2) in keys
    assert all(c.machine_id is None for c in r.data.chains)
    assert_citations_in_scope(built, r, "brick")
    bad = repeat_failures(built, RepeatArgs(machine_id="s_2", key="reason_detail"))
    assert bad.status == "out_of_scope" and "alarm" in bad.missing
