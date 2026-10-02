"""Testhilfe für die Qt-Oberfläche: die App wie beim echten Start – Controller, QML und Fenster.

Die Tests laufen ohne Bildschirm (``QT_QPA_PLATFORM=offscreen``). Rückfragen beantwortet
``dialogs.AUTO_ANSWER``, Dateiauswahlen ``files.RESPONSES`` – ein echter Dialog öffnet sich nie.
Jede Meldung der QML-Engine (Warnung, Bindungsschleife, Fehler) landet in ``messages()``.
"""

from __future__ import annotations

import gc
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if sys.platform == "win32" and os.environ["QT_QPA_PLATFORM"] == "offscreen":
    # »offscreen« findet unter Windows keine Schriften von selbst – ohne sie wären Textmaße falsch
    os.environ.setdefault("QT_QPA_FONTDIR", os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts"))


def qt_application():
    """Die eine QApplication des Testprozesses (Stil »Basic« wie in der App)."""
    from qtapp import application as appmod

    app = appmod.create_application([])
    if os.environ.get("PDFTOOL_LAYOUT_DEBUG"):
        _layout_diagnostics()
    return app


_LAYOUT_TRACE: list[str] = []
_DIAG_WINDOWS: list = []


def _layout_diagnostics() -> None:
    """Nur zur Fehlersuche (``PDFTOOL_LAYOUT_DEBUG=1``, z. B. in der Absturzanalyse der CI):
    Qt Quick Layouts schreibt seine Schritte mit; meldet ein Layout »Detected recursive
    rearrange«, stehen die letzten Schritte und alle Karten (Titel, Adresse des Inhalts, Größen)
    in der Ausgabe – die Warnung selbst nennt nur Datei und Zeile, nicht die Karte."""
    if _LAYOUT_TRACE:
        return
    from PySide6.QtCore import QLoggingCategory, QtMsgType, qInstallMessageHandler

    _LAYOUT_TRACE.append("")

    def handler(mode, context, message) -> None:
        text = str(message)
        category = str(context.category) if context is not None and context.category else ""
        if mode == QtMsgType.QtDebugMsg:
            if category.startswith("qt.quick.layouts"):
                _LAYOUT_TRACE.append(text)
                del _LAYOUT_TRACE[1:-150]
            return
        print(text, file=sys.stderr)
        if "recursive rearrange" in text:
            print("=== Qt Quick Layouts: letzte Schritte ===", file=sys.stderr)
            for line in _LAYOUT_TRACE[1:]:
                print("  " + line, file=sys.stderr)
            print("=== Karten (PCard): Titel · Adresse des Inhalts · Größe · implizite Größe ===", file=sys.stderr)
            for window in _DIAG_WINDOWS:
                for card in _cards(window):
                    print("  " + card, file=sys.stderr)
            sys.stderr.flush()

    QLoggingCategory.setFilterRules("qt.quick.layouts.debug=true")
    qInstallMessageHandler(handler)


def _cards(window) -> list[str]:
    import shiboken6

    if not shiboken6.isValid(window):
        return []
    out = []
    stack = [window.contentItem()]
    while stack:
        item = stack.pop()
        stack.extend(item.childItems())
        if qml_type(item) != "PCard":
            continue
        try:  # Inhalt der Karte: zweites Element ihrer Spalte (Kopfzeile, Inhalt, Füller)
            body = item.childItems()[0].childItems()[1]
            address = hex(shiboken6.getCppPointer(body)[0])
        except (IndexError, RuntimeError):
            address = "?"
        out.append(f"{item.property('title')!r} · {address} · {item.width():.1f}×{item.height():.1f} · "
                   f"{item.implicitWidth():.1f}×{item.implicitHeight():.1f} · sichtbar {item.isVisible()}")
    return out


def process_events(ms: int = 20) -> None:
    from PySide6.QtCore import QCoreApplication, QEventLoop

    QCoreApplication.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, ms)


def pump(seconds: float = 0.3) -> None:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        process_events()
        time.sleep(0.004)


def qml_type(item) -> str:
    """QML-Typ eines Elements (»PButton«, »PCard«, »QQuickText« …) aus seiner JavaScript-Darstellung.

    Bewusst nicht über ``metaObject()``: PySide hängt dessen Rückgabe an den Wrapper des Elements.
    Überlebt der Wrapper die QML-Engine (z. B. im Traceback eines fehlgeschlagenen Tests), liefert
    PySide später für ein neues Element an derselben Adresse dieses veraltete QMetaObject – und
    ein fehlgeschlagener Test zöge weitere mit.
    """
    from PySide6.QtQml import QQmlEngine

    context = QQmlEngine.contextForObject(item)
    if context is None or context.engine() is None:
        return ""  # nicht aus QML (z. B. die Inhaltsebene des Fensters)
    return context.engine().toScriptValue(item).toString().split("(", 1)[0].split("_QML", 1)[0]


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
        appmod.prepare_data()  # wie beim echten Start: vorbereitete Wiederherstellung zuerst
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
        self.templates = rt.contracts.templates
        self.rules = rt.contracts.rules
        self.backup = rt.backup
        self.diagnose = rt.diagnose
        self.updates = rt.updates
        self.repair = rt.repair.controller
        self.engine = None
        self.window = None
        if ui:
            self.engine = appmod.create_engine(rt)
            self.window = appmod.show_window(rt, self.engine)
            if _LAYOUT_TRACE:
                _DIAG_WINDOWS[:] = [self.window]
            self.window.resize(*size)
            wait_until(lambda: self.app.ready, 10)
            self.wait_pages()
            pump(0.1)

    PAGES = ("home", "reader", "create", "layout", "preview", "templates", "rules", "batch", "comparison", "customers", "repair", "settings")

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
            # Noch entstehende QML-Objekte fertig bauen – nie die Engine mitten in ihrer Entstehung abbauen
            self.appmod.finish_incubation(self.engine)
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
