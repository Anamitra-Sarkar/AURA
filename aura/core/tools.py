"""Tool registry, schemas, and permission tier enforcement."""

from __future__ import annotations

import inspect
from dataclasses import dataclass, field
from typing import Any, Callable

Tier = int
ToolHandler = Callable[[dict[str, Any]], Any]


@dataclass(slots=True)
class ToolSpec:
    """Metadata describing a callable tool."""

    name: str
    description: str
    tier: Tier
    arguments_schema: dict[str, Any]
    return_schema: dict[str, Any]
    handler: ToolHandler


@dataclass(slots=True)
class ToolCallResult:
    """Structured result from a tool invocation."""

    ok: bool
    tool: str
    tier: Tier
    result: Any | None = None
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class ToolRegistry:
    """Register and execute tools with explicit permission tiers."""

    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> None:
        """Register a tool spec."""

        if spec.name in self._tools:
            raise ValueError(f"Tool already registered: {spec.name}")
        self._tools[spec.name] = spec

    def decorator(
        self,
        *,
        name: str,
        description: str,
        tier: Tier,
        arguments_schema: dict[str, Any],
        return_schema: dict[str, Any],
    ) -> Callable[[ToolHandler], ToolHandler]:
        """Return a decorator that registers a tool function."""

        def wrapper(func: ToolHandler) -> ToolHandler:
            self.register(
                ToolSpec(
                    name=name,
                    description=description,
                    tier=tier,
                    arguments_schema=arguments_schema,
                    return_schema=return_schema,
                    handler=func,
                )
            )
            return func

        return wrapper

    def get(self, name: str) -> ToolSpec:
        """Lookup a registered tool."""

        return self._tools[name]

    def list_tools(self) -> list[ToolSpec]:
        """Return all registered tools."""

        return list(self._tools.values())

    async def execute(self, name: str, arguments: dict[str, Any] | None = None, *, confirm: bool = False) -> ToolCallResult:
        """Execute a tool and enforce tier gates."""

        try:
            spec = self.get(name)
        except KeyError:
            return ToolCallResult(ok=False, tool=name, tier=0, error=f"unknown-tool:{name}")
        if spec.tier >= 3 and not confirm:
            return ToolCallResult(ok=False, tool=name, tier=spec.tier, error="tier-3-confirmation-required")
        try:
            outcome = spec.handler(arguments or {})
            if inspect.isawaitable(outcome):
                outcome = await outcome
            return ToolCallResult(ok=True, tool=name, tier=spec.tier, result=outcome)
        except Exception as exc:
            return ToolCallResult(ok=False, tool=name, tier=spec.tier, error=str(exc))


def build_tool_schema(name: str, description: str, arguments_schema: dict[str, Any], return_schema: dict[str, Any], tier: Tier) -> dict[str, Any]:
    """Return a JSON-schema-friendly tool description."""

    return {
        "name": name,
        "description": description,
        "tier": tier,
        "arguments": arguments_schema,
        "returns": return_schema,
    }
