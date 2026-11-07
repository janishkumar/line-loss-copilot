"""Ollama runners: the web chat loop in-process, with every tool (`ollama`) or none
(`ollama-notools`, which sends an empty tool list so the model sees no data)."""

from __future__ import annotations

import time
from typing import Any

from evals.runners import Reply, build_prompt
from linecopilot.chat.loop import run_chat
from linecopilot.chat.ollama import OllamaClient, OllamaError, OllamaTimeout

RETRIES_ON_TIMEOUT = 1


class RetryingClient:
    """Wraps an OllamaClient: a chat call that times out is tried again, up to `retries`
    times, and every retry is counted."""

    def __init__(self, client: OllamaClient, retries: int = RETRIES_ON_TIMEOUT):
        self.client = client
        self.retries = retries
        self.retry_count = 0

    @property
    def model(self) -> str:
        return self.client.model

    def chat(self, messages: list[dict], tools: list[dict]) -> dict:
        for attempt in range(self.retries + 1):
            try:
                return self.client.chat(messages, tools)
            except OllamaTimeout:
                if attempt == self.retries:
                    raise
                self.retry_count += 1
        raise AssertionError("unreachable")


def config(tools_enabled: bool) -> dict[str, Any]:
    """What the runner passes to run_chat; the no-tools baseline differs only here."""
    return {"tools_enabled": tools_enabled}


class OllamaRunner:
    def __init__(
        self,
        conn: Any,
        client: OllamaClient,
        tools_enabled: bool,
        retries: int = RETRIES_ON_TIMEOUT,
    ):
        self.conn = conn
        self.client = client
        self.retries = retries
        self.retries_total = 0
        self.tools_enabled = tools_enabled
        self.name = "ollama" if tools_enabled else "ollama-notools"

    @property
    def model(self) -> str:
        return self.client.model

    def meta(self) -> dict[str, Any]:
        """Model name, digest and Ollama version; missing values stay None."""
        out: dict[str, Any] = {
            "model": self.model,
            "model_digest": None,
            "ollama_version": None,
            "timeout_s": self.client.timeout,
            "retries_on_timeout": self.retries,
        }
        try:
            out["ollama_version"] = self.client.version()
            for m in self.client.tags():
                if m.get("name") == self.model or m.get("model") == self.model:
                    out["model_digest"] = m.get("digest")
        except OllamaError as e:
            out["meta_error"] = str(e)
        return out

    def ask(self, prompt: str) -> Reply:
        t0 = time.monotonic()
        client = RetryingClient(self.client, self.retries)
        try:
            res = run_chat(
                self.conn,
                client,  # type: ignore[arg-type]
                [{"role": "user", "content": build_prompt(prompt)}],
                **config(self.tools_enabled),
            )
        except OllamaError as e:
            self.retries_total += client.retry_count
            return Reply(
                answer="",
                latency_s=time.monotonic() - t0,
                error=str(e),
                retries=client.retry_count,
            )
        self.retries_total += client.retry_count
        return Reply(
            answer=res.answer,
            latency_s=time.monotonic() - t0,
            model_id=res.model,
            tool_calls=[tc.model_dump(mode="json") for tc in res.tool_calls],
            rounds=res.rounds,
            retries=client.retry_count,
        )
