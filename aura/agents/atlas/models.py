"""Data models for ATLAS."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class FileMatch:
    """A file search match."""

    path: str
    snippet: str
    score: float
    modified_date: str


@dataclass(slots=True)
class FileContent:
    """Structured file content."""

    path: str
    content: str
    encoding: str
    size_bytes: int
    modified_date: str
    file_type: str


@dataclass(slots=True)
class FileEntry:
    """A directory entry."""

    path: str
    name: str
    size_bytes: int
    modified_date: str
    is_dir: bool
    extension: str


@dataclass(slots=True)
class OperationResult:
    """Result from an Atlas file operation."""

    success: bool
    message: str
    data: dict[str, Any] | None = field(default=None)


@dataclass(slots=True)
class WatchHandle:
    """Handle for a folder watch."""

    watch_id: str
    path: str
    active: bool
