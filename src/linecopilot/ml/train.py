"""Train and evaluate the next-hour stop-risk models on PIADE. `make train-risk` runs this.

For each target (long: a stop of LONG_STOP_S or more starts in the next hour; any: any stop
starts), fit a logistic regression on standardised features and a histogram gradient
boosting model on the training split, pick each one's hyper-parameters on validation
PR-AUC, and compare both with two baselines (persistence, hour-of-week rate). The model
with the better validation PR-AUC is served; the test split is scored once. Rows whose next
hour has nothing logged have no observed label and are left out of fitting and metrics
(they still get a score)."""

from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
import sklearn
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from linecopilot.ml.dataset import (
    LONG_STOP_S,
    TEST_START,
    TRAIN_END,
    build_dataset,
    build_features,
    known_at,
    load_frames,
    top_alarm_codes,
)
from linecopilot.ml.metrics import (
    TOP_K,
    alert_mask,
    hour_of_week_scores,
    persistence_scores,
    pr_auc,
    top_k_precision_recall,
)
from linecopilot.ml.score import top_contributions, write_tables

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[3]
MODEL_DIR = ROOT / "data" / "models"
RESULTS_JSON = ROOT / "evals" / "results" / "stop_risk.json"
RESULTS_MD = ROOT / "evals" / "results" / "stop_risk.md"

TARGETS = {"long": "y_long", "any": "y_stop"}
LR_GRID = (0.01, 0.1, 1.0)
HGB_GRID = (
    {"learning_rate": 0.05, "max_leaf_nodes": 15},
    {"learning_rate": 0.1, "max_leaf_nodes": 31},
    {"learning_rate": 0.05, "max_leaf_nodes": 63},
)
MODELS = ("logistic", "hist_gb")
BASELINES = ("persistence", "hour_of_week")
EVAL_SPLITS = ("validation", "test")
QUANTILES = (0.5, 0.75, 0.9, 0.95, 0.99)
N_PERM = 5


def make_lr(c: float) -> Pipeline:
    return Pipeline(
        [
            ("scale", StandardScaler()),
            ("model", LogisticRegression(max_iter=2000, class_weight="balanced", C=c)),
        ]
    )


def make_hgb(**params: Any) -> HistGradientBoostingClassifier:
    return HistGradientBoostingClassifier(random_state=0, **params)


def feature_hash(features: list[str]) -> str:
    return hashlib.sha256("\n".join(features).encode()).hexdigest()[:16]


def check_split_gap(df: pd.DataFrame) -> None:
    """Raise unless every train time is more than 1 h before every validation and test
    time, and every validation time before every test time."""
    t = {s: df.loc[df.split == s, "t"] for s in ("train", "validation", "test")}
    gap = pd.Timedelta(hours=1)
    if len(t["train"]) and len(t["test"]) and not t["test"].min() > t["train"].max() + gap:
        raise ValueError("split overlap: a test time is within 1 h of a train time")
    if len(t["train"]) and len(t["validation"]):
        if not t["validation"].min() > t["train"].max():
            raise ValueError("split overlap: a validation time is not after every train time")
    if len(t["validation"]) and len(t["test"]) and not t["test"].min() > t["validation"].max():
        raise ValueError("split overlap: a test time is not after every validation time")


def _observed(df: pd.DataFrame, split: str) -> pd.DataFrame:
    return df[(df.split == split) & df.label_observed.astype(bool)]


def _score(model: Any, X: pd.DataFrame) -> np.ndarray:
    return model.predict_proba(X)[:, 1]


def shuffled_label_pr_auc(
    df: pd.DataFrame,
    features: list[str],
    y: str,
    seed: int = 0,
    with_real: bool = False,
    n_perm: int = N_PERM,
) -> float | tuple[float, float]:
    """Mean test PR-AUC of gradient boosting models fitted on permuted training labels.

    Boosting with its default early stopping stays close to a constant on labels with no
    signal, so its test PR-AUC should sit near the test base rate. (A logistic model was
    tried first: fitted to shuffled labels it still orders rows along a random direction
    in feature space, so with informative features a single permutation lands far above
    or below the base rate.) The mean over n_perm permutations is reported. A label leaking
    into a feature is not caught by this alone; dataset.known_at and the max_source_ts
    check cover that."""
    tr, te = _observed(df, "train"), _observed(df, "test")
    rng = np.random.default_rng(seed)
    vals = []
    for _ in range(n_perm):
        perm = rng.permutation(tr[y].to_numpy())
        vals.append(pr_auc(te[y], _score(make_hgb().fit(tr[features], perm), te[features])))
    shuffled = float(np.mean(vals))
    if not with_real:
        return shuffled
    real = pr_auc(te[y], _score(make_lr(1.0).fit(tr[features], tr[y]), te[features]))
    return shuffled, real


def truncation_check(
    intervals: pd.DataFrame,
    episodes: pd.DataFrame,
    df: pd.DataFrame,
    features: list[str],
    alarms: list[str],
    n: int = 200,
    seed: int = 0,
) -> dict[str, float]:
    """Rebuild the features of n sampled rows from only what was known at each row's t
    (dataset.known_at) and return the largest absolute difference from the full build."""
    machines = sorted(intervals.machine_id.unique())
    sample = df.sample(n=min(n, len(df)), random_state=seed)
    by_m = {m: (intervals[intervals.machine_id == m], episodes[episodes.machine_id == m])
            for m in machines}  # fmt: skip
    worst = 0.0
    for r in sample.itertuples(index=False):
        iv, ep = known_at(*by_m[r.machine_id], r.t)
        one = pd.DataFrame({"machine_id": [r.machine_id], "t": [r.t]})
        cut = build_features(iv, ep, one, alarms, machines)
        full = sample[(sample.machine_id == r.machine_id) & (sample.t == r.t)]
        diff = np.abs(cut[features].to_numpy(float) - full[features].to_numpy(float)).max()
        worst = max(worst, float(diff))
    return {"rows_checked": float(len(sample)), "max_abs_diff": worst}


@dataclass
class TargetResult:
    target: str
    selected: str
    hyperparameters: dict[str, Any]
    search: list[dict[str, Any]]
    base_rates: dict[str, float]
    metrics: dict[str, dict[str, dict[str, float]]]
    per_machine_test: dict[str, dict[str, float]]
    per_machine_base_rates: dict[str, dict[str, float]]
    train_pr_auc: dict[str, float]
    shuffled_label_pr_auc: float
    alert_thresholds: dict[str, float]
    rows: dict[str, int]
    positives: dict[str, int]
    scores: pd.DataFrame = field(repr=False)
    models: dict[str, Any] = field(repr=False)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d.pop("scores")
        d.pop("models")
        return _clean(d)


def _clean(x: Any) -> Any:
    """NaN -> None and numpy scalars -> Python, for JSON."""
    if isinstance(x, dict):
        return {k: _clean(v) for k, v in x.items()}
    if isinstance(x, list | tuple):
        return [_clean(v) for v in x]
    if isinstance(x, np.generic):
        x = x.item()
    if isinstance(x, float) and np.isnan(x):
        return None
    return x


def _evaluate(df: pd.DataFrame, score: np.ndarray, y: str) -> dict[str, float]:
    d = df[["machine_id", "t", "shift", y]].copy()
    d["score"] = score
    p, r, n = top_k_precision_recall(d, "score", y, TOP_K)
    return {
        "pr_auc": pr_auc(d[y], d.score),
        "precision_top3": p,
        "recall_top3": r,
        "alerts": float(n),
    }


def _per_machine(df: pd.DataFrame, score: np.ndarray, y: str) -> dict[str, float]:
    d = df[["machine_id", y]].assign(score=score)
    return {m: pr_auc(g[y], g.score) for m, g in d.groupby("machine_id", sort=True)}


def fit_target(df: pd.DataFrame, features: list[str], target: str) -> TargetResult:
    """Fit, select and evaluate both models and both baselines for one target."""
    y = TARGETS[target]
    check_split_gap(df)
    tr, va, te = (_observed(df, s) for s in ("train", "validation", "test"))
    splits = {"train": tr, "validation": va, "test": te}

    search: list[dict[str, Any]] = []
    best: dict[str, tuple[float, Any, dict[str, Any]]] = {}
    candidates = [("logistic", {"C": c}, make_lr(c)) for c in LR_GRID]
    candidates += [("hist_gb", dict(p), make_hgb(**p)) for p in HGB_GRID]
    for name, params, model in candidates:
        model.fit(tr[features], tr[y])
        v = pr_auc(va[y], _score(model, va[features]))
        search.append({"model": name, "params": params, "validation_pr_auc": v})
        log.info("%s %s %s validation PR-AUC %.4f", target, name, params, v)
        if name not in best or v > best[name][0]:
            best[name] = (v, model, params)
    models = {name: best[name][1] for name in MODELS}
    selected = max(MODELS, key=lambda n: best[n][0])

    def scores_for(name: str, part: pd.DataFrame) -> np.ndarray:
        if name in models:
            return _score(models[name], part[features])
        if name == "persistence":
            return persistence_scores(part).to_numpy()
        return hour_of_week_scores(tr, part, y).to_numpy()

    names = [*MODELS, *BASELINES]
    metrics = {n: {s: _evaluate(splits[s], scores_for(n, splits[s]), y) for s in EVAL_SPLITS}
               for n in names}  # fmt: skip
    per_machine = {n: _per_machine(te, scores_for(n, te), y) for n in names}

    # Alert threshold per machine: the validation score above which the same share of
    # hours is alerted as under the top-3-per-shift rule.
    v = va[["machine_id", "t", "shift"]].assign(score=scores_for(selected, va))
    v["alert"] = alert_mask(v, "score", TOP_K)
    thresholds = {
        m: float(g.score.quantile(1 - g.alert.mean())) for m, g in v.groupby("machine_id")
    }

    served = models[selected]
    contrib = top_contributions(models["logistic"], df, features)
    scores = pd.DataFrame(
        {
            "machine_id": df.machine_id.to_numpy(),
            "t": df.t.to_numpy(),
            "target": target,
            "model_name": selected,
            "score": _score(served, df[features]),
            "top_features": contrib,
            "split": df.split.to_numpy(),
        }
    )
    scores["t"] = pd.to_datetime(scores.t, utc=True)
    return TargetResult(
        target=target,
        selected=selected,
        hyperparameters={n: best[n][2] for n in MODELS},
        search=search,
        base_rates={s: float(p[y].mean()) for s, p in splits.items()},
        metrics=metrics,
        per_machine_test=per_machine,
        per_machine_base_rates={
            s: {m: float(g[y].mean()) for m, g in p.groupby("machine_id", sort=True)}
            for s, p in splits.items()
        },
        train_pr_auc={n: pr_auc(tr[y], scores_for(n, tr)) for n in MODELS},
        shuffled_label_pr_auc=float(shuffled_label_pr_auc(df, features, y)),
        alert_thresholds=thresholds,
        rows={s: len(p) for s, p in splits.items()},
        positives={s: int(p[y].sum()) for s, p in splits.items()},
        scores=scores,
        models=models,
    )


def metric_rows(results: dict[str, TargetResult]) -> list[dict[str, Any]]:
    """Long-format rows for ml.model_metrics."""
    out: list[dict[str, Any]] = []

    def add(target, model, split, metric, value, machine=None):
        out.append(
            {
                "target": target,
                "model_name": model,
                "split": split,
                "metric": metric,
                "value": None if value is None else float(value),
                "machine_id": machine,
            }
        )

    for t, r in results.items():
        for split, br in r.base_rates.items():
            add(t, "data", split, "base_rate", br)
            add(t, "data", split, "rows", r.rows[split])
            add(t, "data", split, "positives", r.positives[split])
            for m, v in r.per_machine_base_rates[split].items():
                add(t, "data", split, "base_rate", v, m)
        for model, by_split in r.metrics.items():
            for split, ms in by_split.items():
                for metric, v in ms.items():
                    add(t, model, split, metric, v)
        for model, by_m in r.per_machine_test.items():
            for m, v in by_m.items():
                add(t, model, "test", "pr_auc", v, m)
        add(t, r.selected, "validation", "selected", 1.0)
        add(t, r.selected, "test", "shuffled_label_pr_auc", r.shuffled_label_pr_auc)
        for m, v in r.alert_thresholds.items():
            add(t, r.selected, "validation", "alert_threshold", v, m)
    return out


def duration_quantiles(episodes: pd.DataFrame, long_s: float) -> dict[str, dict[str, float]]:
    def q(d: pd.Series) -> dict[str, float]:
        out = {f"p{int(p * 100)}": float(d.quantile(p)) for p in QUANTILES}
        out["n"] = int(len(d))
        out["share_at_or_above_long"] = float((d >= long_s).mean())
        return out

    res = {"all": q(episodes.duration_s)}
    for m, g in episodes.groupby("machine_id", sort=True):
        res[m] = q(g.duration_s)
    return res


def _f(x: float | None, nd: int = 3) -> str:
    return "n/a" if x is None else f"{x:.{nd}f}"


def render_markdown(res: dict[str, Any]) -> str:
    L = [
        "# Next-hour stop risk on PIADE",
        "",
        f"Generated {res['generated_at']} with scikit-learn {res['sklearn_version']}, "
        f"feature list hash {res['feature_hash']}. Real PIADE data only.",
        "",
        f"Long stop: a stop episode of {res['long_stop_s']} s or more. PR-AUC is average "
        "precision; compare it with the base rate (the share of hours with the event), not "
        f"with 0. Alert volume: top {TOP_K} hours per machine per 8 h shift.",
        "",
        "| Target | Model | Split | PR-AUC | Base rate | Precision at top 3 | Recall at top 3 |",
        "|---|---|---|---|---|---|---|",
    ]
    for t, r in res["targets"].items():
        for model, by_split in r["metrics"].items():
            for split in EVAL_SPLITS:
                m = by_split[split]
                name = f"{model} (served)" if model == r["selected"] else model
                L.append(
                    f"| {t} | {name} | {split} | {_f(m['pr_auc'])} | "
                    f"{_f(r['base_rates'][split])} | {_f(m['precision_top3'])} | "
                    f"{_f(m['recall_top3'])} |"
                )
    L += ["", "Per machine, test PR-AUC (base rate in brackets):", ""]
    for t, r in res["targets"].items():
        machines = sorted(r["per_machine_base_rates"]["test"])
        L += [
            f"| {t} | " + " | ".join(machines) + " |",
            "|---|" + "---|" * len(machines),
        ]
        for model, by_m in r["per_machine_test"].items():
            cells = [
                f"{_f(by_m.get(m))} ({_f(r['per_machine_base_rates']['test'][m])})"
                for m in machines
            ]
            L.append(f"| {model} | " + " | ".join(cells) + " |")
        L.append("")
    L += [
        "Leakage checks: every row's latest source timestamp is before t "
        f"({res['leakage_checks']['rows_checked']} rows); features rebuilt from only the data "
        f"known at t match the full build on {res['leakage_checks']['truncation_rows_checked']} "
        "sampled rows (largest difference "
        f"{res['leakage_checks']['truncation_max_abs_diff']:.2g}); the first test hour is "
        f"{res['leakage_checks']['min_test_t']}, the last train hour "
        f"{res['leakage_checks']['max_train_t']}. Shuffled-label test PR-AUC (mean of "
        f"{N_PERM} gradient boosting models fitted on permuted training labels) next to the "
        "test base rate:",
        "",
        "| Target | Shuffled-label PR-AUC | Test base rate |",
        "|---|---|---|",
    ]
    for t, r in res["targets"].items():
        L.append(f"| {t} | {_f(r['shuffled_label_pr_auc'])} | {_f(r['base_rates']['test'])} |")
    q = res["duration_quantiles"]
    L += ["", "Stop episode duration quantiles (seconds):", ""]
    keys = [k for k in ("p50", "p75", "p90", "p95", "p99") if k in q["all"]]
    L += ["| Machine | " + " | ".join(keys) + " | Episodes | Share long |"]
    L += ["|---|" + "---|" * (len(keys) + 2)]
    for m, v in q.items():
        L.append(
            f"| {m} | "
            + " | ".join(f"{v[k]:.0f}" for k in keys)
            + f" | {v.get('n', '')} | {_f(v.get('share_at_or_above_long'))} |"
        )
    L += ["", f"Runtime: {res['runtime_s']:.0f} s.", ""]
    return "\n".join(L)


def main() -> None:
    from linecopilot.config import get_settings
    from linecopilot.db import connect

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    t0 = time.monotonic()
    with connect(get_settings().database_url) as conn:
        iv, ep = load_frames(conn)
        log.info("loaded %d intervals, %d episodes", len(iv), len(ep))
        alarms = top_alarm_codes(iv)
        df, features = build_dataset(iv, ep, alarms, long_s=LONG_STOP_S)
        log.info("dataset %d rows, %d features", len(df), len(features))
        bad = df.max_source_ts.notna() & (df.max_source_ts >= df.t)
        if bad.any():
            raise RuntimeError(f"{int(bad.sum())} rows read data at or after t")
        trunc = truncation_check(iv, ep, df, features, alarms)
        log.info("truncation check %s", trunc)
        if trunc["max_abs_diff"] > 1e-6:
            raise RuntimeError(f"features change when the future is removed: {trunc}")
        results = {t: fit_target(df, features, t) for t in TARGETS}
        fhash = feature_hash(features)
        MODEL_DIR.mkdir(parents=True, exist_ok=True)
        for t, r in results.items():
            joblib.dump(
                {
                    "target": t,
                    "selected": r.selected,
                    "models": r.models,
                    "features": features,
                    "feature_hash": fhash,
                    "sklearn_version": sklearn.__version__,
                    "long_stop_s": LONG_STOP_S,
                },
                MODEL_DIR / f"stop_risk_{t}.joblib",
            )
        scores = pd.concat([r.scores for r in results.values()], ignore_index=True)
        write_tables(conn, scores, metric_rows(results))
        conn.commit()
    tr = df[df.split == "train"]
    res = {
        "generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "sklearn_version": sklearn.__version__,
        "feature_hash": fhash,
        "features": features,
        "long_stop_s": LONG_STOP_S,
        "splits": {
            "train": f"t < {TRAIN_END.date()}",
            "validation": f"{TRAIN_END.date()} <= t < {TEST_START.date()}",
            "test": f"t >= {TEST_START.date()}",
        },
        "prediction_rows": int(len(df)),
        "unobserved_label_rows": int((~df.label_observed.astype(bool)).sum()),
        "top_alarms_from_train": alarms,
        "duration_quantiles": duration_quantiles(ep, LONG_STOP_S),
        "leakage_checks": {
            "max_source_ts_before_t": True,
            "rows_checked": int(len(df)),
            "truncation_rows_checked": int(trunc["rows_checked"]),
            "truncation_max_abs_diff": trunc["max_abs_diff"],
            "min_test_t": str(df.loc[df.split == "test", "t"].min()),
            "max_train_t": str(tr.t.max()),
        },
        "targets": {t: r.to_dict() for t, r in results.items()},
        "runtime_s": time.monotonic() - t0,
    }
    RESULTS_JSON.write_text(json.dumps(_clean(res), indent=2) + "\n")
    RESULTS_MD.write_text(render_markdown(_clean(res)))
    log.info("done in %.0f s", res["runtime_s"])


if __name__ == "__main__":
    main()
