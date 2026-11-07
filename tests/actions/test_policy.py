"""Policy file loading and validation (offline)."""

from pathlib import Path

import pytest

from linecopilot.actions.identity import AGENT, ActionContext
from linecopilot.actions.policy import load_policy

REPO_POLICY = Path(__file__).resolve().parents[2] / "config" / "policy.toml"


def test_policy_loads_repo_file():
    p = load_policy(REPO_POLICY)
    assert p.may_approve("shift_supervisor", "work_order")
    assert not p.may_approve("planner", "work_order")
    assert not p.may_propose("operator", "work_order")
    assert p.may_propose("operator", "follow_up")
    assert p.ttl_minutes == 15
    assert p.max_events == 50
    assert p.priority_floor("high") == (1800, 2)
    assert p.priority_floor("critical") == (7200, 3)
    assert p.priority_floor("low") is None


def test_agent_never_holds_a_permission():
    p = load_policy(REPO_POLICY)
    for action in ("work_order", "quality_hold", "follow_up"):
        assert not p.may_approve("agent", action)
        assert not p.may_propose("agent", action)


def _write(tmp_path, text):
    f = tmp_path / "policy.toml"
    f.write_text(text)
    return f


def test_policy_rejects_unknown_role(tmp_path):
    text = REPO_POLICY.read_text().replace("planner =", "janitor =")
    with pytest.raises(ValueError, match="janitor"):
        load_policy(_write(tmp_path, text))


def test_policy_rejects_unknown_action(tmp_path):
    text = REPO_POLICY.read_text().replace('"quality_hold", "follow_up"]', '"launch", "follow_up"]')
    with pytest.raises(ValueError, match="launch"):
        load_policy(_write(tmp_path, text))


def test_policy_rejects_unknown_key_and_section(tmp_path):
    with pytest.raises(ValueError):
        load_policy(_write(tmp_path, REPO_POLICY.read_text() + "\n[extra]\nx = 1\n"))
    with pytest.raises(ValueError):
        load_policy(_write(tmp_path, REPO_POLICY.read_text().replace("max_events", "max_evnts")))


def test_policy_rejects_agent_role(tmp_path):
    text = REPO_POLICY.read_text().replace(
        'follow_up = ["shift_supervisor"]', 'follow_up = ["shift_supervisor", "agent"]'
    )
    with pytest.raises(ValueError, match="agent"):
        load_policy(_write(tmp_path, text))


def test_action_context_is_frozen():
    ctx = ActionContext(principal=AGENT, on_behalf_of="sup.a", channel="mcp")
    assert ctx.principal == "copilot-agent"
    with pytest.raises(AttributeError):
        ctx.principal = "sup.a"  # type: ignore[misc]
