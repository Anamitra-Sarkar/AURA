"""NEXUS top-level orchestrator agent."""

from __future__ import annotations

from typing import Any

from aura.core.agent_base import BaseAgent
from aura.core.multiagent.orchestrator import NexusOrchestrator


class NexusAgent(BaseAgent):
    def __init__(self, orchestrator: NexusOrchestrator) -> None:
        super().__init__("nexus", "NEXUS", "Central orchestrator", ["routing", "orchestration"])
        self.orchestrator = orchestrator

    async def handle(self, instruction: str, context: dict[str, Any] | None = None) -> Any:
        ctx = context or {}
        return await self.orchestrator.handle(instruction, ctx.get('user_id', 'local'), ctx, ctx.get('importance', 2))
