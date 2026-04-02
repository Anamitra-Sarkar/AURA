"""Data models for PHANTOM background automation."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(slots=True)
class PhantomTask:
    id: str
    name: str
    description: str
    schedule: str
    last_run: datetime | None
    next_run: datetime | None
    enabled: bool
    handler_function: str
    config: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class WatchTarget:
    id: str
    name: str
    type: str
    target: str
    check_interval_minutes: int
    last_checked: datetime | None
    last_hash: str
    on_change_action: str
    on_change_config: dict[str, Any] = field(default_factory=dict)
    enabled: bool = True


@dataclass(slots=True)
class Briefing:
    generated_at: datetime
    date: str
    meetings_today: list[Any]
    pending_tasks: list[str]
    new_assignments: list[str]
    arxiv_papers: list[Any]
    github_events: list[str]
    system_health: Any
    summary_text: str
