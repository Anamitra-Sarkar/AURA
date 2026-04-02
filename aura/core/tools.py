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
    tier_resolver: Callable[[dict[str, Any]], Tier] | None = None

    def to_schema(self) -> dict[str, Any]:
        """Return a JSON-schema-friendly representation of the tool."""

        return build_tool_schema(self.name, self.description, self.arguments_schema, self.return_schema, self.tier)


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
        tier_resolver: Callable[[dict[str, Any]], Tier] | None = None,
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
                    tier_resolver=tier_resolver,
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

    def clear(self) -> None:
        """Remove all registered tools."""

        self._tools.clear()

    async def execute(self, name: str, arguments: dict[str, Any] | None = None, *, confirm: bool = False) -> ToolCallResult:
        """Execute a tool and enforce tier gates."""

        try:
            spec = self.get(name)
        except KeyError:
            return ToolCallResult(ok=False, tool=name, tier=0, error=f"unknown-tool:{name}")
        effective_tier = spec.tier_resolver(arguments or {}) if spec.tier_resolver is not None else spec.tier
        if effective_tier >= 3 and not confirm:
            return ToolCallResult(ok=False, tool=name, tier=effective_tier, error="tier-3-confirmation-required")
        try:
            outcome = spec.handler(arguments or {})
            if inspect.isawaitable(outcome):
                outcome = await outcome
            return ToolCallResult(ok=True, tool=name, tier=effective_tier, result=outcome)
        except Exception as exc:
            return ToolCallResult(ok=False, tool=name, tier=effective_tier, error=str(exc))


def build_tool_schema(name: str, description: str, arguments_schema: dict[str, Any], return_schema: dict[str, Any], tier: Tier) -> dict[str, Any]:
    """Return a JSON-schema-friendly tool description."""

    return {
        "name": name,
        "description": description,
        "tier": tier,
        "arguments": arguments_schema,
        "returns": return_schema,
    }


GLOBAL_TOOL_REGISTRY = ToolRegistry()
_BUILTIN_TOOLS_LOADED = False
_BUILTIN_TOOLS_LOADING = False


def ensure_builtin_tools_loaded() -> None:
    """Import built-in agent packages so their tools register themselves."""

    global _BUILTIN_TOOLS_LOADED, _BUILTIN_TOOLS_LOADING
    if _BUILTIN_TOOLS_LOADED:
        return
    if _BUILTIN_TOOLS_LOADING:
        return
    _BUILTIN_TOOLS_LOADING = True
    try:
        import aura.agents.atlas.tools  # noqa: F401
        import aura.agents.logos.tools  # noqa: F401
        import aura.agents.echo.tools  # noqa: F401
        import aura.memory.mneme.tools  # noqa: F401
        import aura.browser.hermes.tools  # noqa: F401
        import aura.agents.iris.tools  # noqa: F401
        import aura.agents.aegis.tools  # noqa: F401
        import aura.agents.director.tools  # noqa: F401
        import aura.agents.phantom.tools  # noqa: F401
        import aura.agents.ensemble.tools  # noqa: F401
        import aura.agents.oracle_deep.tools  # noqa: F401
        import aura.agents.lyra.tools  # noqa: F401
        import aura.agents.stream.tools  # noqa: F401
        import aura.agents.mosaic.tools  # noqa: F401
        _BUILTIN_TOOLS_LOADED = True
    finally:
        _BUILTIN_TOOLS_LOADING = False


def register_tool(
    *,
    name: str,
    description: str,
    tier: Tier,
    arguments_schema: dict[str, Any],
    return_schema: dict[str, Any],
    tier_resolver: Callable[[dict[str, Any]], Tier] | None = None,
) -> Callable[[ToolHandler], ToolHandler]:
    """Register a tool in the global registry."""

    return GLOBAL_TOOL_REGISTRY.decorator(
        name=name,
        description=description,
        tier=tier,
        arguments_schema=arguments_schema,
        return_schema=return_schema,
        tier_resolver=tier_resolver,
    )


def get_tool_registry() -> ToolRegistry:
    """Return the process-wide tool registry."""

    ensure_builtin_tools_loaded()
    return GLOBAL_TOOL_REGISTRY
