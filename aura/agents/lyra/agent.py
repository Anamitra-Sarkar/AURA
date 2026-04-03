from __future__ import annotations

import asyncio
from typing import Any

from aura.core.agent_base import BaseAgent
from . import tools


class LyraAgent(BaseAgent):
    def __init__(self) -> None:
        super().__init__('lyra', 'LYRA', 'Voice input and output', ['speech_to_text', 'text_to_speech', 'wake_word', 'voice_command'])

    async def handle(self, instruction: str, context: dict[str, Any] | None = None) -> Any:
        ctx = context or {}
        if ctx.get('mode', 'speak') == 'listen':
            return await asyncio.to_thread(tools.listen_once, ctx.get('timeout_seconds', 10), ctx.get('noise_reduction', True))
        return await asyncio.to_thread(tools.speak, instruction, ctx.get('interrupt_if_speaking', True))
