"""Model fitting, selection, metrics and results on a synthetic frame (no database)."""

import json

import numpy as np
import pandas as pd
from frames import ALARMS, EP, IV, synthetic_dataset

from linecopilot.ml.dataset import build_dataset
from linecopilot.ml.score import top_contributions
from linecopilot.ml.train import (
    duration_quantiles,
    feature_hash,
    fit_target,
    make_lr,
    metric_rows,
    render_markdown,
    truncation_check,
)


def test_fit_target_selects_on_validation_and_scores_every_row():
    df, features = synthetic_dataset(seed=3)
    df.loc[df.index[:5], "label_observed"] = False
    res = fit_target(df, features, "long")
    assert res.selected in {"logistic", "hist_gb"}
    m = res.metrics
    assert set(m) == {"logistic", "hist_gb", "persistence", "hour_of_week"}
    for model in m:
        assert set(m[model]) == {"validation", "test"}
        for split in ("validation", "test"):
            row = m[model][split]
            assert 0 <= row["pr_auc"] <= 1 and row["alerts_top3"] > row["alerts_top1"] > 0
            assert row["recall_top1"] < row["recall_top3"]
    # Unobserved rows are negatives in the headline and dropped in the observed-only view.
    assert res.rows["train"] == res.rows_observed["train"] + 5
    assert res.base_rates["train"] <= res.base_rates_observed["train"]
    assert set(res.metrics_observed) == set(m)
    # The models see the signal; the baselines (which do not use f1) do not.
    assert m[res.selected]["test"]["pr_auc"] > m["persistence"]["test"]["pr_auc"] + 0.2
    assert set(res.per_machine_test) == set(m)
    assert set(res.per_machine_test["logistic"]) == {"s_1", "s_2", "s_3"}
    assert set(res.alert_thresholds) == {"s_1", "s_2", "s_3"}
    assert abs(res.shuffled_label_pr_auc - res.base_rates["test"]) < 0.03
    # Every row is scored, including unobserved ones; top features come from the logistic.
    s = res.scores
    assert len(s) == len(df) and s.score.notna().all()
    assert set(s.split) == {"train", "validation", "test"}
    assert all(len(tf) == 3 for tf in s.top_features)
    assert s.top_features.iloc[0][0]["feature"] in features


def test_top_contributions_sign_and_order():
    rng = np.random.default_rng(0)
    X = pd.DataFrame({"a": rng.normal(size=500), "b": rng.normal(size=500)})
    y = (X.a > 0).astype(int)
    lr = make_lr(1.0).fit(X, y)
    top = top_contributions(lr, X.iloc[[int(np.argmax(X.a))]], ["a", "b"], k=2)
    assert top[0][0]["feature"] == "a" and top[0][0]["contribution"] > 0
    assert top[0][0]["value"] == round(float(X.a.max()), 4)
    # Machine one-hot columns are never listed, however large their term.
    X["machine_s_1"] = (X.a > 0).astype(float)
    lr = make_lr(1.0).fit(X, y)
    top = top_contributions(lr, X.iloc[:20], ["a", "b", "machine_s_1"], k=2)
    assert all(f["feature"] != "machine_s_1" for row in top for f in row)


def test_metric_rows_and_markdown():
    df, features = synthetic_dataset(seed=4)
    res = {"long": fit_target(df, features, "long"), "any": fit_target(df, features, "any")}
    rows = metric_rows(res)
    keys = {(r["target"], r["model_name"], r["split"], r["metric"]) for r in rows}
    assert ("long", "persistence", "test", "pr_auc") in keys
    assert ("any", "data", "train", "base_rate") in keys
    assert ("long", res["long"].selected, "validation", "selected") in keys
    assert any(r["metric"] == "alert_threshold" and r["machine_id"] == "s_1" for r in rows)
    results = {
        "generated_at": "2026-01-01T00:00:00Z",
        "sklearn_version": "x",
        "feature_hash": feature_hash(features),
        "long_stop_s": 600,
        "duration_quantiles": {"all": {"p50": 1.0}},
        "targets": {k: v.to_dict() for k, v in res.items()},
        "leakage_checks": {
            "rows_checked": 10,
            "truncation_rows_checked": 5,
            "truncation_max_abs_diff": 0.0,
            "min_test_t": "2021-10-01",
            "max_train_t": "2021-06-30",
        },
        "unobserved_label_rows": 0,
        "runtime_s": 1.0,
    }
    json.dumps(results)
    md = render_markdown(results)
    assert "| long | persistence | test |" in md and "600" in md
    assert "Precision top 1" in md and "observed only" in md
    assert "second time" not in md  # run history lives in docs/data-notes.md, not here
    assert ("any", "logistic", "test", "pr_auc_observed") in keys


def test_duration_quantiles():
    ep = pd.DataFrame(
        {"machine_id": ["s_1"] * 4 + ["s_2"], "duration_s": [10.0, 20.0, 30.0, 700.0, 50.0]}
    )
    q = duration_quantiles(ep, 600)
    assert q["all"]["n"] == 5 and q["all"]["share_at_or_above_long"] == 0.2
    assert q["s_1"]["p50"] == 25.0
    assert feature_hash(["a", "b"]) != feature_hash(["b", "a"])


def test_truncation_check_on_small_frame():
    df, features = build_dataset(IV, EP, ALARMS)
    got = truncation_check(IV, EP, df, features, ALARMS, n=50)
    assert got == {"rows_checked": 5.0, "max_abs_diff": 0.0}
