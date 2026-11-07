"""Alert-volume metrics and baselines for the stop-risk model, on small frames."""

import numpy as np
import pandas as pd
import pytest

from linecopilot.ml.dataset import shift_start
from linecopilot.ml.metrics import (
    alert_mask,
    hour_of_week_scores,
    persistence_scores,
    pr_auc,
    top_k_precision_recall,
)


def frame(machine: str, start: str, scores: list[float], y: list[int]) -> pd.DataFrame:
    t = pd.date_range(start, periods=len(scores), freq="h", tz="UTC")
    return pd.DataFrame({"machine_id": machine, "t": t, "score": scores, "y": y})


def with_shift(df: pd.DataFrame) -> pd.DataFrame:
    df = df.reset_index(drop=True)
    df["shift"] = shift_start(df.t)
    return df


def test_top3_per_machine_per_shift():
    # s_1: one 8 h shift (06:00-14:00), 4 positives; s_2: the same shift, 1 positive.
    a = frame("s_1", "2021-01-04 06:00", [0.9, 0.1, 0.8, 0.2, 0.7, 0.3, 0.05, 0.6],
              [1, 0, 0, 1, 1, 0, 0, 1])  # fmt: skip
    b = frame("s_2", "2021-01-04 06:00", [0.5, 0.4, 0.3, 0.2, 0.1, 0.0, 0.0, 0.0],
              [0, 0, 0, 0, 0, 0, 0, 1])  # fmt: skip
    df = with_shift(pd.concat([a, b]))
    m = alert_mask(df, "score", k=3)
    assert m.sum() == 6
    assert df.loc[m & (df.machine_id == "s_1"), "score"].tolist() == [0.9, 0.8, 0.7]
    p, r, n = top_k_precision_recall(df, "score", "y", k=3)
    # s_1 alerts hit 2 (0.9 and 0.7); s_2 alerts hit none. 5 positives in all.
    assert n == 6 and p == pytest.approx(2 / 6) and r == pytest.approx(2 / 5)


def test_top3_ties_broken_by_time_and_short_shifts():
    # Equal scores: the earliest hours are alerted. A shift with 2 rows alerts both.
    df = with_shift(frame("s_1", "2021-01-04 06:00", [1, 1, 1, 1], [0, 0, 0, 1]))
    assert alert_mask(df, "score", k=3).tolist() == [True, True, True, False]
    df = with_shift(frame("s_1", "2021-01-04 12:00", [0.1, 0.2, 0.3], [1, 0, 1]))
    # 12:00 and 13:00 are one shift, 14:00 the next.
    assert alert_mask(df, "score", k=3).tolist() == [True, True, True]


def test_no_positives():
    df = with_shift(frame("s_1", "2021-01-04 06:00", [0.1, 0.2], [0, 0]))
    p, r, n = top_k_precision_recall(df, "score", "y", k=3)
    assert p == 0 and np.isnan(r) and n == 2
    assert np.isnan(pr_auc(df.y, df.score))


def test_pr_auc_perfect_and_random():
    assert pr_auc(pd.Series([0, 1, 0, 1]), pd.Series([0.1, 0.9, 0.2, 0.8])) == 1.0
    assert pr_auc(pd.Series([0, 1, 0, 1]), pd.Series([0.5] * 4)) == 0.5


def test_persistence_breaks_ties_by_recent_stopped_seconds():
    df = pd.DataFrame({"ep_count_1h": [0, 1, 1, 0, 2], "stopped_s_1h": [3600, 10, 900, 0, 7200]})
    s = persistence_scores(df)
    # Any recent episode outranks none; among each group more stopped seconds rank higher.
    assert s[1] > s[0] and s[2] > s[1] and s[0] > s[3]
    assert s[4] == pytest.approx(1.5)  # stopped seconds are capped at an hour
    assert s.max() <= 1.5 and s.min() >= 0


def test_hour_of_week_rates_from_train_only():
    t = pd.to_datetime(
        ["2021-01-04 06:00", "2021-01-11 06:00", "2021-01-04 07:00", "2021-07-05 06:00"], utc=True
    )
    train = pd.DataFrame({"machine_id": ["s_1"] * 3, "t": t[:3], "y": [1, 0, 1]})
    train["hour_of_week"] = train.t.dt.day_of_week * 24 + train.t.dt.hour
    score = pd.DataFrame(
        {"machine_id": ["s_1", "s_1", "s_2"], "t": [t[3], t[3], t[3]], "y": [1, 1, 1]}
    )
    score["hour_of_week"] = [6, 100, 6]
    s = hour_of_week_scores(train, score, "y")
    # Monday 06:00 seen twice in train (1, 0) -> 0.5; an unseen hour falls back to the
    # machine's train rate (2/3); an unseen machine to the overall train rate.
    assert s.tolist() == pytest.approx([0.5, 2 / 3, 2 / 3])
