"""Cost-based reject threshold, review band and sensitivity (relative costs only).

A false reject (a normal image rejected) costs 1; an escaped defect (an anomalous image passed)
costs r. An image is rejected when its score is >= the threshold. The threshold is chosen on
validation images only and then applied to test images.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np

DEFAULT_R = 20
RS = (5, 10, 20, 50, 100)


def _arrays(scores, labels) -> tuple[np.ndarray, np.ndarray]:
    s, y = np.asarray(scores, float), np.asarray(labels, int)
    if s.size == 0 or s.size != y.size:
        raise ValueError("scores and labels must be non-empty and the same length")
    return s, y


def cost_threshold(scores, labels, r: float = DEFAULT_R) -> float:
    """Threshold minimising (false rejects + r * escapes) on the given images.

    Candidates are the midpoints between neighbouring distinct scores plus one just under the
    lowest and one just over the highest. Ties go to the lowest threshold (rejects more).
    """
    s, y = _arrays(scores, labels)
    u = np.unique(s)
    pad = max(float(u[-1] - u[0]), 1.0) * 1e-6
    cands = np.concatenate([[u[0] - pad], (u[:-1] + u[1:]) / 2, [u[-1] + pad]])
    normal, anomal = np.sort(s[y == 0]), np.sort(s[y == 1])
    fr = len(normal) - np.searchsorted(normal, cands, side="left")  # normals with s >= t
    esc = np.searchsorted(anomal, cands, side="left")  # anomalies with s < t
    cost = fr + r * esc
    return float(cands[int(np.argmin(cost))])


def evaluate(scores, labels, threshold: float, r: float = DEFAULT_R) -> dict:
    s, y = _arrays(scores, labels)
    rejected = s >= threshold
    n_norm, n_anom = int((y == 0).sum()), int((y == 1).sum())
    fr = int((rejected & (y == 0)).sum())
    esc = int((~rejected & (y == 1)).sum())
    cost = fr + r * esc
    return {
        "n": int(s.size),
        "n_normal": n_norm,
        "n_anomalous": n_anom,
        "false_rejects": fr,
        "escapes": esc,
        "false_reject_rate": fr / n_norm if n_norm else None,
        "escape_rate": esc / n_anom if n_anom else None,
        "cost": float(cost),
        "cost_per_1000": float(cost) / s.size * 1000,
    }


def review_band(scores, labels, threshold: float, review_share: float) -> dict:
    """Lower edge so that `review_share` of these (validation) images fall in [lower, threshold)."""
    s, y = _arrays(scores, labels)
    below = np.sort(s[s < threshold])[::-1]
    want = int(round(review_share * s.size))
    if want <= 0 or below.size == 0:
        lower = float(threshold)
    else:
        lower = float(below[min(want, below.size) - 1])
    in_band = (s >= lower) & (s < threshold)
    return {
        "lower": lower,
        "target_share": review_share,
        "share": float(in_band.mean()),
        "n_review": int(in_band.sum()),
        "anomalies_in_band": int((in_band & (y == 1)).sum()),
        "normals_in_band": int((in_band & (y == 0)).sum()),
    }


def band_effect(scores, labels, threshold: float, lower: float, r: float = DEFAULT_R) -> dict:
    """What the band does on other (test) images, assuming reviewers decide correctly."""
    s, y = _arrays(scores, labels)
    in_band = (s >= lower) & (s < threshold)
    base = evaluate(s, y, threshold, r)
    avoided = int((in_band & (y == 1)).sum())
    return {
        "share_to_review": float(in_band.mean()),
        "n_review": int(in_band.sum()),
        "anomalies_in_review": avoided,
        "normals_in_review": int((in_band & (y == 0)).sum()),
        "escapes_before": base["escapes"],
        "escapes_avoided": avoided,
        "escapes_remaining": base["escapes"] - avoided,
    }


def sensitivity(
    val: tuple[Sequence[float], Sequence[int]],
    test: tuple[Sequence[float], Sequence[int]],
    rs: Sequence[float] = RS,
) -> list[dict]:
    """Per r: threshold from validation, cost and rates on both validation and test."""
    rows = []
    for r in rs:
        t = cost_threshold(val[0], val[1], r)
        rows.append(
            {
                "r": r,
                "threshold": t,
                "validation": evaluate(val[0], val[1], t, r),
                "test": evaluate(test[0], test[1], t, r),
            }
        )
    return rows
