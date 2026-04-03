"""Minimal async ReAct loop for AURA."""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Callable

from .event_bus import EventBus
from .config import load_config
from .llm_router import OllamaRouter
from .tools import ToolCallResult, ToolRegistry, get_tool_registry

try:
    from aura.memory import inject_context, auto_extract_memories
except Exception:  # pragma: no cover
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

    def __init__(
        self,
        router: OllamaRouter,
        registry: ToolRegistry | None = None,
        event_bus: EventBus | None = None,
        max_steps: int = 10,
        confirm_tier3: Callable[[str, dict[str, Any]], bool] | None = None,
        orchestrator: Any | None = None,
    ) -> None:
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
        if callable(inject_context):
            try:
                memory_context = await asyncio.to_thread(inject_context, user_message)
            except Exception:
                memory_context = ""

        registry = self.registry or get_tool_registry()
        messages = [
            {"role": "system", "content": self._system_prompt(registry.list_tools(), memory_context)},
            {"role": "user", "content": user_message},
        ]
        steps: list[dict[str, Any]] = []

        for _ in range(self.max_steps):
            model_result = await self._model_call(messages, user_message, importance)
            if not model_result.ok or model_result.content is None:
                return AgentLoopResult(
                    ok=False,
                    error=model_result.error or "model-error",
                    steps=steps,
                    used_ensemble=model_result.used_ensemble,
                )

            parsed = self._parse_turn(model_result.content)

            # ----------------------------------------------------------------
            # Final answer path — this now also fires for plain-prose replies
            # because _parse_turn() treats unstructured content as a final
            # answer instead of returning {final_answer: None, action: None}.
            # ----------------------------------------------------------------
            if parsed["final_answer"] is not None:
                answer = parsed["final_answer"]
                await self._maybe_voice_response(answer)
                return AgentLoopResult(
                    ok=True,
                    answer=answer,
                    steps=steps,
                    used_ensemble=model_result.used_ensemble,
                    tools_called=[step["tool"] for step in steps],
                    reasoning_used=self._reasoning_used(steps),
                )

            # ----------------------------------------------------------------
            # Tool-call path
            # ----------------------------------------------------------------
            action = parsed["action"]
            if action is None:
                # Should not happen now that _parse_turn() has a prose
                # fallback, but guard anyway to avoid silent empty responses.
                answer = model_result.content.strip() or "(no response)"
                await self._maybe_voice_response(answer)
                return AgentLoopResult(
                    ok=True,
                    answer=answer,
                    steps=steps,
                    used_ensemble=model_result.used_ensemble,
                    tools_called=[step["tool"] for step in steps],
                    reasoning_used=self._reasoning_used(steps),
                )

            tool_name = str(action.get("tool") or action.get("name") or "")
            arguments = action.get("arguments") if isinstance(action.get("arguments"), dict) else {}

            if not tool_name:
                return AgentLoopResult(
                    ok=False,
                    error="missing-tool-name",
                    steps=steps,
                    used_ensemble=model_result.used_ensemble,
                )

            try:
                tool_spec = registry.get(tool_name)
            except KeyError:
                return AgentLoopResult(
                    ok=False,
                    error=f"unknown-tool:{tool_name}",
                    steps=steps,
                )

            if tool_spec.tier >= 3 and not self.confirm_tier3(tool_name, arguments):
                return AgentLoopResult(
                    ok=False,
                    error="tier-3-confirmation-required",
                    steps=steps,
                )

            tool_result = await registry.execute(tool_name, arguments, confirm=True)
            tool_result_dict = self._tool_result_dict(tool_result)
            steps.append({"tool": tool_name, "arguments": arguments, "result": tool_result_dict})

            if self.event_bus is not None:
                await self.event_bus.publish(
                    "agent.tool", {"tool": tool_name, "result": tool_result_dict}
                )

            if not tool_result.ok:
                return AgentLoopResult(
                    ok=False,
                    error=tool_result.error,
                    steps=steps,
                    used_ensemble=model_result.used_ensemble,
                    tools_called=[step["tool"] for step in steps],
                    reasoning_used=self._reasoning_used(steps),
                )

            observation = self._format_observation(tool_result)
            messages.append({"role": "assistant", "content": model_result.content})
            messages.append({"role": "user", "content": f"Observation: {observation}"})

            if auto_extract_memories is not None:
                asyncio.create_task(self._extract_memories(user_message, model_result.content))

        return AgentLoopResult(
            ok=False,
            error="max-steps-exceeded",
            steps=steps,
            tools_called=[step["tool"] for step in steps],
            reasoning_used=self._reasoning_used(steps),
        )

    async def handle_message(
        self,
        user_message: str,
        importance: int | None = None,
        stream: bool = False,
    ) -> dict[str, Any] | AsyncIterator[dict[str, Any]]:
        """Compatibility wrapper returning a UI-friendly result."""

        if stream:
            async def _stream() -> AsyncIterator[dict[str, Any]]:
                if self.orchestrator is not None:
                    result = await self.orchestrator.handle(
                        user_message, "local", {}, importance or 2, stream=True
                    )
                    async for event in result:
                        yield event
                    return
                result = await self.run(user_message, importance=importance)
                # Always send at least the opening keep-alive frame
                yield {"token": "", "done": False}
                text = result.answer or result.error or "No response."
                for chunk in self._chunk_text(text):
                    yield {"token": chunk, "done": False}
                yield {
                    "token": "",
                    "done": True,
                    "tools_called": result.tools_called,
                    "reasoning_used": result.reasoning_used,
                    "used_ensemble": result.used_ensemble,
                }

            return _stream()

        if self.orchestrator is not None:
            result = await self.orchestrator.handle(
                user_message, "local", {}, importance or 2
            )
            return {
                "response": getattr(result, "response", "") or "",
                "used_ensemble": getattr(result, "ensemble_used", False),
                "tools_called": getattr(result, "tools_called", []),
                "reasoning_used": getattr(result, "reasoning_used", False),
                "steps": getattr(result, "steps", []),
            }

        result = await self.run(user_message, importance=importance)
        # Hard guard: response must NEVER be empty string.
        # If answer is None/empty, show the error; if that's also empty
        # show a static fallback so the frontend always renders something.
        response_text = result.answer or result.error or "No response."
        return {
            "response": response_text,
            "used_ensemble": result.used_ensemble,
            "tools_called": result.tools_called,
            "reasoning_used": result.reasoning_used,
            "steps": result.steps,
        }

    @staticmethod
    def _chunk_text(text: str) -> list[str]:
        if not text:
            return []
        return re.findall(r"\S+\s*", text)

    async def _model_call(
        self,
        messages: list[dict[str, Any]],
        user_message: str,
        importance: int | None = None,
    ) -> _ModelTurn:
        importance = importance if importance is not None else self._importance_level(user_message)
        ensemble = getattr(self._config, "ensemble", None)
        if (
            ensemble is not None
            and ensemble.enabled
            and importance >= ensemble.default_importance_threshold
        ):
            from aura.agents.ensemble.tools import ensemble_answer

            prompt = json.dumps(messages, ensure_ascii=True)
            result = await ensemble_answer(
                prompt,
                importance_level=importance,
                models=ensemble.models,
                context=None,
            )
            return _ModelTurn(
                ok=True,
                content=result.synthesized_answer,
                error=None,
                used_ensemble=True,
            )

        raw = await self.router.chat(messages)
        # Guard against router returning None when all providers are
        # quota-exhausted — without this we get an AttributeError on
        # raw.ok which swallows the real error.
        if raw is None:
            return _ModelTurn(
                ok=False,
                content=None,
                error="all-providers-quota-exhausted",
            )
        return _ModelTurn(
            ok=raw.ok,
            content=raw.content,
            error=raw.error,
            used_ensemble=False,
        )

    async def _extract_memories(self, user_message: str, response: str) -> None:
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

    def _system_prompt(self, tools: list[Any], memory_context: str = "") -> str:
        tool_descriptions = [
            {
                "name": spec.name,
                "description": spec.description,
                "tier": spec.tier,
                "arguments": spec.arguments_schema,
                "returns": spec.return_schema,
            }
            for spec in tools
        ]
        payload = {
            "instructions": [
                "You are AURA, a personal AI assistant.",
                "Think step by step in a brief Thought section.",
                "Then output exactly one Action JSON object OR a Final Answer line.",
                'Valid Action JSON: {"tool":"tool_name","arguments":{...}}',
                "If you do not need a tool, output: Final Answer: <your answer here>.",
                "You MUST end every response with either an Action JSON or a Final Answer line.",
            ],
            "tools": tool_descriptions,
            "max_steps": self.max_steps,
        }
        if memory_context:
            payload["memory_context"] = memory_context
        return json.dumps(payload, ensure_ascii=True)

    @staticmethod
    def _importance_level(message: str) -> int:
        lowered = message.lower()
        if any(
            keyword in lowered
            for keyword in ["code", "research", "decide", "decision", "plan", "workflow"]
        ):
            return 3
        if any(keyword in lowered for keyword in ["summarize", "explain", "summary"]):
            return 2
        return 1

    @staticmethod
    def _reasoning_used(steps: list[dict[str, Any]]) -> bool:
        reasoning_tools = {
            "analyze_decision",
            "what_if_scenario",
            "devil_advocate",
            "explain_uncertainty",
            "ensemble_answer",
        }
        return any(step.get("tool") in reasoning_tools for step in steps)

    @staticmethod
    def _parse_turn(content: str) -> dict[str, Any]:
        """Parse a single model turn into thought / action / final_answer.

        Priority:
        1. Explicit ``Final Answer: ...`` marker  -> final_answer
        2. Explicit ``Action: {...}`` JSON block   -> action
        3. Bare JSON object with tool/name key     -> action
        4. Bare JSON with final_answer / type=final -> final_answer
        5. Plain prose (no markers at all)         -> treat as final_answer
           This is the key fix: LLMs often just reply with plain text.
           Returning (None, None) caused 'no response generated'.
        """
        # 1. Explicit Final Answer marker
        final_answer = ReActAgentLoop._extract_final_answer(content)
        if final_answer is not None:
            return {
                "thought": ReActAgentLoop._extract_thought(content),
                "action": None,
                "final_answer": final_answer,
            }

        # 2. Explicit Action: {...} block
        action = ReActAgentLoop._extract_action(content)
        if action is not None:
            return {
                "thought": ReActAgentLoop._extract_thought(content),
                "action": action,
                "final_answer": None,
            }

        # 3 & 4. Bare JSON object
        try:
            parsed = json.loads(content)
            if isinstance(parsed, dict):
                if "final_answer" in parsed:
                    return {
                        "thought": parsed.get("thought"),
                        "action": None,
                        "final_answer": str(parsed.get("final_answer", "")),
                    }
                if parsed.get("type") == "final":
                    return {
                        "thought": parsed.get("thought"),
                        "action": None,
                        "final_answer": str(parsed.get("response", "")),
                    }
                if "tool" in parsed or "name" in parsed:
                    return {
                        "thought": parsed.get("thought"),
                        "action": parsed,
                        "final_answer": None,
                    }
        except (json.JSONDecodeError, ValueError):
            pass

        # 5. Plain-prose fallback — treat the whole content as the answer.
        #    This fires for any LLM that just replies conversationally
        #    without following the ReAct format exactly.
        stripped = content.strip()
        return {
            "thought": ReActAgentLoop._extract_thought(content),
            "action": None,
            "final_answer": stripped if stripped else None,
        }

    @staticmethod
    def _extract_thought(content: str) -> str:
        match = re.search(
            r"Thought:\s*(.*?)(?:\n(?:Action|Final Answer):|\Z)",
            content,
            flags=re.DOTALL | re.IGNORECASE,
        )
        return match.group(1).strip() if match else ""

    @staticmethod
    def _extract_final_answer(content: str) -> str | None:
        match = re.search(
            r"Final Answer:\s*(.+)",
            content,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if match:
            return match.group(1).strip()
        return None

    @staticmethod
    def _extract_action(content: str) -> dict[str, Any] | None:
        match = re.search(
            r"Action:\s*(\{.*\})",
            content,
            flags=re.DOTALL | re.IGNORECASE,
        )
        if not match:
            return None
        payload = match.group(1).strip()
        try:
            parsed = json.loads(payload)
        except json.JSONDecodeError:
            return None
        return parsed if isinstance(parsed, dict) else None

    @staticmethod
    def _format_observation(result: ToolCallResult) -> str:
        if result.ok:
            return json.dumps({"tool": result.tool, "result": result.result}, ensure_ascii=True)
        return json.dumps({"tool": result.tool, "error": result.error}, ensure_ascii=True)

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
