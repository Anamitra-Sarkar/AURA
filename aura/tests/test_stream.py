from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

import aura.agents.stream.tools as stream
from aura.agents.phantom import tools as phantom_tools
from aura.core.config import AppConfig, EnsembleSettings, FeatureFlags, LyraSettings, ModelSettings, PathsSettings, StreamSettings, StreamSourceConfig, UISettings
from aura.memory import list_memories, save_memory
from aura.memory.mneme import tools as mneme_tools


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
        stream=StreamSettings(
            enabled=True,
            fetch_interval_hours=6,
            min_relevance_score=0.4,
            sources=[
                StreamSourceConfig(name="ArXiv AI/ML", type="arxiv", query="large language model transformer"),
                StreamSourceConfig(name="HackerNews AI", type="hackernews", query="LLM machine learning"),
                StreamSourceConfig(name="PyPI", type="pypi", query="torch"),
                StreamSourceConfig(name="GitHub", type="github", query="ai"),
                StreamSourceConfig(name="Kaggle", type="kaggle", query=""),
                StreamSourceConfig(name="RSS", type="rss", query="https://example.com/feed.xml"),
            ],
        ),
    )


@pytest.fixture()
def stream_runtime(tmp_path, monkeypatch):
    config = _config(tmp_path)
    mneme_tools.set_config(config)
    phantom_tools.set_config(config)
    stream.set_config(config)
    return config


@pytest.mark.asyncio
async def test_fetch_stream_routes_and_saves(monkeypatch, stream_runtime):
    called = []

    def make_item(source, suffix):
        return stream.StreamItem(id=f"{source.id}-{suffix}", source_id=source.id, title=f"{source.type} title", summary="LLM transformers and LoRA", url=f"https://example.com/{suffix}", relevance_score=0.0, tags=[source.type], discovered_at=datetime.now(timezone.utc))

    monkeypatch.setattr(stream, "_fetch_arxiv", lambda source: called.append(source.type) or [make_item(source, "a")])
    monkeypatch.setattr(stream, "_fetch_hackernews", lambda source: called.append(source.type) or [make_item(source, "h")])
    monkeypatch.setattr(stream, "_fetch_pypi", lambda source: called.append(source.type) or [make_item(source, "p")])
    monkeypatch.setattr(stream, "_fetch_github", lambda source: called.append(source.type) or [make_item(source, "g")])
    monkeypatch.setattr(stream, "_fetch_kaggle", lambda source: called.append(source.type) or [make_item(source, "k")])
    monkeypatch.setattr(stream, "_fetch_rss", lambda source: called.append(source.type) or [make_item(source, "r")])

    async def fake_score(_item):
        return 0.9

    monkeypatch.setattr(stream, "_score_relevance", fake_score)

    items = await stream.fetch_stream()
    assert {item.source_id for item in items}
    assert set(called) == {"arxiv", "hackernews", "pypi", "github", "kaggle", "rss"}
    assert list_memories(category="stream", limit=20)


@pytest.mark.asyncio
async def test_fetch_stream_filters_low_scores(monkeypatch, stream_runtime):
    monkeypatch.setattr(stream, "_fetch_arxiv", lambda source: [stream.StreamItem(id="x", source_id=source.id, title="x", summary="y", url="https://example.com/x", relevance_score=0.0, tags=[], discovered_at=datetime.now(timezone.utc))])

    async def fake_score(_item):
        return 0.1

    monkeypatch.setattr(stream, "_score_relevance", fake_score)
    assert await stream.fetch_stream("arxiv") == []


def test_daily_digest_and_read_tracking(monkeypatch, stream_runtime):
    target_date = datetime.now(timezone.utc).date().isoformat()
    items = []
    for index in range(6):
        item = stream.StreamItem(
            id=f"item-{index}",
            source_id="source-1",
            title=f"Item {index}",
            summary="Transformers and LoRA",
            url=f"https://example.com/{index}",
            relevance_score=0.9 - index * 0.1,
            tags=["stream"],
            discovered_at=datetime.now(timezone.utc),
        )
        if index == 5:
            item.read = True
        items.append(item)
        save_memory(f"stream:source-1:{item.id}", stream._serialize_item(item), "stream", tags=["stream"], source="stream", confidence=item.relevance_score)

    digest = stream.generate_daily_digest(target_date)
    assert digest.date == target_date
    assert digest.total_found == 5
    assert len(digest.highlights) == 5
    assert digest.highlights[0].relevance_score >= digest.highlights[-1].relevance_score

    unread = stream.get_unread_items(limit=10)
    assert all(item.read is False for item in unread)

    result = stream.mark_item_read("item-0")
    assert result["success"] is True


def test_add_source_and_startup_registration(stream_runtime):
    before = len(stream.list_stream_sources())
    with pytest.raises(ValueError):
        stream.add_stream_source("Bad", "invalid", "query")
    added = stream.add_stream_source("New RSS", "rss", "https://example.com/feed.xml")
    assert added.type == "rss"
    assert len(stream.list_stream_sources()) == before + 1
    workflows = phantom_tools.list_workflows()
    names = {task.id for task in workflows}
    assert "stream.fetch_all" in names
    assert "stream.daily_digest" in names
