"""Ground truth on the fixture database: hand-computed values, and agreement with the tools
on the same definitions (the tools are only used here, never by evals/truth.py)."""

from datetime import UTC, datetime

import pytest

from evals import truth
from evals.questions import build_questions, check
from linecopilot.tools.losses import LossParetoArgs, RepeatArgs, loss_pareto, repeat_failures
from linecopilot.tools.oee import GetOeeArgs, get_oee
from linecopilot.tools.reliability import ReliabilityArgs, reliability

pytestmark = pytest.mark.db

JAN20 = (datetime(2020, 1, 1, tzinfo=UTC), datetime(2020, 2, 1, tzinfo=UTC))
FEB26 = (datetime(2026, 2, 1, tzinfo=UTC), datetime(2026, 3, 1, tzinfo=UTC))


def test_numeric_truth_mttr_mtbf(built):
    # s_2: 3 failure episodes, 1500 s; 6299 s running after the 1 s overlap is clipped.
    t = truth.mttr_s(built, "s_2", "2020-01")
    assert t.expected == 500
    assert t.evidence_event_ids
    t = truth.mtbf_s(built, "s_2", "2020-01")
    assert t.expected == pytest.approx(6299 / 3)
    assert truth.mttr_s(built, "s_2", "2020-01").evidence_event_ids < t.evidence_event_ids
    r = reliability(built, ReliabilityArgs(machine_id="s_2", start=JAN20[0], end=JAN20[1]))
    assert r.data.rows[0].mttr_s == 500
    assert r.data.rows[0].mtbf_s == pytest.approx(t.expected)
    # every event the tool cites for the failures is evidence for MTTR
    cited = {c.event_id for c in r.citations}
    assert cited <= truth.mttr_s(built, "s_2", "2020-01").evidence_event_ids


def test_brick_month_truth_matches_tools(built):
    r = reliability(built, ReliabilityArgs(line_id="brick", group="month"))
    rows = {row.period: row for row in r.data.rows}
    t = truth.mttr_s(built, "brick", "2026-02")
    assert t.detail["failure_count"] == rows["2026-02"].failure_count == 4
    assert t.expected == pytest.approx(rows["2026-02"].mttr_s)
    assert truth.mtbf_s(built, "brick", "2026-02").expected == pytest.approx(rows["2026-02"].mtbf_s)
    assert truth.stop_count(built, "brick", "2026-02").expected == rows["2026-02"].stop_count

    oee = get_oee(built, GetOeeArgs(line_id="brick", start=FEB26[0], end=FEB26[1], group="month"))
    a = truth.availability(built, "brick", "2026-02")
    assert a.expected == pytest.approx(oee.data.rows[0].metrics["availability_calc"])
    assert {c.event_id for c in oee.citations} <= a.evidence_event_ids


def test_piade_availability_matches_tool(built):
    oee = get_oee(built, GetOeeArgs(machine_id="s_2", start=JAN20[0], end=JAN20[1], group="month"))
    a = truth.availability(built, "s_2", "2020-01")
    assert a.expected == pytest.approx(oee.data.rows[0].metrics["availability"])
    o = truth.piade_oee(built, "s_2", "2020-01")
    assert o.expected == pytest.approx(oee.data.rows[0].metrics["oee"])
    d = truth.availability_delta(built, "s_2", "2020-01", "2020-01")
    assert d.expected == 0


def test_label_truth_top_reason(built):
    t = truth.top_reason(built, "brick", "2026-02")
    p = loss_pareto(
        built, LossParetoArgs(line_id="brick", start=FEB26[0], end=FEB26[1], by="reason")
    )
    assert t.expected == p.data.rows[0].category
    assert t.detail["lost_s"] == pytest.approx(p.data.rows[0].lost_s)
    assert {c.event_id for c in p.data.rows[0].citations} <= t.evidence_event_ids
    lost = truth.top_reason_lost_s(built, "brick", "2026-02")
    assert lost.expected == t.detail["lost_s"] and lost.detail["reason"] == t.expected
    assert truth.top_reason(built, "s_2", "2020-01").expected == "A_101"


def test_repeat_chain_count_matches_tool(built):
    for asset, month, (lo, hi) in (("s_2", "2020-01", JAN20), ("brick", "2026-02", FEB26)):
        for within, n in ((24, 3), (1, 2)):
            t = truth.repeat_chain_count(built, asset, month, within_hours=within, min_repeats=n)
            r = repeat_failures(
                built,
                RepeatArgs(line_id=asset, start=lo, end=hi, within_hours=within, min_repeats=n),
            )
            assert t.expected == r.data.chain_count, (asset, within, n)
            cited = {c.event_id for ch in r.data.chains for c in ch.citations}
            assert cited <= t.evidence_event_ids


def test_note_truth(built):
    t = truth.note_date(built, "grasarisma")
    assert t.expected == "2025-09-22" and t.evidence_event_ids == {14}
    with pytest.raises(truth.NoTruth):
        truth.note_date(built, "no such word anywhere")


def test_na_truth(built):
    assert truth.not_available(built).expected == truth.NOT_AVAILABLE
    assert truth.not_available(built, "s_3", "2021-02").evidence_event_ids == frozenset()
    with pytest.raises(truth.NoTruth):
        truth.not_available(built, "s_2", "2020-01")  # has data: would be answerable
    with pytest.raises(truth.NoTruth):
        truth.mttr_s(built, "s_1", "2021-05")
    assert truth.compute(built, "stop_count", {"asset": "s_2", "month": "2020-01"}).expected == 3


def test_before_after_facts(built):
    facts = truth.before_after_facts(built)
    by = {f["metric"]: f for f in facts["facts"]}
    assert {"availability", "stop_count", "stop_time"} <= set(facts["directions"])
    for f in facts["facts"]:
        assert f["direction"] in ("up", "down")
        assert f["delta"] == pytest.approx(f["after"] - f["before"])
    sc = by.get("stop_count")
    if sc:
        assert sc["before"] == truth.stop_count(built, "brick", "2025-09").expected
    reasons = [m for m in facts["facts"] if m["metric"].startswith("reason:")]
    assert len(reasons) <= truth.TOP_REASON_FACTS


def test_check_reports_missing_truth_on_fixture(built):
    # the fixture holds a sliver of the data, so most live-data questions are flagged
    problems = check(built, build_questions()[:3])
    assert problems and all(":" in p for p in problems)
