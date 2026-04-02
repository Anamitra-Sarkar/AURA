"""Data models for AEGIS system control tools."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(slots=True)
class GPUInfo:
    name: str
    memory_total_mb: float
    memory_used_mb: float
    utilization_percent: float


@dataclass(slots=True)
class SystemSnapshot:
    timestamp: datetime
    cpu_percent: float
    cpu_count: int
    ram_total_gb: float
    ram_used_gb: float
    ram_percent: float
    disk_total_gb: float
    disk_used_gb: float
    disk_percent: float
    gpu_info: list[GPUInfo]
    uptime_seconds: int
    platform: str
    python_version: str


@dataclass(slots=True)
class ProcessInfo:
    pid: int
    name: str
    status: str
    cpu_percent: float
    memory_mb: float
    created_time: datetime
    username: str
    cmdline: str


@dataclass(slots=True)
class NetworkInterface:
    name: str
    ip_address: str
    is_up: bool


@dataclass(slots=True)
class NetworkSnapshot:
    interfaces: list[NetworkInterface]
    bytes_sent: int
    bytes_recv: int
    connections_count: int


@dataclass(slots=True)
class CommandResult:
    command: str
    stdout: str
    stderr: str
    exit_code: int
    execution_time_ms: int


@dataclass(slots=True)
class ClipboardContent:
    text: str
    timestamp: datetime


@dataclass(slots=True)
class OperationResult:
    success: bool
    message: str
    data: dict[str, Any] = field(default_factory=dict)
