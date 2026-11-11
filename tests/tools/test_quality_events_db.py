"""The quality_events read tool: synthetic labels, event ids a hold can cite, missing data."""

import pytest

from linecopilot.tools.registry import TOOLS, call_tool

pytestmark = pytest.mark.db


def test_registered_read_only_with_strict_args():
    spec = TOOLS["quality_events"]
    assert spec.read_only and spec.args_model.model_config.get("extra") == "forbid"
    assert "SIMULATED" in spec.description and "synthetic" in spec.description


def test_no_events_is_insufficient_evidence(vision_clean):
    r = call_tool(vision_clean, "quality_events", {})
    assert r.status == "insufficient_evidence" and "make inspect" in r.missing
    assert any("SIMULATED" in a for a in r.assumptions)


def test_lists_events_with_labels_and_scores(make_inspection, vision_clean):
    auto = make_inspection(subset="cashew", decision="reject", score=0.95)
    queued = make_inspection(subset="fryum", decision="review")
    from linecopilot.vision import store

    store.record_review(vision_clean, queued, "reject", "ql.a")
    make_inspection(subset="cashew", decision="pass")  # no event
    make_inspection(subset="cashew", decision="review")  # queued: no event yet
    r = call_tool(vision_clean, "quality_events", {})
    assert r.status == "ok" and r.data.total == 2 and r.data.is_synthetic
    assert r.citations == [] and r.citation_count == 0
    by_asset = {e.asset_id: e for e in r.data.rows}
    assert set(by_asset) == {"SIM-VIS-cashew", "SIM-VIS-fryum"}
    c, f = by_asset["SIM-VIS-cashew"], by_asset["SIM-VIS-fryum"]
    assert c.path == "automatic reject" and c.score == 0.95 and c.inspection_id == auto
    assert f.path == "rejected by reviewer ql.a" and f.reviewer == "ql.a"
    assert c.event_id >= 9_000_000_000 and c.is_synthetic and c.reason_code == "VISUAL_REJECT"
    assert "SIMULATED" in c.detail and "SIMULATED" in r.data.notice
    assert any("SIMULATED" in a for a in r.assumptions)
    only = call_tool(vision_clean, "quality_events", {"asset_id": "SIM-VIS-fryum"})
    assert [e.asset_id for e in only.data.rows] == ["SIM-VIS-fryum"]
    none = call_tool(vision_clean, "quality_events", {"asset_id": "s_1"})
    assert none.status == "insufficient_evidence"
    assert call_tool(vision_clean, "quality_events", {"asset_id": "x", "bogus": 1}).status == (
        "out_of_scope"
    )


def test_missing_view_is_insufficient_evidence_not_an_error(built):
    """Before the vision schema (or after a dbt rebuild without `make schemas`) the view is
    absent; the tool says so instead of failing. Rolled back, so the view comes back."""
    import os

    import psycopg

    with psycopg.connect(os.environ["LINECOPILOT_TEST_DB_URL"], autocommit=True) as conn:
        conn.execute("BEGIN")
        try:
            conn.execute("DROP VIEW core.event_all")
            r = call_tool(conn, "quality_events", {})
        finally:
            conn.execute("ROLLBACK")
    assert r.status == "insufficient_evidence" and "make inspect" in r.missing


def test_missing_sim_asset_table_is_insufficient_evidence(built):
    import os

    import psycopg

    with psycopg.connect(os.environ["LINECOPILOT_TEST_DB_URL"], autocommit=True) as conn:
        conn.execute("BEGIN")
        try:
            conn.execute("DROP VIEW core.event_all")
            conn.execute(
                "ALTER TABLE synthetic.quality_event DROP CONSTRAINT quality_event_asset_id_fkey"
            )
            conn.execute("DROP TABLE synthetic.sim_asset")
            r = call_tool(conn, "quality_events", {})
        finally:
            conn.execute("ROLLBACK")
    assert r.status == "insufficient_evidence"


def test_tool_output_hides_the_class_folder(make_inspection, vision_clean):
    make_inspection(decision="reject", image="cashew/Data/Images/Normal/321.JPG")
    r = call_tool(vision_clean, "quality_events", {})
    text = r.model_dump_json()
    assert "321.JPG" in text and "Normal" not in text and "Anomaly" not in text
    from linecopilot.tools.inspection import ListInspectionsArgs, list_inspections

    lst = list_inspections(vision_clean, ListInspectionsArgs()).model_dump_json()
    assert "321.JPG" in lst and "Normal" not in lst and "Anomaly" not in lst
