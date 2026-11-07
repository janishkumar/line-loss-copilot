"""Ollama runners: the web chat loop in-process, with every tool (`ollama`) or none
(`ollama-notools`, which sends an empty tool list so the model sees no data)."""

from __future__ import annotations

import time
from typing import Any

from evals.runners import Reply
from linecopilot.chat.loop import run_chat
from linecopilot.chat.ollama import OllamaClient, OllamaError


def config(tools_enabled: bool) -> dict[str, Any]:
    """What the runner passes to run_chat; the no-tools baseline differs only here."""
    return {"tools_enabled": tools_enabled}


class OllamaRunner:
    def __init__(self, conn: Any, client: OllamaClient, tools_enabled: bool):
        self.conn = conn
        self.client = client
        self.tools_enabled = tools_enabled
        self.name = "ollama" if tools_enabled else "ollama-notools"

    @property
    def model(self) -> str:
        return self.client.model

    def meta(self) -> dict[str, Any]:
        """Model name, digest and Ollama version; missing values stay None."""
        out: dict[str, Any] = {"model": self.model, "model_digest": None, "ollama_version": None}
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
        try:
            res = run_chat(
                self.conn,
                self.client,
                [{"role": "user", "content": prompt}],
                **config(self.tools_enabled),
            )
        except OllamaError as e:
            return Reply(answer="", latency_s=time.monotonic() - t0, error=str(e))
        return Reply(
            answer=res.answer,
            latency_s=time.monotonic() - t0,
            model_id=res.model,
            tool_calls=[tc.model_dump(mode="json") for tc in res.tool_calls],
            rounds=res.rounds,
        )
