"""One-time codes against the test database, on the restricted agent role."""

import threading
import uuid
from datetime import UTC, datetime, timedelta

import psycopg
import pytest

from linecopilot.actions import codes
from linecopilot.actions.identity import ActionContext

pytestmark = pytest.mark.db

NOW = datetime(2021, 1, 1, 8, tzinfo=UTC)
TTL = timedelta(minutes=15)


@pytest.fixture
def agent(agent_url, built):
    with psycopg.connect(agent_url, autocommit=True) as conn:
        yield conn


@pytest.fixture
def ctx():
    # unique per test so rows from other tests never interfere
    return ActionContext("copilot-agent", f"sup.{uuid.uuid4().hex[:6]}", "mcp")


def issue(agent, ctx, action="work_order", h="hash1"):
    return codes.issue(agent, action, ctx, h, NOW, TTL)


def test_code_single_use(agent, ctx):
    c = issue(agent, ctx)
    assert codes.redeem(agent, c, "work_order", ctx, "hash1", NOW) is None
    refusal = codes.redeem(agent, c, "work_order", ctx, "hash1", NOW)
    assert refusal and "already used" in refusal


def test_code_accepts_lowercase_and_spaces(agent, ctx):
    c = issue(agent, ctx)
    assert codes.redeem(agent, f" {c.lower()} ", "work_order", ctx, "hash1", NOW) is None


def test_code_unknown(agent, ctx):
    refusal = codes.redeem(agent, "ZZZZZZZZ", "work_order", ctx, "hash1", NOW)
    assert refusal and "unknown" in refusal


def test_code_expiry_is_ttl(agent, ctx):
    c = issue(agent, ctx)
    row = agent.execute(
        "SELECT expires_at FROM actions.confirmation_code WHERE code_sha256 = %s",
        (codes.hash_code(c),),
    ).fetchone()
    assert row[0] == NOW + timedelta(minutes=15)


def test_code_custom_ttl(agent, ctx):
    c = codes.issue(agent, "work_order", ctx, "h", NOW, ttl=timedelta(minutes=5))
    assert codes.redeem(agent, c, "work_order", ctx, "h", NOW + timedelta(minutes=6))


def test_code_expired(agent, ctx):
    c = issue(agent, ctx)
    refusal = codes.redeem(agent, c, "work_order", ctx, "hash1", NOW + timedelta(minutes=16))
    assert refusal and "expired" in refusal


def test_code_valid_just_before_expiry(agent, ctx):
    c = issue(agent, ctx)
    assert codes.redeem(agent, c, "work_order", ctx, "hash1", NOW + timedelta(minutes=14)) is None


def test_code_other_user(agent, ctx):
    c = issue(agent, ctx)
    other = ActionContext(ctx.principal, "sup.b", ctx.channel)
    refusal = codes.redeem(agent, c, "work_order", other, "hash1", NOW)
    assert refusal and "different action or user" in refusal


def test_code_other_principal(agent, ctx):
    c = issue(agent, ctx)
    other = ActionContext("sup.a", ctx.on_behalf_of, "web_form")
    assert codes.redeem(agent, c, "work_order", other, "hash1", NOW)


def test_code_other_action(agent, ctx):
    c = issue(agent, ctx)
    refusal = codes.redeem(agent, c, "quality_hold", ctx, "hash1", NOW)
    assert refusal and "different action or user" in refusal


def test_code_args_changed(agent, ctx):
    c = issue(agent, ctx)
    refusal = codes.redeem(agent, c, "work_order", ctx, "hash2", NOW)
    assert refusal and "differ" in refusal


def test_code_burned_even_when_refused(agent, ctx):
    c = issue(agent, ctx)
    assert codes.redeem(agent, c, "work_order", ctx, "wrong", NOW)
    refusal = codes.redeem(agent, c, "work_order", ctx, "hash1", NOW)
    assert refusal and "already used" in refusal


def test_code_burned_even_when_expired(agent, ctx):
    c = issue(agent, ctx)
    later = NOW + timedelta(hours=1)
    assert "expired" in codes.redeem(agent, c, "work_order", ctx, "hash1", later)
    assert "already used" in codes.redeem(agent, c, "work_order", ctx, "hash1", NOW)


def test_code_missing_does_not_touch_database(agent, ctx):
    before = agent.execute(
        "SELECT count(*) FROM actions.confirmation_code WHERE used_at IS NOT NULL"
    ).fetchone()[0]
    assert codes.redeem(agent, "", "work_order", ctx, "hash1", NOW) == "missing code"
    after = agent.execute(
        "SELECT count(*) FROM actions.confirmation_code WHERE used_at IS NOT NULL"
    ).fetchone()[0]
    assert before == after


def test_code_concurrent_redeem_one_wins(agent_url, agent, ctx):
    c = issue(agent, ctx)
    results: list = []
    barrier = threading.Barrier(2)

    def worker():
        with psycopg.connect(agent_url, autocommit=True) as conn:
            barrier.wait()
            results.append(codes.redeem(conn, c, "work_order", ctx, "hash1", NOW))

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(r is None for r in results) == [False, True]


def test_code_stored_hashed(agent, ctx):
    c = issue(agent, ctx)
    rows = agent.execute(
        "SELECT code_sha256 FROM actions.confirmation_code WHERE on_behalf_of = %s",
        (ctx.on_behalf_of,),
    ).fetchall()
    assert rows == [(codes.hash_code(c),)]
    hit = agent.execute(
        "SELECT count(*) FROM actions.confirmation_code "
        "WHERE code_sha256 = %s OR action = %s OR principal = %s OR on_behalf_of = %s "
        "OR payload_sha256 = %s",
        (c, c, c, c, c),
    ).fetchone()[0]
    assert hit == 0
