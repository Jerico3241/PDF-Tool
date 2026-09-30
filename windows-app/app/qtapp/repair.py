"""Werkzeug »PDF reparieren« (in QML: ``Repair``).

Ablauf wie bis 2.6: PDF wählen (Dialog oder Hineinziehen) → Analyse im Arbeitsprozess →
Karte »Analyse« mit Zustand und Diagnose → »PDF reparieren« (bei digitalen Signaturen und
im Rettungsmodus erst nach Bestätigung) → Fortschritt mit »Abbrechen« → Ergebnis mit
Öffnen, Ordner öffnen, Pfad kopieren und »Weitere PDF reparieren«.

Analyse und Reparatur laufen in einem eigenen Prozess (``tools.pdf_repair.process``); der
Controller fragt dessen Meldungen im GUI-Thread ab. Die Originaldatei wird nur gelesen.
Passwörter bleiben ausschließlich im Arbeitsspeicher: Sie sind keine Property, stehen weder
im Protokoll noch in den Einstellungen, und das Eingabefeld wird nach jedem Versuch geleert.
"""

from __future__ import annotations

import traceback
from pathlib import Path

from PySide6.QtCore import Property, QObject, QTimer, Signal, Slot

from appstate import DATA_DIR, desktop_dir
from tools.pdf_repair import presentation
from tools.pdf_repair import process
from tools.pdf_repair.models import STAGES, Condition, PdfAnalysis, PdfRepairResult, RepairMode, RepairStatus
from tools.pdf_repair.presentation import OUT_FOLDER, OUT_ORIGINAL, RepairLog, is_pdf, size_text
from tools.registry import REPAIR

from . import files
from .base import Observable, Var, prop

POLL_MS = 80
CLEANUP_DELAY_MS = 3000  # alte Arbeitsordner erst nach dem Start im Hintergrund entfernen
ANALYSIS_AREA = "repair_analysis"
RESULT_AREA = "repair_result"
RESCUE_AREA = "repair_rescue"


class RepairController(Observable):
    """Zustand und Ablauf des Werkzeugs – QML zeigt nur an und ruft die Slots auf."""

    # Datei
    hasFileChanged, hasFile = prop(bool, "hasFile", False)
    fileNameChanged, fileName = prop(str, "fileName", "")
    filePathChanged, filePath = prop(str, "filePath", "")
    # Analyse
    analyzedChanged, analyzed = prop(bool, "analyzed", False)
    conditionChanged, condition = prop(str, "condition", "")
    factsChanged, facts = prop(list, "facts", [])
    detailsChanged, details = prop(list, "details", [])
    needsPasswordChanged, needsPassword = prop(bool, "needsPassword", False)
    canRepairChanged, canRepair = prop(bool, "canRepair", False)
    repairTextChanged, repairText = prop(str, "repairText", "PDF reparieren")
    # Laufender Vorgang
    busyChanged, busy = prop(bool, "busy", False)
    jobKindChanged, jobKind = prop(str, "jobKind", "")
    progressTextChanged, progressText = prop(str, "progressText", "")
    progressValueChanged, progressValue = prop(float, "progressValue", -1.0)  # −1: unbestimmt
    # Ausgabe
    outModeChanged, outMode = prop(str, "outMode", OUT_ORIGINAL)
    outLabelChanged, outLabel = prop(str, "outLabel", "Neben der Original-PDF")
    outPathChanged, outPath = prop(str, "outPath", "")
    outMissingChanged, outMissing = prop(bool, "outMissing", False)
    outNameChanged, outName = prop(str, "outName", presentation.OUT_NAME_EMPTY)
    # Ergebnis
    hasResultChanged, hasResult = prop(bool, "hasResult", False)
    hasOutputChanged, hasOutput = prop(bool, "hasOutput", False)
    resultFactsChanged, resultFacts = prop(list, "resultFacts", [])
    resultWarningsChanged, resultWarnings = prop(list, "resultWarnings", [])
    resultActionsChanged, resultActions = prop(list, "resultActions", [])
    # Ziehen und Ablegen
    dropHighlightChanged, dropHighlight = prop(bool, "dropHighlight", False)

    focusRequested = Signal(str)  # »password« oder »pick«
    revealRequested = Signal(str)  # »analysis« oder »result«: Karte nach dem Aufklappen zeigen
    passwordCleared = Signal()  # Passwortfeld leeren (nach jedem Versuch und bei neuer Datei)

    def __init__(self, app, cfg: dict, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.app = app
        self.path: Path | None = None
        self.analysis: PdfAnalysis | None = None
        self.result: PdfRepairResult | None = None
        self.output: Path | None = None
        self._password: str | None = None  # nur im Arbeitsspeicher
        mode = cfg.get("reparatur_ausgabe")
        self.set_quietly("outMode", mode if mode in (OUT_ORIGINAL, OUT_FOLDER) else OUT_ORIGINAL)
        self.out_dir = str(cfg.get("reparatur_ordner") or "")
        self.source_dir = str(cfg.get("ordner_reparatur") or "")
        self.var_out_mode = Var(self, "outMode")
        self.job: process.Job | None = None
        self.job_kind = ""
        self.stage = ""
        self.log = RepairLog(DATA_DIR)
        self._poll = QTimer(self)
        self._poll.setInterval(POLL_MS)
        self._poll.timeout.connect(self._poll_job)
        self.observe("outMode", lambda _value: self._output_changed())
        self._render_output()

    def start(self) -> None:
        """Nach dem Start: Arbeitsordner früherer, abgebrochener Sitzungen im Hintergrund entfernen."""
        self.app.timers.later("repair:cleanup", CLEANUP_DELAY_MS, lambda: self.app.worker.run(process.cleanup_stale))

    # Einstellungen ---------------------------------------------------------------------------------
    def config(self) -> dict:
        return {
            "reparatur_ausgabe": self.outMode,
            "reparatur_ordner": self.out_dir,
            "ordner_reparatur": self.source_dir,
        }

    # Datei wählen ------------------------------------------------------------------------------------
    @Slot()
    def pick(self) -> None:
        if self.busy:
            return
        start = self.source_dir if self.source_dir and Path(self.source_dir).is_dir() else str(desktop_dir())
        path = files.open_file("PDF zum Reparieren wählen", start, files.PDF_FILTER)
        if path:
            self.use(path)

    def accepts(self, dropped: list[str]) -> bool:
        return any(is_pdf(f) for f in dropped)

    def drag_enter(self, accepted: bool) -> None:
        if accepted:
            self.dropHighlight = True

    def drag_leave(self) -> None:
        self.dropHighlight = False

    def drop(self, dropped: list[str]) -> None:
        self.drag_leave()
        pdfs = [f for f in dropped if is_pdf(f)]
        if not pdfs:
            self.app.notify("repair_drop_info", "warning", "Bitte eine PDF-Datei in das Fenster ziehen.")
            return
        if len(pdfs) > 1:
            self.app.set_status("Es wird eine PDF pro Vorgang repariert – die erste wurde übernommen.", "info")
        self.use(pdfs[0])

    @Slot(str)
    def use(self, path: str) -> None:
        if self.busy:
            self.app.notify("repair_info", "warning", "Bitte warten, bis der laufende Vorgang beendet ist, oder ihn abbrechen.")
            return
        if not is_pdf(path):
            self.app.notify("repair_drop_info", "warning", "Bitte eine PDF-Datei wählen (Dateiendung .pdf).")
            return
        file = Path(path)
        if not file.is_file():
            self.app.notify("repair_drop_info", "error", "Die Datei ist nicht vorhanden.")
            return
        self.path = file
        self.source_dir = str(file.parent)
        self.analysis = None
        self.result = None
        self.output = None
        self._password = None
        self.passwordCleared.emit()
        self.needsPassword = False
        self.app.hide_notice("repair_drop_info")
        self._show_result(None)
        self.app.schedule_save()
        self.analyze()

    # Analyse -----------------------------------------------------------------------------------------
    def analyze(self) -> None:
        if self.path is None:
            return
        self._render_file()
        self._start("analyze", {"path": str(self.path), "password": self._password})

    @Slot(str)
    def unlock(self, password: str) -> None:
        """Verschlüsselte PDF mit dem eingegebenen Passwort erneut analysieren."""
        self.passwordCleared.emit()
        if not password:
            self.app.notify("repair_info", "warning", "Bitte das Passwort der PDF eingeben.")
            return
        if self.busy or self.path is None:
            return
        self._password = password
        self.analyze()

    # Reparatur ----------------------------------------------------------------------------------------
    @Slot()
    def startRepair(self) -> None:  # noqa: N802 - QML-Schreibweise
        self.start_repair()

    @Slot()
    def rescue(self) -> None:
        """Rettungsmodus: lesbare Seiten als Bilder in eine neue PDF (nur nach Bestätigung)."""
        self.start_repair(RepairMode.RASTER)

    def start_repair(self, mode: RepairMode | None = None) -> None:
        analysis = self.analysis
        path = self.path
        if self.busy or analysis is None or path is None:
            return
        if analysis.condition is Condition.ENCRYPTED:
            self.app.notify("repair_info", "warning", "Bitte zuerst das Passwort eingeben.")
            return
        if mode is None:
            mode = RepairMode.REBUILD if analysis.condition is Condition.HEALTHY else RepairMode.AUTO
        if mode is not RepairMode.RASTER and analysis.condition is Condition.UNREADABLE:
            self.app.notify("repair_info", "error", "Diese Datei lässt sich nicht reparieren.")
            return
        if analysis.signatures and not self._confirm(presentation.SIGNATURE_TITLE, presentation.SIGNATURE_TEXT, presentation.SIGNATURE_CONFIRM, danger=True):
            return
        if mode is RepairMode.RASTER and not self._confirm(presentation.RASTER_TITLE, presentation.RASTER_TEXT, presentation.RASTER_CONFIRM, danger=False):
            return
        # Während der Rückfrage kann eine andere PDF gewählt worden sein
        if self.busy or self.analysis is not analysis or self.path != path:
            return
        self._show_result(None)
        self._start("repair", {"path": str(path), "password": self._password, "mode": mode.value, "sha256": analysis.sha256})

    def _confirm(self, title: str, message: str, confirm: str, danger: bool) -> bool:
        return self.app.dialogs.confirm(title, message, confirm, danger=danger)

    @Slot()
    def cancel(self) -> None:
        job = self.job
        if job is None:
            return
        job.cancel()
        self.job = None
        self._set_busy(False)
        self.log.write([f"Abgebrochen: {self.job_kind} {self.path.name if self.path else ''}"])
        if self.job_kind == "repair":
            self.app.notify("repair_info", "info", "Die Reparatur wurde abgebrochen. Es wurde keine Datei gespeichert.")
        else:
            self.app.notify("repair_info", "info", "Die Analyse wurde abgebrochen.")

    @Slot()
    def reset(self) -> None:
        """»Weitere PDF reparieren«: Zustand leeren, Ausgabeort und Einstellungen bleiben."""
        if self.busy:
            return
        self.path = None
        self.analysis = None
        self.result = None
        self.output = None
        self._password = None
        self.passwordCleared.emit()
        self.needsPassword = False
        self._show_result(None)
        self.hasFile = False
        self.analyzed = False
        self.condition = ""
        self.canRepair = False
        self.app.hide_notice("repair_info")
        self.app.hide_notice(ANALYSIS_AREA, animate=False)
        self._render_output()
        self.app.set_status("Bereit für die nächste PDF.", "neutral")
        self.focusRequested.emit("pick")

    def close(self) -> None:
        """Beim Beenden: laufenden Arbeitsprozess beenden (sein Arbeitsordner wird gelöscht)."""
        self._poll.stop()
        job, self.job = self.job, None
        if job is not None:
            job.cancel()

    # Arbeitsprozess -------------------------------------------------------------------------------------
    def _start(self, kind: str, request: dict) -> None:
        self.job_kind = kind
        self.jobKind = kind
        self.stage = "hash"
        try:
            self.job = process.Job(kind, request)
        except Exception as exc:  # noqa: BLE001 - z. B. Prozess lässt sich nicht starten
            self.job = None
            self.app.notify("repair_info", "error", str(exc), title="Der Vorgang konnte nicht gestartet werden")
            return
        self._set_busy(True)
        self._progress("hash", None)
        self._poll.start()

    def _poll_job(self) -> None:
        job = self.job
        if job is None:
            self._poll.stop()
            return
        try:
            for event in job.events():
                kind = event[0]
                if kind == "progress":
                    self._progress(event[1], event[2])
                elif kind == "result":
                    self._finish(event[1])
                elif kind == "error":
                    self._failed(event[1])
                elif kind == "crash":
                    self._failed(presentation.crash_text(event[1]))
        except Exception:  # noqa: BLE001 - Fehler melden, die Oberfläche bleibt bedienbar
            self.app.report_exception(traceback.format_exc())
            if self.job is job:
                self.job = None
                job.cancel()
                self._set_busy(False)
        if self.job is not job or job.done:
            self._poll.stop()

    def _progress(self, stage: str, fraction: float | None) -> None:
        self.stage = stage
        text = STAGES.get(stage, "Bitte warten …")
        if fraction is not None and 0 < fraction < 1:
            text = f"{text} {int(fraction * 100)} %"
            self.progressValue = float(fraction)
        else:
            self.progressValue = -1.0
        self.progressText = text
        self.app.set_status(text, "busy")

    def _set_busy(self, busy: bool) -> None:
        self.busy = busy
        if not busy:
            self.progressValue = -1.0

    def _finish(self, payload) -> None:
        job, self.job = self.job, None
        self._set_busy(False)
        if isinstance(payload, PdfAnalysis):
            if job is not None:
                job.cleanup()
            self._analysis_done(payload)
        elif isinstance(payload, PdfRepairResult):
            self._repair_done(payload, job)
        elif job is not None:
            job.cleanup()

    def _failed(self, message: str) -> None:
        job, self.job = self.job, None
        if job is not None:
            job.cleanup()
        self._set_busy(False)
        self.log.write([f"Fehler ({self.job_kind}): {message}"])
        self.app.notify("repair_info", "error", message, title="Vorgang fehlgeschlagen")

    # Ergebnisse --------------------------------------------------------------------------------------------
    def _analysis_done(self, analysis: PdfAnalysis) -> None:
        self.analysis = analysis
        name = Path(analysis.path).name
        self.log.write(presentation.analysis_log(analysis))
        self._render_analysis()
        severity, title, _message = presentation.condition_text(analysis)
        self.app.set_status(f"{title}: {name}", presentation.SEVERITY_STATUS.get(severity, "info"))
        self.app.hide_notice("repair_info")
        encrypted = analysis.condition is Condition.ENCRYPTED
        self.needsPassword = encrypted
        if encrypted:
            self.focusRequested.emit("password")

    def _repair_done(self, result: PdfRepairResult, job: process.Job | None) -> None:
        self.result = result
        lines = presentation.result_log(result)
        try:
            if result.usable and self.path is not None:
                try:
                    self.output = process.deliver(Path(result.output_path), self.path, self._output_folder())
                except OSError as exc:
                    self.output = None
                    result.status = RepairStatus.FAILED
                    result.error = f"Die reparierte Datei konnte nicht gespeichert werden ({exc.strerror or exc})."
                    lines.append(f"  Speichern fehlgeschlagen: {exc}")
                else:
                    lines.append(f"  Gespeichert als {self.output.name}")
        finally:
            if job is not None:
                job.cleanup()
        self.log.write(lines)
        self._show_result(result)
        self._render_output()  # nächster freier Name (»_2«, »_3« …) für einen weiteren Durchlauf
        if self.output is not None:
            self.app.set_status(f"Gespeichert: {self.output.name}", "success" if result.status is RepairStatus.REPAIRED else "warning")
        elif result.status is RepairStatus.ENCRYPTED:
            self.app.set_status("Passwort fehlt oder ist falsch.", "error")
        else:
            self.app.set_status("PDF konnte nicht repariert werden.", "error")

    # Aktionen im Ergebnis -------------------------------------------------------------------------------------
    @Slot()
    def openOutput(self) -> None:  # noqa: N802
        if self.output is not None:
            self.app.open_file(self.output, "repair_result_info")

    @Slot()
    def openOutputFolder(self) -> None:  # noqa: N802
        if self.output is not None:
            self.app.open_folder_of(self.output, "repair_result_info")

    @Slot()
    def copyOutputPath(self) -> None:  # noqa: N802
        if self.output is not None:
            self.app.copy_path(self.output)

    @Slot()
    def copyInputPath(self) -> None:  # noqa: N802
        self.app.copy_path(self.path or "")

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

    def _output_folder(self) -> Path | None:
        if self.outMode == OUT_FOLDER and self.out_dir:
            return Path(self.out_dir)
        return None  # neben der Original-PDF

    def _output_changed(self) -> None:
        self._render_output()
        self.app.schedule_save()

    def _render_output(self) -> None:
        folder_mode = self.outMode == OUT_FOLDER
        self.outMissing = folder_mode and not self.out_dir
        if self.outMissing:
            self.outLabel, self.outPath = "Bitte einen Ordner wählen", ""
        elif folder_mode:
            self.outLabel, self.outPath = Path(self.out_dir).name or self.out_dir, self.out_dir
        else:
            self.outLabel, self.outPath = "Neben der Original-PDF", ""
        if self.path is not None:
            target = process.next_output(self.path, self._output_folder())
            self.outName = f"Ausgabe: {target.name}"
        else:
            self.outName = presentation.OUT_NAME_EMPTY

    # Darstellung -----------------------------------------------------------------------------------------------
    def _render_file(self) -> None:
        if self.path is None:
            return
        self.fileName = self.path.name
        self.filePath = str(self.path)
        self.facts = presentation.checking_facts(self.path.stat().st_size if self.path.exists() else None)
        self.details = []
        self.analyzed = False
        self.condition = ""
        self.canRepair = False
        self.repairText = presentation.repair_label(None)
        self.app.hide_notice(ANALYSIS_AREA, animate=False)
        self.hasFile = True
        self._render_output()
        self.revealRequested.emit("analysis")

    def _render_analysis(self) -> None:
        analysis = self.analysis
        if analysis is None:
            return
        severity, title, message = presentation.condition_text(analysis)
        self.facts = presentation.analysis_facts(analysis)
        actions = ()
        if analysis.condition is Condition.UNREADABLE and analysis.rasterizable_pages:
            actions = ((presentation.RESCUE_ACTION_SHORT, self.rescue),)
        self.app.notices.notify(ANALYSIS_AREA, severity, message, title, actions, animate=False)
        self.details = presentation.analysis_details(analysis)
        self.repairText = presentation.repair_label(analysis)
        self.canRepair = presentation.can_repair(analysis)
        self.condition = analysis.condition.value
        self.analyzed = True
        self._render_output()

    def _show_result(self, result: PdfRepairResult | None) -> None:
        if result is None:
            self.hasResult = False
            self.hasOutput = False
            return
        severity, title, message = presentation.result_summary(result, self.analysis, self.output)
        self.app.notices.notify(RESULT_AREA, severity, message, title, animate=False)
        self.resultFacts = presentation.result_facts(result, self.output)
        self.resultWarnings = presentation.result_warnings(result)
        self.resultActions = presentation.result_actions(result)
        self.hasOutput = self.output is not None
        self.app.hide_notice("repair_result_info", animate=False)
        if presentation.rescue_possible(result, self.analysis):
            self.app.notices.notify(RESCUE_AREA, "info", presentation.RESCUE_TEXT, presentation.RESCUE_TITLE, ((presentation.RESCUE_ACTION, self.rescue),), animate=False)
        else:
            self.app.hide_notice(RESCUE_AREA, animate=False)
        self.hasResult = True
        self.revealRequested.emit("result")

    # Konstante Angaben für QML ------------------------------------------------------------------------------------
    def _texts(self) -> dict:
        return {"privacy": presentation.PRIVACY, "outOriginal": OUT_ORIGINAL, "outFolder": OUT_FOLDER}

    _constant = Signal()
    texts = Property("QVariantMap", _texts, notify=_constant)


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
        pass

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

    def close(self) -> None:
        self.controller.close()


__all__ = ["RepairController", "RepairTool", "size_text"]
