from __future__ import annotations

import pytest

import aura.agents.ensemble.tools as ensemble
from aura.core.config import AppConfig, EnsembleSettings, FeatureFlags, ModelSettings, PathsSettings


@pytest.fixture()
def ensemble_config(tmp_path):
    config = AppConfig(
        name="AURA",
        offline_mode=True,
        log_level="INFO",
        primary_model=ModelSettings(provider="ollama", name="llama3:8b", host="http://127.0.0.1:11434"),
        fallback_models=[],
        paths=PathsSettings(
            allowed_roots=[tmp_path],
            data_dir=tmp_path,
            log_dir=tmp_path / "logs",
            memory_dir=tmp_path / "memory",
            ipc_socket=tmp_path / "aura.sock",
        ),
        features=FeatureFlags(hotkey=True, tray=True, ipc=True, api=True),
        source_path=tmp_path / "config.yaml",
        ensemble=EnsembleSettings(
            enabled=True,
            default_importance_threshold=2,
            models=["llama3:8b", "mistral:7b", "qwen2:7b"],
            judge_model="llama3:8b",
            model_timeout_seconds=5,
            min_successful_responses=2,
            fallback_to_single=True,
        ),
    )
    ensemble.set_config(config)
    return config


class FakeRouter:
    def __init__(self, model: str):
        self.model = model

    async def generate(self, prompt: str):
        if self.model == "llama3:8b" and '"responses"' in prompt:
            return type(
                "R",
                (),
                {
                    "ok": True,
                    "content": '{"agreements":["fact"],"disagreements":["detail"],"best_response_model":"mistral:7b","synthesized_answer":"best","confidence":0.8,"reasoning":"judge"}',
                },
            )()
        if self.model == "qwen2:7b":
            return type("R", (), {"ok": False, "content": "", "error": "boom"})()
        return type("R", (), {"ok": True, "content": f"answer-from-{self.model}"})()


@pytest.mark.asyncio
async def test_ensemble_debate_and_fallback(monkeypatch, ensemble_config):
    monkeypatch.setattr(ensemble, "_model_router", lambda model: FakeRouter(model))
    result = await ensemble.ensemble_answer("Explain photosynthesis", importance_level=3)
    assert result.models_used
    assert result.judge_model == "llama3:8b"
    assert result.confidence_score >= 0
    assert result.synthesized_answer

    single = await ensemble.ensemble_answer("Hi", importance_level=1)
    assert len(single.responses) == 1
    assert single.models_used == [single.responses[0].model_name]


@pytest.mark.asyncio
async def test_available_models_and_benchmark(monkeypatch, ensemble_config):
    monkeypatch.setattr(ensemble, "_model_router", lambda model: FakeRouter(model))
    models = await ensemble.get_available_models()
    assert models and models[0]["available"] is True
    benchmark = await ensemble.benchmark_models("Say hello")
    assert "llama3:8b" in benchmark
    assert benchmark["llama3:8b"]["score"] >= 0


def test_confidence_score_formula():
    assert ensemble._confidence_score(3, 3, 3) == pytest.approx(1.0)
    assert ensemble._confidence_score(1, 4, 3) < ensemble._confidence_score(3, 3, 3)
