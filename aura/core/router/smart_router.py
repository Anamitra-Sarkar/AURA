"""Smart multi-provider router."""

from __future__ import annotations

import asyncio
from dataclasses import asdict
from typing import Any

from .failover import build_fallback_chain
from .models import ProviderCall, ProviderUnavailableError, RateLimitError
from .providers.cerebras import CerebrasClient
from .providers.cloudflare import CloudflareClient
from .providers.gemini import GeminiClient
from .providers.groq import GroqClient
from .providers.mistral import MistralClient
from .providers.openrouter import OpenRouterClient
from .providers.xai import XAIClient
from .quota_tracker import QuotaTracker
from .registry import ModelRegistry
from .task_classifier import TaskClassifier


class SmartRouter:
    """Route requests across verified free providers."""

    def __init__(self, quota_tracker: QuotaTracker, event_bus: Any | None = None) -> None:
        self.quota_tracker = quota_tracker
        self.event_bus = event_bus
        self.registry = ModelRegistry()
        self.classifier = TaskClassifier()
        self.providers = {
            "groq": GroqClient(),
            "openrouter": OpenRouterClient(),
            "cerebras": CerebrasClient(),
            "gemini": GeminiClient(),
            "mistral": MistralClient(),
            "cloudflare": CloudflareClient(),
            "xai": XAIClient(),
        }

    async def complete(
        self,
        task: str,
        messages: list[dict[str, Any]],
        importance: int = 2,
        force_provider: str | None = None,
        force_model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        tools: list[dict[str, Any]] | None = None,
    ) -> ProviderCall:
        self.quota_tracker.reset_if_new_day()
        if force_provider and force_model:
            decision = self.classifier.classify(task, context=" ".join(str(message.get("content", "")) for message in messages))
            chain = [f"{force_provider}:{force_model}", *[entry for entry in decision.fallback_chain if entry != f"{force_provider}:{force_model}"]]
        elif importance == 1:
            chain = [
                "cerebras:llama-4-scout",
                "groq:llama-3.1-8b-instant",
                "cloudflare:@cf/meta/llama-3.3-70b-instruct-fp8-fast",
                "openrouter:openrouter/auto",
            ]
        else:
            decision = self.classifier.classify(task, context=" ".join(str(message.get("content", "")) for message in messages))
            chain = decision.fallback_chain or build_fallback_chain(decision.task_tags, self.quota_tracker)
        last_error = ""
        for entry in chain:
            provider, model = entry.split(":", 1)
            if not self.quota_tracker.is_available(provider, model):
                continue
            provider_client = self.providers.get(provider)
            if provider_client is None:
                continue
            try:
                result = await provider_client.complete(model, messages, max_tokens, temperature, tools)
                self.quota_tracker.record_usage(provider, model, result.tokens_used, 1)
                if self.event_bus is not None:
                    await self.event_bus.publish("router.call_completed", asdict(result))
                return result
            except RateLimitError:
                self.quota_tracker.mark_rate_limited(provider, model)
                last_error = f"{provider}:{model}:rate_limited"
                continue
            except ProviderUnavailableError as exc:
                last_error = str(exc)
                continue
        return ProviderCall(
            provider="local",
            model="fallback",
            prompt=task,
            response=f"Offline fallback response for: {task[:120]}",
            tokens_used=0,
            latency_ms=0,
            success=True,
            error=last_error or "",
        )

    async def ensemble_complete(self, task: str, messages: list[dict[str, Any]], n_providers: int = 4, importance: int = 3) -> list[ProviderCall]:
        decision = self.classifier.classify(task, context=" ".join(str(message.get("content", "")) for message in messages))
        chain = build_fallback_chain(decision.task_tags, self.quota_tracker)
        providers: list[str] = []
        seen: set[str] = set()
        for entry in chain:
            provider, _model = entry.split(":", 1)
            if provider in seen:
                continue
            seen.add(provider)
            providers.append(provider)
            if len(providers) >= n_providers:
                break
        tasks = []
        selected_models: list[tuple[str, str]] = []
        for provider in providers:
            entry = next((item for item in chain if item.startswith(f"{provider}:")), None)
            if entry is None:
                continue
            _provider, model = entry.split(":", 1)
            selected_models.append((_provider, model))
            tasks.append(self.providers[_provider].complete(model, messages, 4096, 0.7, None))
        results = await asyncio.gather(*tasks, return_exceptions=True)
        calls: list[ProviderCall] = []
        for (provider, model), result in zip(selected_models, results, strict=False):
            if isinstance(result, Exception):
                continue
            self.quota_tracker.record_usage(provider, model, result.tokens_used, 1)
            calls.append(result)
        return calls

    async def generate(self, prompt: str, system: str | None = None) -> ProviderCall:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        return await self.complete(prompt, messages)

    async def chat(self, messages: list[dict[str, Any]]) -> ProviderCall:
        prompt = "\n".join(str(message.get("content", "")) for message in messages)
        return await self.complete(prompt, messages)
