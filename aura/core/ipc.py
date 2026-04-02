"""Unix socket IPC stub for AURA."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable

from .platform import supports_unix_sockets

RequestHandler = Callable[[str], Awaitable[str] | str]


@dataclass(slots=True)
class IPCResult:
    """Structured result from IPC operations."""

    ok: bool
    message: str
    details: dict[str, str] | None = None


class UnixSocketServer:
    """Minimal async Unix socket server."""

    def __init__(self, socket_path: str | Path, handler: RequestHandler | None = None) -> None:
        self.socket_path = Path(socket_path)
        self.handler = handler or (lambda message: message)
        self._server: asyncio.base_events.Server | None = None

    async def start(self) -> IPCResult:
        """Start the socket server."""

        if not supports_unix_sockets():
            return IPCResult(ok=False, message="unix-sockets-unsupported")
        try:
            self.socket_path.parent.mkdir(parents=True, exist_ok=True)
            if self.socket_path.exists():
                self.socket_path.unlink()
            self._server = await asyncio.start_unix_server(self._handle_client, path=str(self.socket_path))
            return IPCResult(ok=True, message="ipc-started", details={"path": str(self.socket_path)})
        except Exception as exc:
            return IPCResult(ok=False, message=str(exc), details={"path": str(self.socket_path)})

    async def stop(self) -> IPCResult:
        """Stop the socket server."""

        try:
            if self._server is not None:
                self._server.close()
                await self._server.wait_closed()
                self._server = None
            if self.socket_path.exists():
                self.socket_path.unlink()
            return IPCResult(ok=True, message="ipc-stopped", details={"path": str(self.socket_path)})
        except Exception as exc:
            return IPCResult(ok=False, message=str(exc), details={"path": str(self.socket_path)})

    async def _handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        data = await reader.readline()
        message = data.decode("utf-8").rstrip("\n")
        response = self.handler(message)
        if asyncio.iscoroutine(response):
            response = await response
        writer.write((str(response) + "\n").encode("utf-8"))
        await writer.drain()
        writer.close()
        await writer.wait_closed()
