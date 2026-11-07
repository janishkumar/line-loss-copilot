"""Next-hour stop-risk dataset on PIADE: one row per machine and whole UTC hour t.

Every feature reads only source values with a timestamp before t. Intervals that started
before t and are still open at t are clipped to t: their start is read, their end and speed
are not. Window sums use F(x) = sum over intervals starting before x of (x - start) minus the
same over intervals ending before x, which is the seconds logged before x and never reads an
end at or after x. `max_source_ts` is, per row, the latest source timestamp any feature read;
the tests check it is before t and that the features do not change when everything at or
after t is removed.

Labels look forward: y_stop = a stop episode (mart.stop_episode) starts in [t, t + 1 h);
y_long = one with duration_s >= LONG_STOP_S does. sequences_1h_data.csv is not used."""

from __future__ import annotations

from collections.abc import Iterable

import numpy as np
import pandas as pd

LONG_STOP_S = 600
TRAIN_END = pd.Timestamp("2021-07-01", tz="UTC")
TEST_START = pd.Timestamp("2021-10-01", tz="UTC")
N_ALARMS = 10
STATES = ("running", "idle", "off")
EPISODE_WINDOWS_H = (1, 4, 24)
STATE_WINDOWS_H = (1, 24)
MIN_SINCE_CAP = 7 * 24 * 60
# PIADE shifts: 8 h from 06:00 UTC, as core.event shift_id.
SHIFT_OFFSET = pd.Timedelta(hours=6)
SHIFT_LEN = pd.Timedelta(hours=8)
HOUR = 3600.0
EPOCH = pd.Timestamp("1970-01-01", tz="UTC")


def _sec(ts: pd.Series | pd.DatetimeIndex) -> np.ndarray:
    """Timestamps as float epoch seconds (independent of the datetime unit)."""
    return np.asarray((pd.to_datetime(ts, utc=True) - EPOCH) / pd.Timedelta(seconds=1), float)


def _ts(sec: np.ndarray) -> pd.Series:
    return pd.Series(EPOCH + pd.to_timedelta(np.round(sec * 1000), unit="ms"))


def shift_start(t: pd.Series) -> pd.Series:
    """Start of the 8 h PIADE shift containing each time."""
    t = pd.Series(pd.to_datetime(t, utc=True))
    return ((t - SHIFT_OFFSET).dt.floor(SHIFT_LEN) + SHIFT_OFFSET).reset_index(drop=True)


def assign_split(t: pd.Series) -> pd.Series:
    t = pd.Series(pd.to_datetime(t, utc=True)).reset_index(drop=True)
    out = pd.Series("validation", index=t.index, dtype=object)
    out[t < TRAIN_END] = "train"
    out[t >= TEST_START] = "test"
    return out


class _Logged:
    """Seconds logged before x for one machine's intervals (any overlap allowed)."""

    def __init__(self, starts: np.ndarray, ends: np.ndarray):
        # Offsets from the first start keep the prefix sums small enough to stay exact.
        self.ref = float(starts.min()) if len(starts) else 0.0
        self.s = np.sort(starts) - self.ref
        self.e = np.sort(ends) - self.ref
        self.cs = np.concatenate([[0.0], np.cumsum(self.s)])
        self.ce = np.concatenate([[0.0], np.cumsum(self.e)])

    def before(self, x: np.ndarray) -> np.ndarray:
        x = x - self.ref
        ks = np.searchsorted(self.s, x, "left")  # starts < x
        ke = np.searchsorted(self.e, x, "left")  # ends < x
        return (ks * x - self.cs[ks]) - (ke * x - self.ce[ke])

    def window(self, t: np.ndarray, hours: float) -> np.ndarray:
        """Seconds logged in [t - hours, t)."""
        return np.maximum(self.before(t) - self.before(t - hours * HOUR), 0.0)


def _count_in(sorted_x: np.ndarray, lo: np.ndarray, hi: np.ndarray) -> np.ndarray:
    """Number of values in [lo, hi)."""
    return np.searchsorted(sorted_x, hi, "left") - np.searchsorted(sorted_x, lo, "left")


def _last_before(sorted_x: np.ndarray, t: np.ndarray) -> np.ndarray:
    """Latest value < t, NaN if none."""
    k = np.searchsorted(sorted_x, t, "left")
    out = np.full(len(t), np.nan)
    has = k > 0
    out[has] = sorted_x[k[has] - 1]
    return out


def prediction_times(intervals: pd.DataFrame) -> pd.DataFrame:
    """Whole UTC hours t per machine with at least one interval overlapping [t - 1 h, t)."""
    out = []
    for m, g in intervals.groupby("machine_id", sort=True):
        s, e = _sec(g.start_ts), _sec(g.end_ts)
        lo = np.floor(s.min() / HOUR) * HOUR + HOUR
        hi = np.ceil(e.max() / HOUR) * HOUR
        grid = np.arange(lo, hi + HOUR / 2, HOUR)
        logged = _Logged(s, e).window(grid, 1)
        out.append(pd.DataFrame({"machine_id": m, "t": _ts(grid[logged > 0])}))
    if not out:
        return pd.DataFrame({"machine_id": pd.Series(dtype=object), "t": pd.Series(dtype=object)})
    return pd.concat(out, ignore_index=True)


def top_alarm_codes(intervals: pd.DataFrame, n: int = N_ALARMS) -> list[str]:
    """The n most frequent alarm codes over intervals that start before TRAIN_END."""
    a = intervals.loc[(intervals.start_ts < TRAIN_END) & intervals.alarm_code.notna()]
    vc = a.alarm_code.value_counts()
    vc = vc.sort_index().sort_values(ascending=False, kind="stable")
    return vc.index[:n].tolist()


def _machine_features(
    iv: pd.DataFrame, ep: pd.DataFrame, t: np.ndarray, alarms: list[str]
) -> dict[str, np.ndarray]:
    s_all, e_all = _sec(iv.start_ts), _sec(iv.end_ts)
    f: dict[str, np.ndarray] = {}

    ep_s = np.sort(_sec(ep.start_ts)) if len(ep) else np.array([])
    stopped = (iv.state == "stopped").to_numpy()
    stop_log = _Logged(s_all[stopped], e_all[stopped])
    for h in EPISODE_WINDOWS_H:
        f[f"ep_count_{h}h"] = _count_in(ep_s, t - h * HOUR, t).astype(float)
        f[f"stopped_s_{h}h"] = stop_log.window(t, h)
    for st in STATES:
        sel = (iv.state == st).to_numpy()
        log = _Logged(s_all[sel], e_all[sel])
        for h in STATE_WINDOWS_H:
            f[f"{st}_s_{h}h"] = log.window(t, h)

    has_alarm = iv.alarm_code.notna().to_numpy()
    codes = iv.alarm_code.to_numpy()
    distinct = np.zeros(len(t))
    for code in sorted(set(codes[has_alarm])):
        cs = np.sort(s_all[codes == code])
        n = _count_in(cs, t - 24 * HOUR, t)
        distinct += n > 0
        if code in alarms:
            f[f"alarm_{code}_24h"] = n.astype(float)
    for code in alarms:
        f.setdefault(f"alarm_{code}_24h", np.zeros(len(t)))
    f["distinct_alarms_24h"] = distinct

    # Speed of running intervals that ended in (t - 1 h, t): an open interval's speed is
    # not known until it ends.
    run = (iv.state == "running").to_numpy() & iv.speed.notna().to_numpy()
    order = np.argsort(e_all[run], kind="stable")
    re_, sp = e_all[run][order], iv.speed.to_numpy(float)[run][order]
    c1 = np.concatenate([[0.0], np.cumsum(sp)])
    c2 = np.concatenate([[0.0], np.cumsum(sp * sp)])
    i1 = np.searchsorted(re_, t, "left")
    i0 = np.searchsorted(re_, t - HOUR, "right")
    n = np.maximum(i1 - i0, 0)
    with np.errstate(invalid="ignore", divide="ignore"):
        mean = np.where(n > 0, (c1[i1] - c1[i0]) / n, 0.0)
        var = np.where(n > 0, (c2[i1] - c2[i0]) / n - mean**2, 0.0)
    f["speed_mean_1h"] = mean
    f["speed_std_1h"] = np.sqrt(np.maximum(var, 0.0))
    f["speed_n_1h"] = n.astype(float)

    # Minutes since the last stopped interval ended; 0 while one is open at t.
    ss, se = np.sort(s_all[stopped]), np.sort(e_all[stopped])
    open_n = np.searchsorted(ss, t, "left") - np.searchsorted(se, t, "left")
    last_end = _last_before(se, t)
    mins = np.where(np.isnan(last_end), MIN_SINCE_CAP, (t - last_end) / 60.0)
    f["min_since_stop_end"] = np.where(open_n > 0, 0.0, np.minimum(mins, MIN_SINCE_CAP))

    src = np.vstack(
        [
            _last_before(np.sort(s_all), t),
            _last_before(np.sort(e_all), t),
            _last_before(ep_s, t),
        ]
    )
    with np.errstate(invalid="ignore"):
        f["_max_source"] = np.where(np.isnan(src).all(axis=0), np.nan, np.nanmax(src, axis=0))
    return f


def build_features(
    intervals: pd.DataFrame,
    episodes: pd.DataFrame,
    times: pd.DataFrame,
    alarms: Iterable[str],
    machines: Iterable[str] | None = None,
) -> pd.DataFrame:
    """Feature rows for (machine_id, t) in `times`, plus `max_source_ts`.

    `alarms` are the top alarm codes chosen on the training split; `machines` the full
    machine list for the one-hot columns (default: those in `times`)."""
    alarms = list(alarms)
    machines = sorted(machines or times.machine_id.unique())
    parts = []
    for m, g in times.groupby("machine_id", sort=True):
        t = _sec(g.t)
        f = _machine_features(
            intervals[intervals.machine_id == m],
            episodes[episodes.machine_id == m],
            t,
            alarms,
        )
        src = f.pop("_max_source")
        df = pd.DataFrame({"machine_id": m, "t": g.t.to_numpy(), **f})
        df["max_source_ts"] = _ts(src).where(~np.isnan(src)).to_numpy()
        parts.append(df)
    df = pd.concat(parts, ignore_index=True)
    df["t"] = pd.to_datetime(df.t, utc=True)
    hours = df.t.dt.day_of_week * 24 + df.t.dt.hour
    df["hour_of_week"] = hours.astype(float)
    df["hod_sin"] = np.sin(2 * np.pi * df.t.dt.hour / 24)
    df["hod_cos"] = np.cos(2 * np.pi * df.t.dt.hour / 24)
    for mm in machines:
        df[f"machine_{mm}"] = (df.machine_id == mm).astype(float)
    return df


def label_times(
    intervals: pd.DataFrame, episodes: pd.DataFrame, times: pd.DataFrame, long_s: float
) -> pd.DataFrame:
    """y_stop, y_long and label_observed (anything logged in [t, t + 1 h)) per row."""
    parts = []
    for m, g in times.groupby("machine_id", sort=True):
        t = _sec(g.t)
        iv = intervals[intervals.machine_id == m]
        ep = episodes[episodes.machine_id == m]
        es = _sec(ep.start_ts)
        longs = ep.duration_s.to_numpy(float) >= long_s
        logged = _Logged(_sec(iv.start_ts), _sec(iv.end_ts)).window(t + HOUR, 1)
        parts.append(
            pd.DataFrame(
                {
                    "machine_id": m,
                    "t": g.t.to_numpy(),
                    "y_stop": (_count_in(np.sort(es), t, t + HOUR) > 0).astype(int),
                    "y_long": (_count_in(np.sort(es[longs]), t, t + HOUR) > 0).astype(int),
                    "label_observed": logged > 0,
                }
            )
        )
    df = pd.concat(parts, ignore_index=True)
    df["t"] = pd.to_datetime(df.t, utc=True)
    return df


def feature_columns(df: pd.DataFrame) -> list[str]:
    skip = {"machine_id", "t", "max_source_ts", "split", "shift"}
    skip |= {"y_stop", "y_long", "label_observed"}
    return [c for c in df.columns if c not in skip]


def known_at(
    intervals: pd.DataFrame, episodes: pd.DataFrame, t: pd.Timestamp
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """The frames as a live system would hold them at t: intervals started before t, with
    an open interval's end set to t and its speed unknown; episodes started before t, with
    durations unknown. Features built from these must equal features built from the full
    frames."""
    iv = intervals[intervals.start_ts < t].copy()
    still_open = iv.end_ts > t
    iv.loc[still_open, "end_ts"] = t
    iv.loc[still_open, "speed"] = np.nan
    ep = episodes[episodes.start_ts < t].copy()
    ep["duration_s"] = np.nan
    return iv, ep


def build_dataset(
    intervals: pd.DataFrame,
    episodes: pd.DataFrame,
    alarms: Iterable[str] | None = None,
    long_s: float = LONG_STOP_S,
) -> tuple[pd.DataFrame, list[str]]:
    """Features, labels, split and shift for every prediction time; returns the frame and
    the feature column names. Top alarms default to the training split's top N_ALARMS."""
    alarms = top_alarm_codes(intervals) if alarms is None else list(alarms)
    times = prediction_times(intervals)
    machines = sorted(intervals.machine_id.unique())
    feats = build_features(intervals, episodes, times, alarms, machines)
    labels = label_times(intervals, episodes, times, long_s)
    df = feats.merge(labels, on=["machine_id", "t"], how="left", validate="one_to_one")
    df["split"] = assign_split(df.t)
    df["shift"] = shift_start(df.t)
    return df, feature_columns(df)


def load_frames(conn) -> tuple[pd.DataFrame, pd.DataFrame]:
    """PIADE intervals (clipped as in the marts; zero-length ones dropped) and stop
    episodes from the database."""
    cur = conn.execute(
        """SELECT i.machine_id, i.event_id, e.state, e.alarm_code, i.start_ts, i.end_ts,
                  i.speed::float8 AS speed
           FROM mart.piade_interval_counts i JOIN core.event e USING (event_id)
           WHERE i.end_ts > i.start_ts
           ORDER BY i.machine_id, i.start_ts, i.event_id"""
    )
    iv = pd.DataFrame(cur.fetchall(), columns=[d.name for d in cur.description])
    cur = conn.execute(
        """SELECT machine_id, episode_id, start_ts, duration_s::float8 AS duration_s
           FROM mart.stop_episode WHERE source_system = 'piade'
           ORDER BY machine_id, start_ts"""
    )
    ep = pd.DataFrame(cur.fetchall(), columns=[d.name for d in cur.description])
    for df in (iv, ep):
        for c in ("start_ts", "end_ts"):
            if c in df:
                df[c] = pd.to_datetime(df[c], utc=True)
    return iv, ep
