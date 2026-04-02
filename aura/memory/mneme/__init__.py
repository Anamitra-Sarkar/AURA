"""MNEME long-term memory agent."""

from .models import ConsolidationReport, MemoryRecord, RecallResult
from .tools import (
    auto_extract_memories,
    consolidate_memory,
    delete_memory,
    get_memory_tools,
    inject_context,
    list_memories,
    recall_memory,
    save_memory,
    set_config,
    set_router,
    update_memory,
)

__all__ = [
    "ConsolidationReport",
    "MemoryRecord",
    "RecallResult",
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
