"""Cross-platform platform helpers and abstraction stubs."""

from __future__ import annotations

import os
import platform as py_platform
import subprocess
import sys
import shutil
import webbrowser
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

    @property
    def is_posix(self) -> bool:
        return self.system.lower() in {"linux", "darwin"}


@dataclass(slots=True)
class PlatformResult:
    """Structured result from a platform action."""

    ok: bool
    action: str
    message: str
    details: dict[str, Any] | None = None


@dataclass(slots=True)
class NotificationResult:
    """Structured result from a system notification request."""

    ok: bool
    message: str
    details: dict[str, Any] | None = None


def detect_os() -> PlatformInfo:
    """Return the current runtime platform information."""

    return PlatformInfo(
        system=py_platform.system() or sys.platform,
        release=py_platform.release(),
        machine=py_platform.machine(),
    )


def supports_unix_sockets() -> bool:
    """Return True when Unix domain sockets are supported."""

    return detect_os().is_posix and hasattr(socket_factory(), "AF_UNIX")


def socket_factory() -> Any:
    """Return the socket module for feature detection."""

    import socket

    return socket


def default_data_dir(app_name: str) -> Path:
    """Return a conventional per-user data directory for the current OS."""

    info = detect_os()
    home = Path.home()
    if info.is_windows:
        return home / "AppData" / "Local" / app_name
    if info.is_macos:
        return home / "Library" / "Application Support" / app_name
    return home / ".local" / "share" / app_name


def open_file(path: str | Path) -> PlatformResult:
    """Open a file or folder using the OS default handler."""

    target = str(path)
    try:
        if target.startswith(("http://", "https://")):
            webbrowser.open(target)
            return PlatformResult(ok=True, action="open_file", message="Opened URL", details={"path": target})
        file_path = Path(target)
        info = detect_os()
        if info.is_windows:
            os.startfile(str(file_path))  # type: ignore[attr-defined]
        elif info.is_macos:
            subprocess.Popen(["open", str(file_path)])
        else:
            subprocess.Popen(["xdg-open", str(file_path)])
        return PlatformResult(ok=True, action="open_file", message="Opened path", details={"path": target})
    except Exception as exc:  # pragma: no cover - exercised via tests with monkeypatch
        return PlatformResult(ok=False, action="open_file", message=str(exc), details={"path": target})


def send_notification(title: str, message: str) -> NotificationResult:
    """Send a desktop notification if the platform supports it."""

    info = detect_os()
    try:
        if info.is_linux and shutil.which("notify-send"):
            subprocess.run(["notify-send", title, message], capture_output=True, text=True, check=False)
            return NotificationResult(ok=True, message="notification-sent", details={"platform": info.system})
        if info.is_macos:
            script = f'display notification {message!r} with title {title!r}'
            subprocess.run(["osascript", "-e", script], capture_output=True, text=True, check=False)
            return NotificationResult(ok=True, message="notification-sent", details={"platform": info.system})
        if info.is_windows:
            return NotificationResult(ok=False, message="windows-notification-unavailable", details={"platform": info.system})
        return NotificationResult(ok=False, message="notification-unavailable", details={"platform": info.system})
    except Exception as exc:  # pragma: no cover - platform dependent
        return NotificationResult(ok=False, message=str(exc), details={"platform": info.system})


def open_path(path: str | Path) -> PlatformResult:
    """Backward-compatible alias for open_file."""

    result = open_file(path)
    if result.action == "open_file":
        result.action = "open_path"
    return result


# Backwards-compatible alias for earlier phases.
detect_platform = detect_os
notify_user = send_notification
