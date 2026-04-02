"""Structured JSON logging utilities for AURA."""

from __future__ import annotations

import json
import logging
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


@dataclass(slots=True)
class LogContext:
    """Additional structured fields for a log entry."""

    component: str
    event: str | None = None


class JsonFormatter(logging.Formatter):
    """Format log records as JSON lines."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        component = getattr(record, "component", None)
        if component is not None:
            payload["component"] = component
        event = getattr(record, "event", None)
        if event is not None:
            payload["event"] = event
        extra = {
            key: value
            for key, value in record.__dict__.items()
            if key
            not in {
                "name",
                "msg",
                "args",
                "levelname",
                "levelno",
                "pathname",
                "filename",
                "module",
                "exc_info",
                "exc_text",
                "stack_info",
                "lineno",
                "funcName",
                "created",
                "msecs",
                "relativeCreated",
                "thread",
                "threadName",
                "processName",
                "process",
                "message",
                "asctime",
                "component",
                "event",
            }
        }
        if extra:
            payload["extra"] = extra
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str, ensure_ascii=True)


def configure_logging(level: str = "INFO", stream: Any | None = None) -> None:
    """Configure the root logger for JSON output."""

    handler = logging.StreamHandler(stream or sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level.upper())
    root.propagate = False


def get_logger(name: str, component: str | None = None) -> logging.LoggerAdapter:
    """Return a logger adapter that injects a component tag."""

    base_logger = logging.getLogger(name)
    return logging.LoggerAdapter(base_logger, {"component": component or name})
