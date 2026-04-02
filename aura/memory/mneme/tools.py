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

from aura.core.config import AppConfig, load_config
from aura.core.logging import get_logger
from aura.core.tools import ToolSpec, get_tool_registry

from .models import ALLOWED_CATEGORIES, ConsolidationReport, MemoryRecord, RecallResult

LOGGER = get_logger(__name__, component="mneme")
CONFIG: AppConfig = load_config()
_ROUTER: Any | None = None
_EMBED_MODEL: Any | None = None
_EMBED_DIM = 128
_READY = False


class MnemeError(Exception):
    """Raised when memory operations fail."""


def set_config(config: AppConfig) -> None:
    """Override the runtime configuration used by MNEME."""

    global CONFIG, _READY
    CONFIG = config
    _READY = False


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

    global _EMBED_MODEL
    try:
        if _EMBED_MODEL is None:
            from sentence_transformers import SentenceTransformer  # type: ignore

            _EMBED_MODEL = SentenceTransformer("all-MiniLM-L6-v2")
        vector = _EMBED_MODEL.encode([text], normalize_embeddings=True)[0]
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


def _fetch_by_id(memory_id: str) -> MemoryRecord:
    with _connect() as connection:
        row = connection.execute("SELECT * FROM memories WHERE id = ?", (memory_id,)).fetchone()
    if row is None:
        raise MnemeError(f"memory not found: {memory_id}")
    return _row_to_record(row)


def _fetch_by_key(key: str) -> MemoryRecord | None:
    with _connect() as connection:
        row = connection.execute("SELECT * FROM memories WHERE key = ?", (key,)).fetchone()
    return _row_to_record(row) if row is not None else None


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
    scored: list[tuple[float, MemoryRecord]] = []
    for record in _all_records():
        if category_filter and record.category != category_filter:
            continue
        score = _cosine(query_embedding, record.embedding)
        if score >= min_score:
            scored.append((score, record))
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
            return {"success": False, "message": f"memory not found: {id}", "data": {"id": id}}
        connection.execute("DELETE FROM memories WHERE id = ?", (id,))
        connection.commit()
    return {"success": True, "message": "memory deleted", "data": {"id": id}}


def list_memories(category: str | None = None, tag_filter: str | None = None, limit: int = 50) -> list[MemoryRecord]:
    """List memories from SQLite."""

    _ensure_ready()
    sql = "SELECT * FROM memories"
    params: list[Any] = []
    clauses: list[str] = []
    if category is not None:
        _validate_category(category)
        clauses.append("category = ?")
        params.append(category)
    if tag_filter is not None:
        clauses.append("tags LIKE ?")
        params.append(f"%{tag_filter}%")
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY last_accessed DESC LIMIT ?"
    params.append(limit)
    with _connect() as connection:
        rows = connection.execute(sql, params).fetchall()
    return [_row_to_record(row) for row in rows]


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
        ToolSpec("auto_extract_memories", "Extract memories from a response.", 1, {"type": "object"}, {"type": "array"}, lambda args: auto_extract_memories(args["conversation_turn"], args["response"])),
    ]


def register_memory_tools() -> None:
    """Register MNEME tools in the global registry."""

    registry = get_tool_registry()
    for spec in get_memory_tools():
        try:
            registry.register(spec)
        except ValueError:
            pass


register_memory_tools()
