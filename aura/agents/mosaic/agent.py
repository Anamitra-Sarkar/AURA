from __future__ import annotations

from typing import Any

from aura.core.agent_base import BaseAgent
from . import tools


class MosaicAgent(BaseAgent):
    def __init__(self) -> None:
        super().__init__('mosaic', 'MOSAIC', 'Multi-source synthesis', ['multi_source_synthesis', 'code_merge', 'source_diff', 'citation'])

    async def handle(self, instruction: str, context: dict[str, Any] | None = None) -> Any:
        ctx = context or {}
        sources = ctx.get('sources', [])
        return await tools.synthesize(instruction, sources, ctx.get('output_format', 'markdown'), ctx.get('max_length'))
