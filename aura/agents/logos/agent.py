from __future__ import annotations

import asyncio
from typing import Any

from aura.core.agent_base import BaseAgent
from . import tools


class LogosAgent(BaseAgent):
    def __init__(self) -> None:
        super().__init__('logos', 'LOGOS', 'Code execution and debugging', ['code_execution', 'code_generation', 'apply_patch', 'git_operations'])

    async def handle(self, instruction: str, context: dict[str, Any] | None = None) -> Any:
        ctx = context or {}
        if ctx.get('language'):
            return await asyncio.to_thread(tools.run_code, instruction, ctx.get('language', 'python'), ctx.get('context_dir'))
        return await asyncio.to_thread(tools.generate_code, instruction, ctx.get('language', 'python'), ctx.get('context_files'))
