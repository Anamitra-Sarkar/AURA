"""Models for mobile device control."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(slots=True)
class MobileDevice:
    device_id: str
    model: str
    android_version: str
    is_connected: bool


@dataclass(slots=True)
class MobileAction:
    action_type: str
    result: str
    screenshot_path: str
    timestamp: datetime


@dataclass(slots=True)
class AppInfo:
    package_name: str
    label: str
    version: str
    is_running: bool
