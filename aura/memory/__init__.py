"""AURA memory package."""

from __future__ import annotations

from importlib import import_module
from typing import Any

from .mneme.models import ConsolidationReport, MemoryRecord, RecallResult

TOOL_LIST = [
    "save_memory",
    "recall_memory",
    "update_memory",
    "delete_memory",
    "list_memories",
    "consolidate_memory",
    "inject_context",
    "auto_extract_memories",
]

__all__ = [
    "MemoryRecord",
    "RecallResult",
    "ConsolidationReport",
    "auto_extract_memories",
    "consolidate_memory",
    "delete_memory",
    "get_memory_tools",
    "inject_context",
    "list_memories",
    "recall_memory",
    "save_memory",
    "set_config",
    "set_router",
    "update_memory",
]


def __getattr__(name: str) -> Any:
    if name in {"auto_extract_memories", "consolidate_memory", "delete_memory", "get_memory_tools", "inject_context", "list_memories", "recall_memory", "save_memory", "set_config", "set_router", "update_memory"}:
        module = import_module("aura.memory.mneme.tools")
        return getattr(module, name)
    raise AttributeError(name)

