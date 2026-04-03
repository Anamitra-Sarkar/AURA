"""FastAPI MCP tool surface."""

from __future__ import annotations

from typing import Any

from aura.core.tools import get_tool_registry


def list_mcp_tools() -> list[dict[str, Any]]:
    registry = get_tool_registry()
    tools = []
    for spec in registry.list_tools():
        tools.append(
            {
                "name": spec.name,
                "description": spec.description,
                "inputSchema": spec.arguments_schema,
                "outputSchema": spec.return_schema,
                "tier": spec.tier,
            }
        )
    return tools


async def call_mcp_tool(agent_id: str, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    registry = get_tool_registry()
    result = await registry.execute(tool_name, arguments, confirm=True)
    return {"content": [{"type": "text", "text": str(result.result if result.ok else result.error)}]}
