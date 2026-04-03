"""Local PC websocket bridge for AURA."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

from aura.core.logging import get_logger
from aura.core.tools import get_tool_registry

LOGGER = get_logger(__name__, component="local-client")


def _serialize(value: Any) -> Any:
    if is_dataclass(value):
        return _serialize(asdict(value))
    if isinstance(value, dict):
        return {key: _serialize(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_serialize(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    return value


def _ws_url(server: str) -> str:
    base = server.rstrip("/")
    if base.endswith("/ws/client/local"):
        return base
    if base.startswith("http://"):
        base = "ws://" + base.removeprefix("http://")
    elif base.startswith("https://"):
        base = "wss://" + base.removeprefix("https://")
    return f"{base}/ws/client/local"


async def _dispatch_tool(tool: str, args: dict[str, Any]) -> Any:
    registry = get_tool_registry()
    result = await registry.execute(tool, args, confirm=True)
    if not result.ok:
        raise RuntimeError(result.error or f"tool failed: {tool}")
    return result.result


async def _connect_once(server: str, token: str) -> None:
    try:
        import websockets
    except ImportError as exc:  # pragma: no cover - dependency availability
        raise RuntimeError("websockets package is required for aura.local_client") from exc

    url = f"{_ws_url(server)}?token={token}"
    async with websockets.connect(url, max_size=16 * 1024 * 1024) as websocket:  # type: ignore[attr-defined]
        hello = await websocket.recv()
        try:
            payload = json.loads(hello)
        except json.JSONDecodeError:
            payload = {"raw": hello}
        LOGGER.info("connected", extra={"hello": payload})
        while True:
            message = await websocket.recv()
            data = json.loads(message)
            if not isinstance(data, dict) or data.get("action") != "tool_call":
                continue
            call_id = str(data.get("call_id", ""))
            tool = str(data.get("tool", ""))
            args = data.get("args") if isinstance(data.get("args"), dict) else {}
            if not call_id or not tool:
                continue
            try:
                result = await _dispatch_tool(tool, args)
                await websocket.send(
                    json.dumps(
                        {
                            "action": "tool_result",
                            "call_id": call_id,
                            "result": _serialize(result),
                            "error": None,
                        },
                        ensure_ascii=True,
                    )
                )
            except Exception as exc:
                await websocket.send(
                    json.dumps(
                        {
                            "action": "tool_result",
                            "call_id": call_id,
                            "result": None,
                            "error": str(exc),
                        },
                        ensure_ascii=True,
                    )
                )


async def run_client(server: str, token: str) -> None:
    delay = 1
    while True:
        try:
            await _connect_once(server, token)
            delay = 1
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            LOGGER.warning("client-disconnected", extra={"error": str(exc), "retry_in_seconds": delay})
            await asyncio.sleep(delay)
            delay = min(delay * 2, 60)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Connect a local PC to the AURA brain over WebSocket.")
    parser.add_argument("--server", default=os.environ.get("AURA_SERVER", ""), help="Base server URL, e.g. wss://space.hf.space")
    parser.add_argument("--token", default=os.environ.get("AURA_TOKEN", ""), help="JWT token used for authentication")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.server or not args.token:
        parser.error("--server and --token are required (or set AURA_SERVER and AURA_TOKEN)")
    asyncio.run(run_client(args.server, args.token))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
