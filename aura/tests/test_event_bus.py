from __future__ import annotations

import pytest

from aura.core.event_bus import EventBus


@pytest.mark.asyncio
async def test_event_bus_publish():
    bus = EventBus()
    seen = []

    async def handler(topic, payload):
        seen.append((topic, payload))

    await bus.subscribe("topic", handler)
    result = await bus.publish("topic", {"value": 1})
    assert result.ok is True
    assert seen == [("topic", {"value": 1})]
