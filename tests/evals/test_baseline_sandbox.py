"""No-tools baselines cannot see the answer key; the tools runs see only this server."""

import json
import tempfile
from pathlib import Path

import httpx

from evals.runners import claude as cr
from evals.runners.ollama import OllamaRunner, config
from linecopilot.chat.ollama import OllamaClient
from linecopilot.tools.registry import TOOLS

REPO = Path(__file__).resolve().parents[2]


def flag(argv: list[str], name: str) -> str:
    return argv[argv.index(name) + 1]


def test_baseline_sandbox_configs():
    work = tempfile.mkdtemp()
    # no-tools Claude: outside the repo, no MCP servers, no built-in tools, nothing allowed
    nt = cr.notools_invocation("q?", work)
    assert not Path(nt.cwd).resolve().is_relative_to(REPO)
    assert nt.mcp_config == {"mcpServers": {}}
    assert json.loads(flag(nt.argv, "--mcp-config")) == {"mcpServers": {}}
    assert "--strict-mcp-config" in nt.argv
    assert flag(nt.argv, "--tools") == ""
    assert "--allowedTools" not in nt.argv
    disallowed = set(flag(nt.argv, "--disallowedTools").split(","))
    assert {"Bash", "Read", "Grep", "Glob", "Write", "Edit", "WebFetch"} <= disallowed
    assert flag(nt.argv, "--setting-sources") == ""
    assert nt.stdin == "q?" and "q?" not in nt.argv
    assert cr.SYSTEM_PROMPT in nt.argv

    # tools Claude: only this server, only its tools, no built-ins, no asking
    url = "postgresql://u:p@localhost:5434/db"
    t = cr.tools_invocation("q?", url, work, str(Path(work).parent / "cfg.json"))
    assert not Path(t.cwd).resolve().is_relative_to(REPO)
    servers = t.mcp_config["mcpServers"]
    assert list(servers) == ["linecopilot"]
    srv = servers["linecopilot"]
    assert srv["args"] == ["-m", "linecopilot.mcp_server"]
    assert srv["env"] == {"LINECOPILOT_DB_URL": url, "PYTHONPATH": str(REPO / "src")}
    assert Path(srv["command"]).is_absolute()
    assert "--strict-mcp-config" in t.argv
    assert flag(t.argv, "--tools") == ""
    allowed = flag(t.argv, "--allowedTools").split(",")
    assert sorted(allowed) == sorted(f"mcp__linecopilot__{n}" for n in TOOLS)
    assert all(a.startswith("mcp__linecopilot__") for a in allowed)
    assert flag(t.argv, "--permission-mode") == "dontAsk"
    assert flag(t.argv, "--setting-sources") == ""


def test_claude_child_env_has_no_database(monkeypatch):
    monkeypatch.setenv("LINECOPILOT_DB_URL", "postgresql://x")
    monkeypatch.setenv("PGPASSWORD", "x")
    env = cr.child_env()
    assert "LINECOPILOT_DB_URL" not in env and "PGPASSWORD" not in env


def test_claude_runner_writes_config_outside_workdir():
    r = cr.ClaudeRunner("postgresql://x", tools_enabled=True)
    work = tempfile.mkdtemp()
    inv = r.invocation("q", work)
    cfg = Path(flag(inv.argv, "--mcp-config"))
    assert cfg.parent == Path(work).parent and cfg.name.endswith("-mcp.json")
    assert cr.ClaudeRunner("x", tools_enabled=False).invocation("q", work).mcp_config == {
        "mcpServers": {}
    }


def test_parse_claude_output():
    out = json.dumps(
        {
            "type": "result",
            "result": "x\nANSWER: 1",
            "modelUsage": {"claude-test-1": {"inputTokens": 3}},
            "num_turns": 4,
        }
    )
    answer, model, extra = cr.parse_output(out, None)
    assert answer.endswith("ANSWER: 1") and model == "claude-test-1" and extra["num_turns"] == 4
    assert cr.parse_output(json.dumps({"result": "y"}), "m-arg")[1] == "m-arg"
    assert cr.parse_output("not json", None)[2]["parse_error"]


def test_ollama_notools_sends_empty_tools():
    assert config(False) == {"tools_enabled": False}
    bodies = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/chat":
            bodies.append(json.loads(request.content))
            reply = {"message": {"role": "assistant", "content": "x\nANSWER: NOT_AVAILABLE"}}
            return httpx.Response(200, json=reply)
        if request.url.path == "/api/version":
            return httpx.Response(200, json={"version": "0.0.1"})
        return httpx.Response(200, json={"models": [{"name": "fake:1b", "digest": "abc"}]})

    client = OllamaClient("http://ollama.test", "fake:1b", transport=httpx.MockTransport(handler))
    runner = OllamaRunner(conn=None, client=client, tools_enabled=False)
    reply = runner.ask("What was the OEE?")
    assert runner.name == "ollama-notools"
    assert bodies[0]["tools"] == []
    assert reply.answer.endswith("NOT_AVAILABLE") and reply.tool_calls == []
    assert runner.meta() == {"model": "fake:1b", "model_digest": "abc", "ollama_version": "0.0.1"}

    with_tools = OllamaRunner(conn=None, client=client, tools_enabled=True)
    with_tools.ask("q")
    assert {t["function"]["name"] for t in bodies[1]["tools"]} == set(TOOLS)
