"""LLM routing for AURA — local Ollama + multi-provider SmartRouter adapter."""

from __future__ import annotations

import inspect
import os
from dataclasses import dataclass
from typing import Any, Sequence

try:  # pragma: no cover - import availability depends on environment
    import ollama  # type: ignore
except Exception:  # pragma: no cover
    ollama = None  # type: ignore[assignment]

# ---------------------------------------------------------------------------
# Provider API key env-var names.  Presence of the var means the provider
# is configured and should be attempted.  Absence means skip it entirely
# rather than returning a 401 that wastes quota.
# ---------------------------------------------------------------------------
_PROVIDER_KEY_VARS: dict[str, str] = {
    "groq": "GROQ_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "mistral": "MISTRAL_API_KEY",
    "cerebras": "CEREBRAS_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "cloudflare": "CLOUDFLARE_API_TOKEN",
    "xai": "XAI_API_KEY",
}


def _keyed_providers() -> list[str]:
    """Return list of providers whose API key env var is actually set."""
    return [p for p, var in _PROVIDER_KEY_VARS.items() if os.getenv(var)]


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

    def __init__(self, model: str, host: str = "", client: Any | None = None) -> None:
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

    async def chat(
        self,
        messages: Sequence[dict[str, str]],
        options: dict[str, Any] | None = None,
    ) -> LLMResult:
        """Send chat messages to Ollama and return a structured result."""
        client = self._resolve_client()
        if client is None:
            return LLMResult(ok=False, model=self.model, error="ollama-client-unavailable")
        payload = list(messages)
        kwargs: dict[str, Any] = {"model": self.model, "messages": payload}
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
        messages: list[dict[str, str]] = []
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


class SmartRouterAdapter:
    """Wraps SmartRouter to expose the same .chat() interface as OllamaRouter.

    agent_loop.py calls ``router.chat(messages)`` and expects an ``LLMResult``.
    ``SmartRouter.complete(task, messages)`` is the correct entry-point; it runs
    the TaskClassifier and picks the best available provider.  This adapter:

    1. Extracts the task string from the last user message so the classifier
       gets real text (not an empty string).
    2. Skips providers whose API key env var is not set — avoids 401 errors
       that would uselessly consume the fallback chain.
    3. Translates ProviderCall -> LLMResult so agent_loop.py is unchanged.
    """

    def __init__(self, smart_router: Any) -> None:
        self._router = smart_router

    @staticmethod
    def _task_from_messages(messages: Sequence[dict[str, Any]]) -> str:
        """Extract the last user message content as the task description."""
        for msg in reversed(messages):
            if msg.get("role") == "user":
                return str(msg.get("content") or "").strip()
        # Fallback: concatenate all content fields
        return " ".join(
            str(m.get("content") or "") for m in messages
        ).strip()

    async def chat(
        self,
        messages: Sequence[dict[str, Any]],
        options: dict[str, Any] | None = None,
        importance: int = 2,
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> LLMResult:
        """Dispatch to SmartRouter.complete() and translate to LLMResult.

        We call ``complete()`` rather than ``chat()`` because ``complete()``
        runs the TaskClassifier and respects the quota/fallback chain.
        ``SmartRouter.chat()`` bypasses classification entirely.
        """
        task = self._task_from_messages(messages)
        keyed = _keyed_providers()

        # If no provider keys are configured at all, return a helpful error
        # rather than silently returning the offline fallback every time.
        if not keyed:
            return LLMResult(
                ok=False,
                model="smart_router",
                error=(
                    "No LLM provider API keys found. "
                    "Set at least one of: "
                    + ", ".join(_PROVIDER_KEY_VARS.values())
                    + " as a HuggingFace Space Secret or environment variable."
                ),
            )

        try:
            result = await self._router.complete(
                task=task,
                messages=list(messages),
                importance=importance,
                max_tokens=max_tokens,
                temperature=temperature,
            )
            ok = bool(getattr(result, "success", True))
            content = str(getattr(result, "response", "") or "")
            error_str = str(getattr(result, "error", "") or "") or None
            model_label = (
                f"{getattr(result, 'provider', 'unknown')}:"
                f"{getattr(result, 'model', 'unknown')}"
            )
            # The offline fallback returns success=True with provider='local'.
            # Surface it as an error so the frontend can show a warning.
            if getattr(result, "provider", "") == "local":
                return LLMResult(
                    ok=False,
                    model=model_label,
                    content=content,
                    error="all-providers-exhausted",
                    raw=result,
                )
            if not ok and not content:
                return LLMResult(ok=False, model=model_label, error=error_str or "provider-error")
            return LLMResult(
                ok=True,
                model=model_label,
                content=content,
                raw=result,
                error=error_str,
            )
        except Exception as exc:
            return LLMResult(ok=False, model="smart_router", error=str(exc))

    async def generate(self, prompt: str, system: str | None = None) -> LLMResult:
        """Single-turn convenience wrapper."""
        messages: list[dict[str, Any]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        return await self.chat(messages)

    @property
    def keyed_providers(self) -> list[str]:
        """Providers that have an API key configured right now."""
        return _keyed_providers()
