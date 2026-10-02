"""Werkzeug »PDF Reader & Editor« (in QML: ``Reader``): Tabs, Öffnen (Dialog, Ziehen, zuletzt
geöffnet, »Öffnen mit«), Schließen mit Rückfrage, Passwörter, beschädigte PDFs, Sitzungs-
wiederherstellung nach einem Absturz und die Bildquelle der Seiten.

Passwörter bleiben nur im Arbeitsspeicher (nie in Einstellungen, Protokoll oder Sicherung). Die
Liste »Zuletzt geöffnet« enthält nur Pfade und lässt sich leeren. Inhalte von PDFs werden nie
protokolliert.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

from PySide6.QtCore import Property, QObject, Signal, Slot

from tools.pdf_editor import recovery
from tools.pdf_editor import save as save_engine
from tools.pdf_editor.errors import DamagedDocument, EditorError, NotAPdf, PasswordRequired
from tools.registry import READER

from .. import files
from ..base import Observable, prop
from ..models import KeyedListModel
from .document import DocumentController
from tools.pdf_editor.render import MAX_PIXELS

from .engine import BACKGROUND, THUMB, VIEW, Engine, PageImageProvider, RenderCache
from .session import THUMB_WIDTH, Session

RECENT_LIMIT = 12
TAB_LIMIT = 24
MAX_WIDTH = 12000  # Pixel – breitere Seitenbilder gibt es nicht (der Ausschnitt bleibt scharf)
# Farben der Werkzeuge (Text, Zeichnen, Markieren, Kommentare) – Farben auf dem Papier
TOOL_COLORS = (
    ("#000000", "Schwarz"), ("#5F6368", "Grau"), ("#E53935", "Rot"), ("#FB8C00", "Orange"), ("#FFEB3B", "Gelb"),
    ("#43A047", "Grün"), ("#00897B", "Petrol"), ("#1E88E5", "Blau"), ("#3949AB", "Indigo"), ("#8E24AA", "Lila"),
)
FONT_FAMILIES = (("Helvetica", "Serifenlos (Helvetica/Arial)"), ("Times", "Serif (Times)"), ("Courier", "Festbreite (Courier)"))
HELP_STEPS = (
    "PDF öffnen: »Öffnen« (Strg+O), eine Datei in das Fenster ziehen oder eine Datei aus »Zuletzt geöffnet« wählen.",
    "Lesen: Seiten blättern (Bild ↑/↓), zoomen (Strg+Mausrad, Strg++ / Strg+−), Miniaturen und Lesezeichen links, Suchen mit Strg+F.",
    "Bearbeiten: Werkzeug oben wählen – Text ändern oder hinzufügen, Bilder, Kommentare, Formulare. Rückgängig mit Strg+Z.",
    "Speichern: Strg+S (die Datei wird erst nach erfolgreicher Prüfung ersetzt), Speichern unter: Strg+Umschalt+S. Drucken: Strg+P.",
)
HELP_NOTES = (
    "Textänderungen nennen ihren Weg: »Direkt im PDF geändert«, »Neu gesetzt« oder »Kompatibilitätsmodus« (Überlagerung – keine Schwärzung, der Originaltext bleibt in der Datei).",
    "Ungespeicherte Änderungen werden regelmäßig lokal gesichert und nach einem Absturz zum Wiederherstellen angeboten.",
    "PDF-JavaScript wird nie ausgeführt. Alle Dateien bleiben auf diesem PC.",
)
HINT = "Strg+O Öffnen   ·   Strg+F Suchen   ·   Strg+S Speichern   ·   Strg+P Drucken   ·   Strg+Z Rückgängig"


class ReaderController(Observable):
    hasDocumentChanged, hasDocument = prop(bool, "hasDocument", False)
    currentKeyChanged, currentKey = prop(str, "currentKey", "")
    recentChanged, recent = prop(list, "recent", [])
    dropHighlightChanged, dropHighlight = prop(bool, "dropHighlight", False)
    leftPanelChanged, leftPanel = prop(str, "leftPanel", "thumbs")  # thumbs, outline, search oder ""
    rightPanelChanged, rightPanel = prop(str, "rightPanel", "")  # comments, properties oder ""
    organizeChanged, organize = prop(bool, "organize", False)  # Ansicht »Seiten organisieren«
    openingChanged, opening = prop(int, "opening", 0)  # Dateien, die gerade geöffnet werden

    currentChanged = Signal()

    def __init__(self, app, cfg: dict, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.app = app
        self.engine = Engine(self, on_exception=app.report_exception)
        self.cache = RenderCache()
        self._tabs = KeyedListModel(("key", "name", "dirty", "path", "tip"), key="key", parent=self)
        self._docs: dict[str, DocumentController] = {}
        self._current: DocumentController | None = None
        self._ids = 0
        recent = cfg.get("reader_zuletzt")
        self._recent_paths = [str(p) for p in recent if isinstance(p, str)][:RECENT_LIMIT] if isinstance(recent, list) else []
        view = cfg.get("reader_ansicht") if isinstance(cfg.get("reader_ansicht"), dict) else {}
        self._view = {"fit": view.get("fit", "width") if view.get("fit") in ("width", "page", "") else "width", "zoom": float(view.get("zoom", 100) or 100), "mode": view.get("mode", "continuous")}
        if view.get("links") in ("thumbs", "outline", "search", ""):
            self.set_quietly("leftPanel", view.get("links"))
        self.source_dir = str(cfg.get("ordner_reader") or "")
        self._external: list[str] = []
        self._refresh_recent()
        app.observe("ready", self._ready)

    # QML: aktuelles Dokument ---------------------------------------------------------------------------------
    def _get_current(self):
        return self._current

    current = Property(QObject, _get_current, notify=currentChanged)

    def provider(self) -> PageImageProvider:
        return PageImageProvider(self._render, self.cache)

    def _render(self, ident: str, page: int, width: int, revision: int, kind: str, region: tuple, deliver):
        controller = self._docs.get(ident)
        if controller is None:
            return None
        cache = self.cache

        def work():
            session = controller.session
            if session is None or session.closed:
                deliver(None, "Dokument geschlossen")
                return None
            try:
                image = session.render(page, max(8, min(int(width), MAX_WIDTH)), kind, region)
            except Exception as exc:  # noqa: BLE001 - eine Seite ohne Bild statt Absturz
                deliver(None, type(exc).__name__)
                return None
            if image is not None:
                cache.put((ident, page, width, session.document.revision, kind, region), image)
            deliver(image, "" if image is not None else "Seite nicht vorhanden")
            return None

        return self.engine.submit(work, priority=THUMB if kind == "thumb" else VIEW, label="seite")

    # QML-Konstanten: Grenze eines ganzen Seitenbilds (darüber zeigt die Ansicht den sichtbaren
    # Ausschnitt zusätzlich scharf) und Breite der Miniaturen
    def _max_pixels(self) -> int:
        return MAX_PIXELS

    def _thumb_width(self) -> int:
        return THUMB_WIDTH

    def _tool_colors(self) -> list:
        return [{"value": value, "name": name} for value, name in TOOL_COLORS]

    def _font_families(self) -> list:
        return [{"value": value, "label": label} for value, label in FONT_FAMILIES]

    def _tabs_model(self) -> KeyedListModel:
        return self._tabs

    _constant = Signal()
    tabs = Property(QObject, _tabs_model, notify=_constant)  # geöffnete Dokumente (Tabs)
    maxPagePixels = Property(int, _max_pixels, notify=_constant)
    thumbWidth = Property(int, _thumb_width, notify=_constant)
    toolColors = Property(list, _tool_colors, notify=_constant)
    fontFamilies = Property(list, _font_families, notify=_constant)

    # Öffnen -----------------------------------------------------------------------------------------------
    @Slot()
    def openDialog(self) -> None:  # noqa: N802
        paths = files.open_files("PDF öffnen", self.app.initial_dir("reader", self.source_dir), files.PDF_FILTER)
        if paths:
            self.source_dir = str(Path(paths[0]).parent)
            self.app.schedule_save()
            self.open_paths(paths)

    @Slot("QVariantList")
    def openPaths(self, paths: list) -> None:  # noqa: N802
        self.open_paths([str(p) for p in paths])

    @Slot(str)
    def openRecent(self, path: str) -> None:  # noqa: N802
        if not Path(path).is_file():
            self.app.notify("reader", "warning", f"Die Datei »{Path(path).name}« gibt es nicht mehr.", title="Nicht gefunden")
            self._recent_paths = [p for p in self._recent_paths if p != path]
            self._refresh_recent()
            return
        self.open_paths([path])

    def open_external(self, paths: list[str]) -> None:
        """PDFs aus der Befehlszeile oder von einem weiteren Start (»Öffnen mit«) – nach dem Start."""
        if self.app.ready:
            self.open_paths(paths)
        else:
            self._external.extend(paths)

    def _ready(self, ready: bool) -> None:
        if not ready:
            return
        waiting, self._external = self._external, []
        if waiting:
            self.open_paths(waiting)
        self.offer_recovery()
        # Sicherungskopien vor dem Überschreiben: älter als 7 Tage entfernen (je Datei bleiben höchstens 3)
        self.engine.submit(lambda: save_engine.cleanup_backups(recovery.backups_dir()), None, lambda _exc, _details: None, priority=BACKGROUND, label="aufräumen")

    def open_paths(self, paths: list[str]) -> None:
        pdfs = [p for p in paths if p.lower().endswith(".pdf") or _looks_like_pdf(p)]
        if not pdfs:
            self.app.notify("reader", "warning", "Bitte eine PDF-Datei wählen.", title="Keine PDF")
            return
        if self.app.currentPage != "reader":
            self.app.navigate(READER.key)
        for path in pdfs:
            existing = next((doc for doc in self._docs.values() if doc.path and _same(doc.path, path)), None)
            if existing is not None:
                self.activate(existing.ident)
                continue
            if len(self._docs) >= TAB_LIMIT:
                self.app.notify("reader", "warning", f"Höchstens {TAB_LIMIT} Dokumente gleichzeitig – bitte erst ein Dokument schließen.", title="Zu viele Dokumente")
                return
            self._open(path, None)

    def _open(self, path: str, password: str | None, recovered: recovery.SessionInfo | None = None) -> None:
        self._ids += 1
        ident = f"d{self._ids}"
        controller = DocumentController(self, self.engine, ident, self)
        self.opening = self.opening + 1
        name = recovered.name if recovered is not None else Path(path).name
        self.app.set_status(f"Wird geöffnet: {name} …", "busy")

        def work():
            if recovered is not None:
                session = Session.from_recovery(ident, recovered, password)
            else:
                session = Session.open(ident, path, password)
            controller.session = session
            return session.state()

        def done(state) -> None:
            self.opening = max(0, self.opening - 1)
            self._docs[ident] = controller
            controller.apply_state(state)
            fit = self._view["fit"]
            controller.viewMode = self._view["mode"] if self._view["mode"] in ("continuous", "single", "two", "continuousTwo") else "continuous"
            if fit:
                controller.fit = fit
            else:
                controller.fit = ""
                controller.setZoom(self._view["zoom"])
            controller.opening_notice()
            controller.load_outline()
            controller.loadAnnotations()
            controller.loadFields()
            self.tabs.set_items([*self.tabs.items(), self._tab_item(controller)])
            self.activate(ident)
            if recovered is None:
                self.remember_recent(path)
            else:
                # Sofort neu sichern: die neue Sitzung gehört diesem Prozess, die alte wird entfernt –
                # so bietet ein weiterer Start dieselbe Sitzung nicht noch einmal an
                controller.write_recovery_now()
            self.app.set_status(f"Geöffnet: {controller.name} – {controller.pageCount} Seite(n)", "success")

        def failed(exc: BaseException, _details: str) -> None:
            self.opening = max(0, self.opening - 1)
            controller.deleteLater()
            if isinstance(exc, PasswordRequired):
                secret = self.ask_password(name, exc.wrong)
                if secret is not None:
                    self._open(path, secret, recovered)
                else:
                    self.app.set_status("Öffnen abgebrochen.", "neutral")
                return
            if isinstance(exc, DamagedDocument):
                self._offer_repair(path)
                return
            if isinstance(exc, NotAPdf):
                self.app.notify("reader", "error", f"»{name}« ist keine PDF-Datei.", title="Öffnen nicht möglich")
                return
            message = str(exc) if isinstance(exc, EditorError) else f"»{name}« konnte nicht geöffnet werden."
            if not isinstance(exc, (EditorError, OSError)):
                self.app.report_exception(_details)
            self.app.notify("reader", "error", message, title="Öffnen nicht möglich")

        self.engine.submit(work, done, failed, label="öffnen")

    def _offer_repair(self, path: str) -> None:
        name = Path(path).name
        answer, _data = self.app.dialogs.ask(
            "confirm", "Dieses Dokument scheint beschädigt zu sein.",
            f"»{name}« lässt sich nicht öffnen. »PDF reparieren« kann lesbare Inhalte in eine neue Datei übertragen – das Original bleibt unverändert. Danach lässt sich die reparierte Datei hier öffnen.",
            primary="Mit »PDF reparieren« öffnen", close="Abbrechen",
        )
        if answer == "primary":
            repair = getattr(self.app, "repair_tool", None)
            self.app.navigate("repair")
            if repair is not None:
                repair.drop([path], "repair")

    def ask_password(self, name: str, wrong: bool) -> str | None:
        answer, data = self.app.dialogs.ask(
            "password", "Passwort erforderlich",
            ("Das Passwort ist falsch. " if wrong else "") + f"»{name}« ist mit einem Passwort geschützt.",
            primary="Öffnen", close="Abbrechen", data={"label": "Passwort"},
        )
        if answer != "primary":
            return None
        return str(data.get("value") or "")

    # Tabs ---------------------------------------------------------------------------------------------------
    def _tab_item(self, controller: DocumentController) -> dict:
        return {"key": controller.ident, "name": controller.name, "dirty": controller.dirty, "path": controller.path, "tip": controller.path or controller.name}

    def tab_changed(self, controller: DocumentController) -> None:
        if controller.ident in self._docs:
            self.tabs.update_item(controller.ident, **self._tab_item(controller))

    @Slot(str)
    def activate(self, key: str) -> None:
        controller = self._docs.get(key)
        if controller is None or controller is self._current:
            return
        self._current = controller
        self.currentKey = key
        self.hasDocument = True
        self.currentChanged.emit()

    @Slot(int)
    def activateIndex(self, offset: int) -> None:  # noqa: N802 - Strg+Tab / Strg+Umschalt+Tab
        keys = self.tabs.keys()
        if not keys:
            return
        index = keys.index(self.currentKey) if self.currentKey in keys else 0
        self.activate(keys[(index + offset) % len(keys)])

    @Slot(str, result=bool)
    def closeTab(self, key: str) -> bool:  # noqa: N802
        controller = self._docs.get(key)
        if controller is None:
            return True
        if controller.dirty:
            answer, _data = self.app.dialogs.ask(
                "confirm", f"Änderungen an »{controller.name}« speichern?",
                "Ohne Speichern gehen die Änderungen verloren.",
                primary="Speichern", secondary="Nicht speichern", close="Abbrechen",
            )
            if answer == "primary":
                controller.save(then=lambda ok, key=key: self._finish_close(key, True) if ok else None)
                return False
            if answer != "secondary":
                return False
        self._finish_close(key, True)
        return True

    @Slot()
    def closeCurrent(self) -> None:  # noqa: N802
        if self.currentKey:
            self.closeTab(self.currentKey)

    def _finish_close(self, key: str, discard_recovery: bool) -> None:
        controller = self._docs.pop(key, None)
        if controller is None:
            return
        keys = self.tabs.keys()
        position = keys.index(key) if key in keys else 0
        self.tabs.set_items([item for item in self.tabs.items() if item["key"] != key])
        controller.shutdown(discard_recovery)
        self.cache.drop(key)
        if self._current is controller:
            remaining = self.tabs.keys()
            self._current = None
            self.currentKey = ""
            if remaining:
                self.activate(remaining[min(position, len(remaining) - 1)])
            else:
                self.hasDocument = False
                self.organize = False
                self.currentChanged.emit()
        controller.deleteLater()

    # Zuletzt geöffnet, Ansicht ---------------------------------------------------------------------------------
    def remember_recent(self, path: str) -> None:
        path = str(path)
        self._recent_paths = [path] + [p for p in self._recent_paths if not _same(p, path)]
        del self._recent_paths[RECENT_LIMIT:]
        self._refresh_recent()
        self.app.schedule_save()

    def _refresh_recent(self) -> None:
        items = []
        for path in self._recent_paths:
            p = Path(path)
            items.append({"path": path, "name": p.name, "folder": str(p.parent), "missing": not p.is_file()})
        self.recent = items

    @Slot()
    def clearRecent(self) -> None:  # noqa: N802
        self._recent_paths = []
        self._refresh_recent()
        self.app.schedule_save()
        self.app.set_status("Liste »Zuletzt geöffnet« geleert.", "success")

    @Slot(str)
    def showInFolder(self, path: str) -> None:  # noqa: N802
        if path and Path(path).parent.is_dir():
            self.app.open_folder_of(path, "reader")

    @Slot(str)
    def removeRecent(self, path: str) -> None:  # noqa: N802
        self._recent_paths = [p for p in self._recent_paths if p != path]
        self._refresh_recent()
        self.app.schedule_save()

    def remember_view(self, controller: DocumentController) -> None:
        self._view = {"fit": controller.fit, "zoom": controller.zoom, "mode": controller.viewMode}
        self.app.schedule_save()

    @Slot(str)
    def setLeftPanel(self, panel: str) -> None:  # noqa: N802
        self.leftPanel = "" if panel == self.leftPanel else panel
        self.app.schedule_save()

    @Slot(str)
    def showLeftPanel(self, panel: str) -> None:  # noqa: N802
        """Linke Seitenleiste zeigen (ohne Umschalten): ``thumbs``, ``outline`` oder ``search``."""
        if panel in ("thumbs", "outline", "search") and panel != self.leftPanel:
            self.leftPanel = panel
            self.app.schedule_save()

    @Slot(str)
    def setRightPanel(self, panel: str) -> None:  # noqa: N802
        self.rightPanel = "" if panel == self.rightPanel else panel

    @Slot(str)
    def showRightPanel(self, panel: str) -> None:  # noqa: N802
        """Rechte Seitenleiste zeigen (ohne Umschalten): ``comments`` oder ``properties``."""
        if panel in ("comments", "properties"):
            self.rightPanel = panel

    @Slot(bool)
    def setOrganize(self, value: bool) -> None:  # noqa: N802
        self.organize = bool(value) and self.hasDocument

    def config(self) -> dict:
        return {"reader_zuletzt": list(self._recent_paths), "reader_ansicht": {**self._view, "links": self.leftPanel}, "ordner_reader": self.source_dir}

    # Dateiauswahl -------------------------------------------------------------------------------------------------
    def pick_pdf(self, title: str) -> str:
        return files.open_file(title, self.app.initial_dir("reader", self.source_dir), files.PDF_FILTER)

    def pick_pdfs(self, title: str) -> list[str]:
        return files.open_files(title, self.app.initial_dir("reader", self.source_dir), files.PDF_FILTER)

    def pick_image(self) -> str:
        return files.open_file("Bild wählen", self.app.initial_dir("logo", ""), "Bilder (*.png *.jpg *.jpeg);;Alle Dateien (*.*)")

    def pick_folder(self, title: str) -> str:
        return files.pick_folder(title, self.app.initial_dir("reader", self.source_dir))

    def pick_save_pdf(self, name: str, title: str) -> str:
        current = self._current.path if self._current is not None and self._current.path else ""
        folder = str(Path(current).parent) if current else self.app.initial_dir("reader", self.source_dir)
        target = files.save_file(title, str(Path(folder) / name), files.PDF_FILTER)
        if target and not target.lower().endswith(".pdf"):
            target += ".pdf"
        return target

    # Absturz: ungespeicherte Bearbeitungen ------------------------------------------------------------------
    def offer_recovery(self) -> None:
        """Nach dem Start: verwaiste Sitzungen (Absturz) zum Wiederherstellen anbieten."""
        def find():
            return recovery.orphaned_sessions()

        def done(found) -> None:
            for info in found[:5]:
                when = time.strftime("%d.%m.%Y %H:%M", time.localtime(info.saved_at))
                origin = f"Original: {info.original}" if info.original else "Neues Dokument"
                answer, _data = self.app.dialogs.ask(
                    "confirm", "Eine nicht gespeicherte Bearbeitung wurde gefunden.",
                    f"»{info.name}« – zuletzt gesichert am {when}. {origin}. Wiederhergestellt wird ein ungespeicherter Stand; die Originaldatei bleibt unverändert, bis Sie speichern.",
                    primary="Wiederherstellen", secondary="Verwerfen", close="Später",
                )
                if answer == "primary":
                    if self.app.currentPage != "reader":
                        self.app.navigate(READER.key)
                    self._open(info.original or info.name, None, recovered=info)
                elif answer == "secondary":
                    recovery.discard_session(info)

        self.engine.submit(find, done, lambda _exc, _details: None, label="wiederherstellung", priority=3)

    # Beenden -----------------------------------------------------------------------------------------------------
    def confirm_close(self) -> bool:
        for controller in list(self._docs.values()):
            if not controller.dirty:
                continue
            self.activate(controller.ident)
            answer, _data = self.app.dialogs.ask(
                "confirm", f"Änderungen an »{controller.name}« speichern?", "PDF Tool wird beendet. Ohne Speichern gehen die Änderungen verloren.",
                primary="Speichern", secondary="Nicht speichern", close="Abbrechen",
            )
            if answer == "primary":
                if not self._save_now(controller):
                    return False
            elif answer != "secondary":
                return False
        return True

    def _save_now(self, controller: DocumentController) -> bool:
        target = controller.path or self.pick_save_pdf(controller.name or "Dokument.pdf", "Speichern unter")
        if not target:
            return False
        task = self.engine.submit(lambda: controller.session.save(target), label="speichern")
        try:
            self.engine.wait(task, timeout=600)
        except Exception as exc:  # noqa: BLE001 - Fehler anzeigen (mit Protokoll), Beenden abbrechen
            controller._report_save_error(exc)  # noqa: SLF001
            return False
        return True

    def running_work(self) -> str:
        return "PDF speichern" if any(controller.busy or controller.saving for controller in self._docs.values()) else ""

    def close_all(self) -> None:
        for key in list(self._docs):
            self._finish_close(key, discard_recovery=True)
        self.engine.shutdown()


class ReaderTool:
    """Anbindung an den AppController (Tastenkürzel, Ziehen und Ablegen, Beenden)."""

    def __init__(self, app, cfg: dict) -> None:
        self.app = app
        self.controller = ReaderController(app, cfg, app)
        app.register_tool(READER.key, self)

    def primary_action(self, page: str) -> None:
        current = self.controller.current
        if current is not None:
            current.saveDocument()

    def open_action(self, page: str) -> None:
        self.controller.openDialog()

    def find_action(self, page: str) -> None:
        current = self.controller.current
        if current is not None:
            self.controller.leftPanel = "search"
            current.requestSearch()

    def show_help(self, page: str) -> None:
        self.app.show_steps("Kurzanleitung – PDF Reader & Editor", HELP_STEPS, HELP_NOTES)

    def hint(self, page: str) -> str:
        return HINT

    def accepts(self, paths: list[str], page: str) -> bool:
        return any(p.lower().endswith(".pdf") for p in paths)

    def drag_enter(self, accepted: bool, page: str) -> None:
        self.controller.dropHighlight = accepted

    def drag_leave(self) -> None:
        self.controller.dropHighlight = False

    def drop(self, paths: list[str], page: str) -> None:
        self.controller.open_paths(paths)

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
        return self.controller.confirm_close()

    def running_work(self) -> str:
        return self.controller.running_work()

    def close(self) -> None:
        self.controller.close_all()


def _same(a: str, b: str) -> bool:
    try:
        return os.path.samefile(a, b)
    except OSError:
        return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


def _looks_like_pdf(path: str) -> bool:
    try:
        with open(path, "rb") as handle:
            return b"%PDF-" in handle.read(1024)
    except OSError:
        return False
