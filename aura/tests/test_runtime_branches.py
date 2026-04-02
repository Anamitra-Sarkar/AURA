from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path

import pytest

import aura.daemon as daemon
from aura.core.event_bus import EventBus
from aura.core.hotkey import GlobalHotkeyManager
from aura.core.ipc import UnixSocketServer
from aura.core.llm_router import LLMResult, OllamaRouter
from aura.core.platform import PlatformInfo, default_data_dir, open_application, open_file, send_notification, supports_unix_sockets
from aura.core.tools import ToolRegistry
from aura.core.tray import TrayController


def test_platform_branches(monkeypatch, tmp_path):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr("aura.core.platform.webbrowser.open", lambda *_args, **_kwargs: True)
    monkeypatch.setattr("aura.core.platform.subprocess.Popen", lambda *_args, **_kwargs: object())
    monkeypatch.setattr("aura.core.platform.subprocess.run", lambda *_args, **_kwargs: __import__("subprocess").CompletedProcess(args=_args[0], returncode=0))
    monkeypatch.setattr("aura.core.platform.shutil.which", lambda _name: "/usr/bin/notify-send")
    monkeypatch.setattr("aura.core.platform.os.startfile", lambda *_args, **_kwargs: None, raising=False)

    monkeypatch.setattr("aura.core.platform.detect_os", lambda: PlatformInfo(system="Linux", release="1", machine="x86_64"))
    assert default_data_dir("AURA").as_posix().endswith(".local/share/AURA")
    assert open_file("https://example.com").ok is True
    assert open_application("app").ok is True
    assert send_notification("A", "B").ok is True
    assert supports_unix_sockets() is True

    monkeypatch.setattr("aura.core.platform.detect_os", lambda: PlatformInfo(system="Darwin", release="1", machine="arm64"))
    assert default_data_dir("AURA").as_posix().endswith("Library/Application Support/AURA")
    assert open_file("/tmp/example").ok is True
    assert open_application("App").ok is True
    assert send_notification("A", "B").ok is True

    monkeypatch.setattr("aura.core.platform.detect_os", lambda: PlatformInfo(system="Windows", release="1", machine="AMD64"))
    assert default_data_dir("AURA").as_posix().endswith("AppData/Local/AURA")
    assert open_file("/tmp/example").ok is True
    assert open_application("App").ok is True
    assert send_notification("A", "B").ok is False


@pytest.mark.asyncio
async def test_event_bus_branches():
    bus = EventBus()
    seen: list[tuple[str, object]] = []

    async def async_handler(topic, payload):
        seen.append((topic, payload))

    async def failing_handler(_topic, _payload):
        raise RuntimeError("boom")

    token = await bus.subscribe("topic", async_handler)
    await bus.subscribe("topic", failing_handler)
    result = await bus.publish("topic", {"value": 1})
    assert result.ok is False
    assert result.delivered == 1
    assert seen == [("topic", {"value": 1})]
    assert await bus.unsubscribe("topic", token) is True
    assert await bus.unsubscribe("topic", token) is False
    sync_result = bus.publish_sync("topic", {"value": 2})
    assert sync_result.ok is False


@pytest.mark.asyncio
async def test_hotkey_tray_ipc_and_router_branches(tmp_path):
    hotkey = GlobalHotkeyManager(callback=lambda: None, listener_factory=lambda mapping: type("L", (), {"start": lambda self: None, "stop": lambda self: None})())
    assert hotkey.start().ok is True
    assert hotkey.stop().ok is True

    tray = TrayController(icon_factory=lambda: type("I", (), {"run_detached": lambda self: None, "stop": lambda self: None})())
    assert tray.start().ok is True
    assert tray.stop().ok is True

    server = UnixSocketServer(tmp_path / "aura.sock", handler=lambda msg: msg.upper())
    assert (await server.start()).ok is True
    assert (await server.stop()).ok is True

    client = type(
        "Client",
        (),
        {
            "chat": lambda self, **kwargs: {"message": {"content": f"echo:{kwargs['model']}"}},
        },
    )()
    router = OllamaRouter(model="llama3", client=client)
    result = await router.generate("hello")
    assert result.ok is True
    assert result.content == "echo:llama3"


@dataclass
class _DummyState:
    config: object
    event_bus: EventBus
    tools: ToolRegistry
    router: object
    agent_loop: object
    ipc_server: object | None = None
    hotkey: object | None = None
    tray: object | None = None


@pytest.mark.asyncio
async def test_daemon_bootstrap_and_forever(monkeypatch, tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        '{"app":{"name":"AURA","offline_mode":true,"log_level":"INFO"},"models":{"primary":{"provider":"ollama","name":"llama3","host":"http://127.0.0.1:11434"},"fallbacks":[]},"paths":{"data_dir":"./data","log_dir":"./logs","memory_dir":"./memory","ipc_socket":"./run/aura.sock"},"features":{"hotkey":false,"tray":false,"ipc":false,"api":false}}',
        encoding="utf-8",
    )

    class FakeRouter:
        def __init__(self, *args, **kwargs):
            self.model = kwargs.get("model") or args[0]

        async def chat(self, messages, options=None):
            return LLMResult(ok=True, model=self.model, content='{"type":"final","response":"ok"}')

        async def generate(self, prompt, system=None):
            return LLMResult(ok=True, model=self.model, content='{"type":"final","response":"ok"}')

    class FakeLoop:
        def __init__(self, *args, **kwargs):
            self.router = kwargs["router"]

        async def run(self, prompt):
            return type("R", (), {"ok": True, "answer": "ok", "error": None, "steps": []})()

    monkeypatch.setattr(daemon, "OllamaRouter", FakeRouter)
    monkeypatch.setattr(daemon, "ReActAgentLoop", FakeLoop)
    monkeypatch.setattr(daemon, "register_atlas_tools", lambda: None)
    monkeypatch.setattr(daemon, "register_logos_tools", lambda: None)
    monkeypatch.setattr(daemon, "register_echo_tools", lambda: None)
    monkeypatch.setattr(daemon, "register_aegis_tools", lambda: None)
    monkeypatch.setattr(daemon, "register_director_tools", lambda: None)
    monkeypatch.setattr(daemon, "register_phantom_tools", lambda: None)
    monkeypatch.setattr(daemon, "resume_interrupted_workflows", lambda: [])
    monkeypatch.setattr(daemon, "phantom_loop", lambda: asyncio.sleep(0))
    monkeypatch.setattr(daemon, "GlobalHotkeyManager", lambda: type("H", (), {"start": lambda self: None, "stop": lambda self: None})())
    monkeypatch.setattr(daemon, "TrayController", lambda: type("T", (), {"start": lambda self: None, "stop": lambda self: None})())
    monkeypatch.setattr(daemon, "UnixSocketServer", lambda _path: type("S", (), {"start": lambda self: asyncio.sleep(0), "stop": lambda self: asyncio.sleep(0)})())
    state = await daemon.bootstrap(config_path)
    assert state.config.name == "AURA"
