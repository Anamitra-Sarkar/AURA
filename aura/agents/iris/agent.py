from __future__ import annotations

import asyncio
from typing import Any

from aura.core.agent_base import BaseAgent
from . import tools


class IrisAgent(BaseAgent):
    def __init__(self) -> None:
        super().__init__('iris', 'IRIS', 'Research and web intelligence', ['web_search', 'fact_check', 'research', 'fetch_url', 'deep_research'])

    async def handle(self, instruction: str, context: dict[str, Any] | None = None) -> Any:
        query = (context or {}).get('query', instruction)
        if 'http' in query or query.endswith('.html'):
            return await asyncio.to_thread(tools.fetch_url, query)
        if any(word in instruction.lower() for word in ['deep', 'research', 'compare', 'synthesize']):
            return await asyncio.to_thread(tools.deep_research, query)
        return await asyncio.to_thread(tools.web_search, query)
