"""Ground truth on the fixture database: hand-computed values, and agreement with the tools
on the same definitions (the tools are only used here, never by evals/truth.py)."""

from datetime import UTC, datetime

import psycopg
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
    assert {"availability", "stop_count", "stop_time", "mttr"} <= set(facts["status"])
    for f in facts["facts"]:
        assert f["status"] in ("scored", "flat", "ambiguous")
        assert f["delta"] == pytest.approx(f["after"] - f["before"])
        dirs = set(f["readings"].values())
        if f["status"] == "scored":
            assert dirs == {f["direction"]} and f["direction"] in ("up", "down")
        elif f["status"] == "flat":
            assert dirs == {"flat"} and f["direction"] is None
        else:
            assert len(dirs) > 1 and f["direction"] is None
        expected = {"ratio": {"value", truth.EX_READING}, "total": {"total", "per_shift"}}
        assert set(f["readings"]) == expected.get(f["kind"], {"value"})
    sc = by["stop_count"]
    assert sc["before"] == truth.stop_count(built, "brick", "2025-09").expected
    assert sc["before_per_shift"] == pytest.approx(sc["before"] / facts["shifts"]["before"])
    reasons = [m for m in facts["facts"] if m["metric"].startswith("reason:")]
    assert len(reasons) <= truth.TOP_REASON_FACTS


def test_before_after_planned_gap_days_make_ratios_ambiguous(built):
    # Fixture: no planned-time gap, so both availability readings agree (down by ~1 pt).
    base = truth.before_after_facts(built)
    assert base["planned_gap_days"]["before"] == [] and base["planned_gap_days"]["after"] == []
    av = {f["metric"]: f for f in base["facts"]}["availability"]
    assert av["readings"] == {"value": "down", truth.EX_READING: "down"}
    assert av["before_ex_planned_gap"] == pytest.approx(av["before"])
    # Give two zero-stop before days 5 h of planned time that neither production nor the
    # stop columns account for (as in October 2025), inside a rolled-back transaction.
    days = ("brick:2025-09-24", "brick:2025-09-25")
    with built.transaction():  # psycopg.Rollback below is caught by the block
        built.execute(
            "UPDATE core.brick_shift_published SET planned_s = planned_s + 18000 "
            "WHERE shift_id = ANY(%s)",
            [list(days)],
        )
        built.execute(
            "UPDATE mart.brick_shift_oee SET planned_s_published = planned_s_published + 18000 "
            "WHERE shift_id = ANY(%s)",
            [list(days)],
        )
        facts = truth.before_after_facts(built)
        raise psycopg.Rollback
    assert facts["planned_gap_days"]["before"] == ["2025-09-24", "2025-09-25"]
    assert facts["planned_gap_days"]["shifts_ex"]["before"] == facts["shifts"]["before"] - 2
    by = {f["metric"]: f for f in facts["facts"]}
    av = by["availability"]
    # all days: 1 - 4200/166384 = 0.975 > after 0.957 (down); without the two days:
    # 1 - 4200/74584 = 0.944 < after (up). The readings disagree, so it is not scored.
    assert av["before"] == pytest.approx(1 - 4200 / 166384)
    assert av["before_ex_planned_gap"] == pytest.approx(1 - 4200 / 74584)
    assert av["readings"] == {"value": "down", truth.EX_READING: "up"}
    assert av["status"] == "ambiguous" and av["direction"] is None
    assert facts["status"]["availability"] == "ambiguous"
    # stop totals are not read twice
    assert truth.EX_READING not in by["stop_count"]["readings"]
    # the rollback left the fixture as it was
    assert truth.before_after_facts(built)["planned_gap_days"]["before"] == []


def test_effect_size_and_ambiguity():
    shifts = (10.0, 5.0)
    assert truth._fact("availability", "ratio", 0.70, 0.695, shifts)["status"] == "flat"
    assert truth._fact("availability", "ratio", 0.70, 0.685, shifts)["direction"] == "down"
    assert truth._fact("mttr", "mean", 100.0, 104.0, shifts)["status"] == "flat"
    assert truth._fact("mttr", "mean", 100.0, 106.0, shifts)["direction"] == "up"
    # total falls by a third, but per shift it rises (10/shift -> 13.3/shift): ambiguous
    f = truth._fact("stop_count", "total", 100.0, 66.7, shifts)
    assert f["readings"] == {"total": "down", "per_shift": "up"} and f["status"] == "ambiguous"
    f = truth._fact("stop_time", "total", 100.0, 40.0, shifts)
    assert f["status"] == "scored" and f["direction"] == "down"
    assert truth._fact("reason:X", "total", 0.0, 0.0, shifts)["status"] == "flat"
    # a ratio read with and without the planned-time gap days
    f = truth._fact("availability", "ratio", 0.736, 0.700, shifts, (0.676, 0.700))
    assert f["readings"] == {"value": "down", truth.EX_READING: "up"}
    assert f["status"] == "ambiguous" and f["before_ex_planned_gap"] == 0.676
    f = truth._fact("quality", "ratio", 0.985, 0.968, shifts, (0.984, 0.968))
    assert f["status"] == "scored" and f["direction"] == "down"


def test_stop_episode_matches_recount_from_core_event(built):
    # one brick month and one PIADE month of the fixture, recounted from core.event
    assert truth.crosscheck_episodes(built, "brick", "2025-09") == []
    assert truth.crosscheck_episodes(built, "brick", "2026-02") == []
    assert truth.crosscheck_episodes(built, "s_2", "2020-01") == []
    core = truth._reason_totals(built, truth.CORE_PIADE_REASONS, "s_2", "2020-01")
    assert sum(n for n, _ in core.values()) == truth.stop_count(built, "s_2", "2020-01").expected
    brick = truth._reason_totals(built, truth.CORE_BRICK_REASONS, "brick", "2026-02")
    assert sum(n for n, _ in brick.values()) == truth.stop_count(built, "brick", "2026-02").expected
    assert truth.crosscheck_episodes(built, "s_3", "2021-02") == [
        "crosscheck s_3 2021-02: no stops in core.event"
    ]


def test_crosscheck_reports_a_mart_that_drifts(built):
    with built.transaction():  # psycopg.Rollback below is caught by the block
        built.execute(
            "UPDATE mart.stop_episode SET duration_s = duration_s + 60 "
            "WHERE episode_id = (SELECT min(episode_id) FROM mart.stop_episode "
            "WHERE line_id = 'brick' AND in_oee AND start_ts >= '2026-02-01')"
        )
        problems = truth.crosscheck_episodes(built, "brick", "2026-02")
        raise psycopg.Rollback
    assert len(problems) == 1 and "mart.stop_episode" in problems[0]
    assert truth.crosscheck_episodes(built, "brick", "2026-02") == []


def test_check_reports_missing_truth_on_fixture(built):
    # the fixture holds a sliver of the data, so most live-data questions are flagged
    problems = check(built, build_questions()[:3])
    assert problems and all(":" in p for p in problems)
