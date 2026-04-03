"""MNEME memory operations."""

from __future__ import annotations

import asyncio
import json
import math
import sqlite3
import uuid
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import chromadb
from chromadb.config import Settings

from aura.core.config import AppConfig, load_config
from aura.core.logging import get_logger
from aura.core.tools import GLOBAL_TOOL_REGISTRY, ToolSpec

from .models import ALLOWED_CATEGORIES, ConsolidationReport, MemoryRecord, RecallResult

LOGGER = get_logger(__name__, component="mneme")
CONFIG: AppConfig = load_config()
_ROUTER: Any | None = None
_EMBED_MODEL: Any | None = None
_EMBED_DIM = 128
_CHROMA_CLIENT: chromadb.PersistentClient | None = None
_CHROMA_COLLECTION: Any | None = None
_READY = False


class MnemeError(Exception):
    """Raised when memory operations fail."""


def set_config(config: AppConfig) -> None:
    """Override the runtime configuration used by MNEME."""

    global CONFIG, _READY, _CHROMA_CLIENT, _CHROMA_COLLECTION
    CONFIG = config
    _READY = False
    _CHROMA_CLIENT = None
    _CHROMA_COLLECTION = None


def set_router(router: Any | None) -> None:
    """Set the router used for auto extraction."""

    global _ROUTER
    _ROUTER = router


def _ensure_ready() -> None:
    """Create the database schema and working directories."""

    global _READY
    if _READY:
        return
    CONFIG.paths.data_dir.mkdir(parents=True, exist_ok=True)
    (CONFIG.paths.data_dir / "models" / "embeddings").mkdir(parents=True, exist_ok=True)
    with _connect() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS memories (
                id TEXT PRIMARY KEY,
                key TEXT NOT NULL,
                value TEXT NOT NULL,
                category TEXT NOT NULL,
                tags TEXT NOT NULL,
                source TEXT NOT NULL,
                confidence REAL NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                access_count INTEGER NOT NULL DEFAULT 0,
                last_accessed TEXT NOT NULL,
                embedding_json TEXT NOT NULL
            )
            """
        )
        connection.execute("CREATE INDEX IF NOT EXISTS idx_memories_key ON memories(key)")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_memories_category ON memories(category)")
    _READY = True


def _db_path() -> Path:
    """Return the SQLite database path."""

    return CONFIG.paths.data_dir / "mneme.db"


def _connect() -> sqlite3.Connection:
    """Open the SQLite database."""

    connection = sqlite3.connect(_db_path())
    connection.row_factory = sqlite3.Row
    return connection


def _chroma_dir() -> Path:
    return CONFIG.paths.data_dir / "chroma"


def _get_embed_model() -> Any:
    """Return the local sentence-transformers embedder."""

    global _EMBED_MODEL
    if _EMBED_MODEL is None:
        from sentence_transformers import SentenceTransformer  # type: ignore

        _EMBED_MODEL = SentenceTransformer("all-MiniLM-L6-v2")
    return _EMBED_MODEL


def _ensure_chroma_collection() -> Any:
    """Create the persistent Chroma collection lazily."""

    global _CHROMA_CLIENT, _CHROMA_COLLECTION
    if _CHROMA_COLLECTION is not None:
        return _CHROMA_COLLECTION
    _chroma_dir().mkdir(parents=True, exist_ok=True)
    if _CHROMA_CLIENT is None:
        _CHROMA_CLIENT = chromadb.PersistentClient(path=str(_chroma_dir()), settings=Settings(anonymized_telemetry=False))
    _CHROMA_COLLECTION = _CHROMA_CLIENT.get_or_create_collection(
        name="aura_memories",
        metadata={"hnsw:space": "cosine"},
    )
    return _CHROMA_COLLECTION


def _now() -> str:
    """Return the current UTC timestamp."""

    return datetime.now(timezone.utc).isoformat()


def _validate_category(category: str) -> str:
    """Validate that a memory category is allowed."""

    if category not in ALLOWED_CATEGORIES:
        raise MnemeError(f"invalid category: {category}")
    return category


def _is_sensitive(text: str) -> bool:
    lowered = text.lower()
    return any(marker in lowered for marker in ["password", "passwd", "token", "secret", "private key", "api key"])


def _normalize_tags(tags: list[str] | None) -> list[str]:
    return [tag.strip() for tag in (tags or []) if tag and tag.strip()]


def _embed_text(text: str) -> list[float]:
    """Generate an offline embedding vector."""

    try:
        vector = _get_embed_model().encode([text], normalize_embeddings=True)[0]
        return [float(value) for value in vector]
    except Exception:
        vector = [0.0] * _EMBED_DIM
        tokens = Counter(token for token in "".join(ch.lower() if ch.isalnum() else " " for ch in text).split() if token)
        for token, count in tokens.items():
            vector[hash(token) % _EMBED_DIM] += float(count)
        norm = math.sqrt(sum(value * value for value in vector)) or 1.0
        return [value / norm for value in vector]


def _cosine(a: list[float], b: list[float]) -> float:
    """Calculate cosine similarity between two vectors."""

    if not a or not b:
        return 0.0
    size = min(len(a), len(b))
    dot = sum(a[i] * b[i] for i in range(size))
    a_norm = math.sqrt(sum(value * value for value in a[:size])) or 1.0
    b_norm = math.sqrt(sum(value * value for value in b[:size])) or 1.0
    return dot / (a_norm * b_norm)


def _row_to_record(row: sqlite3.Row) -> MemoryRecord:
    return MemoryRecord(
        id=row["id"],
        key=row["key"],
        value=row["value"],
        category=row["category"],
        tags=json.loads(row["tags"]),
        embedding=json.loads(row["embedding_json"]),
        source=row["source"],
        confidence=float(row["confidence"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        access_count=int(row["access_count"]),
        last_accessed=row["last_accessed"],
    )


def _record_to_metadata(record: MemoryRecord) -> dict[str, Any]:
    return {
        "key": record.key,
        "value": record.value,
        "category": record.category,
        "tags": json.dumps(record.tags),
        "source": record.source,
        "confidence": float(record.confidence),
        "created_at": record.created_at,
        "updated_at": record.updated_at,
        "access_count": int(record.access_count),
        "last_accessed": record.last_accessed,
    }


def _metadata_to_record(memory_id: str, metadata: dict[str, Any] | None, document: str | None = None, embedding: list[float] | None = None) -> MemoryRecord:
    data = metadata or {}
    key = str(data.get("key", memory_id))
    value = str(data.get("value", document or ""))
    tags_raw = data.get("tags", "[]")
    tags: list[str]
    try:
        tags_data = json.loads(tags_raw) if isinstance(tags_raw, str) else tags_raw
        tags = [str(tag) for tag in tags_data] if isinstance(tags_data, list) else []
    except Exception:
        tags = []
    record_embedding = embedding if embedding is not None else _embed_text(f"{key}\n{value}")
    return MemoryRecord(
        id=memory_id,
        key=key,
        value=value,
        category=str(data.get("category", "general")),
        tags=tags,
        embedding=record_embedding,
        source=str(data.get("source", "manual")),
        confidence=float(data.get("confidence", 1.0)),
        created_at=str(data.get("created_at", _now())),
        updated_at=str(data.get("updated_at", _now())),
        access_count=int(data.get("access_count", 0)),
        last_accessed=str(data.get("last_accessed", _now())),
    )


def _upsert_chroma(record: MemoryRecord) -> None:
    collection = _ensure_chroma_collection()
    collection.upsert(
        ids=[record.id],
        documents=[f"{record.key}\n{record.value}"],
        embeddings=[record.embedding],
        metadatas=[_record_to_metadata(record)],
    )


def _fetch_chroma(memory_id: str) -> MemoryRecord | None:
    collection = _ensure_chroma_collection()
    result = collection.get(ids=[memory_id], include=["metadatas", "documents", "embeddings"])
    ids = result.get("ids")
    if ids is None:
        ids = []
    if len(ids) == 0:
        return None
    metadatas = result.get("metadatas")
    documents = result.get("documents")
    embeddings = result.get("embeddings")
    metadata = metadatas[0] if metadatas is not None and len(metadatas) > 0 else None
    document = documents[0] if documents is not None and len(documents) > 0 else None
    embedding = embeddings[0] if embeddings is not None and len(embeddings) > 0 else None
    embedding_list = [float(value) for value in embedding] if embedding is not None else None
    return _metadata_to_record(str(ids[0]), metadata if isinstance(metadata, dict) else None, str(document) if document is not None else None, embedding_list)


def _fetch_by_id(memory_id: str) -> MemoryRecord:
    with _connect() as connection:
        row = connection.execute("SELECT * FROM memories WHERE id = ?", (memory_id,)).fetchone()
    if row is not None:
        return _row_to_record(row)
    chroma_record = _fetch_chroma(memory_id)
    if chroma_record is None:
        raise MnemeError(f"memory not found: {memory_id}")
    return chroma_record


def _fetch_by_key(key: str) -> MemoryRecord | None:
    with _connect() as connection:
        row = connection.execute("SELECT * FROM memories WHERE key = ?", (key,)).fetchone()
    if row is not None:
        return _row_to_record(row)
    collection = _ensure_chroma_collection()
    result = collection.get(where={"key": key}, include=["metadatas", "documents", "embeddings"])
    ids = result.get("ids")
    if ids is None:
        ids = []
    if len(ids) == 0:
        return None
    metadatas = result.get("metadatas")
    documents = result.get("documents")
    embeddings = result.get("embeddings")
    metadata = metadatas[0] if metadatas is not None and len(metadatas) > 0 else None
    document = documents[0] if documents is not None and len(documents) > 0 else None
    embedding = embeddings[0] if embeddings is not None and len(embeddings) > 0 else None
    embedding_list = [float(value) for value in embedding] if embedding is not None else None
    return _metadata_to_record(str(ids[0]), metadata if isinstance(metadata, dict) else None, str(document) if document is not None else None, embedding_list)


def _upsert(record: MemoryRecord) -> MemoryRecord:
    with _connect() as connection:
        connection.execute(
            """
            INSERT OR REPLACE INTO memories
            (id, key, value, category, tags, source, confidence, created_at, updated_at, access_count, last_accessed, embedding_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.id,
                record.key,
                record.value,
                record.category,
                json.dumps(record.tags),
                record.source,
                record.confidence,
                record.created_at,
                record.updated_at,
                record.access_count,
                record.last_accessed,
                json.dumps(record.embedding),
            ),
        )
        connection.commit()
    _upsert_chroma(record)
    return record


def save_memory(
    key: str,
    value: str,
    category: str,
    tags: list[str] | None = None,
    source: str = "manual",
    confidence: float = 1.0,
) -> MemoryRecord:
    """Save a memory and its embedding."""

    _ensure_ready()
    if _is_sensitive(value):
        raise MnemeError("sensitive values are not stored in MNEME")
    _validate_category(category)
    existing = _fetch_by_key(key)
    if existing is not None:
        return update_memory(existing.id, new_value=value, new_tags=tags, new_confidence=confidence)
    now = _now()
    record = MemoryRecord(
        id=str(uuid.uuid4()),
        key=key,
        value=value,
        category=category,
        tags=_normalize_tags(tags),
        embedding=_embed_text(f"{key}\n{value}"),
        source=source,
        confidence=float(confidence),
        created_at=now,
        updated_at=now,
        access_count=0,
        last_accessed=now,
    )
    return _upsert(record)


def _all_records() -> list[MemoryRecord]:
    with _connect() as connection:
        rows = connection.execute("SELECT * FROM memories ORDER BY last_accessed DESC").fetchall()
    return [_row_to_record(row) for row in rows]


def _touch(record_id: str) -> None:
    with _connect() as connection:
        connection.execute(
            "UPDATE memories SET access_count = access_count + 1, last_accessed = ? WHERE id = ?",
            (_now(), record_id),
        )
        connection.commit()


def recall_memory(query: str, top_k: int = 5, category_filter: str | None = None, min_score: float = 0.3) -> list[RecallResult]:
    """Recall memories ranked by similarity to the query."""

    _ensure_ready()
    if category_filter is not None:
        _validate_category(category_filter)
    query_embedding = _embed_text(query)
    collection = _ensure_chroma_collection()
    query_kwargs: dict[str, Any] = {
        "query_embeddings": [query_embedding],
        "n_results": top_k,
        "include": ["metadatas", "documents", "distances"],
    }
    if category_filter is not None:
        query_kwargs["where"] = {"category": category_filter}
    query_result = collection.query(**query_kwargs)
    scored: list[tuple[float, MemoryRecord]] = []
    ids_rows = query_result.get("ids")
    metadatas_rows = query_result.get("metadatas")
    documents_rows = query_result.get("documents")
    distances_rows = query_result.get("distances")
    if ids_rows is None:
        ids_rows = [[]]
    if metadatas_rows is None:
        metadatas_rows = [[]]
    if documents_rows is None:
        documents_rows = [[]]
    if distances_rows is None:
        distances_rows = [[]]
    ids = ids_rows[0]
    metadatas = metadatas_rows[0]
    documents = documents_rows[0]
    distances = distances_rows[0]
    for index, memory_id in enumerate(ids):
        distance = float(distances[index]) if index < len(distances) and distances[index] is not None else 1.0
        similarity = max(0.0, 1.0 - distance)
        if similarity < min_score:
            continue
        metadata = metadatas[index] if index < len(metadatas) and isinstance(metadatas[index], dict) else None
        document = documents[index] if index < len(documents) else None
        try:
            record = _fetch_by_id(str(memory_id))
        except MnemeError:
            record = _metadata_to_record(str(memory_id), metadata, str(document) if document is not None else None)
        scored.append((similarity, record))
    scored.sort(key=lambda item: item[0], reverse=True)
    results: list[RecallResult] = []
    for rank, (score, record) in enumerate(scored[:top_k], start=1):
        _touch(record.id)
        refreshed = _fetch_by_id(record.id)
        results.append(RecallResult(record=refreshed, similarity_score=score, rank=rank))
    return results


def update_memory(
    id: str,
    new_value: str | None = None,
    new_tags: list[str] | None = None,
    new_confidence: float | None = None,
) -> MemoryRecord:
    """Update an existing memory."""

    _ensure_ready()
    record = _fetch_by_id(id)
    value = new_value if new_value is not None else record.value
    tags = _normalize_tags(new_tags) if new_tags is not None else record.tags
    confidence = float(new_confidence) if new_confidence is not None else record.confidence
    embedding = _embed_text(f"{record.key}\n{value}") if new_value is not None else record.embedding
    updated = MemoryRecord(
        id=record.id,
        key=record.key,
        value=value,
        category=record.category,
        tags=tags,
        embedding=embedding,
        source=record.source,
        confidence=confidence,
        created_at=record.created_at,
        updated_at=_now(),
        access_count=record.access_count,
        last_accessed=_now(),
    )
    return _upsert(updated)


def delete_memory(id: str) -> dict[str, Any]:
    """Delete a memory from storage."""

    _ensure_ready()
    with _connect() as connection:
        row = connection.execute("SELECT 1 FROM memories WHERE id = ?", (id,)).fetchone()
        if row is None:
            chroma_record = _fetch_chroma(id)
            if chroma_record is None:
                return {"success": False, "message": f"memory not found: {id}", "data": {"id": id}}
        connection.execute("DELETE FROM memories WHERE id = ?", (id,))
        connection.commit()
    collection = _ensure_chroma_collection()
    collection.delete(ids=[id])
    return {"success": True, "message": "memory deleted", "data": {"id": id}}


def list_memories(category: str | None = None, tag_filter: str | None = None, limit: int = 50) -> list[MemoryRecord]:
    """List memories from SQLite."""

    _ensure_ready()
    collection = _ensure_chroma_collection()
    query_kwargs: dict[str, Any] = {"limit": limit, "include": ["metadatas", "documents", "embeddings"]}
    if category is not None:
        _validate_category(category)
        query_kwargs["where"] = {"category": category}
    result = collection.get(**query_kwargs)
    ids = result.get("ids")
    metadatas = result.get("metadatas")
    documents = result.get("documents")
    embeddings = result.get("embeddings")
    if ids is None:
        ids = []
    if metadatas is None:
        metadatas = []
    if documents is None:
        documents = []
    if embeddings is None:
        embeddings = []
    memories: list[MemoryRecord] = []
    for index, memory_id in enumerate(ids):
        metadata = metadatas[index] if index < len(metadatas) and isinstance(metadatas[index], dict) else None
        document = documents[index] if index < len(documents) else None
        embedding = embeddings[index] if index < len(embeddings) else None
        embedding_list = [float(value) for value in embedding] if embedding is not None else None
        try:
            record = _fetch_by_id(str(memory_id))
        except MnemeError:
            record = _metadata_to_record(str(memory_id), metadata, str(document) if document is not None else None, embedding_list)
        memories.append(record)
    if tag_filter is not None:
        memories = [record for record in memories if tag_filter in record.tags or tag_filter in record.value or tag_filter in record.key]
    return memories[:limit]


def consolidate_memory() -> ConsolidationReport:
    """Merge duplicate memories and flag stale entries."""

    _ensure_ready()
    records = _all_records()
    merged_count = 0
    consumed: set[str] = set()
    for i, left in enumerate(records):
        if left.id in consumed:
            continue
        for right in records[i + 1 :]:
            if right.id in consumed:
                continue
            if _cosine(left.embedding, right.embedding) > 0.95:
                merged_count += 1
                keep, drop = (left, right) if left.confidence >= right.confidence else (right, left)
                merged_tags = sorted(set(keep.tags) | set(drop.tags))
                update_memory(keep.id, new_tags=merged_tags, new_confidence=max(keep.confidence, drop.confidence))
                delete_memory(drop.id)
                consumed.add(drop.id)
    stale_cutoff = datetime.now(timezone.utc) - timedelta(days=90)
    flagged_stale = 0
    for record in _all_records():
        if datetime.fromisoformat(record.last_accessed) < stale_cutoff and record.confidence < 0.5:
            flagged_stale += 1
    total_after = len(_all_records())
    return ConsolidationReport(
        merged_count=merged_count,
        flagged_stale_count=flagged_stale,
        total_before=len(records),
        total_after=total_after,
        details={"consumed": list(consumed)},
    )


def inject_context(query: str, max_tokens: int = 500) -> str:
    """Format recalled memories into concise context for the LLM."""

    recalls = recall_memory(query, top_k=5)
    if not recalls:
        return ""
    lines: list[str] = []
    budget = max_tokens * 4
    used = 0
    for recall in recalls:
        line = f"[memory:{recall.record.category}] {recall.record.key}: {recall.record.value}"
        if used + len(line) > budget:
            break
        lines.append(line)
        used += len(line)
    return "\n".join(lines)


async def auto_extract_memories(conversation_turn: str, response: str) -> list[MemoryRecord]:
    """Extract memory candidates from a conversation turn."""

    _ensure_ready()
    router = _ROUTER
    if router is None:
        return []
    prompt = (
        "Extract factual statements about the user worth remembering. "
        "Return JSON list: [{key, value, category, confidence}]\n\n"
        f"Conversation: {conversation_turn}\nResponse: {response}"
    )
    try:
        if hasattr(router, "generate"):
            result = router.generate(prompt)
        else:
            result = router.chat([{"role": "user", "content": prompt}])
        if asyncio.iscoroutine(result):
            result = await result
        content = getattr(result, "content", result)
        payload = json.loads(content or "[]")
    except Exception:
        return []
    saved: list[MemoryRecord] = []
    if isinstance(payload, list):
        for item in payload:
            if not isinstance(item, dict):
                continue
            confidence = float(item.get("confidence", 0.0))
            if confidence < 0.7:
                continue
            try:
                saved.append(
                    save_memory(
                        key=str(item.get("key", "extracted-memory")),
                        value=str(item.get("value", "")),
                        category=str(item.get("category", "general")),
                        tags=["auto-extracted"],
                        source="auto",
                        confidence=confidence,
                    )
                )
            except Exception:
                continue
    return saved


def get_memory_tools() -> list[ToolSpec]:
    """Return the MNEME tool specifications."""

    return [
        ToolSpec("save_memory", "Save a memory.", 1, {"type": "object"}, {"type": "object"}, lambda args: save_memory(args["key"], args["value"], args["category"], args.get("tags"), args.get("source", "manual"), args.get("confidence", 1.0))),
        ToolSpec("recall_memory", "Recall memories.", 1, {"type": "object"}, {"type": "array"}, lambda args: recall_memory(args["query"], args.get("top_k", 5), args.get("category_filter"), args.get("min_score", 0.3))),
        ToolSpec("update_memory", "Update a memory.", 1, {"type": "object"}, {"type": "object"}, lambda args: update_memory(args["id"], args.get("new_value"), args.get("new_tags"), args.get("new_confidence"))),
        ToolSpec("delete_memory", "Delete a memory.", 2, {"type": "object"}, {"type": "object"}, lambda args: delete_memory(args["id"])),
        ToolSpec("list_memories", "List memories.", 1, {"type": "object"}, {"type": "array"}, lambda args: list_memories(args.get("category"), args.get("tag_filter"), args.get("limit", 50))),
        ToolSpec("consolidate_memory", "Consolidate duplicate memories.", 1, {"type": "object"}, {"type": "object"}, lambda args: consolidate_memory()),
        ToolSpec("inject_context", "Inject memory context into prompts.", 1, {"type": "object"}, {"type": "string"}, lambda args: inject_context(args["query"], args.get("max_tokens", 500))),
        ToolSpec(
            "auto_extract_memories",
            "Extract memories from a response.",
            1,
            {"type": "object"},
            {"type": "array"},
            lambda args: asyncio.run(auto_extract_memories(args["conversation_turn"], args["response"])),
        ),
    ]


def register_memory_tools() -> None:
    """Register MNEME tools in the global registry."""

    registry = GLOBAL_TOOL_REGISTRY
    for spec in get_memory_tools():
        try:
            registry.register(spec)
        except ValueError:
            continue


register_memory_tools()
