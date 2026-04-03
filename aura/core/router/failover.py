"""Failover chain builder."""

from __future__ import annotations

from .registry import ModelRegistry


def build_fallback_chain(task_tags: list[str], quota_tracker: object | None = None) -> list[str]:
    registry = ModelRegistry()
    provider_order = {
        "coding": ["openrouter", "mistral", "groq", "cerebras", "xai", "cloudflare"],
        "reasoning": ["groq", "cerebras", "xai", "openrouter", "mistral"],
        "long_context": ["gemini", "xai", "openrouter", "groq", "cerebras"],
        "rag": ["groq", "openrouter", "cerebras", "xai"],
        "multilingual": ["openrouter", "groq", "mistral", "gemini"],
        "fast": ["cerebras", "groq", "cloudflare", "openrouter"],
        "general": ["groq", "openrouter", "cerebras", "xai", "mistral"],
    }
    priorities = provider_order.get(task_tags[0] if task_tags else "general", provider_order["general"])
    preferred: list[str] = []
    for provider in priorities:
        models = registry.get_models_by_provider(provider)
        tagged = [model for model in models if not task_tags or any(tag in model.capability_tags for tag in task_tags)]
        pick = tagged[0] if tagged else (models[0] if models else None)
        if pick is None:
            continue
        entry = f"{pick.provider}:{pick.model_id}"
        if entry not in preferred:
            preferred.append(entry)
    if "openrouter:openrouter/auto" not in preferred:
        preferred.append("openrouter:openrouter/auto")
    return preferred
