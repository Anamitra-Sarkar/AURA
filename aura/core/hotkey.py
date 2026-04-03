"""Global hotkey manager built around pynput."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

HotkeyCallback = Callable[[], None]


@dataclass(slots=True)
class HotkeyResult:
    """Structured result for hotkey operations."""

    ok: bool
    message: str
    details: dict[str, Any] | None = None


class GlobalHotkeyManager:
    """Register and manage a global hotkey listener."""

    def __init__(self, combination: str = "<ctrl>+<space>", callback: HotkeyCallback | None = None, listener_factory: Callable[[dict[str, HotkeyCallback]], Any] | None = None) -> None:
        self.combination = combination
        self.callback = callback or (lambda: None)
        self.listener_factory = listener_factory
        self._listener: Any = None

    def start(self) -> HotkeyResult:
        """Start listening for the configured hotkey."""

        try:
            factory = self.listener_factory or self._default_factory()
            self._listener = factory({self.combination: self.callback})
            self._listener.start()
            return HotkeyResult(ok=True, message="hotkey-started", details={"combination": self.combination})
        except Exception as exc:
            return HotkeyResult(ok=False, message=str(exc), details={"combination": self.combination})

    def stop(self) -> HotkeyResult:
        """Stop listening for the configured hotkey."""

        try:
            if self._listener is not None:
                self._listener.stop()
                self._listener = None
            return HotkeyResult(ok=True, message="hotkey-stopped", details={"combination": self.combination})
        except Exception as exc:
            return HotkeyResult(ok=False, message=str(exc), details={"combination": self.combination})

    def _default_factory(self) -> Callable[[dict[str, HotkeyCallback]], Any]:
        try:
            from pynput import keyboard  # type: ignore
        except Exception as exc:  # pragma: no cover - optional dependency
            raise RuntimeError("pynput-unavailable") from exc
        return keyboard.GlobalHotKeys
