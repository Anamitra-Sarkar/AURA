from __future__ import annotations

from aura.core.tray import TrayController


class FakeIcon:
    def __init__(self):
        self.started = False
        self.stopped = False

    def run_detached(self):
        self.started = True

    def stop(self):
        self.stopped = True


def test_tray_controller_lifecycle():
    icon = FakeIcon()
    tray = TrayController(icon_factory=lambda: icon)
    start = tray.start()
    stop = tray.stop()
    assert start.ok is True
    assert stop.ok is True
    assert icon.started is True
    assert icon.stopped is True
