"""STREAM world-awareness feed tools."""

from __future__ import annotations

import asyncio
import json
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote_plus
from urllib.request import urlopen
from xml.etree import ElementTree as ET

from aura.agents.iris import tools as iris_tools
from aura.agents.phantom import tools as phantom_tools
from aura.core.config import AppConfig, StreamSourceConfig, load_config
from aura.core.llm_router import OllamaRouter
from aura.core.logging import get_logger
from aura.core.tools import ToolSpec, get_tool_registry
from aura.memory import list_memories, save_memory, update_memory

from .models import DailyDigest, StreamItem, StreamSource

LOGGER = get_logger(__name__, component="stream")
CONFIG: AppConfig = load_config()
_ROUTER: Any | None = None
_SUPPORTED_TYPES = {"arxiv", "github", "kaggle", "rss", "hackernews", "pypi"}


def set_config(config: AppConfig) -> None:
    """Override the runtime configuration used by STREAM."""

    global CONFIG
    CONFIG = config
    _register_default_tasks()


def set_router(router: Any | None) -> None:
    """Set the router used for relevance scoring."""

    global _ROUTER
    _ROUTER = router


def _stream_settings() -> Any:
    return CONFIG.stream


def _router() -> Any:
    if _ROUTER is not None:
        return _ROUTER
    return OllamaRouter(model=CONFIG.primary_model.name, host=CONFIG.primary_model.host)


def _source_id(name: str, type: str, query: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"{type}:{name}:{query}"))


def _item_id(source_id: str, url: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"{source_id}:{url}"))


def _item_key(item: StreamItem) -> str:
    return f"stream:{item.source_id}:{item.id}"


def _serialize_item(item: StreamItem) -> str:
    payload = asdict(item)
    payload["discovered_at"] = item.discovered_at.isoformat()
    return json.dumps({"kind": "item", **payload}, ensure_ascii=True)


def _deserialize_item(value: str) -> StreamItem | None:
    try:
        payload = json.loads(value)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict) or payload.get("kind") not in {"item", None}:
        return None
    try:
        discovered_at = datetime.fromisoformat(str(payload["discovered_at"]))
        return StreamItem(
            id=str(payload["id"]),
            source_id=str(payload["source_id"]),
            title=str(payload["title"]),
            summary=str(payload["summary"]),
            url=str(payload["url"]),
            relevance_score=float(payload["relevance_score"]),
            tags=[str(tag) for tag in payload.get("tags", [])],
            discovered_at=discovered_at,
            read=bool(payload.get("read", False)),
        )
    except Exception:
        return None


def _deserialize_digest(value: str) -> DailyDigest | None:
    try:
        payload = json.loads(value)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict) or payload.get("kind") != "digest":
        return None
    items = [_deserialize_item(json.dumps({"kind": "item", **item}, ensure_ascii=True)) for item in payload.get("items", [])]
    highlights = [_deserialize_item(json.dumps({"kind": "item", **item}, ensure_ascii=True)) for item in payload.get("highlights", [])]
    return DailyDigest(
        date=str(payload["date"]),
        items=[item for item in items if item is not None],
        total_found=int(payload.get("total_found", 0)),
        highlights=[item for item in highlights if item is not None],
        generated_at=datetime.fromisoformat(str(payload["generated_at"])),
        metadata=dict(payload.get("metadata", {})),
    )


def _stream_memory_records() -> list[Any]:
    return list_memories(category="stream", limit=500)


def _saved_item_ids() -> set[str]:
    item_ids: set[str] = set()
    for record in _stream_memory_records():
        item = _deserialize_item(record.value)
        if item is not None:
            item_ids.add(item.id)
    return item_ids


def _saved_items() -> list[StreamItem]:
    items: list[StreamItem] = []
    for record in _stream_memory_records():
        item = _deserialize_item(record.value)
        if item is not None:
            items.append(item)
    return items


async def _score_relevance(item: StreamItem) -> float:
    prompt = (
        "Rate relevance to an AIML student building LLMs, training models, using PyTorch/JAX, interested in "
        "transformers, MoE, LoRA, context extension. Score 0.0-1.0. Return ONLY the float.\n"
        f"Title: {item.title}\nSummary: {item.summary}\nURL: {item.url}"
    )
    try:
        result = await _router().generate(prompt)
        text = str(getattr(result, "content", "") or "").strip()
        score = float(text.split()[0])
        return max(0.0, min(1.0, score))
    except Exception:
        text = f"{item.title} {item.summary}".lower()
        keywords = ["llm", "transformer", "lora", "moe", "jax", "pytorch", "context", "training", "attention", "fine-tuning"]
        score = 0.1 + 0.1 * sum(keyword in text for keyword in keywords)
        return max(0.0, min(1.0, score))


def _record_item(source: StreamSource, title: str, summary: str, url: str, tags: list[str] | None = None, relevance_score: float = 0.0) -> StreamItem:
    item = StreamItem(
        id=_item_id(source.id, url),
        source_id=source.id,
        title=title,
        summary=summary,
        url=url,
        relevance_score=relevance_score,
        tags=tags or [],
        discovered_at=datetime.now(timezone.utc),
        read=False,
    )
    save_memory(_item_key(item), _serialize_item(item), "stream", tags=["stream", source.type], source="stream", confidence=relevance_score)
    return item


def _source_from_config(entry: StreamSourceConfig) -> StreamSource:
    return StreamSource(
        id=_source_id(entry.name, entry.type, entry.query),
        name=entry.name,
        type=entry.type,
        query=entry.query,
        last_checked=None,
        last_hash="",
        enabled=True,
    )


def list_stream_sources() -> list[StreamSource]:
    """Return configured stream sources."""

    settings = _stream_settings()
    if settings is None:
        return []
    return [_source_from_config(source) for source in settings.sources]


def add_stream_source(name: str, type: str, query: str) -> StreamSource:
    """Add a stream source to the runtime configuration."""

    if type not in _SUPPORTED_TYPES:
        raise ValueError(f"unsupported stream source type: {type}")
    settings = _stream_settings()
    if settings is None:
        raise RuntimeError("stream settings unavailable")
    entry = StreamSourceConfig(name=name, type=type, query=query)
    settings.sources.append(entry)
    sources_path = CONFIG.paths.data_dir / "stream_sources.json"
    sources_path.parent.mkdir(parents=True, exist_ok=True)
    sources_path.write_text(json.dumps([asdict(source) for source in settings.sources], ensure_ascii=True), encoding="utf-8")
    return _source_from_config(entry)


def _fetch_arxiv(source: StreamSource) -> list[StreamItem]:
    papers = iris_tools.search_academic(source.query, source="arxiv", max_results=5)
    items: list[StreamItem] = []
    for paper in papers:
        items.append(
            StreamItem(
                id=_item_id(source.id, paper.url),
                source_id=source.id,
                title=paper.title,
                summary=paper.abstract,
                url=paper.url,
                relevance_score=0.0,
                tags=["arxiv", paper.source],
                discovered_at=datetime.now(timezone.utc),
                read=False,
            )
        )
    return items


def _fetch_hackernews(source: StreamSource) -> list[StreamItem]:
    url = f"https://hn.algolia.com/api/v1/search?query={quote_plus(source.query)}&tags=story&hitsPerPage=5"
    try:
        with urlopen(url, timeout=20) as response:  # noqa: S310 - free public API
            payload = json.loads(response.read().decode("utf-8", errors="replace"))
    except Exception:
        payload = {"hits": []}
    items: list[StreamItem] = []
    for hit in payload.get("hits", [])[:5]:
        items.append(
            StreamItem(
                id=_item_id(source.id, str(hit.get("url") or hit.get("objectID"))),
                source_id=source.id,
                title=str(hit.get("title") or ""),
                summary=str(hit.get("story_text") or hit.get("comment_text") or ""),
                url=str(hit.get("url") or f"https://news.ycombinator.com/item?id={hit.get('objectID')}"),
                relevance_score=0.0,
                tags=["hackernews"],
                discovered_at=datetime.now(timezone.utc),
                read=False,
            )
        )
    return items


def _fetch_pypi(source: StreamSource) -> list[StreamItem]:
    url = f"https://pypi.org/rss/search/?q={quote_plus(source.query)}"
    return _fetch_rss_url(url, source, tags=["pypi"])


def _fetch_github(source: StreamSource) -> list[StreamItem]:
    query = source.query or "ai"
    url = f"https://github.com/trending/{quote_plus(query)}?since=daily"
    return [
        StreamItem(
            id=_item_id(source.id, url),
            source_id=source.id,
            title=f"GitHub trending: {query}",
            summary=f"Trending repositories related to {query}.",
            url=url,
            relevance_score=0.0,
            tags=["github"],
            discovered_at=datetime.now(timezone.utc),
            read=False,
        )
    ]


def _fetch_kaggle(source: StreamSource) -> list[StreamItem]:
    return [
        StreamItem(
            id=_item_id(source.id, "https://www.kaggle.com/competitions"),
            source_id=source.id,
            title="Kaggle competitions",
            summary=source.query or "Kaggle competition feed",
            url="https://www.kaggle.com/competitions",
            relevance_score=0.0,
            tags=["kaggle"],
            discovered_at=datetime.now(timezone.utc),
            read=False,
        )
    ]


def _fetch_rss_url(url: str, source: StreamSource, tags: list[str]) -> list[StreamItem]:
    try:
        with urlopen(url, timeout=20) as response:  # noqa: S310 - free public feed
            content = response.read()
    except Exception:
        return []
    try:
        root = ET.fromstring(content)
    except Exception:
        return []
    items: list[StreamItem] = []
    for node in root.findall(".//item")[:5] + root.findall(".//{http://www.w3.org/2005/Atom}entry")[:5]:
        title = (node.findtext("title") or node.findtext("{http://www.w3.org/2005/Atom}title") or "").strip()
        summary = (node.findtext("description") or node.findtext("{http://www.w3.org/2005/Atom}summary") or "").strip()
        link = node.findtext("link") or node.findtext("{http://www.w3.org/2005/Atom}link") or url
        items.append(
            StreamItem(
                id=_item_id(source.id, link),
                source_id=source.id,
                title=title,
                summary=summary,
                url=link,
                relevance_score=0.0,
                tags=tags,
                discovered_at=datetime.now(timezone.utc),
                read=False,
            )
        )
    return items


def _fetch_rss(source: StreamSource) -> list[StreamItem]:
    return _fetch_rss_url(source.query, source, tags=["rss"])


def _fetch_source(source: StreamSource) -> list[StreamItem]:
    if source.type == "arxiv":
        return _fetch_arxiv(source)
    if source.type == "github":
        return _fetch_github(source)
    if source.type == "kaggle":
        return _fetch_kaggle(source)
    if source.type == "rss":
        return _fetch_rss(source)
    if source.type == "hackernews":
        return _fetch_hackernews(source)
    if source.type == "pypi":
        return _fetch_pypi(source)
    return []


async def fetch_stream(source_id: str | None = None) -> list[StreamItem]:
    """Fetch feed items from configured sources."""

    settings = _stream_settings()
    if settings is None or not settings.enabled:
        return []
    sources = list_stream_sources()
    if source_id is not None:
        sources = [source for source in sources if source.id == source_id or source.name == source_id]
    seen_ids = _saved_item_ids()
    new_items: list[StreamItem] = []
    for source in sources:
        raw_items = _fetch_source(source)
        for item in raw_items:
            if item.id in seen_ids:
                continue
            item.relevance_score = await _score_relevance(item)
            if item.relevance_score < settings.min_relevance_score:
                continue
            new_items.append(item)
            seen_ids.add(item.id)
            _record_item(source, item.title, item.summary, item.url, tags=item.tags, relevance_score=item.relevance_score)
    return new_items


def _stream_items_for_date(target_date: str) -> list[StreamItem]:
    items: list[StreamItem] = []
    for item in _saved_items():
        if item.discovered_at.date().isoformat() == target_date and not item.read:
            items.append(item)
    return items


def _digest_payload(digest: DailyDigest) -> str:
    payload = asdict(digest)
    payload["generated_at"] = digest.generated_at.isoformat()
    payload["items"] = [asdict(item) | {"discovered_at": item.discovered_at.isoformat()} for item in digest.items]
    payload["highlights"] = [asdict(item) | {"discovered_at": item.discovered_at.isoformat()} for item in digest.highlights]
    return json.dumps({"kind": "digest", **payload}, ensure_ascii=True)


def _digest_from_record(record: Any) -> DailyDigest | None:
    return _deserialize_digest(record.value)


def generate_daily_digest(date: str | None = None) -> DailyDigest:
    """Generate a daily digest from stored stream items."""

    target_date = date or datetime.now(timezone.utc).date().isoformat()
    items = sorted(_stream_items_for_date(target_date), key=lambda item: item.relevance_score, reverse=True)
    highlights = items[:5]
    digest = DailyDigest(
        date=target_date,
        items=items,
        total_found=len(items),
        highlights=highlights,
        generated_at=datetime.now(timezone.utc),
        metadata={"source_count": len(list_stream_sources())},
    )
    save_memory(f"digest:{target_date}", _digest_payload(digest), "stream", tags=["stream", "digest"], source="stream", confidence=1.0)
    return digest


def mark_item_read(item_id: str) -> dict[str, Any]:
    """Mark a stream item as read."""

    for record in _stream_memory_records():
        item = _deserialize_item(record.value)
        if item is None or item.id != item_id:
            continue
        item.read = True
        update_memory(record.id, new_value=_serialize_item(item))
        return {"success": True, "message": "item marked read", "data": {"item_id": item_id}}
    return {"success": False, "message": f"item not found: {item_id}", "data": {"item_id": item_id}}


def get_unread_items(limit: int = 20) -> list[StreamItem]:
    """Return unread stream items sorted by relevance."""

    items = [item for item in _saved_items() if not item.read]
    items.sort(key=lambda item: item.relevance_score, reverse=True)
    return items[:limit]


def _register_default_tasks() -> None:
    settings = _stream_settings()
    if settings is None or not settings.enabled:
        return
    try:
        phantom_tools.register_task("stream.fetch_all", _schedule_fetch_all, interval_hours=settings.fetch_interval_hours, run_on_startup=True, description="Fetch all configured STREAM sources")
    except Exception:
        pass
    try:
        phantom_tools.register_task("stream.daily_digest", lambda: generate_daily_digest(), schedule="daily@08:00", run_on_startup=False, description="Generate the daily STREAM digest")
    except Exception:
        pass


def _schedule_fetch_all() -> Any:
    try:
        loop = asyncio.get_running_loop()
        return loop.create_task(fetch_stream())
    except RuntimeError:
        return asyncio.run(fetch_stream())


def register_stream_tools() -> None:
    """Register STREAM tools in the global registry."""

    registry = get_tool_registry()
    specs = [
        ToolSpec("fetch_stream", "Fetch configured stream sources.", 1, {"type": "object"}, {"type": "array"}, lambda args: fetch_stream(args.get("source_id"))),
        ToolSpec("generate_daily_digest", "Generate today's digest.", 1, {"type": "object"}, {"type": "object"}, lambda args: generate_daily_digest(args.get("date"))),
        ToolSpec("add_stream_source", "Add a stream source.", 1, {"type": "object"}, {"type": "object"}, lambda args: add_stream_source(args["name"], args["type"], args["query"])),
        ToolSpec("list_stream_sources", "List stream sources.", 1, {"type": "object"}, {"type": "array"}, lambda _args: list_stream_sources()),
        ToolSpec("mark_item_read", "Mark a stream item read.", 1, {"type": "object"}, {"type": "object"}, lambda args: mark_item_read(args["item_id"])),
        ToolSpec("get_unread_items", "List unread stream items.", 1, {"type": "object"}, {"type": "array"}, lambda args: get_unread_items(args.get("limit", 20))),
    ]
    for spec in specs:
        try:
            registry.register(spec)
        except ValueError:
            pass


register_stream_tools()
_register_default_tasks()
