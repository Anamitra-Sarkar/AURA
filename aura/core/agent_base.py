"""Base classes for AURA agents."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class BaseAgent(ABC):
    """Common interface for all AURA agents."""

    agent_id: str
    name: str
    description: str
    capabilities: list[str] = field(default_factory=list)

    @abstractmethod
    async def handle(self, instruction: str, context: dict[str, Any] | None = None) -> Any:
        """Handle a natural-language instruction."""

