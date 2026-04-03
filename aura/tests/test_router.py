from __future__ import annotations

from pathlib import Path

import pytest

from aura.core.router.models import ProviderCall, ProviderUnavailableError
from aura.core.router.quota_tracker import QuotaTracker
from aura.core.router.smart_router import SmartRouter
from aura.core.router.task_classifier import TaskClassifier


def test_classifier_routes_by_intent():
    classifier = TaskClassifier()
    coding = classifier.classify("fix the bug in this script")
    reasoning = classifier.classify("analyze this decision")
    long_context = classifier.classify("x" * 60000, context="y" * 200000)
    assert coding.selected_provider == "openrouter"
    assert coding.selected_model == "qwen/qwen3-coder-480b-a35b:free"
    assert reasoning.selected_provider == "groq"
    assert long_context.selected_provider == "gemini"


def test_quota_tracker_limits_and_reset(tmp_path: Path):
    tracker = QuotaTracker(tmp_path / "quota.db")
    tracker.record_usage("openrouter", "openai/gpt-oss-120b:free", tokens=10, requests=200)
    assert tracker.is_available("openrouter", "openai/gpt-oss-120b:free") is False
    tracker.reset_if_new_day()
    assert "requests_remaining" in tracker.get_remaining("openrouter", "openai/gpt-oss-120b:free")


@pytest.mark.asyncio
async def test_smart_router_falls_through_and_ensemble(tmp_path: Path):
    tracker = QuotaTracker(tmp_path / "quota.db")
    router = SmartRouter(tracker)

    calls: list[str] = []

    class Failing:
        async def complete(self, model_id, messages, max_tokens, temperature, tools):
            calls.append(model_id)
            raise ProviderUnavailableError("nope")

    class Succeeding:
        async def complete(self, model_id, messages, max_tokens, temperature, tools):
            calls.append(model_id)
            return ProviderCall(provider="groq", model=model_id, prompt="p", response="ok", tokens_used=1, latency_ms=1, success=True)

    router.providers["groq"] = Failing()
    router.providers["cerebras"] = Failing()
    router.providers["xai"] = Succeeding()
    result = await router.complete("analyze this decision", [{"role": "user", "content": "analyze this decision"}])
    assert result.response == "ok"
    assert calls == ["deepseek-r1-distill-llama-70b", "deepseek-r1", "grok-4"]

    router.providers["openrouter"] = Failing()
    router.providers["groq"] = Succeeding()
    router.providers["cerebras"] = Succeeding()
    ensemble = await router.ensemble_complete("research quantum computing", [{"role": "user", "content": "research quantum computing"}], n_providers=3)
    assert len(ensemble) == 2
