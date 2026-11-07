"""reliability, compare_periods and get_events against the fixture database."""

from datetime import UTC, datetime

import pytest

from linecopilot.tools.envelope import CITATION_CAP
from linecopilot.tools.events import GetEventsArgs, get_events
from linecopilot.tools.oee import GetOeeArgs, get_oee
from linecopilot.tools.registry import call_tool
from linecopilot.tools.reliability import (
    CompareArgs,
    ReliabilityArgs,
    compare_periods,
    reliability,
)

pytestmark = pytest.mark.db


def test_mttr_mtbf_hand_computed(built):
    # s_2 fixture: stops A_101 600 s, A_101 300 s + A_005 300 s (4 s apart, one episode),
    # A_101 300 s = 3 episodes, 1500 s; running intervals total 6300 s.
    r = reliability(built, ReliabilityArgs(machine_id="s_2"))
    assert r.status == "ok", r.missing
    (row,) = r.data.rows
    assert row.period == "all"
    assert (row.failure_count, row.stop_count) == (3, 3)
    assert row.failure_s == 1500 and row.run_s == 6300
    assert row.mttr_s == 500 and row.mtbf_s == 2100
    assert 0 < len(r.citations) <= CITATION_CAP and row.citation_count == r.citation_count
    assert any("MTBF" in a for a in r.assumptions)

    # Brick: 7 in-OEE failure stops, 6720 s; run = published planned 217684 s minus the
    # union of in-OEE stop seconds 7920 s.
    r = reliability(built, ReliabilityArgs(line_id="brick"))
    (row,) = r.data.rows
    assert row.failure_count == 7 and row.failure_s == 6720
    assert row.mttr_s == pytest.approx(960)
    assert row.run_s == 217684 - 7920
    assert row.mtbf_s == pytest.approx((217684 - 7920) / 7)
    assert row.stop_count == 14  # in-OEE stops: 17 episodes less 3 not in OEE
    assert any("union" in a for a in r.assumptions)

    r = reliability(built, ReliabilityArgs(line_id="brick", group="month"))
    by = {x.period: x for x in r.data.rows}
    assert set(by) == {"2025-09", "2026-01", "2026-02"}
    assert (by["2025-09"].failure_count, by["2025-09"].failure_s) == (3, 3000)
    assert (by["2026-02"].failure_count, by["2026-02"].failure_s) == (4, 3720)
    assert sum(x.failure_count for x in r.data.rows) == 7


def test_zero_failures_null_mtbf(built):
    # s_2 before its first stop: 2400 s of running, no failure.
    r = reliability(
        built,
        ReliabilityArgs(
            machine_id="s_2",
            start=datetime(2020, 1, 1, 12, tzinfo=UTC),
            end=datetime(2020, 1, 1, 12, 40, tzinfo=UTC),
        ),
    )
    assert r.status == "ok"
    (row,) = r.data.rows
    assert row.failure_count == 0 and row.run_s == 2400
    assert row.mttr_s is None and row.mtbf_s is None
    assert any("no failures" in a for a in r.assumptions)
    # brick January month: shifts but no failures
    r = reliability(built, ReliabilityArgs(line_id="brick", group="month"))
    jan = next(x for x in r.data.rows if x.period == "2026-01")
    assert jan.failure_count == 0 and jan.mtbf_s is None and jan.run_s == 27900 - 2100


def test_reliability_empty_and_unknown(built):
    r = reliability(built, ReliabilityArgs(line_id="brick", start="2015-01-01", end="2015-02-01"))
    assert r.status == "insufficient_evidence" and "coverage is" in r.missing
    assert reliability(built, ReliabilityArgs(machine_id="s_99")).status == "out_of_scope"


def period(a, b):
    return {"a_start": a[0], "a_end": a[1], "b_start": b[0], "b_end": b[1]}


BEFORE = ("2025-09-01", "2025-12-31")
AFTER = ("2026-01-01", "2026-04-30")


def test_compare_overlap_rejected(built):
    r = compare_periods(
        built,
        CompareArgs(line_id="brick", **period(("2025-09-01", "2026-01-15"), AFTER)),
    )
    assert r.status == "out_of_scope" and "overlap" in r.missing and r.data is None
    # touching periods do not overlap (end is exclusive)
    r = compare_periods(
        built,
        CompareArgs(line_id="brick", **period(("2025-09-01", "2026-01-01"), AFTER)),
    )
    assert r.status == "ok"
    bad = compare_periods(
        built, CompareArgs(line_id="brick", **period(("2025-10-01", "2025-09-01"), AFTER))
    )
    assert bad.status == "out_of_scope" and "period A" in bad.missing
    r = compare_periods(built, CompareArgs(line_id="nope", **period(BEFORE, AFTER)))
    assert r.status == "out_of_scope"


def test_compare_deltas_are_b_minus_a(built):
    r = compare_periods(built, CompareArgs(line_id="brick", **period(BEFORE, AFTER)))
    assert r.status == "ok", r.missing
    d = r.data
    assert d.deltas.keys() == d.a.metrics.keys() == d.b.metrics.keys()
    for k, delta in d.deltas.items():
        a, b = d.a.metrics[k], d.b.metrics[k]
        if a is None or b is None:
            assert delta is None
        else:
            assert delta == pytest.approx(b - a)
    # hand values: before has 3 failures (3000 s) and 3 stops of other kinds
    assert d.a.metrics["failure_count"] == 3 and d.a.metrics["failure_s"] == 3000
    assert d.b.metrics["failure_count"] == 4 and d.b.metrics["failure_s"] == 3720
    assert d.deltas["failure_count"] == 1
    assert d.a.metrics["stop_count"] == 7 and d.b.metrics["stop_count"] == 7
    for ch in d.reason_changes:
        assert ch.delta_lost_s == pytest.approx(ch.b_lost_s - ch.a_lost_s)
    assert {c.reason for c in d.reason_changes} >= {x.reason for x in d.a.top_reasons}
    assert 0 < len(r.citations) <= CITATION_CAP


def test_compare_brick_before_after_oee_matches_get_oee(built):
    r = compare_periods(built, CompareArgs(line_id="brick", **period(BEFORE, AFTER)))
    assert r.status == "ok"
    for per, (lo, hi) in ((r.data.a, BEFORE), (r.data.b, AFTER)):
        g = get_oee(built, GetOeeArgs(line_id="brick", start=lo, end=hi, group="month"))
        rows = g.data.rows
        planned = sum(x.metrics["planned_s"] for x in rows)
        stop = sum(x.metrics["stop_s_union"] for x in rows)
        want = 1 - stop / planned
        assert per.metrics["availability_calc"] == pytest.approx(want)
        assert per.metrics["planned_s"] == planned
        # a single-month window must equal get_oee's month row exactly
    one = compare_periods(
        built,
        CompareArgs(
            line_id="brick", **period(("2025-09-01", "2025-10-01"), ("2026-02-01", "2026-03-01"))
        ),
    )
    g = get_oee(
        built, GetOeeArgs(line_id="brick", start="2026-02-01", end="2026-03-01", group="month")
    )
    (m,) = g.data.rows
    for k, v in m.metrics.items():
        assert one.data.b.metrics[k] == pytest.approx(v)


def test_compare_piade_window_matches_day_sums(built):
    # Shifts belong to a period by their start: A is the 06-14 shift, B the 14-22 shift.
    a = ("2020-01-01T06:00:00", "2020-01-01T14:00:00")
    b = ("2020-01-01T14:00:00", "2020-01-01T22:00:00")
    r = compare_periods(built, CompareArgs(machine_id="s_2", **period(a, b)))
    assert r.status == "ok", r.missing
    assert r.data.a.metrics["availability"] is not None
    assert (r.data.a.metrics["failure_count"], r.data.b.metrics["failure_count"]) == (1, 2)
    assert r.data.b.top_reasons[0].lost_s == 900 and r.data.deltas["failure_count"] == 1
    assert r.data.a.top_reasons and r.data.b.top_reasons[0].reason == "A_101"
    empty = compare_periods(
        built, CompareArgs(machine_id="s_2", **period(a, ("2015-01-01", "2015-02-01")))
    )
    assert empty.status == "insufficient_evidence" and "period B" in empty.missing


def test_get_events_filters_and_paging(built):
    r = get_events(built, GetEventsArgs(machine_id="s_2", state="stopped"))
    assert r.status == "ok"
    d = r.data
    assert d.total == 4 and len(d.events) == 4 and not d.truncated
    assert {e.state for e in d.events} == {"stopped"}
    assert [e.start_ts for e in d.events] == sorted(e.start_ts for e in d.events)
    assert {e.alarm_code for e in d.events} == {"A_101", "A_005"}
    assert r.citation_count == 4
    for c in r.citations:
        ev = next(e for e in d.events if e.event_id == c.event_id)
        assert (ev.raw_table, ev.source_file) == (c.raw_table, c.source_file)
        assert c.raw_row_id in ev.raw_row_ids

    page1 = get_events(built, GetEventsArgs(machine_id="s_2", state="stopped", limit=3))
    page2 = get_events(built, GetEventsArgs(machine_id="s_2", state="stopped", limit=3, offset=3))
    assert page1.data.truncated and not page2.data.truncated
    ids = [e.event_id for e in page1.data.events + page2.data.events]
    assert ids == [e.event_id for e in d.events]

    a = get_events(built, GetEventsArgs(machine_id="s_2", alarm="A_005"))
    assert a.data.total == 1
    b = get_events(built, GetEventsArgs(line_id="brick", event_type="stop", reason="FAILURE"))
    assert b.data.total == 7 and {e.reason_code for e in b.data.events} == {"FAILURE"}
    assert b.data.events[0].reason_text is not None  # core columns come through
    w = get_events(
        built,
        GetEventsArgs(
            machine_id="s_2",
            start=datetime(2020, 1, 1, 15, tzinfo=UTC),
            end=datetime(2020, 1, 1, 16, tzinfo=UTC),
            event_type="state_interval",
        ),
    )
    assert w.data.total == 4
    none = get_events(built, GetEventsArgs(machine_id="s_2", alarm="A_999"))
    assert none.status == "insufficient_evidence"
    assert get_events(built, GetEventsArgs(machine_id="zz")).status == "out_of_scope"


def test_events_limit_bounds_and_registry(built):
    r = call_tool(built, "get_events", {"machine_id": "s_2", "limit": 501})
    assert r.status == "out_of_scope" and "limit" in r.missing
    r = call_tool(built, "reliability", {"machine_id": "s_2", "group": "year"})
    assert r.status == "out_of_scope"
    r = call_tool(
        built,
        "compare_periods",
        {"line_id": "brick", "a_start": "2025-09-01", "a_end": "2025-10-01"},
    )
    assert r.status == "out_of_scope" and "b_start" in r.missing
