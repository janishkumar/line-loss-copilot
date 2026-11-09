"""Image AUROC, pixel AUROC, pixel AUPRO and bootstrap intervals.

AUPRO follows the MVTec AD / VisA metric: for a threshold t the pixel false positive rate is the
share of normal pixels (every pixel outside the ground-truth masks, normal images included) with
score above t, and PRO is the mean over connected ground-truth regions (8-connectivity) of the
share of that region's pixels above t. The area under PRO against FPR up to `fpr_limit` is
divided by `fpr_limit`.

`aupro` is exact: the curve is a staircase, so the area is the sum, over normal pixels taken in
descending score, of PRO at that pixel's score divided by the number of normal pixels. When the
limit covers more normal pixels than `max_steps` the sum is taken on an even grid of ranks (the
default is dense enough that the grid error is far below the bootstrap interval).

`PixelStats` is the same maths on score histograms, so a bootstrap over images only adds
per-image count vectors instead of re-sorting millions of pixels.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence

import numpy as np
from scipy import ndimage
from sklearn.metrics import roc_auc_score

EIGHT = np.ones((3, 3), dtype=int)


def image_auroc(labels: Sequence[int] | np.ndarray, scores: Sequence[float] | np.ndarray) -> float:
    return float(roc_auc_score(np.asarray(labels), np.asarray(scores)))


def pixel_auroc(masks: np.ndarray, maps: np.ndarray) -> float:
    return float(roc_auc_score(np.asarray(masks).ravel().astype(int), np.asarray(maps).ravel()))


def _regions(masks: Sequence[np.ndarray]) -> list[tuple[int, np.ndarray]]:
    """(image index, boolean region mask) for every connected region of every mask."""
    out = []
    for i, mk in enumerate(masks):
        lab, n = ndimage.label(np.asarray(mk, bool), structure=EIGHT)
        for k in range(1, n + 1):
            out.append((i, lab == k))
    return out


def n_regions(masks: Sequence[np.ndarray]) -> int:
    return len(_regions(masks))


def aupro(
    masks: Sequence[np.ndarray],
    maps: Sequence[np.ndarray],
    fpr_limit: float = 0.3,
    max_steps: int = 20000,
) -> float:
    masks = [np.asarray(m, bool) for m in masks]
    maps = [np.asarray(m, float) for m in maps]
    regions = _regions(masks)
    if not regions:
        raise ValueError("AUPRO needs at least one anomalous region")
    neg = np.concatenate([mp[~mk] for mk, mp in zip(masks, maps, strict=True)])
    if neg.size == 0:
        raise ValueError("AUPRO needs normal pixels")
    region_scores = [np.sort(maps[i][rm]) for i, rm in regions]
    neg_desc = np.sort(neg)[::-1]
    n = neg_desc.size
    limit = fpr_limit * n
    whole = math.floor(limit + 1e-9)
    if math.ceil(limit - 1e-9) <= max_steps:
        edges = np.arange(0, whole + 1, dtype=float)
    else:
        edges = np.linspace(0, limit, max_steps + 1)
    if edges[-1] < limit - 1e-9:
        edges = np.append(edges, limit)
    widths = np.diff(edges)
    idx = np.clip(np.ceil(edges[1:] - 1e-9).astype(int), 1, n) - 1
    ts = neg_desc[idx]
    pro = np.zeros(ts.size)
    for rs in region_scores:
        pro += (rs.size - np.searchsorted(rs, ts, side="right")) / rs.size
    pro /= len(region_scores)
    return float(np.sum(widths / n * pro) / fpr_limit)


class PixelStats:
    """Histogram form of pixel AUROC and AUPRO with per-image weights (for the bootstrap)."""

    def __init__(self, masks: np.ndarray, maps: np.ndarray, bins: int = 3000) -> None:
        masks = np.asarray(masks, bool)
        maps = np.asarray(maps, float)
        neg = maps[~masks]
        qs = np.quantile(neg, np.linspace(0, 1, bins))
        top = np.linspace(neg.max(), maps.max(), max(bins // 4, 2))[1:]
        self.edges = np.unique(np.concatenate([qs, top]))
        nb = self.edges.size + 1
        self.nb = nb
        n_img = masks.shape[0]
        self.neg_hist = np.zeros((n_img, nb))
        self.pos_hist = np.zeros((n_img, nb))
        for i in range(n_img):
            b = np.searchsorted(self.edges, maps[i], side="right")
            self.neg_hist[i] = np.bincount(b[~masks[i]], minlength=nb)
            self.pos_hist[i] = np.bincount(b[masks[i]], minlength=nb)
        regions = _regions(list(masks))
        self.region_image = np.array([i for i, _ in regions], dtype=int)
        surv = np.zeros((len(regions), nb + 1), dtype=np.float32)
        for r, (i, rm) in enumerate(regions):
            h = np.bincount(np.searchsorted(self.edges, maps[i][rm], side="right"), minlength=nb)
            surv[r, :nb] = h[::-1].cumsum()[::-1] / h.sum()  # share with bin >= k
        self.surv = surv

    def pixel_auroc(self, w: np.ndarray) -> float:
        neg, pos = w @ self.neg_hist, w @ self.pos_hist
        if neg.sum() == 0 or pos.sum() == 0:
            raise ValueError("resample has no positive or no negative pixels")
        below = np.cumsum(neg) - neg
        return float(np.sum(pos * (below + 0.5 * neg)) / (pos.sum() * neg.sum()))

    def aupro(self, w: np.ndarray, fpr_limit: float = 0.3) -> float:
        wr = w[self.region_image].astype(float)
        if wr.sum() == 0:
            raise ValueError("resample has no anomalous region")
        neg = w @ self.neg_hist
        fpr = np.append(neg[::-1].cumsum()[::-1], 0.0) / neg.sum()  # FPR at threshold bin >= k
        pro = (wr @ self.surv) / wr.sum()
        fpr, pro = fpr[::-1], pro[::-1]  # ascending FPR
        keep = fpr <= fpr_limit
        x = np.append(fpr[keep], fpr_limit)
        y = np.append(pro[keep], np.interp(fpr_limit, fpr, pro))
        return float(np.trapezoid(y, x) / fpr_limit)


def bootstrap_ci(
    stat: Callable[[np.ndarray], float],
    n_items: int,
    n: int = 1000,
    seed: int = 0,
    return_skipped: bool = False,
) -> tuple[float, float] | tuple[float, float, int]:
    """95% percentile interval of stat(indices) over n resamples of range(n_items) with
    replacement. Resamples where the statistic is undefined (ValueError) are skipped; with
    `return_skipped` their count is returned as a third value."""
    rng = np.random.default_rng(seed)
    vals = []
    for _ in range(n):
        try:
            vals.append(stat(rng.integers(0, n_items, n_items)))
        except ValueError:
            continue
    if not vals:
        raise ValueError("statistic undefined on every resample")
    lo, hi = np.percentile(vals, [2.5, 97.5])
    if return_skipped:
        return float(lo), float(hi), n - len(vals)
    return float(lo), float(hi)
