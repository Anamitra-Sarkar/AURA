"""Top-level NEXUS orchestrator."""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from typing import Any

from ..router.smart_router import SmartRouter
from .dispatcher import A2ADispatcher
from .models import A2ATask, OrchestratorResult
from .registry import AgentRegistry


@dataclass(slots=True)
class _MemoryHooks:
    inject_context: Any
    auto_extract: Any


class NexusOrchestrator:
    """Classify user intent and coordinate agents."""

    def __init__(self, smart_router: SmartRouter, dispatcher: A2ADispatcher | None = None, registry: AgentRegistry | None = None) -> None:
        self.smart_router = smart_router
        self.dispatcher = dispatcher or A2ADispatcher(registry or AgentRegistry())
        self.registry = registry or AgentRegistry()

    async def handle(self, message: str, user_id: str, context: dict[str, Any], importance: int = 2) -> OrchestratorResult:
        from aura import memory as memory_module

        if callable(getattr(memory_module, "inject_context", None)):
            await asyncio.to_thread(memory_module.inject_context, f"{user_id}:{message}")
        lowered = message.lower()
        selected_agent = self._select_agent(lowered)
        if selected_agent == "general":
            call = await self.smart_router.complete(message, [{"role": "user", "content": message}], importance=importance)
            response = call.response
            result = OrchestratorResult(response=response, agents_used=["router"], tools_called=[], reasoning_used=False, ensemble_used=False, tokens_used=call.tokens_used)
        elif selected_agent == "director":
            plan = await self.dispatcher.dispatch(A2ATask(task_id=str(uuid.uuid4()), from_agent="director", to_agent="director", instruction=message, context=context, priority=importance))
            response = plan.output
            result = OrchestratorResult(response=response, agents_used=["director"], tools_called=[], reasoning_used=False, ensemble_used=False, tokens_used=plan.tokens_used)
        else:
            task = A2ATask(task_id=str(uuid.uuid4()), from_agent="director", to_agent=selected_agent, instruction=message, context=context, priority=importance)
            agent_result = await self.dispatcher.dispatch(task)
            response = agent_result.output
            result = OrchestratorResult(response=response, agents_used=[selected_agent], tools_called=[], reasoning_used=selected_agent == "oracle_deep", ensemble_used=selected_agent == "ensemble", tokens_used=agent_result.tokens_used)
        if callable(getattr(memory_module, "auto_extract_memories", None)):
            try:
                await memory_module.auto_extract_memories(message, result.response)
            except Exception:
                pass
        return result

    def _select_agent(self, message: str) -> str:
        if "complex" in message or ("research" in message and ("write" in message or "save" in message)):
            return "director"
        if any(phrase in message for phrase in ["find file", "open", "read"]):
            return "atlas"
        if any(phrase in message for phrase in ["search", "research", "find info"]):
            return "iris"
        if any(phrase in message for phrase in ["code", "script", "implement"]):
            return "logos"
        if any(phrase in message for phrase in ["schedule", "remind", "meeting"]):
            return "echo"
        if any(phrase in message for phrase in ["browse", "open website", "fill"]):
            return "hermes"
        if any(phrase in message for phrase in ["analyze", "reason", "decide"]):
            return "oracle_deep"
        if any(phrase in message for phrase in ["create", "write", "generate"]):
            return "mosaic"
        return "general"
