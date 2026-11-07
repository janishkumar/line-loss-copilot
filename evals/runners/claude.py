"""Claude runners: `claude -p` headless, on normal plan limits.

`claude`: only this project's MCP server, only its read tools allowed, no built-in tools.
`claude-notools`: no MCP servers and no built-in tools, so it cannot read evals/ or query
Postgres. Both run from a fresh empty temporary directory outside the repo, so no project
instructions file or project settings are picked up; the MCP server is started by absolute
path. The prompt goes in on stdin (several flags take variadic values).

The invocation builders are pure functions so the sandbox can be checked by tests."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from evals.runners import Reply
from linecopilot.chat.prompt import SYSTEM_PROMPT
from linecopilot.tools.registry import TOOLS

SERVER = "linecopilot"
REPO = Path(__file__).resolve().parents[2]
BUILTIN_TOOLS = (
    "Bash",
    "Edit",
    "Glob",
    "Grep",
    "LS",
    "MultiEdit",
    "NotebookEdit",
    "NotebookRead",
    "Read",
    "Task",
    "TodoWrite",
    "WebFetch",
    "WebSearch",
    "Write",
)
TIMEOUT_S = 600
# Which settings files to load: none, so user hooks and project settings stay out.
SETTING_SOURCES = ""


@dataclass(frozen=True)
class Invocation:
    argv: list[str]
    cwd: str
    stdin: str
    mcp_config: dict[str, Any]


def allowed_tools() -> list[str]:
    return [f"mcp__{SERVER}__{name}" for name in TOOLS]


def mcp_config(db_url: str, repo: Path = REPO, python: str = sys.executable) -> dict[str, Any]:
    return {
        "mcpServers": {
            SERVER: {
                "command": python,
                "args": ["-m", "linecopilot.mcp_server"],
                "env": {"LINECOPILOT_DB_URL": db_url, "PYTHONPATH": str(repo / "src")},
            }
        }
    }


def _base(model: str | None) -> list[str]:
    argv = [
        "claude",
        "-p",
        "--output-format",
        "json",
        "--no-session-persistence",
        "--disable-slash-commands",
        "--setting-sources",
        SETTING_SOURCES,
        "--strict-mcp-config",
        "--tools",
        "",
        "--disallowedTools",
        ",".join(BUILTIN_TOOLS),
        "--append-system-prompt",
        SYSTEM_PROMPT,
    ]
    if model:
        argv += ["--model", model]
    return argv


def tools_invocation(
    prompt: str, db_url: str, workdir: str, config_path: str, model: str | None = None
) -> Invocation:
    cfg = mcp_config(db_url)
    argv = _base(model) + [
        "--mcp-config",
        config_path,
        "--allowedTools",
        ",".join(allowed_tools()),
        "--permission-mode",
        "dontAsk",
    ]
    return Invocation(argv=argv, cwd=workdir, stdin=prompt, mcp_config=cfg)


def notools_invocation(prompt: str, workdir: str, model: str | None = None) -> Invocation:
    cfg: dict[str, Any] = {"mcpServers": {}}
    argv = _base(model) + ["--mcp-config", json.dumps(cfg), "--permission-mode", "dontAsk"]
    return Invocation(argv=argv, cwd=workdir, stdin=prompt, mcp_config=cfg)


def child_env() -> dict[str, str]:
    """The parent environment without database settings, so nothing but the MCP config
    tells the child where the data is."""
    drop = ("LINECOPILOT_", "PG", "DATABASE_URL")
    return {k: v for k, v in os.environ.items() if not k.startswith(drop)}


def _main_model(usage: Any) -> str | None:
    """The model that wrote the most output tokens (a run can use a small helper model too)."""
    if not isinstance(usage, dict) or not usage:
        return None

    def out_tokens(v: Any) -> float:
        return float((v or {}).get("outputTokens") or 0) if isinstance(v, dict) else 0.0

    return max(usage, key=lambda k: (out_tokens(usage[k]), k))


def parse_output(stdout: str, model: str | None = None) -> tuple[str, str | None, dict]:
    """(answer, model id, extra) from `--output-format json`. The model id is the usage
    block's model with the most output tokens, else the result's model, else --model; every
    model in the usage block is kept in extra['models']."""
    try:
        data = json.loads(stdout)
    except ValueError:
        return stdout, model, {"parse_error": "output was not JSON"}
    if isinstance(data, list):  # some versions print the event list
        data = next((d for d in reversed(data) if d.get("type") == "result"), {})
    usage = data.get("modelUsage") or {}
    model_id = _main_model(usage)
    extra = {
        k: data.get(k) for k in ("num_turns", "duration_ms", "is_error", "subtype") if k in data
    }
    if isinstance(usage, dict) and usage:
        extra["models"] = sorted(usage)
    return str(data.get("result") or ""), model_id or data.get("model") or model, extra


class ClaudeRunner:
    def __init__(self, db_url: str, tools_enabled: bool, model: str | None = None):
        self.db_url = db_url
        self.tools_enabled = tools_enabled
        self.model_arg = model
        self.model = model or "claude-default"
        self.name = "claude" if tools_enabled else "claude-notools"
        self.models_seen: set[str] = set()

    def meta(self) -> dict[str, Any]:
        try:
            v = subprocess.run(
                ["claude", "--version"], capture_output=True, text=True, timeout=30
            ).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            v = None
        return {"model": self.model, "claude_cli_version": v}

    def invocation(self, prompt: str, workdir: str) -> Invocation:
        if not self.tools_enabled:
            return notools_invocation(prompt, workdir, self.model_arg)
        path = str(Path(workdir).parent / f"{Path(workdir).name}-mcp.json")
        return tools_invocation(prompt, self.db_url, workdir, path, self.model_arg)

    def ask(self, prompt: str) -> Reply:
        workdir = tempfile.mkdtemp(prefix="linecopilot-eval-")
        cfg_path: Path | None = None
        try:
            inv = self.invocation(prompt, workdir)
            if self.tools_enabled:
                cfg_path = Path(inv.argv[inv.argv.index("--mcp-config") + 1])
                cfg_path.write_text(json.dumps(inv.mcp_config))
            return self._run(inv)
        finally:
            shutil.rmtree(workdir, ignore_errors=True)
            if cfg_path is not None:
                cfg_path.unlink(missing_ok=True)

    def _run(self, inv: Invocation) -> Reply:
        t0 = time.monotonic()
        try:
            proc = subprocess.run(
                inv.argv,
                input=inv.stdin,
                cwd=inv.cwd,
                env=child_env(),
                capture_output=True,
                text=True,
                timeout=TIMEOUT_S,
            )
        except (OSError, subprocess.SubprocessError) as e:
            return Reply(answer="", latency_s=time.monotonic() - t0, error=str(e))
        latency = time.monotonic() - t0
        answer, model_id, extra = parse_output(proc.stdout, self.model_arg)
        if model_id:
            self.model = model_id
        self.models_seen.update(extra.get("models", []))
        err = None
        if proc.returncode != 0 or extra.get("is_error"):
            err = f"claude exited {proc.returncode}: {(proc.stderr or proc.stdout)[:300]}"
        return Reply(
            answer=answer,
            latency_s=latency,
            model_id=model_id,
            rounds=extra.get("num_turns"),
            error=err,
        )
