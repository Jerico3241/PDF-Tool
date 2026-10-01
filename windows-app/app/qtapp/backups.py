"""Einstellungen → »Sicherung & Wiederherstellung« (in QML: ``Backup``).

* Automatische Sicherung (Standard: an): 15 Sekunden nach dem Start im Hintergrund, höchstens
  einmal am Tag und nur, wenn sich die Daten geändert haben (``backup.policy``).
* »Jetzt sichern …«: Ordner wählen, Sicherung im Hintergrund erstellen und prüfen.
* »Wiederherstellen …«: Sicherung wählen → vollständig prüfen → Zusammenfassung mit Auswahl der
  Bereiche → Sicherung des aktuellen Stands → Wiederherstellung vorbereiten → Neustart.
  Eine Sicherung einer neueren PDF-Tool-Version wird nie eingespielt.
* Vor jedem Update: Sicherung des aktuellen Stands (``backup_before_update``).

Alles bleibt lokal. Während einer Sicherung oder Wiederherstellung startet kein Update.
"""

from __future__ import annotations

from functools import partial
from pathlib import Path
from typing import Callable

from PySide6.QtCore import Property, QObject, Signal, Slot

from appstate import VERSION
from backup import archive, policy, restore
from backup.archive import BackupError
from storage import data_root

from . import dialogs as dialog_service
from . import files
from .base import Observable, prop
from .models import KeyedListModel

AREA = "sicherung_info"
AUTO_DELAY = 15_000  # ms nach dem Start
FILTER = "Sicherung von PDF Tool (*.pdtbackup);;Alle Dateien (*.*)"
RECENT = 8


def size_text(size: int) -> str:
    if size >= 1024 * 1024:
        return f"{size / 1024 / 1024:.1f} MB".replace(".", ",")
    return f"{max(1, round(size / 1024))} KB"


class BackupController(Observable):
    automaticChanged, automatic = prop(bool, "automatic", True)
    folderTextChanged, folderText = prop(str, "folderText", "")
    lastAutoChanged, lastAuto = prop(str, "lastAuto", "Noch keine")
    lastManualChanged, lastManual = prop(str, "lastManual", "Noch keine")
    busyChanged, busy = prop(bool, "busy", False)
    busyTextChanged, busyText = prop(str, "busyText", "")
    progressChanged, progress = prop(float, "progress", 0.0)
    pendingChanged, pending = prop(str, "pending", "")  # vorbereitete Wiederherstellung (Text)

    def __init__(self, app, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.app = app
        self.root = data_root()
        self.state = policy.BackupState.load(self.root)
        self.model = KeyedListModel(("name", "kind", "date", "size", "version", "path"), key="path", parent=self)
        self._job = ""  # laufende Arbeit (Text für »Updates warten«)
        self.auto_runs = 0  # Tests, Diagnose
        self.restart = None  # Neustart der App (Tests: Attrappe)
        self._listing = False
        self.refresh(listing=False)  # die Liste der Sicherungen erst beim Öffnen der Einstellungen
        app.observe("currentPage", lambda page: self.refresh_list() if page == "settings" else None)
        outcome = restore.take_result(self.root)
        if outcome is not None:
            # Ergebnis der Wiederherstellung beim Start (nach dem ersten Bild anzeigen)
            self.app.timers.later("backup:result", 300, lambda: self._show_outcome(outcome))

    # Anzeige -----------------------------------------------------------------------------------------------
    def folder(self) -> Path:
        return policy.auto_folder(self.root, self.state)

    def refresh(self, listing: bool = True) -> None:
        self.automatic = self.state.automatic
        self.folderText = str(self.folder())
        self.lastAuto = archive.format_time(self.state.last_auto) or "Noch keine"
        if self.state.last_manual:
            name = Path(self.state.last_manual_file).name if self.state.last_manual_file else ""
            self.lastManual = archive.format_time(self.state.last_manual) + (f" · {name}" if name else "")
        else:
            self.lastManual = "Noch keine"
        plan = restore.pending(self.root)
        self.pending = f"Wiederherstellung aus „{plan.backup}“ ist vorbereitet und wird beim nächsten Start ausgeführt." if plan else ""
        if listing:
            self.refresh_list()

    def refresh_list(self) -> None:
        """Gesicherte Stände im Ordner der automatischen Sicherungen (Manifeste lesen: im Hintergrund)."""
        if self._listing:
            self.app.timers.later("backup:list", 200, self.refresh_list)
            return
        self._listing = True
        folder = self.folder()

        def done(entries) -> None:
            self._listing = False
            self.model.set_items(
                [
                    {
                        "path": str(entry.path),
                        "name": entry.path.name,
                        "kind": archive.KINDS.get(entry.kind, entry.kind),
                        "date": archive.format_time(entry.created_at),
                        "size": size_text(entry.size),
                        "version": entry.app_version,
                    }
                    for entry in entries
                ]
            )

        def failed(_exc, _text) -> None:
            self._listing = False

        self.app.worker.run(lambda: policy.list_backups(folder)[:RECENT], done, failed)

    def running_work(self) -> str:
        return self._job

    def _begin(self, job: str, text: str) -> bool:
        if self._job:
            self.app.notify(AREA, "info", f"Bitte warten – {self._job} läuft noch.", auto_hide=4000)
            return False
        self._job = job
        self.busyText = text
        self.progress = 0.0
        self.busy = True
        return True

    def _end(self) -> None:
        self._job = ""
        self.busy = False
        self.busyText = ""
        self.progress = 0.0

    def _progress(self, done: int, total: int, start: float = 0.0, span: float = 1.0) -> None:
        """Aus dem Hintergrund: Fortschritt im GUI-Thread anzeigen (höchstens jede 1 % neu).
        ``start``/``span``: Anteil am Balken bei Vorgängen aus mehreren Schritten."""
        value = start + span * (done / total if total else 0.0)
        if value - self.progress >= 0.01 or done == total:
            self.app.worker.post(lambda: setattr(self, "progress", value) if self.busy else None)

    def _step(self, text: str) -> None:
        """Aus dem Hintergrund: nächster Schritt eines laufenden Vorgangs."""
        self.app.worker.post(lambda: setattr(self, "busyText", text) if self.busy else None)

    # Automatisch ------------------------------------------------------------------------------------------------
    def start(self) -> None:
        self.app.timers.later("backup:auto", AUTO_DELAY, self.run_auto)

    def run_auto(self) -> None:
        """Automatische Sicherung, falls fällig (im Hintergrund, ohne Hinweis bei Erfolg)."""
        if not self.state.automatic or self._job or self.app.closing:
            return
        root, folder = self.root, self.folder()
        last = self.state

        def work():
            fingerprint = archive.fingerprint(root)
            if not policy.auto_due(last, fingerprint):
                return None
            result = archive.create_backup(root, folder, kind=archive.KIND_AUTO, app_version=VERSION)
            policy.prune(folder)
            return result, fingerprint

        def done(outcome) -> None:
            self._end()
            if outcome is None:
                return
            result, fingerprint = outcome
            self.auto_runs += 1
            self.state.note(archive.KIND_AUTO, result.path, result.created_at, fingerprint)
            self.state.save(self.root)
            self.refresh()
            self._log("info", "Automatische Sicherung erstellt: %s (%d Dateien)", result.path.name, result.files)

        def failed(exc, text) -> None:
            self._end()
            self._log("warning", "Automatische Sicherung fehlgeschlagen: %s", exc if isinstance(exc, BackupError) else text)
            self.app.notify(AREA, "warning", f"Die automatische Sicherung ist fehlgeschlagen: {exc}" if isinstance(exc, BackupError) else "Die automatische Sicherung ist fehlgeschlagen (Details in fehler.log).", status=False)

        if self._begin("automatische Sicherung", "Automatische Sicherung …"):
            self.app.worker.run(work, done, failed)

    @Slot(bool)
    def setAutomatic(self, value: bool) -> None:  # noqa: N802
        self.state.automatic = bool(value)
        self.state.save(self.root)
        self.automatic = self.state.automatic
        self.app.set_status("Automatische Sicherung " + ("eingeschaltet" if value else "ausgeschaltet"), "success")

    @Slot()
    def pickAutoFolder(self) -> None:  # noqa: N802
        folder = files.pick_folder("Ordner für automatische Sicherungen wählen", str(self.folder()))
        if not folder:
            return
        self.state.folder = folder
        self.state.save(self.root)
        self.refresh()
        self.app.notify(AREA, "success", f"Automatische Sicherungen werden ab jetzt in „{folder}“ abgelegt.", auto_hide=6000)

    @Slot()
    def resetAutoFolder(self) -> None:  # noqa: N802
        self.state.folder = ""
        self.state.save(self.root)
        self.refresh()

    @Slot()
    def openFolder(self) -> None:  # noqa: N802
        folder = self.folder()
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        self.app.open_file(folder, AREA)

    # Manuell ----------------------------------------------------------------------------------------------------
    @Slot()
    def backupNow(self) -> None:  # noqa: N802
        """Sicherung in einen gewählten Ordner (z. B. USB-Stick oder Netzlaufwerk)."""
        start = files.start_dir(self.state.manual_folder, str(Path.home() / "Documents"))
        folder = files.pick_folder("Ordner für die Sicherung wählen", start)
        if not folder:
            return
        self.create(folder, archive.KIND_MANUAL)

    def create(self, folder: str, kind: str, then: Callable[[object], None] | None = None) -> None:
        root = self.root

        def work():
            result = archive.create_backup(root, folder, kind=kind, app_version=VERSION, progress=self._progress)
            if kind != archive.KIND_MANUAL and Path(folder) == self.folder():
                policy.prune(folder)
            return result

        def done(result) -> None:
            self._end()
            self.state.note(kind, result.path, result.created_at)
            self.state.save(self.root)
            self.refresh()
            self._log("info", "Sicherung erstellt (%s): %s, %d Dateien, %s", kind, result.path.name, result.files, size_text(result.size))
            if then is not None:
                then(result)
                return
            self.app.notify(
                AREA,
                "success",
                f"Sicherung „{result.path.name}“ erstellt ({result.files} Dateien, {size_text(result.size)}) und geprüft.",
                actions=(("Ordner öffnen", lambda: self.app.open_folder_of(result.path, AREA)),),
                auto_hide=10000,
            )

        def failed(exc, text) -> None:
            self._end()
            message = str(exc) if isinstance(exc, BackupError) else "Die Sicherung konnte nicht erstellt werden (Details in fehler.log)."
            if not isinstance(exc, BackupError):
                self.app.write_error_log(text)
            self._log("error", "Sicherung fehlgeschlagen (%s): %s", kind, message)
            if then is not None:
                then(BackupError(message))
                return
            self.app.notify(AREA, "error", message, title="Sicherung fehlgeschlagen")

        if self._begin("Sicherung", "Sicherung wird erstellt …"):
            self.app.worker.run(work, done, failed)

    # Vor einem Update -------------------------------------------------------------------------------------------
    def backup_before_update(self, proceed: Callable[[], None]) -> bool:
        """Vor der Installation den aktuellen Stand sichern; danach ``proceed()``. Scheitert die
        Sicherung, entscheidet der Benutzer. ``False``: gerade läuft schon eine Sicherung."""
        if self._job:
            return False

        def then(result) -> None:
            if not isinstance(result, BackupError):
                proceed()
                return
            if self.app.dialogs.confirm("Sicherung vor dem Update fehlgeschlagen", f"{result} Soll das Update trotzdem installiert werden?", "Ohne Sicherung installieren", danger=True):
                self._log("warning", "Update ohne Sicherung bestätigt")
                proceed()

        self.create(str(self.folder()), archive.KIND_PRE_UPDATE, then)
        return True

    # Wiederherstellen -------------------------------------------------------------------------------------------
    @Slot()
    def restoreFrom(self) -> None:  # noqa: N802
        path = files.open_file("Sicherung zum Wiederherstellen wählen", str(self.folder()) if self.folder().is_dir() else files.start_dir(self.state.manual_folder), FILTER)
        if path:
            self.restore(path)

    @Slot(str)
    def restore(self, path: str) -> None:
        """Sicherung prüfen (im Hintergrund), dann Zusammenfassung und Auswahl zeigen."""

        def work():
            return archive.inspect_backup(path, app_version=VERSION, progress=self._progress)

        def done(info) -> None:
            self._end()
            self._confirm_restore(info)

        def failed(exc, text) -> None:
            self._end()
            if not isinstance(exc, BackupError):
                self.app.write_error_log(text)
            message = str(exc) if isinstance(exc, BackupError) else "Die Sicherung konnte nicht gelesen werden (Details in fehler.log)."
            self._log("warning", "Sicherung nicht verwendbar: %s – %s", Path(path).name, message)
            self.app.notify(AREA, "error", message, title="Wiederherstellung nicht möglich")

        if self._begin("Prüfung der Sicherung", "Sicherung wird geprüft …"):
            self.app.worker.run(work, done, failed)

    def _confirm_restore(self, info: archive.BackupInfo) -> None:
        areas = [
            {"key": area.key, "label": area.label, "summary": area.summary, "available": area.files > 0 or area.key != "einstellungen"}
            for area in info.areas
        ]
        data = {
            "name": info.path.name,
            "created": info.created_label,
            "version": info.app_version or "unbekannt",
            "kind": info.kind_label,
            "size": size_text(info.size),
            "areas": areas,
            "notes": list(info.notes),
        }
        answer, result = self.app.dialogs.ask(
            "restore_summary",
            "Sicherung wiederherstellen?",
            "Die gewählten Bereiche werden durch den Stand der Sicherung ersetzt. Vorher sichert PDF Tool den aktuellen Stand automatisch. Danach startet PDF Tool neu.",
            primary="Wiederherstellen",
            close="Abbrechen",
            danger=True,
            data=data,
            width=560,
        )
        if answer != dialog_service.PRIMARY:
            return
        chosen = [key for key in result.get("areas", [a["key"] for a in areas]) if key in archive.AREA]
        if not chosen:
            self.app.notify(AREA, "warning", "Bitte mindestens einen Bereich wählen.")
            return
        self._stage(info, chosen)

    def _stage(self, info: archive.BackupInfo, areas: list[str]) -> None:
        """Erst den aktuellen Stand sichern, dann die Wiederherstellung vorbereiten."""
        root, folder = self.root, self.folder()

        def work():
            # Ein Balken für beide Schritte: erst sichern (erste Hälfte), dann entpacken und prüfen
            pre = archive.create_backup(root, folder, kind=archive.KIND_PRE_RESTORE, app_version=VERSION, progress=partial(self._progress, start=0.0, span=0.5))
            policy.prune(folder)
            self._step("Wiederherstellung wird vorbereitet …")
            return restore.stage_restore(info.path, root, areas, pre_backup=pre.path.name, app_version=VERSION, progress=partial(self._progress, start=0.5, span=0.5))

        def done(plan: restore.RestorePlan) -> None:
            self._end()
            self.refresh()
            self._log("info", "Wiederherstellung vorbereitet aus %s (%s), Sicherung vorher: %s", plan.backup, ", ".join(plan.areas), plan.pre_backup)
            if self.app.dialogs.confirm(
                "Neu starten",
                f"Die Wiederherstellung ({restore.area_labels(plan.areas)}) ist vorbereitet. PDF Tool startet jetzt neu und spielt sie ein. Der bisherige Stand ist gesichert in „{plan.pre_backup}“.",
                "Jetzt neu starten",
                danger=False,
            ):
                self._restart()
            else:
                restore.discard_pending(self.root)
                self.refresh()
                self.app.notify(AREA, "info", "Wiederherstellung abgebrochen – es wurde nichts verändert.", auto_hide=6000)

        def failed(exc, text) -> None:
            self._end()
            if not isinstance(exc, BackupError):
                self.app.write_error_log(text)
            message = str(exc) if isinstance(exc, BackupError) else "Die Wiederherstellung konnte nicht vorbereitet werden (Details in fehler.log)."
            self._log("error", "Wiederherstellung nicht vorbereitet: %s", message)
            self.app.notify(AREA, "error", message + " Es wurde nichts verändert.", title="Wiederherstellung nicht möglich")

        if self._begin("Wiederherstellung", "Aktueller Stand wird gesichert …"):
            self.app.worker.run(work, done, failed)

    def _restart(self) -> None:
        if self.restart is not None:
            self.restart()
            return
        self.app.restart()

    @Slot()
    def discardPending(self) -> None:  # noqa: N802
        if restore.discard_pending(self.root):
            self.refresh()
            self.app.notify(AREA, "info", "Vorbereitete Wiederherstellung verworfen.", auto_hide=5000)

    def _show_outcome(self, outcome: restore.RestoreOutcome) -> None:
        if outcome.ok:
            text = outcome.message + (f" Der vorherige Stand liegt in „{outcome.pre_backup}“." if outcome.pre_backup else "")
            self.app.notify(AREA, "success", text, title="Wiederherstellung abgeschlossen")
            self.app.notify("home_info", "success", text, title="Wiederherstellung abgeschlossen", status=False, auto_hide=12000)
        else:
            self.app.notify(AREA, "error", outcome.message, title="Wiederherstellung nicht ausgeführt")
            self.app.notify("home_info", "error", outcome.message, title="Wiederherstellung nicht ausgeführt", status=False)

    @staticmethod
    def _log(level: str, message: str, *args) -> None:
        from diagnostics.applog import get

        getattr(get("sicherung"), level)(message, *args)

    def config(self) -> dict:
        return {}

    # Für QML ---------------------------------------------------------------------------------------------------
    _constant = Signal()

    def _list(self) -> QObject:
        return self.model

    recentModel = Property(QObject, _list, notify=_constant)
