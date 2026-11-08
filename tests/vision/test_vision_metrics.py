"""Metrics on toy arrays: AUROC against sklearn, AUPRO against a hand-computed case."""

import numpy as np
import pytest
from sklearn.metrics import roc_auc_score

from linecopilot.vision import metrics as m


def test_image_auroc_matches_sklearn():
    rng = np.random.default_rng(0)
    y = rng.integers(0, 2, 60)
    s = rng.normal(size=60) + y
    assert m.image_auroc(y, s) == pytest.approx(roc_auc_score(y, s))


def test_pixel_auroc_matches_sklearn():
    rng = np.random.default_rng(1)
    masks = rng.random((6, 8, 8)) > 0.8
    maps = rng.normal(size=(6, 8, 8)) + masks
    assert m.pixel_auroc(masks, maps) == pytest.approx(roc_auc_score(masks.ravel(), maps.ravel()))


# Toy for the hand computation: one anomalous 1x5 image with regions R1 = px 0,1 (scores 0.9, 0.5)
# and R2 = px 3 (0.7), not 8-connected to each other; its normal pixels 2 and 4 score 0.8 and 0.6;
# a normal 1x2 image scores 0.3 and 0.1. Normals desc: 0.8, 0.6, 0.3, 0.1. Pixels pass when
# score > t. fpr_limit 0.5 covers the first 2 of 4 normals:
#   t = 0.8 (FPR 0):    R1 1/2, R2 0 -> PRO 0.25
#   t = 0.6 (FPR 0.25): R1 1/2, R2 1 -> PRO 0.75
# Area = 0.25*0.25 + 0.25*0.75 = 0.25 (vertical jumps add none); / 0.5 = 0.5.


def test_aupro_hand_computed_toy():
    masks = [np.array([[1, 1, 0, 1, 0]], bool), np.array([[0, 0]], bool)]
    maps = [np.array([[0.9, 0.5, 0.8, 0.7, 0.6]]), np.array([[0.3, 0.1]])]
    assert m.aupro(masks, maps, fpr_limit=0.5) == pytest.approx(0.5)


def test_aupro_perfect_and_worst():
    masks = [np.array([[1, 1, 0, 0]], bool), np.array([[0, 0, 0, 0]], bool)]
    good = [np.array([[0.9, 0.9, 0.1, 0.1]]), np.array([[0.1, 0.1, 0.1, 0.1]])]
    bad = [np.array([[0.1, 0.1, 0.9, 0.9]]), np.array([[0.9, 0.9, 0.9, 0.9]])]
    assert m.aupro(masks, good, fpr_limit=0.3) == pytest.approx(1.0)
    assert m.aupro(masks, bad, fpr_limit=0.3) == pytest.approx(0.0)


def test_aupro_is_per_region_not_per_pixel():
    # a big region found and a tiny region missed: per-region mean is 0.5, per-pixel would be ~1
    big = np.zeros((1, 12), bool)
    big[0, :10] = True
    tiny = np.zeros((1, 12), bool)
    tiny[0, 11] = True
    mk = [big, tiny, np.zeros((1, 12), bool)]
    sc = [np.full((1, 12), 0.9), np.where(tiny, 0.0, 0.0) + 0.05, np.full((1, 12), 0.05)]
    sc[0][0, 10:] = 0.05
    # normal pixels (all scoring <= 0.05) never exceed a threshold above 0.05 -> FPR 0
    assert m.aupro(mk, sc, fpr_limit=0.3) == pytest.approx(0.5, abs=0.02)


def test_aupro_connected_components_use_8_connectivity():
    mk = [np.array([[1, 0], [0, 1]], bool), np.zeros((2, 2), bool)]  # one diagonal region
    # diagonal neighbours form one region under 8-connectivity (two under 4-connectivity)
    assert m.n_regions(mk) == 1


def test_aupro_grid_matches_exact():
    rng = np.random.default_rng(2)
    mk = [np.zeros((20, 20), bool) for _ in range(6)]
    for i in range(3):
        mk[i][4:9, 5:12] = True
    sc = [rng.normal(size=(20, 20)) + 1.5 * x for x in mk]
    exact = m.aupro(mk, sc, 0.3, max_steps=10**9)
    grid = m.aupro(mk, sc, 0.3, max_steps=200)
    assert grid == pytest.approx(exact, abs=0.02)


def test_aupro_needs_regions_and_normals():
    with pytest.raises(ValueError):
        m.aupro([np.zeros((2, 2), bool)], [np.zeros((2, 2))])
    with pytest.raises(ValueError):
        m.aupro([np.ones((2, 2), bool)], [np.zeros((2, 2))])


def test_binned_stats_match_exact():
    rng = np.random.default_rng(3)
    mk = np.zeros((8, 16, 16), bool)
    for i in range(4):
        mk[i, 3:8, 4:10] = True
    sc = rng.normal(size=mk.shape) + 1.2 * mk
    stats = m.PixelStats(mk, sc, bins=2000)
    w = np.ones(8)
    assert stats.pixel_auroc(w) == pytest.approx(m.pixel_auroc(mk, sc), abs=5e-3)
    assert stats.aupro(w) == pytest.approx(m.aupro(list(mk), list(sc), 0.3), abs=2e-2)


def test_bootstrap_ci_is_deterministic_and_brackets():
    rng = np.random.default_rng(4)
    y = rng.integers(0, 2, 80)
    s = rng.normal(size=80) + 1.5 * y
    a = m.bootstrap_ci(lambda idx: roc_auc_score(y[idx], s[idx]), 80, n=200, seed=0)
    b = m.bootstrap_ci(lambda idx: roc_auc_score(y[idx], s[idx]), 80, n=200, seed=0)
    assert a == b
    lo, hi = a
    assert lo < roc_auc_score(y, s) < hi
