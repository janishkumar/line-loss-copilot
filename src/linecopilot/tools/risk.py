"""stop_risk: next-hour stop risk per PIADE machine, read from the scores `make train-risk`
stored in ml.stop_risk_score, with the base rate, the alert threshold and the events that
fed the features. Read only; the model is never run here."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Literal

import psycopg
from pydantic import BaseModel, ConfigDict, Field

from linecopilot.ml.dataset import LONG_STOP_S
from linecopilot.tools.common import keyed_citations, machine_rows, rows, utc
from linecopilot.tools.envelope import CITATION_CAP, Citation, Result, Window, cap_citations

Target = Literal["long", "any"]
EVIDENCE_H = 24
DEFINITION = {
    "long": f"a PIADE stop episode of {LONG_STOP_S} s or more starts in [t, t + 1 h)",
    "any": "any PIADE stop episode starts in [t, t + 1 h)",
}
NOT_TRAINED = "no stop-risk scores in the database; run `make train-risk`"

ASSUMPTIONS = [
    "Scores come from the model selected on validation PR-AUC and were computed by "
    "`make train-risk`; the tool only reads them. Features use only data logged before t "
    "(an interval still open at t counts up to t). Splits: train t < 2021-07-01, "
    "validation to 2021-10-01, test after; a score in the train split is in-sample.",
    "A score ranks hours; it is a probability only for the gradient boosting model. Read "
    "it against base_rate (the machine's training-split share of hours with the event) and "
    "alert_threshold (the validation score above which as many hours are alerted as under "
    "the rule 'top 3 hours per machine per 8 h shift').",
    "top_features are the 3 largest coefficient x standardised value terms of the logistic "
    "model for that hour, even when the served score is from gradient boosting; the "
    "machine indicator columns are left out of this list.",
    f"Citations are the machine's events that start in the {EVIDENCE_H} h before t, stopped "
    "intervals first, then the most recent.",
]


class StopRiskArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    machine_id: str | None = Field(
        default=None, description="PIADE machine s_1..s_5; omit for every machine"
    )
    at: datetime = Field(
        description="use the score of the latest prediction hour at or before this time; "
        "no zone means UTC"
    )
    target: Target = Field(
        default="long",
        description=f"long: a stop of {LONG_STOP_S} s or more in the next hour; any: any stop",
    )


class FeatureContribution(BaseModel):
    feature: str
    contribution: float = Field(description="coefficient x standardised value (logistic)")
    value: float = Field(description="the feature's raw value at t")


class MachineRisk(BaseModel):
    machine_id: str
    t: datetime = Field(description="prediction hour; the score is for [t, t + 1 h)")
    covers_at: bool = Field(description="whether `at` falls inside [t, t + 1 h)")
    score: float
    model_name: str
    split: str
    base_rate: float | None = None
    alert_threshold: float | None = None
    alert: bool | None = Field(default=None, description="score >= alert_threshold")
    top_features: list[FeatureContribution]
    citations: list[Citation] = Field(default_factory=list)
    citation_count: int = 0


class RiskData(BaseModel):
    target: str
    definition: str
    rows: list[MachineRisk]


LATEST_SQL = """
SELECT DISTINCT ON (machine_id) machine_id, t, score, model_name, split, top_features
FROM ml.stop_risk_score
WHERE target = %(target)s AND t <= %(at)s AND (%(m)s::text IS NULL OR machine_id = %(m)s)
ORDER BY machine_id, t DESC"""

COVERAGE_SQL = """
SELECT machine_id, min(t) AS first_t, max(t) AS last_t
FROM ml.stop_risk_score
WHERE target = %(target)s AND (%(m)s::text IS NULL OR machine_id = %(m)s)
GROUP BY machine_id ORDER BY machine_id"""

METRIC_SQL = """
SELECT machine_id, metric, value FROM ml.model_metrics
WHERE target = %(target)s AND machine_id = ANY(%(ms)s)
  AND ((metric = 'base_rate' AND model_name = 'data' AND split = 'train')
       OR (metric = 'alert_threshold' AND split = 'validation' AND model_name = %(model)s))"""

# Events of each (machine, t) in the hours before t; the window length is bound.
EVIDENCE_SQL = """
SELECT g.key, 0 AS ord, e.event_id, e.event_type, e.state, e.start_ts, e.raw_table,
       e.source_file, e.raw_row_ids
FROM unnest(%(keys)s::text[], %(ts)s::timestamptz[]) AS g(key, t)
JOIN core.event e ON e.machine_id = g.key
WHERE e.start_ts >= g.t - %(span)s AND e.start_ts < g.t"""


def _coverage(cov: list[dict[str, Any]]) -> str:
    if not cov:
        return "no scores stored for this target"
    return "; ".join(
        f"{c['machine_id']} {c['first_t'].isoformat()} to {c['last_t'].isoformat()}" for c in cov
    )


def stop_risk(conn: psycopg.Connection, args: StopRiskArgs) -> Result[RiskData]:
    at = utc(args.at)
    win = Window(end=at, machine_id=args.machine_id)
    if args.machine_id is not None and not machine_rows(conn, args.machine_id):
        return Result(
            status="out_of_scope", window=win, missing=f"unknown machine_id {args.machine_id!r}"
        )
    (exists,) = conn.execute("SELECT to_regclass('ml.stop_risk_score') IS NOT NULL").fetchone()
    if not exists:
        return Result(status="insufficient_evidence", window=win, missing=NOT_TRAINED)
    p = {"target": args.target, "at": at, "m": args.machine_id}
    latest = rows(conn, LATEST_SQL, p)
    cov = rows(conn, COVERAGE_SQL, p)
    if not latest:
        what = args.machine_id or "any machine"
        return Result(
            status="insufficient_evidence",
            window=win,
            assumptions=ASSUMPTIONS,
            missing=f"no {args.target} stop-risk score for {what} at or before "
            f"{at.isoformat()}; scores cover {_coverage(cov)}",
        )

    model = latest[0]["model_name"]
    ms = [r["machine_id"] for r in latest]
    mets: dict[tuple[str, str], float] = {
        (r["machine_id"], r["metric"]): r["value"]
        for r in rows(conn, METRIC_SQL, {"target": args.target, "ms": ms, "model": model})
    }
    cites, n_raw = keyed_citations(
        conn,
        EVIDENCE_SQL,
        {
            "keys": ms,
            "ts": [r["t"] for r in latest],
            "span": timedelta(hours=EVIDENCE_H),
            "cap": CITATION_CAP,
        },
        "(state = 'stopped') DESC, start_ts DESC, event_id",
    )
    out = []
    for r in latest:
        m = r["machine_id"]
        thr = mets.get((m, "alert_threshold"))
        mc, mn = cites.get(m, ([], 0))
        out.append(
            MachineRisk(
                machine_id=m,
                t=r["t"],
                covers_at=at < r["t"] + timedelta(hours=1),
                score=r["score"],
                model_name=r["model_name"],
                split=r["split"],
                base_rate=mets.get((m, "base_rate")),
                alert_threshold=thr,
                alert=None if thr is None else r["score"] >= thr,
                top_features=[FeatureContribution(**f) for f in r["top_features"]],
                citations=mc,
                citation_count=mn,
            )
        )
    assumptions = list(ASSUMPTIONS)
    stale = [x.machine_id for x in out if not x.covers_at]
    if stale:
        assumptions.append(
            "For " + ", ".join(stale) + " the latest score is for an hour that ends before "
            "`at` (no data logged since), so it does not describe the hour containing `at`."
        )
    missing = None
    if args.machine_id is None:
        absent = sorted({c["machine_id"] for c in cov} - set(ms))
        if absent:
            missing = (
                f"no score at or before {at.isoformat()} for " + ", ".join(absent) + "; "
                f"scores cover {_coverage([c for c in cov if c['machine_id'] in absent])}"
            )
    return Result(
        status="ok",
        data=RiskData(target=args.target, definition=DEFINITION[args.target], rows=out),
        citations=cap_citations([c for x in out for c in x.citations])[0],
        citation_count=n_raw,
        window=Window(
            start=min(x.t for x in out) - timedelta(hours=EVIDENCE_H),
            end=at,
            machine_id=args.machine_id,
        ),
        assumptions=assumptions,
        missing=missing,
    )


# ml.model_metrics, for the web page ---------------------------------------------------------


class MetricRow(BaseModel):
    target: str
    model_name: str
    split: str
    metric: str
    value: float | None
    machine_id: str | None
    created_at: datetime


class RiskMetricsData(BaseModel):
    rows: list[MetricRow]


def risk_metrics(conn: psycopg.Connection) -> Result[RiskMetricsData]:
    (exists,) = conn.execute("SELECT to_regclass('ml.model_metrics') IS NOT NULL").fetchone()
    recs = (
        rows(
            conn,
            """SELECT target, model_name, split, metric, value, machine_id, created_at
               FROM ml.model_metrics
               ORDER BY target, model_name, split, metric, machine_id NULLS FIRST""",
        )
        if exists
        else []
    )
    if not recs:
        return Result(status="insufficient_evidence", missing=NOT_TRAINED)
    return Result(
        status="ok",
        data=RiskMetricsData(rows=[MetricRow(**r) for r in recs]),
        assumptions=[
            "Evaluation numbers from `make train-risk` on real PIADE data. machine_id null "
            "means all machines; model_name 'data' rows are base rates and counts. Compare "
            "PR-AUC with the base rate and the persistence baseline, not with 0.",
        ],
    )
