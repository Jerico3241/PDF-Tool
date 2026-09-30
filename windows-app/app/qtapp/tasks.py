"""Hintergrundarbeit ohne blockierte Oberfläche.

Schwere Arbeit (Excel-Prüfung, PDF-Erzeugung, Vorschau, Stapel, Hashing) läuft in Threads.
Threads berühren nie QML-Objekte: Ergebnisse, Fehler und Zwischenmeldungen kommen über ein
Qt-Signal (queued) im GUI-Thread an und werden dort ausgewertet.
"""

from __future__ import annotations

import threading
import traceback
from typing import Any, Callable

from PySide6.QtCore import QObject, Qt, Signal


class Worker(QObject):
    """``run(func, on_done, on_error)`` im Hintergrund, ``post(callback, *args)`` aus Threads."""

    _deliver = Signal(object)

    def __init__(self, parent: QObject | None = None, on_exception: Callable[[str], None] | None = None) -> None:
        super().__init__(parent)
        self._active = 0
        self._closed = False
        self._on_exception = on_exception
        self._deliver.connect(self._handle, Qt.ConnectionType.QueuedConnection)

    def run(self, func: Callable[[], Any], on_done: Callable[[Any], None] | None = None, on_error: Callable[[BaseException, str], None] | None = None) -> None:
        self._active += 1

        def target() -> None:
            try:
                result = func()
            except BaseException as exc:  # noqa: BLE001 - Fehler gehen an die Oberfläche
                self._deliver.emit((on_error, (exc, traceback.format_exc()), True))
            else:
                self._deliver.emit((on_done, (result,), True))

        threading.Thread(target=target, name="pdftool-arbeit", daemon=True).start()

    def post(self, callback: Callable[..., None], *args: Any) -> None:
        """Aus einem Hintergrund-Thread: ``callback(*args)`` im GUI-Thread ausführen."""
        self._deliver.emit((callback, args, False))

    def _handle(self, payload) -> None:
        callback, args, finished = payload
        if finished:
            self._active = max(0, self._active - 1)
        if self._closed or callback is None:
            return
        try:
            callback(*args)
        except Exception:  # noqa: BLE001 - ein Fehler in einer Rückmeldung darf die App nicht beenden
            text = traceback.format_exc()
            if self._on_exception is not None:
                self._on_exception(text)
            else:
                traceback.print_exc()

    def busy(self) -> bool:
        return self._active > 0

    def shutdown(self) -> None:
        """Beim Beenden: Ergebnisse laufender Aufgaben verfallen (nichts läuft nach dem Schließen weiter)."""
        self._closed = True
        self._active = 0
