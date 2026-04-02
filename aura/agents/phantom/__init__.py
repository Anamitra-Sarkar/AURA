"""PHANTOM background autopilot."""

from .models import Briefing, PhantomTask, WatchTarget
from .tools import (
    disable_watch,
    enable_watch,
    generate_daily_briefing,
    get_phantom_status,
    list_watches,
    pause_all,
    phantom_loop,
    register_phantom_tools,
    register_watch,
    resume_all,
    run_scheduled_tasks,
    set_config,
    set_event_bus,
)

__all__ = [
    "Briefing",
    "PhantomTask",
    "WatchTarget",
    "disable_watch",
    "enable_watch",
    "generate_daily_briefing",
    "get_phantom_status",
    "list_watches",
    "pause_all",
    "phantom_loop",
    "register_phantom_tools",
    "register_watch",
    "resume_all",
    "run_scheduled_tasks",
    "set_config",
    "set_event_bus",
]

TOOL_LIST = [
    "register_watch",
    "disable_watch",
    "enable_watch",
    "list_watches",
    "run_scheduled_tasks",
    "generate_daily_briefing",
    "pause_all",
    "resume_all",
    "get_phantom_status",
]
