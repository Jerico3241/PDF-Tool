"""Benannte, abbrechbare Zeitgeber (Entprellen, verzögertes Speichern, Ausblenden von Hinweisen)."""

from __future__ import annotations

import traceback
from typing import Callable

from PySide6.QtCore import QObject, QTimer


class Timers(QObject):
    """``later(key, ms, func)`` ersetzt einen gleichnamigen Zeitgeber – je Schlüssel läuft höchstens einer."""

    def __init__(self, parent: QObject | None = None, on_exception: Callable[[str], None] | None = None) -> None:
        super().__init__(parent)
        self._timers: dict[str, QTimer] = {}
        self._closed = False
        self._on_exception = on_exception

    def later(self, key: str, delay_ms: int, func: Callable[[], None]) -> None:
        if self._closed:
            return
        self.cancel(key)
        timer = QTimer(self)
        timer.setSingleShot(True)

        def fire() -> None:
            if self._timers.get(key) is timer:
                del self._timers[key]
            timer.deleteLater()
            try:
                func()
            except Exception:  # noqa: BLE001 - Fehler im Zeitgeber melden, nicht abstürzen
                text = traceback.format_exc()
                if self._on_exception is not None:
                    self._on_exception(text)
                else:
                    traceback.print_exc()

        timer.timeout.connect(fire)
        self._timers[key] = timer
        timer.start(max(0, int(delay_ms)))

    def soon(self, key: str, func: Callable[[], None]) -> None:
        """Gesammelt im nächsten Durchlauf der Ereignisschleife (wie ``after_idle``) – nur einmal je Schlüssel."""
        if key not in self._timers:
            self.later(key, 0, func)

    def cancel(self, key: str) -> None:
        timer = self._timers.pop(key, None)
        if timer is not None:
            timer.stop()
            timer.deleteLater()

    def pending(self, key: str) -> bool:
        return key in self._timers

    def count(self) -> int:
        return len(self._timers)

    def shutdown(self) -> None:
        self._closed = True
        for key in list(self._timers):
            self.cancel(key)
