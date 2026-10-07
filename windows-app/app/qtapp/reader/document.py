"""Ein geöffnetes Dokument in der Oberfläche (in QML: ``Reader.current``).

Hält, was QML anzeigt (Seitengrößen, Zoom, aktuelle Seite, Auswahl, Treffer, Blöcke, Bilder,
Kommentare, Formularfelder, Rückgängig-Titel) und schickt jede Arbeit an den Arbeitsthread
(``engine.Engine``). Koordinaten sind Anzeige-Punkte je Seite; QML multipliziert mit ``scale``.
"""

from __future__ import annotations

import hashlib
import itertools
import os
import threading
import time
import traceback
from collections import Counter
from typing import Any, Callable

from PySide6.QtCore import Property, QObject, Signal, Slot

from tools.pdf_editor.errors import EditorError, ExternalChange, Overflow, PasswordRequired, ReadOnlyDocument, SaveFailed, UnsupportedEdit

from ..base import Observable, prop
from ..models import KeyedListModel
from .engine import BACKGROUND, EDIT, VIEW, Engine, Task

PT_TO_PX = 96 / 72  # 100 % = Originalgröße bei 96 dpi
ZOOM_STEPS = (25, 33, 50, 67, 75, 100, 125, 150, 200, 300, 400)
ZOOM_MIN, ZOOM_MAX = 10.0, 800.0
PAGE_GAP = 12  # Abstand der Seiten (geräteunabhängige Pixel)
VIEW_MARGIN = 16
VIEW_MODES = ("continuous", "single", "two", "continuousTwo")
TOOLS = ("select", "hand", "editText", "objects", "addText", "image", "highlight", "underline", "strikeout", "note", "ink", "rect", "ellipse", "line", "arrow", "textbox", "form", "formDesign", "redact", "stamp", "signature", "link")
ACTIONS = ("optimize", "redact", "redactSearch", "protect", "watermark", "headerFooter", "clean", "flatten", "sign", "stamp", "crop")  # Schnellwerkzeuge der Startseite
SIGNATURE_FILE = "unterschriften.json"  # gespeicherte Unterschriften (nur lokal, nur auf Wunsch)
MM = 72 / 25.4
RECOVERY_DELAY_MS = 4000
LINKS_DELAY_MS = 250  # nach einer Änderung: Links gesammelt neu lesen
SAVED_SHOWN_MS = 2500  # »Gespeichert« so lange in der Werkzeugleiste
NUDGE_DELAY_MS = 350  # Pfeiltasten: so lange sammeln, dann ein Schritt (eine Änderung, ein Rückgängig)
SCAN_CHECK_PAGES = 10  # nach dem Öffnen: so viele Seiten auf Scans ohne Text prüfen
ANNOTATION_ROLES = ("key", "page", "label", "contents", "author", "modified", "color", "subtype", "replyTo", "depth", "ours", "width", "fill", "opacity", "fontSize", "resizable")
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
    scanHintChanged, scanHint = prop(bool, "scanHint", False)  # gescannte Seiten ohne Text (Texterkennung anbieten)
    # Texterkennung (OCR) im Hintergrund: läuft, erledigte und zu erkennende Seiten, Zustandstext
    ocrRunningChanged, ocrRunning = prop(bool, "ocrRunning", False)
    ocrDoneChanged, ocrDone = prop(int, "ocrDone", 0)
    ocrTotalChanged, ocrTotal = prop(int, "ocrTotal", 0)
    ocrStatusChanged, ocrStatus = prop(str, "ocrStatus", "")
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
    # Formular gestalten: Widgets je Seite (mit allen Eigenschaften), das gewählte, anzulegende Feldart
    designPagesChanged, designPages = prop(dict, "designPages", {})
    fieldSelectionChanged, fieldSelection = prop(dict, "fieldSelection", {})
    formKindChanged, formKind = prop(str, "formKind", "")  # "" = auswählen, sonst text, checkbox, radio, combo, list
    annotationsChanged, annotations = prop(list, "annotations", [])
    annotationPagesChanged, annotationPages = prop(dict, "annotationPages", {})  # Seite (Text) → Kommentare
    selectedObjectChanged, selectedObject = prop(dict, "selectedObject", {})  # {kind: image|annotation, page, index|key, view}
    # Objekt bearbeiten: Objekte je Seite (Text: {segments, images, message}) und Auswahl (eine Seite)
    objectPagesChanged, objectPages = prop(dict, "objectPages", {})
    objectSelectionChanged, objectSelection = prop(list, "objectSelection", [])  # [{id, kind: text|word|image, page, view, …}]
    objectMessageChanged, objectMessage = prop(str, "objectMessage", "")  # z. B. »kein bearbeitbarer Text« der aktuellen Seite
    lastModeChanged, lastMode = prop(str, "lastMode", "")  # Weg der letzten Textänderung (ehrlich benannt)
    # Farben und Stärken der Werkzeuge
    toolColorChanged, toolColor = prop(str, "toolColor", "#E53935")
    markColorChanged, markColor = prop(str, "markColor", "#FFEB3B")
    strokeWidthChanged, strokeWidth = prop(float, "strokeWidth", 2.0)
    fontSizeChanged, fontSize = prop(float, "fontSize", 12.0)
    hasOutlineChanged, hasOutline = prop(bool, "hasOutline", False)
    attachmentCountChanged, attachmentCount = prop(int, "attachmentCount", 0)
    # Schwärzen: markierte Bereiche je Seite (noch nicht angewendet) und wie markiert wird (Bereich oder Text)
    redactMarksChanged, redactMarks = prop(dict, "redactMarks", {})  # Seite (Text) → [{id, page, view}]
    redactCountChanged, redactCount = prop(int, "redactCount", 0)
    redactModeChanged, redactMode = prop(str, "redactMode", "area")
    # Links je Seite (Anzeige-Punkte): Ziel Seite (target ≥ 0) oder Webadresse (uri)
    linkPagesChanged, linkPages = prop(dict, "linkPages", {})
    # Stempel (Vorgabe oder eigener Text, zweite Zeile) und Unterschriften (gespeicherte und die aktuelle)
    stampPresetChanged, stampPreset = prop(str, "stampPreset", "genehmigt")
    stampTextChanged, stampText = prop(str, "stampText", "")
    stampSubtitleChanged, stampSubtitle = prop(str, "stampSubtitle", "{datum}")
    signaturesChanged, signatures = prop(list, "signatures", [])  # [{id, label, preview, aspect, stored}]
    signatureChoiceChanged, signatureChoice = prop(str, "signatureChoice", "")

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
        self._annotation_list = KeyedListModel(ANNOTATION_ROLES, key="key", parent=self)
        self._attachment_list = KeyedListModel(("key", "name", "description", "sizeText", "modified", "page", "openable"), key="key", parent=self)
        # Seitenleisten und »Seiten organisieren« dieses Tabs (ReaderController übernimmt sie beim Wechsel)
        self.panels: dict = {}
        self._outline_entries: list[dict] = []
        self._texts: dict[int, Any] = {}  # Seite → PageText (Zeichentabelle)
        self._text_requests: set[int] = set()
        self._select_all_pending: set[int] = set()  # »Alles auswählen«, sobald die Textschicht da ist
        self._selection: tuple[int, int, int] | None = None  # Seite, Anfang, Ende (einschließlich)
        self._search_task: Task | None = None
        self._search_hits: list[dict] = []
        self._search_serial = 0
        self._viewport = (900.0, 700.0, 1.0)
        self._pending: dict[str, Task] = {}
        self._save_next: dict | None = None  # Speicheranfrage während eines laufenden Speicherns
        self._object_requests: set[int] = set()
        self._reselect: dict[int, list[list[float]]] = {}  # nach einer Änderung: Auswahl an diesen Stellen wiederfinden
        self._paste_select: dict[int, tuple[list[float], list]] = {}  # nach dem Einfügen: Bereich, Objekte davor
        self._ocr_cancel: threading.Event | None = None  # Abbrechen der laufenden Texterkennung
        self._nudge = [0.0, 0.0]  # gesammelte Pfeiltasten-Verschiebung (Anzeige-Punkte)
        self._field_nudge = [0.0, 0.0]  # dasselbe für ein Formularfeld (Formular gestalten)
        self._select_field = ""  # nach dem Neuladen auswählen (neu angelegtes oder dupliziertes Feld)
        self._failure_details = ""  # Traceback des zuletzt fehlgeschlagenen Auftrags (Protokoll)
        self._mark_serial = 0  # Kennungen der Schwärzungsbereiche
        self._links_requested = False  # Links (für Anklicken und das Link-Werkzeug) schon angefragt
        self._links_revision = -1  # Stand, zu dem die Links zuletzt angefragt wurden
        self._select_annotation = ""  # nach dem Neuladen der Kommentare auswählen (gerade gesetzter Stempel)
        self._closing = False
        self.state: dict = {}
        self.observe("currentPage", self._page_shown)

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

    def _attachments_model(self) -> KeyedListModel:
        return self._attachment_list

    def _stamp_presets(self) -> list:
        from tools.pdf_editor import stamps

        return [{"key": key, "label": text, "color": "#%02X%02X%02X" % color} for key, (text, color, _name) in stamps.PRESETS.items()]

    _constant = Signal()
    stampPresets = Property(list, _stamp_presets, notify=_constant)  # [{key, label, color}]
    pageGap = Property(int, _gap, notify=_constant)
    docId = Property(str, _ident, notify=_constant)
    outline = Property(QObject, _outline_model, notify=_constant)  # Lesezeichen (sichtbare Einträge)
    hits = Property(QObject, _hits_model, notify=_constant)  # Trefferliste der Suche
    annotationList = Property(QObject, _annotations_model, notify=_constant)  # Kommentare aller Seiten
    attachmentList = Property(QObject, _attachments_model, notify=_constant)  # Anhänge (Dokument und Seiten)

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
            if self.objectPages:
                self.objectPages = {}
                self.objectSelection = []
            if self.tool == "objects":
                self._load_visible_objects()
            if self.searchCount:
                self.hitRects = {}
                self.currentHit = {}
                self.hits.clear()
                self.searchCount = 0
                self.searchIndex = -1
                self.searchSummary = "Das Dokument wurde geändert – bitte erneut suchen."
        changed = state["revision"] != self._links_revision
        self._links_revision = state["revision"]
        if changed or not self._links_requested:
            self._links_requested = True
            self.app.timers.later(f"reader:links:{self.ident}", LINKS_DELAY_MS, self.loadLinks)
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
        if self.ocrRunning:
            self.app.notify("reader", "info", "Bitte warten, bis die Texterkennung fertig ist – oder sie abbrechen.", title="Texterkennung läuft", auto_hide=6000)
            return False
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
        if tool != "objects" and self.objectSelection:
            self.objectSelection = []  # Objektmodus verlassen: keine alte Auswahl stehen lassen
        if tool != "formDesign":
            self.fieldSelection = {}
            self.formKind = ""
        self.tool = tool
        self.selectedObject = {}
        if tool == "formDesign":
            self.loadDesign()
        if tool == "objects":
            self._load_visible_objects()
        if tool in ("editText",):
            self.loadBlocks(self.currentPage)
        if tool == "image":
            self.loadImages(self.currentPage)
        if tool == "form":
            self.loadFields()
        if tool == "signature":
            self._load_signatures(ask=True)
        if tool == "link":
            self.loadLinks()

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
                if page in self._select_all_pending:
                    self._select_all_pending.discard(page)
                    self._select_whole(page)

        def failed(_exc) -> None:
            self._text_requests.discard(page)
            self._select_all_pending.discard(page)

        self.run(lambda session: session.page_text(page), done, refresh=False, priority=VIEW, failed=failed)

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
        if page in self._texts:
            self._select_whole(page)
        elif 0 <= page < self.pageCount:
            # Textschicht noch nicht geladen (z. B. nach einer Änderung): auswählen, sobald sie da ist
            self._select_all_pending.add(page)
            self.loadText(page)

    def _select_whole(self, page: int) -> None:
        table = self._texts.get(page)
        if table is not None and table.boxes:
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
        self._select_all_pending.clear()  # eine neue Auswahl, ein Klick oder eine Änderung ersetzt die Bitte
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

    # Objekt bearbeiten ------------------------------------------------------------------------------------------
    def _page_shown(self, page: int) -> None:
        """Neue aktuelle Seite (Scrollen, Sprung, Blättern). Seitenweise mit »Ganze Seite«: die neue Seite
        einpassen. Fortlaufend bleibt der Zoom – sonst wechselt das Einpassen bei unterschiedlich großen
        Seiten selbst die aktuelle Seite, und die Ansicht springt hin und her. Im Objektmodus: Hinweis der
        Seite zeigen, sie und die Nachbarn analysieren."""
        if self.fit == "page" and self.viewMode in ("single", "two"):
            self._apply_fit()
        if self.tool == "objects":
            self.objectMessage = (self.objectPages.get(str(page)) or {}).get("message", "")
            self._load_visible_objects()

    def _load_visible_objects(self) -> None:
        """Aktuelle Seite zuerst, dann die Nachbarn – nie alle Seiten auf einmal."""
        for page in (self.currentPage, self.currentPage + 1, self.currentPage - 1):
            if 0 <= page < self.pageCount:
                self.loadObjects(page)

    @Slot(int)
    def loadObjects(self, page: int) -> None:  # noqa: N802
        if not 0 <= page < self.pageCount or page in self._object_requests:
            return
        known = self.objectPages.get(str(page))
        if known is not None and known.get("revision") == self.revision:
            return
        self._object_requests.add(page)

        def done(data) -> None:
            self._object_requests.discard(page)
            if data.get("revision") != self.revision:
                if self.tool == "objects":
                    self.loadObjects(page)  # inzwischen geändert: neu analysieren
                return
            pages = dict(self.objectPages)
            pages[str(page)] = data
            self.objectPages = pages
            if page == self.currentPage:
                self.objectMessage = data.get("message", "")
            self._restore_selection(page)

        self.run(lambda session: session.objects(page), done, refresh=False, priority=VIEW, failed=lambda _exc: self._object_requests.discard(page))

    def _object_items(self, page: int) -> list[dict]:
        data = self.objectPages.get(str(page)) or {}
        return [*data.get("segments", []), *data.get("images", []), *data.get("paths", [])]

    def _find_object(self, page: int, ident: str) -> dict | None:
        for item in self._object_items(page):
            if item["id"] == ident:
                return {**item, "page": page}
            for word in item.get("words", []):
                if word["id"] == ident:
                    return {**item, "id": word["id"], "kind": "word", "text": word["text"], "view": word["view"], "segment": item["id"], "page": page}
        return None

    def _restore_selection(self, page: int) -> None:
        """Nach einer Änderung dieselben Stellen wieder auswählen (die Kennungen sind dann neu). Nach dem
        Einfügen: alle Objekte im eingefügten Bereich, die es vorher nicht gab."""
        pasted = self._paste_select.pop(page, None)
        if pasted is not None:
            self._reselect.pop(page, None)
            area, before = pasted
            known = {(kind, tuple(view)) for kind, view in before}
            fresh = [{**item, "page": page} for item in self._object_items(page) if area and _overlap(item["view"], area) >= 0.6 and (item["kind"], tuple(round(value, 1) for value in item["view"])) not in known]
            self.objectSelection = fresh
            return
        wanted = self._reselect.pop(page, None)
        if not wanted:
            return
        chosen = []
        for rect in wanted:
            best, best_overlap = None, 0.0
            for item in self._object_items(page):
                overlap = _overlap(item["view"], rect)
                if overlap > best_overlap:
                    best, best_overlap = item, overlap
            if best is not None and best_overlap >= 0.3 and all(item["id"] != best["id"] for item in chosen):
                chosen.append({**best, "page": page})
        self.objectSelection = chosen

    @Slot(int, str, bool)
    def selectObject(self, page: int, ident: str, additive: bool = False) -> None:  # noqa: N802
        item = self._find_object(page, ident)
        if item is None:
            return
        current = [entry for entry in self.objectSelection if entry["page"] == page] if additive else []
        if additive and any(entry["id"] == ident for entry in current):
            self.objectSelection = [entry for entry in current if entry["id"] != ident]
            return
        # Ein Wort und sein Segment schließen sich aus (keine überlappende Auswahl)
        family = item.get("segment", item["id"])
        current = [entry for entry in current if entry.get("segment", entry["id"]) != family]
        self.objectSelection = [*current, item]

    @Slot(int, "QVariantList", bool)
    def selectObjectsIn(self, page: int, rect, additive: bool = False) -> None:  # noqa: N802
        """Auswahlrechteck: alle Objekte, die überwiegend darin liegen."""
        area = [float(value) for value in rect]
        found = [{**item, "page": page} for item in self._object_items(page) if _overlap(item["view"], area) >= 0.6]
        current = [entry for entry in self.objectSelection if entry["page"] == page] if additive else []
        known = {entry["id"] for entry in current}
        self.objectSelection = current + [item for item in found if item["id"] not in known]

    @Slot(int)
    def selectAllObjects(self, page: int) -> None:  # noqa: N802
        """Strg+A im Objektmodus: alle Objekte der Seite (Segmente, Bilder)."""
        items = self._object_items(page)
        if items:
            self.objectSelection = [{**item, "page": page} for item in items]
        elif 0 <= page < self.pageCount:
            self.loadObjects(page)

    @Slot()
    def clearObjectSelection(self) -> None:  # noqa: N802
        self.objectSelection = []

    @Slot(int)
    def selectNextObject(self, step: int) -> None:  # noqa: N802
        """Tab / Umschalt+Tab: nächstes bzw. voriges Objekt der Seite (Lesereihenfolge)."""
        page = self.objectSelection[0]["page"] if self.objectSelection else self.currentPage
        items = self._object_items(page)
        if not items:
            return
        ids = [item["id"] for item in items]
        current = self.objectSelection[-1].get("segment", self.objectSelection[-1]["id"]) if self.objectSelection else None
        index = (ids.index(current) + step) % len(ids) if current in ids else (0 if step > 0 else len(ids) - 1)
        self.objectSelection = [{**items[index], "page": page}]

    def _selected(self, kinds=("text", "word")) -> tuple[int, list[dict]]:
        chosen = [entry for entry in self.objectSelection if entry["kind"] in kinds]
        return (chosen[0]["page"] if chosen else -1), chosen

    def _chosen(self) -> tuple[int, list[str], list[list[float]]]:
        """Die ganze Auswahl (Text, Wörter, Bilder, Vektorobjekte einer Seite): Seite, Kennungen, Lagen."""
        if not self.objectSelection:
            return -1, [], []
        page = self.objectSelection[0]["page"]
        chosen = [entry for entry in self.objectSelection if entry["page"] == page]
        return page, [entry["id"] for entry in chosen], [list(entry["view"]) for entry in chosen]

    def _object_op(self, page: int, func: Callable[[Any], Any], title: str, reselect: list[list[float]] | None = None, after: Callable[[Any], None] | None = None) -> bool:
        if not self.edit_allowed():
            return False

        def done(result) -> None:
            label = result.get("label", "") if isinstance(result, dict) else ""
            mode = result.get("mode", "") if isinstance(result, dict) else ""
            self.lastMode = label
            self.edited(title if mode in ("", "native") else f"{title}: {label}")
            notes = result.get("notes") if isinstance(result, dict) else None
            if notes:
                self.app.notify("reader", "info", " ".join(notes), title=title, auto_hide=9000)
            if reselect is not None:
                self._reselect[page] = reselect
            elif isinstance(result, dict) and result.get("views"):
                self._reselect[page] = result["views"]
            else:
                self._reselect[page] = [result["view"]] if isinstance(result, dict) and result.get("view") else []
            if after is not None:
                after(result)

        self.run(func, done, busy="Wird geändert und geprüft …")
        return True

    @Slot(int, str, str)
    def editObject(self, page: int, ident: str, text: str) -> None:  # noqa: N802
        self._object_op(page, lambda session: session.object_edit(page, ident, text), "Text geändert")

    @Slot()
    def deleteObjects(self) -> None:  # noqa: N802
        """Auswahl löschen – Text, Bilder und Vektorobjekte zusammen in einem Schritt."""
        page, ids, _views = self._chosen()
        if ids and self._object_op(page, lambda session: session.object_delete(page, ids), "Gelöscht", reselect=[]):
            self.objectSelection = []

    @Slot(float, float)
    def moveObjects(self, du: float, dv: float) -> None:  # noqa: N802
        """Auswahl um (du, dv) Anzeige-Punkte verschieben – ein Schritt, auch für gemischte Auswahlen."""
        if abs(du) < 0.01 and abs(dv) < 0.01:
            return
        page, ids, views = self._chosen()
        if not ids:
            return
        moved = [[view[0] + du, view[1] + dv, view[2] + du, view[3] + dv] for view in views]
        self._object_op(page, lambda session: session.object_move(page, ids, du, dv), "Verschoben", reselect=moved)

    @Slot(int, int, "QVariantList")
    def resizeObjectImage(self, page: int, index: int, rect) -> None:  # noqa: N802
        """Bild im Objektmodus skalieren – die Auswahl bleibt am Bild."""
        self._reselect[page] = [[float(value) for value in rect]]
        self.resizeImage(page, index, rect)

    @Slot("QVariantList")
    def resizeObjects(self, rect) -> None:  # noqa: N802
        """Vektorobjekte (bzw. Bilder und Vektorobjekte zusammen) auf einen neuen Bereich bringen."""
        page, ids, _views = self._chosen()
        if not ids:
            return
        target = [float(value) for value in rect]
        self._object_op(page, lambda session: session.object_resize(page, ids, target), "Größe geändert", reselect=[target] if len(ids) == 1 else None)

    @Slot(float, float)
    def nudgeObjects(self, du: float, dv: float) -> None:  # noqa: N802
        """Pfeiltasten: Auswahl sofort mitbewegen, die Änderung gesammelt als ein Schritt."""
        if not self.objectSelection:
            return
        self._nudge[0] += du
        self._nudge[1] += dv
        self.objectSelection = [{**entry, "view": [entry["view"][0] + du, entry["view"][1] + dv, entry["view"][2] + du, entry["view"][3] + dv]} for entry in self.objectSelection]
        self.app.timers.later(f"reader:nudge:{self.ident}", NUDGE_DELAY_MS, self._flush_nudge)

    def _flush_nudge(self) -> None:
        du, dv = self._nudge
        self._nudge = [0.0, 0.0]
        # Die Auswahl zeigt schon die neue Lage – zurückrechnen, dann als ein Schritt verschieben
        self.objectSelection = [{**entry, "view": [entry["view"][0] - du, entry["view"][1] - dv, entry["view"][2] - du, entry["view"][3] - dv]} for entry in self.objectSelection]
        self.moveObjects(du, dv)

    @Slot(str, "QVariant")
    def styleObjects(self, name: str, value) -> None:  # noqa: N802
        """Eine Eigenschaft der Auswahl: Text (size, spacing, color, family, bold, italic), Vektorobjekte
        (stroke, fill, width) und für alle die Deckkraft (opacity, 0–1)."""
        page, ids, views = self._chosen()
        if not ids:
            return
        if hasattr(value, "name") and callable(value.name):  # QColor aus QML
            value = value.name()
        self._object_op(page, lambda session: session.object_style(page, ids, name, value), "Formatiert", reselect=views)

    @Slot()
    def duplicateObject(self) -> None:  # noqa: N802
        """Auswahl duplizieren (Strg+D) – die Kopie liegt versetzt daneben und ist danach ausgewählt."""
        page, ids, views = self._chosen()
        if not ids:
            return
        shifted = [[view[0] + 12, view[1] + 12, view[2] + 12, view[3] + 12] for view in views]
        self._object_op(page, lambda session: session.object_duplicate(page, ids), "Dupliziert", reselect=shifted if len(ids) > 1 else None)

    @Slot(str)
    def alignObjects(self, how: str) -> None:  # noqa: N802
        """Ausrichten (left, hcenter, right, top, vcenter, bottom) bzw. verteilen (hspace, vspace)."""
        page, ids, _views = self._chosen()
        if len(ids) < (3 if how in ("hspace", "vspace") else 2):
            return
        title = "Verteilt" if how in ("hspace", "vspace") else "Ausgerichtet"
        self._object_op(page, lambda session: session.object_align(page, ids, how), title)

    @Slot(float)
    def rotateObjects(self, degrees: float) -> None:  # noqa: N802
        """Auswahl um ihre Mitte drehen (Grad im Uhrzeigersinn)."""
        page, ids, _views = self._chosen()
        if not ids or abs(float(degrees)) < 0.01:
            return
        self._object_op(page, lambda session: session.object_rotate(page, ids, float(degrees)), "Gedreht")

    @Slot(bool)
    def arrangeObjects(self, front: bool) -> None:  # noqa: N802
        """Bilder und Vektorobjekte ganz nach vorn bzw. ganz nach hinten legen."""
        page, ids, views = self._chosen()
        if not ids:
            return
        self._object_op(page, lambda session: session.object_arrange(page, ids, bool(front)), "In den Vordergrund" if front else "In den Hintergrund", reselect=views)

    # Zwischenablage -------------------------------------------------------------------------------------------
    def _may_copy(self) -> bool:
        if not (self.permissions or {}).get("copy", True):
            self.app.notify("reader", "warning", "Die Berechtigungen dieses PDFs erlauben kein Kopieren von Inhalten.", title="Kopieren nicht erlaubt")
            return False
        return True

    def _copy(self, page: int, ids: list[str], done: Callable[[Any], None], *, cut: bool = False) -> None:
        def work(session):
            return session.object_copy(page, ids), session.object_picture(page, ids)

        def copied(result) -> None:
            clip, picture = result
            self.reader.set_clip(clip, picture, cut=cut)
            done(clip)

        self.run(work, copied, refresh=False, priority=VIEW)

    @Slot()
    def copyObjects(self) -> None:  # noqa: N802
        """Auswahl kopieren: Objekte für Strg+V (auch in andere Tabs), Text bzw. Bild für andere Programme."""
        page, ids, _views = self._chosen()
        if ids and self._may_copy():
            self._copy(page, ids, lambda _clip: None)

    @Slot()
    def cutObjects(self) -> None:  # noqa: N802
        """Ausschneiden: erst kopieren – nur wenn das gelungen ist, wird gelöscht."""
        page, ids, _views = self._chosen()
        if not ids or not self._may_copy() or not self.edit_allowed():
            return

        def remove(_clip) -> None:
            if self._object_op(page, lambda session: session.object_delete(page, ids), "Ausgeschnitten", reselect=[]):
                self.objectSelection = []

        self._copy(page, ids, remove, cut=True)

    @Slot()
    def pasteObjects(self) -> None:  # noqa: N802
        """Strg+V: kopierte Objekte an derselben Stelle (wiederholt versetzt), sonst Bild oder Text der
        Zwischenablage auf der aktuellen Seite."""
        page = self.objectSelection[0]["page"] if self.objectSelection else self.currentPage
        self._paste(page, None)

    @Slot(int, float, float)
    def pasteObjectsAt(self, page: int, u: float, v: float) -> None:  # noqa: N802
        """»Hier einfügen«: obere linke Ecke an dieser Stelle."""
        self._paste(page, (float(u), float(v)))

    def _paste(self, page: int, at: tuple[float, float] | None) -> None:
        if not 0 <= page < self.pageCount or not self.edit_allowed():
            return
        kind, data = self.reader.paste_source()
        if kind == "clip":
            nudge = 0 if at is not None else self.reader.paste_nudge(self.ident, page, data)
            before = [(item["kind"], [round(value, 1) for value in item["view"]]) for item in self._object_items(page)]

            def placed(result) -> None:
                self._paste_select[page] = (result.get("view") or [], before)  # die neuen Objekte auswählen

            self._object_op(page, lambda session: session.object_paste(page, data, at, nudge), "Eingefügt", reselect=[], after=placed)
            return
        if kind == "image":
            self._paste_image(page, data, at)
            return
        if kind == "text":
            width, height = self.pageSizes[page] if page < len(self.pageSizes) else (595.0, 842.0)
            u, v = at if at is not None else (width * 0.1, height * 0.1)
            text = data.replace("\r\n", "\n").strip("\n")
            self.run(lambda session: session.add_text(page, u, v, text, {"size": self.fontSize}, None), lambda _outcome: self.edited("Text eingefügt"), busy="Text wird eingefügt …")
            return
        self.app.notify("reader", "info", "Die Zwischenablage enthält nichts, was sich hier einfügen lässt.", title="Einfügen", auto_hide=6000)

    def _paste_image(self, page: int, image, at: tuple[float, float] | None) -> None:
        import tempfile

        handle, path = tempfile.mkstemp(prefix="pdf-tool-einfuegen-", suffix=".png")
        os.close(handle)
        if not image.save(path, "PNG"):
            os.remove(path)
            self.app.notify("reader", "error", "Das Bild aus der Zwischenablage ließ sich nicht übernehmen.", title="Einfügen")
            return
        width, height = self.pageSizes[page] if page < len(self.pageSizes) else (595.0, 842.0)
        # In Punkten wie bei 96 dpi, höchstens halb so groß wie die Seite
        w, h = image.width() * 0.75, image.height() * 0.75
        shrink = min(1.0, width * 0.5 / max(1.0, w), height * 0.5 / max(1.0, h))
        w, h = w * shrink, h * shrink
        u0, v0 = at if at is not None else ((width - w) / 2, (height - h) / 2)
        rect = [u0, v0, u0 + w, v0 + h]

        def cleanup(_result=None) -> None:
            try:
                os.remove(path)
            except OSError as exc:
                _log().info("Temporäres Bild ließ sich nicht entfernen: %s", type(exc).__name__)

        def done(_index) -> None:
            cleanup()
            self.edited("Bild eingefügt")
            self._reselect[page] = [rect]

        def failed(exc: BaseException) -> None:
            cleanup()
            self.report(exc)

        self.run(lambda session: session.insert_image(page, path, rect), done, busy="Bild wird eingefügt …", failed=failed)

    # Texterkennung (OCR) -------------------------------------------------------------------------------------
    def check_scanned(self) -> None:
        """Nach dem Öffnen im Hintergrund: Bestehen die ersten Seiten aus Scans ohne Text? Dann bietet ein
        Hinweis die Texterkennung an (nur lesen, ohne Tesseract)."""
        pages = list(range(min(self.pageCount, SCAN_CHECK_PAGES)))
        if not pages:
            return

        def done(result) -> None:
            scans, _revision = result
            self.scanHint = any(scan["needs"] for scan in scans)

        self.run(lambda session: session.ocr_scan(pages), done, refresh=False, priority=BACKGROUND, failed=lambda exc: _log("ocr").info("Prüfung auf Scans fehlgeschlagen: %s", type(exc).__name__))

    @Slot("QVariantList")
    def recognizeText(self, selected) -> None:  # noqa: N802
        """»Text erkennen (OCR)«: Seiten (alle, aktuelle oder ausgewählte) und Sprachen wählen, dann läuft die
        Erkennung im Hintergrund – Seite für Seite, abbrechbar, am Ende ein Schritt für Rückgängig."""
        if self.ocrRunning or self.pageCount == 0 or not self.edit_allowed():
            return
        reader = self.reader
        if reader.ocrState == "fehlt":
            self.app.notify("reader", "error", "Die Texterkennung (Tesseract) wurde nicht gefunden. Bitte PDF Tool neu installieren.", title="Texterkennung nicht verfügbar")
            return
        reader.probe_ocr()
        chosen = sorted({int(page) for page in (selected or []) if 0 <= int(page) < self.pageCount})
        data = {"pageCount": self.pageCount, "current": self.currentPage, "selected": chosen, "languages": reader.ocr_languages(), "scope": "selected" if chosen else "all"}
        answer, result = self.app.dialogs.ask("ocr", "Text erkennen (OCR)", "", primary="Erkennen", data=data, width=520)
        if answer != "primary" or self.session is None:
            return
        installed = [entry["code"] for entry in reader.ocrLanguages]
        languages = [code for code in result.get("languages", []) if code in installed]
        if not languages or reader.ocr_engine() is None:
            self.app.notify("reader", "error", "Keine Sprache für die Texterkennung gewählt bzw. verfügbar.", title="Texterkennung nicht möglich")
            return
        scope = result.get("scope", "all")
        pages = chosen if scope == "selected" and chosen else ([self.currentPage] if scope == "current" else list(range(self.pageCount)))
        reader.remember_ocr_languages(languages)
        self._start_ocr(pages, languages, bool(result.get("redo")))

    def _on_worker(self, func: Callable[[Any], Any]) -> Any:
        """Aus dem Thread der Texterkennung: ``func(session)`` im Arbeitsthread ausführen und warten."""
        task = self.engine.submit(lambda: func(self.session), priority=BACKGROUND, label="texterkennung")
        result = self.engine.wait(task, timeout=600)
        if task.cancelled:
            from tools.pdf_editor import ocr

            raise ocr.OcrCancelled()
        return result

    def _start_ocr(self, pages: list[int], languages: list[str], redo: bool) -> None:
        from tools.pdf_editor import ocr

        engine = self.reader.ocr_engine()
        cancel = threading.Event()
        self._ocr_cancel = cancel
        self.ocrRunning = True
        self.ocrDone = 0
        self.ocrTotal = 0
        self.ocrStatus = "Seiten werden geprüft …"
        post = self.app.worker.post
        started = time.monotonic()

        def progress(done: int, total: int, page: int) -> None:
            self.ocrDone, self.ocrTotal = done, total
            self.ocrStatus = f"Seite {page + 1} wird erkannt ({done + 1} von {total})" if done < total else "Erkannter Text wird übernommen und geprüft …"

        def job() -> dict:
            scans, revision = self._on_worker(lambda session: session.ocr_scan(pages))
            todo = [scan["page"] for scan in scans if scan["needs"] or (redo and scan["layer"])]
            with_text = sum(1 for scan in scans if not scan["needs"] and not scan["layer"])
            if not todo:
                return {"pages": 0, "skipped": len(scans), "withText": with_text, "words": 0, "confidence": 0.0, "language": ""}
            results = []
            for number, page in enumerate(todo):
                if cancel.is_set():
                    raise ocr.OcrCancelled()
                post(progress, number, len(todo), page)
                png, dpi, now = self._on_worker(lambda session, page=page: session.ocr_image(page))
                if now != revision:
                    raise ocr.OcrError("Das Dokument wurde während der Texterkennung geändert. Bitte den Text erneut erkennen.")
                results.append(ocr.recognize(engine, page, png, languages, dpi, cancel=cancel))
                del png
            if cancel.is_set():
                raise ocr.OcrCancelled()
            post(progress, len(todo), len(todo), todo[-1])
            changed, state = self._on_worker(lambda session: (session.ocr_apply(results, revision), session.state()))
            words = sum(result.words for result in results)
            weighted = sum(result.confidence * result.words for result in results) / words if words else 0.0
            found = Counter(result.language for result in results if result.language).most_common(1)
            return {"pages": changed, "skipped": len(scans) - len(todo), "withText": with_text, "words": words, "confidence": weighted, "language": found[0][0] if found else "", "state": state}

        def finished() -> None:
            self.ocrRunning = False
            self.ocrStatus = ""
            self._ocr_cancel = None

        def done(summary: dict) -> None:
            finished()
            if summary.get("state") is not None:
                self.apply_state(summary["state"])
                self._reload_tool()
            _log("ocr").info("Texterkennung: %d Seiten, %d Wörter, %.0f %% Sicherheit, %d ms", summary["pages"], summary["words"], summary["confidence"], (time.monotonic() - started) * 1000)
            if summary["pages"] == 0:
                reason = "Die gewählten Seiten haben bereits Text – sie sind schon durchsuchbar." if summary["withText"] else "Auf den gewählten Seiten wurde kein Text erkannt."
                self.app.notify("reader", "info", reason, title="Text erkennen", auto_hide=9000)
                return
            self.scanHint = False
            pages_text = "1 Seite" if summary["pages"] == 1 else f"{summary['pages']} Seiten"
            message = f"{pages_text} durchsuchbar gemacht – {summary['words']} Wörter, Sicherheit im Mittel {round(summary['confidence'])} %."
            if summary["skipped"]:
                message += f" {summary['skipped']} {'Seite' if summary['skipped'] == 1 else 'Seiten'} übersprungen (bereits mit Text)."
            message += " Das Aussehen der Seiten ist unverändert; Rückgängig nimmt die Erkennung zurück."
            self.edited("Text erkannt")
            self.app.notify("reader", "success", message, title="Text erkannt", auto_hide=12000)

        def failed(exc: BaseException, details: str) -> None:
            finished()
            if isinstance(exc, ocr.OcrCancelled):
                self.app.notify("reader", "info", "Die Texterkennung wurde abgebrochen. Das Dokument ist unverändert.", title="Abgebrochen", auto_hide=8000)
                return
            if isinstance(exc, EditorError):
                _log("ocr").warning("Texterkennung fehlgeschlagen: %s", type(exc).__name__)
                self.app.notify("reader", "error", str(exc), title="Text erkennen nicht möglich")
                return
            self.report(exc, details)

        self.app.worker.run(job, done, failed)

    @Slot()
    def cancelOcr(self) -> None:  # noqa: N802
        if self._ocr_cancel is not None:
            self._ocr_cancel.set()
            self.ocrStatus = "Wird abgebrochen …"

    @Slot("QVariantList")
    def removeRecognizedText(self, selected) -> None:  # noqa: N802
        """Von PDF Tool erkannten Text (Textebenen) wieder entfernen – alle bzw. die ausgewählten Seiten."""
        if not self.edit_allowed():
            return
        pages = sorted({int(page) for page in (selected or []) if 0 <= int(page) < self.pageCount}) or list(range(self.pageCount))

        def done(count: int) -> None:
            if count:
                self.edited("Erkannten Text entfernt")
                self.app.notify("reader", "success", f"Erkannter Text von {count} {'Seite' if count == 1 else 'Seiten'} entfernt.", title="Erkannten Text entfernen", auto_hide=8000)
            else:
                self.app.notify("reader", "info", "Auf diesen Seiten gibt es keinen von PDF Tool erkannten Text.", title="Erkannten Text entfernen", auto_hide=8000)

        self.run(lambda session: session.ocr_remove(pages), done, busy="Erkannter Text wird entfernt …")

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
                if not item.get("replyTo"):  # Antworten haben kein eigenes Bild auf der Seite
                    by_page.setdefault(str(item["page"]), []).append(item)
            self.annotationPages = by_page
            # Antworten stehen im Verlauf direkt unter ihrem Kommentar (eingerückt)
            order = [item for item in items if not item.get("replyTo")]
            replies: dict[str, list] = {}
            for item in items:
                if item.get("replyTo"):
                    replies.setdefault(item["replyTo"], []).append(item)
            listed = []
            for item in order:
                listed.append({**item, "depth": 0})
                listed += [{**reply, "depth": 1} for reply in replies.pop(item["key"], [])]
            listed += [{**reply, "depth": 1} for group in replies.values() for reply in group]  # Kommentar fehlt
            self.annotationList.set_items([{key: item[key] for key in ANNOTATION_ROLES} for item in listed])
            wanted, self._select_annotation = self._select_annotation, ""
            chosen = next((item for item in items if item["key"] == wanted), None) if wanted else None
            if chosen is not None and self.tool == "select":
                self.selectedObject = {"kind": "annotation", "page": chosen["page"], "key": chosen["key"], "view": chosen["view"]}

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

    @Slot(str, str, "QVariant")
    def styleAnnotation(self, key: str, name: str, value) -> None:  # noqa: N802
        """Linienstärke, Füllung, Deckkraft oder Schriftgröße eines Kommentars aus PDF Tool ändern."""
        if hasattr(value, "name") and callable(value.name):  # QColor aus QML
            value = value.name()
        self._annot_op(lambda session: session.restyle_annotation(key, name, value), "Kommentar formatiert")

    @Slot(str, "QVariantList")
    def resizeAnnotation(self, key: str, rect) -> None:  # noqa: N802
        box = [float(v) for v in rect]
        selected = dict(self.selectedObject)
        if selected.get("key") == key:
            self.selectedObject = {**selected, "view": box}
        self._annot_op(lambda session: session.resize_annotation(key, box), "Kommentargröße geändert")

    @Slot(str, str)
    def replyAnnotation(self, key: str, text: str) -> None:  # noqa: N802
        """Antwort auf einen Kommentar – erscheint im Verlauf unter ihm."""
        if text.strip():
            self._annot_op(lambda session: session.reply_annotation(key, text), "Antwort hinzugefügt")

    # Anhänge --------------------------------------------------------------------------------------------------------
    @Slot()
    def loadAttachments(self) -> None:  # noqa: N802
        def done(items) -> None:
            self.attachmentList.set_items([{**{key: item[key] for key in ("key", "name", "description", "modified", "page", "openable")}, "sizeText": _size_label(item["size"])} for item in items])
            self.attachmentCount = len(items)

        def failed(exc: BaseException) -> None:
            self.attachmentList.set_items([])
            self.attachmentCount = 0
            self.report(exc)

        self.run(lambda session: session.attachments(), done, refresh=False, priority=BACKGROUND, key="attachments", failed=failed)

    def _attachment(self, key: str) -> dict:
        return next((item for item in self.attachmentList.items() if item["key"] == key), {})

    @Slot(str)
    def saveAttachment(self, key: str) -> None:  # noqa: N802
        item = self._attachment(key)
        if not item:
            return
        target = self.reader.pick_save_file(item["name"], "Anhang speichern")
        if not target:
            return
        self.run(lambda session: session.save_attachment(key, target), lambda path: self.app.set_status(f"Anhang gespeichert: {path}", "success"), refresh=False, busy="Anhang wird gespeichert …")

    @Slot(str)
    def openAttachment(self, key: str) -> None:  # noqa: N802
        item = self._attachment(key)
        if not item:
            return
        if not item["openable"]:
            self.app.notify("reader", "warning", f"»{item['name']}« wird aus Sicherheitsgründen nicht geöffnet – Programme und Skripte aus PDFs werden nie ausgeführt. Mit »Speichern unter …« lässt sich die Datei speichern.", title="Anhang nicht geöffnet")
            return
        if not self.app.dialogs.confirm(f"»{item['name']}« öffnen?", "Anhänge können schädliche Inhalte enthalten. Öffnen Sie nur Dateien aus Quellen, denen Sie vertrauen. Die Datei wird mit dem zugeordneten Programm geöffnet.", "Öffnen", danger=False):
            return
        folder = self.reader.attachment_dir()

        def done(path: str) -> None:
            from .. import files

            try:
                files.open_path(path)
            except OSError as exc:
                self.app.notify("reader", "error", f"Für diesen Dateityp ist kein Programm zugeordnet ({exc.strerror or 'nicht möglich'}).", title="Öffnen nicht möglich")

        self.run(lambda session: session.open_attachment(key, folder), done, refresh=False, busy="Anhang wird geöffnet …")

    @Slot()
    def addAttachment(self) -> None:  # noqa: N802
        if not self.edit_allowed():
            return
        path = self.reader.pick_file("Datei anhängen")
        if path:
            self.run(lambda session: session.add_attachment(path, ""), lambda _key: (self.edited("Anhang hinzugefügt"), self.loadAttachments()), busy="Anhang wird hinzugefügt …")

    @Slot(str)
    def removeAttachment(self, key: str) -> None:  # noqa: N802
        item = self._attachment(key)
        if not item or not self.edit_allowed():
            return
        if not self.app.dialogs.confirm(f"»{item['name']}« entfernen?", "Der Anhang wird aus dem Dokument entfernt. Mit »Rückgängig« (Strg+Z) lässt er sich zurückholen, solange das Dokument offen ist.", "Entfernen"):
            return
        self.run(lambda session: session.remove_attachment(key), lambda _result: (self.edited("Anhang entfernt"), self.loadAttachments()), busy="")

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

    # Formular gestalten --------------------------------------------------------------------------------------------
    @Slot()
    def loadDesign(self) -> None:  # noqa: N802
        def done(items) -> None:
            by_page: dict[str, list] = {}
            for item in items:
                by_page.setdefault(str(item["page"]), []).append(item)
            self.designPages = by_page
            wanted = self._select_field or self.fieldSelection.get("key", "")
            self._select_field = ""
            self.fieldSelection = next((item for item in items if item["key"] == wanted), {}) if wanted else {}

        self.run(lambda session: session.design_widgets(), done, refresh=False, priority=VIEW, key="design")

    @Slot(str)
    def setFormKind(self, kind: str) -> None:  # noqa: N802
        """Art des nächsten Feldes (Rahmen aufziehen oder klicken legt es an); »« = Felder auswählen."""
        from tools.pdf_editor import formdesign

        self.formKind = kind if kind in formdesign.KINDS else ""
        if self.formKind:
            self.fieldSelection = {}

    @Slot(str)
    def selectField(self, key: str) -> None:  # noqa: N802
        self.fieldSelection = next((item for items in self.designPages.values() for item in items if item["key"] == key), {}) if key else {}

    def _design_op(self, func, title: str, select: bool = False) -> None:
        """Änderung am Formular: danach die Felder neu laden (``select``: das gelieferte Widget auswählen)."""
        if not self.edit_allowed("edit"):
            return
        if not (self.permissions or {}).get("annotate", True):
            self.app.notify("reader", "warning", "Die Berechtigungen dieses PDFs erlauben das nicht.", title="Nicht erlaubt")
            return

        def done(result) -> None:
            if select and isinstance(result, str):
                self._select_field = result
            self.edited(title)
            self.loadDesign()

        self.run(func, done, busy="", failed=lambda exc: (self.report(exc), self.loadDesign()))

    def _chosen_field(self, key: str = "") -> str:
        return key or self.fieldSelection.get("key", "")

    @Slot(int, "QVariantList")
    def createField(self, page: int, rect: list) -> None:  # noqa: N802
        """Feld der gewählten Art anlegen: im aufgezogenen Rahmen bzw. – bei einem Klick – in Standardgröße
        ab dieser Stelle (Anzeige-Koordinaten). Danach ist es ausgewählt und »Auswählen« wieder aktiv."""
        from tools.pdf_editor import formdesign

        kind = self.formKind
        if kind not in formdesign.KINDS or not 0 <= page < self.pageCount:
            return
        box = [float(v) for v in rect]
        if box[2] - box[0] < 4 and box[3] - box[1] < 4:
            width, height = formdesign.SIZES[kind]
            box = [box[0], box[1], box[0] + width, box[1] + height]
        self.formKind = ""
        self._design_op(lambda session: session.create_field(page, kind, box), f"{formdesign.TITLES[kind]} hinzugefügt", select=True)

    @Slot(str, str)
    def createFieldAt(self, kind: str, at: str) -> None:  # noqa: N802
        """Kontextmenü »… hier anlegen«: ``at`` = »Seite,u,v« (Anzeige-Koordinaten)."""
        page, u, v = (float(part) for part in at.split(","))
        self.setFormKind(kind)
        self.createField(int(page), [u, v, u, v])

    @Slot(str, float, float)
    def moveField(self, key: str, du: float, dv: float) -> None:  # noqa: N802
        key = self._chosen_field(key)
        if not key or (abs(du) < 0.25 and abs(dv) < 0.25):
            return
        chosen = self.fieldSelection
        if chosen.get("key") == key:  # Auswahl gleich an der neuen Stelle zeigen
            view = chosen["view"]
            self.fieldSelection = {**chosen, "view": [view[0] + du, view[1] + dv, view[2] + du, view[3] + dv]}
        self._design_op(lambda session: session.move_field(key, du, dv), "Feld verschoben")

    @Slot(float, float)
    def nudgeField(self, du: float, dv: float) -> None:  # noqa: N802
        """Pfeiltasten: Auswahl sofort mitbewegen, die Änderung gesammelt als ein Schritt."""
        chosen = self.fieldSelection
        if not chosen:
            return
        self._field_nudge[0] += du
        self._field_nudge[1] += dv
        view = chosen["view"]
        self.fieldSelection = {**chosen, "view": [view[0] + du, view[1] + dv, view[2] + du, view[3] + dv]}
        self.app.timers.later(f"reader:fieldnudge:{self.ident}", NUDGE_DELAY_MS, self._flush_field_nudge)

    def _flush_field_nudge(self) -> None:
        du, dv = self._field_nudge
        self._field_nudge = [0.0, 0.0]
        chosen = self.fieldSelection
        if not chosen:
            return
        view = chosen["view"]
        self.fieldSelection = {**chosen, "view": [view[0] - du, view[1] - dv, view[2] - du, view[3] - dv]}
        self.moveField(chosen["key"], du, dv)

    @Slot(str, "QVariantList")
    def resizeField(self, key: str, rect: list) -> None:  # noqa: N802
        key = self._chosen_field(key)
        box = [float(v) for v in rect]
        if not key:
            return
        if self.fieldSelection.get("key") == key:
            self.fieldSelection = {**self.fieldSelection, "view": box}
        self._design_op(lambda session: session.resize_field(key, box), "Feldgröße geändert")

    @Slot(str)
    def deleteField(self, key: str = "") -> None:  # noqa: N802
        key = self._chosen_field(key)
        if not key:
            return
        if self.fieldSelection.get("key") == key:
            self.fieldSelection = {}
        self._design_op(lambda session: session.delete_field(key), "Feld gelöscht")

    @Slot(str)
    def duplicateField(self, key: str = "") -> None:  # noqa: N802
        key = self._chosen_field(key)
        if key:
            self._design_op(lambda session: session.duplicate_field(key), "Feld dupliziert", select=True)

    @Slot(str)
    def addFieldOption(self, key: str = "") -> None:  # noqa: N802
        """Optionsgruppe: eine weitere Option (darunter bzw. daneben)."""
        key = self._chosen_field(key)
        if key:
            self._design_op(lambda session: session.add_field_option(key), "Option hinzugefügt", select=True)

    @Slot(str)
    def editFieldProperties(self, key: str = "") -> None:  # noqa: N802
        """Dialog »Feldeigenschaften«: geänderte Werte werden als ein Schritt übernommen."""
        key = self._chosen_field(key)
        item = next((entry for items in self.designPages.values() for entry in items if entry["key"] == key), None)
        if item is None:
            return
        self.fieldSelection = item
        answer, data = self.app.dialogs.ask("form_field", "Feldeigenschaften", primary="Übernehmen", close="Abbrechen", data={"field": dict(item)}, width=560)
        if answer != "primary":
            return
        changes = field_changes(item, data or {})
        if changes:
            self._design_op(lambda session: session.field_properties(key, changes), "Feldeigenschaften geändert")

    # Seiten -----------------------------------------------------------------------------------------------------------
    def _page_op(self, func, title: str, done: Callable[[Any], None] | None = None) -> None:
        if not self.edit_allowed("assemble"):
            return

        def finished(result) -> None:
            self.edited(title)
            if self.redactCount:  # Lage der Seiten geändert: vorgemerkte Bereiche passen nicht mehr
                self._set_marks({})
                self.app.notify("reader", "info", "Die Seiten haben sich geändert – noch nicht angewendete Schwärzungsbereiche wurden verworfen.", title="Schwärzen", auto_hide=8000)
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
        """Seiten einer anderen PDF einfügen – alle oder nur ausgewählte (z. B. »1-3, 5«)."""
        if not self.edit_allowed("assemble"):
            return

        def failed(exc: BaseException) -> None:
            if isinstance(exc, PasswordRequired):
                secret = self.reader.ask_password(path, exc.wrong)
                if secret is not None:
                    self._insert_file(index, path, secret)
                return
            self.report(exc)

        def counted(count: int) -> None:
            from tools.pdf_editor import pages as page_ops

            chosen = None
            if count > 1:
                name = os.path.basename(path)
                answer, data = self.app.dialogs.ask(
                    "text_input", "Seiten aus PDF einfügen", f"»{name}« hat {count} Seiten. Welche sollen eingefügt werden?",
                    primary="Einfügen", close="Abbrechen",
                    data={"label": "Seiten", "value": f"1-{count}", "placeholder": "z. B. 1-3, 5", "hint": "Leer oder »1-" + str(count) + "« fügt alle Seiten ein; einzelne Seiten mit Komma, Bereiche mit Bindestrich."},
                )
                if answer != "primary":
                    return
                spec = str(data.get("value", "")).strip()
                if spec:
                    try:
                        chosen = page_ops.parse_pages(spec, count)
                    except ValueError as exc:
                        self.app.notify("reader", "warning", str(exc), title="Seiten einfügen")
                        return
                    if chosen == list(range(count)):
                        chosen = None

            def done(notes) -> None:
                self.edited("Seiten eingefügt")
                if notes:
                    self.app.notify("reader", "info", " ".join(notes), title="Seiten eingefügt", auto_hide=10000)

            self.run(lambda session: session.insert_file(index, path, password, chosen), done, busy="Seiten werden eingefügt …", failed=failed)

        self.run(lambda session: session.source_pages(path, password), counted, refresh=False, failed=failed, priority=VIEW)

    # Seiten über die Zwischenablage (auch in andere Tabs) ------------------------------------------------------
    @Slot("QVariantList")
    def copyPages(self, indexes: list) -> None:  # noqa: N802
        chosen = sorted({int(i) for i in indexes if 0 <= int(i) < self.pageCount}) or [self.currentPage]
        if not (self.permissions or {}).get("copy", True):
            self.app.notify("reader", "warning", "Die Berechtigungen dieses PDFs erlauben kein Kopieren von Seiten.", title="Kopieren nicht erlaubt")
            return
        self.run(lambda session: session.copy_pages(chosen), lambda data: self.reader.set_page_clip(data, len(chosen)), refresh=False, priority=VIEW, busy="Seiten werden kopiert …")

    @Slot("QVariantList")
    def cutPages(self, indexes: list) -> None:  # noqa: N802
        """Ausschneiden: erst kopieren – nur wenn das gelungen ist, werden die Seiten entfernt."""
        chosen = sorted({int(i) for i in indexes if 0 <= int(i) < self.pageCount}) or [self.currentPage]
        if len(chosen) >= self.pageCount:
            self.app.notify("reader", "warning", "Mindestens eine Seite muss im Dokument bleiben.", title="Nicht möglich")
            return
        if not (self.permissions or {}).get("copy", True) or not self.edit_allowed("assemble"):
            if not (self.permissions or {}).get("copy", True):
                self.app.notify("reader", "warning", "Die Berechtigungen dieses PDFs erlauben kein Kopieren von Seiten.", title="Kopieren nicht erlaubt")
            return

        def copied(data: bytes) -> None:
            self.reader.set_page_clip(data, len(chosen))
            self._page_op(lambda session: session.delete_pages(chosen, cut=True), "Seiten ausgeschnitten" if len(chosen) > 1 else "Seite ausgeschnitten")

        self.run(lambda session: session.copy_pages(chosen), copied, refresh=False, priority=VIEW, busy="Seiten werden kopiert …")

    @Slot(int)
    def pastePages(self, index: int) -> None:  # noqa: N802
        """Kopierte Seiten an Position ``index`` einfügen (0 = vor die erste Seite, Seitenzahl = ans Ende)."""
        data = self.reader.page_clip()
        if not data:
            self.app.notify("reader", "info", "Es wurden noch keine Seiten kopiert.", title="Seiten einfügen", auto_hide=6000)
            return
        target = max(0, min(int(index), self.pageCount))
        self._page_op(lambda session: session.paste_pages(target, data), "Seiten eingefügt", lambda _notes: self.goTo(target))

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
            self.run(lambda session: session.extract(chosen, target), lambda path: self.app.notify("reader", "success", f"{len(chosen)} {'Seite' if len(chosen) == 1 else 'Seiten'} gespeichert: {path}", title="Neue PDF erstellt", auto_hide=8000), refresh=False, busy="Seiten werden gespeichert …")

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
        self.run(lambda session: session.export_images(chosen, folder, stem, fmt, dpi), lambda written: self.app.notify("reader", "success", f"{len(written)} {'Bild' if len(written) == 1 else 'Bilder'} gespeichert in {folder}", title="Exportiert", auto_hide=8000), refresh=False, busy="Seiten werden exportiert …")

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

    # Schnellwerkzeuge der Startseite ---------------------------------------------------------------------------------
    @Slot(str)
    def runAction(self, name: str) -> None:  # noqa: N802
        """Werkzeug oder Dialog eines Schnellwerkzeugs (gleich nach dem Öffnen aufgerufen)."""
        handlers = {
            "optimize": self.optimizeDocument, "redact": lambda: self.setTool("redact"), "redactSearch": self.searchRedact,
            "protect": self.protectDocument, "watermark": self.watermarkDocument, "headerFooter": self.headerFooterDocument,
            "clean": self.cleanDocument, "flatten": self.flattenDocument, "sign": lambda: self.setTool("signature"),
            "stamp": lambda: self.setTool("stamp"), "crop": lambda: self.cropPages([]),
        }
        handler = handlers.get(name)
        if handler is not None:
            handler()

    # Kennwortschutz und Berechtigungen ---------------------------------------------------------------------------------
    @Slot()
    def protectDocument(self) -> None:  # noqa: N802
        """Dialog »Kennwortschutz«: Kennwort zum Öffnen und/oder Einschränkungen festlegen, ändern oder entfernen.
        Gilt ab dem nächsten Speichern (AES-256); Kennwörter bleiben im Arbeitsspeicher und werden nie protokolliert."""

        def show(info: dict) -> None:
            if not info.get("changeable"):
                self._unlock(then=self.protectDocument)
                return
            if not self.edit_allowed("edit"):
                return
            answer, data = self.app.dialogs.ask("protect", "Kennwortschutz", "", primary="Übernehmen", close="Abbrechen", data={**info, "name": self.name}, width=600)
            if answer != "primary":
                return
            values = {} if (data or {}).get("mode") == "remove" else dict(data or {})

            def done(title: str) -> None:
                self.edited(title)
                message = "Der Schutz gilt ab dem nächsten Speichern." if values else "Beim nächsten Speichern entsteht eine Datei ohne Kennwortschutz."
                self.app.notify("reader", "success", message, title=title, auto_hide=10000, actions=[("Jetzt speichern", self.saveDocument)])

            self.run(lambda session: session.set_protection(values), done, busy="")

        self.run(lambda session: session.protection(), show, refresh=False, priority=VIEW)

    @Slot()
    def unlockPermissions(self) -> None:  # noqa: N802
        self._unlock()

    def _unlock(self, then: Callable[[], None] | None = None) -> None:
        """Berechtigungskennwort eingeben: Stimmt es, sind die Einschränkungen dieses PDFs aufgehoben (nur hier,
        die Datei bleibt, wie sie ist). Nichts wird geraten oder umgangen."""
        answer, data = self.app.dialogs.ask(
            "password", "Einschränkungen aufheben",
            "Dieses PDF schränkt Änderungen ein. Mit dem Berechtigungskennwort lassen sie sich für die Bearbeitung hier aufheben.",
            primary="Aufheben", close="Abbrechen", data={"label": "Berechtigungskennwort"},
        )
        if answer != "primary":
            return
        secret = str((data or {}).get("value") or "")

        def done(ok: bool) -> None:
            if not ok:
                self.app.notify("reader", "warning", "Das Kennwort stimmt nicht – die Einschränkungen bleiben.", title="Einschränkungen")
                return
            self.opening_notice()
            self.app.notify("reader", "success", "Dieses Dokument lässt sich jetzt uneingeschränkt bearbeiten.", title="Einschränkungen aufgehoben", auto_hide=8000)
            if then is not None:
                then()

        self.run(lambda session: session.unlock(secret), done, busy="Kennwort wird geprüft …")

    # Bereinigen, Reduzieren, Verkleinern ----------------------------------------------------------------------------
    @Slot()
    def cleanDocument(self) -> None:  # noqa: N802
        """Vor dem Weitergeben: Daten entfernen, die man auf den Seiten nicht sieht (vorher gezählt)."""
        if not self.edit_allowed("edit"):
            return

        def show(found: dict) -> None:
            items = [
                {"key": "metadata", "label": "Metadaten", "detail": "Titel, Autor, Programm, Datumsangaben und XMP-Daten", "count": found.get("metadata", 0), "checked": True},
                {"key": "javascript", "label": "Skripte und Aktionen", "detail": "JavaScript, Programme starten, Formulare senden, Daten laden", "count": found.get("javascript", 0), "checked": True},
                {"key": "attachments", "label": "Dateianhänge", "detail": "eingebettete Dateien und Dateianhang-Kommentare", "count": found.get("attachments", 0), "checked": True},
                {"key": "hidden", "label": "Versteckte Daten", "detail": "Vorschaubilder, Bearbeitungsdaten anderer Programme, unsichtbare Kommentare", "count": found.get("hidden", 0), "checked": True},
                {"key": "comments", "label": "Kommentare und Markierungen", "detail": "alle Kommentare – auch sichtbare", "count": found.get("comments", 0), "checked": False},
            ]
            if not any(item["count"] for item in items):
                self.app.notify("reader", "success", "Keine Metadaten, Skripte, Anhänge, Kommentare oder versteckten Daten gefunden.", title="Nichts zu bereinigen", auto_hide=8000)
                return
            answer, data = self.app.dialogs.ask(
                "checklist", "Dokument bereinigen",
                "Entfernt Daten, die man auf den Seiten nicht sieht. Rückgängig (Strg+Z) ist möglich, solange das Dokument offen ist.",
                primary="Bereinigen", close="Abbrechen", data={"items": items}, width=580,
            )
            if answer != "primary":
                return
            options = {item["key"]: bool((data or {}).get(item["key"])) and item["count"] > 0 for item in items}
            if not any(options.values()):
                return

            def done(removed: dict) -> None:
                labels = {"metadata": "Metadaten", "javascript": "Skripte und Aktionen", "attachments": "Anhänge", "comments": "Kommentare", "hidden": "versteckte Daten"}
                parts = [f"{labels[key]} ({count})" for key, count in removed.items() if count]
                self.edited("Dokument bereinigt")
                self.app.notify("reader", "success", ("Entfernt: " + ", ".join(parts) + "." if parts else "Es war nichts zu entfernen.") + " Gespeichert wird beim nächsten Speichern.", title="Dokument bereinigt", auto_hide=10000, actions=[("Jetzt speichern", self.saveDocument)])
                self.loadAnnotations()
                self.loadAttachments()
                self.loadFields()

            self.run(lambda session: session.cleanup(options), done, busy="Dokument wird bereinigt …")

        self.run(lambda session: session.cleanup_findings(), show, refresh=False, busy="Dokument wird geprüft …")

    @Slot()
    def flattenDocument(self) -> None:  # noqa: N802
        """Formularfelder und Kommentare fest in die Seiten übernehmen."""
        if not self.edit_allowed("edit"):
            return

        def show(counts: dict) -> None:
            fields_count, comments_count = int(counts.get("fields", 0)), int(counts.get("comments", 0))
            if not fields_count and not comments_count:
                self.app.notify("reader", "info", "Dieses Dokument hat keine Formularfelder oder Kommentare.", title="Nichts zu reduzieren", auto_hide=8000)
                return
            items = [
                {"key": "fields", "label": "Formularfelder", "detail": "Eingaben werden fester Text", "count": fields_count, "checked": True},
                {"key": "comments", "label": "Kommentare, Stempel und Unterschriften", "detail": "werden Teil der Seite", "count": comments_count, "checked": True},
            ]
            answer, data = self.app.dialogs.ask(
                "checklist", "Reduzieren",
                "Formularfelder und Kommentare werden fester Bestandteil der Seiten: Sie sehen gleich aus, lassen sich aber nicht mehr ändern oder entfernen.",
                primary="Reduzieren", close="Abbrechen", data={"items": items}, width=560,
            )
            if answer != "primary":
                return
            fields = bool((data or {}).get("fields")) and fields_count > 0
            comments = bool((data or {}).get("comments")) and comments_count > 0
            if not (fields or comments):
                return

            def done(result: dict) -> None:
                parts = []
                if result.get("fields"):
                    parts.append(f"{result['fields']} Formularfelder")
                if result.get("comments"):
                    parts.append(f"{result['comments']} Kommentare")
                note = f" {result['skipped']} ohne eigenes Erscheinungsbild blieben unverändert." if result.get("skipped") else ""
                self.edited("Reduziert")
                self.app.notify("reader", "success", ("Fest übernommen: " + " und ".join(parts) + "." if parts else "Es wurde nichts übernommen.") + note, title="Reduziert", auto_hide=10000)
                self.loadAnnotations()
                self.loadFields()

            self.run(lambda session: session.flatten(fields, comments), done, busy="Wird reduziert …")

        self.run(lambda session: session.flatten_counts(), show, refresh=False, priority=VIEW)

    @Slot()
    def optimizeDocument(self) -> None:  # noqa: N802
        """Verkleinerte Kopie speichern – das Original bleibt unverändert."""

        def show(size: int) -> None:
            answer, data = self.app.dialogs.ask("optimize", "PDF verkleinern", "", primary="Weiter", close="Abbrechen", data={"size": _size_label(size), "name": self.name}, width=560)
            if answer != "primary":
                return
            level = str((data or {}).get("level") or "mittel")
            target = self.reader.pick_save_pdf(f"{self._stem()}_verkleinert.pdf", "Verkleinerte Kopie speichern")
            if not target:
                return

            def done(result: dict) -> None:
                before, after = _size_label(result["before"]), _size_label(result["after"])
                if result["after"] >= result["before"]:
                    message = f"Dieses PDF lässt sich nicht weiter verkleinern ({before}); die Kopie entspricht dem aktuellen Stand."
                else:
                    images = f", {result['images']} {'Bild' if result['images'] == 1 else 'Bilder'} neu berechnet" if result["images"] else ""
                    message = f"Von {before} auf {after} verkleinert (−{result['percent']} %){images}."
                path = result["path"]
                self.app.notify("reader", "success", message, title="Verkleinerte Kopie gespeichert", auto_hide=12000, actions=[("Öffnen", lambda: self.reader.open_paths([path])), ("Ordner öffnen", lambda: self.reader.showInFolder(path))])

            self.run(lambda session: session.optimize_copy(target, level), done, refresh=False, busy="PDF wird verkleinert …")

        self.run(lambda session: session.size_now(), show, refresh=False, busy="Größe wird ermittelt …")

    # Kopf- und Fußzeile, Seitenzahlen, Wasserzeichen ----------------------------------------------------------------
    @Slot()
    def headerFooterDocument(self) -> None:  # noqa: N802
        self._page_marks("Header")

    @Slot()
    def watermarkDocument(self) -> None:  # noqa: N802
        self._page_marks("Watermark")

    def _page_marks(self, kind: str) -> None:
        if not self.edit_allowed("edit"):
            return
        header = kind == "Header"

        def show(present: dict) -> None:
            existing = int(present.get(kind, 0))
            answer, data = self.app.dialogs.ask(
                "header_footer" if header else "watermark", "Kopf- und Fußzeile, Seitenzahlen" if header else "Wasserzeichen", "",
                primary="Hinzufügen", close="Abbrechen", data={"pageCount": self.pageCount, "existing": existing, "name": self._stem()}, width=700 if header else 620,
            )
            if answer != "primary":
                return
            spec = dict(data or {})
            replace = existing > 0 and bool(spec.get("replace", True))

            def done(result: dict) -> None:
                title = ("Kopf- und Fußzeile" if header else "Wasserzeichen") + " hinzugefügt"
                if not result.get("pages"):
                    self.app.notify("reader", "info", "Es wurde nichts hinzugefügt – bitte einen Text eingeben.", title="Nichts hinzugefügt", auto_hide=8000)
                    return
                note = f" Nicht darstellbare Zeichen wurden durch »?« ersetzt: {' '.join(result['replaced'])}" if result.get("replaced") else ""
                self.edited(title)
                self.app.notify("reader", "warning" if note else "success", f"{result['pages']} {'Seite' if result['pages'] == 1 else 'Seiten'}.{note}", title=title, auto_hide=10000)

            self.run(lambda session: session.page_marks(kind, spec, replace), done, busy="Wird hinzugefügt …")

        self.run(lambda session: session.marks_present(), show, refresh=False, priority=VIEW)

    @Slot()
    def removePageMarks(self) -> None:  # noqa: N802
        """Kopf-/Fußzeilen und Wasserzeichen entfernen, die PDF Tool hinzugefügt hat (andere bleiben)."""
        if not self.edit_allowed("edit"):
            return

        def show(present: dict) -> None:
            items = [
                {"key": "Header", "label": "Kopf- und Fußzeilen, Seitenzahlen", "detail": "von PDF Tool hinzugefügt", "count": int(present.get("Header", 0)), "checked": True, "unit": "Seiten"},
                {"key": "Watermark", "label": "Wasserzeichen", "detail": "von PDF Tool hinzugefügt", "count": int(present.get("Watermark", 0)), "checked": True, "unit": "Seiten"},
            ]
            if not any(item["count"] for item in items):
                self.app.notify("reader", "info", "Dieses Dokument hat keine Kopf-/Fußzeilen oder Wasserzeichen von PDF Tool.", title="Nichts zu entfernen", auto_hide=8000)
                return
            answer, data = self.app.dialogs.ask("checklist", "Kopf-/Fußzeile und Wasserzeichen entfernen", "", primary="Entfernen", close="Abbrechen", data={"items": items}, width=540)
            if answer != "primary":
                return
            kinds = [item["key"] for item in items if item["count"] and (data or {}).get(item["key"])]
            if kinds:
                self.run(lambda session: session.remove_marks(kinds), lambda count: self.edited(f"Von {count} {'Seite' if count == 1 else 'Seiten'} entfernt"), busy="")

        self.run(lambda session: session.marks_present(), show, refresh=False, priority=VIEW)

    # Schwärzen -------------------------------------------------------------------------------------------------------
    def _set_marks(self, marks: dict) -> None:
        self.redactMarks = marks
        self.redactCount = sum(len(items) for items in marks.values())

    def _add_marks(self, page: int, rects: list) -> int:
        marks = {key: list(items) for key, items in self.redactMarks.items()}
        added = 0
        for rect in rects:
            box = [float(v) for v in rect]
            if len(box) != 4 or box[2] - box[0] < 1 or box[3] - box[1] < 1:
                continue
            self._mark_serial += 1
            marks.setdefault(str(page), []).append({"id": f"m{self._mark_serial}", "page": page, "view": [round(v, 2) for v in box]})
            added += 1
        if added:
            self._set_marks(marks)
        return added

    @Slot(str)
    def setRedactMode(self, mode: str) -> None:  # noqa: N802
        if mode in ("area", "text"):
            self.redactMode = mode

    @Slot(int, "QVariantList")
    def addRedactArea(self, page: int, rect) -> None:  # noqa: N802
        """Bereich zum Schwärzen vormerken (Anzeige-Punkte) – angewendet wird erst mit »Schwärzen anwenden«."""
        if 0 <= page < self.pageCount:
            self._add_marks(page, [list(rect)])

    @Slot()
    def redactSelection(self) -> None:  # noqa: N802
        """Ausgewählten Text zum Schwärzen vormerken (je Zeile ein Bereich)."""
        if self._selection is None:
            return
        page, start, end = self._selection
        self.run(lambda session: session.selection_rects(page, start, end - start + 1), lambda rects: (self._add_marks(page, rects), self.clear_selection()), refresh=False, priority=VIEW)

    @Slot(int, str)
    def removeRedactMark(self, page: int, ident: str) -> None:  # noqa: N802
        marks = {key: [item for item in items if item["id"] != ident] for key, items in self.redactMarks.items()}
        self._set_marks({key: items for key, items in marks.items() if items})

    @Slot()
    def clearRedactMarks(self) -> None:  # noqa: N802
        self._set_marks({})

    @Slot()
    def searchRedact(self) -> None:  # noqa: N802
        """Suchen und schwärzen: Muster (IBAN, E-Mail, Telefon, Datum) und eigene Begriffe vormerken."""
        answer, data = self.app.dialogs.ask("redact_search", "Suchen und schwärzen", "", primary="Markieren", close="Abbrechen", data={"current": self.currentPage, "pageCount": self.pageCount}, width=580)
        if answer != "primary":
            return
        kinds = [str(kind) for kind in (data or {}).get("kinds") or []]
        terms = [line.strip() for line in str((data or {}).get("terms") or "").splitlines() if line.strip()]
        match_case = bool((data or {}).get("matchCase"))
        scope = [self.currentPage] if (data or {}).get("scope") == "current" else None
        if not kinds and not terms:
            return

        def done(found: list) -> None:
            if not found:
                self.app.notify("reader", "info", "Nichts gefunden – es wurde nichts markiert.", title="Suchen und schwärzen", auto_hide=8000)
                return
            counts = Counter(item["label"] or "Begriff" for item in found)
            for item in found:
                self._add_marks(item["page"], item["rects"])
            if self.tool != "redact":
                self.setTool("redact")
            self.goTo(found[0]["page"])
            summary = ", ".join(f"{label} {count}" for label, count in counts.most_common())
            self.app.notify("reader", "info", f"{len(found)} Fundstellen markiert ({summary}). Bitte prüfen – eine Markierung entfernt der Rechtsklick. Dann »Schwärzen anwenden«.", title="Suchen und schwärzen", actions=[("Schwärzen anwenden", self.applyRedaction)])

        self.run(lambda session: session.redact_find(kinds, terms, match_case, scope), done, refresh=False, busy="Dokument wird durchsucht …")

    @Slot()
    def applyRedaction(self) -> None:  # noqa: N802
        if not self.redactCount:
            self.app.notify("reader", "info", "Es ist noch nichts markiert. Bereiche aufziehen oder Text auswählen – oder »Suchen …«.", title="Schwärzen", auto_hide=8000)
            return
        if not self.edit_allowed("edit"):
            return
        pages = sorted({int(key) for key in self.redactMarks})
        count = self.redactCount
        where = f"{count} {'Bereich' if count == 1 else 'Bereiche'} auf {len(pages)} {'Seite' if len(pages) == 1 else 'Seiten'}"
        if not self.app.dialogs.confirm(
            "Markierte Inhalte endgültig schwärzen?",
            f"{where}: Text, Bildpunkte, Grafiken, Kommentare und Formularfelder darin werden aus dem Dokument entfernt – nicht nur abgedeckt. "
            "Rückgängig (Strg+Z) geht, solange das Dokument offen ist; nach dem Speichern sind die Inhalte endgültig entfernt.",
            "Schwärzen",
        ):
            return
        marks = [{"page": item["page"], "rect": item["view"]} for items in self.redactMarks.values() for item in items]

        def done(result: dict) -> None:
            self._set_marks({})
            parts = [f"{result['chars']} Zeichen"] if result.get("chars") else []
            parts += [f"{result[key]} {label}" for key, label in (("images", "Bilder"), ("paths", "Grafiken"), ("annotations", "Kommentare/Felder")) if result.get(key)]
            rasterized = f" Seite {', '.join(str(page) for page in result['rasterized'])} wurde als Bild geschwärzt (dort ist kein Text mehr auswählbar)." if result.get("rasterized") else ""
            self.edited("Geschwärzt")
            self.app.notify(
                "reader", "success",
                (f"Entfernt: {', '.join(parts)}." if parts else "Im markierten Bereich war nichts zu entfernen.") + rasterized + " Tipp: Mit »Dokument bereinigen« auch Metadaten und Anhänge entfernen.",
                title="Geschwärzt", actions=[("Dokument bereinigen …", self.cleanDocument), ("Speichern", self.saveDocument)],
            )
            self.loadAnnotations()
            self.loadFields()
            self.loadLinks()

        self.run(lambda session: session.redact_apply(marks), done, busy="Wird geschwärzt und geprüft …")

    # Stempel und Unterschrift -------------------------------------------------------------------------------------------
    @Slot(str)
    def setStampPreset(self, key: str) -> None:  # noqa: N802
        """Stempel wählen: eine Vorgabe oder »custom« (fragt nach dem Text)."""
        from tools.pdf_editor import stamps

        if key == "custom":
            answer, data = self.app.dialogs.ask("text_input", "Eigener Stempel", "Text des Stempels – höchstens 60 Zeichen.", primary="Übernehmen", close="Abbrechen", data={"label": "Text", "value": self.stampText, "placeholder": "z. B. GEBUCHT"})
            if answer != "primary":
                return
            text = " ".join(str((data or {}).get("value") or "").split())[: stamps.MAX_TEXT]
            if not text:
                return
            self.stampText = text
        elif key not in stamps.PRESETS:
            return
        self.stampPreset = key

    @Slot(str)
    def setStampSubtitle(self, value: str) -> None:  # noqa: N802
        """Zweite Zeile: »« (ohne), »{datum}«, »{datum} {zeit}« oder »custom« (fragt nach dem Text)."""
        if value == "custom":
            answer, data = self.app.dialogs.ask("text_input", "Zweite Zeile des Stempels", "Zum Beispiel ein Name oder Zeichen. {datum} und {zeit} werden beim Setzen ersetzt.", primary="Übernehmen", close="Abbrechen", data={"label": "Text", "value": self.stampSubtitle, "placeholder": "z. B. {datum} – M. Muster"})
            if answer != "primary":
                return
            value = " ".join(str((data or {}).get("value") or "").split())[:80]
        self.stampSubtitle = value

    @Slot(int, "QVariantList")
    def placeStamp(self, page: int, rect) -> None:  # noqa: N802
        """Stempel setzen: aufgezogener Rahmen oder – bei einem Klick – natürliche Größe um diese Stelle."""
        if not 0 <= page < self.pageCount or not self.edit_allowed("annotate"):
            return
        custom = self.stampPreset == "custom"
        if custom and not self.stampText:
            self.setStampPreset("custom")
            if not self.stampText:
                return
        spec = {"preset": "" if custom else self.stampPreset, "text": self.stampText, "subtitle": self.stampSubtitle, "color": self.toolColor}
        box = [float(v) for v in rect]
        self.run(lambda session: session.add_stamp(page, box, spec), lambda key: self._placed(key, "Stempel gesetzt"), busy="")

    def _signature_store(self):
        from storage import data_root
        from tools.pdf_editor import stamps

        return stamps.SignatureStore(data_root() / SIGNATURE_FILE)

    @Slot()
    def loadSignatures(self) -> None:  # noqa: N802
        self._load_signatures(ask=False)

    def _load_signatures(self, ask: bool) -> None:
        """Gespeicherte Unterschriften (und die nur für diese Sitzung) mit Vorschau laden; ``ask``: ohne
        Unterschrift gleich eine anlegen lassen."""
        store = self._signature_store()
        current = _SESSION_SIGNATURE[0]

        def work(_session) -> list[dict]:
            items = [{"id": item.ident, "label": item.label, "preview": signature_preview(item.signature), "aspect": round(item.signature.aspect, 3), "stored": True} for item in store.load()]
            if current is not None:
                items.append({"id": SESSION_SIGNATURE, "label": "Nur für diese Sitzung", "preview": signature_preview(current), "aspect": round(current.aspect, 3), "stored": False})
            return items

        def done(items: list) -> None:
            self.signatures = items
            if self.signatureChoice not in [item["id"] for item in items]:
                self.signatureChoice = items[0]["id"] if items else ""
            if ask and not items and self.tool == "signature":
                self.newSignature()

        self.run(work, done, refresh=False, priority=VIEW, key="signatures")

    @Slot()
    def newSignature(self) -> None:  # noqa: N802
        """Dialog »Unterschrift erstellen«: zeichnen oder ein Bild einlesen; auf Wunsch nur lokal speichern."""
        from tools.pdf_editor import stamps
        from tools.pdf_editor.errors import UnsupportedEdit as Refused

        stored = sum(1 for item in self.signatures if item.get("stored"))
        answer, data = self.app.dialogs.ask("signature", "Unterschrift erstellen", "", primary="Übernehmen", close="Abbrechen", data={"stored": stored, "limit": stamps.MAX_STORED}, width=640)
        if answer != "primary":
            if self.tool == "signature" and not self.signatures:
                self.setTool("select")
            return
        data = data or {}
        try:
            if data.get("mode") == "image":
                signature = stamps.Signature.from_dict(data.get("image") or {})
            else:
                signature = stamps.signature_from_strokes(data.get("strokes") or [], color=_hex_rgb(data.get("color")) or stamps.INK, pen=float(data.get("pen") or 2.6))
            if data.get("save"):
                choice = self._signature_store().add(signature, str(data.get("label") or "")).ident
            else:
                _SESSION_SIGNATURE[0] = signature
                choice = SESSION_SIGNATURE
        except (Refused, OSError) as exc:
            self.report(exc)
            return
        self.signatureChoice = choice
        if self.tool != "signature":
            self.setTool("signature")
        else:
            self._load_signatures(ask=False)
        self.app.set_status("Unterschrift bereit – in die Seite klicken oder einen Rahmen aufziehen.", "success")

    @Slot(result="QVariant")
    def pickSignatureImage(self):  # noqa: N802
        """Bild für eine Unterschrift wählen (aus dem Dialog): Vorschau und Daten – oder ``{error}``."""
        from tools.pdf_editor import stamps
        from tools.pdf_editor.errors import UnsupportedEdit as Refused

        path = self.reader.pick_image()
        if not path:
            return {}
        try:
            signature = stamps.signature_from_image(path)
        except Refused as exc:
            return {"error": str(exc)}
        return {"preview": signature_preview(signature), "data": signature.to_dict(), "aspect": round(signature.aspect, 3)}

    @Slot(str)
    def chooseSignature(self, ident: str) -> None:  # noqa: N802
        if any(item["id"] == ident for item in self.signatures):
            self.signatureChoice = ident

    @Slot(str)
    def deleteSignature(self, ident: str) -> None:  # noqa: N802
        item = next((entry for entry in self.signatures if entry["id"] == ident), None)
        if item is None:
            return
        if not self.app.dialogs.confirm("Unterschrift löschen?", "Die Unterschrift wird von diesem PC entfernt. Bereits gesetzte Unterschriften in Dokumenten bleiben, wie sie sind.", "Löschen"):
            return
        if ident == SESSION_SIGNATURE:
            _SESSION_SIGNATURE[0] = None
        else:
            try:
                self._signature_store().remove(ident)
            except OSError as exc:
                self.report(exc)
                return
        self._load_signatures(ask=False)

    @Slot(int, "QVariantList")
    def placeSignature(self, page: int, rect) -> None:  # noqa: N802
        if not 0 <= page < self.pageCount or not self.edit_allowed("annotate"):
            return
        signature = self._chosen_signature()
        if signature is None:
            self.newSignature()
            return
        data = signature.to_dict()
        box = [float(v) for v in rect]
        self.run(lambda session: session.add_signature(page, box, data), lambda key: self._placed(key, "Unterschrift gesetzt"), busy="")

    def _placed(self, key: str, title: str) -> None:
        """Nach dem Setzen: »Auswählen« mit dem neuen Stempel bzw. der Unterschrift ausgewählt (gleich verschieben
        und in der Größe ändern)."""
        self.edited(title)
        self._select_annotation = key
        self.setTool("select")
        self.loadAnnotations()

    def _chosen_signature(self):
        ident = self.signatureChoice
        if ident == SESSION_SIGNATURE:
            return _SESSION_SIGNATURE[0]
        stored = self._signature_store().get(ident) if ident else None
        return stored.signature if stored is not None else None

    # Links ---------------------------------------------------------------------------------------------------------------
    @Slot()
    def loadLinks(self) -> None:  # noqa: N802
        self._links_requested = True

        def done(items: list) -> None:
            by_page: dict[str, list] = {}
            for item in items:
                by_page.setdefault(str(item["page"]), []).append(item)
            self.linkPages = by_page

        self.run(lambda session: session.links(), done, refresh=False, priority=BACKGROUND, key="links")

    def _link(self, page: int, key: str) -> dict | None:
        return next((item for item in self.linkPages.get(str(page), []) if item["key"] == key), None)

    @Slot(int, str)
    def followLink(self, page: int, key: str) -> None:  # noqa: N802
        """Link anklicken: Seite anzeigen; eine Webadresse erst nach Rückfrage öffnen. Andere Aktionen nie."""
        link = self._link(page, key)
        if link is None:
            return
        if link["target"] >= 0:
            self.goTo(link["target"])
            return
        uri = link["uri"]
        if not uri:
            self.app.notify("reader", "info", "Dieser Link führt aus dem Dokument hinaus oder startet eine Aktion – PDF Tool führt so etwas nicht aus.", title="Link nicht geöffnet", auto_hide=8000)
            return
        mail = uri.lower().startswith("mailto:")
        if not self.app.dialogs.confirm("E-Mail schreiben?" if mail else "Webadresse öffnen?", (f"Der Link öffnet eine neue E-Mail an {uri[7:]}." if mail else f"Der Link führt zu {uri}") + " Öffnen Sie nur Adressen aus Quellen, denen Sie vertrauen.", "Öffnen", danger=False):
            return
        from .. import files

        files.open_url(uri)

    def _ask_link(self, current: dict, title: str) -> tuple[int, str] | None:
        answer, data = self.app.dialogs.ask("link", title, "", primary="Übernehmen", close="Abbrechen", data={**current, "pageCount": self.pageCount}, width=520)
        if answer != "primary":
            return None
        data = data or {}
        if data.get("kind") == "web":
            uri = str(data.get("uri") or "").strip()
            return (-1, uri) if uri else None
        try:
            number = int(str(data.get("page") or "").strip())
        except ValueError:
            self.app.notify("reader", "warning", "Bitte eine Seitenzahl eingeben.", title=title)
            return None
        return max(0, min(self.pageCount - 1, number - 1)), ""

    @Slot(int, "QVariantList")
    def addLinkAt(self, page: int, rect) -> None:  # noqa: N802
        """Link im aufgezogenen Bereich: zu einer Seite dieses Dokuments oder zu einer Webadresse."""
        box = [float(v) for v in rect]
        if not 0 <= page < self.pageCount or box[2] - box[0] < 4 or box[3] - box[1] < 4 or not self.edit_allowed("annotate"):
            return
        values = self._ask_link({"kind": "page", "page": min(self.pageCount, self.currentPage + 2), "uri": ""}, "Link hinzufügen")
        if values is None:
            return
        target, uri = values
        self.run(lambda session: session.add_link(page, box, target, uri), lambda _key: (self.edited("Link hinzugefügt"), self.loadLinks()), busy="")

    @Slot(int, str)
    def editLink(self, page: int, key: str) -> None:  # noqa: N802
        link = self._link(page, key)
        if link is None or not self.edit_allowed("annotate"):
            return
        current = {"kind": "web" if link["uri"] or link["target"] < 0 else "page", "page": link["target"] + 1 if link["target"] >= 0 else self.currentPage + 1, "uri": link["uri"]}
        values = self._ask_link(current, "Link bearbeiten")
        if values is None:
            return
        target, uri = values
        self.run(lambda session: session.update_link(key, target, uri), lambda _r: (self.edited("Link geändert"), self.loadLinks()), busy="")

    @Slot(int, str)
    def removeLink(self, page: int, key: str) -> None:  # noqa: N802
        if self._link(page, key) is None or not self.edit_allowed("annotate"):
            return
        self.run(lambda session: session.delete_link(key), lambda _r: (self.edited("Link entfernt"), self.loadLinks()), busy="")

    # Lesezeichen bearbeiten -----------------------------------------------------------------------------------------------
    def _outline_entry(self, key: str) -> dict | None:
        return next((entry for entry in self._outline_entries if entry["key"] == key), None)

    def _outline_op(self, func, title: str) -> None:
        if not self.edit_allowed("edit"):
            return
        self.run(func, lambda _r: (self.edited(title), self.load_outline()), busy="")

    @Slot(str, bool)
    def addBookmark(self, after: str, child: bool) -> None:  # noqa: N802
        """Lesezeichen zur aktuellen Seite – hinter ``after`` (Schlüssel; leer: ans Ende) bzw. als Unterpunkt."""
        if not self.edit_allowed("edit"):
            return
        page = self.currentPage
        answer, data = self.app.dialogs.ask("text_input", "Lesezeichen hinzufügen", f"Das Lesezeichen führt zu Seite {page + 1}.", primary="Hinzufügen", close="Abbrechen", data={"label": "Titel", "value": "", "placeholder": f"Seite {page + 1}"})
        if answer != "primary":
            return
        title = str((data or {}).get("value") or "").strip()
        index = int(after) if after.isdigit() else -1
        self.reader.showLeftPanel("outline")
        self._outline_op(lambda session: session.add_bookmark(title, page, index, child), "Lesezeichen hinzugefügt")

    @Slot(str)
    def renameBookmark(self, key: str) -> None:  # noqa: N802
        entry = self._outline_entry(key)
        if entry is None:
            return
        answer, data = self.app.dialogs.ask("text_input", "Lesezeichen umbenennen", "", primary="Umbenennen", close="Abbrechen", data={"label": "Titel", "value": entry["title"], "placeholder": entry["title"]})
        title = str((data or {}).get("value") or "").strip()
        if answer == "primary" and title and title != entry["title"]:
            self._outline_op(lambda session: session.rename_bookmark(int(key), title), "Lesezeichen umbenannt")

    @Slot(str)
    def bookmarkCurrentPage(self, key: str) -> None:  # noqa: N802
        """Ziel des Lesezeichens auf die angezeigte Seite setzen."""
        if self._outline_entry(key) is not None:
            page = self.currentPage
            self._outline_op(lambda session: session.set_bookmark_page(int(key), page), f"Lesezeichen führt zu Seite {page + 1}")

    @Slot(str, str)
    def moveBookmark(self, key: str, direction: str) -> None:  # noqa: N802
        if self._outline_entry(key) is not None and direction in ("up", "down", "in", "out"):
            self._outline_op(lambda session: session.move_bookmark(int(key), direction), "Lesezeichen verschoben")

    @Slot(str)
    def deleteBookmark(self, key: str) -> None:  # noqa: N802
        entry = self._outline_entry(key)
        if entry is None:
            return
        if entry["hasChildren"] and not self.app.dialogs.confirm(f"»{entry['title']}« samt Unterpunkten löschen?", "Das Lesezeichen und alle Lesezeichen darunter werden entfernt. Rückgängig (Strg+Z) holt sie zurück.", "Löschen"):
            return
        self._outline_op(lambda session: session.delete_bookmark(int(key)), "Lesezeichen gelöscht")

    # Seiten zuschneiden --------------------------------------------------------------------------------------------------
    @Slot("QVariantList")
    def cropPages(self, indexes) -> None:  # noqa: N802
        """Dialog »Seiten zuschneiden«: Ränder in Millimetern (oder an den Inhalt angepasst) für alle,
        die aktuelle, die ausgewählten oder angegebene Seiten; auch »Zuschnitt zurücksetzen«."""
        from tools.pdf_editor import pages as page_ops

        chosen = sorted({int(i) for i in indexes or [] if 0 <= int(i) < self.pageCount})
        probe = chosen[0] if chosen else self.currentPage

        def show(auto: list) -> None:
            answer, data = self.app.dialogs.ask(
                "crop", "Seiten zuschneiden", "", primary="Übernehmen", close="Abbrechen",
                data={"auto": [round(value / MM, 1) for value in auto], "selected": len(chosen), "current": self.currentPage, "pageCount": self.pageCount}, width=580,
            )
            if answer != "primary":
                return
            data = data or {}
            scope = data.get("scope")
            try:
                if scope == "selected" and chosen:
                    targets = chosen
                elif scope == "current":
                    targets = [self.currentPage]
                elif scope == "range":
                    targets = page_ops.parse_pages(str(data.get("range") or ""), self.pageCount)
                else:
                    targets = list(range(self.pageCount))
            except ValueError as exc:
                self.app.notify("reader", "warning", str(exc), title="Seiten zuschneiden")
                return
            if data.get("reset"):
                self._page_op(lambda session: session.reset_crop(targets), "Zuschnitt zurückgesetzt")
                return
            margins = [max(0.0, float(value or 0)) * MM for value in (data.get("margins") or [0, 0, 0, 0])[:4]]
            if len(margins) == 4 and any(margins):
                self._page_op(lambda session: session.crop(targets, margins), "Seiten zugeschnitten" if len(targets) > 1 else "Seite zugeschnitten")

        self.run(lambda session: session.content_margins(probe), show, refresh=False, busy="Ränder werden erkannt …")

    # Rückgängig, Speichern ------------------------------------------------------------------------------------------
    @Slot()
    def undo(self) -> None:
        if self.undoText and not self.ocrRunning:
            self.run(lambda session: session.undo(), lambda title: (self.edited(f"Rückgängig: {title}" if title else ""), self._reload_tool()))

    @Slot()
    def redo(self) -> None:
        if self.redoText and not self.ocrRunning:
            self.run(lambda session: session.redo(), lambda title: (self.edited(f"Wiederholt: {title}" if title else ""), self._reload_tool()))

    def _reload_tool(self) -> None:
        if self.tool == "editText":
            self.loadBlocks(self.blocksPage if self.blocksPage >= 0 else self.currentPage)
        elif self.tool == "image":
            self.loadImages(self.imagesPage if self.imagesPage >= 0 else self.currentPage)
        elif self.tool == "form":
            self.loadFields()
        elif self.tool == "formDesign":
            self.loadDesign()
        if self.tool == "signature":
            self._load_signatures(ask=False)
        self.loadAnnotations()
        self.loadAttachments()
        self.load_outline()

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
                _log("save").info("Gespeichert (%s): %d KB, %d Seiten geprüft, Sicherung %s, %d ms", _where(result["path"]), max(1, result["size"] // 1024), result["checked"], "ja" if result.get("backup") else "nein", (time.monotonic() - started) * 1000)
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
            _log("save").warning("Speichern fehlgeschlagen (%s): %s", where, exc.log_text())
            actions = [("Speichern unter …", self.saveDocumentAs)] if exc.save_as else []
            self.app.notify("reader", "error", str(exc), title="Speichern nicht möglich", actions=actions)
            return
        if isinstance(exc, (EditorError, OSError)):
            _log("save").warning("Speichern fehlgeschlagen (%s): %s%s", where, type(exc).__name__, _os_codes(exc))
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
        _log("save").warning("Sitzungssicherung fehlgeschlagen (%s): %s%s", _where(self.path), type(exc).__name__, _os_codes(exc))

    # Drucken ------------------------------------------------------------------------------------------------------
    @Slot()
    def printDocument(self) -> None:  # noqa: N802
        self.printPages([])

    @Slot("QVariantList")
    def printPages(self, pages: list) -> None:  # noqa: N802
        """Drucken – ``pages``: ausgewählte Seiten (im Dialog als »Auswahl« vorgewählt), leer: wie üblich."""
        if not (self.permissions or {}).get("print", True):
            self.app.notify("reader", "warning", "Die Berechtigungen dieses PDFs erlauben kein Drucken.", title="Drucken nicht erlaubt")
            return
        from .printing import print_document

        print_document(self, [int(page) for page in pages or []])

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
        if self._ocr_cancel is not None:
            self._ocr_cancel.set()  # beendet einen laufenden Tesseract-Prozess
        for timer in ("recovery", "nudge", "saved", "links"):
            self.app.timers.cancel(f"reader:{timer}:{self.ident}")
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


def field_changes(item: dict, data: dict) -> dict:
    """Aus dem Dialog »Feldeigenschaften« nur die geänderten Werte (Namen wie ``formdesign.PROPERTIES``)."""
    kind = item.get("kind", "")
    wanted: dict = {"name": str(data.get("name", item["name"].rsplit(".", 1)[-1])), "tooltip": str(data.get("tooltip", item["tooltip"])),
                    "required": bool(data.get("required", item["required"])), "readOnly": bool(data.get("readOnly", item["readOnly"])),
                    "border": bool(data.get("border", item["border"])), "background": bool(data.get("background", item["background"]))}
    current: dict = {"name": item["name"].rsplit(".", 1)[-1], "tooltip": item["tooltip"], "required": item["required"], "readOnly": item["readOnly"],
                     "border": item["border"], "background": item["background"]}
    if kind == "text":
        wanted["multiline"], current["multiline"] = bool(data.get("multiline", item["multiline"])), item["multiline"]
        try:
            wanted["maxLength"] = max(0, int(str(data.get("maxLength", item["maxLength"])).strip() or 0))
        except ValueError:
            wanted["maxLength"] = item["maxLength"]
        current["maxLength"] = item["maxLength"]
    if kind in ("text", "combo", "list"):
        wanted["fontSize"], current["fontSize"] = float(data.get("fontSize", item["fontSize"]) or 0), float(item["fontSize"])
    if kind in ("text", "combo"):
        wanted["align"], current["align"] = str(data.get("align", item["align"])), item["align"]
    if kind in ("combo", "list"):
        lines = data.get("options", item["options"])
        if isinstance(lines, str):
            lines = lines.splitlines()
        wanted["options"] = [" ".join(str(line).split()) for line in lines if str(line).strip()]
        current["options"] = list(item["options"])
    if kind in ("checkbox", "radio"):
        wanted["export"], current["export"] = str(data.get("export", item["export"])).strip(), item["export"]
    return {name: value for name, value in wanted.items() if value != current[name]}


SESSION_SIGNATURE = "sitzung"  # Kennung der nicht gespeicherten Unterschrift
_SESSION_SIGNATURE: list = [None]  # nur im Arbeitsspeicher, bis PDF Tool beendet wird (für alle Tabs)


def signature_preview(signature, height: int = 96) -> str:
    """Vorschau einer Unterschrift als PNG (data-URL, durchsichtiger Hintergrund) – geglättet gezeichnet."""
    import base64
    import io

    from PIL import Image, ImageDraw

    scale = height / max(0.01, signature.height)
    width = max(8, min(900, round(signature.width * scale)))
    if signature.mask:
        with Image.open(io.BytesIO(signature.mask)) as loaded:
            mask = loaded.convert("L").resize((width, height), Image.LANCZOS)
    else:
        factor = 3
        big = Image.new("L", (width * factor, height * factor), 0)
        draw = ImageDraw.Draw(big)
        pen = max(1, round(signature.pen * height * factor))
        for stroke in signature.strokes:
            points = [(x * scale * factor, y * scale * factor) for x, y in stroke]
            if len(points) > 1:
                draw.line(points, fill=255, width=pen, joint="curve")
            for x, y in (points[0], points[-1]):
                draw.ellipse([x - pen / 2, y - pen / 2, x + pen / 2, y + pen / 2], fill=255)
        mask = big.resize((width, height), Image.LANCZOS)
    image = Image.new("RGBA", (width, height), (*signature.color, 0))
    image.putalpha(mask)
    out = io.BytesIO()
    image.save(out, format="PNG")
    return "data:image/png;base64," + base64.b64encode(out.getvalue()).decode("ascii")


def _hex_rgb(value) -> tuple[int, int, int] | None:
    text = str(value or "").lstrip("#")
    if len(text) == 8:  # #AARRGGBB aus QML
        text = text[2:]
    try:
        return (int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16)) if len(text) == 6 else None
    except ValueError:
        return None


def _size_label(size: int) -> str:
    if size < 0:
        return ""
    if size >= 1024 * 1024:
        return f"{size / 1024 / 1024:.1f} MB".replace(".", ",")
    return f"{max(1, round(size / 1024))} KB" if size else "0 KB"


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


def _log(category: str = "pdf"):
    """Logger eines festen Protokollbereichs (``diagnostics.applog``: pdf, save, render, ocr …) – ohne Inhalte."""
    from diagnostics.applog import get

    return get(category)


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


def _overlap(rect, area) -> float:
    """Anteil von ``rect``, der in ``area`` liegt (0 … 1)."""
    x0, y0 = max(rect[0], area[0]), max(rect[1], area[1])
    x1, y1 = min(rect[2], area[2]), min(rect[3], area[3])
    if x1 <= x0 or y1 <= y0:
        return 0.0
    size = max(1e-6, (rect[2] - rect[0]) * (rect[3] - rect[1]))
    return (x1 - x0) * (y1 - y0) / size
