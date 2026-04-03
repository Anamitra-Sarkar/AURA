"""Minimal async ReAct loop for AURA."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import Any, Callable

from .event_bus import EventBus
from .config import load_config
from .llm_router import OllamaRouter
from .tools import ToolCallResult, ToolRegistry

try:
    from aura.memory import inject_context, auto_extract_memories
except Exception:  # pragma: no cover - memory package may not be available in minimal installs
    inject_context = None  # type: ignore[assignment]
    auto_extract_memories = None  # type: ignore[assignment]


@dataclass(slots=True)
class AgentLoopResult:
    """Structured result from a ReAct loop run."""

    ok: bool
    answer: str | None = None
    steps: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None
    used_ensemble: bool = False
    tools_called: list[str] = field(default_factory=list)
    reasoning_used: bool = False


@dataclass(slots=True)
class _ModelTurn:
    ok: bool
    content: str | None
    error: str | None
    used_ensemble: bool = False


class ReActAgentLoop:
    """Reason, act, observe, and repeat with tool usage."""

    def __init__(self, router: OllamaRouter, registry: ToolRegistry, event_bus: EventBus | None = None, max_steps: int = 4, confirm_tier3: Callable[[str, dict[str, Any]], bool] | None = None, orchestrator: Any | None = None) -> None:
        self.router = router
        self.registry = registry
        self.event_bus = event_bus
        self.max_steps = max_steps
        self.confirm_tier3 = confirm_tier3 or (lambda _tool, _args: False)
        self._config = load_config()
        self.orchestrator = orchestrator

    async def run(self, user_message: str, importance: int | None = None) -> AgentLoopResult:
        """Run the loop until a final answer is produced."""

        memory_context = ""
        if inject_context is not None:
            try:
                memory_context = inject_context(user_message)
            except Exception:
                memory_context = ""
        messages = [
            {"role": "system", "content": self._system_prompt(memory_context)},
            {"role": "user", "content": user_message},
        ]
        steps: list[dict[str, Any]] = []
        for _ in range(self.max_steps):
            model_result = await self._model_call(messages, user_message, importance)
            if not model_result.ok or model_result.content is None:
                return AgentLoopResult(ok=False, error=model_result.error or "model-error", steps=steps, used_ensemble=model_result.used_ensemble)
            parsed = self._parse_response(model_result.content)
            if parsed.get("type") == "final":
                answer = str(parsed.get("response", ""))
                await self._maybe_voice_response(answer)
                return AgentLoopResult(ok=True, answer=answer, steps=steps, used_ensemble=model_result.used_ensemble, tools_called=[step["tool"] for step in steps], reasoning_used=self._reasoning_used(steps))
            if parsed.get("type") != "tool":
                answer = model_result.content
                await self._maybe_voice_response(answer)
                return AgentLoopResult(ok=True, answer=answer, steps=steps, used_ensemble=model_result.used_ensemble, tools_called=[step["tool"] for step in steps], reasoning_used=self._reasoning_used(steps))
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
                return AgentLoopResult(ok=False, error=tool_result.error, steps=steps, used_ensemble=model_result.used_ensemble, tools_called=[step["tool"] for step in steps], reasoning_used=self._reasoning_used(steps))
            messages.append({"role": "assistant", "content": model_result.content})
            messages.append({"role": "tool", "content": json.dumps(self._tool_result_dict(tool_result), ensure_ascii=True)})
            if auto_extract_memories is not None:
                asyncio.create_task(self._extract_memories(user_message, model_result.content))
        return AgentLoopResult(ok=False, error="max-steps-exceeded", steps=steps, tools_called=[step["tool"] for step in steps], reasoning_used=self._reasoning_used(steps))

    async def handle_message(self, user_message: str, importance: int | None = None) -> dict[str, Any]:
        """Compatibility wrapper returning a UI-friendly result."""

        if self.orchestrator is not None:
            result = await self.orchestrator.handle(user_message, "local", {}, importance or 2)
            return {
                "response": result.response,
                "used_ensemble": result.ensemble_used,
                "tools_called": result.tools_called,
                "reasoning_used": result.reasoning_used,
            }
        result = await self.run(user_message, importance=importance)
        return {
            "response": result.answer or result.error or "",
            "used_ensemble": result.used_ensemble,
            "tools_called": result.tools_called,
            "reasoning_used": result.reasoning_used,
        }

    async def _model_call(self, messages: list[dict[str, Any]], user_message: str, importance: int | None = None) -> _ModelTurn:
        importance = importance if importance is not None else self._importance_level(user_message)
        ensemble = getattr(self._config, "ensemble", None)
        if ensemble is not None and ensemble.enabled and importance >= ensemble.default_importance_threshold:
            from aura.agents.ensemble.tools import ensemble_answer

            prompt = json.dumps(messages, ensure_ascii=True)
            result = await ensemble_answer(prompt, importance_level=importance, models=ensemble.models, context=None)
            return _ModelTurn(ok=True, content=result.synthesized_answer, error=None, used_ensemble=True)
        result = await self.router.chat(messages)
        return _ModelTurn(ok=result.ok, content=result.content, error=result.error, used_ensemble=False)

    async def _extract_memories(self, user_message: str, response: str) -> None:
        """Extract memories in the background without blocking the response."""

        if auto_extract_memories is None:
            return
        try:
            await auto_extract_memories(user_message, response)
        except Exception:
            return

    async def _maybe_voice_response(self, answer: str) -> None:
        lyra_config = getattr(self._config, "lyra", None)
        if lyra_config is None or not lyra_config.enabled or not lyra_config.voice_mode:
            return
        try:
            from aura.agents.lyra.tools import listen_once, speak, strip_markdown

            spoken = strip_markdown(answer)
            await asyncio.to_thread(speak, spoken)
            await asyncio.to_thread(listen_once)
        except Exception:
            return

    def _system_prompt(self, memory_context: str = "") -> str:
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
        payload = {"instructions": "Respond with JSON: {type: 'tool'|'final', ...}", "tools": tools}
        if memory_context:
            payload["memory_context"] = memory_context
        return json.dumps(payload, ensure_ascii=True)

    @staticmethod
    def _importance_level(message: str) -> int:
        lowered = message.lower()
        if any(keyword in lowered for keyword in ["code", "research", "decide", "decision", "plan", "workflow"]):
            return 3
        if any(keyword in lowered for keyword in ["summarize", "explain", "summary"]):
            return 2
        return 1

    @staticmethod
    def _reasoning_used(steps: list[dict[str, Any]]) -> bool:
        reasoning_tools = {"analyze_decision", "what_if_scenario", "devil_advocate", "explain_uncertainty", "ensemble_answer"}
        return any(step.get("tool") in reasoning_tools for step in steps)

    @staticmethod
    def _parse_response(content: str) -> dict[str, Any]:
        try:
            parsed = json.loads(content)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            return {"type": "final", "response": content}
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
