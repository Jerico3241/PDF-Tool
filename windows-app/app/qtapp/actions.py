"""Werkzeug »Stapel-Aktionen« (in QML: ``Actions``) – dieselben Schritte auf viele PDFs anwenden.

Ablauf: PDFs wählen oder hineinziehen → Schritte ankreuzen (Text erkennen, bereinigen, reduzieren,
Wasserzeichen, Seitenzahlen, verkleinern, PDF/A, Kennwortschutz) → »Alle bearbeiten« → Fortschritt je
Datei, »Abbrechen« → Ergebnis je Datei. Bearbeitet wird nacheinander in einem Hintergrund-Thread mit den
Werkzeugen des PDF Editors (``tools.pdf_actions``); jede Datei wird für sich geöffnet und als neue Datei
gespeichert. Die Originale werden nur gelesen, vorhandene Dateien nie überschrieben (»Name (2).pdf«).

Das Kennwort für den Kennwortschutz bleibt nur im Arbeitsspeicher: keine Property, nicht im Protokoll,
nicht in den Einstellungen. Gemerkt werden nur die gewählten Schritte und ihre Einstellungen.
"""

from __future__ import annotations

import threading
from pathlib import Path

from PySide6.QtCore import Property, QObject, Signal, Slot

from tools.pdf_actions import actions
from tools.pdf_actions.actions import Plan
from tools.pdf_editor.errors import EditorError, PasswordRequired
from tools.registry import ACTIONS

from . import files
from .base import Observable, prop

CONFIG_KEY = "stapel_aktionen"
OUT_ORIGINAL = "original"
OUT_FOLDER = "folder"
MAX_FILES = 500
INFO_AREA = "actions_info"
HINT = "Strg+O  PDFs wählen   ·   Strg+Enter  Alle bearbeiten   ·   PDFs auch hineinziehen"
HELP_STEPS = (
    "PDFs wählen (Strg+O) oder in das Fenster ziehen – auch viele auf einmal.",
    "Aktionen ankreuzen. Die Reihenfolge ist fest und immer richtig: erst Text erkennen, zuletzt Kennwortschutz.",
    "Ausgabe wählen: neben den Originalen oder in einem gemeinsamen Ordner. An den Namen wird ein Zusatz angehängt.",
    "»Alle bearbeiten« (Strg+Enter). Jede PDF wird als neue Datei gespeichert; »Abbrechen« beendet nach der laufenden Datei.",
)
HELP_NOTES = (
    "Die Originale bleiben unverändert, vorhandene Dateien werden nie überschrieben.",
    "PDF/A und Kennwortschutz lassen sich nicht kombinieren – PDF/A erlaubt keine Verschlüsselung.",
    "Kennwortgeschützte PDFs werden ausgelassen; zuerst im Reader entsperren.",
)
STATE_TEXT = {"waiting": "Bereit", "running": "Wird bearbeitet …", "done": "Fertig", "error": "Fehler", "skipped": "Ausgelassen", "cancelled": "Nicht bearbeitet"}
STATE_TONE = {"waiting": "neutral", "running": "accent", "done": "success", "error": "critical", "skipped": "warning", "cancelled": "neutral"}


def _size(value: int) -> str:
    if value < 1024 * 1024:
        return f"{max(1, round(value / 1024))} KB"
    return f"{value / (1024 * 1024):.1f} MB".replace(".", ",")


class ActionsController(Observable):
    filesChanged, files = prop(list, "files", [])
    countChanged, count = prop(int, "count", 0)
    stepsChanged, steps = prop(list, "steps", [])  # [{key, label, description, checked}]
    # Für die Liste in QML (seit 4.0 Beta 7): feste Schritte und die gewählten getrennt – ändert sich nur die Auswahl,
    # entsteht die Liste nicht neu (sonst wäre kurz das zuletzt erzeugte Kästchen unter dem Mauszeiger »gehovert«)
    stepListChanged, stepList = prop(list, "stepList", [])  # [{key, label, description}]
    chosenChanged, chosen = prop(list, "chosen", [])  # Schlüssel der gewählten Schritte
    watermarkTextChanged, watermarkText = prop(str, "watermarkText", "VERTRAULICH")
    numberFormatChanged, numberFormat = prop(str, "numberFormat", "seite_von")
    numberPositionChanged, numberPosition = prop(str, "numberPosition", "bc")
    optimizeLevelChanged, optimizeLevel = prop(str, "optimizeLevel", "mittel")
    hasPasswordChanged, hasPassword = prop(bool, "hasPassword", False)
    outModeChanged, outMode = prop(str, "outMode", OUT_ORIGINAL)
    outPathChanged, outPath = prop(str, "outPath", "")
    suffixChanged, suffix = prop(str, "suffix", actions.DEFAULT_SUFFIX)
    problemChanged, problem = prop(str, "problem", "")
    summaryChanged, summary = prop(str, "summary", "")
    canStartChanged, canStart = prop(bool, "canStart", False)
    runningChanged, running = prop(bool, "running", False)
    progressTextChanged, progressText = prop(str, "progressText", "")
    progressValueChanged, progressValue = prop(float, "progressValue", 0.0)
    currentTextChanged, currentText = prop(str, "currentText", "")
    resultTextChanged, resultText = prop(str, "resultText", "")
    resultToneChanged, resultTone = prop(str, "resultTone", "neutral")
    dropHighlightChanged, dropHighlight = prop(bool, "dropHighlight", False)

    def __init__(self, app, cfg: dict, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.app = app
        stored = cfg.get(CONFIG_KEY) if isinstance(cfg.get(CONFIG_KEY), dict) else {}
        self._plan = Plan.from_settings(stored)
        self._password = ""  # nur im Arbeitsspeicher
        self._items: list[dict] = []
        self._next_key = 0  # fortlaufend: ein Schlüssel wird nie zweimal vergeben, auch nach Entfernen
        self._cancel: threading.Event | None = None
        self._last_folder = ""
        self.set_quietly("outMode", OUT_FOLDER if stored.get("ausgabe") == OUT_FOLDER else OUT_ORIGINAL)
        self.set_quietly("outPath", str(stored.get("ordner") or ""))
        suffix = str(stored.get("zusatz") or actions.DEFAULT_SUFFIX)
        self.set_quietly("suffix", suffix if _valid_suffix(suffix) else actions.DEFAULT_SUFFIX)
        self.set_quietly("watermarkText", self._plan.watermark_text)
        self.set_quietly("numberFormat", self._plan.number_format)
        self.set_quietly("numberPosition", self._plan.number_position)
        self.set_quietly("optimizeLevel", self._plan.optimize_level)
        self._refresh()

    # Einstellungen ------------------------------------------------------------------------------------------------
    def config(self) -> dict:
        data = self._plan.settings()
        data.update(ausgabe=self.outMode, ordner=self.outPath, zusatz=self.suffix)
        return {CONFIG_KEY: data}

    def _changed(self) -> None:
        self._refresh()
        self.app.schedule_save()

    @Slot(str, bool)
    def setStep(self, key: str, on: bool) -> None:  # noqa: N802
        if key not in actions.ORDER or self.running:
            return
        steps = [step for step in self._plan.steps if step != key]
        if on:
            steps.append(key)
            # PDF/A und Kennwortschutz schließen sich aus: das zuletzt gewählte gilt
            other = {actions.PDFA: actions.PROTECT, actions.PROTECT: actions.PDFA}.get(key)
            steps = [step for step in steps if step != other]
        self._plan.steps = steps
        self._changed()

    @Slot(str)
    def setWatermarkText(self, text: str) -> None:  # noqa: N802
        self._plan.watermark_text = str(text)[: actions.MAX_WATERMARK]
        self.watermarkText = self._plan.watermark_text
        self._changed()

    @Slot(str)
    def setNumberFormat(self, key: str) -> None:  # noqa: N802
        if key in actions.NUMBER_FORMATS:
            self._plan.number_format = self.numberFormat = key
            self._changed()

    @Slot(str)
    def setNumberPosition(self, key: str) -> None:  # noqa: N802
        if key in actions.NUMBER_POSITIONS:
            self._plan.number_position = self.numberPosition = key
            self._changed()

    @Slot(str)
    def setOptimizeLevel(self, key: str) -> None:  # noqa: N802
        if key in ("klein", "mittel", "hoch"):
            self._plan.optimize_level = self.optimizeLevel = key
            self._changed()

    @Slot(str)
    def setPassword(self, text: str) -> None:  # noqa: N802
        self._password = str(text)
        self._plan.password = self._password
        self.hasPassword = bool(self._password)
        self._refresh()

    @Slot(str)
    def setSuffix(self, text: str) -> None:  # noqa: N802
        self.suffix = str(text)
        self._changed()

    @Slot(str)
    def setOutMode(self, mode: str) -> None:  # noqa: N802
        if mode in (OUT_ORIGINAL, OUT_FOLDER) and not self.running:
            self.outMode = mode
            if mode == OUT_FOLDER and not self.outPath:
                self.pickOutDir()
            self._changed()

    @Slot()
    def pickOutDir(self) -> None:  # noqa: N802
        folder = files.pick_folder("Ordner für die bearbeiteten PDFs", self.app.initial_dir("stapel_ziel", self.outPath or self._last_folder))
        if folder:
            self.outPath = folder
            self.outMode = OUT_FOLDER
            self._changed()

    # Dateien --------------------------------------------------------------------------------------------------
    @Slot()
    def pick(self) -> None:
        paths = files.open_files("PDFs für Stapel-Aktionen wählen", self.app.initial_dir("stapel", self._last_folder), files.PDF_FILTER)
        if paths:
            self.add(paths)

    def accepts(self, paths: list[str]) -> bool:
        return any(_is_pdf(p) for p in paths)

    def add(self, paths: list[str]) -> None:
        if self.running:
            return
        known = {item["path"].lower() for item in self._items}
        added = 0
        for path in paths:
            if not _is_pdf(path) or str(path).lower() in known or len(self._items) >= MAX_FILES:
                continue
            p = Path(path)
            try:
                size = p.stat().st_size
            except OSError:
                continue
            self._next_key += 1
            self._items.append({"key": str(self._next_key) + ":" + p.name, "path": str(p), "name": p.name, "folder": str(p.parent), "size": size, "state": "waiting", "message": "", "output": ""})
            known.add(str(path).lower())
            added += 1
        if added:
            self._last_folder = str(Path(paths[0]).parent)
            self.app.remember_dir("stapel", paths[0])
            self.resultText = ""
        if len(self._items) >= MAX_FILES and added < len(paths):
            self.app.notify(INFO_AREA, "warning", f"Höchstens {MAX_FILES} PDFs auf einmal.", title="Nicht alle hinzugefügt", auto_hide=8000)
        self._refresh()

    @Slot(str)
    def remove(self, key: str) -> None:
        if not self.running:
            self._items = [item for item in self._items if item["key"] != key]
            self._refresh()

    @Slot()
    def removeAll(self) -> None:  # noqa: N802
        if not self.running:
            self._items = []
            self.resultText = ""
            self._refresh()

    @Slot(str)
    def openOutput(self, key: str) -> None:  # noqa: N802
        item = next((item for item in self._items if item["key"] == key and item["output"]), None)
        if item is not None:
            reader = getattr(self.app, "reader_controller", None)
            if reader is not None:
                reader.open_paths([item["output"]])
            else:
                self._open(item["output"])

    @Slot(str)
    def openFolder(self, key: str) -> None:  # noqa: N802
        item = next((item for item in self._items if item["key"] == key), None)
        if item is not None:
            self._open(str(Path(item["output"]).parent) if item["output"] else item["folder"])

    @Slot()
    def openOutputFolder(self) -> None:  # noqa: N802
        done = [item for item in self._items if item["output"]]
        if done:
            self._open(str(Path(done[0]["output"]).parent))

    def _open(self, path: str) -> None:
        try:
            files.open_path(path)
        except OSError:
            self.app.notify(INFO_AREA, "warning", "Der Ordner bzw. die Datei lässt sich nicht öffnen.", title="Nicht geöffnet", auto_hide=8000)

    # Bearbeiten -----------------------------------------------------------------------------------------------
    @Slot()
    def start(self) -> None:
        if not self.canStart:
            if self.problem:
                self.app.notify(INFO_AREA, "warning", self.problem, title="Noch nicht bereit", auto_hide=8000)
            return
        plan = Plan(**{**self._plan.__dict__, "steps": list(self._plan.steps), "password": self._password})
        jobs = []
        reserved: set[str] = set()
        for item in self._items:
            folder = Path(self.outPath) if self.outMode == OUT_FOLDER else Path(item["folder"])
            target = _free_name(folder, Path(item["name"]).stem + self.suffix, reserved)
            reserved.add(str(target).lower())
            item.update(state="waiting", message="", output="")
            jobs.append((item["key"], item["path"], str(target)))
        self._cancel = threading.Event()
        cancel = self._cancel
        self.running = True
        self.resultText = ""
        self.app.hide_notice(INFO_AREA)
        self._progress(0, len(jobs), "")
        self._refresh()
        post = self.app.worker.post

        def work() -> dict:
            from tools.pdf_actions import runner

            counts = {"done": 0, "error": 0, "skipped": 0, "cancelled": 0}
            for number, (key, source, target) in enumerate(jobs):
                if cancel.is_set():
                    for rest_key, _s, _t in jobs[number:]:
                        post(self._item_state, rest_key, "cancelled", "", "")
                    counts["cancelled"] += len(jobs) - number
                    break
                post(self._item_state, key, "running", "", "")
                post(self._progress, number, len(jobs), Path(source).name)
                try:
                    result = runner.process(source, target, plan, cancel=cancel, progress=lambda text, key=key: post(self._item_message, key, text))
                except runner.Cancelled:
                    post(self._item_state, key, "cancelled", "", "")
                    counts["cancelled"] += len(jobs) - number
                    for rest_key, _s, _t in jobs[number + 1:]:
                        post(self._item_state, rest_key, "cancelled", "", "")
                    break
                except PasswordRequired:
                    post(self._item_state, key, "skipped", "Kennwortgeschützt – bitte zuerst im Reader öffnen und entsperren.", "")
                    counts["skipped"] += 1
                except (EditorError, OSError) as exc:
                    post(self._item_state, key, "error", _message(exc), "")
                    counts["error"] += 1
                except Exception:  # noqa: BLE001 - eine Datei darf den Durchlauf nicht beenden
                    post(self._item_state, key, "error", "Unerwarteter Fehler beim Bearbeiten dieser Datei.", "")
                    counts["error"] += 1
                else:
                    notes = ", ".join(result.notes)
                    text = f"{_size(result.before)} → {_size(result.after)}" + (f" · {notes}" if notes else "")
                    post(self._item_state, key, "done", text, str(result.target))
                    counts["done"] += 1
            return counts

        def failed(exc: BaseException, details: str) -> None:
            self.running = False
            self.app.report_exception(details)
            self._refresh()

        self.app.worker.run(work, self._finished, failed)

    @Slot()
    def cancel(self) -> None:
        if self._cancel is not None and self.running:
            self._cancel.set()
            self.currentText = "Wird abgebrochen …"

    def _progress(self, number: int, total: int, name: str) -> None:
        self.progressText = f"{number + 1 if number < total else total} / {total} {'Datei' if total == 1 else 'Dateien'}"
        self.progressValue = number / total if total else 0.0
        self.currentText = name

    def _item_state(self, key: str, state: str, message: str, output: str) -> None:
        item = next((item for item in self._items if item["key"] == key), None)
        if item is None:
            return
        item.update(state=state, message=message, output=output)
        self._publish()

    def _item_message(self, key: str, text: str) -> None:
        item = next((item for item in self._items if item["key"] == key), None)
        if item is not None and item["state"] == "running":
            item["message"] = text
            self._publish()

    def _finished(self, counts: dict) -> None:
        self.running = False
        self._cancel = None
        self.progressValue = 1.0
        parts = [f"{counts['done']} von {len(self._items)} {'PDF' if len(self._items) == 1 else 'PDFs'} bearbeitet"]
        if counts["error"]:
            parts.append(f"{counts['error']} mit Fehler")
        if counts["skipped"]:
            parts.append(f"{counts['skipped']} ausgelassen")
        if counts["cancelled"]:
            parts.append(f"{counts['cancelled']} abgebrochen")
        self.resultText = ", ".join(parts) + "."
        self.resultTone = "success" if counts["done"] == len(self._items) else ("critical" if not counts["done"] else "warning")
        self.app.set_status("Stapel-Aktionen: " + self.resultText, "success" if self.resultTone == "success" else "warning")
        self._refresh()

    def close(self) -> None:
        if self._cancel is not None:
            self._cancel.set()

    # Darstellung ----------------------------------------------------------------------------------------------
    def _refresh(self) -> None:
        chosen = set(self._plan.steps)
        self.steps = [{"key": key, "label": actions.LABELS[key], "description": actions.DESCRIPTIONS[key], "checked": key in chosen} for key in actions.ORDER]
        fixed = [{"key": key, "label": actions.LABELS[key], "description": actions.DESCRIPTIONS[key]} for key in actions.ORDER]
        if fixed != self.stepList:
            self.stepList = fixed
        self.chosen = [key for key in actions.ORDER if key in chosen]
        self.summary = self._plan.summary()
        self._plan.password = self._password
        problem = actions.problem(self._plan)
        if not problem and not _valid_suffix(self.suffix) and self.outMode == OUT_ORIGINAL:
            problem = "Neben den Originalen braucht der Name einen Zusatz (z. B. »_bearbeitet«)."
        elif not problem and not _valid_suffix(self.suffix, allow_empty=True):
            problem = "Der Zusatz enthält Zeichen, die in Dateinamen nicht erlaubt sind."
        if not problem and self.outMode == OUT_FOLDER and not (self.outPath and Path(self.outPath).is_dir()):
            problem = "Bitte einen vorhandenen Ausgabeordner wählen."
        self.problem = problem
        self.canStart = bool(self._items) and not problem and not self.running
        self._publish()

    def _publish(self) -> None:
        self.count = len(self._items)
        self.files = [
            {
                "key": item["key"], "name": item["name"], "folder": item["folder"], "sizeText": _size(item["size"]), "state": item["state"],
                "stateText": STATE_TEXT[item["state"]], "tone": STATE_TONE[item["state"]], "message": item["message"], "hasOutput": bool(item["output"]),
                "outputName": Path(item["output"]).name if item["output"] else "",
            }
            for item in self._items
        ]

    @Slot(result=list)
    def numberFormats(self) -> list:  # noqa: N802
        return [{"key": key, "label": text.replace("{seite}", "3").replace("{seiten}", "12")} for key, text in actions.NUMBER_FORMATS.items()]

    def _texts(self) -> dict:
        return {"outOriginal": OUT_ORIGINAL, "outFolder": OUT_FOLDER, "defaultSuffix": actions.DEFAULT_SUFFIX, "pdfa": actions.PDFA, "protect": actions.PROTECT, "watermark": actions.WATERMARK, "numbers": actions.NUMBERS, "optimize": actions.OPTIMIZE}

    _constant = Signal()
    texts = Property(dict, _texts, notify=_constant)


def _is_pdf(path: str) -> bool:
    return str(path).lower().endswith(".pdf") and Path(path).is_file()


def _valid_suffix(text: str, allow_empty: bool = False) -> bool:
    if not text.strip():
        return allow_empty
    return not any(char in text for char in '<>:"/\\|?*') and len(text) <= 40


def _free_name(folder: Path, stem: str, reserved: set[str]) -> Path:
    """Freier Dateiname im Ordner – vorhandene Dateien werden nie überschrieben."""
    candidate = folder / f"{stem}.pdf"
    number = 2
    while candidate.exists() or str(candidate).lower() in reserved:
        candidate = folder / f"{stem} ({number}).pdf"
        number += 1
    return candidate


def _message(exc: BaseException) -> str:
    if isinstance(exc, EditorError):
        return str(exc)
    if isinstance(exc, PermissionError):
        return "Keine Berechtigung zum Speichern im Zielordner."
    return "Die Datei ließ sich nicht lesen oder speichern."


class ActionsTool:
    """Verbindet den Controller mit dem AppController (Tastenkürzel, Drag & Drop, Hilfe, Speichern)."""

    key = ACTIONS.key

    def __init__(self, app, cfg: dict) -> None:
        self.app = app
        self.controller = ActionsController(app, cfg, app)
        app.register_tool(self.key, self)

    def primary_action(self, page: str) -> None:
        self.controller.start()

    def open_action(self, page: str) -> None:
        self.controller.pick()

    def find_action(self, page: str) -> None:
        pass

    def show_help(self, page: str) -> None:
        self.app.show_steps("Kurzanleitung – Stapel-Aktionen", HELP_STEPS, HELP_NOTES)

    def hint(self, page: str) -> str:
        return HINT

    def accepts(self, dropped: list[str], page: str) -> bool:
        return self.controller.accepts(dropped)

    def drag_enter(self, accepted: bool, page: str) -> None:
        self.controller.dropHighlight = accepted

    def drag_leave(self) -> None:
        self.controller.dropHighlight = False

    def drop(self, dropped: list[str], page: str) -> None:
        self.controller.add(dropped)

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

    def running_work(self) -> str:
        return "Stapel-Aktionen" if self.controller.running else ""

    def close(self) -> None:
        self.controller.close()
