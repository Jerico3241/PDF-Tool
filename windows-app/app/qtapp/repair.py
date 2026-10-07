"""Werkzeug »PDF reparieren« (in QML: ``Repair``) – für eine oder mehrere PDFs.

Ablauf: PDFs wählen (Dialog mit Mehrfachauswahl) oder hineinziehen → jede Datei wird für sich
analysiert → Liste mit Zustand, Diagnose und geplantem Ausgabenamen → »PDF reparieren« (eine
Datei) bzw. »Alle reparieren« → Fortschritt je Datei und gesamt, »Abbrechen« → Ergebnis je Datei
und Zusammenfassung. Mit nur einer Datei bleibt es so einfach wie bis 2.7.0.

Analyse und Reparatur sind unverändert die Engine aus 2.7.0: je Datei ein Arbeitsprozess
(``process.Job`` → ``engine.analyze`` / ``engine.repair``), die geprüfte Ausgabe übernimmt
``process.deliver``. ``tools.pdf_repair.batch`` bestimmt nur Reihenfolge, Zustände und Namen.
Höchstens zwei Arbeitsprozesse laufen gleichzeitig (Analysen), repariert wird nacheinander.

Die Originaldateien werden nur gelesen – nie verändert, umbenannt oder überschrieben.
Passwörter gelten nur für ihre Datei und bleiben im Arbeitsspeicher: keine Property, nicht im
Protokoll, nicht in den Einstellungen; das Eingabefeld wird nach jedem Versuch geleert.
"""

from __future__ import annotations

import errno
import traceback
from pathlib import Path

from PySide6.QtCore import Property, QObject, QTimer, Signal, Slot

from appstate import DATA_DIR, desktop_dir
from tools.pdf_repair import presentation
from tools.pdf_repair import process
from tools.pdf_repair.batch import (
    DEFAULT_SUFFIX,
    BatchItem,
    ItemState,
    NameMode,
    Phase,
    RepairBatch,
    analysis_state,
    auto_base,
    name_error,
    phase_of,
    result_state,
    strip_pdf,
    suffix_error,
)
from tools.pdf_repair.models import STAGES, Condition, PdfAnalysis, PdfRepairResult, RepairMode, RepairStatus
from tools.pdf_repair.presentation import OUT_FOLDER, OUT_ORIGINAL, RepairLog, is_pdf, size_text
from tools.registry import REPAIR

from . import files
from .base import Observable, Var, prop
from .models import KeyedListModel

POLL_MS = 30  # Arbeitsprozesse abfragen: kurze Aufträge (kleine PDFs) dauern oft nur wenige Millisekunden
CLEANUP_DELAY_MS = 3000  # alte Arbeitsordner erst nach dem Start im Hintergrund entfernen
MAX_WORKERS = 2  # Arbeitsprozesse gleichzeitig (eine Reparatur und eine Analyse oder zwei Analysen)
ANALYSIS_WORKERS = 2
RESULT_AREA = "repair_result"
# Speichern unmöglich – der ganze Durchlauf hält an (kein Schreibzugriff, Datenträger voll …)
GLOBAL_ERRORS = {errno.EACCES, errno.EPERM, errno.EROFS, errno.ENOSPC, getattr(errno, "EDQUOT", errno.ENOSPC)}
ROLES = (
    "key", "name", "path", "sizeText", "state", "stateText", "tone", "message", "busy", "phaseText", "progress",
    "outputBase", "outputName", "outputFolder", "numbered", "nameManual", "nameError", "needsPassword", "canRepair",
    "repairText", "signatures", "rescue", "hasOutput", "facts", "details", "resultFacts", "warnings", "inRun", "canAnalyze",
    "diagSeverity", "diagTitle", "diagText", "resultSeverity", "resultTitle", "resultText", "resultActions",
)


class RepairController(Observable):
    """Zustand und Ablauf des Werkzeugs – QML zeigt nur an und ruft die Slots auf."""

    # Liste
    countChanged, count = prop(int, "count", 0)
    hasFileChanged, hasFile = prop(bool, "hasFile", False)  # mindestens eine Datei
    singleChanged, single = prop(bool, "single", False)  # genau eine Datei: Einzelmodus
    overviewChanged, overview = prop(str, "overview", "")
    overviewKindChanged, overviewKind = prop(str, "overviewKind", "neutral")
    # Laufende Vorgänge
    busyChanged, busy = prop(bool, "busy", False)  # irgendein Arbeitsprozess läuft
    runningChanged, running = prop(bool, "running", False)  # ein Reparaturdurchlauf läuft
    progressTextChanged, progressText = prop(str, "progressText", "")  # »3 / 8 Dateien«
    progressValueChanged, progressValue = prop(float, "progressValue", -1.0)  # −1: unbestimmt
    currentTextChanged, currentText = prop(str, "currentText", "")
    # Start
    primaryTextChanged, primaryText = prop(str, "primaryText", "PDF reparieren")
    canStartChanged, canStart = prop(bool, "canStart", False)
    canRetryChanged, canRetry = prop(bool, "canRetry", False)
    # Ausgabe
    outModeChanged, outMode = prop(str, "outMode", OUT_ORIGINAL)
    outLabelChanged, outLabel = prop(str, "outLabel", "Neben der Original-PDF")
    outPathChanged, outPath = prop(str, "outPath", "")
    outMissingChanged, outMissing = prop(bool, "outMissing", False)
    appendSuffixChanged, appendSuffix = prop(bool, "appendSuffix", True)
    suffixChanged, suffix = prop(str, "suffix", DEFAULT_SUFFIX)
    suffixErrorChanged, suffixError = prop(str, "suffixError", "")
    outNameChanged, outName = prop(str, "outName", presentation.OUT_NAME_EMPTY)  # Beispiel/Einzeldatei
    namingExampleChanged, namingExample = prop(str, "namingExample", "")  # »Rechnung.pdf → Rechnung_repariert.pdf«
    # Ergebnis des letzten Durchlaufs
    hasResultChanged, hasResult = prop(bool, "hasResult", False)
    summaryChanged, summary = prop(dict, "summary", {})
    # Ziehen und Ablegen
    dropHighlightChanged, dropHighlight = prop(bool, "dropHighlight", False)

    focusRequested = Signal(str)  # »pick«
    revealRequested = Signal(str)  # »list« oder »result«
    passwordCleared = Signal(str)  # Passwortfeld der Datei leeren (Schlüssel)
    passwordRequested = Signal(str)  # Passwortfeld der Datei in den Fokus (Schlüssel)

    def __init__(self, app, cfg: dict, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.app = app
        self.batch = RepairBatch()
        self.model = KeyedListModel(ROLES, key="key", parent=self)
        mode = cfg.get("reparatur_ausgabe")
        self.set_quietly("outMode", mode if mode in (OUT_ORIGINAL, OUT_FOLDER) else OUT_ORIGINAL)
        # Fehlt die Einstellung (Update von 2.7.0 oder älter), gilt das bisherige Verhalten: »_repariert«
        self.set_quietly("appendSuffix", cfg.get("reparatur_anhaengen", True) is not False)
        saved_suffix = str(cfg.get("reparatur_zusatz") or DEFAULT_SUFFIX)
        self.set_quietly("suffix", saved_suffix if not suffix_error(saved_suffix) else DEFAULT_SUFFIX)
        self.out_dir = str(cfg.get("reparatur_ordner") or "")
        self.source_dir = str(cfg.get("ordner_reparatur") or "")
        self.var_out_mode = Var(self, "outMode")
        self.jobs: dict[str, process.Job] = {}  # Schlüssel der Datei → laufender Arbeitsprozess
        self.kinds: dict[str, str] = {}  # … → »analyze« oder »repair«
        self.queue: list[str] = []  # noch zu reparieren (Reihenfolge des Durchlaufs)
        self.modes: dict[str, RepairMode] = {}
        self.run_keys: list[str] = []  # Dateien des laufenden bzw. letzten Durchlaufs
        self.run_skipped: list[str] = []  # … beim Start übersprungen (signiert, nicht gewünscht)
        self.run_not_started: list[str] = []  # … wegen »Abbrechen« nicht mehr begonnen
        self.log = RepairLog(DATA_DIR)
        self._poll = QTimer(self)
        self._poll.setInterval(POLL_MS)
        self._poll.timeout.connect(self._poll_jobs)
        self.observe("outMode", lambda _value: self._output_changed())
        self._refresh()

    def start(self) -> None:
        """Nach dem Start: Arbeitsordner früherer, abgebrochener Sitzungen im Hintergrund entfernen."""
        self.app.timers.later("repair:cleanup", CLEANUP_DELAY_MS, lambda: self.app.worker.run(process.cleanup_stale))

    # Einstellungen ---------------------------------------------------------------------------------
    def config(self) -> dict:
        return {
            "reparatur_ausgabe": self.outMode,
            "reparatur_ordner": self.out_dir,
            "ordner_reparatur": self.source_dir,
            "reparatur_anhaengen": self.appendSuffix,
            "reparatur_zusatz": self.suffix,
        }

    # Einzeldatei (wie bis 2.7.0; Tests, Tastenkürzel) ---------------------------------------------------
    @property
    def current(self) -> BatchItem | None:
        """Die Datei im Einzelmodus (genau eine in der Liste)."""
        return self.batch.items[0] if len(self.batch) == 1 else None

    @property
    def path(self) -> Path | None:
        return self.current.path if self.current else None

    @property
    def analysis(self) -> PdfAnalysis | None:
        return self.current.analysis if self.current else None

    @property
    def result(self) -> PdfRepairResult | None:
        return self.current.result if self.current else None

    @property
    def output(self) -> Path | None:
        return self.current.output if self.current else None

    # Dateien hinzufügen ------------------------------------------------------------------------------
    @Slot()
    def pick(self) -> None:
        start = self.source_dir if self.source_dir and Path(self.source_dir).is_dir() else str(desktop_dir())
        paths = files.open_files("PDFs zum Reparieren wählen", start, files.PDF_FILTER)
        if paths:
            self.add(paths)

    @Slot(str)
    def use(self, path: str) -> None:
        """Eine PDF hinzufügen (z. B. aus »Öffnen mit«)."""
        self.add([path])

    def add(self, paths: list[str]) -> list[BatchItem]:
        result = self.batch.add(paths)
        notes = []
        if result.rejected:
            notes.append(f"Keine PDF: {', '.join(result.rejected[:3])}" + (" …" if len(result.rejected) > 3 else "") + ".")
        if result.duplicates:
            notes.append(f"Bereits in der Liste: {', '.join(result.duplicates[:3])}" + (" …" if len(result.duplicates) > 3 else "") + ".")
        if result.missing:
            notes.append(f"Nicht vorhanden: {', '.join(result.missing[:3])}" + (" …" if len(result.missing) > 3 else "") + ".")
        if notes:
            severity = "warning" if result.added else ("info" if result.duplicates and not result.rejected and not result.missing else "warning")
            self.app.notify("repair_drop_info", severity, " ".join(notes), title="Nicht alle Dateien übernommen" if result.added else "Keine neue PDF")
        else:
            self.app.hide_notice("repair_drop_info")
        if result.added:
            self.source_dir = str(result.added[-1].path.parent)
            self.app.schedule_save()
            self._plan()
            self._refresh()
            self._schedule()
            self.revealRequested.emit("list")
        return result.added

    def accepts(self, dropped: list[str]) -> bool:
        return any(is_pdf(f) for f in dropped)

    def drag_enter(self, accepted: bool) -> None:
        if accepted:
            self.dropHighlight = True

    def drag_leave(self) -> None:
        self.dropHighlight = False

    def drop(self, dropped: list[str]) -> None:
        self.drag_leave()
        if not any(is_pdf(f) for f in dropped):
            self.app.notify("repair_drop_info", "warning", "Bitte PDF-Dateien in das Fenster ziehen (Dateiendung .pdf).", title="Keine PDF")
            return
        self.add(dropped)

    # Entfernen --------------------------------------------------------------------------------------
    @Slot(str)
    def remove(self, key: str) -> None:
        item = self.batch.get(key)
        if item is None:
            return
        if item.state is ItemState.REPAIRING:
            self.app.notify("repair_info", "warning", "Diese PDF wird gerade repariert. Bitte abbrechen oder warten.")
            return
        self._stop_job(key)
        if key in self.queue:
            self.queue.remove(key)
        self.batch.remove(key)
        self.passwordCleared.emit(key)
        self._plan()
        self._refresh()
        self._schedule()

    @Slot()
    def removeAll(self) -> None:  # noqa: N802
        if self.running:
            self.app.notify("repair_info", "warning", "Bitte warten, bis die Reparatur beendet ist, oder sie abbrechen.")
            return
        for key in list(self.jobs):
            self._stop_job(key)
        self.batch.clear()
        self.queue.clear()
        self.run_keys, self.run_skipped = [], []
        self._show_result(None)
        self.app.hide_notice("repair_info")
        self.app.hide_notice("repair_drop_info")
        self._refresh()

    @Slot()
    def reset(self) -> None:
        """»Weitere PDFs reparieren«: Liste leeren, Ausgabeort und Einstellungen bleiben."""
        if self.busy:
            return
        self.removeAll()
        self.app.set_status("Bereit für die nächsten PDFs.", "neutral")
        self.focusRequested.emit("pick")

    # Passwort ---------------------------------------------------------------------------------------
    @Slot(str, str)
    def unlock(self, key: str, password: str) -> None:
        """Verschlüsselte PDF mit ihrem Passwort erneut analysieren (gilt nur für diese Datei)."""
        self.passwordCleared.emit(key)
        item = self.batch.get(key)
        if item is None or item.busy:
            return
        if not password:
            item.message = "Bitte das Passwort dieser PDF eingeben."
            self._refresh_item(item)
            return
        item.password = password
        item.state = ItemState.PENDING
        item.analysis = None
        item.message = ""
        self._refresh()
        self._schedule()

    @Slot(str)
    def analyzeAgain(self, key: str) -> None:  # noqa: N802
        item = self.batch.get(key)
        if item is None or item.busy:
            return
        item.state = ItemState.PENDING
        item.analysis = None
        item.message = ""
        self._refresh()
        self._schedule()

    # Ausgabenamen ----------------------------------------------------------------------------------
    @Slot(bool)
    def setAppendSuffix(self, on: bool) -> None:  # noqa: N802
        self.appendSuffix = bool(on)
        self._output_changed()

    @Slot(str)
    def setSuffix(self, text: str) -> None:  # noqa: N802
        value = str(text or "").strip()
        error = suffix_error(value)
        self.suffixError = error
        if error:
            return  # die Regel behält den letzten gültigen Zusatz
        self.suffix = value
        self._output_changed()

    @Slot(str, str)
    def setOutputName(self, key: str, text: str) -> None:  # noqa: N802
        """Eigener Ausgabename (ohne ».pdf«; die Endung wird ergänzt)."""
        item = self.batch.get(key)
        if item is None or item.output is not None or item.reserved:
            return
        base = strip_pdf(text)
        if name_error(base):
            item.name_input = text  # angezeigt, aber nicht verwendet
        else:
            item.name_input = None
            if base == auto_base(item.path, self.appendSuffix, self.suffix):
                item.name_mode, item.manual_base = NameMode.AUTO, ""
            else:
                item.name_mode, item.manual_base = NameMode.MANUAL, base
        self._plan()
        self._refresh()

    @Slot(str)
    def resetOutputName(self, key: str) -> None:  # noqa: N802
        """»Automatischen Namen wiederherstellen«: wieder die Namensregel."""
        item = self.batch.get(key)
        if item is None or item.output is not None or item.reserved:
            return
        item.name_mode, item.manual_base, item.name_input = NameMode.AUTO, "", None
        self._plan()
        self._refresh()

    # Reparatur ----------------------------------------------------------------------------------------
    @Slot()
    def startRepair(self) -> None:  # noqa: N802 - QML-Schreibweise
        self.start_repair()

    def start_repair(self, mode: RepairMode | None = None) -> None:
        """Einzelmodus: die eine PDF; sonst »Alle reparieren« (beschädigte, noch nicht reparierte)."""
        if self.single:
            item = self.batch.items[0]
            if mode is RepairMode.RASTER:
                self.rescueItem(item.key)
            else:
                self._repair([item], mode)
            return
        self._repair(self.batch.to_repair(), mode)

    @Slot(str)
    def repairItem(self, key: str) -> None:  # noqa: N802
        """»Nur diese Datei reparieren« (auch eine gesunde: »Trotzdem neu aufbauen«)."""
        item = self.batch.get(key)
        if item is not None:
            self._repair([item], None)

    @Slot(str)
    def rescueItem(self, key: str) -> None:  # noqa: N802
        """Rettungsmodus für genau diese Datei: lesbare Seiten als Bilder (nur nach Bestätigung)."""
        item = self.batch.get(key)
        if item is None or item.analysis is None or item.busy or self.running:
            return
        if not self._confirm(presentation.RASTER_TITLE, presentation.RASTER_TEXT, presentation.RASTER_CONFIRM, danger=False):
            return
        self._repair([item], RepairMode.RASTER)  # signiert: fragt zusätzlich wie bis 2.7.0

    @Slot()
    def retryFailed(self) -> None:  # noqa: N802
        self._repair(self.batch.failed(), None)

    @Slot()
    def rescue(self) -> None:
        """Einzelmodus (wie bis 2.7.0): Rettungsmodus für die eine Datei."""
        if self.single:
            self.rescueItem(self.batch.items[0].key)

    def _repair(self, items: list[BatchItem], mode: RepairMode | None) -> None:
        if self.running:
            self.app.notify("repair_info", "warning", "Es läuft bereits eine Reparatur. Bitte warten oder abbrechen.")
            return
        if not items:
            self.app.notify("repair_info", "info", "Keine PDF zu reparieren: Alle Dateien sind repariert, ohne Fehler, verschlüsselt oder nicht wiederherstellbar.")
            return
        for item in items:
            if item.state is ItemState.ENCRYPTED:
                self.app.notify("repair_info", "warning", "Bitte zuerst das Passwort eingeben." if len(items) == 1 else f"»{item.name}«: bitte zuerst das Passwort eingeben.")
                return
            if mode is not RepairMode.RASTER and item.condition is Condition.UNREADABLE:
                self.app.notify("repair_info", "error", "Diese Datei lässt sich nicht reparieren.")
                return
            if item.analysis is None or item.busy:
                self.app.notify("repair_info", "warning", "Bitte warten, bis die Analyse beendet ist.")
                return
        if self.outMode == OUT_FOLDER and not self.out_dir:
            self.app.notify("repair_info", "warning", "Bitte zuerst einen Ausgabeordner wählen.", title="Kein Ausgabeordner")
            return
        invalid = [item for item in items if item.name_error]
        if invalid:
            self.app.notify("repair_info", "warning", f"Bitte den Ausgabenamen von »{invalid[0].name}« korrigieren: {invalid[0].name_error}")
            return
        chosen = list(items)
        skipped: list[BatchItem] = []
        signed = [item for item in chosen if item.signatures]
        if signed:
            if len(chosen) == 1:
                if not self._confirm(presentation.SIGNATURE_TITLE, presentation.SIGNATURE_TEXT, presentation.SIGNATURE_CONFIRM, danger=True):
                    return
            else:
                names = ", ".join(f"»{item.name}«" for item in signed[:5]) + (" …" if len(signed) > 5 else "")
                answer, _data = self.app.dialogs.ask(
                    "confirm",
                    presentation.SIGNATURE_TITLE,
                    f"{len(signed)} der PDFs enthalten digitale Signaturen ({names}). Eine Reparatur kann deren Gültigkeit aufheben.\n\n"
                    "Die Originaldateien bleiben unverändert; die Signaturen der reparierten Kopien sind danach möglicherweise ungültig.",
                    primary="Alle reparieren",
                    secondary="Signierte überspringen",
                    danger=True,
                )
                if answer == "secondary":
                    for item in signed:
                        item.state, item.message = ItemState.SKIPPED, "Digital signiert – übersprungen."
                    skipped = signed
                    chosen = [item for item in chosen if not item.signatures]
                elif answer != "primary":
                    return
        # Während einer Rückfrage kann sich die Liste geändert haben
        chosen = [item for item in chosen if self.batch.get(item.key) is item and not item.busy]
        if not chosen:
            if skipped:  # alle gewählten waren signiert und wurden übersprungen
                self.run_keys, self.run_skipped, self.run_not_started = [], [item.key for item in skipped], []
                self._show_result([item.state for item in skipped])
            self._refresh()
            return
        self.batch.reserve(chosen, self._folder_for, self.appendSuffix, self.suffix)
        self.queue = [item.key for item in chosen]
        self.modes = {item.key: (mode or item.repair_mode()) for item in chosen}
        self.run_keys = [item.key for item in chosen]
        self.run_skipped = [item.key for item in skipped]
        self.run_not_started = []
        for item in chosen:
            item.message = ""
            item.result = None
            item.rescue = False
        self._show_result(None)
        self.app.hide_notice("repair_info")
        self.running = True
        self._refresh()
        self._schedule()

    def _confirm(self, title: str, message: str, confirm: str, danger: bool) -> bool:
        return self.app.dialogs.confirm(title, message, confirm, danger=danger)

    @Slot()
    def cancel(self) -> None:
        """Alles anhalten: laufende Arbeitsprozesse beenden (ihr Arbeitsordner wird gelöscht), noch nicht
        gestartete Dateien nicht mehr bearbeiten. Bereits gespeicherte Dateien bleiben erhalten."""
        if not self.jobs and not self.queue:
            return
        stopped = []
        for key in list(self.jobs):
            item = self.batch.get(key)
            kind = self.kinds.get(key)
            self._stop_job(key)
            if item is not None:
                item.state = ItemState.CANCELLED
                item.message = "Reparatur abgebrochen – es wurde keine Datei gespeichert." if kind == "repair" else "Analyse abgebrochen."
                item.fraction, item.phase = None, None
                stopped.append(item.name)
        for key in self.queue:
            item = self.batch.get(key)
            if item is not None:
                item.state, item.message = ItemState.CANCELLED, "Nicht gestartet (abgebrochen)."
                self.run_not_started.append(key)
        self.queue.clear()
        for item in self.batch.items:
            if item.state is ItemState.PENDING:
                item.state, item.message = ItemState.CANCELLED, "Analyse abgebrochen."
        self.log.write([f"Abgebrochen: {', '.join(stopped) or 'Warteschlange'}"])
        if self.running:
            self._finish_run(cancelled=True)
        else:
            self.app.notify("repair_info", "info", "Der Vorgang wurde abgebrochen.")
            self._refresh()

    def close(self) -> None:
        """Beim Beenden: laufende Arbeitsprozesse beenden (ihre Arbeitsordner werden gelöscht)."""
        self._poll.stop()
        for key in list(self.jobs):
            self._stop_job(key)
        process.stop_workers()  # wartende Arbeitsprozesse
        for item in self.batch.items:
            item.password = None

    # Arbeitsprozesse ------------------------------------------------------------------------------------
    def _schedule(self) -> None:
        """Nächste Arbeit starten: eine Reparatur zur Zeit, daneben Analysen bis zur Höchstzahl."""
        while self.queue and not any(kind == "repair" for kind in self.kinds.values()):
            key = self.queue.pop(0)
            item = self.batch.get(key)
            if item is None:
                continue
            if not item.can_repair() and self.modes.get(key) is not RepairMode.RASTER:
                item.state, item.message = ItemState.SKIPPED, "Nicht reparierbar – übersprungen."
                continue
            request = {"path": str(item.path), "password": item.password, "mode": self.modes.get(key, item.repair_mode()).value, "sha256": item.analysis.sha256 if item.analysis else None}
            if not self._start_job(item, "repair", request):
                continue
            item.state = ItemState.REPAIRING
            break
        while len(self.jobs) < MAX_WORKERS and sum(1 for kind in self.kinds.values() if kind == "analyze") < ANALYSIS_WORKERS:
            item = self.batch.next_to_analyze()
            if item is None:
                break
            item.state = ItemState.ANALYZING
            if not self._start_job(item, "analyze", {"path": str(item.path), "password": item.password}):
                continue
        if self.running and not self.queue and not any(kind == "repair" for kind in self.kinds.values()):
            self._finish_run()
            return
        self._refresh()
        if self.jobs and not self._poll.isActive():
            self._poll.start()

    def _start_job(self, item: BatchItem, kind: str, request: dict) -> bool:
        item.phase, item.stage, item.fraction = Phase.ANALYSIS, "hash", None
        try:
            job = process.Job(kind, request)
        except Exception as exc:  # noqa: BLE001 - z. B. Prozess lässt sich nicht starten
            item.state = ItemState.FAILED
            item.message = f"Der Vorgang konnte nicht gestartet werden ({exc})."
            item.phase = None
            return False
        self.jobs[item.key] = job
        self.kinds[item.key] = kind
        return True

    def _stop_job(self, key: str) -> None:
        job = self.jobs.pop(key, None)
        self.kinds.pop(key, None)
        if job is not None:
            job.cancel()

    def _poll_jobs(self) -> None:
        if not self.jobs:
            self._poll.stop()
            return
        changed = False
        for key, job in list(self.jobs.items()):
            item = self.batch.get(key)
            kind = self.kinds.get(key, "")
            try:
                for event in job.events():
                    if item is None:
                        continue
                    if event[0] == "progress":
                        item.stage, item.phase = event[1], phase_of(kind, event[1])
                        fraction = event[2]
                        item.fraction = float(fraction) if fraction is not None and 0 < fraction < 1 else None
                        self._refresh_item(item, progress=True)
                    elif event[0] == "result":
                        self._finished(key, job, kind, event[1])
                        changed = True
                    elif event[0] in ("error", "crash"):
                        message = event[1] if event[0] == "error" else presentation.crash_text(event[1])
                        self._failed(key, job, kind, message)
                        changed = True
            except Exception:  # noqa: BLE001 - Fehler melden, die Oberfläche bleibt bedienbar
                self.app.report_exception(traceback.format_exc())
                self._failed(key, job, kind, "Interner Fehler bei der Verarbeitung.")
                changed = True
            if job.done and key in self.jobs and self.jobs[key] is job:
                self.jobs.pop(key, None)
                self.kinds.pop(key, None)
                job.cleanup()
                changed = True
        if changed:
            self._schedule()
        if not self.jobs:
            self._poll.stop()
            self._update_busy()

    def _finished(self, key: str, job: process.Job, kind: str, payload) -> None:
        self.jobs.pop(key, None)
        self.kinds.pop(key, None)
        item = self.batch.get(key)
        if item is None:
            job.cleanup()
            return
        item.fraction, item.stage = None, ""
        if isinstance(payload, PdfAnalysis):
            job.cleanup()
            self._analysis_done(item, payload)
        elif isinstance(payload, PdfRepairResult):
            self._repair_done(item, payload, job)
        else:
            job.cleanup()

    def _failed(self, key: str, job: process.Job, kind: str, message: str) -> None:
        self.jobs.pop(key, None)
        self.kinds.pop(key, None)
        job.cleanup()
        item = self.batch.get(key)
        if item is None:
            return
        item.state, item.message, item.phase, item.fraction = ItemState.FAILED, message, None, None
        item.reserved = False
        self.log.write([f"Fehler ({kind}) {item.name}: {message}"])

    def _analysis_done(self, item: BatchItem, analysis: PdfAnalysis) -> None:
        item.analysis = analysis
        item.state = analysis_state(analysis)
        item.phase = None
        item.message = ""  # Diagnose und Erklärung entstehen aus der Analyse (_row)
        item.rescue = analysis.condition is Condition.UNREADABLE and analysis.rasterizable_pages > 0
        self.log.write(presentation.analysis_log(analysis))
        if item.state is ItemState.ENCRYPTED and self.single:
            # Eine PDF: gleich ins Passwortfeld (mit mehreren nicht – der Fokus bliebe sonst nicht, wo der Benutzer arbeitet)
            self.passwordRequested.emit(item.key)
        if self.single:
            severity, title, _message = presentation.condition_text(analysis)
            self.app.set_status(f"{title}: {item.name}", presentation.SEVERITY_STATUS.get(severity, "info"))

    def _repair_done(self, item: BatchItem, result: PdfRepairResult, job: process.Job) -> None:
        item.result = result
        lines = presentation.result_log(result)
        delivered = False
        stop_run = ""
        try:
            if result.usable:
                target = item.planned or process.next_output(item.path, self._folder_for(item))
                try:
                    item.output = process.deliver(
                        Path(result.output_path),
                        item.path,
                        target.parent,
                        base=item.planned_base or None,
                        start=item.planned_number,
                        avoid=self.batch.reserved_names(target.parent, except_item=item),
                    )
                    delivered = True
                    lines.append(f"  Gespeichert als {item.output.name}")
                except OSError as exc:
                    result.status = RepairStatus.FAILED
                    result.error = f"Die reparierte Datei konnte nicht gespeichert werden ({exc.strerror or exc})."
                    lines.append(f"  Speichern fehlgeschlagen: {exc}")
                    if exc.errno in GLOBAL_ERRORS or isinstance(exc, PermissionError):
                        stop_run = result.error
        finally:
            job.cleanup()
        item.reserved = False
        item.state = result_state(result, delivered)
        item.phase = Phase.DONE if delivered else None
        item.message = ""  # Ergebnis und Erklärung entstehen aus dem Ergebnis (_row)
        item.rescue = presentation.rescue_possible(result, item.analysis)
        self.log.write(lines)
        if stop_run and self.queue:
            # Kein Schreibzugriff, Datenträger voll …: die übrigen Dateien nicht mehr anfangen
            for key in self.queue:
                other = self.batch.get(key)
                if other is not None:
                    other.state, other.message, other.reserved = ItemState.SKIPPED, "Nicht gestartet – der Ausgabeordner ist nicht beschreibbar.", False
            self.queue.clear()
            self.app.notify("repair_info", "error", stop_run, title="Reparatur angehalten")

    def _finish_run(self, cancelled: bool = False) -> None:
        """Durchlauf beendet (oder abgebrochen): Zusammenfassung, Reservierungen aufheben."""
        self.running = False
        self.batch.release()
        if cancelled and len(self.run_keys) == 1 and not self.run_skipped:
            # Eine Datei abgebrochen – wie bis 2.7.0: Hinweis statt Ergebnis
            self._show_result(None)
            self.app.notify("repair_info", "info", "Die Reparatur wurde abgebrochen. Es wurde keine Datei gespeichert.")
            self.app.set_status("Reparatur abgebrochen.", "neutral")
        else:
            states = [item.state for key in self.run_keys + self.run_skipped if key not in self.run_not_started and (item := self.batch.get(key)) is not None]
            self._show_result(states, not_started=len(self.run_not_started))
        self._plan()
        self._refresh()
        if self.jobs and not self._poll.isActive():
            self._poll.start()

    def _show_result(self, states: list[ItemState] | None, not_started: int = 0) -> None:
        if not states and not not_started:
            self.hasResult = False
            self.summary = {}
            self.app.hide_notice(RESULT_AREA, animate=False)
            self.app.hide_notice("repair_result_info", animate=False)
            return
        outputs = [item.output for key in self.run_keys if (item := self.batch.get(key)) is not None and item.output is not None]
        folders = {str(path.parent) for path in outputs}
        alone = self.batch.get(self.run_keys[0]) if len(self.run_keys) == 1 and not self.run_skipped else None
        if alone is not None and alone.result is not None:
            # Eine Datei: Ergebnis dieser Datei (wie bis 2.7.0: »PDF wurde repariert.« …)
            severity, title, message = presentation.result_summary(alone.result, alone.analysis, alone.output)
            lines = [message]
        else:
            severity, title, lines = presentation.run_summary(states, not_started)
            message = " · ".join(lines)
        self.summary = {
            "shown": True,
            "severity": severity,
            "title": title,
            "lines": lines,
            "message": message,
            "hasOutput": bool(outputs),
            "folder": next(iter(folders)) if len(folders) == 1 else (str(outputs[0].parent) if outputs else ""),
            "single": alone is not None,
            "key": alone.key if alone is not None else "",
        }
        self.app.notices.notify(RESULT_AREA, severity, message, title, animate=False)
        self.app.hide_notice("repair_result_info", animate=False)
        self.hasResult = True
        if alone is not None and alone.output is not None:
            self.app.set_status(f"Gespeichert: {alone.output.name}", "success" if alone.state is ItemState.REPAIRED else "warning")
        elif alone is not None and alone.state is ItemState.ENCRYPTED:
            self.app.set_status("Passwort fehlt oder ist falsch.", "error")
        elif alone is not None:
            self.app.set_status("PDF konnte nicht repariert werden.", "error")
        else:
            self.app.set_status(f"{title}: {message}", presentation.SEVERITY_STATUS.get(severity, "info"))
        self.revealRequested.emit("result")

    # Aktionen je Datei und im Ergebnis ------------------------------------------------------------------------
    @Slot(str)
    def openItemOutput(self, key: str) -> None:  # noqa: N802
        item = self.batch.get(key)
        if item is not None and item.output is not None:
            self.app.open_file(item.output, "repair_result_info")

    @Slot(str)
    def openItemFolder(self, key: str) -> None:  # noqa: N802
        item = self.batch.get(key)
        if item is not None and item.output is not None:
            self.app.open_folder_of(item.output, "repair_result_info")

    @Slot(str)
    def copyItemOutput(self, key: str) -> None:  # noqa: N802
        item = self.batch.get(key)
        if item is not None and item.output is not None:
            self.app.copy_path(item.output)

    @Slot(str)
    def copyItemPath(self, key: str) -> None:  # noqa: N802
        item = self.batch.get(key)
        if item is not None:
            self.app.copy_path(item.path)

    @Slot()
    def openResultFolder(self) -> None:  # noqa: N802
        """»Ausgabeordner öffnen« nach einem Durchlauf (mehrere Ordner: der der ersten Ausgabe)."""
        outputs = [item.output for key in self.run_keys if (item := self.batch.get(key)) is not None and item.output is not None]
        if outputs:
            self.app.open_folder_of(outputs[0], "repair_result_info")

    @Slot()
    def openResultFile(self) -> None:  # noqa: N802
        """Ergebnis einer einzelnen Datei öffnen (Karte »Ergebnis«)."""
        key = self.summary.get("key") if self.summary else ""
        if key:
            self.openItemOutput(key)

    @Slot()
    def copyResultPath(self) -> None:  # noqa: N802
        key = self.summary.get("key") if self.summary else ""
        if key:
            self.copyItemOutput(key)

    # Einzelmodus (wie bis 2.7.0)
    @Slot()
    def openOutput(self) -> None:  # noqa: N802
        if self.current is not None:
            self.openItemOutput(self.current.key)

    @Slot()
    def openOutputFolder(self) -> None:  # noqa: N802
        if self.current is not None:
            self.openItemFolder(self.current.key)

    @Slot()
    def copyOutputPath(self) -> None:  # noqa: N802
        if self.current is not None:
            self.copyItemOutput(self.current.key)

    @Slot()
    def copyInputPath(self) -> None:  # noqa: N802
        if self.current is not None:
            self.copyItemPath(self.current.key)

    # Ausgabeort ------------------------------------------------------------------------------------------------
    @Slot()
    def pickOutDir(self) -> None:  # noqa: N802
        start = self.out_dir if self.out_dir and Path(self.out_dir).is_dir() else (self.source_dir or str(desktop_dir()))
        path = files.pick_folder("Ordner für reparierte PDFs", start)
        if path:
            self.out_dir = path
            if self.outMode != OUT_FOLDER:
                self.outMode = OUT_FOLDER  # löst _output_changed aus
            else:
                self._output_changed()

    @Slot(str)
    def setOutMode(self, mode: str) -> None:  # noqa: N802
        if mode in (OUT_ORIGINAL, OUT_FOLDER):
            self.outMode = mode

    def _folder_for(self, item: BatchItem) -> Path:
        if self.outMode == OUT_FOLDER and self.out_dir:
            return Path(self.out_dir)
        return item.path.parent  # neben der Original-PDF

    def _output_changed(self) -> None:
        self._plan()
        self._refresh()
        self.app.schedule_save()

    def _plan(self) -> None:
        self.batch.plan(self._folder_for, self.appendSuffix, self.suffix)

    # Darstellung -----------------------------------------------------------------------------------------------
    def _update_busy(self) -> None:
        self.busy = bool(self.jobs) or bool(self.queue)

    def _refresh(self) -> None:
        """Liste und Gesamtstand neu darstellen (nur geänderte Zeilen und Rollen werden gemeldet)."""
        self.model.set_items([self._row(item) for item in self.batch.items])
        self._refresh_state()

    def _refresh_state(self) -> None:
        """Gesamtstand: Zählung, Ausgabe, Start, Fortschritt."""
        count = len(self.batch)
        self.count = count
        self.hasFile = count > 0
        self.single = count == 1
        self._update_busy()
        self.overview, self.overviewKind = presentation.batch_overview(self.batch)
        folder_mode = self.outMode == OUT_FOLDER
        self.outMissing = folder_mode and not self.out_dir
        if self.outMissing:
            self.outLabel, self.outPath = "Bitte einen Ordner wählen", ""
        elif folder_mode:
            self.outLabel, self.outPath = Path(self.out_dir).name or self.out_dir, self.out_dir
        else:
            self.outLabel, self.outPath = "Neben der Original-PDF", ""
        stem = self.batch.items[0].path.stem if self.batch.items else "Rechnung"
        self.namingExample = f"{stem}.pdf → {stem}{self.suffix}.pdf" if self.appendSuffix else f"{stem}.pdf → {stem}.pdf"
        current = self.current
        if current is not None and current.planned is not None:
            self.outName = f"Ausgabe: {(current.output or current.planned).name}"
        else:
            example = f"<Name>{self.suffix}.pdf" if self.appendSuffix else "<Name>.pdf"
            self.outName = f"Ausgabe: {example} – die Originaldatei wird nie überschrieben."
        # Start
        if self.single:
            self.primaryText = presentation.repair_label(current.analysis)
            self.canStart = current.can_repair() and not self.running and not current.done
        else:
            pending = self.batch.to_repair()
            self.primaryText = f"Alle reparieren ({len(pending)})" if pending else "Alle reparieren"
            self.canStart = bool(pending) and not self.running
        self.canRetry = bool(self.batch.failed()) and not self.running
        # Gesamtfortschritt
        if self.running:
            total = len(self.run_keys)
            done = sum(1 for key in self.run_keys if (item := self.batch.get(key)) is not None and item.state not in (ItemState.REPAIRING,) and key not in self.queue)
            working = next((item for key in self.run_keys if (item := self.batch.get(key)) is not None and item.state is ItemState.REPAIRING), None)
            self.progressText = f"{done} / {total} Dateien" if total > 1 else (presentation.PHASE_TEXT.get(working.phase, "") if working else "")
            self.progressValue = (done + (working.fraction or 0) if working else done) / total if total else -1.0
            self.currentText = f"{working.name} · {STAGES.get(working.stage, 'Bitte warten …')}" if working else ""
            if working is not None:
                self.app.set_status(f"{self.progressText} · {working.name}" if total > 1 else STAGES.get(working.stage, "Bitte warten …"), "busy")
        else:
            self.progressText, self.progressValue, self.currentText = "", -1.0, ""

    def _refresh_item(self, item: BatchItem, progress: bool = False) -> None:
        row = self._row(item)
        if progress:
            self.model.update_item(item.key, phaseText=row["phaseText"], progress=row["progress"], busy=row["busy"], stateText=row["stateText"])
            if self.running:
                self._refresh_state()
            elif self.single:
                self.app.set_status(STAGES.get(item.stage, "Bitte warten …"), "busy")
        else:
            self.model.update_item(item.key, **{name: value for name, value in row.items() if name != "key"})

    def _row(self, item: BatchItem) -> dict:
        state_text, tone = presentation.item_state_text(item)
        analysis = item.analysis
        facts = presentation.analysis_facts(analysis) if analysis is not None else presentation.checking_facts(item.size)
        details = presentation.analysis_details(analysis) if analysis is not None else []
        result = item.result
        base = item.name_input if item.name_input is not None else (strip_pdf(item.output.name) if item.output else item.base(self.appendSuffix, self.suffix))
        planned = item.output or item.planned
        expected = f"{item.base(self.appendSuffix, self.suffix)}.pdf"
        phase = presentation.PHASE_TEXT.get(item.phase, "") if item.phase else ""
        if item.busy and item.stage:
            phase = f"{phase} · {STAGES.get(item.stage, '')}".strip(" ·")
        diag = presentation.condition_text(analysis) if analysis is not None else ("", "", "")
        outcome = presentation.result_summary(result, analysis, item.output) if result is not None else ("", "", "")
        # Kurztext der Karte: eigene Meldung; mit mehreren PDFs zusätzlich die Erklärung des Zustands
        # (im Einzelmodus stehen Diagnose und Ergebnis ausführlich in ihren Hinweisen)
        message = item.message
        if not message and not self.single:
            if item.state in (ItemState.ENCRYPTED, ItemState.UNREADABLE) and analysis is not None:
                message = diag[2]
            elif item.state in (ItemState.PARTIALLY_RECOVERED, ItemState.FAILED) and result is not None:
                message = outcome[2]
        return {
            "key": item.key,
            "name": item.name,
            "path": str(item.path),
            "sizeText": size_text(item.size),
            "state": item.state.value,
            "stateText": state_text,
            "tone": tone,
            "message": message,
            "busy": item.busy,
            "phaseText": phase,
            "progress": item.fraction if item.fraction is not None else -1.0,
            "outputBase": base,
            "outputName": planned.name if planned else "",
            "outputFolder": str(planned.parent) if planned else "",
            "numbered": bool(planned) and item.output is None and planned.name.casefold() != expected.casefold(),
            "nameManual": item.name_mode is NameMode.MANUAL,
            "nameError": item.name_error,
            "needsPassword": item.state is ItemState.ENCRYPTED,
            "canRepair": item.can_repair() and not self.running and not item.done,
            "repairText": presentation.repair_label(analysis),
            "signatures": item.signatures,
            "rescue": item.rescue and not self.running and not item.busy,
            "hasOutput": item.output is not None,
            "facts": facts,
            "details": details,
            "resultFacts": presentation.result_facts(result, item.output) if result is not None else [],
            "warnings": presentation.result_warnings(result) if result is not None else [],
            "inRun": self.running and item.key in self.run_keys,
            "canAnalyze": item.analysis is None and item.state in (ItemState.CANCELLED, ItemState.FAILED),
            "diagSeverity": diag[0],
            "diagTitle": diag[1],
            "diagText": diag[2],
            "resultSeverity": outcome[0],
            "resultTitle": outcome[1],
            "resultText": outcome[2],
            "resultActions": presentation.result_actions(result) if result is not None else [],
        }

    # Konstante Angaben für QML ------------------------------------------------------------------------------------
    def _texts(self) -> dict:
        return {
            "privacy": presentation.PRIVACY,
            "outOriginal": OUT_ORIGINAL,
            "outFolder": OUT_FOLDER,
            "emptyTitle": presentation.EMPTY_TITLE,
            "emptyText": presentation.EMPTY_TEXT,
            "namingHint": presentation.NAMING_HINT,
            "defaultSuffix": DEFAULT_SUFFIX,
            "rescueTitle": presentation.RESCUE_TITLE,
            "rescueText": presentation.RESCUE_TEXT,
            "rescueAction": presentation.RESCUE_ACTION,
            "rescueActionShort": presentation.RESCUE_ACTION_SHORT,
        }

    def _items(self) -> QObject:
        return self.model

    _constant = Signal()
    texts = Property("QVariantMap", _texts, notify=_constant)
    items = Property(QObject, _items, notify=_constant)


class RepairTool:
    """Verbindet den Controller mit dem AppController (Tastenkürzel, Drag & Drop, Hilfe, Speichern)."""

    key = REPAIR.key

    def __init__(self, app, cfg: dict) -> None:
        self.app = app
        self.controller = RepairController(app, cfg, app)
        app.register_tool(self.key, self)
        self.controller.start()

    # ToolHooks (AppController) -----------------------------------------------------------------------------------
    def primary_action(self, page: str) -> None:
        self.controller.start_repair()

    def open_action(self, page: str) -> None:
        self.controller.pick()

    def find_action(self, page: str) -> None:
        pass

    def show_help(self, page: str) -> None:
        self.app.show_steps("Kurzanleitung – PDF reparieren", presentation.HELP_STEPS, presentation.HELP_NOTES)

    def hint(self, page: str) -> str:
        return presentation.HINT

    def accepts(self, dropped: list[str], page: str) -> bool:
        return self.controller.accepts(dropped)

    def drag_enter(self, accepted: bool, page: str) -> None:
        self.controller.drag_enter(accepted)

    def drag_leave(self) -> None:
        self.controller.drag_leave()

    def drop(self, dropped: list[str], page: str) -> None:
        self.controller.drop(dropped)

    def page_prepare(self, page: str) -> None:
        # Einen Arbeitsprozess vorbereiten (im Hintergrund): Die erste Analyse wartet dann nicht auf seinen Start
        process.prepare_worker()

    def page_left(self, page: str) -> None:
        pass

    def config(self) -> dict:
        return self.controller.config()

    def autosave(self) -> None:
        pass

    def changed(self) -> None:
        pass

    def confirm_close(self) -> bool:
        return True

    def running_work(self) -> str:
        return "PDF-Reparatur" if self.controller.busy or self.controller.running else ""

    def close(self) -> None:
        self.controller.close()


__all__ = ["RepairController", "RepairTool", "size_text"]
