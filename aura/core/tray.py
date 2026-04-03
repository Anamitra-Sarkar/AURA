"""System tray controller built around pystray."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

TrayFactory = Callable[[], Any]


@dataclass(slots=True)
class TrayResult:
    """Structured result for tray operations."""

    ok: bool
    message: str
    details: dict[str, Any] | None = None


class TrayController:
    """Manage a simple tray icon lifecycle."""

    def __init__(self, icon_factory: TrayFactory | None = None) -> None:
        self.icon_factory = icon_factory
        self._icon: Any = None

    def start(self) -> TrayResult:
        """Start the tray icon."""

        try:
            factory = self.icon_factory or self._default_factory()
            self._icon = factory()
            self._icon.run_detached()
            return TrayResult(ok=True, message="tray-started")
        except Exception as exc:
            return TrayResult(ok=False, message=str(exc))

    def stop(self) -> TrayResult:
        """Stop the tray icon."""

        try:
            if self._icon is not None:
                self._icon.stop()
                self._icon = None
            return TrayResult(ok=True, message="tray-stopped")
        except Exception as exc:
            return TrayResult(ok=False, message=str(exc))

    def _default_factory(self) -> Callable[[], Any]:
        try:
            import pystray  # type: ignore
        except Exception as exc:  # pragma: no cover - optional dependency
            raise RuntimeError("pystray-unavailable") from exc
        return lambda: pystray.Icon("AURA")
