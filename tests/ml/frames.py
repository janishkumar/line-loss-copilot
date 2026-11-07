"""Small hand-made PIADE frames and a synthetic modelling frame for the stop-risk tests."""

import numpy as np
import pandas as pd

from linecopilot.ml.dataset import assign_split, shift_start


def ts(s: str) -> pd.Timestamp:
    return pd.Timestamp(s, tz="UTC")


def intervals_frame(rows: list[tuple]) -> pd.DataFrame:
    df = pd.DataFrame(
        rows, columns=["machine_id", "state", "alarm_code", "start_ts", "end_ts", "speed"]
    )
    df["start_ts"] = pd.to_datetime(df["start_ts"], utc=True, format="ISO8601")
    df["end_ts"] = pd.to_datetime(df["end_ts"], utc=True, format="ISO8601")
    df["event_id"] = range(1, len(df) + 1)
    return df


def episodes_frame(rows: list[tuple]) -> pd.DataFrame:
    df = pd.DataFrame(rows, columns=["machine_id", "start_ts", "duration_s"])
    df["start_ts"] = pd.to_datetime(df["start_ts"], utc=True, format="ISO8601")
    return df


D = "2021-01-01 "
# s_1: running, a 10 min stop, running, a 5 min stop, running across 12:00, a 20 min
# (long) stop, idle. s_2: stopped across 10:00.
IV = intervals_frame(
    [
        ("s_1", "running", None, D + "10:00", D + "10:30", 100.0),
        ("s_1", "stopped", "A_1", D + "10:30", D + "10:40", 0.0),
        ("s_1", "running", None, D + "10:40", D + "11:20", 120.0),
        ("s_1", "stopped", "A_2", D + "11:20", D + "11:25", 0.0),
        ("s_1", "running", None, D + "11:25", D + "12:10", 80.0),
        ("s_1", "stopped", "A_1", D + "12:10", D + "12:30", 0.0),
        ("s_1", "idle", None, D + "12:30", D + "13:00", 0.0),
        ("s_2", "running", None, D + "09:00", D + "09:30", 50.0),
        ("s_2", "stopped", "A_3", D + "09:30", D + "10:20", 0.0),
    ]
)
EP = episodes_frame(
    [
        ("s_1", D + "10:30", 600.0),
        ("s_1", D + "11:20", 300.0),
        ("s_1", D + "12:10", 1200.0),
        ("s_2", D + "09:30", 3000.0),
    ]
)
ALARMS = ["A_1", "A_2"]


def synthetic_dataset(seed: int, n_machines: int = 3) -> tuple[pd.DataFrame, list[str]]:
    """Hourly rows for 2021 per machine: two features, y_long driven by the first, y_stop
    by the second, with label noise. Synthetic, for testing the training code only."""
    rng = np.random.default_rng(seed)
    t = pd.date_range("2021-01-01", "2021-12-31 23:00", freq="h", tz="UTC")
    parts = []
    for i in range(n_machines):
        n = len(t)
        f1, f2 = rng.normal(size=n), rng.normal(size=n)
        p_long = 1 / (1 + np.exp(-(2.5 * f1 - 2.5)))
        p_stop = 1 / (1 + np.exp(-(1.5 * f2)))
        parts.append(
            pd.DataFrame(
                {
                    "machine_id": f"s_{i + 1}",
                    "t": t,
                    "f1": f1,
                    "f2": f2,
                    "noise": rng.normal(size=n),
                    "ep_count_1h": (rng.random(n) < p_stop).astype(int),
                    "stopped_s_1h": rng.uniform(0, 3600, n),
                    "y_long": (rng.random(n) < p_long).astype(int),
                    "y_stop": (rng.random(n) < p_stop).astype(int),
                    "label_observed": True,
                }
            )
        )
    df = pd.concat(parts, ignore_index=True)
    df["hour_of_week"] = df.t.dt.day_of_week * 24 + df.t.dt.hour
    df["split"] = assign_split(df.t)
    df["shift"] = shift_start(df.t)
    return df, ["f1", "f2", "noise", "ep_count_1h", "stopped_s_1h", "hour_of_week"]
