from __future__ import annotations

from typing import Any

from aura.core.agent_base import BaseAgent
from . import tools


class EnsembleAgent(BaseAgent):
    def __init__(self) -> None:
        super().__init__('ensemble', 'ENSEMBLE', 'Parallel multi-model debate', ['multi_model_debate', 'consensus', 'parallel_inference'])

    async def handle(self, instruction: str, context: dict[str, Any] | None = None) -> Any:
        ctx = context or {}
        return await tools.ensemble_answer(instruction, ctx.get('importance_level', 2), ctx.get('models'), ctx.get('context'))
