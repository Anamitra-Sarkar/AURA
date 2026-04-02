from __future__ import annotations

import asyncio

import pytest

from aura.core.ipc import UnixSocketServer
from aura.core.platform import supports_unix_sockets


@pytest.mark.asyncio
async def test_unix_socket_server_echo(tmp_path):
    if not supports_unix_sockets():
        pytest.skip("unix sockets not supported")
    socket_path = tmp_path / "aura.sock"
    server = UnixSocketServer(socket_path)
    start = await server.start()
    assert start.ok is True
    reader, writer = await asyncio.open_unix_connection(path=str(socket_path))
    writer.write(b"ping\n")
    await writer.drain()
    response = await reader.readline()
    assert response.decode().strip() == "ping"
    writer.close()
    await writer.wait_closed()
    await server.stop()
