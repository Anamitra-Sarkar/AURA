from __future__ import annotations

import asyncio
from typing import Any

from aura.core.agent_base import BaseAgent
from aura.memory import save_memory, recall_memory, list_memories


class MnemeAgent(BaseAgent):
    def __init__(self) -> None:
        super().__init__('mneme', 'MNEME', 'Persistent memory and recall', ['memory_save', 'memory_recall', 'context_inject', 'memory_consolidate'])

    async def handle(self, instruction: str, context: dict[str, Any] | None = None) -> Any:
        ctx = context or {}
        action = ctx.get('action', 'save')
        if action == 'recall':
            return await asyncio.to_thread(recall_memory, instruction, ctx.get('top_k', 5), ctx.get('category_filter'))
        if action == 'list':
            return await asyncio.to_thread(list_memories, ctx.get('category'), ctx.get('tag_filter'), ctx.get('limit', 20))
        return await asyncio.to_thread(save_memory, ctx.get('key', 'note'), instruction, ctx.get('category', 'general'), ctx.get('tags', []), ctx.get('source', 'mneme'), ctx.get('confidence', 1.0))
