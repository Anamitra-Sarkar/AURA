from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import aura.ui.server as ui
from aura.agents.mosaic.models import MosaicResult, OverlapCluster
from aura.agents.aegis.models import SystemSnapshot
from aura.agents.director.models import WorkflowPlan, WorkflowStep
from aura.agents.lyra.models import OperationResult
from aura.agents.oracle_deep.models import CounterArgument, ReasoningChain, ReasoningReport, ReasoningStep, ScenarioAnalysis, ScenarioOutcome
from aura.core.config import AppConfig, EnsembleSettings, FeatureFlags, LyraSettings, ModelSettings, PathsSettings, UISettings
from aura.core.event_bus import EventBus
from aura.memory.mneme.models import MemoryRecord, RecallResult


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
    )


@pytest.fixture()
def nexus_runtime(tmp_path, monkeypatch):
    config = _config(tmp_path)
    event_bus = EventBus()
    calls = {"messages": [], "approval": [], "voice": []}

    class FakeAgentLoop:
        async def handle_message(self, text: str, importance: int | None = None):
            calls["messages"].append((text, importance))
            return {"response": "ok", "used_ensemble": importance == 3, "tools_called": ["analyze_decision"], "reasoning_used": True}

    runtime = ui.NexusRuntime(config=config, event_bus=event_bus, agent_loop=FakeAgentLoop())
    ui.configure_runtime(config, event_bus, runtime.agent_loop)

    step = WorkflowStep(id="step-1", name="Collect", description="Collect info", tool_name="save_memory", tool_args={}, depends_on=[], status="done", tier=1)
    plan = WorkflowPlan(
        id="wf-1",
        name="Test workflow",
        description="demo",
        original_instruction="demo",
        steps=[step],
        status="running",
        created_at=datetime.now(timezone.utc),
        started_at=datetime.now(timezone.utc),
        context={},
    )
    memory = MemoryRecord(
        id="mem-1",
        key="hello",
        value="world",
        category="general",
        tags=[],
        embedding=[0.0],
        source="manual",
        confidence=1.0,
        created_at="2024-01-01T00:00:00+00:00",
        updated_at="2024-01-01T00:00:00+00:00",
        access_count=0,
        last_accessed="2024-01-01T00:00:00+00:00",
    )

    monkeypatch.setattr(ui.director_tools, "list_workflows", lambda status_filter=None, limit=100: [plan])
    monkeypatch.setattr(ui.director_tools, "pause_workflow", lambda workflow_id: {"ok": True, "workflow_id": workflow_id})
    monkeypatch.setattr(ui.director_tools, "resume_workflow", lambda workflow_id: {"ok": True, "workflow_id": workflow_id, "resumed": True})
    monkeypatch.setattr(ui.director_tools, "approve_step", lambda workflow_id, step_id, approved, user_notes="": {"ok": approved, "workflow_id": workflow_id, "step_id": step_id, "user_notes": user_notes})
    monkeypatch.setattr(ui.director_tools, "cancel_workflow", lambda workflow_id: {"ok": True, "workflow_id": workflow_id, "cancelled": True})
    monkeypatch.setattr(ui.phantom_tools, "list_workflows", lambda: [SimpleNamespace(id="task-1", name="Daily briefing", next_run=datetime.now(timezone.utc), last_run=None, enabled=True)])
    monkeypatch.setattr(ui, "list_memories", lambda category=None, limit=10: [memory])
    monkeypatch.setattr(ui, "recall_memory", lambda query, top_k=20, category_filter=None: [RecallResult(record=memory, similarity_score=0.91, rank=1)])
    monkeypatch.setattr(ui.aegis_tools, "get_system_info", lambda: SystemSnapshot(timestamp=datetime.now(timezone.utc), cpu_percent=12.5, cpu_count=8, ram_total_gb=16.0, ram_used_gb=4.0, ram_percent=25.0, disk_total_gb=256.0, disk_used_gb=50.0, disk_percent=19.5, gpu_info=[], uptime_seconds=42, platform="linux", python_version="3.12"))
    async def fake_analyze(question, context=None, use_iris=True):
        return ReasoningReport(id="rep-1", question=question, chain=ReasoningChain(steps=[ReasoningStep(id="s1", description="step", evidence=["e1"], assumption=False, confidence=0.8, confidence_reason="ok")], conclusion="therefore", overall_confidence=0.8, weakest_link_id="s1"), conclusion="therefore", confidence=0.8, counter_argument=CounterArgument(argument="counter", strength=0.4, evidence=["e2"], rebuttal="rebuttal"), uncertainty_flags=["maybe"], evidence_sources=["https://example.com"], generated_at=datetime.now(timezone.utc))

    async def fake_what_if(change, base_state=None):
        return ScenarioAnalysis(id="sc-1", change_description=change, base_state=base_state or "", outcomes=[ScenarioOutcome(description="best", probability=0.9, confidence=0.8, supporting_evidence=["e1"], time_horizon="immediate"), ScenarioOutcome(description="worst", probability=0.2, confidence=0.4, supporting_evidence=["e2"], time_horizon="1 year"), ScenarioOutcome(description="maybe", probability=0.5, confidence=0.6, supporting_evidence=["e3"], time_horizon="1 week"), ScenarioOutcome(description="later", probability=0.6, confidence=0.7, supporting_evidence=["e4"], time_horizon="1 month")], best_case=ScenarioOutcome(description="best", probability=0.9, confidence=0.8, supporting_evidence=["e1"], time_horizon="immediate"), worst_case=ScenarioOutcome(description="worst", probability=0.2, confidence=0.4, supporting_evidence=["e2"], time_horizon="1 year"), most_likely=ScenarioOutcome(description="later", probability=0.6, confidence=0.7, supporting_evidence=["e4"], time_horizon="1 month"), recommendation="go ahead", confidence=0.7)

    monkeypatch.setattr(ui.oracle_tools, "analyze_decision", fake_analyze)
    monkeypatch.setattr(ui.oracle_tools, "what_if_scenario", fake_what_if)
    monkeypatch.setattr(ui.lyra_tools, "speak", lambda text, interrupt_if_speaking=True: OperationResult(True, "spoken", {"text": text}))
    monkeypatch.setattr(ui.lyra_tools, "is_wake_word_listener_running", lambda: False)
    async def fake_mosaic_synthesize(task, sources, output_format="markdown", max_length=None):
        return MosaicResult(
            id="m-1",
            task=task,
            sources_used=sources,
            overlaps=[OverlapCluster(topic="topic", sources_agreeing=["s1"], sources_disagreeing=[], resolution="shared")],
            contradictions=[],
            output="artifact",
            output_format=output_format,
            confidence=0.8,
            source_attribution={source.id: {"label": source.label, "type": source.type, "weight": source.weight} for source in sources},
            word_count=1,
            generated_at=datetime.now(timezone.utc),
        )

    monkeypatch.setattr(ui.mosaic_tools, "synthesize", fake_mosaic_synthesize)
    monkeypatch.setattr(ui.mosaic_tools, "merge_code", fake_mosaic_synthesize)
    monkeypatch.setattr(ui.mosaic_tools, "diff_sources", lambda source_a, source_b: {"only_in_a": ["a"], "only_in_b": ["b"], "in_both": ["shared"], "contradictions": []})
    monkeypatch.setattr(ui.mosaic_tools, "cite_sources", lambda mosaic_id: "Sources:\n- Alpha [text] weight=1.0")

    return runtime, calls


def test_health_state_and_actions(nexus_runtime, tmp_path):
    runtime, calls = nexus_runtime
    with TestClient(ui.app) as client:
        health = client.get("/health")
        assert health.status_code == 200
        assert health.json()["status"] == "ok"

        state = client.get("/api/state")
        payload = state.json()
        assert {"active_workflows", "phantom_tasks", "recent_memories", "lyra_status", "system_health"} <= set(payload)

        message = client.post("/api/message", json={"text": "Please decide", "importance": 3})
        assert message.status_code == 200
        assert message.json()["used_ensemble"] is True
        assert calls["messages"][-1] == ("Please decide", 3)

        workflows = client.get("/api/workflows")
        assert workflows.status_code == 200
        assert workflows.json()[0]["id"] == "wf-1"

        assert client.post("/api/workflows/wf-1/pause").json()["workflow_id"] == "wf-1"
        assert client.post("/api/workflows/wf-1/resume").json()["resumed"] is True
        assert client.post("/api/workflows/wf-1/approve/step-1").json()["step_id"] == "step-1"
        assert client.delete("/api/workflows/wf-1").json()["cancelled"] is True

        memories = client.get("/api/memories", params={"query": "hello"})
        assert memories.json()[0]["key"] == "hello"

        report = client.post("/api/oracle/analyze", json={"question": "Should I?", "use_iris": True, "context": "ctx"})
        assert report.json()["id"] == "rep-1"

        scenario = client.post("/api/oracle/whatif", json={"change": "Switch optimizers", "base_state": "baseline"})
        assert scenario.json()["id"] == "sc-1"

        spoken = client.post("/api/lyra/speak", json={"text": "Hello **world**"})
        assert spoken.json()["details"]["text"] == "Hello **world**"

        voice = client.post("/api/lyra/voice-mode", json={"enabled": True})
        assert voice.json()["enabled"] is True
        assert runtime.config.lyra.voice_mode is True

        mosaic_resp = client.post("/api/mosaic/synthesize", json={"task": "demo", "sources": [{"id": "s1", "type": "text", "content": "x", "label": "Alpha"}], "output_format": "markdown"})
        assert mosaic_resp.json()["id"] == "m-1"
        assert client.get("/api/mosaic/m-1").json()["citations"].startswith("Sources:")


def test_websocket_receives_snapshot_and_events(nexus_runtime):
    runtime, _calls = nexus_runtime
    with TestClient(ui.app) as client:
        with client.websocket_connect("/ws/events") as websocket:
            snapshot = websocket.receive_json()
            assert snapshot["type"] == "state_snapshot"
            assert snapshot["data"]["lyra_status"]["enabled"] is True

            runtime.event_bus.publish_sync("mneme.memory_saved", {"key": "x"})
            forwarded = websocket.receive_json()
            assert forwarded["type"] == "mneme.memory_saved"
            assert forwarded["data"]["key"] == "x"

            runtime.event_bus.publish_sync("aegis.tier3_request", {"workflow_id": "wf-1", "step_id": "step-1"})
            approval = websocket.receive_json()
            assert approval["type"] == "aegis.tier3_request"
