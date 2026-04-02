from __future__ import annotations

import asyncio
import json
import sys
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone

import pytest

import aura.agents.aegis.tools as aegis
from aura.core.config import AppConfig, FeatureFlags, ModelSettings, PathsSettings
from aura.core.event_bus import EventBus
from aura.core.tools import get_tool_registry


@pytest.fixture()
def aegis_config(tmp_path):
    config = AppConfig(
        name="AURA",
        offline_mode=True,
        log_level="INFO",
        primary_model=ModelSettings(provider="ollama", name="llama3", host="http://127.0.0.1:11434"),
        fallback_models=[],
        paths=PathsSettings(
            allowed_roots=[tmp_path],
            data_dir=tmp_path,
            log_dir=tmp_path / "logs",
            memory_dir=tmp_path / "memory",
            ipc_socket=tmp_path / "aura.sock",
        ),
        features=FeatureFlags(hotkey=True, tray=True, ipc=True, api=True),
        source_path=tmp_path / "config.yaml",
    )
    aegis.set_config(config)
    aegis.set_event_bus(EventBus())
    return config


@dataclass
class FakeProcess:
    pid: int
    name: str
    status: str = "running"
    cpu_percent: float = 1.5
    memory_mb: float = 12.5
    created_time: datetime = datetime.now(timezone.utc)
    username: str = "tester"
    cmdline: str = "sleep 60"


class FakeProcRunner:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def __call__(self, args, capture_output=True, text=True, timeout=30, cwd=None, shell=False, check=False):
        self.calls.append(args)
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="ok", stderr="")


def test_tier_gate_and_audit_log(monkeypatch, aegis_config):
    registry = get_tool_registry()
    blocked = asyncio.run(registry.execute("kill_process", {"name_or_pid": "123"}, confirm=False))
    assert blocked.ok is False
    assert blocked.error == "tier-3-confirmation-required"

    monkeypatch.setattr(aegis, "get_process", lambda name_or_pid: FakeProcess(pid=321, name="sleep"))
    killed: list[int] = []
    monkeypatch.setattr(aegis, "_kill_pid", lambda pid, force: killed.append(pid))
    result = aegis.kill_process("sleep")
    assert result.success is True
    assert killed == [321]
    audit = (aegis_config.paths.data_dir / "audit.log").read_text(encoding="utf-8").strip().splitlines()
    assert audit and json.loads(audit[-1])["action"] == "kill_process"


@pytest.mark.parametrize("cmd", ["echo hi; rm -rf /", "echo hi && echo bye", "echo hi | cat", "echo hi || echo bye"])
def test_run_shell_command_rejects_shell_injection(cmd, aegis_config):
    with pytest.raises(aegis.AegisError):
        aegis.run_shell_command(cmd)


def test_run_shell_command_writes_audit_log(monkeypatch, aegis_config):
    runner = FakeProcRunner()
    monkeypatch.setattr(aegis.subprocess, "run", runner)
    result = aegis.run_shell_command("echo ok")
    assert result.exit_code == 0
    audit_lines = (aegis_config.paths.data_dir / "audit.log").read_text(encoding="utf-8").strip().splitlines()
    assert audit_lines
    payload = json.loads(audit_lines[-1])
    assert payload["action"] == "run_shell_command"
    assert payload["exit_code"] == 0


@pytest.mark.asyncio
async def test_monitor_resource_emits_event(monkeypatch, aegis_config):
    seen = asyncio.Event()

    async def handler(topic, payload):
        if topic == "aegis.monitor" and payload["resource"] == "cpu":
            seen.set()

    await aegis._EVENT_BUS.subscribe("aegis.monitor", handler)
    monkeypatch.setattr(aegis, "_resource_value", lambda resource: 95.0)
    monitor_id = aegis.monitor_resource("cpu", threshold=80.0, action="threshold-hit", check_interval_seconds=0)
    await asyncio.wait_for(seen.wait(), timeout=2)
    cancelled = aegis.cancel_monitor(monitor_id)
    assert cancelled.success is True


def test_system_and_process_helpers(monkeypatch, aegis_config):
    snapshot = aegis.get_system_info()
    assert snapshot.cpu_count >= 1
    assert snapshot.ram_total_gb >= 0
    assert isinstance(aegis.list_processes(limit=5), list)
    assert aegis.get_process("missing-process") is None


def test_aegis_branch_helpers(monkeypatch, aegis_config, tmp_path):
    class Memory:
        rss = 1024 * 1024 * 12

    class Proc:
        def __init__(self, pid, name):
            self.pid = pid
            self.info = {
                "pid": pid,
                "name": name,
                "status": "running",
                "cpu_percent": 2.5,
                "memory_info": Memory(),
                "create_time": datetime.now(timezone.utc).timestamp(),
                "username": "tester",
                "cmdline": ["sleep", "60"],
            }

    processes = [Proc(100, "alpha"), Proc(200, "beta")]
    monkeypatch.setattr(aegis.psutil, "process_iter", lambda *_args, **_kwargs: processes)
    monkeypatch.setattr(aegis.psutil, "boot_time", lambda: datetime.now(timezone.utc).timestamp() - 10)
    monkeypatch.setattr(aegis.psutil, "virtual_memory", lambda: type("VM", (), {"total": 1024**3, "used": 512**2, "percent": 50.0})())
    monkeypatch.setattr(aegis.psutil, "disk_usage", lambda _path: type("DU", (), {"total": 1024**3, "used": 256**2, "percent": 25.0})())
    monkeypatch.setattr(aegis.psutil, "cpu_percent", lambda interval=0.1: 12.5)
    monkeypatch.setattr(aegis.psutil, "cpu_count", lambda logical=True: 8)
    monkeypatch.setattr(aegis.psutil, "net_if_stats", lambda: {"eth0": type("S", (), {"isup": True})()})
    monkeypatch.setattr(aegis.psutil, "net_if_addrs", lambda: {"eth0": [type("A", (), {"family": object(), "address": "127.0.0.1"})()]})
    monkeypatch.setattr(aegis.psutil, "net_connections", lambda kind="inet": [1, 2])
    monkeypatch.setattr(aegis.psutil, "net_io_counters", lambda: type("C", (), {"bytes_sent": 1, "bytes_recv": 2})())

    monkeypatch.setitem(sys.modules, "pyperclip", type("P", (), {"copy": staticmethod(lambda content: None), "paste": staticmethod(lambda: "clip")})())
    monkeypatch.setitem(
        sys.modules,
        "mss",
        type(
            "M",
            (),
            {
                "mss": type(
                    "Ctx",
                    (),
                    {
                        "__enter__": lambda self: self,
                        "__exit__": lambda self, exc_type, exc, tb: None,
                        "monitors": [{"top": 0, "left": 0, "width": 10, "height": 10}],
                        "grab": lambda self, monitor: type("Img", (), {"rgb": b"x", "size": (1, 1)})(),
                    },
                ),
                "tools": type("T", (), {"to_png": staticmethod(lambda *_args, **_kwargs: None)})(),
            },
        )(),
    )

    filtered = aegis.list_processes(sort_by="name", filter_name="a")
    assert filtered and filtered[0].name == "alpha"
    assert aegis.get_process("100").pid == 100
    assert aegis.get_process("beta").name == "beta"
    with pytest.raises(aegis.AegisError):
        aegis.list_processes(sort_by="invalid")
    assert aegis.clipboard_write("hello").success is True
    assert aegis.clipboard_read().text == "clip"
    path = aegis.take_screenshot(save_path=str(tmp_path / "shot.png"))
    assert path.endswith("shot.png")
    net = aegis.get_network_info()
    assert net.connections_count == 2
    assert net.interfaces and net.interfaces[0].name == "eth0"
    assert aegis.get_environment_variable("MISSING") == ""
    assert aegis.set_environment_variable("X", "1").success is True
    assert aegis.get_environment_variable("X") == "1"
