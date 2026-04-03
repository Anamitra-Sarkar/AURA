from __future__ import annotations

import asyncio
from typing import Any

from aura.core.agent_base import BaseAgent
from . import tools


class PhantomAgent(BaseAgent):
    def __init__(self) -> None:
        super().__init__('phantom', 'PHANTOM', 'Background autopilot', ['background_tasks', 'file_watch', 'scheduled_tasks', 'auto_recovery'])

    async def handle(self, instruction: str, context: dict[str, Any] | None = None) -> Any:
        return await asyncio.to_thread(tools.list_workflows)
