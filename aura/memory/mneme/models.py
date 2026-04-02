"""Data models for MNEME."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


ALLOWED_CATEGORIES = {
    "personal",
    "projects",
    "academic",
    "technical",
    "people",
    "preferences",
    "tasks",
    "general",
    "stream",
}


@dataclass(slots=True)
class MemoryRecord:
    """A persisted memory item."""

    id: str
    key: str
    value: str
    category: str
    tags: list[str]
    embedding: list[float]
    source: str
    confidence: float
    created_at: str
    updated_at: str
    access_count: int
    last_accessed: str


@dataclass(slots=True)
class RecallResult:
    """A ranked memory recall result."""

    record: MemoryRecord
    similarity_score: float
    rank: int


@dataclass(slots=True)
class ConsolidationReport:
    """Summary of consolidation work."""

    merged_count: int
    flagged_stale_count: int
    total_before: int
    total_after: int
    details: dict[str, Any] = field(default_factory=dict)
