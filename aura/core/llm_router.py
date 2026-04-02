"""Local Ollama routing for AURA."""

from __future__ import annotations

import inspect
from dataclasses import dataclass
from typing import Any, Sequence

try:  # pragma: no cover - import availability depends on environment
    import ollama  # type: ignore
except Exception:  # pragma: no cover
    ollama = None  # type: ignore[assignment]


@dataclass(slots=True)
class LLMResult:
    """Structured response from a model invocation."""

    ok: bool
    model: str
    content: str | None = None
    raw: Any | None = None
    error: str | None = None


class OllamaRouter:
    """Route chat requests to a configured local Ollama model."""

    def __init__(self, model: str, host: str = "http://127.0.0.1:11434", client: Any | None = None) -> None:
        self.model = model
        self.host = host
        self._client = client

    def _resolve_client(self) -> Any:
        if self._client is not None:
            return self._client
        if ollama is None:
            return None
        if hasattr(ollama, "Client"):
            return ollama.Client(host=self.host)
        if hasattr(ollama, "AsyncClient"):
            return ollama.AsyncClient(host=self.host)
        return None

    async def chat(self, messages: Sequence[dict[str, str]], options: dict[str, Any] | None = None) -> LLMResult:
        """Send chat messages to Ollama and return a structured result."""

        client = self._resolve_client()
        if client is None:
            return LLMResult(ok=False, model=self.model, error="ollama-client-unavailable")
        payload = list(messages)
        kwargs = {"model": self.model, "messages": payload}
        if options:
            kwargs["options"] = options
        try:
            response = client.chat(**kwargs)
            if inspect.isawaitable(response):
                response = await response
            content = self._extract_content(response)
            return LLMResult(ok=True, model=self.model, content=content, raw=response)
        except Exception as exc:
            return LLMResult(ok=False, model=self.model, error=str(exc))

    async def generate(self, prompt: str, system: str | None = None) -> LLMResult:
        """Convenience wrapper for a single-turn prompt."""

        messages = []
        if system is not None:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        return await self.chat(messages)

    @staticmethod
    def _extract_content(response: Any) -> str:
        if isinstance(response, dict):
            message = response.get("message") or {}
            if isinstance(message, dict) and "content" in message:
                return str(message["content"])
            if "response" in response:
                return str(response["response"])
        return str(response)
