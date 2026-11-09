"""Prevalence-weighted reject threshold, review band and sensitivity (relative costs only).

A false reject (a normal item rejected) costs 1; an escaped defect (an anomalous item passed)
costs r. Items are rejected when their score is >= the threshold. Because the benchmark's test
mix (two thirds anomalous) is nothing like a plant's, the expected cost per item is built from
per-class rates and a stated defect prevalence p:

    cost = (1 - p) * false_reject_rate + p * r * escape_rate

The threshold minimises this on validation images only and is then applied to test images. The
default r = 20 and p = 0.02 are assumptions, not plant figures.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np

DEFAULT_R = 20
DEFAULT_P = 0.02
RS = (5, 10, 20, 50, 100)
PS = (0.005, 0.01, 0.02, 0.05)


def _arrays(scores, labels) -> tuple[np.ndarray, np.ndarray]:
    s, y = np.asarray(scores, float), np.asarray(labels, int)
    if s.size == 0 or s.size != y.size:
        raise ValueError("scores and labels must be non-empty and the same length")
    return s, y


def _both_classes(y: np.ndarray, p: float) -> None:
    if not (y == 0).any() or not (y == 1).any():
        raise ValueError("need both normal and anomalous images")
    if not 0 < p < 1:
        raise ValueError("prevalence p must be in (0, 1)")


def cost_threshold(scores, labels, r: float = DEFAULT_R, p: float = DEFAULT_P) -> float:
    """Threshold minimising the prevalence-weighted cost on the given images.

    Candidates are the midpoints between neighbouring distinct scores plus one just under the
    lowest and one just over the highest. Ties go to the lowest threshold (rejects more).
    """
    s, y = _arrays(scores, labels)
    _both_classes(y, p)
    u = np.unique(s)
    pad = max(float(u[-1] - u[0]), 1.0) * 1e-6
    cands = np.concatenate([[u[0] - pad], (u[:-1] + u[1:]) / 2, [u[-1] + pad]])
    normal, anomal = np.sort(s[y == 0]), np.sort(s[y == 1])
    frr = (len(normal) - np.searchsorted(normal, cands, side="left")) / len(normal)
    er = np.searchsorted(anomal, cands, side="left") / len(anomal)
    cost = (1 - p) * frr + p * r * er
    return float(cands[int(np.argmin(cost))])


def evaluate(scores, labels, threshold: float, r: float = DEFAULT_R, p: float = DEFAULT_P) -> dict:
    s, y = _arrays(scores, labels)
    rejected = s >= threshold
    n_norm, n_anom = int((y == 0).sum()), int((y == 1).sum())
    fr = int((rejected & (y == 0)).sum())
    esc = int((~rejected & (y == 1)).sum())
    frr = fr / n_norm if n_norm else None
    er = esc / n_anom if n_anom else None
    cost = (1 - p) * frr + p * r * er if n_norm and n_anom else None
    return {
        "n": int(s.size),
        "n_normal": n_norm,
        "n_anomalous": n_anom,
        "false_rejects": fr,
        "escapes": esc,
        "false_reject_rate": frr,
        "escape_rate": er,
        "prevalence": p,
        "cost": cost,
        "cost_per_1000": None if cost is None else 1000 * cost,
    }


def review_band(
    scores, labels, threshold: float, review_share: float, p: float = DEFAULT_P
) -> dict:
    """Lower edge so that about `review_share` of production items fall in [lower, threshold).

    The share is prevalence-weighted: (1 - p) x (share of validation normals in the band) +
    p x (share of validation anomalies in the band). The band is the widest one whose weighted
    share does not exceed the target (the closest from below).
    """
    s, y = _arrays(scores, labels)
    _both_classes(y, p)
    normal, anomal = s[y == 0], s[y == 1]

    def weighted(lower: float) -> float:
        return float(
            (1 - p) * np.mean((normal >= lower) & (normal < threshold))
            + p * np.mean((anomal >= lower) & (anomal < threshold))
        )

    below = np.unique(s[s < threshold])[::-1]  # candidate lower edges, highest first
    lower = float(threshold)
    for cand in below:
        if weighted(float(cand)) > review_share + 1e-12:
            break
        lower = float(cand)
    in_band = (s >= lower) & (s < threshold)
    return {
        "lower": lower,
        "target_share": review_share,
        "prevalence": p,
        "share": weighted(lower),
        "n_review": int(in_band.sum()),
        "normals_in_band": int((in_band & (y == 0)).sum()),
        "anomalies_in_band": int((in_band & (y == 1)).sum()),
    }


def band_effect(
    scores, labels, threshold: float, lower: float, r: float = DEFAULT_R, p: float = DEFAULT_P
) -> dict:
    """What the band does on other (test) images, assuming reviewers decide correctly."""
    s, y = _arrays(scores, labels)
    _both_classes(y, p)
    in_band = (s >= lower) & (s < threshold)
    base = evaluate(s, y, threshold, r, p)
    nrate = float(in_band[y == 0].mean())
    arate = float(in_band[y == 1].mean())
    avoided = int((in_band & (y == 1)).sum())
    return {
        "normals_in_review_rate": nrate,
        "anomalies_in_review_rate": arate,
        "review_per_1000": 1000 * ((1 - p) * nrate + p * arate),
        "n_review": int(in_band.sum()),
        "escape_rate_before": base["escape_rate"],
        "escape_rate_after": base["escape_rate"] - arate,
        "escapes_before": base["escapes"],
        "escapes_avoided": avoided,
        "escapes_remaining": base["escapes"] - avoided,
    }


def sensitivity(
    val: tuple[Sequence[float], Sequence[int]],
    test: tuple[Sequence[float], Sequence[int]],
    rs: Sequence[float] = RS,
    ps: Sequence[float] = PS,
) -> list[dict]:
    """Per (r, p): threshold from validation, cost and rates on both validation and test."""
    rows = []
    for r in rs:
        for p in ps:
            t = cost_threshold(val[0], val[1], r, p)
            rows.append(
                {
                    "r": r,
                    "p": p,
                    "threshold": t,
                    "validation": evaluate(val[0], val[1], t, r, p),
                    "test": evaluate(test[0], test[1], t, r, p),
                }
            )
    return rows
