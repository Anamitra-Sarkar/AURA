from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pytest

import aura.agents.mosaic.tools as mosaic
from aura.agents.logos import tools as logos_tools
from aura.agents.logos.models import RunResult
from aura.core.config import AppConfig, EnsembleSettings, FeatureFlags, LyraSettings, ModelSettings, PathsSettings, StreamSettings, UISettings
from aura.core.tools import get_tool_registry
from aura.memory import list_memories
from aura.memory.mneme import tools as mneme_tools


def _config(tmp_path: Path) -> AppConfig:
    return AppConfig(
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
        ensemble=EnsembleSettings(enabled=True, default_importance_threshold=2, models=["llama3:8b"], judge_model="llama3:8b", model_timeout_seconds=10, min_successful_responses=2, fallback_to_single=True),
        lyra=LyraSettings(enabled=True, voice_mode=False, stt_model="base", wake_word_engine="energy_threshold", wake_phrase="hey aura", wake_sensitivity=0.5, tts_rate=175, tts_volume=0.9, save_audio=False, noise_reduction=True),
        ui=UISettings(enabled=True, host="127.0.0.1", port=7437, open_browser_on_start=False),
        stream=StreamSettings(enabled=False, fetch_interval_hours=6, min_relevance_score=0.4, sources=[]),
    )


@dataclass
class FakeResponse:
    content: str


class FakeRouter:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def generate(self, prompt: str, system: str | None = None):
        self.calls.append(system or prompt)
        if system and "Extract key claims" in system:
            return FakeResponse(json.dumps({"claims": ["alpha"], "facts": ["1"], "concepts": ["transformers"]}))
        if system and "Given claims" in system:
            return FakeResponse(json.dumps({"overlaps": [{"topic": "transformers", "sources_agreeing": ["s1", "s2"], "sources_disagreeing": [], "resolution": "shared"}], "contradictions": [], "resolution_notes": ["ok"]}))
        if system and "Using these sources" in system:
            return FakeResponse("Synthesized artifact")
        return FakeResponse("0.9")


@pytest.fixture()
def mosaic_runtime(tmp_path):
    config = _config(tmp_path)
    mneme_tools.set_config(config)
    mosaic.set_config(config)
    router = FakeRouter()
    mosaic.set_router(router)
    return config, router


@pytest.mark.asyncio
async def test_synthesize_saves_memory_and_uses_router(mosaic_runtime):
    _config, router = mosaic_runtime
    sources = [
        mosaic.SourceInput(id="s1", type="text", content="alpha source", label="Alpha"),
        mosaic.SourceInput(id="s2", type="text", content="beta source", label="Beta", weight=2.0),
    ]

    result = await mosaic.synthesize("Integrate sources", sources, "markdown")

    assert result.output == "Synthesized artifact"
    assert result.confidence > 0
    assert result.word_count == 2
    assert len(result.sources_used) == 2
    assert router.calls[0].startswith("Extract key claims")
    assert router.calls[1].startswith("Extract key claims")
    assert any(call.startswith("Given claims") for call in router.calls)
    assert any(call.startswith("Using these sources") for call in router.calls)
    assert list_memories(category="general", limit=50)


@pytest.mark.asyncio
async def test_merge_code_and_registry(monkeypatch, mosaic_runtime):
    _config, _router = mosaic_runtime
    monkeypatch.setattr(logos_tools, "run_code", lambda code, language, context_dir=None: RunResult(stdout="ok", stderr="", exit_code=0, execution_time_ms=5, language=language))

    sources = [
        mosaic.SourceInput(id="s1", type="text", content="def one():\n    return 1\n", label="One"),
        mosaic.SourceInput(id="s2", type="text", content="def one():\n    return 1\n\ndef two():\n    return 2\n", label="Two"),
    ]

    result = await mosaic.merge_code(sources, "Merge helpers")
    assert "def two()" in result.output
    assert result.confidence == 1.0
    assert result.metadata["verification"]["exit_code"] == 0

    registry = get_tool_registry()
    assert registry.get("synthesize").name == "synthesize"
    assert registry.get("merge_code").name == "merge_code"
    assert registry.get("diff_sources").name == "diff_sources"
    assert registry.get("cite_sources").name == "cite_sources"


def test_diff_and_citations(mosaic_runtime):
    _config, _router = mosaic_runtime
    a = mosaic.SourceInput(id="a", type="text", content="alpha\nshared\nnot beta", label="A")
    b = mosaic.SourceInput(id="b", type="text", content="beta\nshared", label="B")

    diff = mosaic.diff_sources(a, b)
    assert "alpha" in diff["only_in_a"]
    assert "beta" in diff["only_in_b"]
    assert "shared" in diff["in_both"]
    assert "not beta" in diff["contradictions"]

    payload = json.dumps(
        {
            "kind": "mosaic",
            "id": "mosaic-1",
            "task": "demo",
            "sources_used": [],
            "overlaps": [],
            "contradictions": [],
            "output": "artifact",
            "output_format": "markdown",
            "confidence": 0.9,
            "source_attribution": {"a": {"label": "Alpha", "type": "text", "weight": 1.0}},
            "word_count": 1,
            "generated_at": "2024-01-01T00:00:00+00:00",
            "metadata": {},
        },
        ensure_ascii=True,
    )
    mneme_tools.save_memory("mosaic:mosaic-1", payload, "general", tags=["mosaic"], source="mosaic", confidence=0.9)
    citations = mosaic.cite_sources("mosaic-1")
    assert "Alpha" in citations
