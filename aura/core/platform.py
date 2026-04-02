"""Cross-platform platform helpers and abstraction stubs."""

from __future__ import annotations

import os
import platform as py_platform
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class PlatformInfo:
    """Basic system identification metadata."""

    system: str
    release: str
    machine: str

    @property
    def is_windows(self) -> bool:
        return self.system.lower() == "windows"

    @property
    def is_macos(self) -> bool:
        return self.system.lower() == "darwin"

    @property
    def is_linux(self) -> bool:
        return self.system.lower() == "linux"


@dataclass(slots=True)
class PlatformResult:
    """Structured result from a platform action."""

    ok: bool
    action: str
    message: str
    details: dict[str, Any] | None = None


def detect_platform() -> PlatformInfo:
    """Return the current runtime platform information."""

    return PlatformInfo(
        system=py_platform.system() or sys.platform,
        release=py_platform.release(),
        machine=py_platform.machine(),
    )


def supports_unix_sockets() -> bool:
    """Return True when Unix domain sockets are supported."""

    return os.name == "posix" and hasattr(socket_factory(), "AF_UNIX")


def socket_factory() -> Any:
    """Return the socket module for feature detection."""

    import socket

    return socket


def default_data_dir(app_name: str) -> Path:
    """Return a conventional per-user data directory for the current OS."""

    info = detect_platform()
    home = Path.home()
    if info.is_windows:
        return home / "AppData" / "Local" / app_name
    if info.is_macos:
        return home / "Library" / "Application Support" / app_name
    return home / ".local" / "share" / app_name


def open_path(path: str | Path) -> PlatformResult:
    """Open a file or folder using the OS default handler."""

    target = str(Path(path))
    try:
        info = detect_platform()
        if info.is_windows:
            os.startfile(target)  # type: ignore[attr-defined]
        elif info.is_macos:
            subprocess.Popen(["open", target])
        else:
            subprocess.Popen(["xdg-open", target])
        return PlatformResult(ok=True, action="open_path", message="Opened path", details={"path": target})
    except Exception as exc:  # pragma: no cover - exercised via tests with monkeypatch
        return PlatformResult(ok=False, action="open_path", message=str(exc), details={"path": target})
