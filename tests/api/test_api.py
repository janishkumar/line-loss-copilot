"""API routes against the fixture database built by dbt (shared `built` fixture)."""

import os

import pytest
from fastapi.testclient import TestClient

from linecopilot.api.app import create_app
from linecopilot.api.models import CITATION_CAP

pytestmark = pytest.mark.db


@pytest.fixture(scope="module")
def client(built):
    return TestClient(create_app(os.environ["LINECOPILOT_TEST_DB_URL"]))


def get(client, path, **params):
    r = client.get(path, params=params)
    assert r.status_code == 200, r.text
    return r.json()


def test_health(client):
    assert get(client, "/api/health") == {"status": "ok"}


def test_assets_lists_lines_and_machines(client):
    body = get(client, "/api/assets")
    assert body["status"] == "ok"
    lines = {x["line_id"]: x for x in body["data"]["lines"]}
    assert {"brick", "s_1"} <= set(lines)
    assert lines["s_1"]["machines"] == ["s_1"] and lines["brick"]["machines"] == []
    assert {m["machine_id"] for m in body["data"]["machines"]} >= {"s_1"}


def test_oee_brick_shift_has_citations(client, built):
    body = get(client, "/api/oee", line_id="brick", group="shift")
    assert body["status"] == "ok"
    assert body["window"]["start"] and body["window"]["end"]
    rows = {r["key"]: r for r in body["data"]["rows"]}
    row = rows["brick:2026-02-02"]
    assert row["metrics"]["oee_pub"] == pytest.approx(0.687063235)
    assert row["metrics"]["availability_calc"] is not None
    # the shift's production_count event plus its in-OEE stops; the 120-min
    # "Not included" stop on that date is not cited.
    n_stops = built.execute(
        "SELECT count(*) FROM core.event WHERE shift_id = 'brick:2026-02-02'"
        " AND event_type = 'stop' AND stop_type <> 'Planned - Not included in OEE'"
    ).fetchone()[0]
    assert n_stops == 3
    assert row["citation_count"] == n_stops + 1
    tables = sorted(c["raw_table"] for c in row["citations"])
    assert tables == ["brick_downtime"] * n_stops + ["brick_oee"]
    for c in row["citations"]:
        assert c["source_file"].startswith("brick/") and c["raw_row_id"] >= 1 and c["event_id"]
    # top level: events in the window, capped, with the true total
    assert 0 < len(body["citations"]) <= CITATION_CAP
    total = built.execute("SELECT count(*) FROM core.event WHERE line_id = 'brick'").fetchone()[0]
    assert body["citation_count"] == total
    # every shift row's citation count is the DB count of its evidence; a date with only
    # "Not included" stops has none, and that is reported as 0, not hidden
    expected = dict(
        built.execute(
            "SELECT shift_id, count(*) FROM core.event WHERE source_system = 'brick'"
            " AND (event_type = 'production_count'"
            "      OR stop_type <> 'Planned - Not included in OEE')"
            " GROUP BY 1"
        ).fetchall()
    )
    for key, r in rows.items():
        assert r["citation_count"] == expected.get(key, 0)
    assert sum(r["citation_count"] > 0 for r in rows.values()) > 5


def test_source_rows_match_raw_table(client, built):
    body = get(client, "/api/oee", line_id="brick", group="shift")
    row = next(r for r in body["data"]["rows"] if r["key"] == "brick:2026-02-02")
    for c in row["citations"]:
        src = get(client, f"/api/events/{c['event_id']}/source")
        assert src["status"] == "ok"
        (raw,) = src["data"]["rows"]
        table = c["raw_table"]
        cur = built.execute(
            f"SELECT * FROM raw.{table} WHERE source_file = %s AND source_row = %s",
            (c["source_file"], c["raw_row_id"]),
        )
        cols = [d.name for d in cur.description]
        (expected,) = [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]
        assert raw == expected  # all columns, as loaded
        assert raw["source_file"] == c["source_file"] and raw["source_row"] == c["raw_row_id"]
        assert src["data"]["raw_table"] == table


def test_source_rows_piade_and_unknown_event(client, built):
    eid, rid = built.execute(
        "SELECT event_id, raw_row_ids[1] FROM core.event WHERE raw_table = 'piade_raw' LIMIT 1"
    ).fetchone()
    src = get(client, f"/api/events/{eid}/source")
    assert src["data"]["rows"][0]["source_row"] == rid
    assert src["data"]["rows"][0]["machine_id"] == "s_1"
    missing = get(client, "/api/events/999999999/source")
    assert missing["status"] == "out_of_scope" and "no event" in missing["missing"]


def test_empty_window_is_insufficient_evidence(client):
    # s_1 has data; this window is before its coverage. Must not return an OEE of 0.
    body = get(
        client,
        "/api/oee",
        machine_id="s_1",
        start="2015-01-01T00:00:00Z",
        end="2015-02-01T00:00:00Z",
        group="shift",
    )
    assert body["status"] == "insufficient_evidence"
    assert body["data"] is None and "coverage is" in body["missing"]
    assert body["window"]["start"].startswith("2015-01-01")
    brick = get(
        client, "/api/oee", line_id="brick", start="2015-01-01", end="2015-01-08", group="month"
    )
    assert brick["status"] == "insufficient_evidence" and brick["data"] is None


def test_unknown_machine_is_out_of_scope(client):
    body = get(client, "/api/oee", machine_id="s_99")
    assert body["status"] == "out_of_scope" and "s_99" in body["missing"]
    assert get(client, "/api/oee", line_id="nope")["status"] == "out_of_scope"
    assert get(client, "/api/oee", line_id="brick", machine_id="s_1")["status"] == "out_of_scope"
    assert get(client, "/api/oee")["status"] == "out_of_scope"


def test_bad_group_and_window_rejected(client):
    assert client.get("/api/oee", params={"line_id": "s_1", "group": "week"}).status_code == 422
    r = client.get(
        "/api/oee", params={"line_id": "s_1", "start": "2020-02-01", "end": "2020-01-01"}
    )
    assert r.status_code == 422


def test_piade_shift_rows_match_mart_and_cite_intervals(client, built):
    body = get(client, "/api/oee", machine_id="s_1", group="shift")
    assert body["status"] == "ok" and body["data"]["source_system"] == "piade"
    assert any("p95" in a for a in body["assumptions"]) and any(
        "UTC" in a for a in body["assumptions"]
    )
    for r in body["data"]["rows"]:
        (oee,) = built.execute(
            "SELECT oee FROM mart.piade_shift_oee WHERE shift_id = %s", (r["key"],)
        ).fetchone()
        assert r["metrics"]["oee"] == (None if oee is None else pytest.approx(float(oee)))
        n = built.execute(
            "SELECT count(*) FROM core.event WHERE shift_id = %s", (r["key"],)
        ).fetchone()[0]
        assert r["citation_count"] == n and len(r["citations"]) == min(n, CITATION_CAP)
        assert {c["raw_table"] for c in r["citations"]} == {"piade_raw"}


def test_piade_day_and_month_are_time_weighted(client, built):
    shifts = get(client, "/api/oee", machine_id="s_1", group="shift")["data"]["rows"]
    day = get(client, "/api/oee", machine_id="s_1", group="day")["data"]["rows"]
    month = get(client, "/api/oee", machine_id="s_1", group="month")["data"]["rows"]
    assert day and month
    # availability recomputed from summed seconds, not the mean of shift ratios
    planned = sum(r["metrics"]["planned_s"] for r in shifts if r["start"][:10] == day[0]["key"])
    run = sum(r["metrics"]["run_s"] for r in shifts if r["start"][:10] == day[0]["key"])
    assert day[0]["metrics"]["availability"] == pytest.approx(run / planned)
    (mart_a,) = built.execute(
        "SELECT availability FROM mart.piade_machine_oee"
        " WHERE month = %s::date AND machine_id = 's_1'",
        (month[0]["key"],),
    ).fetchone()
    assert month[0]["metrics"]["availability"] == pytest.approx(float(mart_a))


def test_brick_month_is_time_weighted(client, built):
    month = get(client, "/api/oee", line_id="brick", group="month")["data"]["rows"]
    assert {m["key"] for m in month} >= {"2026-02"}
    feb = next(m for m in month if m["key"] == "2026-02")
    (planned, stop) = built.execute(
        "SELECT sum(planned_s_published), sum(stop_s_union) FROM mart.brick_shift_oee"
        " WHERE shift_id LIKE 'brick:2026-02-%' AND planned_s_published IS NOT NULL"
    ).fetchone()
    assert feb["metrics"]["availability_calc"] == pytest.approx(1 - float(stop) / float(planned))


def test_validation_report(client):
    body = get(client, "/api/oee/validation")
    assert body["status"] == "ok"
    assert set(body["data"]["periods"]) == {"before", "after"}
    assert body["data"]["shifts"] and "shift_id" in body["data"]["shifts"][0]
