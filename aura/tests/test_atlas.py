from __future__ import annotations

import asyncio
import zipfile

import pytest

from aura.agents.atlas import tools as atlas
from aura.core.config import AppConfig, FeatureFlags, ModelSettings, PathsSettings
from aura.core.event_bus import EventBus
from aura.core.tools import get_tool_registry


@pytest.fixture()
def atlas_config(tmp_path):
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
    atlas.set_config(config)
    return config


@pytest.fixture()
def atlas_bus():
    bus = EventBus()
    atlas.set_event_bus(bus)
    return bus


def test_tool_registration_exists():
    registry = get_tool_registry()
    assert registry.get("read_file").name == "read_file"
    assert registry.get("delete_file").tier == 3


def test_write_read_search_and_list(atlas_config, tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    path = root / "note.txt"
    result = atlas.write_file(str(path), "hello world")
    assert result.success is True
    content = atlas.read_file(str(path))
    assert content.content == "hello world"
    matches = atlas.search_files("hello", str(root), "both")
    assert matches and matches[0].path == str(path)
    entries = atlas.list_directory(str(root))
    assert entries and entries[0].name == "note.txt"


def test_write_copy_move_rename_delete_and_archive(atlas_config, tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    source = root / "source.txt"
    atlas.write_file(str(source), "alpha")
    copied = root / "copy.txt"
    moved = root / "moved.txt"
    renamed = root / "renamed.txt"
    archive = root / "archive.zip"
    extracted = root / "extracted"

    assert atlas.copy_file(str(source), str(copied)).success is True
    assert atlas.move_file(str(copied), str(moved)).success is True
    assert atlas.rename_file(str(moved), "renamed.txt").success is True
    assert atlas.compress_folder(str(root), str(archive)).success is True
    assert zipfile.is_zipfile(archive)
    assert atlas.extract_archive(str(archive), str(extracted)).success is True
    delete_result = atlas.delete_file(str(source))
    assert delete_result.success is True
    assert (root / ".aura_trash").exists()
    assert not source.exists()
    assert renamed.exists()


def test_path_traversal_rejected(atlas_config, tmp_path):
    outside = tmp_path.parent / "outside.txt"
    outside.write_text("nope", encoding="utf-8")
    with pytest.raises(atlas.AtlasError):
        atlas.read_file(str(outside))


@pytest.mark.asyncio
async def test_watch_folder_publishes_events(atlas_config, atlas_bus, tmp_path):
    root = tmp_path / "watch"
    root.mkdir()
    seen = asyncio.Event()

    async def handler(topic, payload):
        if topic == "folder.changed" and payload["event"] == "create":
            seen.set()

    await atlas_bus.subscribe("folder.changed", handler)
    handle = atlas.watch_folder(str(root), "folder.changed")
    assert handle.active is True
    (root / "new.txt").write_text("hi", encoding="utf-8")
    await asyncio.wait_for(seen.wait(), timeout=5)


@pytest.mark.asyncio
async def test_tier_three_delete_requires_confirmation(atlas_config, tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    path = root / "secret.txt"
    atlas.write_file(str(path), "secret")
    registry = get_tool_registry()
    result = await registry.execute("delete_file", {"path": str(path)}, confirm=False)
    assert result.ok is False
    assert result.error == "tier-3-confirmation-required"
