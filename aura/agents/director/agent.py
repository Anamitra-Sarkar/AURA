from __future__ import annotations

from typing import Any

from aura.core.agent_base import BaseAgent
from . import tools


class DirectorAgent(BaseAgent):
    def __init__(self) -> None:
        super().__init__('director', 'DIRECTOR', 'Autonomous workflow orchestration', ['workflow_plan', 'workflow_execute', 'workflow_pause', 'workflow_approve'])

    async def handle(self, instruction: str, context: dict[str, Any] | None = None) -> Any:
        ctx = context or {}
        action = ctx.get('action', 'plan')
        if action == 'execute':
            plan = tools.plan_workflow(instruction, ctx)
            return await tools.execute_workflow(plan.id)
        if action == 'pause':
            return tools.pause_workflow(ctx['workflow_id'])
        if action == 'resume':
            return await tools.resume_workflow(ctx['workflow_id'])
        return tools.plan_workflow(instruction, ctx)
