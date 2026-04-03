"""ECHO calendar, reminder, and email tools."""

from __future__ import annotations

import json
import smtplib
import sqlite3
import uuid
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from pathlib import Path
from typing import Any

import dateparser

from aura.core.config import AppConfig, load_config
from aura.core.event_bus import EventBus
from aura.core.logging import get_logger
from aura.core.platform import open_file, send_notification
from aura.core.tools import ToolSpec, get_tool_registry

from .models import EmailDraft, Event, OperationResult, Reminder

LOGGER = get_logger(__name__, component="echo")
CONFIG: AppConfig = load_config()
EMAIL_CONFIG: dict[str, Any] | None = None
_EVENT_BUS: EventBus = EventBus()
notify_user = send_notification
open_path = open_file


class EchoError(Exception):
    """Raised when an ECHO action cannot be completed."""


def set_email_config(config: dict[str, Any] | None) -> None:
    """Set the SMTP/Gmail configuration used by send_email."""

    global EMAIL_CONFIG
    EMAIL_CONFIG = config


def set_config(config: AppConfig) -> None:
    """Override the runtime configuration used by ECHO."""

    global CONFIG
    CONFIG = config


def set_event_bus(event_bus: EventBus) -> None:
    """Override the event bus used by Echo."""

    global _EVENT_BUS
    _EVENT_BUS = event_bus


def _db_path() -> Path:
    """Return the local calendar database path."""

    path = CONFIG.paths.data_dir / "echo_calendar.db"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _connect() -> sqlite3.Connection:
    """Open a database connection and ensure tables exist."""

    connection = sqlite3.connect(_db_path())
    connection.row_factory = sqlite3.Row
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS events (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            start TEXT NOT NULL,
            end TEXT NOT NULL,
            attendees TEXT NOT NULL,
            platform TEXT NOT NULL,
            description TEXT NOT NULL,
            provider TEXT NOT NULL,
            meeting_link TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS reminders (
            id TEXT PRIMARY KEY,
            text TEXT NOT NULL,
            trigger_time TEXT NOT NULL,
            repeat TEXT,
            active INTEGER NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS email_drafts (
            id TEXT PRIMARY KEY,
            to_json TEXT NOT NULL,
            subject TEXT NOT NULL,
            body TEXT NOT NULL,
            attachments_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            sent INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    connection.commit()
    return connection


def _now() -> str:
    """Return the current UTC time in ISO format."""

    return datetime.now(timezone.utc).isoformat()


def _row_to_event(row: sqlite3.Row) -> Event:
    """Convert a database row to an Event."""

    return Event(
        id=row["id"],
        title=row["title"],
        start=row["start"],
        end=row["end"],
        attendees=json.loads(row["attendees"]),
        platform=row["platform"],
        description=row["description"],
        provider=row["provider"],
        meeting_link=row["meeting_link"],
        created_at=row["created_at"],
    )


def _row_to_reminder(row: sqlite3.Row) -> Reminder:
    """Convert a database row to a Reminder."""

    return Reminder(
        id=row["id"],
        text=row["text"],
        trigger_time=row["trigger_time"],
        repeat=row["repeat"],
        active=bool(row["active"]),
        created_at=row["created_at"],
    )


def _row_to_draft(row: sqlite3.Row) -> EmailDraft:
    """Convert a database row to an EmailDraft."""

    return EmailDraft(
        id=row["id"],
        to=json.loads(row["to_json"]),
        subject=row["subject"],
        body=row["body"],
        attachments=json.loads(row["attachments_json"]),
        created_at=row["created_at"],
    )


def parse_natural_time(expression: str) -> str:
    """Convert a natural-language time expression into ISO 8601."""

    parsed = dateparser.parse(expression, settings={"TIMEZONE": "UTC", "RETURN_AS_TIMEZONE_AWARE": True})
    if parsed is None:
        raise EchoError(f"could not parse time expression: {expression}")
    return parsed.astimezone(timezone.utc).isoformat()


def list_meetings(date_range: dict[str, str]) -> list[Event]:
    """List meetings in a time range."""

    start = dateparser.parse(date_range["start"])
    end = dateparser.parse(date_range["end"])
    if start is None or end is None:
        raise EchoError("invalid date range")
    connection = _connect()
    try:
        rows = connection.execute(
            "SELECT * FROM events WHERE start >= ? AND end <= ? ORDER BY start ASC",
            (start.astimezone(timezone.utc).isoformat(), end.astimezone(timezone.utc).isoformat()),
        ).fetchall()
        return [_row_to_event(row) for row in rows]
    finally:
        connection.close()


def create_meeting(title: str, start: str, end: str, attendees: list[str], platform: str, description: str = "") -> Event:
    """Create a meeting in the local calendar fallback."""

    event = Event(
        id=str(uuid.uuid4()),
        title=title,
        start=parse_natural_time(start) if not start.endswith("Z") and not start[0].isdigit() else dateparser.parse(start).astimezone(timezone.utc).isoformat(),
        end=parse_natural_time(end) if not end.endswith("Z") and not end[0].isdigit() else dateparser.parse(end).astimezone(timezone.utc).isoformat(),
        attendees=attendees,
        platform=platform,
        description=description,
        provider="local-sqlite",
        meeting_link=f"{platform}://{title.replace(' ', '-').lower()}" if platform != "offline" else "",
        created_at=_now(),
    )
    connection = _connect()
    try:
        connection.execute(
            "INSERT INTO events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (event.id, event.title, event.start, event.end, json.dumps(event.attendees), event.platform, event.description, event.provider, event.meeting_link, event.created_at),
        )
        connection.commit()
        _EVENT_BUS.publish_sync("echo.event_created", {"event_id": event.id, "title": event.title, "start": event.start, "end": event.end})
        return event
    finally:
        connection.close()


def create_event(title: str, start_time: str, end_time: str, description: str = "", location: str = "") -> Event:
    """Compatibility wrapper for the prompt's event API."""

    return create_meeting(title=title, start=start_time, end=end_time, attendees=[], platform=location or "local", description=description)


def list_events(start_date: str, end_date: str, limit: int = 20) -> list[Event]:
    """Compatibility wrapper that returns meetings in the requested range."""

    return list_meetings({"start": start_date, "end": end_date})[:limit]


def delete_event(event_id: str) -> bool:
    """Compatibility wrapper for deleting an event."""

    return cancel_meeting(event_id, notify_attendees=False).success


def remind_before(event_id: str, minutes_before: int) -> Reminder:
    """Compatibility wrapper that stores a reminder note."""

    connection = _connect()
    try:
        row = connection.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
    finally:
        connection.close()
    if row is None:
        raise EchoError(f"event not found: {event_id}")
    event = _row_to_event(row)
    event_start = datetime.fromisoformat(event.start)
    reminder_time = event_start - timedelta(minutes=minutes_before)
    return set_reminder(
        text=f"Reminder: {event.title} starts in {minutes_before} minutes",
        trigger_time=reminder_time.astimezone(timezone.utc).isoformat(),
        repeat=None,
    )


def find_free_slot(duration_minutes: int, after: str, before: str) -> dict[str, str] | None:
    """Compatibility wrapper returning the next available slot."""

    if duration_minutes <= 0:
        return None
    start_dt = dateparser.parse(after)
    end_dt = dateparser.parse(before)
    if start_dt is None or end_dt is None:
        raise EchoError("invalid time range")
    cursor = start_dt.astimezone(timezone.utc)
    cutoff = end_dt.astimezone(timezone.utc)
    target_delta = timedelta(minutes=duration_minutes)
    events = sorted(list_events(after, before, limit=200), key=lambda event: event.start)
    for event in events:
        event_start = datetime.fromisoformat(event.start)
        if event_start - cursor >= target_delta:
            return {"start": cursor.isoformat(), "end": (cursor + target_delta).isoformat()}
        event_end = datetime.fromisoformat(event.end)
        if event_end > cursor:
            cursor = event_end
    if cutoff - cursor >= target_delta:
        return {"start": cursor.isoformat(), "end": (cursor + target_delta).isoformat()}
    return None


def update_meeting(event_id: str, changes: dict[str, Any]) -> Event:
    """Update a meeting and return the updated event."""

    connection = _connect()
    try:
        row = connection.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
        if row is None:
            raise EchoError(f"meeting not found: {event_id}")
        event = _row_to_event(row)
        payload = asdict(event)
        payload.update(changes)
        payload["attendees"] = list(payload.get("attendees", []))
        connection.execute(
            """
            UPDATE events
            SET title = ?, start = ?, end = ?, attendees = ?, platform = ?, description = ?, provider = ?, meeting_link = ?, created_at = ?
            WHERE id = ?
            """,
            (
                payload["title"],
                payload["start"],
                payload["end"],
                json.dumps(payload["attendees"]),
                payload["platform"],
                payload["description"],
                payload["provider"],
                payload["meeting_link"],
                payload["created_at"],
                event_id,
            ),
        )
        connection.commit()
        updated = connection.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
        assert updated is not None
        return _row_to_event(updated)
    finally:
        connection.close()


def cancel_meeting(event_id: str, notify_attendees: bool = True) -> OperationResult:
    """Cancel a meeting in the local calendar fallback."""

    connection = _connect()
    try:
        row = connection.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
        if row is None:
            return OperationResult(False, f"meeting not found: {event_id}", {"event_id": event_id})
        connection.execute("DELETE FROM events WHERE id = ?", (event_id,))
        connection.commit()
        _EVENT_BUS.publish_sync("echo.event_deleted", {"event_id": event_id, "notify_attendees": notify_attendees})
        return OperationResult(True, "meeting cancelled", {"event_id": event_id, "notify_attendees": notify_attendees})
    finally:
        connection.close()


def set_reminder(text: str, trigger_time: str, repeat: str | None = None) -> Reminder:
    """Persist a reminder and send a confirmation notification."""

    parsed_time = parse_natural_time(trigger_time) if not trigger_time.endswith("Z") and not trigger_time[:1].isdigit() else dateparser.parse(trigger_time).astimezone(timezone.utc).isoformat()
    reminder = Reminder(id=str(uuid.uuid4()), text=text, trigger_time=parsed_time, repeat=repeat, active=True, created_at=_now())
    connection = _connect()
    try:
        connection.execute(
            "INSERT INTO reminders VALUES (?, ?, ?, ?, ?, ?)",
            (reminder.id, reminder.text, reminder.trigger_time, reminder.repeat, 1, reminder.created_at),
        )
        connection.commit()
    finally:
        connection.close()
    try:
        from aura.memory import save_memory

        save_memory(
            key=f"reminder:{reminder.id}",
            value=text,
            category="tasks",
            tags=["reminder"],
            source="echo",
            confidence=1.0,
        )
    except Exception:
        LOGGER.info("reminder-memory-sync-failed", extra={"reminder_id": reminder.id})
    notification = send_notification("AURA reminder", text)
    if not notification.ok:
        LOGGER.info("reminder-notification-fallback", extra={"message": notification.message, "text": text})
    return reminder


def get_upcoming_reminders(hours_ahead: int = 24) -> list[Reminder]:
    """Return active reminders in the next N hours."""

    connection = _connect()
    try:
        now = datetime.now(timezone.utc)
        cutoff = now + timedelta(hours=hours_ahead)
        rows = connection.execute(
            "SELECT * FROM reminders WHERE active = 1 AND trigger_time >= ? AND trigger_time <= ? ORDER BY trigger_time ASC",
            (now.isoformat(), cutoff.isoformat()),
        ).fetchall()
        return [_row_to_reminder(row) for row in rows]
    finally:
        connection.close()


def join_meeting(link: str) -> OperationResult:
    """Open a meeting link using the platform default handler."""

    result = open_path(link)
    return OperationResult(result.ok, result.message, result.details)


def draft_email(to: list[str], subject: str, body: str, attachments: list[str] | None = None) -> EmailDraft:
    """Create a local email draft without sending it."""

    draft = EmailDraft(id=str(uuid.uuid4()), to=to, subject=subject, body=body, attachments=attachments or [], created_at=_now())
    connection = _connect()
    try:
        connection.execute(
            "INSERT INTO email_drafts VALUES (?, ?, ?, ?, ?, ?, 0)",
            (draft.id, json.dumps(draft.to), draft.subject, draft.body, json.dumps(draft.attachments), draft.created_at),
        )
        connection.commit()
        return draft
    finally:
        connection.close()


def send_email(draft_id: str) -> OperationResult:
    """Send a draft email using SMTP configuration if available."""

    if EMAIL_CONFIG is None:
        return OperationResult(False, "smtp-not-configured", {"draft_id": draft_id})
    connection = _connect()
    try:
        row = connection.execute("SELECT * FROM email_drafts WHERE id = ?", (draft_id,)).fetchone()
        if row is None:
            return OperationResult(False, f"draft not found: {draft_id}", {"draft_id": draft_id})
        draft = _row_to_draft(row)
        message = EmailMessage()
        message["Subject"] = draft.subject
        message["From"] = EMAIL_CONFIG["from_address"]
        message["To"] = ", ".join(draft.to)
        message.set_content(draft.body)
        with smtplib.SMTP_SSL(EMAIL_CONFIG["smtp_host"], int(EMAIL_CONFIG.get("smtp_port", 465))) as client:
            client.login(EMAIL_CONFIG["username"], EMAIL_CONFIG["password"])
            client.send_message(message)
        connection.execute("UPDATE email_drafts SET sent = 1 WHERE id = ?", (draft_id,))
        connection.commit()
        return OperationResult(True, "email sent", {"draft_id": draft_id})
    except Exception as exc:
        return OperationResult(False, str(exc), {"draft_id": draft_id})
    finally:
        connection.close()


def register_echo_tools() -> None:
    """Register ECHO tools in the global registry."""

    registry = get_tool_registry()
    specs = [
        ToolSpec("list_meetings", "List meetings in a date range.", 1, {"type": "object", "properties": {"date_range": {"type": "object"}}, "required": ["date_range"], "additionalProperties": False}, {"type": "array"}, lambda args: list_meetings(args["date_range"])),
        ToolSpec("create_meeting", "Create a meeting.", 2, {"type": "object", "properties": {"title": {"type": "string"}, "start": {"type": "string"}, "end": {"type": "string"}, "attendees": {"type": "array"}, "platform": {"type": "string"}, "description": {"type": "string"}}, "required": ["title", "start", "end", "attendees", "platform"], "additionalProperties": False}, {"type": "object"}, lambda args: create_meeting(args["title"], args["start"], args["end"], args["attendees"], args["platform"], args.get("description", ""))),
        ToolSpec("update_meeting", "Update a meeting.", 2, {"type": "object", "properties": {"event_id": {"type": "string"}, "changes": {"type": "object"}}, "required": ["event_id", "changes"], "additionalProperties": False}, {"type": "object"}, lambda args: update_meeting(args["event_id"], args["changes"])),
        ToolSpec("cancel_meeting", "Cancel a meeting.", 2, {"type": "object", "properties": {"event_id": {"type": "string"}, "notify_attendees": {"type": "boolean"}}, "required": ["event_id"], "additionalProperties": False}, {"type": "object"}, lambda args: cancel_meeting(args["event_id"], args.get("notify_attendees", True))),
        ToolSpec("set_reminder", "Set a reminder.", 1, {"type": "object", "properties": {"text": {"type": "string"}, "trigger_time": {"type": "string"}, "repeat": {"type": ["string", "null"]}}, "required": ["text", "trigger_time"], "additionalProperties": False}, {"type": "object"}, lambda args: set_reminder(args["text"], args["trigger_time"], args.get("repeat"))),
        ToolSpec("get_upcoming_reminders", "Fetch upcoming reminders.", 1, {"type": "object", "properties": {"hours_ahead": {"type": "integer"}}, "required": [], "additionalProperties": False}, {"type": "array"}, lambda args: get_upcoming_reminders(args.get("hours_ahead", 24))),
        ToolSpec("join_meeting", "Open a meeting link.", 1, {"type": "object", "properties": {"link": {"type": "string"}}, "required": ["link"], "additionalProperties": False}, {"type": "object"}, lambda args: join_meeting(args["link"])),
        ToolSpec("draft_email", "Create an email draft.", 1, {"type": "object", "properties": {"to": {"type": "array"}, "subject": {"type": "string"}, "body": {"type": "string"}, "attachments": {"type": ["array", "null"]}}, "required": ["to", "subject", "body"], "additionalProperties": False}, {"type": "object"}, lambda args: draft_email(args["to"], args["subject"], args["body"], args.get("attachments"))),
        ToolSpec("send_email", "Send an email draft.", 2, {"type": "object", "properties": {"draft_id": {"type": "string"}}, "required": ["draft_id"], "additionalProperties": False}, {"type": "object"}, lambda args: send_email(args["draft_id"])),
        ToolSpec("parse_natural_time", "Parse a natural language time expression.", 1, {"type": "object", "properties": {"expression": {"type": "string"}}, "required": ["expression"], "additionalProperties": False}, {"type": "string"}, lambda args: parse_natural_time(args["expression"])),
    ]
    for spec in specs:
        try:
            registry.register(spec)
        except ValueError:
            continue


register_echo_tools()
