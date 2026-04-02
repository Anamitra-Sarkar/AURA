from __future__ import annotations

import pytest

from aura.core.agent_loop import ReActAgentLoop
from aura.core.event_bus import EventBus
from aura.core.llm_router import LLMResult
from aura.core.tools import ToolRegistry, ToolSpec


class FakeRouter:
    def __init__(self, outputs):
        self.outputs = outputs
        self.calls = 0

    async def chat(self, messages):
        output = self.outputs[self.calls]
        self.calls += 1
        return LLMResult(ok=True, model="fake", content=output)


@pytest.mark.asyncio
async def test_agent_loop_executes_tool_then_finishes():
    registry = ToolRegistry()
    registry.register(
        ToolSpec(
            name="echo",
            description="Echo input",
            tier=1,
            arguments_schema={"type": "object"},
            return_schema={"type": "object"},
            handler=lambda args: args,
        )
    )
    router = FakeRouter([
        '{"type":"tool","tool":"echo","arguments":{"value":42}}',
        '{"type":"final","response":"finished"}',
    ])
    loop = ReActAgentLoop(router=router, registry=registry, event_bus=EventBus())
    result = await loop.run("run echo")
    assert result.ok is True
    assert result.answer == "finished"
    assert result.steps[0]["tool"] == "echo"
