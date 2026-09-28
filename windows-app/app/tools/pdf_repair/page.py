"""Werkzeug »PDF reparieren« – Ablauf und Oberfläche.

Ablauf: PDF wählen (Dialog oder Hineinziehen) → Analyse im Arbeitsprozess →
Karte »Analyse« mit Zustand und Diagnose → »PDF reparieren« (bei digitalen
Signaturen erst nach Bestätigung) → Fortschritt mit »Abbrechen« → Ergebnis mit
Öffnen, Ordner öffnen, Pfad kopieren und »Weitere PDF reparieren«.

Die Originaldatei wird nur gelesen. Passwörter bleiben ausschließlich im
Arbeitsspeicher und erscheinen weder im Protokoll noch in den Einstellungen.
"""

from __future__ import annotations

import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog
from types import SimpleNamespace
from typing import TYPE_CHECKING

from appstate import DATA_DIR, ICON_FILE, desktop_dir
from ui import dialogs, icons
from ui.components import DropZone, FactList, FileRow, StatusLine
from ui.context import ctx
from ui.inputs import TextField
from ui.navigation import Page
from ui.theme import px
from ui.widgets import Button, Card, Collapsible, Divider, FlowRow, Icon, IconButton, InfoBar, RadioGroup, Text, frame

from . import process
from .models import STAGES, Condition, PdfAnalysis, PdfRepairResult, RepairMode, RepairStatus

if TYPE_CHECKING:
    from vertragdesk import App

HINT = "Strg+O  PDF auswählen   ·   Strg+Enter  PDF reparieren"
PRIVACY = "Die Verarbeitung erfolgt vollständig lokal auf diesem PC. Keine Datei wird hochgeladen."
LOG_FILE = "pdf-repair.log"
LOG_LIMIT = 1_000_000  # Byte, danach wird das Protokoll einmal rotiert
POLL_MS = 80
REVEAL_MS = 280
OUT_ORIGINAL = "original"
OUT_FOLDER = "ordner"
HELP_STEPS = (
    "Eine PDF wählen (Strg+O) oder in das Fenster ziehen – sie wird sofort analysiert.",
    "Die Analyse lesen: Keine Fehler, reparierbare Probleme oder schwer beschädigt.",
    "Verschlüsselte PDFs erst mit dem richtigen Passwort entsperren.",
    "Auf »PDF reparieren« klicken oder Strg+Enter drücken. Ein laufender Vorgang lässt sich abbrechen.",
    "Das Ergebnis öffnen, den Ordner anzeigen oder den Pfad kopieren.",
)
HELP_NOTES = (
    "Die Originaldatei wird nie verändert. Die reparierte Datei heißt »<Name>_repariert.pdf« (bei Bedarf »_2«, »_3« …).",
    "Nicht jede Datei lässt sich vollständig wiederherstellen; teilweise gerettete Dateien werden deutlich gekennzeichnet.",
    "Der Rettungsmodus überträgt lesbare Seiten als Bilder – nur nach Bestätigung, weil Text- und Vektorinformationen verloren gehen.",
    "Passwörter werden nicht gespeichert. Technische Details stehen im Protokoll pdf-repair.log im Datenordner.",
)

CONDITION_TEXT = {
    Condition.HEALTHY: ("success", "Keine Fehler gefunden", "Die PDF scheint strukturell in Ordnung zu sein. Eine Reparatur ist nicht nötig."),
    Condition.REPAIRABLE: ("warning", "Reparierbare Probleme erkannt", "PDF Tool hat beschädigte Strukturen gefunden, die möglicherweise repariert werden können."),
    Condition.DAMAGED: ("warning", "Schwer beschädigt", "Teile der PDF können nicht gelesen werden. PDF Tool versucht, so viele Seiten und Inhalte wie möglich wiederherzustellen."),
    Condition.UNREADABLE: ("error", "Keine Reparatur möglich", "Die Datei lässt sich mit keiner der eingebauten Engines lesen."),
    Condition.ENCRYPTED: ("info", "Die PDF ist verschlüsselt", "Zum Öffnen wird ein Passwort benötigt."),
}
STATUS_TONE = {"success": "success", "warning": "caution", "error": "critical", "info": "", "neutral": ""}


def size_text(size: int | None) -> str:
    if size is None:
        return "–"
    value = float(size)
    for unit in ("Byte", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            if unit == "Byte":
                return f"{int(value)} Byte"
            return f"{value:.1f} {unit}".replace(".", ",")
        value /= 1024
    return f"{size} Byte"


def is_pdf(path: str) -> bool:
    return str(path).lower().endswith(".pdf")


class RepairLog:
    """Technisches Protokoll ``pdf-repair.log`` im Datenordner – ohne PDF-Inhalte und Passwörter."""

    def __init__(self, folder: Path) -> None:
        self.path = folder / LOG_FILE

    def write(self, lines: list[str]) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            if self.path.is_file() and self.path.stat().st_size > LOG_LIMIT:
                self.path.replace(self.path.with_suffix(".log.1"))
            stamp = time.strftime("%Y-%m-%d %H:%M:%S")
            with open(self.path, "a", encoding="utf-8") as handle:
                for line in lines:
                    handle.write(f"{stamp}  {line}\n")
        except OSError:
            pass


class RepairTool:
    """Zustand und Ablauf des Werkzeugs. Die Oberfläche entsteht in ``build()``."""

    def __init__(self, app: "App", cfg: dict) -> None:
        self.app = app
        self.ui = SimpleNamespace()
        self.path: Path | None = None
        self.analysis: PdfAnalysis | None = None
        self.result: PdfRepairResult | None = None
        self.output: Path | None = None
        self._password: str | None = None  # nur im Arbeitsspeicher
        self.var_password = tk.StringVar(app, "")
        mode = cfg.get("reparatur_ausgabe")
        self.var_out_mode = tk.StringVar(app, mode if mode in (OUT_ORIGINAL, OUT_FOLDER) else OUT_ORIGINAL)
        self.out_dir = str(cfg.get("reparatur_ordner") or "")
        self.source_dir = str(cfg.get("ordner_reparatur") or "")
        self.job: process.Job | None = None
        self.job_kind = ""
        self.stage = ""
        self._poll = None
        self.busy = False
        self.log = RepairLog(DATA_DIR)
        self.var_out_mode.trace_add("write", lambda *_a: self._output_changed())
        process.cleanup_stale()

    # Einstellungen ---------------------------------------------------------------------
    def config(self) -> dict:
        return {
            "reparatur_ausgabe": self.var_out_mode.get(),
            "reparatur_ordner": self.out_dir,
            "ordner_reparatur": self.source_dir,
        }

    # Datei wählen ------------------------------------------------------------------------
    def pick(self) -> None:
        if self.busy:
            return
        start = self.source_dir if self.source_dir and Path(self.source_dir).is_dir() else str(desktop_dir())
        path = filedialog.askopenfilename(parent=self.app, title="PDF zum Reparieren wählen", initialdir=start, filetypes=[("PDF", "*.pdf"), ("Alle Dateien", "*.*")])
        if path:
            self.use(path)

    def accepts(self, files: list[str]) -> bool:
        return any(is_pdf(f) for f in files)

    def drop(self, files: list[str]) -> None:
        pdf = next((f for f in files if is_pdf(f)), "")
        if not pdf:
            self.app.notify("repair_drop_info", "warning", "Bitte eine PDF-Datei in das Fenster ziehen.")
            return
        if len([f for f in files if is_pdf(f)]) > 1:
            self.app.set_status("Es wird eine PDF pro Vorgang repariert – die erste wurde übernommen.", "info")
        self.use(pdf)

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
        self.var_password.set("")
        self.app.hide_notice("repair_drop_info")
        self._show_result(None)
        self.app.schedule_save()
        self.analyze()

    # Analyse -------------------------------------------------------------------------------
    def analyze(self) -> None:
        if self.path is None:
            return
        self._render_file()
        self._start("analyze", {"path": str(self.path), "password": self._password})

    def unlock(self) -> None:
        password = self.var_password.get()
        if not password:
            self.app.notify("repair_info", "warning", "Bitte das Passwort der PDF eingeben.")
            return
        self._password = password
        self.var_password.set("")
        self.analyze()

    # Reparatur -----------------------------------------------------------------------------
    def start_repair(self, mode: RepairMode | None = None) -> None:
        analysis = self.analysis
        if self.busy or analysis is None or self.path is None:
            return
        if analysis.condition is Condition.ENCRYPTED:
            self.app.notify("repair_info", "warning", "Bitte zuerst das Passwort eingeben.")
            return
        if mode is None:
            mode = RepairMode.REBUILD if analysis.condition is Condition.HEALTHY else RepairMode.AUTO
        if mode is not RepairMode.RASTER and analysis.condition is Condition.UNREADABLE:
            self.app.notify("repair_info", "error", "Diese Datei lässt sich nicht reparieren.")
            return
        if analysis.signatures and not dialogs.confirm(
            self.app,
            "Digital signierte PDF",
            "Die PDF enthält digitale Signaturen. Eine Reparatur kann deren Gültigkeit aufheben.\n\n"
            "Die Originaldatei bleibt unverändert; die Signaturen der reparierten Kopie sind danach möglicherweise ungültig.",
            "Trotzdem reparieren",
            icon=ICON_FILE,
        ):
            return
        if mode is RepairMode.RASTER and not dialogs.confirm(
            self.app,
            "Lesbare Seiten als Bilder retten?",
            "Im Rettungsmodus werden die lesbaren Seiten als Bilder in eine neue PDF übertragen.\n\n"
            "Text- und Vektorinformationen gehen dabei verloren: Text ist nicht mehr durchsuchbar oder kopierbar, "
            "Links, Formulare und Lesezeichen fehlen. Die Originaldatei bleibt unverändert.",
            "Seiten retten",
            danger=False,
            icon=ICON_FILE,
        ):
            return
        self._show_result(None)
        self._start("repair", {"path": str(self.path), "password": self._password, "mode": mode.value, "sha256": analysis.sha256})

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

    def reset(self) -> None:
        """»Weitere PDF reparieren«: Zustand leeren, Ausgabeort und Einstellungen bleiben."""
        if self.busy:
            return
        self.path = None
        self.analysis = None
        self.result = None
        self.output = None
        self._password = None
        self.var_password.set("")
        self._show_result(None)
        self._show_analysis(False)
        self.app.hide_notice("repair_info")
        self.app.set_status("Bereit für die nächste PDF.", "neutral")
        try:
            self.ui.drop.button.focus_set()
        except (AttributeError, tk.TclError):
            pass

    # Arbeitsprozess ------------------------------------------------------------------------
    def _start(self, kind: str, request: dict) -> None:
        self.job_kind = kind
        self.stage = "hash"
        try:
            self.job = process.Job(kind, request)
        except Exception as exc:  # z. B. Prozess lässt sich nicht starten
            self.job = None
            self.app.notify("repair_info", "error", str(exc), title="Der Vorgang konnte nicht gestartet werden")
            return
        self._set_busy(True)
        self._progress("hash", None)
        self._poll = self.app.after(POLL_MS, self._poll_job)

    def _poll_job(self) -> None:
        self._poll = None
        job = self.job
        if job is None:
            return
        for event in job.events():
            kind = event[0]
            if kind == "progress":
                self._progress(event[1], event[2])
            elif kind == "result":
                self._finish(event[1])
            elif kind == "error":
                self._failed(event[1])
            elif kind == "crash":
                self._failed(
                    f"Die Verarbeitung wurde unerwartet beendet (Code {event[1]}). Die Datei ist möglicherweise so stark "
                    "beschädigt oder so groß, dass die PDF-Engine abgebrochen hat. Es wurde keine Datei gespeichert; "
                    "die Originaldatei ist unverändert."
                )
        if self.job is job and not job.done:
            self._poll = self.app.after(POLL_MS, self._poll_job)

    def _progress(self, stage: str, fraction: float | None) -> None:
        self.stage = stage
        text = STAGES.get(stage, "Bitte warten …")
        if fraction is not None and 0 < fraction < 1:
            text = f"{text} {int(fraction * 100)} %"
        progress = getattr(self.ui, "progress", None)
        if progress is not None:
            progress.set("busy", text)
        self.app.set_status(text, "busy")

    def _set_busy(self, busy: bool) -> None:
        self.busy = busy
        ui = self.ui
        if not hasattr(ui, "btn_repair"):
            return
        ui.btn_repair.set_enabled(not busy and self._can_repair())
        ui.btn_pick.set_enabled(not busy)
        ui.drop.button.set_enabled(not busy)
        if busy:
            ui.btn_cancel.set_enabled(True)
            ui.progress_area.expand(animate=False)
        else:
            ui.btn_cancel.set_enabled(False)
            ui.progress_area.collapse(animate=False)

    def _finish(self, payload) -> None:
        job, self.job = self.job, None
        self._set_busy(False)
        if isinstance(payload, PdfAnalysis):
            if job is not None:
                job.cleanup()
            self._analysis_done(payload)
        elif isinstance(payload, PdfRepairResult):
            self._repair_done(payload, job)

    def _failed(self, message: str) -> None:
        job, self.job = self.job, None
        if job is not None:
            job.cleanup()
        self._set_busy(False)
        self.log.write([f"Fehler ({self.job_kind}): {message}"])
        self.app.notify("repair_info", "error", message, title="Vorgang fehlgeschlagen")

    # Ergebnisse -------------------------------------------------------------------------------
    def _analysis_done(self, analysis: PdfAnalysis) -> None:
        self.analysis = analysis
        name = Path(analysis.path).name
        self.log.write([f"Analyse {name} ({size_text(analysis.size)}): {analysis.condition.value}, Engine {analysis.engine}"] + [f"  {line}" for line in analysis.technical[:80]])
        self._render_analysis()
        severity, title, message = CONDITION_TEXT[analysis.condition]
        if analysis.condition is Condition.ENCRYPTED and analysis.password_rejected:
            severity, message = "error", "Das Passwort ist falsch. Bitte erneut eingeben."
        if analysis.error and analysis.condition is Condition.UNREADABLE:
            message = f"{analysis.error} {message}" if not message.startswith(analysis.error) else message
        self.app.set_status(f"{title}: {name}", {"success": "success", "warning": "warning", "error": "error"}.get(severity, "info"))
        self.app.hide_notice("repair_info")
        if analysis.condition is Condition.ENCRYPTED:
            self.ui.password_area.expand()
            try:
                self.ui.field_password.entry.focus_set()
            except tk.TclError:
                pass
        else:
            self.ui.password_area.collapse()

    def _repair_done(self, result: PdfRepairResult, job: process.Job | None) -> None:
        self.result = result
        name = Path(result.input_path).name
        lines = [f"Reparatur {name}: {result.status.value}" + (f" über {result.method.value}" if result.method else "")]
        lines += [f"  Aktion: {a}" for a in result.repair_actions] + [f"  Warnung: {w}" for w in result.warnings]
        lines += [f"  {line}" for line in result.technical[:120]]
        if result.error:
            lines.append(f"  Fehler: {result.error}")
        try:
            if result.usable and self.path is not None:
                try:
                    folder = self._output_folder()
                    self.output = process.deliver(Path(result.output_path), self.path, folder)
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
        self._output_changed()  # nächster freier Name (»_2«, »_3« …) für einen weiteren Durchlauf
        if self.output is not None:
            self.app.set_status(f"Gespeichert: {self.output.name}", "success" if result.status is RepairStatus.REPAIRED else "warning")
        elif result.status is RepairStatus.ENCRYPTED:
            self.app.set_status("Passwort fehlt oder ist falsch.", "error")
        else:
            self.app.set_status("PDF konnte nicht repariert werden.", "error")

    # Aktionen im Ergebnis ------------------------------------------------------------------------
    def open_output(self) -> None:
        if self.output is not None:
            self.app.open_file(self.output, "repair_result_info")

    def open_output_folder(self) -> None:
        if self.output is not None:
            self.app.open_folder_of(self.output, "repair_result_info")

    def copy_output_path(self) -> None:
        if self.output is not None:
            self.app.copy_path(self.output)

    # Ausgabeort ------------------------------------------------------------------------------------
    def pick_out_dir(self) -> None:
        start = self.out_dir if self.out_dir and Path(self.out_dir).is_dir() else (self.source_dir or str(desktop_dir()))
        path = filedialog.askdirectory(parent=self.app, title="Ordner für reparierte PDFs", initialdir=start)
        if path:
            self.out_dir = path
            self.var_out_mode.set(OUT_FOLDER)
            self._output_changed()

    def _output_folder(self) -> Path | None:
        if self.var_out_mode.get() == OUT_FOLDER and self.out_dir:
            return Path(self.out_dir)
        return None  # neben der Original-PDF

    def _output_changed(self) -> None:
        ui = self.ui
        if not hasattr(ui, "row_out"):
            return
        folder = self.out_dir if self.var_out_mode.get() == OUT_FOLDER and self.out_dir else ""
        if self.var_out_mode.get() == OUT_FOLDER and not self.out_dir:
            ui.row_out.set_value("Bitte einen Ordner wählen")
        elif folder:
            ui.row_out.set_value(Path(folder).name or folder, folder)
        else:
            ui.row_out.set_value("Neben der Original-PDF")
        if self.path is not None:
            target = process.next_output(self.path, self._output_folder())
            ui.out_name.configure(text=f"Ausgabe: {target.name}")
        else:
            ui.out_name.configure(text="Ausgabe: <Name>_repariert.pdf – die Originaldatei wird nie überschrieben.")
        self.app.schedule_save()

    # Darstellung ---------------------------------------------------------------------------------
    def _can_repair(self) -> bool:
        analysis = self.analysis
        return analysis is not None and analysis.condition not in (Condition.ENCRYPTED, Condition.UNREADABLE)

    def _render_file(self) -> None:
        ui = self.ui
        if self.path is None or not hasattr(ui, "row_file"):
            return
        ui.row_file.set_value(self.path.name, str(self.path))
        ui.analysis_facts.set([("Größe", size_text(self.path.stat().st_size if self.path.exists() else None), ""), ("Status", "Wird geprüft …", "muted")])
        ui.analysis_info.hide(animate=False)
        ui.btn_repair.set_text("PDF reparieren")
        self._show_analysis(True)
        self._reveal(self.ui.analysis_area)
        self._output_changed()

    def _show_analysis(self, show: bool) -> None:
        area = getattr(self.ui, "analysis_area", None)
        if area is None:
            return
        if show:
            area.expand()
        else:
            area.collapse()

    def _render_analysis(self) -> None:
        ui = self.ui
        analysis = self.analysis
        if analysis is None or not hasattr(ui, "analysis_facts"):
            return
        severity, title, message = CONDITION_TEXT[analysis.condition]
        if analysis.condition is Condition.ENCRYPTED and analysis.password_rejected:
            severity, message = "error", "Das Passwort ist falsch. Bitte erneut eingeben."
        if analysis.condition is Condition.UNREADABLE and analysis.error:
            message = f"{analysis.error} {message}"
        facts = [("Größe", size_text(analysis.size), "")]
        if analysis.page_count or analysis.pages_expected:
            pages = analysis.page_count or analysis.pages_expected
            text = f"{pages}"
            if analysis.readable_pages is not None and analysis.readable_pages < pages:
                text += f" (davon {analysis.readable_pages} vollständig lesbar)"
            facts.append(("Seiten", text, ""))
        if analysis.pdf_version:
            facts.append(("PDF-Version", analysis.pdf_version, ""))
        facts.append(("Verschlüsselt", "ja" if analysis.encrypted else "nein", ""))
        if analysis.signatures:
            facts.append(("Digitale Signaturen", f"{analysis.signatures} – eine Reparatur kann sie ungültig machen", "caution"))
        facts.append(("Status", title, STATUS_TONE.get(severity, "")))
        ui.analysis_facts.set(facts)
        ui.analysis_info.show(severity, message, title, animate=False)
        # Befunde und Diagnose (aufklappbar)
        details = [(check.label, check.detail or ("in Ordnung" if check.ok else "–"), "success" if check.ok else ("critical" if check.ok is False else "muted")) for check in analysis.checks]
        for finding in analysis.structural_errors:
            details.append(("Befund", finding, "caution"))
        for warning in analysis.warnings:
            details.append(("Hinweis", warning, "caution"))
        if analysis.forms:
            details.append(("Formular", f"{analysis.form_fields} Felder", ""))
        if analysis.attachments:
            details.append(("Dateianhänge", str(analysis.attachments), ""))
        details.append(("Engine", analysis.engine, "muted"))
        ui.details_facts.set(details)
        # Schaltfläche passend zum Zustand
        healthy = analysis.condition is Condition.HEALTHY
        ui.btn_repair.set_text("Trotzdem neu aufbauen" if healthy else "PDF reparieren")
        ui.btn_repair.set_enabled(self._can_repair() and not self.busy)
        if analysis.condition is Condition.UNREADABLE and analysis.rasterizable_pages:
            ui.analysis_info.show(severity, message, title, actions=(("Lesbare Seiten retten", lambda: self.start_repair(RepairMode.RASTER)),), animate=False)
        self._output_changed()

    def _show_result(self, result: PdfRepairResult | None) -> None:
        ui = self.ui
        if not hasattr(ui, "result_area"):
            return
        if result is None:
            ui.result_area.collapse(animate=False)
            return
        status = result.status
        if status is RepairStatus.REPAIRED and self.output is not None:
            rebuilt = self.analysis is not None and self.analysis.condition is Condition.HEALTHY
            ui.result_info.show("success", "Die reparierte Datei wurde geprüft und gespeichert." if not rebuilt else "Die PDF wurde neu aufgebaut, geprüft und gespeichert.", "PDF wurde repariert." if not rebuilt else "PDF wurde neu aufgebaut.", animate=False)
        elif status is RepairStatus.PARTIALLY_RECOVERED and self.output is not None:
            first = result.warnings[0] if result.warnings else "Nicht alle Inhalte konnten wiederhergestellt werden."
            ui.result_info.show("warning", first, "PDF teilweise wiederhergestellt", animate=False)
        elif status is RepairStatus.ENCRYPTED:
            ui.result_info.show("error", result.error or "Das Passwort fehlt oder ist falsch.", "PDF konnte nicht repariert werden.", animate=False)
        else:
            ui.result_info.show("error", result.error or "Es konnte keine lesbare PDF erzeugt werden.", "PDF konnte nicht repariert werden.", animate=False)
        facts = []
        if self.output is not None:
            facts.append(("Ausgabedatei", self.output.name, ""))
            facts.append(("Ordner", str(self.output.parent), "muted"))
        facts.append(("Ursprüngliche Größe", size_text(result.size_before), ""))
        if self.output is not None:
            facts.append(("Neue Größe", size_text(result.size_after), ""))
        if result.pages_before is not None:
            facts.append(("Seiten vorher", str(result.pages_before), ""))
        if self.output is not None and result.pages_after is not None:
            tone = "success" if result.pages_after == result.pages_before and not result.incomplete_pages else "caution"
            facts.append(("Seiten nachher", str(result.pages_after), tone))
        ui.result_facts.set(facts)
        for child in ui.result_warnings.winfo_children():
            child.destroy()
        warnings = result.warnings[1:] if status is RepairStatus.PARTIALLY_RECOVERED else result.warnings
        for warning in warnings:
            row = frame(ui.result_warnings)
            row.pack(fill="x", pady=(0, px(4)))
            if ctx().icons_available:
                Icon(row, icons.WARNING, color="caution").pack(side="left", anchor="n", padx=(0, px(8)), pady=(px(2), 0))
            Text(row, warning, style="body", wrap=True).pack(side="left", fill="x", expand=True)
        has_output = self.output is not None
        for button in (ui.btn_open, ui.btn_folder, ui.btn_copy):
            button.set_enabled(has_output)
        ui.result_actions_details.set([(str(index), action, "") for index, action in enumerate(result.repair_actions, start=1)] or [("–", "Keine Aktionen", "muted")])
        rescue = (
            status in (RepairStatus.FAILED, RepairStatus.PARTIALLY_RECOVERED)
            and self.analysis is not None
            and self.analysis.rasterizable_pages > 0
            and result.method is not None and result.method.value != "raster"
        ) or (status is RepairStatus.FAILED and self.analysis is not None and self.analysis.rasterizable_pages > 0)
        if rescue:
            ui.rescue_info.show(
                "info",
                "Die lesbaren Seiten können als Bilder in eine neue PDF übertragen werden. Text- und Vektorinformationen können dabei teilweise verloren gehen.",
                "Rettungsmodus",
                actions=(("Lesbare Seiten als neue PDF retten", lambda: self.start_repair(RepairMode.RASTER)),),
                animate=False,
            )
        else:
            ui.rescue_info.hide(animate=False)
        ui.result_area.expand()
        self._reveal(ui.result_area)

    def _reveal(self, widget) -> None:
        """Karte nach dem Aufklappen in den sichtbaren Bereich scrollen."""
        page = getattr(self.ui, "page", None)
        if page is None:
            return

        def scroll() -> None:
            try:
                page.scroll.scroll_to_widget(widget)
            except tk.TclError:
                pass

        self.app.after(REVEAL_MS, scroll)  # nach der Aufklapp-Animation


def build(app: "App", host) -> Page:
    tool: RepairTool = app.repair
    ui = tool.ui
    page = Page(host, "PDF reparieren", "Beschädigte PDF-Dateien analysieren und lesbare Inhalte in eine neue PDF übertragen.")
    ui.page = page

    note = frame(page.content)
    page.add_section(note, pady=(0, px(12)))
    if ctx().icons_available:
        Icon(note, icons.SHIELD, color="text2").pack(side="left", anchor="n", padx=(0, px(8)), pady=(px(1), 0))
    Text(note, PRIVACY, style="caption", color="text2", wrap=True).pack(side="left", fill="x", expand=True)

    # PDF auswählen ----------------------------------------------------------------------------
    ui.drop = DropZone(
        page.content,
        icons.PDF,
        "PDF hierher ziehen",
        "oder eine Datei auswählen – eine PDF pro Vorgang. Die Originaldatei wird nie verändert.",
        "PDF auswählen",
        tool.pick,
        button_icon=icons.OPEN_FILE,
    )
    page.add_section(ui.drop)
    app.ui.repair_drop_info = InfoBar(page.content)
    page.add_section(app.ui.repair_drop_info, pady=(px(8), 0))

    # Analyse ---------------------------------------------------------------------------------------
    ui.analysis_area = Collapsible(page.content)
    page.add_section(ui.analysis_area, pady=(px(12), 0))
    card = Card(ui.analysis_area.content, "Analyse", icons.PDF)
    card.pack(fill="x")
    ui.btn_pick = IconButton(card.header_right, icons.OPEN_FILE, tool.pick, tooltip="Andere PDF wählen (Strg+O)")
    ui.btn_pick.pack(side="right")
    body = card.body
    ui.row_file = FileRow(body, icons.PAGE, "Datei")
    ui.row_file.pack(fill="x")
    IconButton(ui.row_file.buttons, icons.COPY, lambda: app.copy_path(tool.path or ""), tooltip="Pfad der PDF kopieren").pack(side="right")
    ui.analysis_facts = FactList(body)
    ui.analysis_facts.pack(fill="x", pady=(px(12), px(4)))
    ui.analysis_info = InfoBar(body, closable=False)
    ui.analysis_info.pack(fill="x", pady=(px(8), 0))

    # Passwort (nur bei verschlüsselten PDFs)
    ui.password_area = Collapsible(body)
    ui.password_area.pack(fill="x")
    pw = ui.password_area.content
    Text(pw, "Passwort", style="body").pack(anchor="w", pady=(px(12), px(4)))
    row = frame(pw)
    row.pack(fill="x")
    ui.field_password = TextField(row, tool.var_password, placeholder="Passwort der PDF", width=260, on_submit=tool.unlock)
    ui.field_password.entry.configure(show="•")
    ui.field_password.pack(side="left")
    Button(row, "Entsperren", tool.unlock, icon=icons.LOCK).pack(side="left", padx=(px(8), 0))
    Text(pw, "Das Passwort wird nur für diesen Vorgang verwendet und nicht gespeichert.", style="caption", color="text2").pack(anchor="w", pady=(px(6), 0))

    # Technische Details (aufklappbar)
    details_toggle = frame(body)
    details_toggle.pack(fill="x", pady=(px(10), 0))
    ui.details_area = Collapsible(body)

    def toggle_details() -> None:
        if ui.details_area.expanded:
            ui.details_area.collapse()
            ui.btn_details.set_text("Technische Details anzeigen")
        else:
            ui.details_area.expand()
            ui.btn_details.set_text("Technische Details ausblenden")

    ui.btn_details = Button(details_toggle, "Technische Details anzeigen", toggle_details, icon=icons.INFO, kind="subtle")
    ui.btn_details.pack(side="left")
    ui.details_area.pack(fill="x")
    ui.details_facts = FactList(ui.details_area.content, label_width=190)
    ui.details_facts.pack(fill="x", pady=(px(8), px(4)))

    Divider(body).pack(fill="x", pady=(px(12), px(12)))
    # Ausgabe
    Text(body, "Speichern", style="body_strong").pack(anchor="w")
    RadioGroup(body, tool.var_out_mode, ((OUT_ORIGINAL, "Neben der Original-PDF"), (OUT_FOLDER, "Anderer Ordner"))).pack(anchor="w", pady=(px(6), px(4)))
    ui.row_out = FileRow(body, icons.FOLDER, "Ausgabeordner")
    ui.row_out.pack(fill="x", pady=(px(4), 0))
    Button(ui.row_out.buttons, "Durchsuchen", tool.pick_out_dir, icon=icons.FOLDER_OPEN, tooltip="Ordner für reparierte PDFs wählen").pack(side="right")
    ui.out_name = Text(body, "", style="caption", color="text2", wrap=True)
    ui.out_name.pack(anchor="w", fill="x", pady=(px(6), 0))

    # Aktionen
    ui.actions = FlowRow(body, gap=8, row_gap=8)
    ui.actions.pack(fill="x", pady=(px(14), 0))
    ui.btn_repair = Button(ui.actions, "PDF reparieren", lambda: tool.start_repair(), icon=icons.REPAIR, kind="accent", height=40, min_width=180, font="body_strong", tooltip="PDF reparieren (Strg+Enter)")
    ui.actions.add(ui.btn_repair)
    ui.btn_cancel = Button(ui.actions, "Abbrechen", tool.cancel, icon=icons.CANCEL, height=40, tooltip="Vorgang abbrechen – es bleibt keine unvollständige Datei zurück")
    ui.btn_cancel.set_enabled(False)
    ui.actions.add(ui.btn_cancel)
    ui.progress_area = Collapsible(body)
    ui.progress_area.pack(fill="x")
    ui.progress = StatusLine(ui.progress_area.content)
    ui.progress.pack(fill="x", pady=(px(12), 0))
    app.ui.repair_info = InfoBar(body)
    app.ui.repair_info.pack(fill="x", pady=(px(8), 0))

    # Ergebnis ------------------------------------------------------------------------------------------
    ui.result_area = Collapsible(page.content)
    page.add_section(ui.result_area, pady=(px(12), 0))
    result = Card(ui.result_area.content, "Ergebnis", icons.COMPLETED)
    result.pack(fill="x")
    body = result.body
    ui.result_info = InfoBar(body, closable=False)
    ui.result_info.pack(fill="x")
    ui.result_facts = FactList(body)
    ui.result_facts.pack(fill="x", pady=(px(12), px(4)))
    ui.result_warnings = frame(body)
    ui.result_warnings.pack(fill="x", pady=(px(8), 0))
    row = FlowRow(body, gap=8, row_gap=8)
    row.pack(fill="x", pady=(px(12), 0))
    ui.btn_open = Button(row, "Öffnen", tool.open_output, icon=icons.OPEN_IN_WINDOW, kind="accent")
    row.add(ui.btn_open)
    ui.btn_folder = Button(row, "Ordner öffnen", tool.open_output_folder, icon=icons.FOLDER_OPEN)
    row.add(ui.btn_folder)
    ui.btn_copy = Button(row, "Pfad kopieren", tool.copy_output_path, icon=icons.COPY)
    row.add(ui.btn_copy)
    row.add(Button(row, "Weitere PDF reparieren", tool.reset, icon=icons.ADD))
    ui.rescue_info = InfoBar(body, closable=False)
    ui.rescue_info.pack(fill="x", pady=(px(10), 0))
    app.ui.repair_result_info = InfoBar(body)
    app.ui.repair_result_info.pack(fill="x", pady=(px(4), 0))
    details_toggle = frame(body)
    details_toggle.pack(fill="x", pady=(px(8), 0))
    ui.result_details = Collapsible(body)

    def toggle_result_details() -> None:
        if ui.result_details.expanded:
            ui.result_details.collapse()
            ui.btn_result_details.set_text("Details anzeigen")
        else:
            ui.result_details.expand()
            ui.btn_result_details.set_text("Details ausblenden")

    ui.btn_result_details = Button(details_toggle, "Details anzeigen", toggle_result_details, icon=icons.BULLETED_LIST, kind="subtle")
    ui.btn_result_details.pack(side="left")
    ui.result_details.pack(fill="x")
    ui.result_actions_details = FactList(ui.result_details.content, label_width=40)
    ui.result_actions_details.pack(fill="x", pady=(px(8), 0))

    tool._set_busy(False)
    ui.btn_repair.set_enabled(False)
    tool._output_changed()
    return page
