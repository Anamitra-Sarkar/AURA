"""STREAM world-awareness feed."""

from .models import DailyDigest, StreamItem, StreamSource
from .tools import (
    add_stream_source,
    fetch_stream,
    generate_daily_digest,
    get_unread_items,
    list_stream_sources,
    mark_item_read,
    register_stream_tools,
    set_config,
    set_router,
)

__all__ = [
    "DailyDigest",
    "StreamItem",
    "StreamSource",
    "add_stream_source",
    "fetch_stream",
    "generate_daily_digest",
    "get_unread_items",
    "list_stream_sources",
    "mark_item_read",
    "register_stream_tools",
    "set_config",
    "set_router",
]

TOOL_LIST = [
    "fetch_stream",
    "generate_daily_digest",
    "add_stream_source",
    "list_stream_sources",
    "mark_item_read",
    "get_unread_items",
]
