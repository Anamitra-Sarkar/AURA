from __future__ import annotations

from typing import Any

from aura.core.agent_base import BaseAgent
from . import tools


class StreamAgent(BaseAgent):
    def __init__(self) -> None:
        super().__init__('stream', 'STREAM', 'World awareness feeds', ['arxiv_watch', 'github_watch', 'rss_fetch', 'daily_digest'])

    async def handle(self, instruction: str, context: dict[str, Any] | None = None) -> Any:
        ctx = context or {}
        if ctx.get('mode', 'fetch') == 'digest':
            return tools.generate_daily_digest(ctx.get('date'))
        return await tools.fetch_stream(ctx.get('source_id'))
