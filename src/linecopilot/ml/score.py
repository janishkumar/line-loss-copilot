"""Per-row feature contributions and the ml.* tables the stop_risk tool reads."""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import psycopg
from sklearn.pipeline import Pipeline

SCHEMA_FILE = Path(__file__).resolve().parents[3] / "sql" / "ml_schema.sql"
TOP_FEATURES = 3
# Machine one-hot columns are constant for a machine, so "not being machine s_5" says
# nothing about this hour; they are left out of the explanation (not out of the model).
EXPLAIN_SKIP = ("machine_",)


def top_contributions(
    lr: Pipeline, X: pd.DataFrame, features: list[str], k: int = TOP_FEATURES
) -> list[list[dict[str, Any]]]:
    """For each row, the k features with the largest |coef x standardised value| in the
    logistic model, with the signed contribution and the raw value. Columns starting with
    an EXPLAIN_SKIP prefix are not listed."""
    z = lr.named_steps["scale"].transform(X[features])
    coef = lr.named_steps["model"].coef_[0]
    contrib = z * coef
    raw = X[features].to_numpy(float)
    skip = np.array([f.startswith(EXPLAIN_SKIP) for f in features])
    rank = np.where(skip, -1.0, np.abs(contrib))
    top = np.argsort(-rank, axis=1, kind="stable")[:, :k]
    return [
        [
            {
                "feature": features[j],
                "contribution": round(float(contrib[i, j]), 4),
                "value": round(float(raw[i, j]), 4),
            }
            for j in top[i]
        ]
        for i in range(len(X))
    ]


def apply_schema(conn: psycopg.Connection) -> None:
    conn.execute(SCHEMA_FILE.read_text())


def write_tables(
    conn: psycopg.Connection, scores: pd.DataFrame, metrics: Iterable[dict[str, Any]]
) -> None:
    """Replace ml.stop_risk_score and ml.model_metrics in one transaction.

    `scores` columns: machine_id, t, target, model_name, score, top_features (list), split.
    `metrics` rows: target, model_name, split, metric, value, machine_id (optional)."""
    with conn.transaction():
        apply_schema(conn)
        conn.execute("DELETE FROM ml.stop_risk_score")
        conn.execute("DELETE FROM ml.model_metrics")
        with conn.cursor() as cur:
            with cur.copy(
                "COPY ml.stop_risk_score (machine_id, t, target, model_name, score, "
                "top_features, split) FROM STDIN"
            ) as cp:
                for r in scores.itertuples(index=False):
                    cp.write_row(
                        (
                            r.machine_id,
                            r.t.to_pydatetime(),
                            r.target,
                            r.model_name,
                            float(r.score),
                            json.dumps(r.top_features),
                            r.split,
                        )
                    )
            cur.executemany(
                "INSERT INTO ml.model_metrics (target, model_name, split, metric, value, "
                "machine_id) VALUES (%s, %s, %s, %s, %s, %s)",
                [
                    (
                        m["target"],
                        m["model_name"],
                        m["split"],
                        m["metric"],
                        None if m["value"] is None or np.isnan(m["value"]) else m["value"],
                        m.get("machine_id"),
                    )
                    for m in metrics
                ],
            )
