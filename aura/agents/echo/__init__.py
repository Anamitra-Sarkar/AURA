"""ECHO calendar and meeting agent."""

from .models import EmailDraft, Event, OperationResult, Reminder
from .tools import (
    cancel_meeting,
    create_meeting,
    draft_email,
    get_upcoming_reminders,
    join_meeting,
    list_meetings,
    parse_natural_time,
    register_echo_tools,
    send_email,
    set_config,
    set_reminder,
    set_email_config,
    update_meeting,
)

__all__ = [
    "EmailDraft",
    "Event",
    "OperationResult",
    "Reminder",
    "cancel_meeting",
    "create_meeting",
    "draft_email",
    "get_upcoming_reminders",
    "join_meeting",
    "list_meetings",
    "parse_natural_time",
    "register_echo_tools",
    "send_email",
    "set_config",
    "set_reminder",
    "set_email_config",
    "update_meeting",
]
