"""Probe PIADE counter alignment and the unit of `speed` (Task 8, step 0).

`pi` and `po` are running counters. A per-interval count is a difference of consecutive
readings, and it is not stated which interval the difference belongs to:

- start: delta x[i+1] - x[i] is attributed to row i (the reading is taken at row start)
- end:   delta x[i] - x[i-1] is attributed to row i (the reading is taken at row end)

For each alignment this reports the share of valid `po` (and `pi`) counts that land on run
rows (production, performance_loss). Rules applied before counting, same as the dbt mart:
negative delta -> reset (dropped); delta > 3 x cap x hours of the attributed row -> glitch
(dropped), cap = the machine's max `speed` on production rows.

It also reports the speed-unit ratio: valid `po` counts on run rows per run hour divided by
the elapsed-weighted mean `speed` on run rows. A ratio well below 1 fits packages per hour.

Usage: PYTHONPATH=src uv run python scripts/probe_piade_counts.py [path/to/raw_data.csv]
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

RUN = {"production", "performance_loss"}
GAP_S = 60.0


def load(path: Path) -> pd.DataFrame:
    df = pd.read_csv(
        path,
        usecols=["equipment_ID", "type", "start", "end", "elapsed", "pi", "po", "speed"],
    )
    df = df.rename(columns={"equipment_ID": "machine_id", "type": "state"})
    df["row"] = np.arange(len(df)) + 2  # 1-based file line, header is line 1
    return df.sort_values(["machine_id", "start", "row"], kind="stable").reset_index(drop=True)


def deltas(g: pd.DataFrame, col: str, cap: float, alignment: str) -> pd.DataFrame:
    x = g[col].to_numpy(dtype=float)
    hours = g["elapsed"].to_numpy(dtype=float) / 3_600_000.0
    d = np.full(len(g), np.nan)
    gap = np.zeros(len(g), dtype=bool)
    gap_s = g["start"].to_numpy()[1:] - g["end"].to_numpy()[:-1]
    if alignment == "start":
        d[:-1] = x[1:] - x[:-1]
        gap[:-1] = gap_s > GAP_S
    else:
        d[1:] = x[1:] - x[:-1]
        gap[1:] = gap_s > GAP_S
    reset = d < 0
    glitch = d > 3 * cap * hours
    valid = ~np.isnan(d) & ~reset & ~glitch
    return pd.DataFrame(
        {
            "d": np.where(valid, d, 0.0),
            "valid": valid,
            "reset": reset,
            "glitch": glitch,
            "gap": gap,
            "run": g["state"].isin(RUN).to_numpy(),
            "hours": hours,
            "speed": g["speed"].to_numpy(dtype=float),
        }
    )


def main(path: Path) -> None:
    df = load(path)
    rows = []
    for machine, g in df.groupby("machine_id", sort=True):
        cap = float(g.loc[g["state"] == "production", "speed"].max())
        rec = {"machine": machine, "rows": len(g), "cap": cap}
        for col in ("po", "pi"):
            for al in ("start", "end"):
                t = deltas(g, col, cap, al)
                total = t["d"].sum() or np.nan
                rec[f"{col}_{al}_run_share"] = t.loc[t["run"], "d"].sum() / total
                rec[f"{col}_{al}_gap_share"] = t.loc[t["gap"], "d"].sum() / total
                rec[f"{col}_{al}_resets"] = int(t["reset"].sum())
                rec[f"{col}_{al}_glitches"] = int(t["glitch"].sum())
        t = deltas(g, "po", cap, "end")
        run = t[t["run"]]
        run_hours = run["hours"].sum()
        w_speed = (run["speed"] * run["hours"]).sum() / run_hours
        rec["po_per_run_hour"] = run["d"].sum() / run_hours
        rec["weighted_speed"] = w_speed
        rec["speed_ratio"] = rec["po_per_run_hour"] / w_speed
        rows.append(rec)
    out = pd.DataFrame(rows).set_index("machine")
    pd.set_option("display.width", 200)
    pd.set_option("display.max_columns", 50)
    for col in ("po", "pi"):
        cols = [c for c in out.columns if c.startswith(f"{col}_")]
        print(f"\n{col} counters")
        print(out[cols].round(4).T.to_string())
    print("\nspeed unit")
    print(out[["cap", "po_per_run_hour", "weighted_speed", "speed_ratio"]].round(4).to_string())


if __name__ == "__main__":
    main(Path(sys.argv[1] if len(sys.argv) > 1 else "data/raw/piade/raw_data.csv"))
