from __future__ import annotations

import asyncio
from typing import Any

from aura.core.agent_base import BaseAgent
from . import tools


class AegisAgent(BaseAgent):
    def __init__(self) -> None:
        super().__init__('aegis', 'AEGIS', 'System monitoring and control', ['system_monitor', 'process_management', 'shell_execution', 'clipboard', 'screenshot'])

    async def handle(self, instruction: str, context: dict[str, Any] | None = None) -> Any:
        lowered = instruction.lower()
        if 'kill' in lowered or 'process' in lowered:
            return await asyncio.to_thread(tools.kill_process, instruction, False)
        if 'shell' in lowered or 'command' in lowered:
            return await asyncio.to_thread(tools.run_shell_command, instruction, 30, None)
        return await asyncio.to_thread(tools.get_system_info)
