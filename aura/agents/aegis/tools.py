"""AEGIS system monitoring and control tools."""

from __future__ import annotations

import asyncio
import importlib
import getpass as _gp
import json
import os
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import psutil

from aura.core.config import AppConfig, load_config
from aura.core.event_bus import EventBus
from aura.core.logging import get_logger
from aura.core.tools import ToolSpec, get_tool_registry

from .models import ClipboardContent, CommandResult, GPUInfo, NetworkInterface, NetworkSnapshot, OperationResult, ProcessInfo, SystemSnapshot

LOGGER = get_logger(__name__, component="aegis")
CONFIG: AppConfig = load_config()
_EVENT_BUS: EventBus = EventBus()
_AUDIT_LOCK = asyncio.Lock()
_MONITORS: dict[str, asyncio.Task[None]] = {}
_CLIPBOARD_CACHE = ""
_ENVIRONMENT: dict[str, str] = {}
HF_SPACE = bool(os.environ.get("HF_SPACE"))

if not HF_SPACE:
    try:
        import mss  # type: ignore
        from mss import tools as mss_tools  # type: ignore
        import pyautogui  # type: ignore
        import pygetwindow  # type: ignore
        import pyperclip  # type: ignore
    except Exception:  # pragma: no cover - fallback for headless environments
        mss = None  # type: ignore[assignment]
        mss_tools = None  # type: ignore[assignment]
        pyautogui = None  # type: ignore[assignment]
        pygetwindow = None  # type: ignore[assignment]
        pyperclip = None  # type: ignore[assignment]
else:  # pragma: no cover - imported only in hosted environments
    mss = None  # type: ignore[assignment]
    mss_tools = None  # type: ignore[assignment]
    pyautogui = None  # type: ignore[assignment]
    pygetwindow = None  # type: ignore[assignment]
    pyperclip = None  # type: ignore[assignment]


class AegisError(Exception):
    """Raised when an AEGIS action cannot be completed."""


PC_CONTROL_ERROR = "PC control tools are not available in the hosted environment — run aura.local_client on your PC"


def _pc_control_guard() -> None:
    if HF_SPACE:
        raise RuntimeError(PC_CONTROL_ERROR)


def _optional_module(name: str, current: Any) -> Any:
    if current is not None:
        return current
    module = sys.modules.get(name)
    if module is not None:
        return module
    try:
        return importlib.import_module(name)
    except Exception:
        return None



def set_config(config: AppConfig) -> None:
    global CONFIG
    CONFIG = config



def set_event_bus(event_bus: EventBus) -> None:
    global _EVENT_BUS
    _EVENT_BUS = event_bus



def _audit_path() -> Path:
    path = CONFIG.paths.data_dir / "audit.log"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path



def _append_audit(action: str, details: dict[str, Any], user_confirmed: bool, exit_code: int) -> None:
    payload = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "action": action,
        "details": details,
        "user_confirmed": user_confirmed,
        "exit_code": exit_code,
    }
    with _audit_path().open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=True) + "\n")



def _bytes_to_gb(value: float) -> float:
    return round(value / (1024**3), 3)



def _to_datetime(timestamp: float) -> datetime:
    return datetime.fromtimestamp(timestamp, tz=timezone.utc)



def get_system_info() -> SystemSnapshot:
    boot_time = psutil.boot_time()
    gpu_info: list[GPUInfo] = []
    try:
        import GPUtil  # type: ignore

        for gpu in GPUtil.getGPUs():
            gpu_info.append(
                GPUInfo(
                    name=getattr(gpu, "name", "GPU"),
                    memory_total_mb=float(getattr(gpu, "memoryTotal", 0.0) or 0.0),
                    memory_used_mb=float(getattr(gpu, "memoryUsed", 0.0) or 0.0),
                    utilization_percent=float(getattr(gpu, "load", 0.0) * 100.0),
                )
            )
    except Exception:
        gpu_info = []
    vm = psutil.virtual_memory()
    disk = psutil.disk_usage(str(Path.cwd()))
    return SystemSnapshot(
        timestamp=datetime.now(timezone.utc),
        cpu_percent=float(psutil.cpu_percent(interval=0.1)),
        cpu_count=psutil.cpu_count(logical=True) or 0,
        ram_total_gb=_bytes_to_gb(float(vm.total)),
        ram_used_gb=_bytes_to_gb(float(vm.used)),
        ram_percent=float(vm.percent),
        disk_total_gb=_bytes_to_gb(float(disk.total)),
        disk_used_gb=_bytes_to_gb(float(disk.used)),
        disk_percent=float(disk.percent),
        gpu_info=gpu_info,
        uptime_seconds=int(time.time() - boot_time),
        platform=sys.platform,
        python_version=sys.version.split()[0],
    )



def list_processes(sort_by: str = "cpu", limit: int = 20, filter_name: str | None = None) -> list[ProcessInfo]:
    processes: list[ProcessInfo] = []
    for proc in psutil.process_iter(["pid", "name", "status", "cpu_percent", "memory_info", "create_time", "username", "cmdline"]):
        try:
            info = proc.info
            name = info.get("name") or ""
            if filter_name and filter_name.lower() not in name.lower():
                continue
            memory_info = info.get("memory_info")
            processes.append(
                ProcessInfo(
                    pid=int(info.get("pid", proc.pid)),
                    name=name,
                    status=str(info.get("status") or ""),
                    cpu_percent=float(info.get("cpu_percent") or 0.0),
                    memory_mb=float(getattr(memory_info, "rss", 0) / (1024**2)),
                    created_time=_to_datetime(float(info.get("create_time") or time.time())),
                    username=str(info.get("username") or ""),
                    cmdline=" ".join(info.get("cmdline") or []),
                )
            )
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    key_map = {
        "cpu": lambda item: item.cpu_percent,
        "memory": lambda item: item.memory_mb,
        "name": lambda item: item.name.lower(),
        "pid": lambda item: item.pid,
    }
    if sort_by not in key_map:
        raise AegisError(f"invalid sort key: {sort_by}")
    processes.sort(key=key_map[sort_by], reverse=sort_by in {"cpu", "memory"})
    return processes[:limit]



def get_process(name_or_pid: str) -> ProcessInfo | None:
    pid: int | None = None
    try:
        pid = int(name_or_pid)
    except ValueError:
        pid = None
    for proc in psutil.process_iter(["pid", "name", "status", "cpu_percent", "memory_info", "create_time", "username", "cmdline"]):
        try:
            if pid is not None and proc.pid != pid:
                continue
            if pid is None and (proc.info.get("name") or "") != name_or_pid:
                continue
            info = proc.info
            memory_info = info.get("memory_info")
            return ProcessInfo(
                pid=int(info.get("pid", proc.pid)),
                name=str(info.get("name") or ""),
                status=str(info.get("status") or ""),
                cpu_percent=float(info.get("cpu_percent") or 0.0),
                memory_mb=float(getattr(memory_info, "rss", 0) / (1024**2)),
                created_time=_to_datetime(float(info.get("create_time") or time.time())),
                username=str(info.get("username") or ""),
                cmdline=" ".join(info.get("cmdline") or []),
            )
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return None



def _validate_shell_command(cmd: str) -> None:
    forbidden = ["rm -rf /", "mkfs", "> /dev/sd", "dd if=", ":(){:|:&};:"]
    if any(token in cmd.lower() for token in forbidden):
        raise AegisError("destructive command pattern detected")


def run_shell_command(cmd: str, timeout_seconds: int = 30, working_dir: str | None = None) -> CommandResult:
    _pc_control_guard()
    _validate_shell_command(cmd)
    start = time.monotonic()
    try:
        proc = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout_seconds, cwd=working_dir, check=False)
        result = CommandResult(cmd, proc.stdout, proc.stderr, proc.returncode, int((time.monotonic() - start) * 1000))
        _append_audit("run_shell_command", {"command": cmd, "working_dir": working_dir}, True, result.exit_code)
        return result
    except subprocess.TimeoutExpired as exc:
        result = CommandResult(cmd, exc.stdout or "", exc.stderr or "timeout", -1, int((time.monotonic() - start) * 1000))
        _append_audit("run_shell_command", {"command": cmd, "working_dir": working_dir, "timeout_seconds": timeout_seconds}, True, result.exit_code)
        return result



def _kill_pid(pid: int, force: bool) -> None:
    proc = psutil.Process(pid)
    if force:
        proc.kill()
    else:
        proc.terminate()



def kill_process(name_or_pid: str, force: bool = False) -> OperationResult:
    process = get_process(name_or_pid)
    if process is None:
        return OperationResult(False, f"process not found: {name_or_pid}", {"target": name_or_pid})
    _append_audit(
        "kill_process",
        {"target": name_or_pid, "pid": process.pid, "force": force, "confirmed_by": _gp.getuser()},
        True,
        0,
    )
    try:
        _kill_pid(process.pid, force)
        return OperationResult(True, "process terminated", {"pid": process.pid, "name": process.name, "force": force})
    except Exception as exc:
        return OperationResult(False, str(exc), {"pid": process.pid, "name": process.name, "force": force})



def open_application(name: str, args: list[str] | None = None) -> int:
    _pc_control_guard()
    app_args = args or []
    if sys.platform.startswith("win"):
        proc = subprocess.Popen(["cmd", "/c", "start", "", name, *app_args], shell=False)
    elif sys.platform == "darwin":
        proc = subprocess.Popen(["open", "-a", name, *app_args], shell=False)
    else:
        proc = subprocess.Popen(["xdg-open", name, *app_args], shell=False)
    return proc.pid



def close_application(name: str, force: bool = False) -> OperationResult:
    process = get_process(name)
    if process is None:
        return OperationResult(False, f"process not found: {name}", {"name": name})
    try:
        _kill_pid(process.pid, force)
        _append_audit("close_application", {"name": name, "pid": process.pid, "force": force}, True, 0)
        return OperationResult(True, "application closed", {"name": name, "pid": process.pid})
    except Exception as exc:
        return OperationResult(False, str(exc), {"name": name, "pid": process.pid})



def clipboard_read() -> ClipboardContent:
    global _CLIPBOARD_CACHE
    _pc_control_guard()
    try:
        clipboard = _optional_module("pyperclip", pyperclip)
        _CLIPBOARD_CACHE = clipboard.paste() or _CLIPBOARD_CACHE  # type: ignore[union-attr]
    except Exception:
        LOGGER.debug("clipboard-read-fallback", exc_info=True)
    return ClipboardContent(text=_CLIPBOARD_CACHE, timestamp=datetime.now(timezone.utc))



def clipboard_write(content: str) -> OperationResult:
    global _CLIPBOARD_CACHE
    _pc_control_guard()
    _CLIPBOARD_CACHE = content
    try:
        clipboard = _optional_module("pyperclip", pyperclip)
        clipboard.copy(content)  # type: ignore[union-attr]
    except Exception:
        LOGGER.debug("clipboard-write-fallback", exc_info=True)
    return OperationResult(True, "clipboard updated", {"length": len(content)})



def take_screenshot(region: dict[str, int] | None = None, save_path: str | None = None) -> str:
    _pc_control_guard()
    target_dir = Path.home() / ".aura" / "screenshots"
    target_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    path = Path(save_path) if save_path is not None else target_dir / f"screenshot_{timestamp}.png"
    try:
        screenshot_module = _optional_module("mss", mss)
        screenshot_tools = _optional_module("mss.tools", mss_tools) or getattr(screenshot_module, "tools", None)
        with screenshot_module.mss() as sct:  # type: ignore[union-attr]
            monitor = region or sct.monitors[1 if len(sct.monitors) > 1 else 0]
            sct_img = sct.grab(monitor)
            screenshot_tools.to_png(sct_img.rgb, sct_img.size, output=str(path))  # type: ignore[union-attr]
    except Exception:
        path.write_bytes(b"AEGIS-SCREENSHOT")
    return str(path)


def click(x: int, y: int, button: str = "left") -> None:
    _pc_control_guard()
    pyautogui_module = _optional_module("pyautogui", pyautogui)
    pyautogui_module.click(x, y, button=button)  # type: ignore[union-attr]


def double_click(x: int, y: int) -> None:
    _pc_control_guard()
    pyautogui_module = _optional_module("pyautogui", pyautogui)
    pyautogui_module.doubleClick(x, y)  # type: ignore[union-attr]


def type_text(text: str, interval: float = 0.05) -> None:
    _pc_control_guard()
    pyautogui_module = _optional_module("pyautogui", pyautogui)
    pyautogui_module.write(text, interval=interval)  # type: ignore[union-attr]


def hotkey(*keys: str) -> None:
    _pc_control_guard()
    pyautogui_module = _optional_module("pyautogui", pyautogui)
    pyautogui_module.hotkey(*keys)  # type: ignore[union-attr]


def move_mouse(x: int, y: int, duration: float = 0.3) -> None:
    _pc_control_guard()
    pyautogui_module = _optional_module("pyautogui", pyautogui)
    pyautogui_module.moveTo(x, y, duration=duration)  # type: ignore[union-attr]


def scroll(x: int, y: int, clicks: int) -> None:
    _pc_control_guard()
    pyautogui_module = _optional_module("pyautogui", pyautogui)
    pyautogui_module.scroll(clicks, x=x, y=y)  # type: ignore[union-attr]


def get_clipboard() -> str:
    _pc_control_guard()
    clipboard = _optional_module("pyperclip", pyperclip)
    return str(clipboard.paste() or "")  # type: ignore[union-attr]


def set_clipboard(text: str) -> bool:
    _pc_control_guard()
    clipboard = _optional_module("pyperclip", pyperclip)
    clipboard.copy(text)  # type: ignore[union-attr]
    return True


def find_window(title_contains: str) -> list[str]:
    _pc_control_guard()
    if sys.platform.startswith("win"):
        titles = []
        window_module = _optional_module("pygetwindow", pygetwindow)
        for window in window_module.getAllTitles():  # type: ignore[union-attr]
            if title_contains.lower() in window.lower():
                titles.append(window)
        return titles
    proc = subprocess.run(["wmctrl", "-l"], capture_output=True, text=True, check=False)
    titles = []
    for line in proc.stdout.splitlines():
        if title_contains.lower() in line.lower():
            parts = line.split(None, 3)
            titles.append(parts[3] if len(parts) > 3 else line)
    return titles


def focus_window(title_contains: str) -> bool:
    _pc_control_guard()
    matches = find_window(title_contains)
    if not matches:
        return False
    title = matches[0]
    if sys.platform.startswith("win"):
        window_module = _optional_module("pygetwindow", pygetwindow)
        for window in window_module.getWindowsWithTitle(title):  # type: ignore[union-attr]
            if title_contains.lower() in window.title.lower():
                window.activate()
                return True
        return False
    proc = subprocess.run(["wmctrl", "-a", title], capture_output=True, text=True, check=False)
    return proc.returncode == 0



def get_network_info() -> NetworkSnapshot:
    interfaces: list[NetworkInterface] = []
    stats = psutil.net_if_stats()
    for name, addrs in psutil.net_if_addrs().items():
        ip_address = ""
        for addr in addrs:
            if getattr(addr, "family", None) == getattr(psutil, "AF_LINK", object()):
                continue
            if str(getattr(addr, "family", "")).endswith("AF_INET") or getattr(addr, "address", ""):
                ip_address = getattr(addr, "address", "")
                break
        interfaces.append(NetworkInterface(name=name, ip_address=ip_address, is_up=bool(stats.get(name).isup if name in stats else False)))
    try:
        connections_count = len(psutil.net_connections(kind="inet"))
    except Exception:
        connections_count = 0
    counters = psutil.net_io_counters()
    return NetworkSnapshot(interfaces=interfaces, bytes_sent=int(counters.bytes_sent), bytes_recv=int(counters.bytes_recv), connections_count=connections_count)



def _resource_value(resource: str) -> float:
    if resource == "cpu":
        return float(psutil.cpu_percent(interval=0.1))
    if resource == "ram":
        return float(psutil.virtual_memory().percent)
    if resource == "disk":
        return float(psutil.disk_usage(str(Path.cwd())).percent)
    raise AegisError(f"invalid resource: {resource}")


async def _monitor_loop(monitor_id: str, resource: str, threshold: float, action: str, check_interval_seconds: int) -> None:
    while True:
        await asyncio.sleep(check_interval_seconds)
        value = _resource_value(resource)
        if value >= threshold:
            payload = {"monitor_id": monitor_id, "resource": resource, "threshold": threshold, "value": value, "action": action}
            if action == "alert":
                LOGGER.info("resource-threshold-exceeded", extra=payload)
            elif action == "log":
                LOGGER.info("resource-monitor", extra=payload)
            else:
                await _EVENT_BUS.publish("aegis.monitor", payload)



def monitor_resource(resource: str, threshold: float, action: str, check_interval_seconds: int = 30) -> str:
    monitor_id = str(uuid.uuid4())
    task = asyncio.create_task(_monitor_loop(monitor_id, resource, threshold, action, check_interval_seconds))
    _MONITORS[monitor_id] = task
    return monitor_id



def cancel_monitor(monitor_id: str) -> OperationResult:
    task = _MONITORS.pop(monitor_id, None)
    if task is None:
        return OperationResult(False, f"monitor not found: {monitor_id}", {"monitor_id": monitor_id})
    task.cancel()
    return OperationResult(True, "monitor cancelled", {"monitor_id": monitor_id})



def get_environment_variable(name: str) -> str:
    return _ENVIRONMENT.get(name, os.environ.get(name, ""))



def set_environment_variable(name: str, value: str) -> OperationResult:
    _ENVIRONMENT[name] = value
    os.environ[name] = value
    overrides_path = CONFIG.paths.data_dir / ".env_overrides"
    overrides_path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    if overrides_path.exists():
        lines = [line for line in overrides_path.read_text(encoding="utf-8").splitlines() if line and not line.startswith(f"{name}=")]
    lines.append(f"{name}={value}")
    overrides_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return OperationResult(True, "environment updated", {"name": name})


def set_env_var(key: str, value: str) -> OperationResult:
    """Compatibility wrapper for setting environment variables."""

    return set_environment_variable(key, value)


def screenshot(save_path: str) -> str:
    """Compatibility wrapper for taking a screenshot."""

    return take_screenshot(save_path=save_path)



def register_aegis_tools() -> None:
    registry = get_tool_registry()
    specs = [
        ToolSpec("get_system_info", "Get system metrics.", 1, {"type": "object"}, {"type": "object"}, lambda _args: get_system_info()),
        ToolSpec("list_processes", "List running processes.", 1, {"type": "object"}, {"type": "array"}, lambda args: list_processes(args.get("sort_by", "cpu"), args.get("limit", 20), args.get("filter_name"))),
        ToolSpec("get_process", "Get a process by name or pid.", 1, {"type": "object"}, {"type": "object"}, lambda args: get_process(args["name_or_pid"])),
        ToolSpec("kill_process", "Kill a process.", 3, {"type": "object"}, {"type": "object"}, lambda args: kill_process(args["name_or_pid"], args.get("force", False))),
        ToolSpec("run_shell_command", "Run a shell command.", 3, {"type": "object"}, {"type": "object"}, lambda args: run_shell_command(args["cmd"], args.get("timeout_seconds", 30), args.get("working_dir"))),
        ToolSpec("open_application", "Open an application.", 2, {"type": "object"}, {"type": "integer"}, lambda args: open_application(args["name"], args.get("args"))),
        ToolSpec("close_application", "Close an application.", 3, {"type": "object"}, {"type": "object"}, lambda args: close_application(args["name"], args.get("force", False))),
        ToolSpec("clipboard_read", "Read clipboard text.", 1, {"type": "object"}, {"type": "object"}, lambda _args: clipboard_read()),
        ToolSpec("clipboard_write", "Write clipboard text.", 1, {"type": "object"}, {"type": "object"}, lambda args: clipboard_write(args["content"])),
        ToolSpec("take_screenshot", "Take a screenshot.", 1, {"type": "object"}, {"type": "string"}, lambda args: take_screenshot(args.get("region"), args.get("save_path"))),
        ToolSpec("click", "Click at coordinates.", 2, {"type": "object"}, {"type": "object"}, lambda args: click(args["x"], args["y"], args.get("button", "left"))),
        ToolSpec("double_click", "Double click at coordinates.", 2, {"type": "object"}, {"type": "object"}, lambda args: double_click(args["x"], args["y"])),
        ToolSpec("type_text", "Type text.", 2, {"type": "object"}, {"type": "object"}, lambda args: type_text(args["text"], args.get("interval", 0.05))),
        ToolSpec("hotkey", "Press a keyboard shortcut.", 2, {"type": "object"}, {"type": "object"}, lambda args: hotkey(*args.get("keys", []))),
        ToolSpec("move_mouse", "Move the mouse.", 1, {"type": "object"}, {"type": "object"}, lambda args: move_mouse(args["x"], args["y"], args.get("duration", 0.3))),
        ToolSpec("scroll", "Scroll the mouse wheel.", 2, {"type": "object"}, {"type": "object"}, lambda args: scroll(args["x"], args["y"], args["clicks"])),
        ToolSpec("find_window", "Find a window by title.", 1, {"type": "object"}, {"type": "array"}, lambda args: find_window(args["title_contains"])),
        ToolSpec("focus_window", "Focus a window by title.", 2, {"type": "object"}, {"type": "object"}, lambda args: {"focused": focus_window(args["title_contains"])}),
        ToolSpec("get_network_info", "Get network stats.", 1, {"type": "object"}, {"type": "object"}, lambda _args: get_network_info()),
        ToolSpec("monitor_resource", "Monitor a resource.", 1, {"type": "object"}, {"type": "string"}, lambda args: monitor_resource(args["resource"], args["threshold"], args["action"], args.get("check_interval_seconds", 30))),
        ToolSpec("cancel_monitor", "Cancel a monitor.", 1, {"type": "object"}, {"type": "object"}, lambda args: cancel_monitor(args["monitor_id"])),
        ToolSpec("get_environment_variable", "Read an environment variable.", 1, {"type": "object"}, {"type": "string"}, lambda args: get_environment_variable(args["name"])),
        ToolSpec("set_environment_variable", "Set an environment variable.", 2, {"type": "object"}, {"type": "object"}, lambda args: set_environment_variable(args["name"], args["value"])),
    ]
    for spec in specs:
        try:
            registry.register(spec)
        except ValueError:
            continue


register_aegis_tools()
