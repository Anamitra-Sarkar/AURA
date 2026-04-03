"""Static model registry for the AURA router."""

from __future__ import annotations

from typing import Any

from .models import ModelProfile


class ModelRegistry:
    """Registry of verified free models."""

    def __init__(self) -> None:
        self._providers: dict[str, list[ModelProfile]] = {}
        self._models: list[ModelProfile] = []
        self._load_defaults()

    def _register(self, model: ModelProfile) -> None:
        self._models.append(model)
        self._providers.setdefault(model.provider, []).append(model)

    def _load_defaults(self) -> None:
        # Groq
        for model_id, ctx, speed, tags in [
            ("llama-3.3-70b-versatile", 128_000, "fast", ["reasoning", "general", "long_context", "agents"]),
            ("llama-3.1-8b-instant", 128_000, "ultra_fast", ["fast", "edge"]),
            ("llama-4-scout-17b-16e-instruct", 328_000, "fast", ["general", "long_context"]),
            ("deepseek-r1-distill-llama-70b", 128_000, "fast", ["reasoning"]),
            ("gemma2-9b-it", 8_000, "ultra_fast", ["fast", "edge"]),
            ("qwen-qwen3-32b", 32_000, "fast", ["multilingual", "general"]),
            ("meta-llama/llama-guard-4-12b", 8_000, "fast", ["safety"]),
            ("openai/gpt-oss-120b", 131_000, "medium", ["general", "agents"]),
        ]:
            self._register(ModelProfile("groq", model_id, ctx, speed, tags, 14400 if "8b" in model_id else 1000, 60, True))

        # OpenRouter
        for model_id, ctx, speed, tags in [
            ("stepfun/step-3.5-flash:free", 256_000, "fast", ["agents", "reasoning"]),
            ("nvidia/nemotron-3-super-120b:free", 262_000, "fast", ["reasoning", "agents"]),
            ("qwen/qwen3.6-plus:free", 1_000_000, "fast", ["coding", "long_context", "agents"]),
            ("arcee-ai/arcee-trinity-large:free", 128_000, "fast", ["creative", "agents"]),
            ("zhipuai/glm-4.5-air:free", 131_000, "fast", ["multilingual", "tools"]),
            ("nvidia/nemotron-3-nano-30b-a3b:free", 256_000, "fast", ["fast"]),
            ("arcee-ai/arcee-trinity-mini:free", 131_000, "ultra_fast", ["fast", "agents"]),
            ("nvidia/nemotron-nano-12b-2-vl:free", 128_000, "fast", ["vision"]),
            ("nvidia/nemotron-nano-9b-v2:free", 128_000, "fast", ["reasoning"]),
            ("minimax/minimax-m2.5:free", 197_000, "fast", ["coding", "agents"]),
            ("qwen/qwen3-coder-480b-a35b:free", 262_000, "fast", ["coding"]),
            ("openai/gpt-oss-120b:free", 131_000, "fast", ["general"]),
            ("qwen/qwen3-next-80b-a3b:free", 262_000, "fast", ["rag", "agents"]),
            ("openai/gpt-oss-20b:free", 131_000, "ultra_fast", ["fast", "edge"]),
            ("meta-llama/llama-3.3-70b-instruct:free", 66_000, "fast", ["general"]),
            ("liquid/lfm2.5-1.2b-thinking:free", 32_000, "ultra_fast", ["edge", "fast"]),
            ("openrouter/auto", 0, "fast", ["general"]),
        ]:
            self._register(ModelProfile("openrouter", model_id, ctx, speed, tags, 200, 10, True))

        # Cerebras
        for model_id, ctx, speed, tags in [
            ("llama-3.3-70b", 128_000, "fast", ["general", "reasoning"]),
            ("llama-4-scout", 10_000_000, "fast", ["long_context", "general"]),
            ("deepseek-r1", 128_000, "fast", ["reasoning"]),
        ]:
            self._register(ModelProfile("cerebras", model_id, ctx, speed, tags, 1_000_000, 1000, True))

        # Gemini
        for model_id, rpm in [
            ("gemini-2.5-pro", 5),
            ("gemini-2.5-flash", 10),
            ("gemini-2.5-flash-lite", 15),
        ]:
            self._register(ModelProfile("gemini", model_id, 1_000_000, "fast" if model_id.endswith("flash") else "medium", ["long_context", "general"], 1000, rpm, True))

        # Mistral
        for model_id, ctx, speed, tags in [
            ("mistral-large-latest", 128_000, "fast", ["general", "reasoning"]),
            ("mistral-medium-latest", 128_000, "fast", ["general"]),
            ("codestral-latest", 256_000, "fast", ["coding"]),
            ("pixtral-12b-latest", 128_000, "fast", ["vision"]),
            ("mistral-small-latest", 128_000, "ultra_fast", ["fast"]),
        ]:
            self._register(ModelProfile("mistral", model_id, ctx, speed, tags, 33_000_000, 2, True))

        # Cloudflare
        for model_id, ctx, tags in [
            ("@cf/meta/llama-3.3-70b-instruct-fp8-fast", 128_000, ["general", "fast"]),
            ("@cf/qwen/qwen3-30b-a3b", 32_000, ["general"]),
            ("@cf/meta/llama-4-scout-17b-16e-instruct", 128_000, ["general"]),
            ("@hf/openai/whisper-large-v3-turbo", 0, ["stt"]),
            ("@cf/baai/bge-large-en-v1.5", 0, ["embeddings"]),
        ]:
            self._register(ModelProfile("cloudflare", model_id, ctx, "fast", tags, 10_000, 1000, True))

        # XAI
        for model_id, ctx, speed, tags in [
            ("grok-4", 128_000, "fast", ["reasoning", "general"]),
            ("grok-4-mini", 128_000, "ultra_fast", ["fast", "reasoning"]),
            ("grok-4.1-fast", 2_000_000, "fast", ["long_context", "reasoning"]),
        ]:
            self._register(ModelProfile("xai", model_id, ctx, speed, tags, 0, 60, False))

    def get_models_by_tag(self, tag: str) -> list[ModelProfile]:
        return [model for model in self._models if tag in model.capability_tags]

    def get_models_by_provider(self, provider: str) -> list[ModelProfile]:
        return list(self._providers.get(provider, []))

    def get_fastest_models(self, n: int = 3) -> list[ModelProfile]:
        speed_rank = {"ultra_fast": 0, "fast": 1, "medium": 2, "slow": 3}
        return sorted(self._models, key=lambda model: (speed_rank.get(model.speed_tier, 99), -model.context_length, model.provider, model.model_id))[:n]

    def get_long_context_models(self, min_ctx: int) -> list[ModelProfile]:
        return sorted([model for model in self._models if model.context_length >= min_ctx], key=lambda model: (-model.context_length, model.provider, model.model_id))

    def get_available_models(self, quota_tracker: Any) -> list[ModelProfile]:
        return [model for model in self._models if quota_tracker.is_available(model.provider, model.model_id)]

    def all_models(self) -> list[ModelProfile]:
        return list(self._models)
