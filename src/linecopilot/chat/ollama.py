"""Minimal Ollama client: one non-streaming /api/chat call, plus /api/tags for model digests."""

from __future__ import annotations

from typing import Any

import httpx

# temperature 0 and a fixed seed make answers repeatable for evals; num_ctx is raised from
# Ollama's small default so tool results are not silently cut off.
OPTIONS: dict[str, Any] = {"temperature": 0, "seed": 0, "num_ctx": 16384}
TIMEOUT_S = 180.0


class OllamaError(RuntimeError):
    """Ollama answered with an error status or an unreadable body."""


class OllamaUnreachable(OllamaError):
    """No connection to Ollama (refused or DNS)."""


class OllamaTimeout(OllamaError):
    """Ollama took longer than the client timeout."""


class OllamaClient:
    def __init__(
        self,
        base_url: str,
        model: str,
        transport: httpx.BaseTransport | None = None,
        timeout: float = TIMEOUT_S,
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self._http = httpx.Client(base_url=self.base_url, transport=transport, timeout=timeout)

    def _request(self, method: str, path: str, **kw: Any) -> dict:
        try:
            resp = self._http.request(method, path, **kw)
        except httpx.ConnectError as e:
            raise OllamaUnreachable(f"local model not reachable at {self.base_url}") from e
        except httpx.TimeoutException as e:
            raise OllamaTimeout(f"local model timed out after {self.timeout:g} s") from e
        except httpx.TransportError as e:
            raise OllamaError(f"local model connection failed: {type(e).__name__}") from e
        if resp.status_code >= 400:
            raise OllamaError(f"local model returned {resp.status_code}: {resp.text[:200]}")
        try:
            body = resp.json()
        except ValueError as e:
            raise OllamaError("local model returned a body that is not JSON") from e
        if not isinstance(body, dict):
            raise OllamaError("local model returned a body that is not a JSON object")
        return body

    def chat(self, messages: list[dict], tools: list[dict]) -> dict:
        return self._request(
            "POST",
            "/api/chat",
            json={
                "model": self.model,
                "messages": messages,
                "tools": tools,
                "stream": False,
                "options": OPTIONS,
            },
        )

    def version(self) -> str | None:
        return self._request("GET", "/api/version").get("version")

    def tags(self) -> list[dict]:
        return list(self._request("GET", "/api/tags").get("models", []))

    def close(self) -> None:
        self._http.close()
