"""A2A dispatcher."""

from __future__ import annotations

import asyncio
import inspect
import time
from typing import Any

from .models import A2ATask, AgentResult
from .registry import AgentRegistry


class A2ADispatcher:
    """Dispatch tasks to registered agents."""

    def __init__(self, registry: AgentRegistry | None = None) -> None:
        self.registry = registry or AgentRegistry()

    async def dispatch(self, task: A2ATask) -> AgentResult:
        start = time.perf_counter()
        card = self.registry.get(task.to_agent)
        handler = self._handler_for(card.id)
        result = await self._invoke(card.id, handler, task)
        output = result if isinstance(result, str) else str(result)
        return AgentResult(
            task_id=task.task_id,
            agent_id=card.id,
            output=output,
            structured_output={"result": output} if not isinstance(result, dict) else result,
            tokens_used=max(1, len(output.split())),
            latency_ms=int((time.perf_counter() - start) * 1000),
            success=True,
        )

    async def dispatch_parallel(self, tasks: list[A2ATask]) -> list[AgentResult]:
        return await asyncio.gather(*(self.dispatch(task) for task in tasks))

    def _handler_for(self, agent_id: str) -> Any:
        if agent_id == "iris":
            from aura.agents.iris import tools as iris_tools

            return iris_tools.deep_research if "research" in agent_id else iris_tools.web_search
        if agent_id == "atlas":
            from aura.agents.atlas import tools as atlas_tools

            return atlas_tools.read_file
        if agent_id == "logos":
            from aura.agents.logos import tools as logos_tools

            return logos_tools.run_code
        if agent_id == "echo":
            from aura.agents.echo import tools as echo_tools

            return echo_tools.set_reminder
        if agent_id == "mneme":
            from aura.memory import save_memory

            return save_memory
        if agent_id == "hermes":
            from aura.browser.hermes import tools as hermes_tools

            return hermes_tools.open_url
        if agent_id == "aegis":
            from aura.agents.aegis import tools as aegis_tools

            return aegis_tools.get_system_info
        if agent_id == "director":
            from aura.agents.director import tools as director_tools

            return director_tools.plan_workflow
        if agent_id == "phantom":
            from aura.agents.phantom import tools as phantom_tools

            return phantom_tools.list_workflows
        if agent_id == "ensemble":
            from aura.agents.ensemble import tools as ensemble_tools

            return ensemble_tools.ensemble_answer
        if agent_id == "oracle_deep":
            from aura.agents.oracle_deep import tools as oracle_tools

            return oracle_tools.analyze_decision
        if agent_id == "lyra":
            from aura.agents.lyra import tools as lyra_tools

            return lyra_tools.speak
        if agent_id == "stream":
            from aura.agents.stream import tools as stream_tools

            return stream_tools.fetch_stream
        if agent_id == "mosaic":
            from aura.agents.mosaic import tools as mosaic_tools

            return mosaic_tools.synthesize
        raise KeyError(agent_id)

    async def _invoke(self, agent_id: str, handler: Any, task: A2ATask) -> Any:
        kwargs = task.context.copy()
        instruction = task.instruction
        if agent_id == "iris":
            kwargs.setdefault("query", instruction)
        elif agent_id == "atlas":
            kwargs.setdefault("path", instruction)
        elif agent_id == "logos":
            kwargs.setdefault("code", instruction)
            kwargs.setdefault("language", "python")
        elif agent_id == "echo":
            kwargs.setdefault("text", instruction)
            kwargs.setdefault("trigger_time", "now")
        elif agent_id == "mneme":
            kwargs.setdefault("key", f"a2a:{task.task_id}")
            kwargs.setdefault("value", instruction)
            kwargs.setdefault("category", "general")
        elif agent_id == "hermes":
            kwargs.setdefault("url", instruction)
        elif agent_id == "director":
            kwargs.setdefault("instruction", instruction)
        elif agent_id == "ensemble":
            kwargs.setdefault("task", instruction)
        elif agent_id == "oracle_deep":
            kwargs.setdefault("question", instruction)
        elif agent_id == "lyra":
            kwargs.setdefault("text", instruction)
        elif agent_id == "stream":
            kwargs.setdefault("source_id", None)
        elif agent_id == "mosaic":
            kwargs.setdefault("task", instruction)
            kwargs.setdefault("sources", [])
        result = handler(**kwargs)
        if inspect.isawaitable(result):
            result = await result
        return result
