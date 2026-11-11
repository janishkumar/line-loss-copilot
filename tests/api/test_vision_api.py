"""Inspection routes: queue, one inspection, heatmap whitelist, reviewer decision."""

import os
import subprocess
import sys

import pytest
from fastapi.testclient import TestClient

from linecopilot.api.actions_routes import COOKIE
from linecopilot.api.app import create_app
from linecopilot.config import get_settings

pytestmark = pytest.mark.db


@pytest.fixture
def client(built):
    return TestClient(create_app(os.environ["LINECOPILOT_TEST_DB_URL"]))


@pytest.fixture
def heat(tmp_path, monkeypatch):
    """Point the data dir at a temp folder with a heatmaps/ directory."""
    monkeypatch.setenv("LINECOPILOT_DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    d = tmp_path / "vision" / "heatmaps" / "cashew"
    d.mkdir(parents=True)
    yield tmp_path / "vision" / "heatmaps"
    get_settings.cache_clear()


def login(client, user):
    client.cookies.clear()
    r = client.post("/api/session", json={"user_id": user})
    assert r.status_code == 200, r.text


def test_api_does_not_import_torch():
    code = (
        "import sys, linecopilot.api.app, linecopilot.vision.store, linecopilot.tools.inspection;"
        "bad=[m for m in ('torch','onnxruntime','torchvision') if m in sys.modules];"
        "assert not bad, bad"
    )
    env = {**os.environ, "PYTHONPATH": "src"}
    out = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True)
    assert out.returncode == 0, out.stderr


def test_empty_stream_is_insufficient_evidence(client, vision_clean):
    r = client.get("/api/inspections")
    assert r.status_code == 200 and r.json()["status"] == "insufficient_evidence"
    assert "make inspect" in r.json()["missing"]
    r = client.get("/api/inspections/1")
    assert r.status_code == 404 and r.json()["status"] == "insufficient_evidence"
    r = client.get("/api/inspections/1/heatmap")
    assert r.status_code == 404 and r.json()["status"] == "insufficient_evidence"


def test_list_filter_and_detail(client, make_inspection, heat):
    p = heat / "cashew" / "a.png"
    p.write_bytes(b"\x89PNG\r\n\x1a\nfake")
    q = make_inspection(decision="review", heatmap="cashew/a.png")
    make_inspection(decision="pass")
    make_inspection(decision="reject")
    body = client.get("/api/inspections").json()
    assert body["status"] == "ok" and body["data"]["total"] == 3
    assert body["data"]["counts"] == {"pass": 1, "review": 1, "reject": 1}
    assert body["data"]["pending_review"] == 1 and body["data"]["is_synthetic"] is True
    assert any("SIMULATED" in a for a in body["assumptions"])
    rev = client.get("/api/inspections", params={"decision": "review"}).json()["data"]
    assert [r["inspection_id"] for r in rev["rows"]] == [q] and rev["total"] == 1
    row = rev["rows"][0]
    assert row["asset_id"] == "SIM-VIS-cashew" and row["review"] is None
    assert row["heatmap_url"] == f"/api/inspections/{q}/heatmap"
    one = client.get(f"/api/inspections/{q}").json()
    assert one["status"] == "ok" and one["data"]["inspection_id"] == q
    bad = client.get("/api/inspections", params={"decision": "nope"})
    assert bad.status_code == 200 and bad.json()["status"] == "out_of_scope"
    unrev = client.get("/api/inspections", params={"unreviewed": "true"}).json()["data"]
    assert unrev["total"] == 1


def test_heatmap_serves_only_the_stored_file_under_the_folder(client, make_inspection, heat):
    (heat / "cashew" / "a.png").write_bytes(b"\x89PNG\r\n\x1a\nfake")
    ok = make_inspection(heatmap="cashew/a.png")
    r = client.get(f"/api/inspections/{ok}/heatmap")
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"
    assert r.content.startswith(b"\x89PNG")
    # a file outside the folder, reached by a stored traversal path, is never served
    secret = heat.parent / "secret.txt"
    secret.write_text("secret")
    out = make_inspection(heatmap="../secret.txt")
    r = client.get(f"/api/inspections/{out}/heatmap")
    assert r.status_code == 404 and r.json()["status"] == "insufficient_evidence"
    assert "secret" not in r.text
    # an absolute path is not served either
    absolute = make_inspection(heatmap=str(secret))
    assert client.get(f"/api/inspections/{absolute}/heatmap").status_code == 404
    # a missing file or no heatmap at all: envelope, never 500
    gone = make_inspection(heatmap="cashew/missing.png")
    r = client.get(f"/api/inspections/{gone}/heatmap")
    assert r.status_code == 404 and r.json()["status"] == "insufficient_evidence"
    assert client.get(f"/api/inspections/{make_inspection()}/heatmap").status_code == 404
    # the detail does not advertise a heatmap that is not there
    assert client.get(f"/api/inspections/{gone}").json()["data"]["heatmap_url"] is None
    # the client cannot name a path: only integer ids route
    assert client.get("/api/inspections/..%2Fsecret.txt/heatmap").status_code in (200, 404)
    assert "secret" not in client.get("/api/inspections/..%2Fsecret.txt/heatmap").text


def test_review_needs_a_session_and_the_right_origin(client, make_inspection):
    q = make_inspection(decision="review")
    client.cookies.clear()
    r = client.post(f"/api/inspections/{q}/review", json={"decision": "reject"})
    assert r.status_code == 401
    client.cookies.set(COOKIE, "forged")
    assert (
        client.post(f"/api/inspections/{q}/review", json={"decision": "reject"}).status_code == 401
    )
    login(client, "ql.a")
    r = client.post(
        f"/api/inspections/{q}/review",
        json={"decision": "reject"},
        headers={"Origin": "http://evil.example"},
    )
    assert r.status_code == 403
    r = client.post(
        f"/api/inspections/{q}/review",
        json={"decision": "reject"},
        headers={"Origin": "http://localhost:8080"},
    )
    assert r.status_code == 200, r.text


def test_reviewer_comes_from_the_session_never_the_body(client, make_inspection, vision_clean):
    q = make_inspection(decision="review")
    login(client, "ql.a")
    r = client.post(f"/api/inspections/{q}/review", json={"decision": "accept", "reviewer": "pm.a"})
    assert r.status_code == 422
    assert vision_clean.execute("SELECT count(*) FROM vision.review").fetchone()[0] == 0
    r = client.post(f"/api/inspections/{q}/review", json={"decision": "maybe"})
    assert r.status_code == 422
    r = client.post(f"/api/inspections/{q}/review", json={"decision": "accept"})
    assert r.status_code == 200
    assert vision_clean.execute("SELECT reviewer FROM vision.review").fetchone() == ("ql.a",)
    body = r.json()["data"]
    assert body["inspection"]["review"]["reviewer"] == "ql.a"
    assert body["quality_event_id"] is None


def test_reject_creates_exactly_one_event_and_second_review_is_an_envelope_error(
    client, make_inspection, vision_clean
):
    q = make_inspection(decision="review")
    login(client, "sup.a")
    r = client.post(f"/api/inspections/{q}/review", json={"decision": "reject"})
    assert r.status_code == 200
    eid = r.json()["data"]["quality_event_id"]
    assert eid >= 9_000_000_000
    for decision in ("reject", "accept"):
        again = client.post(f"/api/inspections/{q}/review", json={"decision": decision})
        assert again.status_code == 409
        assert again.json()["status"] == "out_of_scope" and "already" in again.json()["missing"]
    assert vision_clean.execute("SELECT count(*) FROM vision.review").fetchone()[0] == 1
    assert vision_clean.execute("SELECT event_id FROM synthetic.quality_event").fetchall() == [
        (eid,)
    ]
    # shown on the inspection afterwards
    one = client.get(f"/api/inspections/{q}").json()["data"]
    assert one["quality_event_id"] == eid and one["review"]["decision"] == "reject"


def test_only_queued_images_can_be_reviewed(client, make_inspection):
    login(client, "ql.a")
    for decision in ("pass", "reject"):
        i = make_inspection(decision=decision)
        r = client.post(f"/api/inspections/{i}/review", json={"decision": "accept"})
        assert r.status_code == 409 and r.json()["status"] == "out_of_scope"
    r = client.post("/api/inspections/999999999/review", json={"decision": "accept"})
    assert r.status_code == 404 and r.json()["status"] == "out_of_scope"


def test_review_without_a_stream_is_an_envelope(client, vision_clean):
    login(client, "ql.a")
    r = client.post("/api/inspections/1/review", json={"decision": "accept"})
    assert r.status_code == 404 and r.json()["status"] == "out_of_scope"


@pytest.mark.parametrize("user", ["op.a", "plan.a"])
def test_roles_without_quality_authority_cannot_review(client, make_inspection, vision_clean, user):
    q = make_inspection(decision="review")
    login(client, user)
    r = client.post(f"/api/inspections/{q}/review", json={"decision": "reject"})
    assert r.status_code == 403 and r.json()["status"] == "out_of_scope"
    assert "may not review" in r.json()["missing"]
    assert vision_clean.execute("SELECT count(*) FROM vision.review").fetchone()[0] == 0
    assert vision_clean.execute("SELECT count(*) FROM synthetic.quality_event").fetchone()[0] == 0


@pytest.mark.parametrize("user", ["ql.a", "sup.a", "sup.b", "pm.a"])
def test_allowed_roles_can_review(client, make_inspection, vision_clean, user):
    q = make_inspection(decision="review")
    login(client, user)
    r = client.post(f"/api/inspections/{q}/review", json={"decision": "reject"})
    assert r.status_code == 200, r.text
    assert vision_clean.execute("SELECT reviewer FROM vision.review").fetchone() == (user,)


def test_agent_cannot_hold_a_session_to_review(client, make_inspection):
    q = make_inspection(decision="review")
    client.cookies.clear()
    assert client.post("/api/session", json={"user_id": "copilot-agent"}).status_code == 400
    assert (
        client.post(f"/api/inspections/{q}/review", json={"decision": "accept"}).status_code == 401
    )
