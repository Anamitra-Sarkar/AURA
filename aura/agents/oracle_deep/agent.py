from __future__ import annotations

from typing import Any

from aura.core.agent_base import BaseAgent
from . import tools


class OracleDeepAgent(BaseAgent):
    def __init__(self) -> None:
        super().__init__('oracle_deep', 'ORACLE DEEP', 'Deep causal reasoning', ['reasoning_chain', 'causal_analysis', 'what_if_scenario', 'devil_advocate'])

    async def handle(self, instruction: str, context: dict[str, Any] | None = None) -> Any:
        ctx = context or {}
        if ctx.get('mode', 'analyze') == 'what_if':
            return await tools.what_if_scenario(instruction, ctx.get('base_state'), ctx.get('time_horizons'))
        return await tools.analyze_decision(instruction, ctx.get('context'), ctx.get('use_iris', True))
