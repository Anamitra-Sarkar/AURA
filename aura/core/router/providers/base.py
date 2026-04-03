"""Common provider client protocol and helpers."""

from __future__ import annotations

from typing import Protocol

from ..models import ProviderCall


class ProviderClient(Protocol):
    async def complete(self, model_id: str, messages: list[dict[str, object]], max_tokens: int, temperature: float, tools: list[dict[str, object]] | None) -> ProviderCall: ...
