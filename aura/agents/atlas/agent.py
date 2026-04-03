from __future__ import annotations

import asyncio
from typing import Any

from aura.core.agent_base import BaseAgent
from . import tools


class AtlasAgent(BaseAgent):
    def __init__(self) -> None:
        super().__init__('atlas', 'ATLAS', 'Filesystem operations', ['file_read', 'file_write', 'file_search', 'file_move', 'folder_watch'])

    async def handle(self, instruction: str, context: dict[str, Any] | None = None) -> Any:
        ctx = context or {}
        action = ctx.get('action', 'read')
        if action == 'search':
            return await asyncio.to_thread(tools.search_files, instruction, ctx.get('root_path', '.'), ctx.get('mode', 'keyword'))
        if action == 'write':
            return await asyncio.to_thread(tools.write_file, ctx['path'], ctx.get('content', instruction), ctx.get('mode', 'overwrite'))
        if action == 'move':
            return await asyncio.to_thread(tools.move_file, ctx['src'], ctx['dst'])
        return await asyncio.to_thread(tools.read_file, ctx.get('path', instruction), ctx.get('max_bytes'))
