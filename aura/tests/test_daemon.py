from __future__ import annotations

import pytest

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
