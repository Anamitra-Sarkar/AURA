from __future__ import annotations

import asyncio
from typing import Any

from aura.browser.hermes import tools
from aura.core.agent_base import BaseAgent


class HermesAgent(BaseAgent):
    def __init__(self) -> None:
        super().__init__('hermes', 'HERMES', 'Browser automation', ['browser_navigate', 'fill_form', 'click', 'screenshot', 'scrape', 'download'])

    async def handle(self, instruction: str, context: dict[str, Any] | None = None) -> Any:
        ctx = context or {}
        action = ctx.get('action', 'open_url')
        if action == 'click':
            return await asyncio.to_thread(tools.click, ctx['page_id'], ctx.get('selector'), ctx.get('description'))
        if action == 'fill_form':
            return await asyncio.to_thread(tools.fill_form, ctx['page_id'], ctx.get('fields', []))
        if action == 'screenshot':
            return await asyncio.to_thread(tools.take_screenshot, ctx.get('page_id'), ctx.get('region'), ctx.get('save_path'))
        if action == 'download':
            return await asyncio.to_thread(tools.download_file, ctx['page_id'], ctx.get('selector_or_url', instruction), ctx.get('save_path', 'download.bin'))
        return await asyncio.to_thread(tools.open_url, instruction, ctx.get('check_safety', True), ctx.get('wait_for', 'load'))
