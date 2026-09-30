"""Testhilfe für die Qt-Oberfläche: die App wie beim echten Start – Controller, QML und Fenster.

Die Tests laufen ohne Bildschirm (``QT_QPA_PLATFORM=offscreen``). Rückfragen beantwortet
``dialogs.AUTO_ANSWER``, Dateiauswahlen ``files.RESPONSES`` – ein echter Dialog öffnet sich nie.
Jede Meldung der QML-Engine (Warnung, Bindungsschleife, Fehler) landet in ``messages()``.
"""

from __future__ import annotations

import gc
import os
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def qt_application():
    """Die eine QApplication des Testprozesses (Stil »Basic« wie in der App)."""
    from qtapp import application as appmod

    return appmod.create_application([])


def process_events(ms: int = 20) -> None:
    from PySide6.QtCore import QCoreApplication, QEventLoop

    QCoreApplication.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, ms)


def pump(seconds: float = 0.3) -> None:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        process_events()
        time.sleep(0.004)


def wait_until(condition, timeout: float = 60.0) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        process_events()
        if condition():
            return True
        time.sleep(0.01)
    return bool(condition())


class Harness:
    """Laufende App: ``runtime`` mit allen Controllern, optional QML-Oberfläche im Fenster."""

    def __init__(self, ui: bool = True, size: tuple[int, int] = (1180, 860)) -> None:
        from appstate import load_config
        from qtapp import application as appmod

        self.appmod = appmod
        self.qt = qt_application()
        appmod.MESSAGES.clear()
        self.runtime = appmod.Runtime(load_config())
        rt = self.runtime
        self.app = rt.app
        self.theme = rt.theme
        self.settings = rt.settings
        self.contracts = rt.contracts
        self.overview = rt.contracts.overview
        self.customers = rt.contracts.customers
        self.preview = rt.contracts.preview
        self.batch = rt.contracts.batch
        self.comparison = rt.contracts.comparison
        self.repair = rt.repair.controller
        self.engine = None
        self.window = None
        if ui:
            self.engine = appmod.create_engine(rt)
            self.window = appmod.show_window(rt, self.engine)
            self.window.resize(*size)
            wait_until(lambda: self.app.ready, 10)
            self.wait_pages()
            pump(0.1)

    PAGES = ("home", "create", "layout", "preview", "batch", "comparison", "customers", "repair", "settings")

    def wait_pages(self, timeout: float = 20.0) -> bool:
        """Warten, bis alle verfügbaren Seiten im Hintergrund geladen sind (wie nach dem Start)."""

        def loaded() -> bool:
            for key in self.PAGES:
                if key in self.app.unavailablePages:
                    continue
                slot = self.item(f"page_{key}")
                if slot is None or slot.property("item") is None:  # Seite noch nicht fertig
                    return False
            return True

        return wait_until(loaded, timeout)

    # Oberfläche ------------------------------------------------------------------------------
    def item(self, name: str):
        """QML-Element mit ``objectName`` (oder ``None``) – sucht im Elementbaum des Fensters,
        auch in Seiten, die ein Loader erzeugt hat (sie hängen nicht im QObject-Baum)."""
        found = self.items(name)
        return found[0] if found else None

    def items(self, name: str) -> list:
        from PySide6.QtCore import QObject

        if self.window is None:
            return []
        result = []
        stack = [self.window.contentItem()]
        while stack:
            current = stack.pop()
            if current.objectName() == name:
                result.append(current)
            stack.extend(reversed(current.childItems()))
        if not result:
            other = self.window.findChild(QObject, name)
            if other is not None:
                result.append(other)
        return result

    def messages(self) -> list[str]:
        return list(self.appmod.MESSAGES)

    def shot(self, path: str | Path) -> None:
        if self.window is not None:
            self.window.grabWindow().save(str(path))

    def navigate(self, page: str, settle: float = 0.25) -> None:
        self.app.navigate(page)
        pump(settle)

    # Lebenszyklus -----------------------------------------------------------------------------
    def close(self) -> None:
        """Wie beim Beenden: Werkzeuge schließen, Einstellungen speichern, Fenster und Engine freigeben."""
        try:
            self.app.shutdown()
        finally:
            if self.window is not None:
                self.window.close()
                self.window = None
            import shiboken6

            engine, self.engine = self.engine, None
            if engine is not None:
                # Sofort löschen: Seiten, die noch im Hintergrund entstehen, werden verworfen.
                shiboken6.delete(engine)
                del engine
            pump(0.05)
            # Controller im GUI-Thread löschen – nie später durch die Speicherbereinigung eines
            # Hintergrund-Threads (Qt-Objekte dürfen nur in ihrem Thread enden).
            runtime, self.runtime = self.runtime, None
            if runtime is not None and shiboken6.isValid(runtime):
                shiboken6.delete(runtime)
            del runtime
            gc.collect()
            pump(0.02)

    def restart(self, ui: bool | None = None) -> "Harness":
        """Schließen (speichert wie beim Beenden) und mit derselben Konfiguration neu starten."""
        with_ui = self.window is not None if ui is None else ui
        self.close()
        return Harness(ui=with_ui)
