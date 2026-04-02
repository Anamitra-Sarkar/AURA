from __future__ import annotations

from aura.core.config import load_config


def test_load_config(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        '{"app":{"name":"AURA","offline_mode":true,"log_level":"DEBUG"},"models":{"primary":{"provider":"ollama","name":"llama3","host":"http://127.0.0.1:11434"},"fallbacks":[]},"paths":{"data_dir":"./data","log_dir":"./logs","memory_dir":"./memory","ipc_socket":"./run/aura.sock"},"features":{"hotkey":false,"tray":true,"ipc":true,"api":false}}',
        encoding="utf-8",
    )
    config = load_config(config_path)
    assert config.name == "AURA"
    assert config.offline_mode is True
    assert config.primary_model.name == "llama3"
    assert config.paths.data_dir.name == "data"
    assert config.features.tray is True
