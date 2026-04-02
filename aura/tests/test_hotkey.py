from __future__ import annotations

from aura.core.hotkey import GlobalHotkeyManager


class FakeListener:
    def __init__(self, mapping):
        self.mapping = mapping
        self.started = False
        self.stopped = False

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True


def test_hotkey_manager_uses_listener_factory():
    fake = FakeListener({})
    manager = GlobalHotkeyManager(listener_factory=lambda mapping: fake)
    start = manager.start()
    stop = manager.stop()
    assert start.ok is True
    assert stop.ok is True
    assert fake.started is True
    assert fake.stopped is True
