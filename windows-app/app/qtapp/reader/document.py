"""Ein geöffnetes Dokument in der Oberfläche (in QML: ``Reader.current``).

Hält, was QML anzeigt (Seitengrößen, Zoom, aktuelle Seite, Auswahl, Treffer, Blöcke, Bilder,
Kommentare, Formularfelder, Rückgängig-Titel) und schickt jede Arbeit an den Arbeitsthread
(``engine.Engine``). Koordinaten sind Anzeige-Punkte je Seite; QML multipliziert mit ``scale``.
"""

from __future__ import annotations

import hashlib
import itertools
import os
import time
import traceback
from typing import Any, Callable

from PySide6.QtCore import Property, QObject, Signal, Slot

from tools.pdf_editor.errors import EditorError, ExternalChange, PasswordRequired, ReadOnlyDocument, SaveFailed, UnsupportedEdit
from tools.pdf_editor.textedit import Overflow

from ..base import Observable, prop
from ..models import KeyedListModel
from .engine import BACKGROUND, EDIT, VIEW, Engine, Task

PT_TO_PX = 96 / 72  # 100 % = Originalgröße bei 96 dpi
ZOOM_STEPS = (25, 33, 50, 67, 75, 100, 125, 150, 200, 300, 400)
ZOOM_MIN, ZOOM_MAX = 10.0, 800.0
PAGE_GAP = 12  # Abstand der Seiten (geräteunabhängige Pixel)
VIEW_MARGIN = 16
VIEW_MODES = ("continuous", "single", "two", "continuousTwo")
TOOLS = ("select", "editText", "addText", "image", "highlight", "underline", "strikeout", "note", "ink", "rect", "ellipse", "line", "arrow", "textbox", "form")
RECOVERY_DELAY_MS = 4000
SAVED_SHOWN_MS = 2500  # »Gespeichert« so lange in der Werkzeugleiste
SEARCH_LIMIT = 5000
LISTED_HITS = 500
_ids = itertools.count(1)


class DocumentController(Observable):
    """Zustand eines Tabs; Arbeit läuft im Arbeitsthread."""

    # Datei
    nameChanged, name = prop(str, "name", "")
    pathChanged, path = prop(str, "path", "")
    dirtyChanged, dirty = prop(bool, "dirty", False)
    revisionChanged, revision = prop(int, "revision", 0)
    pageCountChanged, pageCount = prop(int, "pageCount", 0)
    pageSizesChanged, pageSizes = prop(list, "pageSizes", [])
    readOnlyReasonChanged, readOnlyReason = prop(str, "readOnlyReason", "")
    permissionsChanged, permissions = prop(dict, "permissions", {})
    signedChanged, signed = prop(int, "signed", 0)
    noticeChanged, notice = prop(str, "notice", "")  # Hinweis beim Öffnen (signiert, repariert, XFA …)
    noticeKindChanged, noticeKind = prop(str, "noticeKind", "info")
    # Ansicht
    currentPageChanged, currentPage = prop(int, "currentPage", 0)
    zoomChanged, zoom = prop(float, "zoom", 100.0)  # Prozent
    scaleChanged, scale = prop(float, "scale", PT_TO_PX)  # Pixel je Punkt
    fitChanged, fit = prop(str, "fit", "width")  # width, page oder "" (freier Zoom)
    viewModeChanged, viewMode = prop(str, "viewMode", "continuous")
    toolChanged, tool = prop(str, "tool", "select")
    busyChanged, busy = prop(bool, "busy", False)
    busyTextChanged, busyText = prop(str, "busyText", "")
    savingChanged, saving = prop(bool, "saving", False)  # Speichern läuft (je Dokument nie zweimal gleichzeitig)
    saveStateChanged, saveState = prop(str, "saveState", "")  # "saving", kurz "saved", sonst ""
    # Rückgängig
    undoTextChanged, undoText = prop(str, "undoText", "")
    redoTextChanged, redoText = prop(str, "redoText", "")
    # Auswahl (Text)
    selectionPageChanged, selectionPage = prop(int, "selectionPage", -1)
    selectionRectsChanged, selectionRects = prop(list, "selectionRects", [])
    textPagesChanged, textPages = prop(list, "textPages", [])  # Seiten mit geladener Zeichentabelle
    # Suche
    searchTextChanged, searchText = prop(str, "searchText", "")
    searchCaseChanged, searchCase = prop(bool, "searchCase", False)
    searchWordsChanged, searchWords = prop(bool, "searchWords", False)
    searchRunningChanged, searchRunning = prop(bool, "searchRunning", False)
    searchProgressChanged, searchProgress = prop(float, "searchProgress", 0.0)
    searchCountChanged, searchCount = prop(int, "searchCount", 0)
    searchIndexChanged, searchIndex = prop(int, "searchIndex", -1)
    searchSummaryChanged, searchSummary = prop(str, "searchSummary", "")
    hitRectsChanged, hitRects = prop(dict, "hitRects", {})  # Seite (Text) → Liste von Rechtecken
    currentHitChanged, currentHit = prop(dict, "currentHit", {})  # {page, rects}
    # Bearbeiten
    blocksChanged, blocks = prop(list, "blocks", [])
    blocksPageChanged, blocksPage = prop(int, "blocksPage", -1)
    imagesChanged, images = prop(list, "images", [])
    imagesPageChanged, imagesPage = prop(int, "imagesPage", -1)
    fieldsChanged, fields = prop(list, "fields", [])
    fieldPagesChanged, fieldPages = prop(dict, "fieldPages", {})  # Seite (Text) → Widgets der Felder
    annotationsChanged, annotations = prop(list, "annotations", [])
    annotationPagesChanged, annotationPages = prop(dict, "annotationPages", {})  # Seite (Text) → Kommentare
    selectedObjectChanged, selectedObject = prop(dict, "selectedObject", {})  # {kind: image|annotation, page, index|key, view}
    lastModeChanged, lastMode = prop(str, "lastMode", "")  # Weg der letzten Textänderung (ehrlich benannt)
    # Farben und Stärken der Werkzeuge
    toolColorChanged, toolColor = prop(str, "toolColor", "#E53935")
    markColorChanged, markColor = prop(str, "markColor", "#FFEB3B")
    strokeWidthChanged, strokeWidth = prop(float, "strokeWidth", 2.0)
    fontSizeChanged, fontSize = prop(float, "fontSize", 12.0)
    hasOutlineChanged, hasOutline = prop(bool, "hasOutline", False)

    # Aufträge an die Ansicht als Properties (QML reagiert mit eigenen Handlern, ohne »Connections«)
    revealTargetChanged, revealTarget = prop(dict, "revealTarget", {})  # {page, u, v, serial}: Stelle in den Blick holen
    searchFocusSerialChanged, searchFocusSerial = prop(int, "searchFocusSerial", 0)  # Suchfeld fokussieren

    closed = Signal()

    def __init__(self, reader, engine: Engine, session_id: str, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.reader = reader
        self.app = reader.app
        self.engine = engine
        self.ident = session_id
        self.session = None  # nur im Arbeitsthread benutzen
        self._outline = KeyedListModel(("key", "level", "title", "page", "hasChildren", "expanded", "visible"), key="key", parent=self)
        self._hits = KeyedListModel(("key", "page", "hit", "excerpt"), key="key", parent=self)
        self._annotation_list = KeyedListModel(("key", "page", "label", "contents", "author", "modified", "color", "subtype"), key="key", parent=self)
        self._outline_entries: list[dict] = []
        self._texts: dict[int, Any] = {}  # Seite → PageText (Zeichentabelle)
        self._text_requests: set[int] = set()
        self._selection: tuple[int, int, int] | None = None  # Seite, Anfang, Ende (einschließlich)
        self._search_task: Task | None = None
        self._search_hits: list[dict] = []
        self._search_serial = 0
        self._viewport = (900.0, 700.0, 1.0)
        self._pending: dict[str, Task] = {}
        self._save_next: dict | None = None  # Speicheranfrage während eines laufenden Speicherns
        self._failure_details = ""  # Traceback des zuletzt fehlgeschlagenen Auftrags (Protokoll)
        self._closing = False
        self.state: dict = {}

    # QML-Konstanten --------------------------------------------------------------------------------------
    def _gap(self) -> int:
        return PAGE_GAP

    def _ident(self) -> str:
        return self.ident

    def _outline_model(self) -> KeyedListModel:
        return self._outline

    def _hits_model(self) -> KeyedListModel:
        return self._hits

    def _annotations_model(self) -> KeyedListModel:
        return self._annotation_list

    _constant = Signal()
    pageGap = Property(int, _gap, notify=_constant)
    docId = Property(str, _ident, notify=_constant)
    outline = Property(QObject, _outline_model, notify=_constant)  # Lesezeichen (sichtbare Einträge)
    hits = Property(QObject, _hits_model, notify=_constant)  # Trefferliste der Suche
    annotationList = Property(QObject, _annotations_model, notify=_constant)  # Kommentare aller Seiten

    # Zustand aus dem Arbeitsthread -----------------------------------------------------------------------
    def apply_state(self, state: dict) -> None:
        self.state = state
        self.name = state["name"]
        self.path = state["path"]
        sizes = state["sizes"]
        if sizes != self.pageSizes:
            self.pageSizes = sizes
        self.pageCount = state["pages"]
        self.readOnlyReason = state["readOnly"]
        self.permissions = state["permissions"]
        self.signed = state["signed"]
        self.undoText = state["undo"]
        self.redoText = state["redo"]
        if state["revision"] != self.revision:
            self._texts.clear()
            self.textPages = []
            self.clear_selection()
            self.revision = state["revision"]
            if self.searchCount:
                self.hitRects = {}
                self.currentHit = {}
                self.hits.clear()
                self.searchCount = 0
                self.searchIndex = -1
                self.searchSummary = "Das Dokument wurde geändert – bitte erneut suchen."
        self.dirty = state["dirty"]
        if self.currentPage >= self.pageCount:
            self.currentPage = max(0, self.pageCount - 1)
        self.reader.tab_changed(self)
        if self.dirty:
            self.app.timers.later(f"reader:recovery:{self.ident}", RECOVERY_DELAY_MS, self._write_recovery)
        self._apply_fit()

    def opening_notice(self) -> None:
        state = self.state
        notes = []
        kind = "info"
        if state.get("signed"):
            notes.append("Dieses PDF ist digital signiert. Jede Änderung macht die Signatur ungültig – PDF Tool fragt vor der ersten Bearbeitung nach.")
            kind = "warning"
        if state.get("readOnly"):
            notes.append(state["readOnly"])
            kind = "warning"
        if state.get("repaired"):
            notes.append("Beim Öffnen wurden kleine Strukturfehler ausgeglichen. Beim Speichern entsteht eine bereinigte Datei; bei Problemen hilft »PDF reparieren«.")
        if state.get("xfa"):
            notes.append("Das PDF enthält ein XFA-Formular. PDF Tool zeigt und bearbeitet nur den AcroForm-Teil.")
        if state.get("javascript"):
            notes.append("Das PDF enthält JavaScript. Es wird nicht ausgeführt.")
        self.notice = " ".join(notes)
        self.noticeKind = kind

    # Hilfen für Aufträge -------------------------------------------------------------------------------------
    def run(self, func: Callable[[Any], Any], done: Callable[[Any], None] | None = None, *, busy: str = "", refresh: bool = True, failed: Callable[[BaseException], None] | None = None, priority: int = EDIT, key: str = "") -> Task:
        """``func(session)`` im Arbeitsthread; danach (GUI-Thread) ``done(ergebnis)`` und – bei
        Änderungen – den neuen Zustand übernehmen. Fehler erscheinen als Hinweis."""
        if busy:
            self.busy = True
            self.busyText = busy

        def work():
            result = func(self.session)
            state = self.session.state() if refresh and self.session is not None and not self.session.closed else None
            return result, state

        def finish(payload) -> None:
            result, state = payload
            if busy:
                self.busy = False
                self.busyText = ""
            if state is not None:
                self.apply_state(state)
            if done is not None:
                done(result)

        def error(exc: BaseException, details: str) -> None:
            if busy:
                self.busy = False
                self.busyText = ""
            if failed is not None and not isinstance(exc, (MemoryError,)):
                self._failure_details = details
                failed(exc)
                return
            self.report(exc, details)
            # Nach einem Fehler den tatsächlichen Stand zeigen (z. B. zurückgenommene Änderung)
            if refresh and self.session is not None and not self.session.closed:
                self.run(lambda session: None, refresh=True)

        task = self.engine.submit(work, finish, error, priority=priority, label=key or busy)
        if key:
            old = self._pending.pop(key, None)
            if old is not None:
                old.cancel()
            self._pending[key] = task
        return task

    def report(self, exc: BaseException, details: str = "") -> None:
        if isinstance(exc, Overflow):
            return
        if isinstance(exc, (EditorError, UnsupportedEdit, ReadOnlyDocument, SaveFailed)):
            message = str(exc)
        elif isinstance(exc, OSError):
            message = f"Die Datei konnte nicht gelesen oder geschrieben werden ({exc.strerror or exc})."
        else:
            message = "Unerwarteter Fehler – Details stehen in fehler.log."
            self.app.report_exception(details or repr(exc))
        self.app.notify("reader", "error", message, title="Nicht möglich", status=True)

    def edit_allowed(self, what: str = "edit") -> bool:
        """Vor der ersten Änderung eines signierten Dokuments nachfragen."""
        if self.readOnlyReason and what in ("edit", "assemble"):
            self.app.notify("reader", "warning", self.readOnlyReason, title="Nur lesen")
            return False
        permissions = self.permissions or {}
        key = {"annotate": "annotate", "fill_forms": "fill", "assemble": "assemble"}.get(what, "edit")
        if permissions and not permissions.get(key, True):
            self.app.notify("reader", "warning", "Die Berechtigungen dieses PDFs erlauben das nicht.", title="Nicht erlaubt")
            return False
        if self.signed and not self.__dict__.get("_signature_ok"):
            ok = self.app.dialogs.confirm("Signiertes Dokument bearbeiten?", "Dieses PDF ist digital signiert. Jede Änderung macht die vorhandene Signatur ungültig. Die Originaldatei bleibt unverändert, bis Sie speichern.", "Trotzdem bearbeiten", danger=True)
            if not ok:
                return False
            self.__dict__["_signature_ok"] = True
        return True

    def edited(self, title: str = "") -> None:
        if title:
            self.app.set_status(title, "success")

    # Ansicht: Seiten und Zoom --------------------------------------------------------------------------------
    @Slot(float, float, float)
    def setViewport(self, width: float, height: float, ratio: float) -> None:  # noqa: N802
        self._viewport = (max(100.0, width), max(100.0, height), max(1.0, ratio))
        self._apply_fit()

    def _apply_fit(self) -> None:
        if not self.fit or not self.pageSizes:
            return
        width, height, _ratio = self._viewport
        index = min(self.currentPage, len(self.pageSizes) - 1)
        page_w, page_h = self.pageSizes[index]
        avail_w = width - 2 * VIEW_MARGIN - 14  # Bildlaufleiste
        avail_h = height - 2 * VIEW_MARGIN
        if self.viewMode in ("two", "continuousTwo"):
            # zwei Seiten nebeneinander; der Abstand zwischen ihnen wächst nicht mit dem Zoom
            first = index - index % 2
            pair = self.pageSizes[first : first + 2]
            page_w = sum(size[0] for size in pair)
            page_h = max(size[1] for size in pair)
            avail_w -= PAGE_GAP if len(pair) > 1 else 0
        scale = avail_w / max(1.0, page_w)
        if self.fit == "page":
            scale = min(scale, avail_h / max(1.0, page_h))
        self._set_zoom(scale / PT_TO_PX * 100, keep_fit=True)

    def _set_zoom(self, percent: float, keep_fit: bool = False) -> None:
        percent = max(ZOOM_MIN, min(ZOOM_MAX, float(percent)))
        if not keep_fit:
            self.fit = ""
        if abs(percent - self.zoom) < 0.05:
            return
        self.zoom = round(percent, 2)
        self.scale = round(percent / 100 * PT_TO_PX, 5)
        self.reader.remember_view(self)

    @Slot(float)
    def setZoom(self, percent: float) -> None:  # noqa: N802
        self._set_zoom(percent)

    @Slot()
    def zoomIn(self) -> None:  # noqa: N802
        self._set_zoom(next((step for step in ZOOM_STEPS if step > self.zoom + 0.5), ZOOM_STEPS[-1]))

    @Slot()
    def zoomOut(self) -> None:  # noqa: N802
        self._set_zoom(next((step for step in reversed(ZOOM_STEPS) if step < self.zoom - 0.5), ZOOM_STEPS[0]))

    @Slot(float)
    def zoomBy(self, factor: float) -> None:  # noqa: N802 - Strg+Mausrad: freier Zoom
        self._set_zoom(self.zoom * max(0.5, min(2.0, factor)))

    @Slot()
    def fitWidth(self) -> None:  # noqa: N802
        self.fit = "width"
        self._apply_fit()
        self.reader.remember_view(self)

    @Slot()
    def fitPage(self) -> None:  # noqa: N802
        self.fit = "page"
        self._apply_fit()
        self.reader.remember_view(self)

    @Slot()
    def actualSize(self) -> None:  # noqa: N802
        self._set_zoom(100)

    @Slot(str)
    def setViewMode(self, mode: str) -> None:  # noqa: N802
        if mode in VIEW_MODES and mode != self.viewMode:
            self.viewMode = mode
            self._apply_fit()
            self.reader.remember_view(self)

    @Slot(int)
    def goTo(self, page: int) -> None:  # noqa: N802
        if self.pageCount:
            target = max(0, min(self.pageCount - 1, int(page)))
            self.currentPage = target
            self.reveal(target, -1.0, -1.0)

    def reveal(self, page: int, u: float, v: float) -> None:
        """Seite (und Stelle u, v; < 0 = Seitenanfang) in den Blick holen."""
        serial = int(self.revealTarget.get("serial", 0)) + 1
        self.revealTarget = {"page": int(page), "u": float(u), "v": float(v), "serial": serial}

    @Slot(int)
    def setCurrentPage(self, page: int) -> None:  # noqa: N802 - aus der Ansicht (Scrollen), ohne Sprung
        if 0 <= page < self.pageCount and page != self.currentPage:
            self.currentPage = page
            if self.fit == "page":
                self._apply_fit()

    @Slot(int)
    def step(self, delta: int) -> None:
        """Seite vor/zurück; zweiseitig zur ersten Seite der nächsten bzw. vorigen Doppelseite."""
        if self.viewMode in ("two", "continuousTwo"):
            self.goTo(self.currentPage - self.currentPage % 2 + delta * 2)
        else:
            self.goTo(self.currentPage + delta)

    @Slot(str)
    def setTool(self, tool: str) -> None:  # noqa: N802
        if tool not in TOOLS:
            return
        self.tool = tool
        self.selectedObject = {}
        if tool in ("editText",):
            self.loadBlocks(self.currentPage)
        if tool == "image":
            self.loadImages(self.currentPage)
        if tool == "form":
            self.loadFields()

    # Text: Zeichentabelle, Auswahl, Kopieren ---------------------------------------------------------------------
    @Slot(int)
    def loadText(self, page: int) -> None:  # noqa: N802
        if page in self._texts or page in self._text_requests or not 0 <= page < self.pageCount:
            return
        self._text_requests.add(page)
        revision = self.revision

        def done(table) -> None:
            self._text_requests.discard(page)
            if table is not None and revision == self.revision:
                self._texts[page] = table
                self.textPages = sorted(self._texts)

        self.run(lambda session: session.page_text(page), done, refresh=False, priority=VIEW, failed=lambda _exc: self._text_requests.discard(page))

    def _index_at(self, page: int, u: float, v: float, nearest: bool) -> int:
        table = self._texts.get(page)
        if table is None:
            return -1
        best, best_distance = -1, 1e18
        for index, (u0, v0, u1, v1) in enumerate(table.boxes):
            if u1 <= u0 and v1 <= v0:
                continue
            if u0 - 1 <= u <= u1 + 1 and v0 - 1 <= v <= v1 + 1:
                return index
            if nearest:
                du = 0.0 if u0 <= u <= u1 else min(abs(u - u0), abs(u - u1))
                dv = 0.0 if v0 <= v <= v1 else min(abs(v - v0), abs(v - v1))
                distance = du * du + 4 * dv * dv  # Zeilen zählen mehr als Spalten
                if distance < best_distance:
                    best, best_distance = index, distance
        return best

    @Slot(int, float, float, float, float, result=bool)
    def selectRange(self, page: int, u0: float, v0: float, u1: float, v1: float) -> bool:  # noqa: N802
        """Auswahl von Punkt (u0, v0) bis (u1, v1) einer Seite (Anzeige-Punkte)."""
        if page not in self._texts:
            self.loadText(page)
            return False
        start = self._index_at(page, u0, v0, nearest=True)
        end = self._index_at(page, u1, v1, nearest=True)
        if start < 0 or end < 0:
            self.clear_selection()
            return False
        if end < start:
            start, end = end, start
        self._set_selection(page, start, end)
        return True

    @Slot(int, float, float, result=bool)
    def selectWord(self, page: int, u: float, v: float) -> bool:  # noqa: N802
        table = self._texts.get(page)
        if table is None:
            self.loadText(page)
            return False
        index = self._index_at(page, u, v, nearest=False)
        if index < 0:
            return False
        start = end = index
        while start > 0 and not table.spaces[start - 1]:
            start -= 1
        while end + 1 < len(table.spaces) and not table.spaces[end + 1]:
            end += 1
        self._set_selection(page, start, end)
        return True

    @Slot(int)
    def selectAll(self, page: int) -> None:  # noqa: N802
        table = self._texts.get(page)
        if table is None:
            self.loadText(page)
            return
        if table.boxes:
            self._set_selection(page, 0, len(table.boxes) - 1)

    def _set_selection(self, page: int, start: int, end: int) -> None:
        table = self._texts[page]
        self._selection = (page, start, end)
        self.selectionPage = page
        self.selectionRects = _line_rects(table.boxes[start : end + 1])

    @Slot()
    def clearSelection(self) -> None:  # noqa: N802
        self.clear_selection()

    def clear_selection(self) -> None:
        self._selection = None
        if self.selectionPage != -1:
            self.selectionPage = -1
        if self.selectionRects:
            self.selectionRects = []

    @Slot()
    def copySelection(self) -> None:  # noqa: N802
        if self._selection is None:
            return
        if not (self.permissions or {}).get("copy", True):
            self.app.notify("reader", "warning", "Die Berechtigungen dieses PDFs erlauben kein Kopieren von Text.", title="Kopieren nicht erlaubt")
            return
        page, start, end = self._selection
        self.run(lambda session: session.text(page, start, end - start + 1), lambda text: self.app.copy_text(text, "Text kopiert."), refresh=False, priority=VIEW)

    @Slot(str)
    def markSelection(self, kind: str) -> None:  # noqa: N802
        """Auswahl markieren, unterstreichen oder durchstreichen (Anmerkung)."""
        if self._selection is None or kind not in ("highlight", "underline", "strikeout") or not self.edit_allowed("annotate"):
            return
        page = self._selection[0]
        rects = [list(rect) for rect in self.selectionRects]
        color = self.markColor if kind == "highlight" else self.toolColor
        self.run(lambda session: session.markup(page, kind, rects, color, ""), lambda _key: (self.clear_selection(), self.loadAnnotations()), busy="")

    # Suche ---------------------------------------------------------------------------------------------------------
    @Slot()
    def requestSearch(self) -> None:  # noqa: N802
        self.searchFocusSerial = self.searchFocusSerial + 1

    @Slot(str, bool, bool)
    def search(self, text: str, match_case: bool, whole_word: bool) -> None:
        self.cancel_search()
        text = text.strip()
        self.searchText = text
        self.searchCase = bool(match_case)
        self.searchWords = bool(whole_word)
        self._search_hits = []
        self.hits.clear()
        self.hitRects = {}
        self.currentHit = {}
        self.searchCount = 0
        self.searchIndex = -1
        if not text:
            self.searchSummary = ""
            return
        self._search_serial += 1
        serial = self._search_serial
        self.searchRunning = True
        self.searchProgress = 0.0
        self.searchSummary = "Suche läuft …"
        total = self.pageCount
        start_page = self.currentPage
        order = list(range(start_page, total)) + list(range(0, start_page))
        engine = self.engine
        state = {"cancelled": False}
        self._search_state = state

        def work(session, first: int, found: int):
            for done in range(first, len(order)):
                if state["cancelled"] or session.closed:
                    return found, None
                page = order[done]
                hits = session.search_page(page, text, match_case, whole_word)
                excerpts = []
                if hits:
                    excerpts = _excerpts(session, page, text, match_case, whole_word, len(hits))
                found += len(hits)
                engine.post(self._search_page_done, serial, page, hits, excerpts, (done + 1) / max(1, total))
                if found >= SEARCH_LIMIT:
                    return found, None
                if done + 1 < len(order) and engine.urgent():
                    return found, done + 1  # Vorrang für Speichern, Bearbeiten und sichtbare Seiten – danach weiter
            return found, None

        def step(result) -> None:
            found, resume = result
            if resume is None:
                self._search_finished(serial, found)
            elif not state["cancelled"] and serial == self._search_serial:
                self._search_task = self.run(lambda session: work(session, resume, found), step, refresh=False, priority=BACKGROUND)

        self._search_task = self.run(lambda session: work(session, 0, 0), step, refresh=False, priority=BACKGROUND)

    def _search_page_done(self, serial: int, page: int, hits: list, excerpts: list, progress: float) -> None:
        if serial != self._search_serial:
            return
        self.searchProgress = progress
        if not hits:
            return
        rects = dict(self.hitRects)
        rects[str(page)] = [rect for hit in hits for rect in hit]
        self.hitRects = rects
        base = len(self._search_hits)
        listed = self.hits.items()
        for number, hit in enumerate(hits):
            self._search_hits.append({"page": page, "rects": hit})
            if len(listed) < LISTED_HITS:  # die Liste zeigt die ersten Treffer; F3 erreicht alle
                listed.append({"key": f"{page}-{number}", "page": page, "hit": base + number, "excerpt": excerpts[number] if number < len(excerpts) else ""})
        self.hits.set_items(listed)
        self.searchCount = len(self._search_hits)
        if self.searchIndex < 0:
            self.showHit(0)

    def _search_finished(self, serial: int, found: int) -> None:
        if serial != self._search_serial:
            return
        self.searchRunning = False
        self.searchProgress = 1.0
        if found == 0:
            self.searchSummary = f"Keine Treffer für »{self.searchText}«."
        else:
            more = " (Suche nach den ersten 5000 Treffern beendet)" if found >= SEARCH_LIMIT else ""
            self.searchSummary = f"{found} Treffer{more}"

    def cancel_search(self) -> None:
        state = getattr(self, "_search_state", None)
        if state is not None:
            state["cancelled"] = True
        self._search_serial += 1
        self.searchRunning = False

    @Slot()
    def cancelSearch(self) -> None:  # noqa: N802
        self.cancel_search()
        self.searchSummary = f"{self.searchCount} Treffer (abgebrochen)" if self.searchCount else ""

    @Slot(int)
    def showHit(self, index: int) -> None:  # noqa: N802
        if not self._search_hits:
            return
        index %= len(self._search_hits)
        hit = self._search_hits[index]
        self.searchIndex = index
        self.currentHit = {"page": hit["page"], "rects": hit["rects"]}
        first = hit["rects"][0] if hit["rects"] else [0, 0, 0, 0]
        self.currentPage = hit["page"]
        self.reveal(hit["page"], first[0], first[1])

    @Slot()
    def nextHit(self) -> None:  # noqa: N802
        self.showHit(self.searchIndex + 1)

    @Slot()
    def previousHit(self) -> None:  # noqa: N802
        self.showHit(self.searchIndex - 1 if self.searchIndex > 0 else len(self._search_hits) - 1)

    # Gliederung ------------------------------------------------------------------------------------------------
    def load_outline(self) -> None:
        def done(entries) -> None:
            self._outline_entries = []
            for index, entry in enumerate(entries):
                following = entries[index + 1] if index + 1 < len(entries) else None
                has_children = following is not None and following["level"] > entry["level"]
                self._outline_entries.append({"key": str(index), "level": entry["level"], "title": entry["title"], "page": entry["page"], "hasChildren": has_children, "expanded": bool(entry["open"]) and entry["level"] < 1})
            self.hasOutline = bool(self._outline_entries)
            self._refresh_outline()

        self.run(lambda session: session.outline(), done, refresh=False, priority=BACKGROUND)

    def _refresh_outline(self) -> None:
        items = []
        hidden_below = None
        for entry in self._outline_entries:
            if hidden_below is not None and entry["level"] > hidden_below:
                continue
            hidden_below = None
            items.append({**entry, "visible": True})
            if entry["hasChildren"] and not entry["expanded"]:
                hidden_below = entry["level"]
        self.outline.set_items(items)

    @Slot(str)
    def toggleOutline(self, key: str) -> None:  # noqa: N802
        for entry in self._outline_entries:
            if entry["key"] == key:
                entry["expanded"] = not entry["expanded"]
        self._refresh_outline()

    @Slot(str)
    def openOutline(self, key: str) -> None:  # noqa: N802
        entry = next((item for item in self._outline_entries if item["key"] == key), None)
        if entry is not None and entry["page"] >= 0:
            self.goTo(entry["page"])

    # Text bearbeiten ---------------------------------------------------------------------------------------------
    @Slot(int)
    def loadBlocks(self, page: int) -> None:  # noqa: N802
        if not 0 <= page < self.pageCount:
            return

        def done(blocks) -> None:
            self.blocksPage = page
            self.blocks = blocks

        self.run(lambda session: session.blocks(page), done, refresh=False, priority=VIEW, key="blocks")

    @Slot(int, str, str, "QVariantMap")
    def editBlock(self, page: int, block_id: str, text: str, style: dict) -> None:  # noqa: N802
        if not self.edit_allowed():
            return
        self._edit_block(page, block_id, text, "ask", dict(style or {}))

    def _edit_block(self, page: int, block_id: str, text: str, overflow: str, style: dict) -> None:
        def failed(exc: BaseException) -> None:
            if isinstance(exc, Overflow):
                answer, _data = self.app.dialogs.ask(
                    "confirm", "Der Text passt nicht in den Bereich", f"Der neue Text braucht {exc.needed} Zeilen, der bisherige Bereich hat {exc.available}.",
                    primary="Zeilen anfügen", secondary="Schrift verkleinern", close="Abbrechen",
                )
                if answer == "primary":
                    self._edit_block(page, block_id, text, "grow", style)
                elif answer == "secondary":
                    self._edit_block(page, block_id, text, "shrink", style)
                else:
                    self.loadBlocks(page)
                return
            self.report(exc)
            self.loadBlocks(page)

        def done(outcome) -> None:
            self.lastMode = outcome["label"]
            severity = "success" if outcome["mode"] == "native" else ("info" if outcome["mode"] == "reconstructed" else "warning")
            message = outcome["label"] + ("" if not outcome["notes"] else " – " + " ".join(outcome["notes"]))
            self.app.notify("reader", severity, message, title="Text geändert", auto_hide=8000 if severity != "warning" else None)
            self.loadBlocks(page)

        self.run(lambda session: session.edit_block(page, block_id, text, overflow, style), done, busy="Text wird geändert …", failed=failed)

    @Slot(int, float, float, str, "QVariantMap")
    def addText(self, page: int, u: float, v: float, text: str, style: dict) -> None:  # noqa: N802
        if not text.strip() or not self.edit_allowed():
            return
        style = dict(style or {})
        style.setdefault("size", self.fontSize)
        width = float(style.pop("width", 0) or 0) or None
        self.run(lambda session: session.add_text(page, u, v, text, style, width), lambda _outcome: self.edited("Text hinzugefügt"), busy="Text wird hinzugefügt …")

    # Bilder --------------------------------------------------------------------------------------------------
    @Slot(int)
    def loadImages(self, page: int) -> None:  # noqa: N802
        if not 0 <= page < self.pageCount:
            return

        def done(items) -> None:
            self.imagesPage = page
            self.images = items

        self.run(lambda session: session.images(page), done, refresh=False, priority=VIEW, key="images")

    def _image_op(self, page: int, func, title: str, reload: bool = True) -> None:
        if not self.edit_allowed():
            return
        self.run(func, lambda _result: (self.edited(title), self.loadImages(page) if reload else None), busy="")

    @Slot(int, int, float, float)
    def moveImage(self, page: int, index: int, du: float, dv: float) -> None:  # noqa: N802
        if abs(du) < 0.25 and abs(dv) < 0.25:
            return
        self._image_op(page, lambda session: session.move_image(page, index, du, dv), "Bild verschoben")

    @Slot(int, int, "QVariantList")
    def resizeImage(self, page: int, index: int, rect: list) -> None:  # noqa: N802
        self._image_op(page, lambda session: session.fit_image(page, index, [float(v) for v in rect]), "Bildgröße geändert")

    @Slot(int, int, bool)
    def rotateImage(self, page: int, index: int, clockwise: bool) -> None:  # noqa: N802
        self._image_op(page, lambda session: session.rotate_image(page, index, clockwise), "Bild gedreht")

    @Slot(int, int)
    def deleteImage(self, page: int, index: int) -> None:  # noqa: N802
        self.selectedObject = {}
        self._image_op(page, lambda session: session.delete_image(page, index), "Bild gelöscht")

    @Slot(int, int, bool)
    def arrangeImage(self, page: int, index: int, front: bool) -> None:  # noqa: N802
        self._image_op(page, lambda session: session.arrange_image(page, index, front), "In den Vordergrund" if front else "In den Hintergrund")

    @Slot(int, int)
    def replaceImage(self, page: int, index: int) -> None:  # noqa: N802
        path = self.reader.pick_image()
        if path:
            self._image_op(page, lambda session: session.replace_image(page, index, path), "Bild ersetzt")

    @Slot(int, "QVariantList")
    def insertImage(self, page: int, rect: list) -> None:  # noqa: N802
        """Bild aus einer Datei einfügen – ``rect`` (Anzeige-Punkte) ist der Platz; leer = mittig."""
        if not self.edit_allowed():
            return
        path = self.reader.pick_image()
        if not path:
            return
        if not rect and self.pageSizes:
            width, height = self.pageSizes[page]
            box = min(width, height) * 0.4
            rect = [(width - box) / 2, (height - box) / 2, (width + box) / 2, (height + box) / 2]
        self._fit_new_image(page, path, [float(v) for v in rect])

    def _fit_new_image(self, page: int, path: str, rect: list) -> None:
        try:
            from PIL import Image

            with Image.open(path) as image:
                ratio = image.width / max(1, image.height)
        except Exception:  # noqa: BLE001 - die Prüfung im Arbeitsthread meldet den Fehler verständlich
            ratio = 1.0
        u0, v0, u1, v1 = rect
        width, height = u1 - u0, v1 - v0
        if width / max(1e-6, height) > ratio:
            new_w = height * ratio
            u0, u1 = u0 + (width - new_w) / 2, u0 + (width + new_w) / 2
        else:
            new_h = width / ratio
            v0, v1 = v0 + (height - new_h) / 2, v0 + (height + new_h) / 2
        self.run(lambda session: session.insert_image(page, path, [u0, v0, u1, v1]), lambda _index: (self.edited("Bild eingefügt"), self.loadImages(page)), busy="Bild wird eingefügt …")

    # Kommentare ---------------------------------------------------------------------------------------------------
    @Slot()
    def loadAnnotations(self) -> None:  # noqa: N802
        def done(items) -> None:
            self.annotations = items
            by_page: dict[str, list] = {}
            for item in items:
                by_page.setdefault(str(item["page"]), []).append(item)
            self.annotationPages = by_page
            self.annotationList.set_items([{key: item[key] for key in ("key", "page", "label", "contents", "author", "modified", "color", "subtype")} for item in items])

        self.run(lambda session: session.annotations(None), done, refresh=False, priority=VIEW, key="annotations")

    def _annot_op(self, func, title: str) -> None:
        if not self.edit_allowed("annotate"):
            return
        self.run(func, lambda _result: (self.edited(title), self.loadAnnotations()), busy="")

    @Slot(int, float, float, str)
    def addNote(self, page: int, u: float, v: float, text: str) -> None:  # noqa: N802
        if text.strip():
            color = self.toolColor
            self._annot_op(lambda session: session.add_note(page, u, v, text, color), "Notiz hinzugefügt")

    @Slot(int, "QVariantList")
    def addInk(self, page: int, strokes: list) -> None:  # noqa: N802
        color, width = self.toolColor, self.strokeWidth
        cleaned = [[[float(point[0]), float(point[1])] for point in stroke] for stroke in strokes if len(stroke) >= 2]
        if cleaned:
            self._annot_op(lambda session: session.add_ink(page, cleaned, color, width), "Freihandzeichnung hinzugefügt")

    @Slot(int, str, "QVariantList")
    def addShape(self, page: int, kind: str, rect: list) -> None:  # noqa: N802
        color, width = self.toolColor, self.strokeWidth
        box = [float(v) for v in rect]
        if kind in ("rect", "ellipse"):
            shape = "square" if kind == "rect" else "circle"
            self._annot_op(lambda session: session.add_shape(page, shape, box, color, width, ""), "Form hinzugefügt")
        elif kind in ("line", "arrow"):
            self._annot_op(lambda session: session.add_line(page, (box[0], box[1]), (box[2], box[3]), kind == "arrow", color, width), "Linie hinzugefügt")

    @Slot(int, "QVariantList", str)
    def addTextbox(self, page: int, rect: list, text: str) -> None:  # noqa: N802
        if text.strip():
            color, size = self.toolColor, self.fontSize
            box = [float(v) for v in rect]
            self._annot_op(lambda session: session.add_textbox(page, box, text, color, size), "Textfeld hinzugefügt")

    @Slot(str, str, str)
    def updateAnnotation(self, key: str, contents: str, color: str) -> None:  # noqa: N802
        self._annot_op(lambda session: session.update_annotation(key, contents, color), "Kommentar geändert")

    @Slot(str, str)
    def setAnnotationColor(self, key: str, color: str) -> None:  # noqa: N802
        self._annot_op(lambda session: session.update_annotation(key, None, color), "Farbe geändert")

    @Slot(str, float, float)
    def moveAnnotation(self, key: str, du: float, dv: float) -> None:  # noqa: N802
        if abs(du) >= 0.25 or abs(dv) >= 0.25:
            self._annot_op(lambda session: session.move_annotation(key, du, dv), "Kommentar verschoben")

    @Slot(str)
    def deleteAnnotation(self, key: str) -> None:  # noqa: N802
        self.selectedObject = {}
        self._annot_op(lambda session: session.delete_annotation(key), "Kommentar gelöscht")

    # Formulare ------------------------------------------------------------------------------------------------------
    @Slot()
    def loadFields(self) -> None:  # noqa: N802
        def done(items) -> None:
            self.fields = items
            by_page: dict[str, list] = {}
            for item in items:
                for number, widget in enumerate(item["widgets"]):
                    on_values = item["onValues"]
                    entry = {key: item[key] for key in ("key", "name", "kind", "value", "options", "multiline", "maxLength", "editable", "reason", "required")}
                    entry["view"] = widget["view"]
                    # Optionsfeld: Wert dieses Knopfes; Kontrollkästchen: sein »Ein«-Wert
                    entry["onValue"] = on_values[number] if number < len(on_values) else (on_values[0] if on_values else "")
                    by_page.setdefault(str(widget["page"]), []).append(entry)
            self.fieldPages = by_page

        self.run(lambda session: session.fields(), done, refresh=False, priority=VIEW, key="fields")

    @Slot(str, "QVariant")
    def setField(self, key: str, value) -> None:  # noqa: N802
        if not self.edit_allowed("fill_forms"):
            self.loadFields()
            return
        self.run(lambda session: session.set_field(key, value), lambda _result: self.loadFields(), busy="", failed=lambda exc: (self.report(exc), self.loadFields()))

    # Seiten -----------------------------------------------------------------------------------------------------------
    def _page_op(self, func, title: str, done: Callable[[Any], None] | None = None) -> None:
        if not self.edit_allowed("assemble"):
            return

        def finished(result) -> None:
            self.edited(title)
            if isinstance(result, list) and result and all(isinstance(note, str) for note in result):
                self.app.notify("reader", "info", " ".join(result), title=title, auto_hide=10000)
            if done is not None:
                done(result)
            self.loadAnnotations()

        self.run(func, finished, busy=title + " …")

    @Slot("QVariantList", int)
    def rotatePages(self, indexes: list, degrees: int) -> None:  # noqa: N802
        chosen = [int(i) for i in indexes] or [self.currentPage]
        self._page_op(lambda session: session.rotate_pages(chosen, degrees), "Seiten gedreht" if len(chosen) > 1 else "Seite gedreht")

    @Slot("QVariantList")
    def deletePages(self, indexes: list) -> None:  # noqa: N802
        chosen = sorted({int(i) for i in indexes} or {self.currentPage})
        if len(chosen) >= self.pageCount:
            self.app.notify("reader", "warning", "Mindestens eine Seite muss im Dokument bleiben.", title="Nicht möglich")
            return
        label = f"Seite {chosen[0] + 1}" if len(chosen) == 1 else f"{len(chosen)} Seiten"
        if not self.app.dialogs.confirm(f"{label} löschen?", "Die Seiten werden aus dem Dokument entfernt. Mit »Rückgängig« (Strg+Z) lassen sie sich zurückholen, solange das Dokument offen ist.", "Löschen"):
            return
        self._page_op(lambda session: session.delete_pages(chosen), "Seiten gelöscht" if len(chosen) > 1 else "Seite gelöscht")

    @Slot("QVariantList")
    def duplicatePages(self, indexes: list) -> None:  # noqa: N802
        chosen = [int(i) for i in indexes] or [self.currentPage]
        self._page_op(lambda session: session.duplicate_pages(chosen), "Seiten dupliziert" if len(chosen) > 1 else "Seite dupliziert")

    @Slot(int)
    def insertBlankPage(self, index: int) -> None:  # noqa: N802
        self._page_op(lambda session: session.insert_blank(index), "Leere Seite eingefügt", lambda _r: self.goTo(index))

    @Slot("QVariantList", int)
    def movePages(self, indexes: list, target: int) -> None:  # noqa: N802
        chosen = [int(i) for i in indexes]
        if chosen:
            self._page_op(lambda session: session.move_pages(chosen, target), "Seiten verschoben" if len(chosen) > 1 else "Seite verschoben")

    @Slot(int)
    def insertFromFile(self, index: int) -> None:  # noqa: N802
        path = self.reader.pick_pdf("Seiten aus PDF einfügen")
        if path:
            self._insert_file(index, path, None)

    def _insert_file(self, index: int, path: str, password: str | None) -> None:
        if not self.edit_allowed("assemble"):
            return

        def failed(exc: BaseException) -> None:
            if isinstance(exc, PasswordRequired):
                secret = self.reader.ask_password(path, exc.wrong)
                if secret is not None:
                    self._insert_file(index, path, secret)
                return
            self.report(exc)

        def done(notes) -> None:
            self.edited("Seiten eingefügt")
            if notes:
                self.app.notify("reader", "info", " ".join(notes), title="Seiten eingefügt", auto_hide=10000)

        self.run(lambda session: session.insert_file(index, path, password), done, busy="Seiten werden eingefügt …", failed=failed)

    @Slot()
    def mergeFiles(self) -> None:  # noqa: N802
        paths = self.reader.pick_pdfs("PDFs anhängen")
        if paths:
            self._page_op(lambda session: session.merge_files(paths), "PDFs angehängt")

    @Slot("QVariantList")
    def extractPages(self, indexes: list) -> None:  # noqa: N802
        chosen = sorted({int(i) for i in indexes}) or [self.currentPage]
        target = self.reader.pick_save_pdf(f"{self._stem()}_Auszug.pdf", "Seiten als neue PDF speichern")
        if target:
            self.run(lambda session: session.extract(chosen, target), lambda path: self.app.notify("reader", "success", f"{len(chosen)} Seite(n) gespeichert: {path}", title="Neue PDF erstellt", auto_hide=8000), refresh=False, busy="Seiten werden gespeichert …")

    @Slot(str)
    def splitDocument(self, spec: str) -> None:  # noqa: N802
        """Teilen: »2« = alle 2 Seiten, sonst Bereiche wie »1-3; 4-6« (leer: nachfragen)."""
        from tools.pdf_editor import pages as page_ops

        spec = (spec or "").strip()
        if not spec:
            answer, data = self.app.dialogs.ask(
                "text_input", "Dokument teilen", f"Das Dokument hat {self.pageCount} Seiten. Jeder Teil wird eine eigene PDF; das Original bleibt unverändert.",
                primary="Weiter", close="Abbrechen",
                data={"label": "Teilen nach", "value": "1" if self.pageCount > 1 else "", "placeholder": "z. B. 2 oder 1-3; 4-6", "hint": "Eine Zahl teilt alle n Seiten (1 = jede Seite einzeln). Bereiche mit Semikolon trennen, z. B. »1-3; 4-6«."},
            )
            if answer != "primary":
                return
            spec = str(data.get("value") or "").strip()
            if not spec:
                return
        try:
            if spec.isdigit():
                ranges = page_ops.every(self.pageCount, int(spec))
            else:
                ranges = [page_ops.parse_pages(part, self.pageCount) for part in spec.split(";") if part.strip()]
        except ValueError as exc:
            self.app.notify("reader", "warning", str(exc), title="Teilen nicht möglich")
            return
        if not ranges:
            return
        folder = self.reader.pick_folder("Ordner für die Teile")
        if not folder:
            return
        stem = self._stem()
        self.run(lambda session: session.split(ranges, folder, stem), lambda written: self.app.notify("reader", "success", f"{len(written)} Dateien in {folder}", title="Dokument geteilt", auto_hide=8000), refresh=False, busy="Dokument wird geteilt …")

    def _stem(self) -> str:
        name = self.name or "Dokument.pdf"
        return name[:-4] if name.lower().endswith(".pdf") else name

    # Export, Eigenschaften ---------------------------------------------------------------------------------------
    @Slot("QVariantList", str, int)
    def exportImages(self, indexes: list, fmt: str, dpi: int) -> None:  # noqa: N802
        chosen = sorted({int(i) for i in indexes}) or list(range(self.pageCount))
        folder = self.reader.pick_folder("Ordner für die Bilder")
        if not folder:
            return
        stem = self._stem()
        self.run(lambda session: session.export_images(chosen, folder, stem, fmt, dpi), lambda written: self.app.notify("reader", "success", f"{len(written)} Bild(er) gespeichert in {folder}", title="Exportiert", auto_hide=8000), refresh=False, busy="Seiten werden exportiert …")

    @Slot()
    def showProperties(self) -> None:  # noqa: N802
        def done(props) -> None:
            editable = not self.readOnlyReason and (self.permissions or {}).get("edit", True)
            answer, data = self.app.dialogs.ask("reader_properties", "Eigenschaften", "", primary="Übernehmen" if editable else "", close="Schließen", default="close" if not editable else "primary", data={"props": props, "editable": editable}, width=640)
            if answer == "primary" and not self.readOnlyReason:
                values = {key: data.get(key) for key in ("title", "author", "subject", "keywords")}
                if any(values.get(key) != props.get(key) for key in values) and self.edit_allowed():
                    self.run(lambda session: session.set_metadata(values), lambda _r: self.edited("Eigenschaften geändert"))

        self.run(lambda session: session.properties(), done, refresh=False, busy="")

    # Rückgängig, Speichern ------------------------------------------------------------------------------------------
    @Slot()
    def undo(self) -> None:
        if self.undoText:
            self.run(lambda session: session.undo(), lambda title: (self.edited(f"Rückgängig: {title}" if title else ""), self._reload_tool()))

    @Slot()
    def redo(self) -> None:
        if self.redoText:
            self.run(lambda session: session.redo(), lambda title: (self.edited(f"Wiederholt: {title}" if title else ""), self._reload_tool()))

    def _reload_tool(self) -> None:
        if self.tool == "editText":
            self.loadBlocks(self.blocksPage if self.blocksPage >= 0 else self.currentPage)
        elif self.tool == "image":
            self.loadImages(self.imagesPage if self.imagesPage >= 0 else self.currentPage)
        elif self.tool == "form":
            self.loadFields()
        self.loadAnnotations()

    def save(self, target: str | None = None, *, force: bool = False, then: Callable[[bool], None] | None = None) -> None:
        """Speichern (``target`` = Speichern unter). ``then(erfolgreich)`` danach.

        Je Dokument läuft höchstens ein Speichervorgang. Anfragen währenddessen (mehrfaches Strg+S,
        »Speichern« beim Schließen) werden zu einer zusammengefasst und danach ausgeführt – nach
        einem Fehler nur »Speichern unter«, ein einfaches Speichern nicht noch einmal."""
        if self.saving:
            queued = self._save_next or {"target": None, "force": False, "then": []}
            if target:
                queued["target"] = target
            queued["force"] = force
            if then is not None:
                queued["then"].append(then)
            self._save_next = queued
            return
        if not target and not self.path:
            target = self.reader.pick_save_pdf(self.name or "Dokument.pdf", "Speichern unter")
            if not target:
                if then:
                    then(False)
                self._next_save(False)
                return
        self.saving = True
        self.saveState = "saving"
        self.app.timers.cancel(f"reader:saved:{self.ident}")
        started = time.monotonic()

        def failed(exc: BaseException) -> None:
            self.saving = False
            self.saveState = ""
            if isinstance(exc, ExternalChange):
                retry = self._ask_overwrite(target)
                if retry is not None:
                    self.save(retry[0], force=retry[1], then=then)
                    return
            else:
                self._report_save_error(exc)
            if then:
                then(False)
            self._next_save(False)

        def done(result) -> None:
            self.saving = False
            self.saveState = "saved"
            self.app.timers.later(f"reader:saved:{self.ident}", SAVED_SHOWN_MS, self._saved_shown)
            self.app.timers.cancel(f"reader:recovery:{self.ident}")
            if result.get("unchanged"):
                self.app.set_status(f"Keine Änderungen – »{result['name']}« ist gespeichert.", "success")
            else:
                backup = " – Sicherung des vorherigen Stands angelegt" if result.get("backup") else ""
                self.app.set_status(f"Gespeichert: {result['name']}{backup}", "success")
                _log().info("Gespeichert (%s): %d KB, %d Seiten geprüft, Sicherung %s, %d ms", _where(result["path"]), max(1, result["size"] // 1024), result["checked"], "ja" if result.get("backup") else "nein", (time.monotonic() - started) * 1000)
                self.reader.remember_recent(result["path"])
            if then:
                then(True)
            self._next_save(True)

        self.run(lambda session: session.save(target, force=force), done, busy="Wird gespeichert und geprüft …", failed=failed, key="save")

    def _next_save(self, ok: bool) -> None:
        """Nach dem Speichern: eine wartende Anfrage ausführen (zusammengefasst)."""
        queued, self._save_next = self._save_next, None
        if queued is None or self._closing:
            return
        callbacks = queued["then"]

        def then(result: bool) -> None:
            for callback in callbacks:
                callback(result)

        if queued["target"] or ok:
            # Einfaches Speichern: der Arbeitsthread speichert nur, wenn es noch Änderungen gibt
            self.save(queued["target"], force=queued["force"], then=then if callbacks else None)
        else:
            then(False)

    def _saved_shown(self) -> None:
        if self.saveState == "saved":
            self.saveState = ""

    def _ask_overwrite(self, target: str | None) -> tuple[str | None, bool] | None:
        """Datei wurde von außen geändert: überschreiben (``(Ziel, True)``), unter neuem Namen
        (``(neues Ziel, False)``) oder abbrechen (``None``)."""
        answer, _data = self.app.dialogs.ask("confirm", "Datei wurde von außen geändert", "Die Datei wurde seit dem Öffnen von einem anderen Programm verändert. Überschreiben oder unter neuem Namen speichern?", primary="Überschreiben", secondary="Speichern unter …", close="Abbrechen", danger=True)
        if answer == "primary":
            return target, True
        if answer == "secondary":
            other = self.reader.pick_save_pdf(self.name, "Speichern unter")
            if other:
                return other, False
        return None

    def _report_save_error(self, exc: BaseException) -> None:
        """Speicherfehler: verständlicher Text (bei Bedarf mit »Speichern unter …«), technische
        Angaben ins Protokoll – ohne Pfad und ohne Inhalte. Der ungespeicherte Stand bleibt."""
        where = _where(self.path)
        if isinstance(exc, SaveFailed):
            _log().warning("Speichern fehlgeschlagen (%s): %s", where, exc.log_text())
            actions = [("Speichern unter …", self.saveDocumentAs)] if exc.save_as else []
            self.app.notify("reader", "error", str(exc), title="Speichern nicht möglich", actions=actions)
            return
        if isinstance(exc, (EditorError, OSError)):
            _log().warning("Speichern fehlgeschlagen (%s): %s%s", where, type(exc).__name__, _os_codes(exc))
            message = str(exc) if isinstance(exc, EditorError) else f"Die Datei konnte nicht geschrieben werden ({exc.strerror or 'Ein-/Ausgabefehler'}). Die Originaldatei ist unverändert."
            self.app.notify("reader", "error", message, title="Speichern nicht möglich", actions=[("Speichern unter …", self.saveDocumentAs)])
            return
        self.report(exc, self._failure_details or "".join(traceback.format_exception(exc)))  # unerwartet: Traceback in fehler.log

    @Slot()
    def saveDocument(self) -> None:  # noqa: N802
        self.save()

    @Slot()
    def saveDocumentAs(self) -> None:  # noqa: N802
        target = self.reader.pick_save_pdf(self.name or "Dokument.pdf", "Speichern unter")
        if target:
            self.save(target)

    def write_recovery_now(self) -> None:
        self.app.timers.cancel(f"reader:recovery:{self.ident}")
        self._write_recovery()

    def _write_recovery(self) -> None:
        if self.dirty and not self._closing:
            self.run(lambda session: session.write_recovery(), None, refresh=False, priority=BACKGROUND, failed=self._recovery_failed, key="recovery")

    def _recovery_failed(self, exc: BaseException) -> None:
        # Die Sitzungssicherung ist Hintergrundarbeit: kein Hinweis, aber nie stillschweigend verloren
        _log().warning("Sitzungssicherung fehlgeschlagen (%s): %s%s", _where(self.path), type(exc).__name__, _os_codes(exc))

    # Drucken ------------------------------------------------------------------------------------------------------
    @Slot()
    def printDocument(self) -> None:  # noqa: N802
        if not (self.permissions or {}).get("print", True):
            self.app.notify("reader", "warning", "Die Berechtigungen dieses PDFs erlauben kein Drucken.", title="Drucken nicht erlaubt")
            return
        from .printing import print_document

        print_document(self)

    @Slot()
    def previewPrint(self) -> None:  # noqa: N802
        if not (self.permissions or {}).get("print", True):
            self.app.notify("reader", "warning", "Die Berechtigungen dieses PDFs erlauben kein Drucken.", title="Drucken nicht erlaubt")
            return
        from .printing import preview_document

        preview_document(self)

    # Schließen ------------------------------------------------------------------------------------------------------
    def shutdown(self, discard_recovery: bool) -> None:
        self._closing = True
        self.cancel_search()
        self.app.timers.cancel(f"reader:recovery:{self.ident}")
        for task in self._pending.values():
            task.cancel()

        def close(session) -> None:
            if session is None:
                return
            if discard_recovery:
                session.discard_recovery()
            session.close()

        self.engine.submit(lambda: close(self.session), priority=EDIT, label="schließen")
        self.closed.emit()


def _line_rects(boxes: list) -> list[list[float]]:
    """Zeichenrechtecke zu Zeilenrechtecken zusammenfassen (für die Anzeige der Auswahl)."""
    lines: list[list[float]] = []
    for u0, v0, u1, v1 in boxes:
        if u1 <= u0 or v1 <= v0:
            continue
        if lines:
            last = lines[-1]
            same_line = abs((v0 + v1) / 2 - (last[1] + last[3]) / 2) < max(2.0, (v1 - v0) * 0.5) and u0 >= last[0] - 2
            if same_line:
                last[0], last[1], last[2], last[3] = min(last[0], u0), min(last[1], v0), max(last[2], u1), max(last[3], v1)
                continue
        lines.append([u0, v0, u1, v1])
    return lines


def _excerpts(session, page: int, query: str, match_case: bool, whole_word: bool, count: int) -> list[str]:
    """Kurzer Textausschnitt um jeden Treffer (für die Trefferliste – nie protokolliert)."""
    from tools.pdf_editor import textlayer

    result = []
    for hit in textlayer.search(session.document, page, query, match_case=match_case, whole_word=whole_word, limit=count):
        before = max(0, hit.start - 30)
        text = textlayer.text(session.document, page, before, hit.count + (hit.start - before) + 30)
        result.append(" ".join(text.split()))
    return result


def _log():
    from diagnostics.applog import get

    return get("reader")


def _where(path: str | None) -> str:
    """Datei fürs Protokoll – ohne Namen und Ordner: Endung und eine Kurzkennung des Pfads (gleiche
    Datei → gleiche Kennung)."""
    if not path:
        return "ohne Speicherort"
    key = hashlib.sha256(os.path.normcase(os.path.abspath(str(path))).encode("utf-8", "replace")).hexdigest()[:8]
    return f"*{os.path.splitext(str(path))[1].lower() or '.pdf'} #{key}"


def _os_codes(exc: BaseException) -> str:
    if not isinstance(exc, OSError):
        return ""
    codes = [f"errno={exc.errno}"] if exc.errno is not None else []
    if getattr(exc, "winerror", None) is not None:
        codes.append(f"WinError={exc.winerror}")
    return " · " + " · ".join(codes) if codes else ""
