"""ADB-backed mobile tools."""

from __future__ import annotations

import subprocess
from pathlib import Path

from aura.core.logging import get_logger
from aura.core.tools import ToolSpec, get_tool_registry

from .models import AppInfo, MobileDevice

LOGGER = get_logger(__name__, component="mobile")


def _adb_available() -> bool:
    return subprocess.run(["sh", "-lc", "command -v adb >/dev/null 2>&1"], capture_output=True, text=True, check=False).returncode == 0


def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, capture_output=True, text=True, check=False)


def list_devices() -> list[MobileDevice]:
    if not _adb_available():
        return []
    proc = _run(["adb", "devices", "-l"])
    devices: list[MobileDevice] = []
    for line in proc.stdout.splitlines():
        if "\tdevice" not in line:
            continue
        device_id = line.split()[0]
        model = ""
        for part in line.split():
            if part.startswith("model:"):
                model = part.split(":", 1)[1]
        devices.append(MobileDevice(device_id=device_id, model=model, android_version="", is_connected=True))
    return devices


def take_screenshot(device_id: str, save_path: str) -> str:
    if not _adb_available():
        Path(save_path).write_bytes(b"ADB unavailable")
        return save_path
    proc = subprocess.run(f"adb -s {device_id} exec-out screencap -p > {save_path}", shell=True, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or "adb screenshot failed")
    return save_path


def tap(device_id: str, x: int, y: int) -> bool:
    return _run(["adb", "-s", device_id, "shell", "input", "tap", str(x), str(y)]).returncode == 0


def swipe(device_id: str, x1: int, y1: int, x2: int, y2: int, duration_ms: int) -> bool:
    return _run(["adb", "-s", device_id, "shell", "input", "swipe", str(x1), str(y1), str(x2), str(y2), str(duration_ms)]).returncode == 0


def type_text(device_id: str, text: str) -> bool:
    return _run(["adb", "-s", device_id, "shell", "input", "text", text]).returncode == 0


def press_key(device_id: str, keycode: int) -> bool:
    return _run(["adb", "-s", device_id, "shell", "input", "keyevent", str(keycode)]).returncode == 0


def open_app(device_id: str, package_name: str) -> bool:
    return _run(["adb", "-s", device_id, "shell", "monkey", "-p", package_name, "-c", "android.intent.category.LAUNCHER", "1"]).returncode == 0


def list_apps(device_id: str) -> list[AppInfo]:
    if not _adb_available():
        return []
    proc = _run(["adb", "-s", device_id, "shell", "pm", "list", "packages", "-3"])
    apps: list[AppInfo] = []
    for line in proc.stdout.splitlines():
        if line.startswith("package:"):
            package_name = line.split(":", 1)[1].strip()
            apps.append(AppInfo(package_name=package_name, label=package_name, version="", is_running=False))
    return apps


def get_screen_text(device_id: str) -> str:
    if not _adb_available():
        return ""
    _run(["adb", "-s", device_id, "shell", "uiautomator", "dump", "/sdcard/window_dump.xml"])
    proc = _run(["adb", "-s", device_id, "shell", "cat", "/sdcard/window_dump.xml"])
    return proc.stdout


def send_notification_read_command(device_id: str) -> list[str]:
    return [line for line in get_screen_text(device_id).splitlines() if line.strip()]


def register_mobile_tools() -> None:
    registry = get_tool_registry()
    specs = [
        ToolSpec("list_devices", "List connected Android devices.", 1, {"type": "object"}, {"type": "array"}, lambda _args: list_devices()),
        ToolSpec("take_screenshot", "Take a screenshot from a device.", 1, {"type": "object"}, {"type": "string"}, lambda args: take_screenshot(args["device_id"], args["save_path"])),
        ToolSpec("tap", "Tap a screen coordinate.", 1, {"type": "object"}, {"type": "boolean"}, lambda args: tap(args["device_id"], args["x"], args["y"])),
        ToolSpec("swipe", "Swipe on a device.", 1, {"type": "object"}, {"type": "boolean"}, lambda args: swipe(args["device_id"], args["x1"], args["y1"], args["x2"], args["y2"], args["duration_ms"])),
        ToolSpec("type_text", "Type text on a device.", 1, {"type": "object"}, {"type": "boolean"}, lambda args: type_text(args["device_id"], args["text"])),
        ToolSpec("press_key", "Press a keycode on a device.", 1, {"type": "object"}, {"type": "boolean"}, lambda args: press_key(args["device_id"], args["keycode"])),
        ToolSpec("open_app", "Open an app on a device.", 1, {"type": "object"}, {"type": "boolean"}, lambda args: open_app(args["device_id"], args["package_name"])),
        ToolSpec("list_apps", "List installed apps.", 1, {"type": "object"}, {"type": "array"}, lambda args: list_apps(args["device_id"])),
        ToolSpec("get_screen_text", "Read screen text.", 1, {"type": "object"}, {"type": "string"}, lambda args: get_screen_text(args["device_id"])),
        ToolSpec("send_notification_read_command", "Read notification text.", 1, {"type": "object"}, {"type": "array"}, lambda args: send_notification_read_command(args["device_id"])),
    ]
    for spec in specs:
        try:
            registry.register(spec)
        except ValueError:
            continue


register_mobile_tools()
