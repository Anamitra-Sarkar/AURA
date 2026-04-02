"""AURA daemon entry point."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:  # pragma: no cover - import shim for script execution
    from .core.agent_loop import ReActAgentLoop
    from .core.config import AppConfig, load_config
    from .core.event_bus import EventBus
    from .core.hotkey import GlobalHotkeyManager
    from .core.ipc import UnixSocketServer
    from .core.llm_router import OllamaRouter
    from .core.logging import configure_logging, get_logger
    from .core.tools import ToolRegistry, ToolSpec, get_tool_registry
    from .core.tray import TrayController
    from .agents.atlas.tools import register_atlas_tools, set_config as set_atlas_config, set_event_bus as set_atlas_event_bus
    from .agents.logos.tools import register_logos_tools, set_router as set_logos_router
    from .agents.echo.tools import register_echo_tools, set_config as set_echo_config
    from .memory import set_config as set_mneme_config, set_router as set_mneme_router
    from .agents.aegis.tools import register_aegis_tools, set_config as set_aegis_config, set_event_bus as set_aegis_event_bus
    from .agents.director.tools import register_director_tools, set_config as set_director_config, set_event_bus as set_director_event_bus, set_router as set_director_router, resume_interrupted_workflows
    from .agents.phantom.tools import register_phantom_tools, set_config as set_phantom_config, set_event_bus as set_phantom_event_bus, phantom_loop
except ImportError:  # pragma: no cover - direct script execution
    from aura.core.agent_loop import ReActAgentLoop
    from aura.core.config import AppConfig, load_config
    from aura.core.event_bus import EventBus
    from aura.core.hotkey import GlobalHotkeyManager
    from aura.core.ipc import UnixSocketServer
    from aura.core.llm_router import OllamaRouter
    from aura.core.logging import configure_logging, get_logger
    from aura.core.tools import ToolRegistry, ToolSpec, get_tool_registry
    from aura.core.tray import TrayController
    from aura.agents.atlas.tools import register_atlas_tools, set_config as set_atlas_config, set_event_bus as set_atlas_event_bus
    from aura.agents.logos.tools import register_logos_tools, set_router as set_logos_router
    from aura.agents.echo.tools import register_echo_tools, set_config as set_echo_config
    from aura.memory import set_config as set_mneme_config, set_router as set_mneme_router
    from aura.agents.aegis.tools import register_aegis_tools, set_config as set_aegis_config, set_event_bus as set_aegis_event_bus
    from aura.agents.director.tools import register_director_tools, set_config as set_director_config, set_event_bus as set_director_event_bus, set_router as set_director_router, resume_interrupted_workflows
    from aura.agents.phantom.tools import register_phantom_tools, set_config as set_phantom_config, set_event_bus as set_phantom_event_bus, phantom_loop


@dataclass(slots=True)
class DaemonState:
    """Container for the running daemon components."""

    config: AppConfig
    event_bus: EventBus
    tools: ToolRegistry
    router: OllamaRouter
    agent_loop: ReActAgentLoop
    ipc_server: UnixSocketServer | None = None
    hotkey: GlobalHotkeyManager | None = None
    tray: TrayController | None = None
    phantom_task: asyncio.Task[None] | None = None


def _default_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(
        ToolSpec(
            name="system_status",
            description="Return a basic daemon health snapshot.",
            tier=1,
            arguments_schema={"type": "object", "properties": {}, "additionalProperties": False},
            return_schema={"type": "object"},
            handler=lambda _args: {"status": "ok"},
        )
    )
    return registry


async def bootstrap(config_path: str | Path | None = None) -> DaemonState:
    """Load configuration and initialize daemon subsystems."""

    config = load_config(config_path)
    configure_logging(config.log_level)
    logger = get_logger(__name__, component="daemon")
    logger.info("bootstrapping", extra={"event": "bootstrap", "config": str(config.source_path)})
    event_bus = EventBus()
    registry = get_tool_registry()
    try:
        registry.register(
            ToolSpec(
                name="system_status",
                description="Return a basic daemon health snapshot.",
                tier=1,
                arguments_schema={"type": "object", "properties": {}, "additionalProperties": False},
                return_schema={"type": "object"},
                handler=lambda _args: {"status": "ok"},
            )
        )
    except ValueError:
        pass
    router = OllamaRouter(model=config.primary_model.name, host=config.primary_model.host)
    agent_loop = ReActAgentLoop(router=router, registry=registry, event_bus=event_bus)
    set_atlas_config(config)
    set_atlas_event_bus(event_bus)
    set_logos_router(router)
    set_echo_config(config)
    set_mneme_config(config)
    set_mneme_router(router)
    set_aegis_config(config)
    set_aegis_event_bus(event_bus)
    set_director_config(config)
    set_director_event_bus(event_bus)
    set_director_router(router)
    set_phantom_config(config)
    set_phantom_event_bus(event_bus)
    register_atlas_tools()
    register_logos_tools()
    register_echo_tools()
    register_aegis_tools()
    register_director_tools()
    register_phantom_tools()
    resume_interrupted_workflows()
    ipc_server = UnixSocketServer(config.paths.ipc_socket) if config.features.ipc else None
    hotkey = GlobalHotkeyManager() if config.features.hotkey else None
    tray = TrayController() if config.features.tray else None
    return DaemonState(
        config=config,
        event_bus=event_bus,
        tools=registry,
        router=router,
        agent_loop=agent_loop,
        ipc_server=ipc_server,
        hotkey=hotkey,
        tray=tray,
    )


async def run_once(config_path: str | Path | None = None, prompt: str = "Bootstrap verification.") -> dict[str, Any]:
    """Run a single diagnostic agent loop turn."""

    state = await bootstrap(config_path)
    result = await state.agent_loop.run(prompt)
    return {"config": str(state.config.source_path), "result": {"ok": result.ok, "answer": result.answer, "error": result.error, "steps": result.steps}}


async def run_forever(config_path: str | Path | None = None) -> None:
    """Run the daemon until cancelled."""

    state = await bootstrap(config_path)
    phantom_task = asyncio.create_task(phantom_loop())
    if state.ipc_server is not None:
        await state.ipc_server.start()
    if state.hotkey is not None:
        state.hotkey.start()
    if state.tray is not None:
        state.tray.start()
    try:
        while True:
            await asyncio.sleep(1)
    except asyncio.CancelledError:
        pass
    finally:
        phantom_task.cancel()
        if state.hotkey is not None:
            state.hotkey.stop()
        if state.tray is not None:
            state.tray.stop()
        if state.ipc_server is not None:
            await state.ipc_server.stop()


def main() -> None:
    """CLI entry point."""

    parser = argparse.ArgumentParser(description="Start the AURA daemon")
    parser.add_argument("--config", type=str, default=None, help="Path to config/config.yaml")
    parser.add_argument("--once", action="store_true", help="Run a single diagnostic cycle and exit")
    args = parser.parse_args()
    if args.once:
        sys.stdout.write(json.dumps(asyncio.run(run_once(args.config)), ensure_ascii=True) + "\n")
        return
    asyncio.run(run_forever(args.config))


if __name__ == "__main__":
    main()
