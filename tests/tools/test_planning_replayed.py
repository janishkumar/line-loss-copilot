"""Replay summary served by get_plan: median and quartiles, same method as evals/plan.py."""

from evals.plan import quartiles
from linecopilot.tools.planning import _replayed


def _rep(late, tard, chg):
    return {"kpis": {"late_orders": late, "total_tardiness_min": tard, "changeover_min": chg}}


def test_replayed_has_quartiles_matching_the_eval_method():
    tards = [100, 200, 300, 400, 1000, 50, 75, 125]
    out = _replayed([_rep(i, t, 10) for i, t in enumerate(tards)])
    med, q1, q3 = quartiles([float(t) for t in tards])
    t = out["total_tardiness_min"]
    assert (t["median"], t["q1"], t["q3"]) == (med, q1, q3)
    assert t["min"] == 50 and t["max"] == 1000 and out["windows"] == 8


def test_replayed_single_window_and_empty():
    one = _replayed([_rep(2, 120, 30)])["total_tardiness_min"]
    assert one["median"] == one["q1"] == one["q3"] == 120
    empty = _replayed([])["late_orders"]
    assert empty["q1"] is None and empty["q3"] is None and empty["median"] is None
