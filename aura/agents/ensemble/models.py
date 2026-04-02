"""Data models for the ENSEMBLE debate engine."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum


@dataclass(slots=True)
class ModelResponse:
    """Response from one model in the debate."""

    model_name: str
    response: str
    latency_ms: int
    token_count: int
    error: str | None = None


@dataclass(slots=True)
class EnsembleResult:
    """Structured output from an ensemble debate."""

    task: str
    responses: list[ModelResponse]
    agreements: list[str] = field(default_factory=list)
    disagreements: list[str] = field(default_factory=list)
    synthesized_answer: str = ""
    confidence_score: float = 0.0
    reasoning: str = ""
    models_used: list[str] = field(default_factory=list)
    models_failed: list[str] = field(default_factory=list)
    judge_model: str = ""
    total_latency_ms: int = 0


class ImportanceLevel(IntEnum):
    """Importance levels used to decide when ENSEMBLE should engage."""

    LOW = 1
    MEDIUM = 2
    HIGH = 3
    CRITICAL = 4
