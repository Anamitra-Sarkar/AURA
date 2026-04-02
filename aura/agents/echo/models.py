"""Data models for ECHO."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class Event:
    """Calendar event data."""

    id: str
    title: str
    start: str
    end: str
    attendees: list[str]
    platform: str
    description: str
    provider: str
    meeting_link: str
    created_at: str


@dataclass(slots=True)
class Reminder:
    """Reminder data."""

    id: str
    text: str
    trigger_time: str
    repeat: str | None
    active: bool
    created_at: str


@dataclass(slots=True)
class EmailDraft:
    """Email draft data."""

    id: str
    to: list[str]
    subject: str
    body: str
    attachments: list[str] = field(default_factory=list)
    created_at: str = ""


@dataclass(slots=True)
class OperationResult:
    """Result from an ECHO operation."""

    success: bool
    message: str
    data: dict[str, Any] | None = None
