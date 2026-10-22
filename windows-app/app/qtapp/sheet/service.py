"""Rechenkern der Tabellen für die Oberfläche: ein eigener Thread schickt die Befehle nacheinander an LibreOffice.

``submit(Befehl, Argumente, fertig, Fehler)`` reiht einen Befehl ein; das Ergebnis kommt im GUI-Thread an. Der Kern
startet beim ersten Befehl (einige Sekunden) und läuft, bis Novadesk endet. Stürzt er ab, meldet ``lost`` das allen
geöffneten Tabellen (``generation`` zählt die Starts) – der nächste Befehl startet ihn neu.
"""

from __future__ import annotations

import logging
import queue
import threading
import traceback
from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import QObject, Signal

from tools.pdf_editor import office
from tools.sheet import engine as calc

_STOP = object()


def _log():
    return logging.getLogger("pdftool.tabelle")


class CalcService(QObject):
    lost = Signal(int)  # Kern abgestürzt: Nummer des Starts, dessen Dokumente fort sind
    startingChanged = Signal(bool)

    def __init__(self, app, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.app = app
        self.engine = calc.Engine()
        self.generation = 0
        self._queue: queue.Queue = queue.Queue()
        self._thread: threading.Thread | None = None
        self._closed = False
        self.fonts_loaded = False
        app.at_shutdown(self.stop)

    @staticmethod
    def available() -> bool:
        return office.libreoffice() is not None

    def submit(self, command: str, args: dict | None = None, done: Callable[[Any], None] | None = None,
               failed: Callable[[BaseException], None] | None = None, *, generation: int | None = None) -> None:
        """Befehl einreihen. ``generation``: nur ausführen, wenn der Kern seit diesem Start läuft (sonst ``failed`` mit
        ``EngineGone``) – die Dokumentnummern eines abgestürzten Kerns gelten nicht mehr."""
        if self._closed:
            return
        if self._thread is None:
            self._thread = threading.Thread(target=self._loop, name="novadesk-tabelle", daemon=True)
            self._thread.start()
        self._queue.put((command, dict(args or {}), done, failed, generation))

    def _loop(self) -> None:
        while True:
            job = self._queue.get()
            if job is _STOP:
                return
            command, args, done, failed, generation = job
            try:
                if not self.engine.running:
                    if generation is not None:
                        raise calc.EngineGone()
                    self.app.worker.post(self._set_starting, True)
                    try:
                        self.engine.start()
                    finally:
                        self.app.worker.post(self._set_starting, False)
                    self.generation += 1
                    _log().info("Rechenkern gestartet (%d)", self.generation)
                if generation is not None and generation != self.generation:
                    raise calc.EngineGone()
                result = self.engine.call(command, **args)
            except calc.EngineGone as exc:
                was = self.generation
                if was and not self._closed:
                    _log().warning("Rechenkern nicht erreichbar (%s): %s", command, exc)
                    self.app.worker.post(self._lost, was)
                if failed is not None:
                    self.app.worker.post(failed, exc)
                continue
            except calc.CalcError as exc:
                if exc.code == "intern":
                    _log().warning("Rechenkern: interner Fehler bei %s: %s", command, exc)
                if failed is not None:
                    self.app.worker.post(failed, exc)
                continue
            except Exception as exc:  # noqa: BLE001 - Fehler gehen an die Oberfläche, der Thread läuft weiter
                _log().warning("Rechenkern: %s bei %s", type(exc).__name__, command)
                self.app.worker.post(self.app.report_exception, traceback.format_exc())
                if failed is not None:
                    self.app.worker.post(failed, exc)
                continue
            if done is not None:
                self.app.worker.post(done, result)

    def _set_starting(self, value: bool) -> None:
        self.startingChanged.emit(value)

    def _lost(self, generation: int) -> None:
        self.lost.emit(generation)

    def stop(self) -> None:
        """Beim Beenden: Warteschlange leeren, LibreOffice beenden (Dokumente ohne Speichern schließen)."""
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

    def load_fonts(self) -> None:
        """Schriften aus LibreOffice auch für die Anzeige: Carlito (gleich breit wie Calibri), Caladea (Cambria),
        Liberation (Arial, Times New Roman, Courier New) – fehlt die Originalschrift, zeigt Novadesk die Entsprechung."""
        if self.fonts_loaded:
            return
        self.fonts_loaded = True
        from PySide6.QtGui import QFont, QFontDatabase

        executable = office.libreoffice()
        if executable is None:
            return
        folder = Path(executable).resolve().parent.parent / "share" / "fonts" / "truetype"
        if not folder.is_dir():
            return
        families = set(QFontDatabase.families())
        for pattern in ("Carlito-*.ttf", "Caladea-*.ttf", "LiberationSans-*.ttf", "LiberationSerif-*.ttf", "LiberationMono-*.ttf"):
            for path in sorted(folder.glob(pattern)):
                QFontDatabase.addApplicationFont(str(path))
        for original, replacement in (("Calibri", "Carlito"), ("Cambria", "Caladea"), ("Arial", "Liberation Sans"),
                                      ("Times New Roman", "Liberation Serif"), ("Courier New", "Liberation Mono")):
            if original not in families:
                QFont.insertSubstitution(original, replacement)
