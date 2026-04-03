"""WebSocket connection to the AURA cloud brain."""

from __future__ import annotations

import asyncio
import json
import platform

from .executor import CommandExecutor
from .security import CommandSecurity


class ClientConnection:
    def __init__(self, server: str, token: str, user_id: str = "local") -> None:
        self.server = server.rstrip("/")
        self.token = token
        self.user_id = user_id
        self.security = CommandSecurity()
        self.executor = CommandExecutor()

    async def run(self) -> None:
        try:
            import websockets
        except Exception as exc:  # pragma: no cover - optional dependency
            raise RuntimeError("websockets is required") from exc

        url = f"{self.server.replace('https://', 'wss://').replace('http://', 'ws://')}/ws/client/{self.user_id}?token={self.token}"
        async for websocket in websockets.connect(url, ping_interval=30, max_size=2**20):  # type: ignore[attr-defined]
            try:
                await websocket.send(json.dumps({"type": "hello", "platform": platform.system().lower(), "capabilities": ["atlas", "aegis", "hermes", "lyra"], "aura_version": "1.0"}))
                while True:
                    message = json.loads(await websocket.recv())
                    self.security.validate(message)
                    result = self.executor.execute(message)
                    await websocket.send(json.dumps({"type": "tool_result", "command_id": message.get("command_id", ""), "success": True, "result": result, "error": ""}))
            except asyncio.CancelledError:
                raise
            except Exception:
                await asyncio.sleep(1)
