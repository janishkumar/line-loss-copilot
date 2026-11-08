import numpy as np
import pytest

from linecopilot.vision import threshold as th


def brute(scores, labels, r):
    best = None
    for t in sorted(set(scores)) + [max(scores) + 1]:
        c = sum(1 for s, y in zip(scores, labels, strict=True) if (s >= t and y == 0)) + r * sum(
            1 for s, y in zip(scores, labels, strict=True) if (s < t and y == 1)
        )
        best = c if best is None else min(best, c)
    return best


def test_cost_threshold_minimises_cost():
    rng = np.random.default_rng(0)
    y = rng.integers(0, 2, 60)
    s = rng.normal(size=60) + y
    for r in (1, 5, 20, 100):
        t = th.cost_threshold(s, y, r)
        got = th.evaluate(s, y, t, r)
        assert got["cost"] == pytest.approx(brute(list(s), list(y), r))


def test_separable_scores_cost_zero_and_threshold_between_classes():
    s = np.array([0.1, 0.2, 0.3, 0.8, 0.9])
    y = np.array([0, 0, 0, 1, 1])
    t = th.cost_threshold(s, y, 20)
    assert 0.3 < t <= 0.8
    e = th.evaluate(s, y, t, 20)
    assert e["cost"] == 0 and e["false_reject_rate"] == 0 and e["escape_rate"] == 0


def test_higher_r_never_raises_threshold():
    rng = np.random.default_rng(1)
    y = rng.integers(0, 2, 80)
    s = rng.normal(size=80) + y
    ts = [th.cost_threshold(s, y, r) for r in (1, 5, 20, 100, 1000)]
    assert ts == sorted(ts, reverse=True)


def test_evaluate_rates_and_cost_per_1000():
    s = np.array([0.1, 0.6, 0.4, 0.9])
    y = np.array([0, 0, 1, 1])
    e = th.evaluate(s, y, 0.5, 20)  # normal 0.6 rejected, anomaly 0.4 escapes
    assert e["false_reject_rate"] == 0.5 and e["escape_rate"] == 0.5
    assert e["cost"] == 1 + 20
    assert e["cost_per_1000"] == pytest.approx(21 / 4 * 1000)


def test_review_band_share_on_validation():
    s = np.arange(100) / 100
    y = np.zeros(100, int)
    y[90:] = 1
    t = 0.9
    band = th.review_band(s, y, t, 0.10)
    assert band["n_review"] == 10 and band["lower"] == pytest.approx(0.80)
    assert band["share"] == pytest.approx(0.10)
    assert th.review_band(s, y, 0.05, 0.5)["lower"] == pytest.approx(0.0)  # fewer than asked


def test_band_effect_on_test():
    s = np.array([0.1, 0.45, 0.48, 0.55, 0.9])
    y = np.array([0, 1, 0, 1, 1])
    eff = th.band_effect(s, y, threshold=0.5, lower=0.4, r=20)
    assert eff["share_to_review"] == pytest.approx(2 / 5)
    assert eff["escapes_avoided"] == 1 and eff["escapes_remaining"] == 0
    assert eff["normals_in_review"] == 1


def test_sensitivity_uses_validation_for_threshold_only():
    val_s = np.array([0.1, 0.2, 0.7, 0.9])
    val_y = np.array([0, 0, 1, 1])
    test_s = np.array([0.15, 0.6, 0.8, 0.95])
    test_y = np.array([0, 0, 1, 1])
    rows = th.sensitivity((val_s, val_y), (test_s, test_y), (5, 20))
    assert [r["r"] for r in rows] == [5, 20]
    assert all(0.2 < r["threshold"] <= 0.7 for r in rows)
    assert rows[0]["test"]["false_reject_rate"] == 0.5  # 0.6 rejected at threshold <= 0.6


def test_degenerate_inputs():
    with pytest.raises(ValueError):
        th.cost_threshold([], [], 20)
