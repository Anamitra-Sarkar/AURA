"""Data models for HERMES browser automation."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(slots=True)
class PageHandle:
    page_id: str
    url: str
    title: str
    status_code: int


@dataclass(slots=True)
class ElementInfo:
    selector: str
    text: str
    tag: str
    is_visible: bool
    bounding_box: dict[str, Any]


@dataclass(slots=True)
class ExtractedData:
    url: str
    schema_used: dict[str, Any]
    data: dict[str, Any] | list[dict[str, Any]]
    extracted_at: datetime


@dataclass(slots=True)
class DownloadResult:
    success: bool
    save_path: str
    filename: str
    size_bytes: int


@dataclass(slots=True)
class OperationResult:
    success: bool
    message: str
    data: dict[str, Any] = field(default_factory=dict)
