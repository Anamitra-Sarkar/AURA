"""Simple async publish/subscribe event bus."""

from __future__ import annotations

import asyncio
import inspect
from dataclasses import dataclass, field
from typing import Any, Callable

EventHandler = Callable[[str, Any], Any]


@dataclass(slots=True)
class PublishResult:
    """Result from publishing an event."""

    ok: bool
    topic: str
    delivered: int = 0
    errors: list[str] = field(default_factory=list)


class EventBus:
    """In-memory pub/sub event bus."""

    def __init__(self) -> None:
        self._topics: dict[str, dict[str, EventHandler]] = {}
        self._lock = asyncio.Lock()
        self._token_counter = 0

    async def subscribe(self, topic: str, handler: EventHandler) -> str:
        """Subscribe a handler to a topic and return a token."""

        async with self._lock:
            self._token_counter += 1
            token = f"sub-{self._token_counter}"
            self._topics.setdefault(topic, {})[token] = handler
            return token

    async def unsubscribe(self, topic: str, token: str) -> bool:
        """Remove a subscription from a topic."""

        async with self._lock:
            handlers = self._topics.get(topic)
            if not handlers or token not in handlers:
                return False
            del handlers[token]
            if not handlers:
                self._topics.pop(topic, None)
            return True

    async def publish(self, topic: str, payload: Any) -> PublishResult:
        """Publish a payload to all subscribers of a topic."""

        async with self._lock:
            handlers = list(self._topics.get(topic, {}).values())
        delivered = 0
        errors: list[str] = []
        for handler in handlers:
            try:
                outcome = handler(topic, payload)
                if inspect.isawaitable(outcome):
                    await outcome
                delivered += 1
            except Exception as exc:
                errors.append(str(exc))
        return PublishResult(ok=not errors, topic=topic, delivered=delivered, errors=errors)
