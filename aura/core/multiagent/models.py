"""A2A and orchestrator data models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass(slots=True)
class AgentCard:
    id: str
    name: str
    description: str
    capabilities: list[str]
    endpoint: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    version: str


@dataclass(slots=True)
class A2ATask:
    task_id: str
    from_agent: str
    to_agent: str
    instruction: str
    context: dict[str, Any]
    priority: int = 2
    callback_url: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    status: str = "pending"
    result: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class AgentResult:
    task_id: str
    agent_id: str
    output: str
    structured_output: dict[str, Any]
    tokens_used: int
    latency_ms: int
    success: bool
    error: str = ""


@dataclass(slots=True)
class OrchestratorResult:
    response: str
    agents_used: list[str] = field(default_factory=list)
    tools_called: list[str] = field(default_factory=list)
    reasoning_used: bool = False
    ensemble_used: bool = False
    tokens_used: int = 0
