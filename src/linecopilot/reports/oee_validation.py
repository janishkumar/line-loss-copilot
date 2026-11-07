"""Brick OEE validation report: computed against published, per period (design 5.5).

`python -m linecopilot.reports.oee_validation` reads the marts and writes
evals/results/oee_validation.json and .md, and evals/results/piade_oee.json.
"""

from __future__ import annotations

import json
import statistics
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import psycopg

from linecopilot.config import get_settings
from linecopilot.db import connect
from linecopilot.reports.piade_summary import piade_machine_summary

RESULTS = Path("evals/results")
LONG_PLANNED_S = 9 * 3600  # chosen after looking at the gaps; see docs/data-notes.md
PERIODS = ("before", "after")


def gap_stats(gaps: list[float]) -> dict[str, Any]:
    """Summary of signed gaps (computed minus published), as fractions. Empty gives None."""
    n = len(gaps)
    if n == 0:
        return {
            "n": 0,
            "mean_abs": None,
            "median_abs": None,
            "max_abs": None,
            "share_within_2pts": None,
            "share_within_5pts": None,
            "mean_signed": None,
        }
    a = [abs(g) for g in gaps]
    return {
        "n": n,
        "mean_abs": sum(a) / n,
        "median_abs": statistics.median(a),
        "max_abs": max(a),
        "share_within_2pts": sum(x <= 0.02 for x in a) / n,
        "share_within_5pts": sum(x <= 0.05 for x in a) / n,
        "mean_signed": sum(gaps) / n,
    }


def _period_summary(rows: list[dict]) -> dict[str, Any]:
    matched = [r for r in rows if r["match_status"] == "matched"]
    return {
        "n_published": sum(r["match_status"] != "no_published" for r in rows),
        "n_matched": len(matched),
        "n_no_stops": sum(r["match_status"] == "no_stops" for r in rows),
        "n_no_published": sum(r["match_status"] == "no_published" for r in rows),
        "availability": gap_stats(
            [float(r["availability_gap"]) for r in matched if r["availability_gap"] is not None]
        ),
        "oee": gap_stats([float(r["oee_gap"]) for r in matched if r["oee_gap"] is not None]),
    }


def summarise_rows(rows: list[dict]) -> dict[str, Any]:
    """Per period: counts by match status (nothing dropped) and gap stats over matched shifts."""
    return {p: _period_summary([r for r in rows if r["period"] == p]) for p in PERIODS}


def split_by_planned(rows: list[dict]) -> dict[str, Any]:
    """Post hoc breakdown of the before period by planned-day length (threshold chosen after
    looking at the gaps, so it explains the headline and does not replace it)."""
    out = {}
    for p in PERIODS:
        m = [
            r
            for r in rows
            if r["period"] == p
            and r["match_status"] == "matched"
            and r["availability_gap"] is not None
        ]
        long_ = [
            float(r["availability_gap"]) for r in m if r["planned_s_published"] > LONG_PLANNED_S
        ]
        short = [
            float(r["availability_gap"]) for r in m if r["planned_s_published"] <= LONG_PLANNED_S
        ]
        out[p] = {"planned_over_9h": gap_stats(long_), "planned_9h_or_less": gap_stats(short)}
    return out


@dataclass
class ValidationReport:
    windows: dict[str, dict[str, str]]
    periods: dict[str, Any]
    post_hoc_split: dict[str, Any]
    shifts: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "windows": self.windows,
            "periods": self.periods,
            "post_hoc_split": self.post_hoc_split,
            "long_planned_threshold_s": LONG_PLANNED_S,
            "shifts": self.shifts,
        }


def _jsonable(v: Any) -> Any:
    if v is None or isinstance(v, str | int | float):
        return v
    if hasattr(v, "isoformat"):
        return v.isoformat()
    return float(v)


def validate_oee(conn: psycopg.Connection) -> ValidationReport:
    cur = conn.execute("select * from mart.brick_shift_oee order by shift_date")
    cols = [d.name for d in cur.description]
    rows = [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]
    windows = {}
    for p in PERIODS:
        dates = [r["shift_date"] for r in rows if r["period"] == p]
        windows[p] = {"first": min(dates).isoformat(), "last": max(dates).isoformat()}
    return ValidationReport(
        windows=windows,
        periods=summarise_rows(rows),
        post_hoc_split=split_by_planned(rows),
        shifts=[{k: _jsonable(v) for k, v in r.items()} for r in rows],
    )


def _pts(v: float | None) -> str:
    return "n/a" if v is None else f"{v * 100:.2f}"


def _pct(v: float | None) -> str:
    return "n/a" if v is None else f"{v * 100:.1f}%"


def render_markdown(rep: ValidationReport) -> str:
    lines = ["# Brick OEE validation", ""]
    for kind, label in (("availability", "Availability"), ("oee", "OEE")):
        lines += [
            f"## {label} gap (computed minus published, matched shifts)",
            "",
            "| Period | Window | Published | Matched | No stops | No published | Mean abs (pts) | Median abs (pts) | Max abs (pts) | Within 2 pts | Within 5 pts |",  # noqa: E501
            "|---|---|---|---|---|---|---|---|---|---|---|",
        ]
        for p in PERIODS:
            s, g, w = rep.periods[p], rep.periods[p][kind], rep.windows[p]
            lines.append(
                f"| {p} | {w['first']} to {w['last']} | {s['n_published']} | {s['n_matched']} "
                f"| {s['n_no_stops']} | {s['n_no_published']} | {_pts(g['mean_abs'])} "
                f"| {_pts(g['median_abs'])} | {_pts(g['max_abs'])} "
                f"| {_pct(g['share_within_2pts'])} | {_pct(g['share_within_5pts'])} |"
            )
        lines.append("")
    lines += [
        "## Availability gap by planned-day length (post hoc)",
        "",
        "The 9 h threshold was chosen after looking at the gaps. It explains the headline;",
        "it does not replace it.",
        "",
        "| Period | Group | Shifts | Mean abs (pts) | Median abs (pts) |",
        "|---|---|---|---|---|",
    ]
    for p in PERIODS:
        for key, name in (
            ("planned_over_9h", "planned over 9 h"),
            ("planned_9h_or_less", "9 h or less"),
        ):
            g = rep.post_hoc_split[p][key]
            lines.append(
                f"| {p} | {name} | {g['n']} | {_pts(g['mean_abs'])} | {_pts(g['median_abs'])} |"
            )
    lines.append("")
    return "\n".join(lines)


def piade_results(conn: psycopg.Connection) -> list[dict]:
    df = piade_machine_summary(conn)
    win = {
        r[0]: (r[1].date().isoformat(), r[2].date().isoformat())
        for r in conn.execute(
            "select machine_id, min(shift_start), max(shift_start) from mart.piade_shift_oee "
            "group by 1 order by 1"
        )
    }
    out = []
    for machine, r in df.iterrows():
        out.append(
            {
                "machine_id": machine,
                "first_shift": win[machine][0],
                "last_shift": win[machine][1],
                **{
                    k: float(r[k])
                    for k in (
                        "n_shifts",
                        "planned_h",
                        "a",
                        "p_count_p95",
                        "p_count_p90",
                        "p_count_p99",
                        "p_time",
                        "q",
                        "oee_p95",
                        "oee_p90",
                        "oee_p99",
                        "oee_time",
                        "p90",
                        "p95",
                        "p99",
                        "n_shifts_counts_excluded",
                    )
                },
            }
        )
    return out


def write_results(rep: ValidationReport, piade: list[dict], out_dir: Path = RESULTS) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "oee_validation.json").write_text(
        json.dumps(rep.to_dict(), indent=2) + "\n", encoding="utf-8"
    )
    (out_dir / "oee_validation.md").write_text(render_markdown(rep), encoding="utf-8")
    (out_dir / "piade_oee.json").write_text(json.dumps(piade, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    with connect(get_settings().database_url) as conn:
        rep = validate_oee(conn)
        piade = piade_results(conn)
    write_results(rep, piade)
    print(render_markdown(rep))


if __name__ == "__main__":
    main()
