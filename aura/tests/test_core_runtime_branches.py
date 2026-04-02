from __future__ import annotations

import asyncio

import pytest

from aura.core.hotkey import GlobalHotkeyManager
from aura.core.ipc import UnixSocketServer
from aura.core.llm_router import OllamaRouter
from aura.core.tools import ToolRegistry, ToolSpec, build_tool_schema
from aura.core.tray import TrayController


def test_tool_registry_branches():
    registry = ToolRegistry()
    schema = build_tool_schema("echo", "Echo input", {"type": "object"}, {"type": "object"}, 1)
    assert schema["name"] == "echo"

    registry.register(ToolSpec("echo", "Echo input", 1, {"type": "object"}, {"type": "object"}, lambda args: args["value"]))
    assert registry.list_tools()[0].name == "echo"

    with pytest.raises(ValueError):
        registry.register(ToolSpec("echo", "Dup", 1, {}, {}, lambda args: args))

    assert asyncio.run(registry.execute("missing")).error == "unknown-tool:missing"
    assert asyncio.run(registry.execute("echo", {"value": "hi"})).result == "hi"

    registry.register(ToolSpec("danger", "Dangerous", 3, {"type": "object"}, {"type": "object"}, lambda args: "done"))
    blocked = asyncio.run(registry.execute("danger"))
    assert blocked.error == "tier-3-confirmation-required"
    allowed = asyncio.run(registry.execute("danger", confirm=True))
    assert allowed.result == "done"

    async def async_handler(_args):
        return "async"

    registry.register(ToolSpec("async", "Async", 1, {"type": "object"}, {"type": "object"}, async_handler))
    assert asyncio.run(registry.execute("async")).result == "async"
    registry.clear()
    assert registry.list_tools() == []


def test_llm_router_branches(monkeypatch):
    monkeypatch.setattr("aura.core.llm_router.ollama", None)
    router = OllamaRouter(model="llama3", client=None)
    assert asyncio.run(router.chat([{"role": "user", "content": "hi"}])).error == "ollama-client-unavailable"

    class Client:
        def __init__(self, payload):
            self.payload = payload

        def chat(self, **kwargs):
            return self.payload

    router = OllamaRouter(model="llama3", client=Client({"message": {"content": "hello"}}))
    assert asyncio.run(router.chat([{"role": "user", "content": "hi"}])).content == "hello"

    router = OllamaRouter(model="llama3", client=Client({"response": "hello"}))
    assert asyncio.run(router.generate("hi")).content == "hello"

    class AwaitableClient:
        def chat(self, **kwargs):
            async def _result():
                return {"message": {"content": "awaited"}}

            return _result()

    router = OllamaRouter(model="llama3", client=AwaitableClient())
    assert asyncio.run(router.generate("hi")).content == "awaited"

    class ErrorClient:
        def chat(self, **kwargs):
            raise RuntimeError("boom")

    router = OllamaRouter(model="llama3", client=ErrorClient())
    assert asyncio.run(router.chat([{"role": "user", "content": "hi"}])).error == "boom"


def test_hotkey_and_tray_branches():
    hotkey = GlobalHotkeyManager(callback=lambda: None, listener_factory=lambda mapping: type("L", (), {"start": lambda self: None, "stop": lambda self: None})())
    assert hotkey.start().ok is True
    assert hotkey.stop().ok is True

    hotkey_fail = GlobalHotkeyManager(listener_factory=lambda mapping: (_ for _ in ()).throw(RuntimeError("no hotkey")))
    assert hotkey_fail.start().ok is False

    tray = TrayController(icon_factory=lambda: type("I", (), {"run_detached": lambda self: None, "stop": lambda self: None})())
    assert tray.start().ok is True
    assert tray.stop().ok is True

    tray_fail = TrayController(icon_factory=lambda: (_ for _ in ()).throw(RuntimeError("no tray")))
    assert tray_fail.start().ok is False


@pytest.mark.asyncio
async def test_ipc_branches(monkeypatch, tmp_path):
    server = UnixSocketServer(tmp_path / "aura.sock", handler=lambda message: message.upper())
    monkeypatch.setattr("aura.core.ipc.supports_unix_sockets", lambda: False)
    assert (await server.start()).ok is False
    monkeypatch.setattr("aura.core.ipc.supports_unix_sockets", lambda: True)

    async def fake_start_unix_server(handler, path):
        class FakeServer:
            def close(self):
                pass

            async def wait_closed(self):
                return None

        return FakeServer()

    monkeypatch.setattr("aura.core.ipc.asyncio.start_unix_server", fake_start_unix_server)
    assert (await server.start()).ok is True

    class Reader:
        async def readline(self):
            return b"hello\n"

    class Writer:
        def __init__(self):
            self.buffer = b""

        def write(self, data):
            self.buffer += data

        async def drain(self):
            return None

        def close(self):
            return None

        async def wait_closed(self):
            return None

    writer = Writer()
    await server._handle_client(Reader(), writer)
    assert writer.buffer == b"HELLO\n"
    assert (await server.stop()).ok is True
