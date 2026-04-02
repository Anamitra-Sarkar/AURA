"""Data models for LYRA voice I/O."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(slots=True)
class TranscriptionResult:
    text: str
    language: str
    confidence: float
    duration_seconds: float
    segments: list[dict[str, Any]] = field(default_factory=list)


@dataclass(slots=True)
class SpeechConfig:
    voice_id: str = ""
    rate: int = 175
    volume: float = 0.9
    language: str = "en"


@dataclass(slots=True)
class WakeWordConfig:
    phrase: str = "hey aura"
    sensitivity: float = 0.5
    engine: str = "energy_threshold"


@dataclass(slots=True)
class ListenResult:
    triggered_by: str
    transcription: TranscriptionResult
    timestamp: datetime


@dataclass(slots=True)
class OperationResult:
    ok: bool
    message: str
    details: dict[str, Any] = field(default_factory=dict)
