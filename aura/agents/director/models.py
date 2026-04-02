"""Data models for DIRECTOR workflow orchestration."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(slots=True)
class WorkflowStep:
    id: str
    name: str
    description: str
    tool_name: str
    tool_args: dict[str, Any]
    depends_on: list[str]
    status: str
    result: dict[str, Any] = field(default_factory=dict)
    error: str = ""
    started_at: datetime | None = None
    completed_at: datetime | None = None
    retry_count: int = 0
    max_retries: int = 0
    requires_approval: bool = False
    tier: int = 1
    optional: bool = False


@dataclass(slots=True)
class WorkflowPlan:
    id: str
    name: str
    description: str
    original_instruction: str
    steps: list[WorkflowStep]
    status: str
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    context: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ExecutionEvent:
    workflow_id: str
    step_id: str
    event_type: str
    message: str
    timestamp: datetime
    data: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ExecutionReport:
    workflow_id: str
    total_steps: int
    completed_steps: int
    failed_steps: int
    skipped_steps: int
    duration_seconds: float
    events: list[ExecutionEvent]
    final_status: str
