"""Minimal async ReAct loop for AURA."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable

from .event_bus import EventBus
from .llm_router import OllamaRouter
from .tools import ToolCallResult, ToolRegistry


@dataclass(slots=True)
class AgentLoopResult:
    """Structured result from a ReAct loop run."""

    ok: bool
    answer: str | None = None
    steps: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None


class ReActAgentLoop:
    """Reason, act, observe, and repeat with tool usage."""

    def __init__(self, router: OllamaRouter, registry: ToolRegistry, event_bus: EventBus | None = None, max_steps: int = 4, confirm_tier3: Callable[[str, dict[str, Any]], bool] | None = None) -> None:
        self.router = router
        self.registry = registry
        self.event_bus = event_bus
        self.max_steps = max_steps
        self.confirm_tier3 = confirm_tier3 or (lambda _tool, _args: False)

    async def run(self, user_message: str) -> AgentLoopResult:
        """Run the loop until a final answer is produced."""

        messages = [
            {"role": "system", "content": self._system_prompt()},
            {"role": "user", "content": user_message},
        ]
        steps: list[dict[str, Any]] = []
        for _ in range(self.max_steps):
            model_result = await self.router.chat(messages)
            if not model_result.ok or model_result.content is None:
                return AgentLoopResult(ok=False, error=model_result.error or "model-error", steps=steps)
            parsed = self._parse_response(model_result.content)
            if parsed.get("type") == "final":
                return AgentLoopResult(ok=True, answer=str(parsed.get("response", "")), steps=steps)
            if parsed.get("type") != "tool":
                return AgentLoopResult(ok=True, answer=model_result.content, steps=steps)
            tool_name = str(parsed.get("tool", ""))
            arguments = parsed.get("arguments") or {}
            tier = 0
            try:
                tool_spec = self.registry.get(tool_name)
                tier = tool_spec.tier
            except KeyError:
                return AgentLoopResult(ok=False, error=f"unknown-tool:{tool_name}", steps=steps)
            if tier >= 3 and not self.confirm_tier3(tool_name, arguments):
                return AgentLoopResult(ok=False, error="tier-3-confirmation-required", steps=steps)
            tool_result = await self.registry.execute(tool_name, arguments, confirm=True)
            steps.append({"tool": tool_name, "arguments": arguments, "result": self._tool_result_dict(tool_result)})
            if self.event_bus is not None:
                await self.event_bus.publish("agent.tool", {"tool": tool_name, "result": self._tool_result_dict(tool_result)})
            if not tool_result.ok:
                return AgentLoopResult(ok=False, error=tool_result.error, steps=steps)
            messages.append({"role": "assistant", "content": model_result.content})
            messages.append({"role": "tool", "content": json.dumps(self._tool_result_dict(tool_result), ensure_ascii=True)})
        return AgentLoopResult(ok=False, error="max-steps-exceeded", steps=steps)

    def _system_prompt(self) -> str:
        tools = [
            {
                "name": spec.name,
                "description": spec.description,
                "tier": spec.tier,
                "arguments": spec.arguments_schema,
                "returns": spec.return_schema,
            }
            for spec in self.registry.list_tools()
        ]
        return json.dumps({"instructions": "Respond with JSON: {type: 'tool'|'final', ...}", "tools": tools}, ensure_ascii=True)

    @staticmethod
    def _parse_response(content: str) -> dict[str, Any]:
        try:
            parsed = json.loads(content)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass
        return {"type": "final", "response": content}

    @staticmethod
    def _tool_result_dict(result: ToolCallResult) -> dict[str, Any]:
        return {
            "ok": result.ok,
            "tool": result.tool,
            "tier": result.tier,
            "result": result.result,
            "error": result.error,
            "metadata": result.metadata,
        }
