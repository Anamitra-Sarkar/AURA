from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import aura.ui.server as ui
from aura.core.config import AppConfig, EnsembleSettings, FeatureFlags, LyraSettings, ModelSettings, PathsSettings, UISettings
from aura.core.event_bus import EventBus
from aura.core.multiagent.dispatcher import A2ADispatcher
from aura.core.multiagent.models import A2ATask
from aura.core.multiagent.orchestrator import NexusOrchestrator
from aura.core.multiagent.registry import AgentRegistry
from aura.core.router.quota_tracker import QuotaTracker
from aura.core.router.smart_router import SmartRouter


def _config(tmp_path: Path) -> AppConfig:
    return AppConfig(
        name="AURA",
        offline_mode=True,
        log_level="INFO",
        primary_model=ModelSettings(provider="ollama", name="llama3:8b", host="http://127.0.0.1:11434"),
        fallback_models=[],
        paths=PathsSettings(allowed_roots=[tmp_path], data_dir=tmp_path, log_dir=tmp_path / "logs", memory_dir=tmp_path / "memory", ipc_socket=tmp_path / "aura.sock"),
        features=FeatureFlags(hotkey=False, tray=False, ipc=False, api=True),
        source_path=tmp_path / "config.yaml",
        ensemble=EnsembleSettings(enabled=True, default_importance_threshold=2, models=["llama3:8b"], judge_model="llama3:8b", model_timeout_seconds=10, min_successful_responses=2, fallback_to_single=True),
        lyra=LyraSettings(enabled=False, voice_mode=False, stt_model="base", wake_word_engine="energy_threshold", wake_phrase="hey aura", wake_sensitivity=0.5, tts_rate=175, tts_volume=0.9, save_audio=False, noise_reduction=True),
        ui=UISettings(enabled=True, host="127.0.0.1", port=7860, open_browser_on_start=False),
    )


def test_registry_and_capabilities():
    registry = AgentRegistry()
    assert registry.get("iris").name == "IRIS"
    assert any(card.id == "iris" for card in registry.find_by_capability("web_search"))


@pytest.mark.asyncio
async def test_dispatch_and_orchestrator(monkeypatch, tmp_path: Path):
    registry = AgentRegistry()
    dispatcher = A2ADispatcher(registry)
    task = A2ATask(task_id="task-1", from_agent="director", to_agent="iris", instruction="research quantum computing", context={}, priority=2)
    result = await dispatcher.dispatch(task)
    assert result.agent_id == "iris"

    tracker = QuotaTracker(tmp_path / "quota.db")
    router = SmartRouter(tracker)

    async def fake_complete(task, messages, importance=2, force_provider=None, force_model=None, max_tokens=4096, temperature=0.7, tools=None):
        return type("R", (), {"response": "router-ok", "tokens_used": 1, "ensemble_used": False, "tools_called": [], "reasoning_used": False})()

    router.complete = fake_complete  # type: ignore[assignment]
    orch = NexusOrchestrator(router, dispatcher, registry)

    seen = []

    async def fake_inject(text):
        seen.append(("inject", text))
        return text

    async def fake_extract(question, response):
        seen.append(("extract", question, response))
        return []

    monkeypatch.setattr("aura.memory.inject_context", lambda text: seen.append(("inject", text)) or "ctx")
    monkeypatch.setattr("aura.memory.auto_extract_memories", fake_extract)
    outcome = await orch.handle("research quantum computing", "user-1", {}, 2)
    assert outcome.agents_used == ["iris"]
    assert seen[0][0] == "inject"
    assert seen[-1][0] == "extract"


def test_ui_routes_expose_multiagent_endpoints(tmp_path: Path):
    config = _config(tmp_path)
    runtime = ui.NexusRuntime(
        config=config,
        event_bus=EventBus(),
        agent_loop=type("Loop", (), {"handle_message": staticmethod(lambda text, importance=None: {"response": "ok", "used_ensemble": False, "tools_called": [], "reasoning_used": False})})(),
        orchestrator=None,
        auth_manager=None,
    )
    ui.configure_runtime(config, runtime.event_bus, runtime.agent_loop, orchestrator=None, auth_manager=None)
    with TestClient(ui.app) as client:
        assert len(client.get("/a2a/agents").json()) == 14
        assert client.get("/a2a/agents/iris").json()["id"] == "iris"
        assert client.get("/mcp/tools").status_code == 200
