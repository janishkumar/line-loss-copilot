"""Stop-risk dataset builder on a small hand-made frame (no database)."""

import pandas as pd
import pytest
from frames import ALARMS, EP, IV, D, intervals_frame, ts

from linecopilot.ml.dataset import (
    TEST_START,
    TRAIN_END,
    assign_split,
    build_dataset,
    build_features,
    label_times,
    prediction_times,
    shift_start,
    top_alarm_codes,
)


def row(df: pd.DataFrame, machine: str, t: str) -> pd.Series:
    sel = df[(df.machine_id == machine) & (df.t == ts(D + t))]
    assert len(sel) == 1
    return sel.iloc[0]


def test_prediction_times_need_an_interval_in_the_previous_hour():
    times = prediction_times(IV)
    got = {(m, t.strftime("%H:%M")) for m, t in zip(times.machine_id, times.t, strict=True)}
    assert got == {
        ("s_1", "11:00"),
        ("s_1", "12:00"),
        ("s_1", "13:00"),
        ("s_2", "10:00"),
        ("s_2", "11:00"),
    }


def test_features_hand_computed():
    df = build_features(IV, EP, prediction_times(IV), ALARMS)
    r = row(df, "s_1", "12:00")
    assert r.ep_count_1h == 1 and r.ep_count_4h == 2 and r.ep_count_24h == 2
    assert r.stopped_s_1h == 300 and r.stopped_s_4h == 900
    assert r.running_s_1h == 3300 and r.idle_s_1h == 0 and r.off_s_1h == 0
    assert r.running_s_24h == 1800 + 2400 + 2100
    assert (r.alarm_A_1_24h, r.alarm_A_2_24h, r.distinct_alarms_24h) == (1, 1, 2)
    # Only running intervals that ended before t: 10:40-11:20 at 120. 11:25-12:10 is open.
    assert (r.speed_mean_1h, r.speed_std_1h, r.speed_n_1h) == (120, 0, 1)
    assert r.min_since_stop_end == 35
    assert r.hour_of_week == 4 * 24 + 12  # Friday
    assert r.machine_s_1 == 1 and r.machine_s_2 == 0

    r = row(df, "s_1", "11:00")
    assert r.stopped_s_1h == 600 and r.running_s_1h == 3000
    assert r.speed_mean_1h == 100 and r.min_since_stop_end == 20

    r = row(df, "s_1", "13:00")
    assert r.stopped_s_1h == 1200 and r.running_s_1h == 600 and r.idle_s_1h == 1800
    assert r.speed_mean_1h == 80 and r.min_since_stop_end == 30
    assert r.alarm_A_1_24h == 2


def test_machine_stopped_at_t_and_no_history():
    df = build_features(IV, EP, prediction_times(IV), ALARMS)
    r = row(df, "s_2", "10:00")
    assert r.min_since_stop_end == 0  # the stop is still open at 10:00
    assert r.stopped_s_1h == 1800 and r.ep_count_1h == 1
    assert r.distinct_alarms_24h == 1  # A_3 is not a top alarm but still counted as distinct
    r = row(df, "s_1", "11:00")
    assert r.speed_n_1h == 1
    # No running interval ended in the hour: speed features are 0 with a count of 0.
    r = row(df, "s_2", "11:00")
    assert (r.speed_mean_1h, r.speed_std_1h, r.speed_n_1h) == (0, 0, 0)


def test_minutes_since_stop_capped_at_7_days():
    iv = intervals_frame([("s_1", "running", None, D + "10:00", D + "11:00", 10.0)])
    df = build_features(iv, EP.iloc[0:0], prediction_times(iv), [])
    assert df.min_since_stop_end.tolist() == [7 * 24 * 60]


def test_labels_and_observation():
    times = prediction_times(IV)
    lab = label_times(IV, EP, times, long_s=600)
    by = {
        (m, t.strftime("%H:%M")): r for (m, t), r in lab.set_index(["machine_id", "t"]).iterrows()
    }
    assert (by["s_1", "11:00"].y_stop, by["s_1", "11:00"].y_long) == (1, 0)
    assert (by["s_1", "12:00"].y_stop, by["s_1", "12:00"].y_long) == (1, 1)
    # Nothing logged in 13:00-14:00, so the label is unobserved.
    assert not by["s_1", "13:00"].label_observed
    assert by["s_1", "12:00"].label_observed
    # A long-stop threshold above every duration gives no long labels.
    lab = label_times(IV, EP, times, long_s=5000)
    assert lab.y_long.sum() == 0


def test_top_alarms_use_training_split_only():
    late = TRAIN_END + pd.Timedelta(days=1)
    rows = [("s_1", "stopped", "A_1", D + "10:00", D + "10:05", 0.0)] * 2
    rows += [("s_1", "stopped", "A_9", str(late), str(late + pd.Timedelta(minutes=5)), 0.0)] * 5
    iv = intervals_frame(rows)
    assert top_alarm_codes(iv, n=10) == ["A_1"]


def test_split_and_shift():
    t = pd.Series(
        [
            TRAIN_END - pd.Timedelta(hours=1),
            TRAIN_END,
            TEST_START - pd.Timedelta(hours=1),
            TEST_START,
        ]
    )
    assert assign_split(t).tolist() == ["train", "validation", "validation", "test"]
    s = shift_start(pd.Series([ts(D + "05:00"), ts(D + "06:00"), ts(D + "13:59"), ts(D + "22:00")]))
    assert [x.strftime("%m-%d %H") for x in s] == ["12-31 22", "01-01 06", "01-01 06", "01-01 22"]


def test_build_dataset_columns():
    df, features = build_dataset(IV, EP, ALARMS, long_s=600)
    assert {"machine_id", "t", "split", "shift", "y_stop", "y_long", "max_source_ts"} <= set(df)
    assert "max_source_ts" not in features and "y_stop" not in features
    assert all(c in df for c in features)
    assert not df[features].isna().any().any()
    assert df.split.unique().tolist() == ["train"]


@pytest.mark.parametrize("col", ["stopped_s_24h", "running_s_24h", "ep_count_24h"])
def test_features_never_negative(col):
    df = build_features(IV, EP, prediction_times(IV), ALARMS)
    assert (df[col] >= 0).all()
