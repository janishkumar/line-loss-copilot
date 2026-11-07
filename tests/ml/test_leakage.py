"""Leakage guards for the stop-risk model: nothing at or after the prediction time feeds a
feature, labels shuffled in training carry no signal, and the splits do not touch."""

import numpy as np
import pandas as pd
from frames import ALARMS, EP, IV, synthetic_dataset

from linecopilot.ml.dataset import build_features, prediction_times
from linecopilot.ml.train import check_split_gap, shuffled_label_pr_auc


def test_max_source_ts_before_t():
    df = build_features(IV, EP, prediction_times(IV), ALARMS)
    assert len(df) == 5
    assert (df.max_source_ts.notna()).all()
    assert (df.max_source_ts < df.t).all()


def truncate(iv: pd.DataFrame, ep: pd.DataFrame, t: pd.Timestamp):
    """What a live system knows at t: intervals started before t, an open interval's end
    replaced by t and its speed unknown; episodes started before t, durations unknown."""
    iv = iv[iv.start_ts < t].copy()
    open_ = iv.end_ts > t
    iv.loc[open_, "end_ts"] = t
    iv.loc[open_, "speed"] = np.nan
    ep = ep[ep.start_ts < t].copy()
    ep["duration_s"] = np.nan
    return iv, ep


def test_features_unchanged_when_the_future_is_removed():
    times = prediction_times(IV)
    machines = ["s_1", "s_2"]
    full = build_features(IV, EP, times, ALARMS, machines).set_index(["machine_id", "t"])
    feats = [c for c in full.columns if c != "max_source_ts"]
    for m, t in zip(times.machine_id, times.t, strict=True):
        iv, ep = truncate(IV, EP, t)
        one = times[(times.machine_id == m) & (times.t == t)]
        cut = build_features(iv, ep, one, ALARMS, machines).set_index(["machine_id", "t"])
        pd.testing.assert_series_equal(
            full.loc[(m, t), feats], cut.loc[(m, t), feats], check_names=False
        )


def test_shuffled_labels_score_near_base_rate():
    df, features = synthetic_dataset(seed=1)
    test = df[df.split == "test"]
    base = test.y_long.mean()
    # The real labels carry signal, so this check is not passing trivially.
    pr, real = shuffled_label_pr_auc(df, features, "y_long", seed=0, with_real=True)
    assert real > base + 0.2
    assert abs(pr - base) < 0.03


def test_split_gap():
    df, _ = synthetic_dataset(seed=2)
    check_split_gap(df)
    train_max = df.loc[df.split == "train", "t"].max()
    assert df.loc[df.split == "test", "t"].min() > train_max + pd.Timedelta(hours=1)
    bad = df.copy()
    bad.loc[bad.index[-1], "split"] = "train"
    try:
        check_split_gap(bad)
    except ValueError as e:
        assert "split" in str(e)
    else:
        raise AssertionError("overlapping splits were not caught")
