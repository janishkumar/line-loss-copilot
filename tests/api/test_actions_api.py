"""Session switcher, web-form proposals, approvals and audit over HTTP (fixture database)."""

import os
import uuid

import pytest
from fastapi.testclient import TestClient

from linecopilot.actions import args as argmod
from linecopilot.actions.identity import AGENT, ActionContext
from linecopilot.api import app as app_module
from linecopilot.api.actions_routes import COOKIE, token_hash
from linecopilot.api.app import create_app

pytestmark = pytest.mark.db


@pytest.fixture
def client(built):
    return TestClient(create_app(os.environ["LINECOPILOT_TEST_DB_URL"]))


@pytest.fixture
def cleanup(built):
    proposals: list[int] = []
    tokens: list[str] = []
    yield proposals, tokens
    for pid in proposals:
        for table in ("work_order", "quality_hold", "follow_up", "proposal_evidence"):
            built.execute(f"DELETE FROM actions.{table} WHERE proposal_id = %s", (pid,))
        built.execute("DELETE FROM actions.proposal WHERE proposal_id = %s", (pid,))
    built.execute("DELETE FROM actions.web_session WHERE created_at > now() - interval '1 hour'")


@pytest.fixture
def event(built):
    row = built.execute(
        "SELECT event_id, coalesce(machine_id, line_id) FROM core.event "
        "WHERE event_type = 'stop' ORDER BY event_id LIMIT 1"
    ).fetchone()
    assert row
    return row


def wo(event, mode=None):
    return {
        "asset_id": event[1],
        "failure_mode": mode or f"jam-{uuid.uuid4().hex[:8]}",
        "priority": "low",
        "description": "repeat jams",
        "evidence_event_ids": [event[0]],
    }


def login(client, user):
    client.cookies.clear()
    r = client.post("/api/session", json={"user_id": user})
    assert r.status_code == 200, r.text
    return r


def form_propose(client, cleanup, event, user="sup.a", raw=None):
    login(client, user)
    raw = raw or wo(event)
    pv = client.post("/api/actions/work_order/preview", json=raw)
    assert pv.status_code == 200 and pv.json()["code"], pv.text
    r = client.post(
        "/api/actions/work_order/propose", json={"args": raw, "code": pv.json()["code"]}
    )
    assert r.status_code == 200, r.text
    pid = r.json()["proposal_id"]
    cleanup[0].append(pid)
    return pid, raw, pv.json()


def test_session_switch_and_read(client, built, cleanup):
    users = client.get("/api/users").json()
    ids = {u["user_id"] for u in users}
    assert {"sup.a", "sup.b", "ql.a"} <= ids and AGENT not in ids
    assert all(u["source"] == "synthetic" and u["role"] for u in users)
    assert client.get("/api/session").json() == {"user": None}
    r = login(client, "sup.a")
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie and "path=/" in cookie
    assert client.get("/api/session").json()["user"]["user_id"] == "sup.a"
    token = client.cookies.get(COOKIE)
    assert len(token) >= 43
    stored = built.execute(
        "SELECT user_id FROM actions.web_session WHERE token_sha256 = %s", (token_hash(token),)
    ).fetchone()
    assert stored == ("sup.a",)
    assert not built.execute(
        "SELECT 1 FROM actions.web_session WHERE token_sha256 = %s", (token,)
    ).fetchone()
    login(client, "sup.b")
    assert client.get("/api/session").json()["user"]["user_id"] == "sup.b"
    assert client.delete("/api/session").status_code == 200
    assert client.get("/api/session").json() == {"user": None}


def test_session_refuses_agent(client, built):
    before = built.execute("SELECT count(*) FROM actions.web_session").fetchone()[0]
    assert client.post("/api/session", json={"user_id": AGENT}).status_code == 400
    assert client.post("/api/session", json={"user_id": "nobody"}).status_code == 400
    assert COOKIE not in client.cookies
    assert built.execute("SELECT count(*) FROM actions.web_session").fetchone()[0] == before


def test_approve_requires_session(client):
    client.cookies.clear()
    assert client.post("/api/proposals/1/approve").status_code == 401
    assert client.post("/api/proposals/1/reject", json={"note": "x"}).status_code == 401
    assert client.post("/api/actions/work_order/preview", json={}).status_code == 401
    assert client.post("/api/actions/work_orders/1/close").status_code == 401


def test_forged_cookie_refused(client, built):
    client.cookies.set(COOKIE, "forged-token-value")
    assert client.post("/api/proposals/1/approve").status_code == 401
    # a session row for the agent (inserted by hand) is still refused
    token = "agent-" + uuid.uuid4().hex
    built.execute(
        "INSERT INTO actions.web_session (token_sha256, user_id) VALUES (%s, %s)",
        (token_hash(token), AGENT),
    )
    try:
        client.cookies.set(COOKIE, token)
        assert client.post("/api/proposals/1/approve").status_code == 401
    finally:
        built.execute(
            "DELETE FROM actions.web_session WHERE token_sha256 = %s", (token_hash(token),)
        )


def test_body_user_id_ignored_or_rejected(client, event, cleanup):
    pid, _, _ = form_propose(client, cleanup, event)
    login(client, "sup.b")
    r = client.post(f"/api/proposals/{pid}/approve", json={"note": "ok", "user_id": "pm.a"})
    assert r.status_code == 422
    r = client.post(f"/api/proposals/{pid}/reject", json={"note": "no", "on_behalf_of": "x"})
    assert r.status_code == 422
    r = client.post("/api/actions/work_order/propose", json={"args": {}, "user_id": "sup.b"})
    assert r.status_code == 422
    assert client.get(f"/api/proposals/{pid}").json()["status"] == "pending"


def test_web_form_full_flow(client, built, event, cleanup):
    pid, raw, pv = form_propose(client, cleanup, event, "sup.a")
    prop = client.get(f"/api/proposals/{pid}").json()
    assert prop["status"] == "pending" and prop["channel"] == "web_form"
    assert prop["principal"] == prop["on_behalf_of"] == "sup.a"
    assert [p["proposal_id"] for p in client.get("/api/proposals?status=pending").json()][:1] == [
        pid
    ] or pid in [p["proposal_id"] for p in client.get("/api/proposals?status=pending").json()]
    login(client, "sup.b")
    r = client.post(f"/api/proposals/{pid}/approve", json={"note": "go"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["outcome"] == "approved" and body["target_id"]
    wos = client.get("/api/actions/work_orders").json()
    assert any(w["work_order_id"] == body["target_id"] and w["created_by"] == "sup.b" for w in wos)
    digest = argmod.payload_sha256(
        "work_order", ActionContext("sup.a", "sup.a", "web_form"), pv["args"]
    )
    log = client.get("/api/audit?limit=1000").json()
    mine = [a["event"] for a in log if a["payload_sha256"] == digest]
    assert mine == ["approved", "proposed", "previewed"]  # newest first
    by_proposal = client.get(f"/api/audit?proposal_id={pid}").json()
    assert [a["event"] for a in by_proposal] == ["approved", "proposed"]
    # close the work order as a supervisor
    r = client.post(f"/api/actions/work_orders/{body['target_id']}/close")
    assert r.status_code == 200 and r.json()["outcome"] == "closed"
    assert client.post(f"/api/actions/work_orders/{body['target_id']}/close").status_code == 403


def test_self_approval_403(client, event, cleanup):
    pid, _, _ = form_propose(client, cleanup, event, "sup.a")
    r = client.post(f"/api/proposals/{pid}/approve", json={"note": "me"})
    assert r.status_code == 403
    assert "segregation_of_duties" in [
        c["name"] for c in r.json()["checks"] if c["level"] == "block"
    ]
    assert client.get(f"/api/proposals/{pid}").json()["status"] == "pending"


def test_blocked_approval_409(client, built, event, cleanup):
    pid, raw, _ = form_propose(client, cleanup, event, "sup.a")
    # an open work order for the same asset and failure mode appears after the proposal
    rival = built.execute(
        "INSERT INTO actions.proposal (action, args, payload_sha256, summary, principal, "
        "on_behalf_of, channel, status) VALUES ('work_order', '{}', 'x', 'rival', 'sup.b', "
        "'sup.b', 'web_form', 'approved') RETURNING proposal_id"
    ).fetchone()[0]
    cleanup[0].append(rival)
    built.execute(
        "INSERT INTO actions.work_order (proposal_id, asset_id, failure_mode, priority, "
        "description, created_by) VALUES (%s, %s, %s, 'low', 'd', 'sup.b')",
        (rival, raw["asset_id"], raw["failure_mode"]),
    )
    login(client, "sup.b")
    r = client.post(f"/api/proposals/{pid}/approve")
    assert r.status_code == 409, r.text
    assert r.json()["outcome"] == "blocked"
    assert "duplicate_open" in [c["name"] for c in r.json()["checks"] if c["level"] == "block"]
    assert client.get(f"/api/proposals/{pid}").json()["status"] == "pending"


def test_invalid_args_422_and_wrong_code(client, event, cleanup):
    login(client, "sup.a")
    r = client.post("/api/actions/work_order/preview", json={"asset_id": "s_1"})
    assert r.status_code == 422 and r.json()["blocked"] is True
    r = client.post("/api/actions/work_order/propose", json={"args": {"asset_id": "s_1"}})
    assert r.status_code == 422 and r.json()["outcome"] == "refused"
    r = client.post("/api/actions/work_order/propose", json={"args": wo(event), "code": "ABCDEFGH"})
    assert r.status_code == 403
    assert client.post("/api/actions/nope/preview", json={}).status_code == 404


def test_cross_origin_refused(client, event, cleanup):
    pid, _, _ = form_propose(client, cleanup, event, "sup.a")
    login(client, "sup.b")
    evil = {"Origin": "http://evil.test"}
    assert client.post(f"/api/proposals/{pid}/approve", headers=evil).status_code == 403
    assert client.post(f"/api/proposals/{pid}/reject", headers=evil).status_code == 403
    assert client.post("/api/session", json={"user_id": "sup.b"}, headers=evil).status_code == 403
    assert client.delete("/api/session", headers=evil).status_code == 403
    assert client.get(f"/api/proposals/{pid}").json()["status"] == "pending"
    ok = {"Origin": "http://localhost:8080"}
    assert (
        client.post(f"/api/proposals/{pid}/reject", json={"note": "no"}, headers=ok).status_code
        == 200
    )


def test_chat_gets_action_context_only_with_session(client, monkeypatch, cleanup):
    seen = []

    def fake(conn, ollama, messages, **kw):
        seen.append(kw.get("action_ctx"))
        from linecopilot.chat.loop import ChatResult

        return ChatResult(
            answer="ok",
            citations=[],
            cited_event_ids=[],
            unsupported_cited_ids=[],
            tool_calls=[],
            model="m",
            rounds=0,
        )

    monkeypatch.setattr(app_module, "run_chat", fake)
    body = {"messages": [{"role": "user", "content": "hi"}]}
    client.cookies.clear()
    assert client.post("/api/chat", json=body).status_code == 200
    login(client, "sup.a")
    assert client.post("/api/chat", json=body).status_code == 200
    assert seen[0] is None
    assert seen[1] == ActionContext(principal=AGENT, on_behalf_of="sup.a", channel="web_chat")
