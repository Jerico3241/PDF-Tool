"""Werkzeug »Umwandeln« (in QML: ``Convert``, seit 5.0 Beta 7) – viele Dateien jeder Art auf einmal.

Ablauf: Dateien wählen oder hineinziehen (PDF, Text, Tabelle, Präsentation, Bild – gemischt) → Aufgabe wählen:

* **Umwandeln** in ein Format (PDF, Word, Excel, PowerPoint, OpenDocument, Webseite, Text, Bilder …) – Dateien, die
  sich nicht in das Ziel umwandeln lassen, werden mit Grund ausgelassen.
* **Zusammenfügen** zu einer PDF in der Reihenfolge der Liste (↑/↓), je Datei ein Lesezeichen.
* **Teilen** jeder Datei in PDFs: jede Seite, alle n Seiten oder nach Bereichen.
* **Drucken** aller Dateien mit einem Druckdialog für alle.
* **Umbenennen** nach einem Muster mit Vorschau und »Rückgängig«.

Gearbeitet wird nacheinander im Hintergrund (``tools.convert``); Originale werden nur gelesen (außer beim Umbenennen),
vorhandene Dateien nie überschrieben.
"""

from __future__ import annotations

import threading
from pathlib import Path

from PySide6.QtCore import Property, QObject, Signal, Slot

from tools.convert import formats, jobs, naming
from tools.pdf_editor import office
from tools.pdf_editor.errors import EditorError
from tools.registry import CONVERT

from . import files
from .base import Observable, prop

CONFIG_KEY = "umwandeln"
INFO_AREA = "convert_info"
MAX_FILES = 500
MODES = ("convert", "merge", "split", "print", "rename")
MODE_LABELS = {"convert": "Umwandeln", "merge": "Zusammenfügen", "split": "Teilen", "print": "Drucken", "rename": "Umbenennen"}
OUT_ORIGINAL = "original"
OUT_FOLDER = "folder"
SPLIT_MODES = (jobs.SPLIT_PAGES, jobs.SPLIT_EVERY, jobs.SPLIT_RANGES)
HINT = "Strg+O  Dateien wählen   ·   Strg+Enter  Starten   ·   Dateien auch hineinziehen"
HELP_STEPS = (
    "Dateien wählen (Strg+O) oder in das Fenster ziehen – PDFs, Texte, Tabellen, Präsentationen und Bilder, auch gemischt.",
    "Oben die Aufgabe wählen: Umwandeln, Zusammenfügen, Teilen, Drucken oder Umbenennen.",
    "Ziel bzw. Einstellungen der Aufgabe wählen und den Ausgabeordner festlegen.",
    "»Starten« (Strg+Enter). Jede Datei wird für sich bearbeitet; »Abbrechen« hält nach der laufenden Datei an.",
)
HELP_NOTES = (
    "Die Originale bleiben unverändert, vorhandene Dateien werden nie überschrieben – neue Dateien heißen dann »Name (2)«.",
    "Umbenennen ändert die Namen der Originale. »Rückgängig« stellt die alten Namen wieder her.",
    "HEIC-Fotos (iPhone), WEBP und AVIF lassen sich in JPEG, PNG oder PDF umwandeln.",
)
STATE_TEXT = {"waiting": "Bereit", "running": "In Arbeit …", "done": "Fertig", "error": "Fehler", "skipped": "Ausgelassen", "cancelled": "Nicht bearbeitet"}
STATE_TONE = {"waiting": "neutral", "running": "accent", "done": "success", "error": "critical", "skipped": "warning", "cancelled": "neutral"}


def _size(value: int) -> str:
    if value < 1024 * 1024:
        return f"{max(1, round(value / 1024))} KB"
    return f"{value / (1024 * 1024):.1f} MB".replace(".", ",")


def _message(exc: BaseException) -> str:
    if isinstance(exc, EditorError) and str(exc):
        return str(exc)
    if isinstance(exc, PermissionError):
        return "Keine Berechtigung – die Datei ist geöffnet oder der Ordner schreibgeschützt."
    if isinstance(exc, OSError):
        return f"Die Datei ließ sich nicht lesen oder speichern ({exc.strerror or type(exc).__name__})."
    return "Unerwarteter Fehler bei dieser Datei."


class ConvertController(Observable):
    filesChanged, files = prop(list, "files", [])
    countChanged, count = prop(int, "count", 0)
    modeChanged, mode = prop(str, "mode", "convert")
    targetChanged, target = prop(str, "target", "pdf")
    targetsChanged, targets = prop(list, "targets", [])  # [{key, label, count}] – count: Dateien, die dorthin können
    splitModeChanged, splitMode = prop(str, "splitMode", jobs.SPLIT_PAGES)
    splitValueChanged, splitValue = prop(str, "splitValue", "2")
    mergeNameChanged, mergeName = prop(str, "mergeName", "Zusammengefügt")
    patternChanged, pattern = prop(str, "pattern", naming.DEFAULT_PATTERN)
    startNumberChanged, startNumber = prop(int, "startNumber", 1)
    outModeChanged, outMode = prop(str, "outMode", OUT_ORIGINAL)
    outPathChanged, outPath = prop(str, "outPath", "")
    problemChanged, problem = prop(str, "problem", "")
    canStartChanged, canStart = prop(bool, "canStart", False)
    startTextChanged, startText = prop(str, "startText", "Umwandeln")
    runningChanged, running = prop(bool, "running", False)
    progressTextChanged, progressText = prop(str, "progressText", "")
    progressValueChanged, progressValue = prop(float, "progressValue", 0.0)
    currentTextChanged, currentText = prop(str, "currentText", "")
    resultTextChanged, resultText = prop(str, "resultText", "")
    resultToneChanged, resultTone = prop(str, "resultTone", "neutral")
    resultPathChanged, resultPath = prop(str, "resultPath", "")  # Zusammenfügen: die neue PDF
    canUndoChanged, canUndo = prop(bool, "canUndo", False)
    dropHighlightChanged, dropHighlight = prop(bool, "dropHighlight", False)

    def __init__(self, app, cfg: dict, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.app = app
        stored = cfg.get(CONFIG_KEY) if isinstance(cfg.get(CONFIG_KEY), dict) else {}
        self._items: list[dict] = []
        self._next_key = 0
        self._cancel: threading.Event | None = None
        self._last_folder = ""
        self._undo: list = []
        if stored.get("aufgabe") in MODES:
            self.set_quietly("mode", stored["aufgabe"])
        if stored.get("ziel") in formats.TARGETS:
            self.set_quietly("target", stored["ziel"])
        if stored.get("teilen") in SPLIT_MODES:
            self.set_quietly("splitMode", stored["teilen"])
        if isinstance(stored.get("teilen_wert"), str):
            self.set_quietly("splitValue", stored["teilen_wert"][:60])
        if isinstance(stored.get("muster"), str) and stored["muster"].strip():
            self.set_quietly("pattern", stored["muster"][:120])
        self.set_quietly("outMode", OUT_FOLDER if stored.get("ausgabe") == OUT_FOLDER else OUT_ORIGINAL)
        self.set_quietly("outPath", str(stored.get("ordner") or ""))
        self._refresh()

    def config(self) -> dict:
        return {CONFIG_KEY: {"aufgabe": self.mode, "ziel": self.target, "teilen": self.splitMode, "teilen_wert": self.splitValue,
                             "muster": self.pattern, "ausgabe": self.outMode, "ordner": self.outPath}}

    def _changed(self) -> None:
        self._refresh()
        self.app.schedule_save()

    # Einstellungen ------------------------------------------------------------------------------------------
    @Slot(str)
    def setMode(self, mode: str) -> None:  # noqa: N802
        if mode in MODES and not self.running and mode != self.mode:
            self.mode = mode
            self.resultText = ""
            self.canUndo = False
            for item in self._items:
                item.update(state="waiting", message="", outputs=[])
            self._changed()

    @Slot(str)
    def setTarget(self, key: str) -> None:  # noqa: N802
        if key in formats.TARGETS and not self.running:
            self.target = key
            self._changed()

    @Slot(str)
    def setSplitMode(self, key: str) -> None:  # noqa: N802
        if key in SPLIT_MODES and not self.running:
            self.splitMode = key
            if key == jobs.SPLIT_RANGES and not any(char in self.splitValue for char in "-,"):
                self.splitValue = "1-2, 3-"
            elif key == jobs.SPLIT_EVERY and not self.splitValue.strip().isdigit():
                self.splitValue = "2"
            self._changed()

    @Slot(str)
    def setSplitValue(self, text: str) -> None:  # noqa: N802
        self.splitValue = str(text)[:60]
        self._changed()

    @Slot(str)
    def setMergeName(self, text: str) -> None:  # noqa: N802
        self.mergeName = str(text)[:120]
        self._refresh()

    @Slot(str)
    def setPattern(self, text: str) -> None:  # noqa: N802
        self.pattern = str(text)[:120]
        self._changed()

    @Slot(int)
    def setStartNumber(self, value: int) -> None:  # noqa: N802
        self.startNumber = max(0, min(999999, int(value)))
        self._refresh()

    @Slot(str)
    def setOutMode(self, mode: str) -> None:  # noqa: N802
        if mode in (OUT_ORIGINAL, OUT_FOLDER) and not self.running:
            self.outMode = mode
            if mode == OUT_FOLDER and not self.outPath:
                self.pickOutDir()
            self._changed()

    @Slot()
    def pickOutDir(self) -> None:  # noqa: N802
        folder = files.pick_folder("Ordner für die neuen Dateien", self.app.initial_dir("umwandeln_ziel", self.outPath or self._last_folder))
        if folder:
            self.outPath = folder
            self.outMode = OUT_FOLDER
            self._changed()

    # Dateien ------------------------------------------------------------------------------------------------
    @Slot()
    def pick(self) -> None:
        paths = files.open_files("Dateien zum Umwandeln wählen", self.app.initial_dir("umwandeln", self._last_folder), formats.dialog_filter())
        if paths:
            self.add(paths)

    def accepts(self, paths: list[str]) -> bool:
        return any(formats.supported(path) for path in paths)

    def add(self, paths: list[str]) -> None:
        if self.running:
            return
        known = {item["path"].lower() for item in self._items}
        added = 0
        rejected = 0
        for path in paths:
            if str(path).lower() in known:
                continue
            if not formats.supported(path) or not Path(path).is_file():
                rejected += 1
                continue
            if len(self._items) >= MAX_FILES:
                break
            p = Path(path)
            try:
                size = p.stat().st_size
            except OSError:
                continue
            self._next_key += 1
            self._items.append({"key": f"{self._next_key}:{p.name}", "path": str(p), "name": p.name, "folder": str(p.parent), "size": size,
                                "kind": formats.kind_of(p), "state": "waiting", "message": "", "outputs": []})
            known.add(str(path).lower())
            added += 1
        if added:
            self._last_folder = str(Path(paths[0]).parent)
            self.app.remember_dir("umwandeln", paths[0])
            self.resultText = ""
            self.canUndo = False
        if rejected and not added:
            self.app.notify(INFO_AREA, "warning", "Diese Dateiart kann Novadesk nicht umwandeln.", title="Nicht hinzugefügt", auto_hide=8000)
        elif len(self._items) >= MAX_FILES and added < len(paths) - rejected:
            self.app.notify(INFO_AREA, "warning", f"Höchstens {MAX_FILES} Dateien auf einmal.", title="Nicht alle hinzugefügt", auto_hide=8000)
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
            self.canUndo = False
            self._refresh()

    @Slot(str, int)
    def move(self, key: str, delta: int) -> None:
        """Reihenfolge ändern (wichtig für »Zusammenfügen«): ``delta`` −1 nach oben, +1 nach unten."""
        index = next((i for i, item in enumerate(self._items) if item["key"] == key), -1)
        other = index + (1 if delta > 0 else -1)
        if self.running or index < 0 or not 0 <= other < len(self._items):
            return
        self._items[index], self._items[other] = self._items[other], self._items[index]
        self._refresh()

    @Slot(str)
    def openOutput(self, key: str) -> None:  # noqa: N802
        item = next((item for item in self._items if item["key"] == key and item["outputs"]), None)
        if item is None:
            return
        output = item["outputs"][0]
        reader = getattr(self.app, "reader_controller", None)
        if reader is not None and (formats.kind_of(output) in (formats.PDF, formats.TEXT, formats.SHEET, formats.SLIDES) and Path(output).suffix.lower() not in (".html", ".txt", ".rtf")):
            reader.open_paths([output])
        else:
            self._open(output)

    @Slot(str)
    def openFolder(self, key: str) -> None:  # noqa: N802
        item = next((item for item in self._items if item["key"] == key), None)
        if item is not None:
            self._open(str(Path(item["outputs"][0]).parent) if item["outputs"] else item["folder"])

    @Slot()
    def openResult(self) -> None:  # noqa: N802
        if self.resultPath:
            reader = getattr(self.app, "reader_controller", None)
            if reader is not None:
                reader.open_paths([self.resultPath])
            else:
                self._open(self.resultPath)

    @Slot()
    def openOutputFolder(self) -> None:  # noqa: N802
        if self.resultPath:
            self._open(str(Path(self.resultPath).parent))
            return
        done = [item for item in self._items if item["outputs"]]
        if done:
            self._open(str(Path(done[0]["outputs"][0]).parent))

    def _open(self, path: str) -> None:
        try:
            files.open_path(path)
        except OSError:
            self.app.notify(INFO_AREA, "warning", "Der Ordner bzw. die Datei lässt sich nicht öffnen.", title="Nicht geöffnet", auto_hide=8000)

    # Starten ------------------------------------------------------------------------------------------------
    def _folder(self, item: dict) -> Path:
        return Path(self.outPath) if self.outMode == OUT_FOLDER else Path(item["folder"])

    @Slot()
    def start(self) -> None:
        if not self.canStart:
            if self.problem:
                self.app.notify(INFO_AREA, "warning", self.problem, title="Noch nicht bereit", auto_hide=8000)
            return
        if self.mode == "print":
            self._print()
            return
        if self.mode == "rename":
            self._rename()
            return
        self.resultText = ""
        self.resultPath = ""
        self.canUndo = False
        self.app.hide_notice(INFO_AREA)
        if self.mode == "merge":
            self._merge()
            return
        for item in self._items:
            item.update(state="waiting", message="", outputs=[])
        work = [(item["key"], item["path"], str(self._folder(item))) for item in self._items]
        mode, target, split_mode, split_value = self.mode, self.target, self.splitMode, self.splitValue
        self._begin(len(work))
        cancel = self._cancel
        post = self.app.worker.post

        def run() -> dict:
            counts = {"done": 0, "error": 0, "skipped": 0, "cancelled": 0, "files": 0}
            taken: set[str] = set()
            for number, (key, source, folder) in enumerate(work):
                if cancel.is_set():
                    for rest, _s, _f in work[number:]:
                        post(self._item_state, rest, "cancelled", "", [])
                    counts["cancelled"] += len(work) - number
                    break
                if mode == "convert" and not formats.can_convert(source, target):
                    post(self._item_state, key, "skipped", formats.why_not(source, target), [])
                    counts["skipped"] += 1
                    continue
                post(self._item_state, key, "running", "", [])
                post(self._progress, number, len(work), Path(source).name)
                progress = lambda text, key=key: post(self._item_message, key, text)  # noqa: E731
                try:
                    if mode == "convert":
                        result = jobs.convert_file(source, target, folder, taken=taken, cancel=cancel, progress=progress)
                    else:
                        result = jobs.split(source, folder, split_mode, split_value, taken=taken, cancel=cancel, progress=progress)
                except jobs.Cancelled:
                    post(self._item_state, key, "cancelled", "", [])
                    for rest, _s, _f in work[number + 1:]:
                        post(self._item_state, rest, "cancelled", "", [])
                    counts["cancelled"] += len(work) - number
                    break
                except (EditorError, OSError) as exc:
                    post(self._item_state, key, "error", _message(exc), [])
                    counts["error"] += 1
                except Exception:  # noqa: BLE001 - eine Datei darf den Durchlauf nicht beenden
                    post(self._item_state, key, "error", "Unerwarteter Fehler bei dieser Datei.", [])
                    counts["error"] += 1
                else:
                    outputs = [str(path) for path in result.outputs]
                    text = ("→ " + Path(outputs[0]).name) if len(outputs) == 1 else f"{len(outputs)} Dateien"
                    if result.notes:
                        text += " · " + ", ".join(result.notes)
                    post(self._item_state, key, "done", text, outputs)
                    counts["done"] += 1
                    counts["files"] += len(outputs)
            return counts

        self.app.worker.run(run, self._finished, self._failed)

    def _begin(self, total: int) -> None:
        self._cancel = threading.Event()
        self.running = True
        self._progress(0, total, "")
        self._refresh()

    def _failed(self, exc: BaseException, details: str) -> None:
        self.running = False
        self._cancel = None
        self.app.report_exception(details)
        self._refresh()

    def _merge(self) -> None:
        name = jobs.safe_stem(self.mergeName.strip() or "Zusammengefügt")
        folder = self._folder(self._items[0])
        target = jobs.unique_path(folder, name + ".pdf")
        paths = [item["path"] for item in self._items]
        for item in self._items:
            item.update(state="running", message="", outputs=[])
        self._begin(len(paths))
        cancel = self._cancel
        post = self.app.worker.post

        def progress(text: str) -> None:
            post(self._merge_progress, text, len(paths))

        def run():
            try:
                return jobs.merge(paths, target, cancel=cancel, progress=progress)
            except jobs.Cancelled:
                return None

        def done(result) -> None:
            self.running = False
            self._cancel = None
            self.progressValue = 1.0
            if result is None:
                for item in self._items:
                    item.update(state="cancelled", message="")
                self.resultText, self.resultTone = "Abgebrochen – es wurde keine Datei erstellt.", "warning"
            else:
                skipped = {name: reason for name, reason in result.skipped}
                for item in self._items:
                    reason = skipped.get(item["path"])
                    item.update(state="skipped" if reason else "done", message=reason or "", outputs=[] if reason else [str(result.target)])
                self.resultPath = str(result.target)
                pages = "1 Seite" if result.pages == 1 else f"{result.pages} Seiten"
                self.resultText = f"{result.parts} Dateien zu »{result.target.name}« zusammengefügt ({pages})."
                if result.skipped:
                    self.resultText += f" {len(result.skipped)} ausgelassen."
                self.resultTone = "warning" if result.skipped else "success"
                self.app.set_status("Umwandeln: " + self.resultText, self.resultTone)
            self._refresh()

        def failed(exc: BaseException, details: str) -> None:
            if isinstance(exc, (EditorError, OSError)):
                self.running = False
                self._cancel = None
                for item in self._items:
                    item.update(state="waiting", message="")
                self.resultText, self.resultTone = _message(exc), "critical"
                self._refresh()
            else:
                self._failed(exc, details)

        self.app.worker.run(run, done, failed)

    def _merge_progress(self, text: str, total: int) -> None:
        done = sum(1 for item in self._items if item["state"] == "done")
        self.currentText = text
        self.progressText = "Wird zusammengefügt …"
        self.progressValue = min(0.95, done / total if total else 0.0)

    def _rename(self) -> None:
        renames = naming.plan([item["path"] for item in self._items], self.pattern, self.startNumber)
        bad = next((item for item in renames if item.error), None)
        if bad is not None:  # inzwischen belegt (die Prüfung lief beim Ändern des Musters)
            self.resultText, self.resultTone = f"Nichts umbenannt – {bad.source.name}: {bad.error}", "critical"
            self._refresh()
            return
        try:
            pairs = naming.apply(renames)
        except (OSError, ValueError) as exc:
            self.resultText, self.resultTone = f"Nichts umbenannt: {_message(exc) if isinstance(exc, OSError) else exc}", "critical"
            self._refresh()
            return
        moved = {str(original): str(current) for current, original in pairs}
        for item in self._items:
            new = moved.get(item["path"])
            if new:
                item.update(path=new, name=Path(new).name, state="done", message="", outputs=[new])
            else:
                item.update(state="skipped", message="Name bleibt gleich", outputs=[])
        self._undo = pairs
        self.canUndo = bool(pairs)
        count = len(pairs)
        self.resultText = f"{count} {'Datei' if count == 1 else 'Dateien'} umbenannt." if count else "Alle Namen bleiben gleich."
        self.resultTone = "success" if count else "neutral"
        self.app.set_status("Umwandeln: " + self.resultText, "success")
        self._refresh()

    @Slot()
    def undoRename(self) -> None:  # noqa: N802
        if not self._undo or self.running:
            return
        back = naming.undo(self._undo)
        restored = {str(current): str(original) for current, original in self._undo}
        for item in self._items:
            old = restored.get(item["path"])
            if old and Path(old).exists():
                item.update(path=old, name=Path(old).name, state="waiting", message="", outputs=[])
        self._undo = []
        self.canUndo = False
        self.resultText = f"{back} {'Name' if back == 1 else 'Namen'} wiederhergestellt."
        self.resultTone = "success"
        self._refresh()

    def _print(self) -> None:
        from . import convertprint

        convertprint.print_files(self, [item["path"] for item in self._items])

    @Slot()
    def cancel(self) -> None:
        if self._cancel is not None and self.running:
            self._cancel.set()
            self.currentText = "Wird abgebrochen …"

    def _progress(self, number: int, total: int, name: str) -> None:
        self.progressText = f"{number + 1 if number < total else total} / {total} {'Datei' if total == 1 else 'Dateien'}"
        self.progressValue = number / total if total else 0.0
        self.currentText = name

    def _item_state(self, key: str, state: str, message: str, outputs: list) -> None:
        item = next((item for item in self._items if item["key"] == key), None)
        if item is not None:
            item.update(state=state, message=message, outputs=list(outputs))
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
        total = len(self._items)
        verb = "umgewandelt" if self.mode == "convert" else "geteilt"
        parts = [f"{counts['done']} von {total} {'Datei' if total == 1 else 'Dateien'} {verb}"]
        if counts["files"] and counts["files"] != counts["done"]:
            parts[0] += f" ({counts['files']} neue Dateien)"
        if counts["error"]:
            parts.append(f"{counts['error']} mit Fehler")
        if counts["skipped"]:
            parts.append(f"{counts['skipped']} ausgelassen")
        if counts["cancelled"]:
            parts.append(f"{counts['cancelled']} abgebrochen")
        self.resultText = ", ".join(parts) + "."
        self.resultTone = "success" if counts["done"] == total else ("critical" if not counts["done"] else "warning")
        self.app.set_status("Umwandeln: " + self.resultText, "success" if self.resultTone == "success" else "warning")
        self._refresh()

    def print_finished(self, printed: int, failed: list[tuple[str, str]], cancelled: bool) -> None:
        """Vom Druck (``convertprint``): Ergebnis je Datei und gesamt."""
        reasons = dict(failed)
        for item in self._items:
            if item["path"] in reasons:
                item.update(state="error", message=reasons[item["path"]])
        self.running = False
        self._cancel = None
        if cancelled:
            self.resultText, self.resultTone = f"Abgebrochen – {printed} {'Datei' if printed == 1 else 'Dateien'} gedruckt.", "warning"
        else:
            self.resultText = f"{printed} {'Datei' if printed == 1 else 'Dateien'} an den Drucker gesendet."
            if failed:
                self.resultText += f" {len(failed)} nicht gedruckt."
            self.resultTone = "warning" if failed else "success"
        self.app.set_status("Umwandeln: " + self.resultText, "success" if self.resultTone == "success" else "warning")
        self._refresh()

    def close(self) -> None:
        if self._cancel is not None:
            self._cancel.set()

    # Darstellung --------------------------------------------------------------------------------------------
    def _refresh(self) -> None:
        counts = {key: 0 for key in formats.ORDER}
        for item in self._items:
            for key in formats.targets_for(item["kind"]):
                if formats.can_convert(item["path"], key):
                    counts[key] += 1
        shown = [key for key in formats.ORDER if counts[key] or not self._items]
        targets = [{"key": key, "label": formats.TARGETS[key].label, "count": counts[key]} for key in formats.ORDER if key in shown]
        if targets != self.targets:
            self.targets = targets
        self.problem = self._problem(counts)
        self.startText = {"convert": "Alle umwandeln" if len(self._items) > 1 else "Umwandeln", "merge": "Zusammenfügen",
                          "split": "Alle teilen" if len(self._items) > 1 else "Teilen", "print": "Alle drucken" if len(self._items) > 1 else "Drucken",
                          "rename": "Umbenennen"}[self.mode]
        self.canStart = bool(self._items) and not self.problem and not self.running
        self._publish()

    def _problem(self, counts: dict) -> str:
        if not self._items:
            return ""
        if self.mode == "convert":
            if not counts.get(self.target):
                return f"Keine der Dateien lässt sich in {formats.TARGETS[self.target].label} umwandeln – bitte ein anderes Ziel wählen."
            needs_office = any(item["kind"] in (formats.TEXT, formats.SHEET, formats.SLIDES) for item in self._items) or self.target == "pptx"
            if needs_office and office.libreoffice() is None:
                return "Für Office-Dateien fehlt LibreOffice. Bitte Novadesk neu installieren."
        if self.mode == "merge" and len(self._items) < 2:
            return "Zum Zusammenfügen bitte mindestens zwei Dateien wählen."
        if self.mode == "merge":
            from tools.pdf_repair.batch import name_error

            error = name_error(self.mergeName.strip())
            if error:
                return error
        if self.mode == "split":
            try:
                jobs.split_ranges(self.splitMode, self.splitValue, 10_000)
            except ValueError as exc:
                return str(exc)
        if self.mode == "rename":
            renames = naming.plan([item["path"] for item in self._items], self.pattern, self.startNumber)
            bad = next((item for item in renames if item.error), None)
            if bad is not None:
                return f"{bad.source.name}: {bad.error}"
            if not any(item.changes for item in renames):
                return "Mit diesem Muster bleiben alle Namen gleich."
        if self.mode in ("convert", "merge", "split") and self.outMode == OUT_FOLDER and not (self.outPath and Path(self.outPath).is_dir()):
            return "Bitte einen vorhandenen Ausgabeordner wählen."
        return ""

    def _publish(self) -> None:
        self.count = len(self._items)
        previews: dict[str, str] = {}
        if self.mode == "rename" and self._items and not self.running:
            for rename in naming.plan([item["path"] for item in self._items], self.pattern, self.startNumber):
                previews[str(rename.source)] = rename.error or ("→ " + rename.target.name if rename.changes and rename.target else "bleibt gleich")
        rows = []
        for number, item in enumerate(self._items):
            message = item["message"]
            if not message and item["state"] == "waiting":
                if self.mode == "rename":
                    message = previews.get(item["path"], "")
                elif self.mode == "convert" and not formats.can_convert(item["path"], self.target):
                    message = formats.why_not(item["path"], self.target)
            rows.append({
                "key": item["key"], "name": item["name"], "folder": item["folder"], "sizeText": _size(item["size"]),
                "kind": formats.KIND_LABELS.get(item["kind"], ""), "symbol": office.symbol(item["path"]), "state": item["state"],
                "stateText": STATE_TEXT[item["state"]], "tone": STATE_TONE[item["state"]], "message": message,
                "hasOutput": bool(item["outputs"]), "first": number == 0, "last": number == len(self._items) - 1,
            })
        self.files = rows

    @Slot(result=list)
    def modes(self) -> list:
        return [{"key": key, "label": MODE_LABELS[key]} for key in MODES]

    def _texts(self) -> dict:
        return {"outOriginal": OUT_ORIGINAL, "outFolder": OUT_FOLDER, "splitPages": jobs.SPLIT_PAGES, "splitEvery": jobs.SPLIT_EVERY,
                "splitRanges": jobs.SPLIT_RANGES}

    _constant = Signal()
    texts = Property(dict, _texts, notify=_constant)


class ConvertTool:
    """Verbindet den Controller mit dem AppController (Tastenkürzel, Drag & Drop, Hilfe, Speichern)."""

    key = CONVERT.key

    def __init__(self, app, cfg: dict) -> None:
        self.app = app
        self.controller = ConvertController(app, cfg, app)
        app.register_tool(self.key, self)

    def primary_action(self, page: str) -> None:
        self.controller.start()

    def open_action(self, page: str) -> None:
        self.controller.pick()

    def find_action(self, page: str) -> None:
        pass

    def show_help(self, page: str) -> None:
        self.app.show_steps("Kurzanleitung – Umwandeln", HELP_STEPS, HELP_NOTES)

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
        return "Umwandeln" if self.controller.running else ""

    def close(self) -> None:
        self.controller.close()
