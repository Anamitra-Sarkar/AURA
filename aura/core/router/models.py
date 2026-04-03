"""Router data models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(slots=True)
class ProviderStatus:
    name: str
    available: bool
    requests_remaining: int
    tokens_remaining: int
    reset_at: datetime
    last_error: str = ""
    last_success: datetime | None = None


@dataclass(slots=True)
class ModelProfile:
    provider: str
    model_id: str
    context_length: int
    speed_tier: str
    capability_tags: list[str] = field(default_factory=list)
    tokens_per_day_limit: int = 0
    requests_per_minute: int = 0
    is_free: bool = True


@dataclass(slots=True)
class RouterDecision:
    task: str
    importance: int
    selected_provider: str
    selected_model: str
    fallback_chain: list[str] = field(default_factory=list)
    rationale: str = ""
    task_tags: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ProviderCall:
    provider: str
    model: str
    prompt: str
    response: str
    tokens_used: int
    latency_ms: int
    success: bool
    error: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.success

    @property
    def content(self) -> str:
        return self.response


class RouterError(RuntimeError):
    """Base router error."""


class RateLimitError(RouterError):
    """Raised when a provider is rate limited."""


class ProviderUnavailableError(RouterError):
    """Raised when a provider cannot be reached."""


class AllProvidersExhaustedError(RouterError):
    """Raised when no provider can satisfy a request."""
