"""ECHO calendar, reminder, and email tools."""

from __future__ import annotations

import json
import smtplib
import sqlite3
import uuid
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
import collections
from pathlib import Path
from typing import Any
from collections.abc import Iterable, Mapping, MutableMapping, Sequence

import dateparser
for _name, _value in {
    "Mapping": Mapping,
    "MutableMapping": MutableMapping,
    "Sequence": Sequence,
    "Iterable": Iterable,
}.items():
    if not hasattr(collections, _name):
        setattr(collections, _name, _value)
from ics import Calendar, Event as ICSEvent  # noqa: E402

from aura.core.config import AppConfig, load_config  # noqa: E402
from aura.core.event_bus import EventBus  # noqa: E402
from aura.core.logging import get_logger  # noqa: E402
from aura.core.platform import open_file, send_notification  # noqa: E402
from aura.core.tools import ToolSpec, get_tool_registry  # noqa: E402

from .models import EmailDraft, Event, OperationResult, Reminder  # noqa: E402

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


def _calendar_path() -> Path:
    """Return the ICS calendar path used by the new event tools."""

    path = Path.home() / ".aura" / "calendar.ics"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _parse_iso_datetime(value: str) -> datetime:
    """Parse an ISO-8601 datetime and normalize it to UTC."""

    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _event_datetime(value: Any) -> datetime | None:
    """Normalize an ics datetime/arrow wrapper to UTC."""

    if value is None:
        return None
    if hasattr(value, "datetime"):
        dt = getattr(value, "datetime")
    elif hasattr(value, "dt"):
        dt = getattr(value, "dt")
    else:
        dt = value
    if not isinstance(dt, datetime):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _load_calendar() -> Calendar:
    """Load the on-disk calendar, creating an empty one when missing."""

    path = _calendar_path()
    if not path.exists():
        calendar = Calendar()
        path.write_text(calendar.serialize(), encoding="utf-8")
        return calendar
    return Calendar(path.read_text(encoding="utf-8"))


def _save_calendar(calendar: Calendar) -> None:
    """Persist a calendar to disk."""

    _calendar_path().write_text(calendar.serialize(), encoding="utf-8")


def _event_payload(event: ICSEvent) -> dict[str, Any]:
    """Return a JSON-friendly event payload."""

    begin = _event_datetime(event.begin)
    end = _event_datetime(event.end)
    return {
        "uid": event.uid,
        "title": event.name,
        "start": begin.astimezone(timezone.utc).isoformat() if begin is not None else "",
        "end": end.astimezone(timezone.utc).isoformat() if end is not None else "",
        "description": event.description,
        "location": event.location,
    }


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


def create_event(title: str, start_iso: str, end_iso: str, description: str = "", location: str = "") -> str:
    """Create a calendar event in the local ICS file."""

    calendar = _load_calendar()
    event = ICSEvent(name=title, begin=_parse_iso_datetime(start_iso), end=_parse_iso_datetime(end_iso), description=description, location=location)
    calendar.events.add(event)
    _save_calendar(calendar)
    return str(event.uid)


def list_events(from_iso: str, to_iso: str) -> list[dict[str, Any]]:
    """List calendar events whose start time falls within the range."""

    start = _parse_iso_datetime(from_iso)
    end = _parse_iso_datetime(to_iso)
    calendar = _load_calendar()
    events = []
    for event in calendar.events:
        begin = _event_datetime(event.begin)
        if begin is None:
            continue
        if start <= begin <= end:
            events.append(_event_payload(event))
    events.sort(key=lambda item: item["start"])
    return events


def delete_event(event_uid: str) -> dict[str, Any]:
    """Delete an event by UID from the local ICS file."""

    calendar = _load_calendar()
    removed = False
    for event in list(calendar.events):
        if str(event.uid) == event_uid:
            calendar.events.remove(event)
            removed = True
            break
    if removed:
        _save_calendar(calendar)
        return {"deleted": True}
    return {"deleted": False, "reason": "not found"}


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


def find_free_slot(date_iso: str, duration_minutes: int = 60) -> str | None:
    """Find the first free slot on a day between 09:00 and 20:00 UTC."""

    if duration_minutes <= 0:
        return None
    day = _parse_iso_datetime(date_iso).date()
    window_start = datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc).replace(hour=9)
    window_end = datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc).replace(hour=20)
    target_delta = timedelta(minutes=duration_minutes)
    events = sorted(list_events(window_start.isoformat(), window_end.isoformat()), key=lambda item: item["start"])
    cursor = window_start
    for event in events:
        event_start = _parse_iso_datetime(event["start"])
        event_end = _parse_iso_datetime(event["end"])
        if event_start - cursor >= target_delta:
            return cursor.isoformat()
        if event_end > cursor:
            cursor = event_end
    if window_end - cursor >= target_delta:
        return cursor.isoformat()
    return None


def update_event(event_uid: str, title: str | None, start_iso: str | None, end_iso: str | None, description: str | None) -> dict[str, Any]:
    """Update a calendar event and rewrite the ICS file."""

    calendar = _load_calendar()
    for event in list(calendar.events):
        if str(event.uid) != event_uid:
            continue
        if title is not None:
            event.name = title
        if start_iso is not None:
            event.begin = _parse_iso_datetime(start_iso)
        if end_iso is not None:
            event.end = _parse_iso_datetime(end_iso)
        if description is not None:
            event.description = description
        _save_calendar(calendar)
        return {"updated": True, "event": _event_payload(event)}
    return {"updated": False, "reason": "not found"}


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
        ToolSpec("create_event", "Create a calendar event in the ICS file.", 1, {"type": "object", "properties": {"title": {"type": "string"}, "start_iso": {"type": "string"}, "end_iso": {"type": "string"}, "description": {"type": "string"}, "location": {"type": "string"}}, "required": ["title", "start_iso", "end_iso"], "additionalProperties": False}, {"type": "string"}, lambda args: create_event(args["title"], args["start_iso"], args["end_iso"], args.get("description", ""), args.get("location", ""))),
        ToolSpec("list_events", "List calendar events in a range.", 1, {"type": "object", "properties": {"from_iso": {"type": "string"}, "to_iso": {"type": "string"}}, "required": ["from_iso", "to_iso"], "additionalProperties": False}, {"type": "array"}, lambda args: list_events(args["from_iso"], args["to_iso"])),
        ToolSpec("delete_event", "Delete a calendar event by UID.", 2, {"type": "object", "properties": {"event_uid": {"type": "string"}}, "required": ["event_uid"], "additionalProperties": False}, {"type": "object"}, lambda args: delete_event(args["event_uid"])),
        ToolSpec("find_free_slot", "Find the first free calendar slot on a day.", 1, {"type": "object", "properties": {"date_iso": {"type": "string"}, "duration_minutes": {"type": "integer"}}, "required": ["date_iso"], "additionalProperties": False}, {"type": ["string", "null"]}, lambda args: find_free_slot(args["date_iso"], args.get("duration_minutes", 60))),
        ToolSpec("update_event", "Update a calendar event.", 2, {"type": "object", "properties": {"event_uid": {"type": "string"}, "title": {"type": ["string", "null"]}, "start_iso": {"type": ["string", "null"]}, "end_iso": {"type": ["string", "null"]}, "description": {"type": ["string", "null"]}}, "required": ["event_uid"], "additionalProperties": False}, {"type": "object"}, lambda args: update_event(args["event_uid"], args.get("title"), args.get("start_iso"), args.get("end_iso"), args.get("description"))),
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
