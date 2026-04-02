"""Data models for MOSAIC."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(slots=True)
class SourceInput:
    id: str
    type: str
    content: str
    path_or_url: str | None = None
    weight: float = 1.0
    label: str = ""


@dataclass(slots=True)
class OverlapCluster:
    topic: str
    sources_agreeing: list[str]
    sources_disagreeing: list[str]
    resolution: str


@dataclass(slots=True)
class MosaicResult:
    id: str
    task: str
    sources_used: list[SourceInput]
    overlaps: list[OverlapCluster]
    contradictions: list[OverlapCluster]
    output: str
    output_format: str
    confidence: float
    source_attribution: dict[str, Any]
    word_count: int
    generated_at: datetime
    metadata: dict[str, Any] = field(default_factory=dict)
