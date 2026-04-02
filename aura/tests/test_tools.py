from __future__ import annotations

import pytest

from aura.core.tools import ToolRegistry, ToolSpec


@pytest.mark.asyncio
async def test_tool_registry_and_tier_enforcement():
    registry = ToolRegistry()
    registry.register(
        ToolSpec(
            name="echo",
            description="Echo text",
            tier=1,
            arguments_schema={"type": "object"},
            return_schema={"type": "object"},
            handler=lambda args: args,
        )
    )
    registry.register(
        ToolSpec(
            name="danger",
            description="Dangerous action",
            tier=3,
            arguments_schema={"type": "object"},
            return_schema={"type": "object"},
            handler=lambda args: args,
        )
    )
    ok = await registry.execute("echo", {"value": 1})
    denied = await registry.execute("danger", {}, confirm=False)
    assert ok.ok is True
    assert ok.result == {"value": 1}
    assert denied.ok is False
    assert denied.error == "tier-3-confirmation-required"
