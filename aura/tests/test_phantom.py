from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

import aura.agents.aegis.tools as aegis_tools
import aura.agents.iris.tools as iris_tools
import aura.agents.phantom.tools as phantom
import aura.agents.director.tools as director_tools
from aura.agents.aegis.models import GPUInfo, SystemSnapshot
from aura.agents.phantom.models import PhantomTask
from aura.core.config import AppConfig, FeatureFlags, ModelSettings, PathsSettings
from aura.core.event_bus import EventBus


@pytest.fixture()
def phantom_config(tmp_path):
    config = AppConfig(
        name="AURA",
        offline_mode=True,
        log_level="INFO",
        primary_model=ModelSettings(provider="ollama", name="llama3", host="http://127.0.0.1:11434"),
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
    )
    phantom.set_config(config)
    phantom.set_event_bus(EventBus())
    phantom._DEFAULT_TASKS_LOADED = True
    phantom._PAUSED = False
    phantom._PAUSE_UNTIL = None
    return config


def test_generate_daily_briefing_produces_valid_object(monkeypatch, phantom_config):
    monkeypatch.setattr(phantom.echo_tools, "list_meetings", lambda _filters: [{"title": "Standup"}])
    monkeypatch.setattr(
        phantom,
        "list_memories",
        lambda category=None, limit=20: [
            SimpleNamespace(value="Finish homework"),
            SimpleNamespace(value="Study ML"),
        ]
        if category == "tasks"
        else [SimpleNamespace(value="ai")]
        if category == "preferences"
        else [],
    )
    monkeypatch.setattr(
        phantom,
        "save_memory",
        lambda *args, **kwargs: SimpleNamespace(id="memory-1"),
    )
    monkeypatch.setattr(phantom, "send_notification", lambda *args, **kwargs: None)
    monkeypatch.setattr(iris_tools, "search_academic", lambda query, source="arxiv", max_results=3: [f"{query}-{source}"])
    monkeypatch.setattr(aegis_tools, "get_system_info", lambda: SystemSnapshot(
        timestamp=datetime.now(timezone.utc),
        cpu_percent=12.0,
        cpu_count=8,
        ram_total_gb=16.0,
        ram_used_gb=8.0,
        ram_percent=50.0,
        disk_total_gb=100.0,
        disk_used_gb=25.0,
        disk_percent=25.0,
        gpu_info=[GPUInfo(name="GPU", memory_total_mb=1024.0, memory_used_mb=128.0, utilization_percent=12.0)],
        uptime_seconds=100,
        platform="linux",
        python_version="3.12",
    ))

    briefing = phantom.generate_daily_briefing()
    assert briefing.summary_text
    assert briefing.pending_tasks == ["Finish homework", "Study ML"]
    assert briefing.meetings_today == [{"title": "Standup"}]
    assert briefing.system_health.cpu_count == 8


@pytest.mark.asyncio
async def test_register_watch_change_triggers_action(monkeypatch, phantom_config):
    payloads: list[dict[str, object]] = []
    event = asyncio.Event()

    async def handler(topic: str, payload):
        payloads.append(payload)
        if topic == "custom.change":
            event.set()

    await phantom._EVENT_BUS.subscribe("custom.change", handler)

    class Page:
        def __init__(self, text: str) -> None:
            self.main_text = text

    texts = {"value": "baseline"}
    monkeypatch.setattr(iris_tools, "fetch_url", lambda target, extract_main_content=True: Page(texts["value"]))

    watch = phantom.register_watch("ArXiv", "url", "https://example.com", 30, "custom.change")
    assert watch.last_hash

    texts["value"] = "updated content"
    triggered = await phantom.check_all_watches()
    await asyncio.wait_for(event.wait(), timeout=2)
    assert triggered == ["ArXiv"]
    assert payloads[-1]["watch_id"] == watch.id


@pytest.mark.asyncio
async def test_pause_all_and_recovery_task(monkeypatch, phantom_config):
    phantom._save_task(
        PhantomTask(
            id="task-1",
            name="Workflow Recovery",
            description="resume interrupted workflows",
            schedule="hourly",
            last_run=None,
            next_run=datetime.now(timezone.utc) - timedelta(minutes=1),
            enabled=True,
            handler_function="workflow_recovery",
            config={},
        )
    )

    monkeypatch.setattr(director_tools, "resume_interrupted_workflows", lambda: ["workflow-123"])

    phantom.pause_all()
    assert phantom.run_scheduled_tasks() == []
    phantom.resume_all()
    assert phantom.run_scheduled_tasks() == ["Workflow Recovery"]


@pytest.mark.asyncio
async def test_phantom_loop_runs_due_tasks_and_skips_future(monkeypatch, phantom_config):
    executed: list[str] = []
    phantom._save_task(
        PhantomTask(
            id="due-task",
            name="Due Task",
            description="due",
            schedule="hourly",
            last_run=None,
            next_run=datetime.now(timezone.utc) - timedelta(minutes=1),
            enabled=True,
            handler_function="system_health_check",
            config={},
        )
    )
    phantom._save_task(
        PhantomTask(
            id="future-task",
            name="Future Task",
            description="not yet due",
            schedule="hourly",
            last_run=None,
            next_run=datetime.now(timezone.utc) + timedelta(hours=1),
            enabled=True,
            handler_function="system_health_check",
            config={},
        )
    )

    monkeypatch.setattr(phantom, "_system_health_check", lambda: executed.append("due") or "ok")

    async def stop_after_first(_seconds: float) -> None:
        raise asyncio.CancelledError

    monkeypatch.setattr(phantom.asyncio, "sleep", stop_after_first)

    with pytest.raises(asyncio.CancelledError):
        await phantom.phantom_loop()

    assert executed == ["due"]
