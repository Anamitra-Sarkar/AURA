from __future__ import annotations

from typing import Any

from aura.core.agent_base import BaseAgent
from . import tools


class EchoAgent(BaseAgent):
    def __init__(self) -> None:
        super().__init__('echo', 'ECHO', 'Calendar and communication assistant', ['calendar', 'reminders', 'meetings', 'email_draft', 'schedule'])

    async def handle(self, instruction: str, context: dict[str, Any] | None = None) -> Any:
        ctx = context or {}
        if 'meeting' in instruction.lower():
            return tools.create_meeting(ctx.get('title', instruction), ctx.get('start', ''), ctx.get('end', ''), ctx.get('attendees', []), ctx.get('platform', 'google'))
        if 'email' in instruction.lower():
            return tools.draft_email(ctx.get('to', []), ctx.get('subject', instruction), ctx.get('body', instruction), ctx.get('attachments', []))
        return tools.set_reminder(instruction, ctx.get('trigger_time', 'now'), ctx.get('repeat'))
