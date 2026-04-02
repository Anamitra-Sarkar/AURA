"""Data models for STREAM."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(slots=True)
class StreamSource:
    id: str
    name: str
    type: str
    query: str
    last_checked: datetime | None
    last_hash: str
    enabled: bool


@dataclass(slots=True)
class StreamItem:
    id: str
    source_id: str
    title: str
    summary: str
    url: str
    relevance_score: float
    tags: list[str]
    discovered_at: datetime
    read: bool = False


@dataclass(slots=True)
class DailyDigest:
    date: str
    items: list[StreamItem]
    total_found: int
    highlights: list[StreamItem]
    generated_at: datetime
    metadata: dict[str, Any] = field(default_factory=dict)
