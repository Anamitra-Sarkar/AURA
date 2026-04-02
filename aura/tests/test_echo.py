from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import pytest

from aura.agents.echo import tools as echo
from aura.agents.echo.models import EmailDraft
from aura.core.config import AppConfig, FeatureFlags, ModelSettings, PathsSettings


@dataclass
class FakeNotification:
    ok: bool = True
    message: str = "sent"


class FakeSMTP:
    def __init__(self, host, port):
        self.host = host
        self.port = port
        self.logged_in = False
        self.sent = False

    def login(self, username, password):
        self.logged_in = True

    def send_message(self, message):
        self.sent = True

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


@pytest.fixture()
def echo_config(tmp_path):
    config = AppConfig(
        name="AURA",
        offline_mode=True,
        log_level="INFO",
        primary_model=ModelSettings(provider="ollama", name="llama3", host="http://127.0.0.1:11434"),
        fallback_models=[],
        paths=PathsSettings(
            allowed_roots=[tmp_path],
            data_dir=tmp_path,
            log_dir=tmp_path / "logs",
            memory_dir=tmp_path / "memory",
            ipc_socket=tmp_path / "aura.sock",
        ),
        features=FeatureFlags(hotkey=True, tray=True, ipc=True, api=True),
        source_path=tmp_path / "config.yaml",
    )
    echo.CONFIG = config
    return config


def test_parse_natural_time_and_reminder_persistence(monkeypatch, echo_config):
    monkeypatch.setattr(echo, "notify_user", lambda *args, **kwargs: FakeNotification())
    iso = echo.parse_natural_time("tomorrow 9am")
    reminder = echo.set_reminder("Standup", "tomorrow 9am")
    upcoming = echo.get_upcoming_reminders(hours_ahead=48)
    assert iso.endswith("+00:00")
    assert reminder.text == "Standup"
    assert upcoming and upcoming[0].id == reminder.id


def test_create_update_list_and_cancel_meeting(echo_config):
    start = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    end = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
    meeting = echo.create_meeting("Planning", start, end, ["a@example.com"], "offline", "demo")
    meetings = echo.list_meetings({"start": (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat(), "end": (datetime.now(timezone.utc) + timedelta(hours=3)).isoformat()})
    updated = echo.update_meeting(meeting.id, {"title": "Planning 2"})
    cancelled = echo.cancel_meeting(meeting.id)
    meetings_after = echo.list_meetings({"start": (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat(), "end": (datetime.now(timezone.utc) + timedelta(hours=3)).isoformat()})

    assert meeting.provider == "local-sqlite"
    assert meetings and meetings[0].id == meeting.id
    assert updated.title == "Planning 2"
    assert cancelled.success is True
    assert meetings_after == []


def test_join_draft_and_send_email(monkeypatch, echo_config):
    monkeypatch.setattr(echo, "open_path", lambda link: type("Result", (), {"ok": True, "message": "opened", "details": {"link": link}})())
    draft = echo.draft_email(["a@example.com"], "Subject", "Body")
    assert isinstance(draft, EmailDraft)
    assert draft.subject == "Subject"

    echo.set_email_config({"smtp_host": "smtp.example.com", "smtp_port": 465, "username": "user", "password": "pass", "from_address": "user@example.com"})
    monkeypatch.setattr(echo.smtplib, "SMTP_SSL", FakeSMTP)
    send_result = echo.send_email(draft.id)
    join_result = echo.join_meeting("https://example.com/meet")

    assert send_result.success is True
    assert join_result.success is True


def test_send_email_without_config_and_invalid_time(echo_config):
    echo.set_email_config(None)
    result = echo.send_email("missing")
    assert result.success is False
    with pytest.raises(Exception):
        echo.parse_natural_time("not a time")
