"""Command execution helpers for the AURA client."""

from __future__ import annotations

from typing import Any


class CommandExecutor:
    def execute(self, command: dict[str, Any]) -> dict[str, Any]:
        tool = command.get("tool")
        return {"tool": tool, "args": command.get("args", {}), "status": "executed"}

