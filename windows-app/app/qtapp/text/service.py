"""Textkern für die Oberfläche: ein eigener Thread schickt die Befehle an den Kern (``tools.text.engine``).

``submit(Befehl, Argumente, fertig, Fehler, priority=…)`` reiht einen Befehl ein; das Ergebnis kommt im GUI-Thread an.
Eingaben (Tasten, Klicks, Befehle) gehen vor Kacheln: Wer tippt, wartet nicht auf das Zeichnen. Ereignisse des Kerns
(``event``) kommen ebenfalls im GUI-Thread an. Der Kern startet beim ersten Befehl und läuft, bis Novadesk endet.
Stürzt er ab, meldet ``lost`` das allen geöffneten Texten (``generation`` zählt die Starts) – der nächste Befehl
startet ihn neu.
"""

from __future__ import annotations

import itertools
import logging
import queue
import threading
import traceback
from typing import Any, Callable

from PySide6.QtCore import QObject, Signal

from tools.text import engine as text

INPUT, NORMAL, TILE = 0, 1, 2  # Vorrang: Eingaben, übrige Befehle, Kacheln
_STOP = (-1, -1, None)


def _log():
    return logging.getLogger("pdftool.text")


class TextService(QObject):
    lost = Signal(int)  # Kern abgestürzt: Nummer des Starts, dessen Dokumente fort sind
    startingChanged = Signal(bool)
    event = Signal(int, int, int, str)  # Start, Dokument, Art, Inhalt

    def __init__(self, app, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.app = app
        self.engine = text.Engine(self._on_event)
        self.generation = 0
        self._queue: queue.PriorityQueue = queue.PriorityQueue()
        self._order = itertools.count()
        self._thread: threading.Thread | None = None
        self._closed = False
        # Ereignisse eines Dokuments, bevor es jemandem gehört (beim Laden: Schreibmarke, Zustand der Knöpfe)
        self._claimed: set[tuple[int, int]] = set()
        self._early: dict[tuple[int, int], list[tuple[int, str]]] = {}
        app.at_shutdown(self.stop)

    def submit(self, command: str, args: dict | None = None, done: Callable[[Any], None] | None = None,
               failed: Callable[[BaseException], None] | None = None, *, generation: int | None = None,
               priority: int = NORMAL) -> None:
        """Befehl einreihen. ``generation``: nur ausführen, wenn der Kern seit diesem Start läuft (sonst ``failed`` mit
        ``EngineGone``) – die Dokumentnummern eines abgestürzten Kerns gelten nicht mehr."""
        if self._closed:
            return
        if self._thread is None:
            self._thread = threading.Thread(target=self._loop, name="novadesk-text", daemon=True)
            self._thread.start()
        self._queue.put((priority, next(self._order), (command, dict(args or {}), done, failed, generation)))

    def _on_event(self, doc: int, kind: int, payload: str) -> None:
        # Lese-Thread des Kerns → GUI-Thread
        self.app.worker.post(self._emit_event, self.generation, doc, kind, payload)

    def _emit_event(self, generation: int, doc: int, kind: int, payload: str) -> None:
        if (generation, doc) not in self._claimed:
            early = self._early.setdefault((generation, doc), [])
            if len(early) < 5000:
                early.append((kind, payload))
            return
        self.event.emit(generation, doc, kind, payload)

    def claim(self, generation: int, doc: int) -> list[tuple[int, str]]:
        """Ein Dokument gehört ab jetzt einem Text: seine bisherigen Ereignisse (zum Nachholen) und ab jetzt ``event``."""
        self._claimed.add((generation, doc))
        return self._early.pop((generation, doc), [])

    def release(self, generation: int, doc: int) -> None:
        self._claimed.discard((generation, doc))
        self._early.pop((generation, doc), None)

    def _loop(self) -> None:
        while True:
            _priority, _order, job = self._queue.get()
            if job is None:
                return
            command, args, done, failed, generation = job
            try:
                if not self.engine.running:
                    if generation is not None:
                        raise text.EngineGone()
                    self.app.worker.post(self.startingChanged.emit, True)
                    try:
                        self.engine.start()
                    finally:
                        self.app.worker.post(self.startingChanged.emit, False)
                    self.generation += 1
                    _log().info("Textkern gestartet (%d)", self.generation)
                if generation is not None and generation != self.generation:
                    raise text.EngineGone()
                result = self.engine.call(command, **args)
            except text.EngineGone as exc:
                was = self.generation
                if was and not self._closed:
                    _log().warning("Textkern nicht erreichbar (%s): %s %s", command, exc, getattr(exc, "detail", ""))
                    self.app.worker.post(self.lost.emit, was)
                if failed is not None:
                    self.app.worker.post(failed, exc)
                continue
            except text.TextError as exc:
                if exc.code == "intern":
                    _log().warning("Textkern: interner Fehler bei %s: %s", command, exc)
                if failed is not None:
                    self.app.worker.post(failed, exc)
                continue
            except Exception as exc:  # noqa: BLE001 - Fehler gehen an die Oberfläche, der Thread läuft weiter
                _log().warning("Textkern: %s bei %s", type(exc).__name__, command)
                self.app.worker.post(self.app.report_exception, traceback.format_exc())
                if failed is not None:
                    self.app.worker.post(failed, exc)
                continue
            if done is not None:
                self.app.worker.post(done, result)

    def stop(self) -> None:
        """Beim Beenden: Warteschlange leeren, den Kern beenden (Dokumente ohne Speichern schließen)."""
        if self._closed:
            return
        self._closed = True
        try:
            while True:
                self._queue.get_nowait()
        except queue.Empty:
            pass
        self.engine.closed = True
        thread = self._thread
        self._queue.put(_STOP)
        if thread is not None:
            thread.join(timeout=10)
        self.engine.stop()
