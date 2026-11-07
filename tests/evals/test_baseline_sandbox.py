"""No-tools baselines cannot see the answer key; the tools runs see only this server."""

import json
import tempfile
from pathlib import Path

import httpx

from evals.runners import STAGE2_TOOLS
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
    # the server itself registers only the 12 stage 2 tools: the model never sees the others
    assert srv["env"] == {
        "LINECOPILOT_DB_URL": url,
        "PYTHONPATH": str(REPO / "src"),
        "LINECOPILOT_MCP_TOOLS": ",".join(STAGE2_TOOLS),
    }
    assert Path(srv["command"]).is_absolute()
    assert "--strict-mcp-config" in t.argv
    assert flag(t.argv, "--tools") == ""
    allowed = flag(t.argv, "--allowedTools").split(",")
    assert sorted(allowed) == sorted(f"mcp__linecopilot__{n}" for n in STAGE2_TOOLS)
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
    # the baseline differs from the tools run only in tools_enabled
    assert config(False) == {**config(True), "tools_enabled": False}
    assert config(False)["tools_enabled"] is False
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
    assert runner.meta() == {
        "model": "fake:1b",
        "model_digest": "abc",
        "ollama_version": "0.0.1",
        "timeout_s": 180.0,
        "retries_on_timeout": 1,
        "time_budget_s": 1800.0,
        "max_rounds": 6,
        "ollama_options": {"temperature": 0, "seed": 0, "num_ctx": 16384, "num_predict": 1024},
    }

    with_tools = OllamaRunner(conn=None, client=client, tools_enabled=True)
    with_tools.ask("q")
    assert {t["function"]["name"] for t in bodies[1]["tools"]} == set(STAGE2_TOOLS)
    assert bodies[0]["options"]["num_predict"] == 1024


def test_claude_model_id_is_the_biggest_writer():
    out = json.dumps(
        {
            "result": "ANSWER: 1",
            "modelUsage": {
                "claude-small": {"outputTokens": 40},
                "claude-main": {"outputTokens": 900},
            },
        }
    )
    _, model, extra = cr.parse_output(out, "arg")
    assert model == "claude-main" and extra["models"] == ["claude-main", "claude-small"]


def test_claude_runner_cleans_up(monkeypatch, tmp_path):
    made = []
    real_mkdtemp = tempfile.mkdtemp

    def mkdtemp(prefix=""):
        d = real_mkdtemp(prefix=prefix, dir=tmp_path)
        made.append(Path(d))
        return d

    class Done:
        returncode = 0
        stdout = json.dumps({"result": "x\nANSWER: 1", "modelUsage": {"m1": {"outputTokens": 1}}})
        stderr = ""

    seen = {}

    def fake_run(argv, **kw):
        cfg = Path(argv[argv.index("--mcp-config") + 1])
        seen["cfg_existed"] = cfg.exists()
        seen["cfg"] = cfg
        return Done()

    monkeypatch.setattr(cr.tempfile, "mkdtemp", mkdtemp)
    monkeypatch.setattr(cr.subprocess, "run", fake_run)
    r = cr.ClaudeRunner("postgresql://x", tools_enabled=True)
    reply = r.ask("q")
    assert reply.answer.endswith("ANSWER: 1") and r.model == "m1" and r.models_seen == {"m1"}
    assert seen["cfg_existed"] and not seen["cfg"].exists()
    assert made and not any(d.exists() for d in made)


def test_runners_send_the_prompt_unchanged():
    # The ANSWER suffix is added once, by evals.run, for every runner (test_run checks it).
    work = tempfile.mkdtemp()
    for tools in (True, False):
        inv = cr.ClaudeRunner("postgresql://x", tools_enabled=tools).invocation("Q?", work)
        assert inv.stdin == "Q?"
    bodies = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json={"message": {"role": "assistant", "content": "ANSWER: 1"}})

    client = OllamaClient("http://ollama.test", "fake:1b", transport=httpx.MockTransport(handler))
    for tools in (True, False):
        OllamaRunner(conn=None, client=client, tools_enabled=tools).ask("Q?")
    assert [b["messages"][-1]["content"] for b in bodies] == ["Q?"] * 2


def test_ollama_eval_budget_and_stop_reasons(monkeypatch):
    from evals.runners import ollama as orun
    from linecopilot.chat.loop import ChatResult

    assert config(True)["time_budget_s"] == 1800 and config(True, 50)["time_budget_s"] == 50
    seen = {}

    def fake_run_chat(conn, client, messages, **kw):
        seen.update(kw)
        return ChatResult(
            answer="The tool loop stopped after 9 s without a final answer.",
            citations=[],
            cited_event_ids=[],
            unsupported_cited_ids=[],
            tool_calls=[],
            model="m",
            rounds=2,
            stop_reason="budget",
        )

    monkeypatch.setattr(orun, "run_chat", fake_run_chat)
    client = OllamaClient("http://ollama.test", "m")
    runner = OllamaRunner(conn=None, client=client, tools_enabled=True, budget_s=9)
    reply = runner.ask("Q?")
    assert seen["time_budget_s"] == 9 and seen["max_rounds"] == orun.MAX_ROUNDS
    assert reply.error == "budget"


def test_ollama_retries_once_on_timeout():
    from evals.runners.ollama import RetryingClient

    calls = []

    def slow_then_ok(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        if len(calls) == 1:
            raise httpx.ReadTimeout("slow", request=request)
        return httpx.Response(200, json={"message": {"role": "assistant", "content": "ANSWER: 1"}})

    client = OllamaClient(
        "http://ollama.test", "fake:1b", transport=httpx.MockTransport(slow_then_ok), timeout=600
    )
    runner = OllamaRunner(conn=None, client=client, tools_enabled=False)
    reply = runner.ask("Q?")
    assert reply.answer == "ANSWER: 1" and reply.retries == 1 and runner.retries_total == 1
    assert runner.meta()["timeout_s"] == 600 and runner.meta()["retries_on_timeout"] == 1

    def always_slow(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    client = OllamaClient("http://ollama.test", "m", transport=httpx.MockTransport(always_slow))
    reply = OllamaRunner(conn=None, client=client, tools_enabled=False).ask("Q?")
    assert "timed out" in reply.error and reply.retries == 1
    wrapped = RetryingClient(client, retries=1)
    assert wrapped.model == "m"


def test_stage2_tool_list_is_the_original_twelve_and_still_in_the_registry():
    assert len(STAGE2_TOOLS) == 12 and len(set(STAGE2_TOOLS)) == 12
    assert set(STAGE2_TOOLS) < set(TOOLS)
    assert {"get_plan", "shortages", "get_order"} == set(TOOLS) - set(STAGE2_TOOLS)
    assert cr.allowed_tools() == [f"mcp__linecopilot__{n}" for n in STAGE2_TOOLS]
