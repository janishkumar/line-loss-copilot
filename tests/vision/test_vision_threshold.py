import numpy as np
import pytest

from linecopilot.vision import threshold as th


def wcost(scores, labels, t, r, p):
    s, y = np.asarray(scores), np.asarray(labels)
    frr = np.mean(s[y == 0] >= t)
    er = np.mean(s[y == 1] < t)
    return (1 - p) * frr + p * r * er


def brute(scores, labels, r, p):
    cands = sorted(set(scores)) + [max(scores) + 1]
    return min(wcost(scores, labels, t, r, p) for t in cands)


def test_cost_threshold_minimises_prevalence_weighted_cost():
    rng = np.random.default_rng(0)
    y = rng.integers(0, 2, 60)
    s = rng.normal(size=60) + y
    for r in (1, 5, 20, 100):
        for p in (0.005, 0.02, 0.5):
            t = th.cost_threshold(s, y, r, p)
            assert wcost(s, y, t, r, p) == pytest.approx(brute(list(s), list(y), r, p))


def test_prevalence_changes_the_threshold():
    """Same scores: a rare defect (small p) tolerates more escapes than a common one."""
    rng = np.random.default_rng(5)
    y = np.array([0] * 100 + [1] * 100)
    s = np.concatenate([rng.normal(0, 1, 100), rng.normal(2, 1, 100)])
    rare = th.cost_threshold(s, y, 20, 0.005)
    common = th.cost_threshold(s, y, 20, 0.5)
    assert rare > common


def test_class_mix_of_the_validation_set_does_not_matter():
    rng = np.random.default_rng(6)
    normal = rng.normal(0, 1, 40)
    anom = rng.normal(2, 1, 20)
    s1 = np.concatenate([normal, anom])
    y1 = np.array([0] * 40 + [1] * 20)
    s2 = np.concatenate([normal, anom, anom])  # same anomalies twice: 2:1 anomalous mix
    y2 = np.array([0] * 40 + [1] * 40)
    assert th.cost_threshold(s1, y1, 20, 0.02) == th.cost_threshold(s2, y2, 20, 0.02)


def test_separable_scores_cost_zero_and_threshold_between_classes():
    s = np.array([0.1, 0.2, 0.3, 0.8, 0.9])
    y = np.array([0, 0, 0, 1, 1])
    t = th.cost_threshold(s, y, 20, 0.02)
    assert 0.3 < t <= 0.8
    e = th.evaluate(s, y, t, 20, 0.02)
    assert e["cost"] == 0 and e["false_reject_rate"] == 0 and e["escape_rate"] == 0


def test_higher_r_never_raises_threshold():
    rng = np.random.default_rng(1)
    y = rng.integers(0, 2, 80)
    s = rng.normal(size=80) + y
    ts = [th.cost_threshold(s, y, r, 0.02) for r in (1, 5, 20, 100, 1000)]
    assert ts == sorted(ts, reverse=True)


def test_evaluate_rates_and_cost_per_1000():
    s = np.array([0.1, 0.6, 0.4, 0.9])
    y = np.array([0, 0, 1, 1])
    e = th.evaluate(s, y, 0.5, 20, 0.02)  # normal 0.6 rejected, anomaly 0.4 escapes
    assert e["false_reject_rate"] == 0.5 and e["escape_rate"] == 0.5
    assert e["cost"] == pytest.approx(0.98 * 0.5 + 0.02 * 20 * 0.5)
    assert e["cost_per_1000"] == pytest.approx(1000 * e["cost"])
    assert e["prevalence"] == 0.02


def test_review_band_weighted_share_on_validation():
    # 50 normals 0.00..0.49, 50 anomalies 0.50..0.99; threshold 0.5
    s = np.concatenate([np.arange(50) / 100, 0.5 + np.arange(50) / 100])
    y = np.array([0] * 50 + [1] * 50)
    band = th.review_band(s, y, 0.5, 0.10, p=0.02)
    # weighted share = 0.98 * (normals in band / 50): 5 of 50 normals -> 0.098, 6 -> 0.1176
    assert band["lower"] == pytest.approx(0.45)
    assert band["share"] == pytest.approx(0.98 * 5 / 50)
    assert band["n_review"] == 5
    assert th.review_band(s, y, 0.05, 0.5, 0.02)["lower"] == pytest.approx(0.0)


def test_band_effect_on_test_per_1000_items():
    s = np.array([0.1, 0.45, 0.48, 0.55, 0.9, 0.2])
    y = np.array([0, 1, 0, 1, 1, 0])
    eff = th.band_effect(s, y, threshold=0.5, lower=0.4, r=20, p=0.02)
    # normals 0.1, 0.48, 0.2: one of three in band; anomalies 0.45, 0.55, 0.9: one of three
    assert eff["normals_in_review_rate"] == pytest.approx(1 / 3)
    assert eff["anomalies_in_review_rate"] == pytest.approx(1 / 3)
    assert eff["review_per_1000"] == pytest.approx(1000 * (0.98 / 3 + 0.02 / 3))
    assert eff["escape_rate_before"] == pytest.approx(1 / 3)
    assert eff["escape_rate_after"] == pytest.approx(0.0)
    assert eff["escapes_avoided"] == 1 and eff["escapes_before"] == 1


def test_sensitivity_grid_r_by_p():
    val = (np.array([0.1, 0.2, 0.7, 0.9]), np.array([0, 0, 1, 1]))
    test = (np.array([0.15, 0.6, 0.8, 0.95]), np.array([0, 0, 1, 1]))
    rows = th.sensitivity(val, test, (5, 20), (0.01, 0.05))
    assert [(r["r"], r["p"]) for r in rows] == [(5, 0.01), (5, 0.05), (20, 0.01), (20, 0.05)]
    assert all(0.2 < r["threshold"] <= 0.7 for r in rows)


def test_degenerate_inputs():
    with pytest.raises(ValueError):
        th.cost_threshold([], [], 20, 0.02)
    with pytest.raises(ValueError):
        th.cost_threshold([0.1, 0.2], [0, 0], 20, 0.02)  # needs both classes
    with pytest.raises(ValueError):
        th.cost_threshold([0.1, 0.2], [0, 1], 20, 0.0)
