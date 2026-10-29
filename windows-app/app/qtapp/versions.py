"""Backup-Center (in QML: ``Versions``, seit 5.0 Beta 7) – frühere Fassungen der Dokumente.

* ``before_save``: Text, Tabelle und Präsentation legen vor dem Überschreiben den bisherigen Stand als Fassung ab (PDFs
  tun das in ``reader.session`` beim sicheren Speichern).
* Automatische Sicherung: alle ``minutes`` Minuten schreibt jedes geöffnete Dokument mit ungespeicherten Änderungen eine
  Kopie seines Stands in die Ablage (``write_version`` der Dokument-Controller – das Dokument selbst bleibt ungespeichert).
* Seite »Backup-Center«: Dokumente mit ihren Fassungen, Öffnen (eine Kopie, das Original bleibt), Wiederherstellen als
  Kopie oder über das Original (mit Sicherung des jetzigen Stands), Löschen, Einstellungen.

Die Liste lesen und Dateien kopieren läuft im Hintergrund; QML sieht nur fertige Zeilen.
"""

from __future__ import annotations

import logging
import shutil
import tempfile
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QObject, QTimer, Slot

from backup import versions
from tools.registry import VERSIONS

from . import files
from .base import Observable, prop

CONFIG_KEY = "backup_center"
AREA = "versions_info"
SYNC_COPY_LIMIT = 32 * 1024 * 1024  # kleinere Dateien sofort kopieren (auch beim Beenden zuverlässig), größere im Hintergrund
HINT = "Fassungen öffnen, als Kopie wiederherstellen oder das Original ersetzen"


def _log() -> logging.Logger:
    return logging.getLogger("pdftool.versions")


def _size(value: int) -> str:
    if value < 1024 * 1024:
        return f"{max(1, round(value / 1024))} KB"
    if value < 1024 * 1024 * 1024:
        return f"{value / (1024 * 1024):.1f} MB".replace(".", ",")
    return f"{value / (1024 * 1024 * 1024):.1f} GB".replace(".", ",")


def before_save(app, target: str, current: str, proceed: Callable[[], None]) -> None:
    """Vor dem Speichern über eine vorhandene Datei: den bisherigen Stand als Fassung ablegen, dann ``proceed()``.
    Scheitert das Ablegen, wird trotzdem gespeichert (protokolliert) – Speichern darf daran nie hängen."""
    store = versions.store()
    path = Path(target)
    if not store.settings.enabled or not current or not path.is_file():
        proceed()
        return

    def remember() -> None:
        try:
            store.remember(path)
        except OSError as exc:
            _log().warning("Fassung vor dem Speichern nicht abgelegt (%s): %s", path.suffix, type(exc).__name__)

    try:
        small = path.stat().st_size <= SYNC_COPY_LIMIT
    except OSError:
        small = True
    if small:
        remember()
        proceed()
        return
    app.worker.run(remember, lambda _result: proceed(), lambda _exc, _details: proceed())


class VersionsController(Observable):
    documentsChanged, documents = prop(list, "documents", [])  # [{key, name, folder, count, sizeText, lastText, exists}]
    selectedChanged, selected = prop(str, "selected", "")
    versionListChanged, versionList = prop(list, "versionList", [])  # Fassungen des gewählten Dokuments
    loadingChanged, loading = prop(bool, "loading", False)
    totalTextChanged, totalText = prop(str, "totalText", "")
    enabledChanged, enabled = prop(bool, "enabled", True)
    minutesChanged, minutes = prop(int, "minutes", 10)
    keepChanged, keep = prop(int, "keep", 20)
    daysChanged, days = prop(int, "days", 30)
    lastAutoChanged, lastAuto = prop(str, "lastAuto", "")  # »Zuletzt automatisch gesichert: 13:05«
    folderChanged, folder = prop(str, "folder", "")

    def __init__(self, app, cfg: dict, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.app = app
        settings = versions.Settings.from_config(cfg.get(CONFIG_KEY))
        versions.configure(settings)
        self.set_quietly("enabled", settings.enabled)
        self.set_quietly("minutes", settings.minutes)
        self.set_quietly("keep", settings.keep)
        self.set_quietly("days", settings.days)
        self._docs: list[versions.Document] = []
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.autoBackup)
        self._apply_timer()
        self._reading = False
        self._again = False
        self._marked: dict[str, tuple[str, int]] = {}  # Dokument → Stand der letzten automatischen Fassung
        self.set_quietly("folder", str(versions.root_dir()))

    def config(self) -> dict:
        return {CONFIG_KEY: versions.Settings(self.enabled, self.minutes, self.keep, self.days).to_config()}

    def start(self) -> None:
        """Nach dem Start im Hintergrund: alte Fassungen aufräumen."""
        self.app.worker.run(lambda: versions.store().prune_all(), None, lambda _exc, _details: None)

    def _settings_changed(self) -> None:
        versions.configure(versions.Settings(self.enabled, self.minutes, self.keep, self.days))
        self._apply_timer()
        self.app.schedule_save()

    def _apply_timer(self) -> None:
        if self.enabled:
            self._timer.start(self.minutes * 60_000)
        else:
            self._timer.stop()

    # Einstellungen ------------------------------------------------------------------------------------------
    @Slot(bool)
    def setEnabled(self, on: bool) -> None:  # noqa: N802
        self.enabled = bool(on)
        self._settings_changed()

    @Slot(int)
    def setMinutes(self, value: int) -> None:  # noqa: N802
        if value in versions.INTERVALS:
            self.minutes = value
            self._settings_changed()

    @Slot(int)
    def setKeep(self, value: int) -> None:  # noqa: N802
        if value in versions.KEEP_CHOICES:
            self.keep = value
            self._settings_changed()

    @Slot(int)
    def setDays(self, value: int) -> None:  # noqa: N802
        if value in versions.DAY_CHOICES:
            self.days = value
            self._settings_changed()

    @Slot(result=list)
    def intervalChoices(self) -> list:  # noqa: N802
        return [{"key": value, "label": f"Alle {value} Minuten"} for value in versions.INTERVALS]

    @Slot(result=list)
    def keepChoices(self) -> list:  # noqa: N802
        return [{"key": value, "label": f"{value} Fassungen je Dokument"} for value in versions.KEEP_CHOICES]

    @Slot(result=list)
    def dayChoices(self) -> list:  # noqa: N802
        labels = {7: "1 Woche", 30: "30 Tage", 90: "90 Tage", 365: "1 Jahr"}
        return [{"key": value, "label": labels[value]} for value in versions.DAY_CHOICES]

    # Liste --------------------------------------------------------------------------------------------------
    @Slot()
    def refresh(self) -> None:
        if self._reading:
            self._again = True
            return
        self._reading = True
        self.loading = True

        def read():
            store = versions.store()
            return store.documents()

        def done(documents) -> None:
            self._reading = False
            self.loading = False
            self._docs = documents
            self._publish()
            if self._again:
                self._again = False
                self.refresh()

        def failed(_exc, _details) -> None:
            self._reading = False
            self.loading = False

        self.app.worker.run(read, done, failed)

    def _publish(self) -> None:
        rows = []
        for document in self._docs:
            newest = document.versions[0]
            count = len(document.versions)
            rows.append({
                "key": document.key, "name": document.name, "folder": str(Path(document.original).parent) if document.original else "",
                "path": document.original, "count": count, "countText": f"{count} {'Fassung' if count == 1 else 'Fassungen'}",
                "sizeText": _size(document.size), "lastText": newest.stamp, "exists": document.exists,
            })
        self.documents = rows
        total = sum(document.size for document in self._docs)
        self.totalText = f"{len(self._docs)} {'Dokument' if len(self._docs) == 1 else 'Dokumente'} · {_size(total)}" if self._docs else ""
        if self.selected and not any(document.key == self.selected for document in self._docs):
            self.selected = ""
        if not self.selected and self._docs:
            self.selected = self._docs[0].key
        self._publish_versions()

    def _publish_versions(self) -> None:
        document = next((document for document in self._docs if document.key == self.selected), None)
        if document is None:
            self.versionList = []
            return
        self.versionList = [
            {"path": str(version.path), "stamp": version.stamp, "kind": version.kind, "kindText": versions.KIND_LABELS[version.kind],
             "sizeText": _size(version.size), "newest": number == 0}
            for number, version in enumerate(document.versions)
        ]

    @Slot(str)
    def select(self, key: str) -> None:
        if any(document.key == key for document in self._docs):
            self.selected = key
            self._publish_versions()

    def _document(self) -> versions.Document | None:
        return next((document for document in self._docs if document.key == self.selected), None)

    # Fassungen ----------------------------------------------------------------------------------------------
    @Slot(str)
    def openVersion(self, path: str) -> None:  # noqa: N802
        """Eine Fassung ansehen: als Kopie im Arbeitsordner öffnen – die Ablage selbst bleibt unverändert."""
        document = self._document()
        source = Path(path)
        if document is None or not source.is_file():
            return
        folder = Path(tempfile.mkdtemp(prefix="novadesk-fassung-"))
        stamp = next((row["stamp"] for row in self.versionList if row["path"] == path), "").replace(":", ".")
        target = folder / f"{Path(document.name).stem} (Fassung {stamp}){source.suffix}"
        try:
            shutil.copyfile(source, target)
        except OSError:
            self.app.notify(AREA, "error", "Die Fassung ließ sich nicht öffnen.", title="Nicht geöffnet", auto_hide=8000)
            return
        reader = getattr(self.app, "reader_controller", None)
        if reader is not None:
            reader.open_paths([str(target)])
        else:
            files.open_path(target)

    @Slot(str)
    def restoreCopy(self, path: str) -> None:  # noqa: N802
        document = self._document()
        if document is None:
            return

        def done(target: Path) -> None:
            self.app.notify(AREA, "success", f"Als »{target.name}« neben dem Original gespeichert – das Original ist unverändert.",
                            title="Fassung wiederhergestellt", auto_hide=10000,
                            actions=[("Öffnen", lambda: self._open_in_reader(str(target))), ("Ordner öffnen", lambda: files.open_path(target.parent))])

        self._run(lambda: versions.store().restore_copy(path, document.original), done)

    @Slot(str)
    def restoreReplace(self, path: str) -> None:  # noqa: N802
        document = self._document()
        if document is None or not document.original:
            return
        reader = getattr(self.app, "reader_controller", None)
        if reader is not None and _is_open(reader, document.original):
            self.app.notify(AREA, "warning", f"»{document.name}« ist in Novadesk geöffnet. Bitte zuerst schließen, dann das Original ersetzen.",
                            title="Dokument ist geöffnet", auto_hide=10000)
            return
        stamp = next((row["stamp"] for row in self.versionList if row["path"] == path), "")
        answer, _data = self.app.dialogs.ask(
            "confirm", "Original ersetzen?",
            f"»{document.name}« wird durch die Fassung vom {stamp} ersetzt. Der jetzige Stand wird vorher als eigene Fassung gesichert.",
            primary="Original ersetzen", close="Abbrechen")
        if answer != "primary":
            return

        def done(target: Path) -> None:
            self.app.notify(AREA, "success", f"»{target.name}« ist wieder auf dem Stand vom {stamp}. Der vorherige Stand ist als Fassung gesichert.",
                            title="Original ersetzt", auto_hide=10000, actions=[("Öffnen", lambda: self._open_in_reader(str(target)))])

        self._run(lambda: versions.store().restore_replace(path, document.original), done)

    @Slot(str)
    def deleteVersion(self, path: str) -> None:  # noqa: N802
        self._run(lambda: versions.store().delete(path), lambda _ok: None)

    @Slot()
    def deleteDocument(self) -> None:  # noqa: N802
        document = self._document()
        if document is None:
            return
        answer, _data = self.app.dialogs.ask("confirm", "Alle Fassungen löschen?",
                                             f"Alle {len(document.versions)} Fassungen von »{document.name}« werden gelöscht. Das Dokument selbst bleibt unverändert.",
                                             primary="Fassungen löschen", close="Abbrechen", danger=True)
        if answer == "primary":
            self._run(lambda: versions.store().delete_document(document.key), lambda _ok: None)

    @Slot()
    def openFolder(self) -> None:  # noqa: N802
        root = versions.root_dir()
        root.mkdir(parents=True, exist_ok=True)
        files.open_path(root)

    @Slot()
    def openOriginalFolder(self) -> None:  # noqa: N802
        document = self._document()
        if document is not None and document.original and Path(document.original).parent.is_dir():
            files.open_path(Path(document.original).parent)

    def _open_in_reader(self, path: str) -> None:
        reader = getattr(self.app, "reader_controller", None)
        if reader is not None:
            reader.open_paths([path])
        else:
            files.open_path(path)

    def _run(self, work: Callable, done: Callable) -> None:
        def finished(result) -> None:
            done(result)
            self.refresh()

        def failed(exc: BaseException, _details: str) -> None:
            message = str(exc) if isinstance(exc, OSError) and str(exc) and not getattr(exc, "errno", None) else "Die Fassung ließ sich nicht wiederherstellen (Datei gesperrt oder Ordner schreibgeschützt)."
            self.app.notify(AREA, "error", message, title="Nicht möglich", auto_hide=10000)
            self.refresh()

        self.app.worker.run(work, finished, failed)

    # Automatische Sicherung ---------------------------------------------------------------------------------
    @Slot()
    def autoBackup(self) -> None:  # noqa: N802
        """Jedes geöffnete Dokument mit ungespeicherten Änderungen (und einem Speicherort) als Fassung ablegen."""
        reader = getattr(self.app, "reader_controller", None)
        if reader is None or not self.enabled:
            return
        store = versions.store()
        for document in list(getattr(reader, "_docs", {}).values()):
            writer = getattr(document, "write_version", None)
            path = getattr(document, "path", "")
            if writer is None or not path or not getattr(document, "dirty", False) or getattr(document, "saving", False):
                continue
            marker = (path, document.version_marker())
            if self._marked.get(document.ident) == marker:
                continue  # seit der letzten automatischen Fassung nicht verändert
            self._marked[document.ident] = marker
            try:
                target = store.snapshot_path(path, document.version_suffix())
            except OSError as exc:
                _log().warning("Automatische Sicherung nicht möglich: %s", type(exc).__name__)
                continue

            def written(ok: bool, target=target) -> None:
                if ok:
                    self.app.worker.run(lambda: store.added(target), lambda _added: self._auto_done(), lambda _exc, _details: None)
                else:
                    target.unlink(missing_ok=True)

            writer(str(target), written)

    def _auto_done(self) -> None:
        import time

        self.lastAuto = time.strftime("%H:%M")
        if self.app.currentPage == VERSIONS.pages[0]:
            self.refresh()


def _is_open(reader, path: str) -> bool:
    import os

    wanted = os.path.normcase(os.path.abspath(path))
    return any(os.path.normcase(os.path.abspath(getattr(document, "path", "") or "")) == wanted for document in getattr(reader, "_docs", {}).values() if getattr(document, "path", ""))


class VersionsTool:
    """Verbindet den Controller mit dem AppController."""

    key = VERSIONS.key

    def __init__(self, app, cfg: dict) -> None:
        self.app = app
        self.controller = VersionsController(app, cfg, app)
        app.register_tool(self.key, self)

    def primary_action(self, page: str) -> None:
        pass

    def open_action(self, page: str) -> None:
        reader = getattr(self.app, "reader_controller", None)
        if reader is not None:
            reader.openDialog()

    def find_action(self, page: str) -> None:
        pass

    def show_help(self, page: str) -> None:
        self.app.show_steps("Kurzanleitung – Backup-Center", (
            "Novadesk legt vor jedem Speichern den bisherigen Stand einer Datei als Fassung ab – für PDFs, Texte, Tabellen und Präsentationen.",
            "Solange ein Dokument ungespeicherte Änderungen hat, sichert Novadesk es zusätzlich in festen Abständen automatisch.",
            "Links ein Dokument wählen, rechts eine Fassung: »Öffnen« zeigt sie als Kopie, »Als Kopie wiederherstellen« legt sie neben das Original.",
            "»Original ersetzen« stellt die Fassung über das Original wieder her – der jetzige Stand wird vorher gesichert.",
        ), ("Die Fassungen liegen nur auf diesem PC (nicht in der Cloud) und werden nach der eingestellten Zeit gelöscht.",))

    def hint(self, page: str) -> str:
        return HINT

    def accepts(self, dropped: list[str], page: str) -> bool:
        return False

    def drag_enter(self, accepted: bool, page: str) -> None:
        pass

    def drag_leave(self) -> None:
        pass

    def drop(self, dropped: list[str], page: str) -> None:
        pass

    def page_prepare(self, page: str) -> None:
        self.controller.refresh()

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
        return ""

    def close(self) -> None:
        self.controller._timer.stop()  # noqa: SLF001
