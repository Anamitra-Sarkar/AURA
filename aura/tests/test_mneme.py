from __future__ import annotations

import json
from dataclasses import dataclass

import pytest

from aura.core.config import AppConfig, FeatureFlags, ModelSettings, PathsSettings
from aura.memory.mneme import tools as mneme
from aura.memory.mneme.models import RecallResult


@dataclass
class FakeRouterResult:
    content: str


class FakeRouter:
    def generate(self, prompt: str) -> FakeRouterResult:
        payload = [
            {"key": "favorite tool", "value": "The user likes Python", "category": "technical", "confidence": 0.9},
            {"key": "low confidence", "value": "Ignore this", "category": "general", "confidence": 0.2},
        ]
        return FakeRouterResult(content=json.dumps(payload))


@pytest.fixture()
def mneme_config(tmp_path):
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
    mneme.set_config(config)
    mneme.set_router(None)
    return config


def test_save_recall_update_delete_and_list(mneme_config):
    saved = mneme.save_memory("favorite color", "The user likes blue", "preferences", tags=["color"], source="manual", confidence=0.8)
    assert saved.key == "favorite color"

    recalled = mneme.recall_memory("blue", top_k=3)
    assert recalled and recalled[0].record.id == saved.id

    updated = mneme.update_memory(saved.id, new_value="The user likes green", new_tags=["color", "updated"], new_confidence=0.95)
    assert updated.value == "The user likes green"
    assert "updated" in updated.tags

    listed = mneme.list_memories(category="preferences")
    assert listed and listed[0].id == saved.id

    deleted = mneme.delete_memory(saved.id)
    assert deleted["success"] is True
    assert mneme.list_memories(category="preferences") == []


def test_inject_context_formats_relevant_memories(monkeypatch, mneme_config):
    record = mneme.MemoryRecord(
        id="123",
        key="project",
        value="AURA is an OS-level daemon",
        category="projects",
        tags=["daemon"],
        embedding=[1.0, 0.0],
        source="manual",
        confidence=1.0,
        created_at="2025-01-01T00:00:00+00:00",
        updated_at="2025-01-01T00:00:00+00:00",
        access_count=0,
        last_accessed="2025-01-01T00:00:00+00:00",
    )
    monkeypatch.setattr(mneme, "recall_memory", lambda query, top_k=5, category_filter=None, min_score=0.3: [RecallResult(record=record, similarity_score=0.99, rank=1)])
    context = mneme.inject_context("daemon")
    assert "[memory:projects] project: AURA is an OS-level daemon" in context


@pytest.mark.asyncio
async def test_auto_extract_memories_saves_high_confidence(mneme_config):
    mneme.set_router(FakeRouter())
    saved = await mneme.auto_extract_memories("I like Python", "Got it")
    memories = mneme.list_memories(category="technical")
    assert saved and saved[0].key == "favorite tool"
    assert memories and memories[0].value == "The user likes Python"


def test_consolidate_memory_merges_near_duplicates(monkeypatch, mneme_config):
    def fake_embed(text: str) -> list[float]:
        return [1.0, 0.0] if "python" in text.lower() else [0.0, 1.0]

    monkeypatch.setattr(mneme, "_embed_text", fake_embed)
    mneme.save_memory("tool-a", "The user likes Python", "technical", tags=["a"], confidence=0.9)
    mneme.save_memory("tool-b", "The user likes Python too", "technical", tags=["b"], confidence=0.8)
    report = mneme.consolidate_memory()
    remaining = mneme.list_memories(category="technical")

    assert report.merged_count >= 1
    assert report.total_before == 2
    assert report.total_after == 1
    assert len(remaining) == 1
    assert set(remaining[0].tags) == {"a", "b"} or set(remaining[0].tags) == {"a"} or set(remaining[0].tags) == {"b"}
