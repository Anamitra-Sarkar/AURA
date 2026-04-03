from __future__ import annotations

import pytest

from aura.agents.nexus.agent import NexusAgent


class _FakeOrchestrator:
    async def handle(self, instruction, user_id, context, importance=2):
        return type("R", (), {"response": f"{user_id}:{importance}:{instruction}", "agents_used": ["nexus"], "tools_called": [], "reasoning_used": False, "ensemble_used": False, "tokens_used": 1})()


@pytest.mark.asyncio
async def test_nexus_agent_delegates():
    agent = NexusAgent(_FakeOrchestrator())
    result = await agent.handle("hello", {"user_id": "u1", "importance": 3})
    assert result.response == "u1:3:hello"
