"""Einstellungen → »Diagnose« (in QML: ``Diagnose``).

* Systeminformationen: Version, Kanal, Python, Qt, Windows, Pfade, Module, Reparatur-Engines.
* Datenprüfung (im Hintergrund): Einstellungen, Kundenakten, Vorlagen, Regelwerke,
  Vertragsstände, Sicherungsordner, temporärer Ordner, freier Speicher.
* Support-Paket: Ordner wählen, ZIP erstellen – bereinigt, nie mit Kunden- oder Dokumentdaten.
  Es wird nichts versendet.
* Protokolle öffnen, eigene temporäre Dateien aufräumen (beim Start automatisch, nach 30 s).
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Property, QObject, Signal, Slot

from appstate import INSTALL_DIR, VERSION
from diagnostics import applog, checks, cleanup, info, support
from storage import data_root

from . import files
from .base import Observable, prop
from .models import KeyedListModel

AREA = "diagnose_info"
PENDING = "wird ermittelt …"
CLEANUP_DELAY = 30_000
STATUS_ICON = {checks.OK: "success", checks.INFO: "info", checks.WARNING: "caution", checks.ERROR: "critical"}


class DiagnoseController(Observable):
    factsChanged, facts = prop(list, "facts", [])
    resultsChanged, results = prop(list, "results", [])
    verdictChanged, verdict = prop(str, "verdict", "")
    verdictKindChanged, verdictKind = prop(str, "verdictKind", "neutral")
    lastRunChanged, lastRun = prop(str, "lastRun", "")
    busyChanged, busy = prop(bool, "busy", False)
    busyTextChanged, busyText = prop(str, "busyText", "")

    def __init__(self, app, backup, updates=None, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.app = app
        self.backup = backup  # BackupController: Ordner der Sicherungen
        self.updates = updates
        self.root = data_root()
        self._job = ""
        self.packages = 0  # Tests
        self.cleaned: list[str] = []
        self._facts_running = False
        # Systeminformationen erst beim Öffnen der Einstellungen (im Hintergrund – Importe dauern).
        # Die Zeilen stehen von Anfang an fest; danach ändern sich nur die Werte (kein Neuaufbau).
        self.fact_model = KeyedListModel(("key", "label", "value"), key="key", parent=self)
        self.fact_model.set_items([{"key": key, "label": label, "value": PENDING} for key, label in info.FACTS])
        app.observe("currentPage", lambda page: self.refreshFacts() if page == "settings" else None)

    def start(self) -> None:
        self.app.timers.later("diagnose:cleanup", CLEANUP_DELAY, self.cleanup_quietly)

    def running_work(self) -> str:
        return self._job

    def _channel(self) -> str:
        return getattr(self.updates, "channel", "stable") if self.updates is not None else "stable"

    @Slot()
    def refreshFacts(self) -> None:  # noqa: N802
        """Systeminformationen im Hintergrund bestimmen (der erste Aufruf lädt einige Module)."""
        if self._facts_running:
            return
        self._facts_running = True
        channel, root = self._channel(), self.root

        def done(facts) -> None:
            self._facts_running = False
            self.facts = [{"label": fact.label, "value": fact.value} for fact in facts]
            self.fact_model.set_items([{"key": fact.key, "label": fact.label, "value": fact.value} for fact in facts])

        def failed(_exc, text) -> None:
            self._facts_running = False
            self.app.write_error_log(text)

        self.app.worker.run(lambda: info.system_facts(VERSION, channel, root, INSTALL_DIR), done, failed)

    def _begin(self, job: str, text: str) -> bool:
        if self._job:
            return False
        self._job, self.busyText, self.busy = job, text, True
        return True

    def _end(self) -> None:
        self._job, self.busyText, self.busy = "", "", False

    # Datenprüfung -----------------------------------------------------------------------------------------------
    @Slot()
    def runChecks(self) -> None:  # noqa: N802
        root, folder = self.root, self.backup.folder()

        def done(found: list[checks.Check]) -> None:
            self._end()
            self._show(found)

        def failed(_exc, text) -> None:
            self._end()
            self.app.write_error_log(text)
            self.app.notify(AREA, "error", "Die Datenprüfung ist fehlgeschlagen (Details in fehler.log).")

        if self._begin("Datenprüfung", "Daten werden geprüft …"):
            self.refreshFacts()
            self.app.worker.run(lambda: checks.run_checks(root, folder), done, failed)

    def _show(self, found: list[checks.Check]) -> None:
        from datetime import datetime

        self.results = [{"label": check.label, "status": STATUS_ICON.get(check.status, "info"), "detail": check.detail} for check in found]
        kind, text = checks.summary(found)
        self.verdictKind = {checks.OK: "success", checks.WARNING: "warning", checks.ERROR: "error"}.get(kind, "info")
        self.verdict = text
        self.lastRun = datetime.now().strftime("Geprüft am %d.%m.%Y um %H:%M")
        applog.get("diagnose").info("Datenprüfung: %s", text)

    # Support-Paket ---------------------------------------------------------------------------------------------
    @Slot()
    def createPackage(self) -> None:  # noqa: N802
        folder = files.pick_folder("Ordner für das Support-Paket wählen", files.start_dir(str(Path.home() / "Documents")))
        if folder:
            self.create_package(folder)

    def create_package(self, folder: str) -> None:
        from . import application

        from storage import read_json

        self.app.persist()  # der aktuelle Stand der Einstellungen (anonymisiert) gehört dazu
        root, backups = self.root, self.backup.folder()
        facts = info.system_facts(VERSION, self._channel(), self.root, INSTALL_DIR)
        qml = list(application.MESSAGES)
        update_log = self._update_log()

        def work() -> Path:
            found = checks.run_checks(root, backups)
            cfg, _reason = read_json(root / "gui-config.json")
            return support.create_package(folder, root, INSTALL_DIR, VERSION, facts, found, cfg if isinstance(cfg, dict) else {}, qml, extra_logs=[update_log] if update_log else None)

        def done(path: Path) -> None:
            self._end()
            self.packages += 1
            applog.get("diagnose").info("Support-Paket erstellt: %s", path.name)
            self.app.notify(
                AREA,
                "success",
                f"Support-Paket „{path.name}“ erstellt. Es enthält keine Kunden- oder Dokumentdaten und wird nicht versendet – geben Sie es nur bei Bedarf selbst weiter.",
                actions=(("Ordner öffnen", lambda: self.app.open_folder_of(path, AREA)),),
                auto_hide=12000,
            )

        def failed(exc, text) -> None:
            self._end()
            self.app.write_error_log(text)
            reason = exc.strerror if isinstance(exc, OSError) and exc.strerror else "Details in fehler.log"
            self.app.notify(AREA, "error", f"Das Support-Paket konnte nicht erstellt werden ({reason}).")

        if self._begin("Diagnose-Export", "Support-Paket wird erstellt …"):
            self.app.worker.run(work, done, failed)

    def _update_log(self) -> Path | None:
        try:
            from updater.store import default_dir

            path = default_dir() / "update-start.log"
        except Exception:  # noqa: BLE001
            return None
        return path if path.is_file() else None

    # Protokolle und Aufräumen ------------------------------------------------------------------------------------
    @Slot()
    def openLogs(self) -> None:  # noqa: N802
        """Datenordner öffnen (Protokolle: pdf-tool.log, fehler.log, stapel.log, pdf-repair.log)."""
        self.app.open_file(self.root, AREA)

    def cleanup_quietly(self) -> None:
        root, folder = self.root, self.backup.folder()

        def done(removed: list[str]) -> None:
            self.cleaned = removed
            if removed:
                applog.get("diagnose").info("Temporäre Dateien früherer Sitzungen entfernt: %d", len(removed))

        self.app.worker.run(lambda: cleanup.cleanup_temp(root, folder), done, lambda _exc, _text: None)

    @Slot()
    def cleanupNow(self) -> None:  # noqa: N802
        root, folder = self.root, self.backup.folder()

        def done(removed: list[str]) -> None:
            self.cleaned = removed
            text = "Keine alten temporären Dateien gefunden." if not removed else f"{len(removed)} {'temporäre Datei' if len(removed) == 1 else 'temporäre Dateien'} früherer Sitzungen entfernt."
            self.app.notify(AREA, "success", text, auto_hide=6000)

        self.app.worker.run(lambda: cleanup.cleanup_temp(root, folder), done, lambda _exc, text: self.app.write_error_log(text))

    def config(self) -> dict:
        return {}

    _constant = Signal()

    def _qml_count(self) -> int:
        from . import application

        return len(application.MESSAGES)

    qmlMessages = Property(int, _qml_count, notify=_constant)

    def _facts_model(self) -> QObject:
        return self.fact_model

    factModel = Property(QObject, _facts_model, notify=_constant)
