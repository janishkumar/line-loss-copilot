"""Metrics and baselines for the stop-risk model.

Alert volume: within each machine and 8 h shift, the 3 hours with the highest score are
alerted (ties go to the earlier hour). Precision = alerted hours that had the event /
alerted hours; recall = alerted hours that had the event / all hours that had it."""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score

TOP_K = 3


def pr_auc(y: pd.Series, score: pd.Series) -> float:
    """Average precision; NaN when there are no positives."""
    y = np.asarray(y)
    if y.sum() == 0:
        return float("nan")
    return float(average_precision_score(y, np.asarray(score)))


def alert_mask(df: pd.DataFrame, score_col: str, k: int = TOP_K) -> pd.Series:
    """True for the top k hours per (machine_id, shift) by score, earlier hour on ties."""
    order = df.sort_values(
        ["machine_id", "shift", score_col, "t"], ascending=[True, True, False, True]
    )
    rank = order.groupby(["machine_id", "shift"], sort=False).cumcount()
    return (rank < k).reindex(df.index)


def top_k_precision_recall(
    df: pd.DataFrame, score_col: str, y_col: str, k: int = TOP_K
) -> tuple[float, float, int]:
    """(precision, recall, alerts) at the top-k-per-machine-per-shift alert volume."""
    m = alert_mask(df, score_col, k)
    y = df[y_col].astype(int)
    hits, n_alerts, pos = int(y[m].sum()), int(m.sum()), int(y.sum())
    precision = hits / n_alerts if n_alerts else float("nan")
    recall = hits / pos if pos else float("nan")
    return precision, recall, n_alerts


def persistence_scores(df: pd.DataFrame) -> pd.Series:
    """1 if a stop episode started in the last hour, else 0, plus up to 0.5 for the stopped
    seconds in the last hour, so ties break towards more recent stop time."""
    hit = (df["ep_count_1h"] > 0).astype(float)
    return hit + 0.5 * np.minimum(df["stopped_s_1h"], 3600.0) / 3600.0


def hour_of_week_scores(train: pd.DataFrame, score: pd.DataFrame, y_col: str) -> pd.Series:
    """Train-split event rate per (machine, hour of week); unseen hours fall back to the
    machine's train rate, unseen machines to the overall train rate."""
    by_how = train.groupby(["machine_id", "hour_of_week"])[y_col].mean()
    by_m = train.groupby("machine_id")[y_col].mean()
    overall = float(train[y_col].mean())
    keys = pd.MultiIndex.from_arrays([score.machine_id, score.hour_of_week])
    out = pd.Series(by_how.reindex(keys).to_numpy(), index=score.index)
    out = out.fillna(score.machine_id.map(by_m))
    return out.fillna(overall).astype(float)
