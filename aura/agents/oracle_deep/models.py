"""Data models for ORACLE DEEP."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone


def _uuid() -> str:
    return str(uuid.uuid4())


@dataclass(slots=True)
class ReasoningStep:
    id: str = field(default_factory=_uuid)
    description: str = ""
    evidence: list[str] = field(default_factory=list)
    assumption: bool = False
    confidence: float = 0.0
    confidence_reason: str = ""


@dataclass(slots=True)
class ReasoningChain:
    steps: list[ReasoningStep] = field(default_factory=list)
    conclusion: str = ""
    overall_confidence: float = 0.0
    weakest_link_id: str = ""


@dataclass(slots=True)
class CounterArgument:
    argument: str = ""
    strength: float = 0.0
    evidence: list[str] = field(default_factory=list)
    rebuttal: str = ""


@dataclass(slots=True)
class ReasoningReport:
    id: str = field(default_factory=_uuid)
    question: str = ""
    chain: ReasoningChain = field(default_factory=ReasoningChain)
    conclusion: str = ""
    confidence: float = 0.0
    counter_argument: CounterArgument = field(default_factory=CounterArgument)
    uncertainty_flags: list[str] = field(default_factory=list)
    evidence_sources: list[str] = field(default_factory=list)
    generated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass(slots=True)
class ScenarioOutcome:
    description: str = ""
    probability: float = 0.0
    confidence: float = 0.0
    supporting_evidence: list[str] = field(default_factory=list)
    time_horizon: str = ""


@dataclass(slots=True)
class ScenarioAnalysis:
    id: str = field(default_factory=_uuid)
    change_description: str = ""
    base_state: str = ""
    outcomes: list[ScenarioOutcome] = field(default_factory=list)
    best_case: ScenarioOutcome = field(default_factory=ScenarioOutcome)
    worst_case: ScenarioOutcome = field(default_factory=ScenarioOutcome)
    most_likely: ScenarioOutcome = field(default_factory=ScenarioOutcome)
    recommendation: str = ""
    confidence: float = 0.0
