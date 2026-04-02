from __future__ import annotations

import asyncio

import pytest

import aura.daemon as daemon_module
from aura.daemon import bootstrap, run_once


@pytest.mark.asyncio
async def test_bootstrap_and_run_once(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        '{"app":{"name":"AURA","offline_mode":true,"log_level":"INFO"},"models":{"primary":{"provider":"ollama","name":"llama3","host":"http://127.0.0.1:11434"},"fallbacks":[]},"paths":{"data_dir":"./data","log_dir":"./logs","memory_dir":"./memory","ipc_socket":"./run/aura.sock"},"features":{"hotkey":false,"tray":false,"ipc":false,"api":false}}',
        encoding="utf-8",
    )
    state = await bootstrap(config_path)
    assert state.config.name == "AURA"
    result = await run_once(config_path)
    assert result["result"]["ok"] in {True, False}


@pytest.mark.asyncio
async def test_run_forever_cleans_up(monkeypatch):
    class FakeComponent:
        def __init__(self):
            self.started = False
            self.stopped = False

        def start(self):
            self.started = True

        def stop(self):
            self.stopped = True

    class FakeIPC:
        async def start(self):
            return None

        async def stop(self):
            return None

    state = type(
        "State",
        (),
        {
            "ipc_server": FakeIPC(),
            "hotkey": FakeComponent(),
            "tray": FakeComponent(),
        },
    )()

    async def fake_bootstrap(_path=None):
        return state

    monkeypatch.setattr(daemon_module, "bootstrap", fake_bootstrap)
    monkeypatch.setattr("aura.daemon.phantom_loop", lambda: asyncio.sleep(0))

    async def stop_sleep(_seconds):
        raise asyncio.CancelledError

    monkeypatch.setattr("aura.daemon.asyncio.sleep", stop_sleep)
    await asyncio.wait_for(daemon_module.run_forever(None), timeout=2)
    assert state.hotkey.stopped is True
    assert state.tray.stopped is True
