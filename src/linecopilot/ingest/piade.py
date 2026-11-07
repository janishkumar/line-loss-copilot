"""Parse the PIADE packaging-machine interval file into the standard contract.

Source columns: interval_start, equipment_ID, alarm, type, start, end, elapsed, pi, po, speed.
`start` and `end` are Unix seconds (UTC) and are written out as ISO 8601 UTC strings with
millisecond precision. `elapsed` is milliseconds. Alarm `A_000` means "no alarm" and becomes
None. Counters and speed stay as stripped strings (validated numeric). Gaps, overlaps and
counter resets are not contract failures; `piade_quality_report` counts them.

Validation is vectorised. The first failing rule per row is its rejection reason; rules run
in the order of `_rules`.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from linecopilot.ingest.contracts import ParsedFile, Rejected

SOURCE_COLUMNS = (
    "interval_start",
    "equipment_ID",
    "alarm",
    "type",
    "start",
    "end",
    "elapsed",
    "pi",
    "po",
    "speed",
)
STATES = ("production", "performance_loss", "downtime", "idle", "scheduled_downtime")
NO_ALARM = "A_000"
ELAPSED_TOLERANCE_MS = 5
OUTPUT_COLUMNS = (
    "machine_id",
    "alarm",
    "state",
    "start_utc",
    "end_utc",
    "elapsed_ms",
    "pi",
    "po",
    "speed",
)
_REQUIRED = ("equipment_ID", "alarm", "type", "start", "end", "elapsed", "pi", "po", "speed")
_NUMERIC = ("start", "end", "elapsed", "pi", "po", "speed")
_NON_NEGATIVE = ("elapsed", "pi", "po", "speed")


def _read(path: Path) -> pd.DataFrame:
    with open(path, encoding="utf-8-sig", newline="") as fh:
        first = fh.readline()
    if not first.strip():
        raise ValueError(f"{path}: empty file")
    header = [h.strip() for h in first.rstrip("\r\n").split(",")]
    unknown = [h for h in header if h and h not in SOURCE_COLUMNS]
    if unknown:
        raise ValueError(f"{path}: unexpected columns {unknown}")
    missing = [c for c in SOURCE_COLUMNS if c not in header]
    if missing:
        raise ValueError(f"{path}: missing columns {missing}")
    dupes = sorted({h for h in header if header.count(h) > 1})
    if dupes:
        raise ValueError(f"{path}: duplicate columns {dupes}")
    df = pd.read_csv(
        path,
        dtype=str,
        keep_default_na=False,
        encoding="utf-8-sig",
        skip_blank_lines=False,
        usecols=list(SOURCE_COLUMNS),
    )
    for col in SOURCE_COLUMNS:
        df[col] = df[col].str.strip()
    df.index = pd.RangeIndex(1, len(df) + 1, name="source_row")
    return df


def _rules(df: pd.DataFrame, num: dict[str, pd.Series]) -> list[tuple[pd.Series, str]]:
    rules: list[tuple[pd.Series, str]] = []
    empty = pd.Series(True, index=df.index)
    for col in SOURCE_COLUMNS:
        empty &= df[col] == ""
    rules.append((empty, "empty_row"))
    for col in _REQUIRED:
        rules.append((df[col] == "", f"missing_required:{col}"))
    for col in _NUMERIC:
        rules.append((~np.isfinite(num[col]), f"bad_number:{col}"))
    for col in _NON_NEGATIVE:
        rules.append((num[col] < 0, f"out_of_range:{col}"))
    rules.append((num["end"] < num["start"], "end_before_start"))
    rules.append((~df["type"].isin(STATES), "unknown_state"))
    drift = (num["elapsed"] - (num["end"] - num["start"]) * 1000).abs()
    rules.append((drift > ELAPSED_TOLERANCE_MS, "elapsed_mismatch"))
    no_alarm = df["alarm"] == NO_ALARM
    rules.append(((df["type"] == "downtime") & no_alarm, "downtime_without_alarm"))
    rules.append(((df["type"] != "downtime") & ~no_alarm, "alarm_outside_downtime"))
    return rules


def _iso_utc(seconds: pd.Series) -> pd.Series:
    ms = np.rint(seconds.to_numpy(dtype="float64") * 1000).astype("int64")
    text = ms.astype("datetime64[ms]").astype("U23")
    return pd.Series(np.char.add(text, "Z"), index=seconds.index, dtype=object)


def parse_piade_raw(path: Path) -> ParsedFile:
    df = _read(path)
    num = {c: pd.to_numeric(df[c], errors="coerce") for c in _NUMERIC}
    reason = pd.Series("", index=df.index, dtype=object)
    for mask, text in _rules(df, num):
        reason = reason.where(reason != "", pd.Series(np.where(mask, text, ""), index=df.index))
    bad = reason != ""
    rejected = [Rejected(int(i), reason[i], df.loc[i].to_dict()) for i in df.index[bad]]
    ok = ~bad
    good = df[ok]
    frame = pd.DataFrame(
        {
            "machine_id": good["equipment_ID"],
            "alarm": good["alarm"].where(good["alarm"] != NO_ALARM, None),
            "state": good["type"],
            "start_utc": _iso_utc(num["start"][ok]),
            "end_utc": _iso_utc(num["end"][ok]),
            "elapsed_ms": good["elapsed"],
            "pi": good["pi"],
            "po": good["po"],
            "speed": good["speed"],
        },
        columns=list(OUTPUT_COLUMNS),
    )
    frame["alarm"] = frame["alarm"].astype(object).where(frame["alarm"].notna(), None)
    rows = frame.to_dict("records")
    return ParsedFile(
        rows=rows,
        source_rows=[int(i) for i in frame.index],
        rejected=rejected,
        frame=frame,
    )


def piade_quality_report(parsed: ParsedFile) -> dict[str, dict[str, float | int]]:
    """Per machine: gaps, overlaps and counter resets, measured in `start` order."""
    frame = parsed.frame if parsed.frame is not None else pd.DataFrame(parsed.rows)
    start = frame["start_utc"].str.rstrip("Z").to_numpy().astype("datetime64[ms]")
    end = frame["end_utc"].str.rstrip("Z").to_numpy().astype("datetime64[ms]")
    work = pd.DataFrame(
        {
            "machine": frame["machine_id"].to_numpy(),
            "start": start,
            "end": end,
            "pi": pd.to_numeric(frame["pi"]).to_numpy(),
            "po": pd.to_numeric(frame["po"]).to_numpy(),
        }
    )
    report: dict[str, dict[str, float | int]] = {}
    for machine, grp in sorted(work.groupby("machine", sort=True), key=lambda kv: kv[0]):
        grp = grp.sort_values("start", kind="stable")
        gap_s = (
            (grp["start"].to_numpy()[1:] - grp["end"].to_numpy()[:-1]) / np.timedelta64(1, "ms")
        ) / 1000
        report[machine] = {
            "rows": len(grp),
            "gaps_over_60s": int((gap_s > 60).sum()),
            "max_gap_s": float(max(gap_s.max(), 0.0)) if len(gap_s) else 0.0,
            "overlaps_over_1s": int((gap_s < -1).sum()),
            "counter_resets_pi": int((np.diff(grp["pi"].to_numpy()) < 0).sum()),
            "counter_resets_po": int((np.diff(grp["po"].to_numpy()) < 0).sum()),
        }
    return report
