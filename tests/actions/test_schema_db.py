"""Actions schema, demo users and the restricted agent role (needs the test database)."""

import uuid
from urllib.parse import urlparse, urlunparse

import psycopg
import pytest

from linecopilot import schemas
from linecopilot.actions.identity import AGENT, get_user

pytestmark = pytest.mark.db

NAMES = ["demo_schema.sql", "actions_schema.sql", "synthetic_schema.sql", "plan_schema.sql"]


def test_schemas_idempotent(built):
    first = schemas.apply(built)
    second = schemas.apply(built)
    assert first == second
    assert NAMES == first[2:]
    assert built.execute("SELECT count(*) FROM demo.app_user").fetchone()[0] == 7


def test_demo_users_seeded(built):
    rows = built.execute("SELECT user_id, role, source FROM demo.app_user").fetchall()
    assert len(rows) == 7
    assert {r[2] for r in rows} == {"synthetic"}
    assert ("copilot-agent", "agent", "synthetic") in rows
    assert built.execute("SELECT count(*) FROM demo.injected_note").fetchone()[0] == 0


def test_get_user(built):
    u = get_user(built, "sup.a")
    assert u is not None and u.role == "shift_supervisor" and u.display_name == "Supervisor A"
    assert get_user(built, AGENT).role == "agent"
    assert get_user(built, "nobody") is None


def test_audit_log_append_only(built):
    built.execute(
        "INSERT INTO actions.audit_log (event, principal, outcome) VALUES ('t', 'x', 'ok')"
    )
    with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
        built.execute("UPDATE actions.audit_log SET outcome = 'changed'")
    with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
        built.execute("DELETE FROM actions.audit_log")


@pytest.fixture
def agent(agent_url, built):
    # No re-apply here: grants must come from the conftest step that mirrors `make dbt`.
    with psycopg.connect(agent_url, autocommit=True) as conn:
        yield conn


def test_agent_url_swaps_credentials(db_url, agent_url):
    u = urlparse(agent_url)
    assert (u.username, u.password) == ("linecopilot_agent", "linecopilot_agent")
    assert u.path == urlparse(db_url).path
    assert urlunparse(u)


def test_agent_role_cannot_write_actions(agent):
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        agent.execute(
            "INSERT INTO actions.work_order (proposal_id, asset_id, failure_mode, priority, "
            "description, created_by) VALUES (1, 'a', 'f', 'low', 'd', 'x')"
        )
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        agent.execute("UPDATE actions.proposal SET status = 'approved'")
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        agent.execute("UPDATE actions.confirmation_code SET expires_at = now()")
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        agent.execute("DELETE FROM actions.audit_log")
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        agent.execute("INSERT INTO actions.web_session VALUES ('h', 'sup.a')")
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        agent.execute("INSERT INTO demo.app_user VALUES ('z', 'z', 'agent')")
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        agent.execute("INSERT INTO core.event DEFAULT VALUES")


def test_agent_role_can_propose_and_audit(agent):
    row = agent.execute(
        "INSERT INTO actions.proposal (action, args, payload_sha256, summary, principal, "
        "on_behalf_of, channel) VALUES ('follow_up', '{}', 'h', 's', 'copilot-agent', "
        "'sup.a', 'mcp') RETURNING proposal_id"
    ).fetchone()
    agent.execute(
        "INSERT INTO actions.proposal_evidence (proposal_id, event_key) VALUES (%s, 'f#1')",
        (row[0],),
    )
    agent.execute(
        "INSERT INTO actions.audit_log (event, principal, outcome) VALUES ('proposed','x','ok')"
    )
    agent.execute(
        "INSERT INTO actions.confirmation_code (code_sha256, action, principal, on_behalf_of, "
        "payload_sha256, expires_at) VALUES (%s, 'follow_up', 'x', 'y', 'h', now())",
        ("c" + str(row[0]),),
    )
    agent.execute(
        "UPDATE actions.confirmation_code SET used_at = now() WHERE code_sha256 = %s",
        ("c" + str(row[0]),),
    )


def test_agent_cannot_forge_a_decision_on_insert(agent):
    base = (
        "INSERT INTO actions.proposal (action, args, payload_sha256, summary, principal, "
        "on_behalf_of, channel, {col}) VALUES ('follow_up', '{{}}', 'h', 's', 'copilot-agent', "
        "'sup.a', 'mcp', {val})"
    )
    for col, val in (
        ("status", "'approved'"),
        ("decided_by", "'sup.a'"),
        ("decided_at", "now()"),
        ("decision_note", "'ok'"),
        ("target_id", "1"),
    ):
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            agent.execute(base.format(col=col, val=val))
    pid = agent.execute(
        "INSERT INTO actions.proposal (action, args, payload_sha256, summary, checks, principal, "
        "on_behalf_of, channel, created_at) VALUES ('follow_up', '{}', 'h', 's', '[]', "
        "'copilot-agent', 'sup.a', 'mcp', now()) RETURNING proposal_id"
    ).fetchone()[0]
    status = agent.execute(
        "SELECT status FROM actions.proposal WHERE proposal_id = %s", (pid,)
    ).fetchone()[0]
    assert status == "pending"


def test_burned_code_cannot_be_revived(agent, built):
    h = f"burn-test-{uuid.uuid4().hex}"
    agent.execute(
        "INSERT INTO actions.confirmation_code (code_sha256, action, principal, on_behalf_of, "
        "payload_sha256, expires_at) VALUES (%s, 'follow_up', 'x', 'y', 'h', now())",
        (h,),
    )
    agent.execute(
        "UPDATE actions.confirmation_code SET used_at = now() WHERE code_sha256 = %s", (h,)
    )
    with pytest.raises(psycopg.errors.RaiseException, match="single-use"):
        agent.execute(
            "UPDATE actions.confirmation_code SET used_at = NULL WHERE code_sha256 = %s", (h,)
        )
    with pytest.raises(psycopg.errors.RaiseException, match="single-use"):
        agent.execute(
            "UPDATE actions.confirmation_code SET used_at = now() WHERE code_sha256 = %s", (h,)
        )
    # owner cannot change other columns either
    with pytest.raises(psycopg.errors.RaiseException, match="single-use"):
        built.execute(
            "UPDATE actions.confirmation_code SET expires_at = now() + interval '1 day' "
            "WHERE code_sha256 = %s",
            (h,),
        )


def test_audit_log_truncate_blocked(built):
    with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
        built.execute("TRUNCATE actions.audit_log")


def test_agent_cannot_read_sessions(agent):
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        agent.execute("SELECT * FROM actions.web_session")


def test_agent_reads_after_dbt_rebuild(agent):
    for table in ("core.event", "demo.app_user", "actions.proposal", "ml.stop_risk_score"):
        agent.execute(f"SELECT count(*) FROM {table}").fetchone()
    assert agent.execute("SELECT count(*) FROM core.event").fetchone()[0] > 0
