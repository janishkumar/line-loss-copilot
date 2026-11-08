"""Plan eval (stage 4): CP-SAT against FIFO and earliest-due-date, nominal and replayed against
real PIADE stops.

For each seed the synthetic orders are regenerated in memory (the database tables are not
touched), the three algorithms plan once, and each plan is replayed in each of the 8 windows
of real stops (2021-07-01 on; planning inputs come only from before that date). Reported per
algorithm: median and interquartile range of late orders, total tardiness and changeover
minutes, nominal (n = seeds) and replayed (n = seeds x windows), how often CP-SAT ended
optimal, feasible or fell back, and the paired CP-SAT minus EDD tardiness per seed x window.

The orders are synthetic; capacity (rates, availability, changeover minutes) and the stops are
real. A schedule that beats the baselines here is a result about the scheduler on this
generator, not about a plant. `make eval-plan` writes evals/results/plan.json and .md."""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from evals.safety.run import git_commit
from linecopilot.plan import cpsat, dispatch, replay
from linecopilot.plan.load import problem_from_synth
from linecopilot.plan.model import kpis, split_unschedulable
from linecopilot.synth.anchors import load_anchors
from linecopilot.synth.generate import content_hash, generate, load_factor

RESULTS = Path(__file__).resolve().parent / "results"
SEEDS = (7, 8, 9, 10, 11)
ALGORITHMS = ("cpsat", "edd_batch", "edd", "fifo")
MEASURES = ("late_orders", "total_tardiness_min", "changeover_min", "orders_after_horizon")
MEASURE_LABEL = {
    "late_orders": "Late orders",
    "total_tardiness_min": "Total tardiness (min)",
    "changeover_min": "Changeover (min)",
    "orders_after_horizon": "Orders finishing after the 14-day horizon",
}
# Eval-only cap on CP-SAT deterministic time; None means the solver default (60).
EVAL_DET_LIMIT: float | None = None

Case = dict  # {"nominal": kpis, "replays": [kpis per window], "status", "solver_status", ...}


def quartiles(xs: list[float]) -> tuple[float, float, float]:
    """(median, q1, q3), inclusive method; a single value gives itself three times."""
    if not xs:
        raise ValueError("no values")
    if len(xs) == 1:
        return xs[0], xs[0], xs[0]
    q1, med, q3 = statistics.quantiles(xs, n=4, method="inclusive")
    return med, q1, q3


def summarise(rows: list[dict]) -> dict[str, dict[str, float]]:
    out = {}
    for m in MEASURES:
        med, q1, q3 = quartiles([r[m] for r in rows])
        out[m] = {"median": med, "q1": q1, "q3": q3, "iqr": q3 - q1, "n": len(rows)}
    return out


def paired(a: list[float], b: list[float]) -> dict[str, Any]:
    """a minus b per case: how often a is strictly lower (better), equal, or higher."""
    if len(a) != len(b) or not a:
        raise ValueError("paired needs two equal, non-empty lists")
    d = [x - y for x, y in zip(a, b, strict=True)]
    n = len(d)
    return {
        "n": n,
        "better": sum(x < 0 for x in d),
        "equal": sum(x == 0 for x in d),
        "worse": sum(x > 0 for x in d),
        "share_better": sum(x < 0 for x in d) / n,
        "share_not_worse": sum(x <= 0 for x in d) / n,
        "median_diff": statistics.median(d),
        "mean_diff": sum(d) / n,
    }


def parse_key(key: str) -> tuple[str, str, str]:
    """`cpsat_vs_<base>_<nominal|replayed>_<measure>` -> (base, kind, measure)."""
    rest = key.removeprefix("cpsat_vs_")
    for kind in ("nominal", "replayed"):
        if f"_{kind}_" in rest:
            base, meas = rest.split(f"_{kind}_", 1)
            return base, kind, meas
    raise ValueError(key)


def evaluate(cases: dict[int, dict[str, Case]]) -> dict[str, Any]:
    """`cases[seed][algorithm]` -> the Case. Pure: this is the part tested on fakes."""
    seeds = sorted(cases)
    out: dict[str, Any] = {"nominal": {}, "replayed": {}, "solver": {}, "paired": {}}
    for alg in ALGORITHMS:
        out["nominal"][alg] = summarise([cases[s][alg]["nominal"] for s in seeds])
        out["replayed"][alg] = summarise([k for s in seeds for k in cases[s][alg]["replays"]])
    counts: dict[str, int] = {}
    stops: dict[str, int] = {}
    for s in seeds:
        c = cases[s]["cpsat"]
        key = "fallback_edd" if c["status"] == "fallback_edd" else c["status"].lower()
        counts[key] = counts.get(key, 0) + 1
        stops[c["stop_reason"]] = stops.get(c["stop_reason"], 0) + 1
    out["solver"] = {"status": counts, "stop_reason": stops, "n": len(seeds)}
    for base in ("edd_batch", "edd", "fifo"):
        for kind in ("nominal", "replayed"):
            for m in ("total_tardiness_min", "late_orders"):
                if kind == "nominal":
                    a = [cases[s]["cpsat"]["nominal"][m] for s in seeds]
                    b = [cases[s][base]["nominal"][m] for s in seeds]
                else:
                    a = [k[m] for s in seeds for k in cases[s]["cpsat"]["replays"]]
                    b = [k[m] for s in seeds for k in cases[s][base]["replays"]]
                out["paired"][f"cpsat_vs_{base}_{kind}_{m}"] = paired(a, b)
    return out


def run_case(problem, windows: list, stops_by_window: list, limit: float | None) -> dict[str, Case]:
    problem = split_unschedulable(problem)
    kwargs = {} if limit is None else {"max_deterministic_time": limit}
    plans = {
        "fifo": dispatch.fifo(problem),
        "edd": dispatch.edd(problem),
        "edd_batch": dispatch.edd_batch(problem),
        "cpsat": cpsat.solve(problem, **kwargs),
    }
    out = {}
    for alg, plan in plans.items():
        out[alg] = {
            "nominal": kpis(problem, plan.assignments),
            "replays": [kpis(problem, replay.execute(problem, plan, st)) for st in stops_by_window],
            "status": plan.status,
            "solver_status": plan.solver_status,
            "stop_reason": plan.stop_reason,
            "objective": plan.objective,
            "bound": plan.bound,
        }
    return out


def run(conn, seeds=SEEDS, limit: float | None = EVAL_DET_LIMIT) -> dict[str, Any]:
    t0 = time.monotonic()
    anchors = load_anchors(conn)
    wins = replay.windows(conn)
    stops_by_window = [replay.stops(conn, w) for w in wins]
    machines = sorted(anchors.rates)
    stats = [replay.window_stats(conn, w, machines) for w in wins]
    cases: dict[int, dict[str, Case]] = {}
    seed_meta = {}
    for seed in seeds:
        data = generate(anchors, seed)
        problem = problem_from_synth(data)
        cases[seed] = run_case(problem, wins, stops_by_window, limit)
        seed_meta[seed] = {
            "content_sha256": content_hash(data),
            "orders": len(data.customer_order),
            "scheduled": len(split_unschedulable(problem).jobs),
            "blocked": len(problem.blocked),
            "load_factor": round(load_factor(data, anchors), 4),
        }
        print(
            f"seed {seed}: cpsat {cases[seed]['cpsat']['status']} "
            f"({time.monotonic() - t0:.0f} s elapsed)",
            file=sys.stderr,
        )
    return {
        "meta": {
            "date": datetime.now(UTC).isoformat(timespec="seconds"),
            "git_commit": git_commit(),
            "seeds": list(seeds),
            "seed_meta": seed_meta,
            "n_windows": len(wins),
            "windows": [{"start": w.start.isoformat(), "end": w.end.isoformat()} for w in wins],
            "cpsat_max_deterministic_time": cpsat.MAX_DETERMINISTIC_TIME
            if limit is None
            else limit,
            "cpsat_wall_cap_s": cpsat.WALL_CAP_S,
            "seconds": round(time.monotonic() - t0, 1),
            "anchors": {
                "rates": anchors.rates,
                "availability": anchors.availability,
                "changeover_same_family_min": anchors.changeover_same_family_min,
                "changeover_cross_family_min": anchors.changeover_cross_family_min,
                "cutoff": anchors.sources["availability_cutoff"],
            },
            "synthetic_orders_real_capacity_real_stops": True,
        },
        "window_stats": stats,
        "cases": {str(s): c for s, c in cases.items()},
        **evaluate(cases),
    }


def _n(x: float) -> str:
    return f"{x:.0f}" if abs(x - round(x)) < 1e-9 else f"{x:.1f}"


def _cell(s: dict) -> str:
    return f"{_n(s['median'])} ({_n(s['q1'])} to {_n(s['q3'])})"


def _pct(x: float | None) -> str:
    return "n/a" if x is None else f"{x:.1%}"


def window_table(doc: dict[str, Any]) -> list[str]:
    """Realised stopped share of covered time (the planning availability's denominator) and the
    no-data share, per window and machine, with the planning figure and the median of windows."""
    a = doc["meta"]["anchors"]["availability"]
    machines = sorted(a)
    L = [
        "| Window start | "
        + " | ".join(f"{m} stopped of covered / no data" for m in machines)
        + " |",
        "|---|" + "---|" * len(machines),
    ]
    rows = list(zip(doc["meta"]["windows"], doc["window_stats"], strict=True))
    for w, st in rows:
        cells = [
            f"{_pct(st[m]['stopped_share_of_covered'])} / {st[m]['no_data_share']:.1%}"
            for m in machines
        ]
        L.append(f"| {w['start'][:10]} | " + " | ".join(cells) + " |")
    meds = []
    for m in machines:
        vals = [st[m]["stopped_share_of_covered"] for _, st in rows]
        vals = [v for v in vals if v is not None]
        meds.append(_pct(statistics.median(vals)) if vals else "n/a")
    L.append("| Median over windows | " + " | ".join(meds) + " |")
    L.append(
        "| Planning stopped share of covered time (before 2021-07-01) | "
        + " | ".join(_pct(1 - a[m]) for m in machines)
        + " |"
    )
    return L


def markdown(doc: dict[str, Any]) -> str:
    m = doc["meta"]
    S = doc["solver"]
    L = [
        "# Plan eval (synthetic orders on real capacity and real stops)",
        "",
        f"- Seeds: {', '.join(map(str, m['seeds']))}; {m['n_windows']} replay windows of 14 days "
        f"from {m['windows'][0]['start'][:10]} ({len(m['seeds']) * m['n_windows']} seed x "
        "window cases per algorithm)",
        f"- Date (UTC): {m['date']}; git commit {m['git_commit']}; run time {m['seconds']} s",
        f"- CP-SAT: 1 worker, seed 0, deterministic limit {m['cpsat_max_deterministic_time']}, "
        f"wall cap {m['cpsat_wall_cap_s']} s",
        f"- Planning inputs: rates and availability from PIADE rows before "
        f"{m['anchors']['cutoff'][:10]}; changeover minutes from the brick line stop log "
        "(2025 to 2026, a different process and period, not date-filtered). Replay windows "
        "start on or after the PIADE cutoff",
        "",
        "Orders, BOMs, stock and receipts are synthetic; capacity and the replayed stops are "
        "real PIADE data. `edd_batch` is EDD with the same earliest-finish "
        "machine rule and a changeover-aware job order (family batching, window "
        f"{dispatch.BATCH_SLACK_MIN} min). The comparison to read first is CP-SAT against plain "
        "EDD; `edd_batch` isolates what batching alone changes. The numbers say how the "
        "schedulers compare on this generator, not what a plant would gain.",
        "",
        "Nominal: the plan as the planner sees it (processing at rate x planning availability). "
        "Replayed: the same job-to-machine assignment and sequence executed against the real "
        "stops of each window, processing at the nominal rate (the stops are explicit). "
        "Changeover minutes are work minutes, so the replay leaves them unchanged. Cells are "
        "median (q1 to q3).",
        "",
    ]
    for kind, title in (
        ("nominal", "Nominal (n = seeds)"),
        ("replayed", "Replayed (n = seeds x windows)"),
    ):
        L += [f"## {title}", "", "| Measure | " + " | ".join(ALGORITHMS) + " |"]
        L += ["|---|" + "---|" * len(ALGORITHMS)]
        for ms in MEASURES:
            L.append(
                f"| {MEASURE_LABEL[ms]} | "
                + " | ".join(_cell(doc[kind][a][ms]) for a in ALGORITHMS)
                + " |"
            )
        L.append("")
    L += [
        "## CP-SAT solver outcome",
        "",
        ", ".join(f"{k}: {v}" for k, v in sorted(S["status"].items()))
        + f" (of {S['n']} instances); stopped by: "
        + ", ".join(f"{k} {v}" for k, v in sorted(S["stop_reason"].items())),
        "",
        "## Paired: CP-SAT minus baseline",
        "",
        "| Comparison | Basis | Measure | n | CP-SAT better | equal | worse | Median diff | Mean diff |",  # noqa: E501
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for key, p in doc["paired"].items():
        base, kind, meas = parse_key(key)
        L.append(
            f"| CP-SAT vs {base.upper()} | {kind} | {MEASURE_LABEL[meas]} | {p['n']} | "
            f"{p['better']} ({p['share_better']:.0%}) | {p['equal']} | {p['worse']} | "
            f"{_n(p['median_diff'])} | {p['mean_diff']:.1f} |"
        )
    L += [
        "",
        "## Real stops by window",
        "",
        "Each cell: realised stopped time over time with data (the denominator planning "
        "availability uses, so it compares with the last row) / share of the window with no "
        "PIADE data at all. A gap is replayed as no stops, so a machine with gaps is stopped "
        "less, over the whole window, than the first figure suggests. Last row: the stopped "
        "share planning used, over covered time.",
        "",
        *window_table(doc),
        "",
        "## Seeds",
        "",
        "| Seed | Orders | Scheduled | Blocked | Load factor | Content sha256 |",
        "|---|---|---|---|---|---|",
    ]
    for s, sm in m["seed_meta"].items():
        L.append(
            f"| {s} | {sm['orders']} | {sm['scheduled']} | {sm['blocked']} | {sm['load_factor']} "
            f"| `{sm['content_sha256'][:12]}` |"
        )
    return "\n".join(L) + "\n"


def write(doc: dict[str, Any], out_dir: Path = RESULTS) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "plan.json"
    path.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n")
    path.with_suffix(".md").write_text(markdown(doc))
    return path


def main(argv: list[str] | None = None) -> int:
    import psycopg

    from linecopilot.config import get_settings

    ap = argparse.ArgumentParser(description="CP-SAT vs FIFO and EDD, nominal and replayed.")
    ap.add_argument("--db-url", help="default: the main database (owner role)")
    ap.add_argument("--seeds", type=int, nargs="+", default=list(SEEDS))
    ap.add_argument("--det-limit", type=float, default=None, help="eval-only CP-SAT limit")
    args = ap.parse_args(argv)
    with psycopg.connect(args.db_url or get_settings().database_url) as conn:
        doc = run(conn, tuple(args.seeds), args.det_limit)
    path = write(doc)
    print(f"wrote {path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
