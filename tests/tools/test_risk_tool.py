"""stop_risk and the ml tables against the fixture database.

The fixture spans a few hours of January 2020, too little to train on, so the scores and
metrics here are hand-written test rows put through the same writer as `make train-risk`."""

import os
from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from linecopilot.api.app import create_app
from linecopilot.ml.dataset import build_dataset, load_frames
from linecopilot.ml.score import write_tables
from linecopilot.tools.registry import call_tool
from linecopilot.tools.risk import NOT_TRAINED, StopRiskArgs, risk_metrics, stop_risk

pytestmark = pytest.mark.db


def at(h: int, m: int = 0, day: int = 1) -> datetime:
    return datetime(2020, 1, day, h, m, tzinfo=UTC)


TF = [
    {"feature": "running_s_1h", "contribution": 0.8, "value": 3000.0},
    {"feature": "idle_s_1h", "contribution": -0.2, "value": 300.0},
    {"feature": "ep_count_1h", "contribution": 0.1, "value": 1.0},
]


def score_rows() -> pd.DataFrame:
    recs = [
        ("s_2", at(14), "long", 0.10),
        ("s_2", at(15), "long", 0.30),
        ("s_2", at(16), "long", 0.05),
        ("s_2", at(15), "any", 0.70),
        ("s_3", at(8, day=2), "long", 0.20),
    ]
    df = pd.DataFrame(recs, columns=["machine_id", "t", "target", "score"])
    df["t"] = pd.to_datetime(df.t, utc=True)
    df["model_name"] = "hist_gb"
    df["split"] = "train"
    df["top_features"] = [TF] * len(df)
    return df


METRICS = [
    {"target": "long", "model_name": "data", "split": "train", "metric": "base_rate",
     "value": 0.05, "machine_id": "s_2"},
    {"target": "long", "model_name": "hist_gb", "split": "validation",
     "metric": "alert_threshold", "value": 0.2, "machine_id": "s_2"},
    {"target": "long", "model_name": "logistic", "split": "validation",
     "metric": "alert_threshold", "value": 0.9, "machine_id": "s_2"},
    {"target": "long", "model_name": "hist_gb", "split": "test", "metric": "pr_auc",
     "value": float("nan"), "machine_id": None},
]  # fmt: skip


@pytest.fixture
def scored(built):
    built.execute("DROP SCHEMA IF EXISTS ml CASCADE")
    write_tables(built, score_rows(), METRICS)
    yield built
    built.execute("DROP SCHEMA IF EXISTS ml CASCADE")


def test_not_trained_and_unknown_machine(built):
    built.execute("DROP SCHEMA IF EXISTS ml CASCADE")
    r = stop_risk(built, StopRiskArgs(machine_id="s_2", at=at(15)))
    assert r.status == "insufficient_evidence" and r.missing == NOT_TRAINED
    assert risk_metrics(built).status == "insufficient_evidence"
    r = stop_risk(built, StopRiskArgs(machine_id="s_9", at=at(15)))
    assert r.status == "out_of_scope" and "s_9" in r.missing


def test_latest_score_with_base_rate_threshold_and_citations(scored):
    r = stop_risk(scored, StopRiskArgs(machine_id="s_2", at=at(15, 30)))
    assert r.status == "ok", r.missing
    (row,) = r.data.rows
    assert row.t == at(15) and row.covers_at and row.score == 0.30
    assert row.base_rate == 0.05
    assert row.alert_threshold == 0.2 and row.alert is True  # the served model's threshold
    assert [f.feature for f in row.top_features] == [f["feature"] for f in TF]
    # s_2 events starting in the 24 h before 15:00: the 13 intervals from 12:00 to 14:56.
    assert row.citation_count == 13 == r.citation_count
    assert {c.raw_table for c in r.citations} == {"piade_raw"}
    assert r.window.start == at(15) - timedelta(hours=24) and r.window.end == at(15, 30)
    assert "[t, t + 1 h)" in r.data.definition and "600" in r.data.definition


def test_stopped_events_cited_first(scored):
    r = stop_risk(scored, StopRiskArgs(machine_id="s_2", at=at(16)))
    (row,) = r.data.rows
    assert row.t == at(16) and row.alert is False
    # The 24 h before 16:00 hold all 17 s_2 intervals, 4 of them stopped (12:40, 15:16,
    # 15:21, 15:26): stopped first, most recent first.
    ids = [c.event_id for c in row.citations]
    states = dict(
        scored.execute(
            "SELECT event_id, state FROM core.event WHERE event_id = ANY(%s)", (ids,)
        ).fetchall()
    )
    assert row.citation_count == 17
    got = [states[i] for i in ids]
    assert got[:4] == ["stopped"] * 4 and "stopped" not in got[4:] and len(got) == 17
    starts = dict(
        scored.execute(
            "SELECT event_id, start_ts FROM core.event WHERE event_id = ANY(%s)", (ids,)
        ).fetchall()
    )
    assert starts[ids[0]] > starts[ids[1]] > starts[ids[2]] > starts[ids[3]]
    assert starts[ids[4]] > starts[ids[5]]


def test_no_score_before_at_and_stale_score(scored):
    r = stop_risk(scored, StopRiskArgs(machine_id="s_2", at=at(13)))
    assert r.status == "insufficient_evidence"
    assert "s_2 2020-01-01T14:00:00+00:00 to 2020-01-01T16:00:00+00:00" in r.missing
    r = stop_risk(scored, StopRiskArgs(machine_id="s_2", at=at(20)))
    assert r.status == "ok" and not r.data.rows[0].covers_at
    assert any("does not describe" in a for a in r.assumptions)
    # A zone-less time is UTC.
    r = stop_risk(scored, StopRiskArgs(machine_id="s_2", at=datetime(2020, 1, 1, 15, 30)))
    assert r.data.rows[0].t == at(15)


def test_all_machines_and_targets(scored):
    r = stop_risk(scored, StopRiskArgs(at=at(15, 30)))
    assert r.status == "ok"
    assert [x.machine_id for x in r.data.rows] == ["s_2"]
    assert "s_3" in r.missing  # s_3's only score is later
    r = stop_risk(scored, StopRiskArgs(at=at(9, day=2)))
    assert [x.machine_id for x in r.data.rows] == ["s_2", "s_3"] and r.missing is None
    s3 = r.data.rows[1]
    assert s3.base_rate is None and s3.alert_threshold is None and s3.alert is None
    r = stop_risk(scored, StopRiskArgs(machine_id="s_2", at=at(16, 30), target="any"))
    assert r.data.rows[0].score == 0.70 and r.data.rows[0].t == at(15)
    assert "any PIADE stop" in r.data.definition


def test_registry_api_and_metrics(scored):
    r = call_tool(scored, "stop_risk", {"machine_id": "s_2", "at": "2020-01-01T15:30:00Z"})
    assert r.status == "ok"
    r = call_tool(scored, "stop_risk", {"at": "2020-01-01T15:30:00Z", "target": "huge"})
    assert r.status == "out_of_scope"
    m = risk_metrics(scored)
    assert m.status == "ok" and len(m.data.rows) == len(METRICS)
    assert any(x.value is None for x in m.data.rows)  # NaN is stored as null
    client = TestClient(create_app(os.environ["LINECOPILOT_TEST_DB_URL"]))
    body = client.get("/api/risk", params={"machine_id": "s_2", "at": "2020-01-01T15:30:00Z"})
    assert body.status_code == 200 and body.json()["status"] == "ok"
    assert body.json()["data"]["rows"][0]["score"] == 0.30
    body = client.get("/api/risk/metrics").json()
    assert body["status"] == "ok" and len(body["data"]["rows"]) == len(METRICS)


def test_write_tables_replaces_rows(scored):
    write_tables(scored, score_rows().iloc[:2], METRICS[:1])
    (n,) = scored.execute("SELECT count(*) FROM ml.stop_risk_score").fetchone()
    (k,) = scored.execute("SELECT count(*) FROM ml.model_metrics").fetchone()
    assert (n, k) == (2, 1)


def test_dataset_from_fixture_database(built):
    iv, ep = load_frames(built)
    assert set(iv.machine_id) == {"s_1", "s_2", "s_3"}
    assert set(iv.state) <= {"running", "idle", "off", "stopped"}
    # s_1: 12:25+12:40 (adjacent, one episode) and 16:45; s_2: 12:40, 15:16+15:21 (4 s
    # apart), 15:26 (6 s after); s_3: 07:00.
    assert ep.groupby("machine_id").size().to_dict() == {"s_1": 2, "s_2": 3, "s_3": 1}
    df, features = build_dataset(iv, ep, [])
    s2 = df[df.machine_id == "s_2"].set_index("t")
    # s_2 logs 12:00-12:50 and 13:50-15:31.
    assert [t.hour for t in s2.index] == [13, 14, 15, 16]
    assert s2.loc[at(16), "ep_count_1h"] == 2 and s2.loc[at(16), "stopped_s_1h"] == 900
    assert s2.loc[at(13), "y_stop"] == 0 and s2.loc[at(15), "y_stop"] == 1
    assert (df.max_source_ts < df.t).all()
