"""Ein geöffneter Text (in QML: ``Reader.current`` mit ``kind`` »text«): Seiten, Schreibmarke, Auswahl, Formate,
Formatvorlagen, Suchen, Speichern.

Der Text lebt im Textkern (LibreOfficeKit in einem eigenen Prozess). Tasten, Klicks und Befehle gehen dorthin; der
Kern meldet, was neu zu zeichnen ist (Kacheln), wo die Schreibmarke steht, was ausgewählt ist und wie die Knöpfe
stehen (fett, Schriftart, Formatvorlage …). Gezeichnet wird in ``TextCanvas``. Wie eine Tabelle gehört der Tab zum
Reader (gleiche Tab-Leiste, Schließen, »Zuletzt verwendet«, letzte Sitzung); dafür hat ``TextController`` dieselben
Grundzüge wie ein PDF-Dokument (``ident``, ``name``, ``path``, ``dirty``, ``save``, ``shutdown``).
"""

from __future__ import annotations

import base64
import json
import logging
import tempfile
from pathlib import Path
from typing import Callable

from PySide6.QtCore import Property, QObject, QUrl, Signal, Slot

from tools.text import engine as text

from ..base import Observable, prop
from .service import INPUT, NORMAL, TILE

MAX_ZOOM, MIN_ZOOM = 400, 25
ZOOM_STEPS = (25, 50, 75, 90, 100, 110, 125, 150, 175, 200, 250, 300, 400)
SAVE_FILTER = (
    "Word-Dokument (*.docx);;OpenDocument-Text (*.odt);;Rich Text (*.rtf);;Word 97–2003 (*.doc)"
)
SAVE_SUFFIXES = (".docx", ".odt", ".rtf", ".doc")
# Formatvorlagen: Name in LibreOffice → Name in der Oberfläche (die Seitenleiste zeigt die ersten vier wie im Design)
STYLES = (
    ("Heading 1", "Überschrift 1"),
    ("Heading 2", "Überschrift 2"),
    ("Standard", "Standard"),
    ("Quotations", "Zitat"),
    ("Heading 3", "Überschrift 3"),
    ("Title", "Titel"),
    ("Subtitle", "Untertitel"),
    ("Text body", "Textkörper"),
)
STYLE_NAMES = {label: name for name, label in STYLES}
# Was LibreOffice für die Vorlagen meldet (deutsche Oberfläche) → Name in der Oberfläche
STYLE_LABELS = {"Default Paragraph Style": "Standard", "Text Body": "Textkörper", "Blockzitat": "Zitat", "Quotations": "Zitat"}
# Ereignisse von LibreOfficeKit (LibreOfficeKitEnums.h)
INVALIDATE_TILES, INVALIDATE_CURSOR, TEXT_SELECTION, CURSOR_VISIBLE = 0, 1, 2, 5
GRAPHIC_SELECTION, HYPERLINK_CLICKED, STATE_CHANGED, SEARCH_NOT_FOUND = 6, 7, 8, 12
DOCUMENT_SIZE_CHANGED, MOUSE_POINTER, ERROR = 13, 18, 22
# Tasten von LibreOffice (com.sun.star.awt.Key) und Umschalter
KEY_DELETE = 1286
# Kennzeichen unserer Kopien in der Zwischenablage: Beim Beenden ersetzt der Reader sie durch Qt-eigene Daten
# (``ReaderController._release_clipboard``), sonst stürzt der Abbau der Anwendung ab
TEXT_CLIP_FORMAT = "application/x-novadesk-text"
MOD_SHIFT, MOD_CTRL, MOD_ALT = 0x1000, 0x2000, 0x4000
# Seiten: A4 in 1/100 mm; Ränder in 1/100 mm (Normal wie in Word: 2,5 cm, Schmal 1,27 cm, Breit 2,5/5 cm)
MARGINS = {"normal": (2500, 2500, 2500, 2500), "narrow": (1270, 1270, 1270, 1270), "wide": (5080, 5080, 2540, 2540)}


def _log():
    return logging.getLogger("pdftool.text")


def _rect(text: str) -> list[int]:
    """»x, y, w, h« (auch mit weiteren Angaben dahinter) → [x, y, w, h]; leer bzw. »EMPTY« → []."""
    parts = [part.strip() for part in text.split(",")]
    if len(parts) < 4:
        return []
    try:
        return [int(float(part)) for part in parts[:4]]
    except ValueError:
        return []


def _rects(text: str) -> list[list[int]]:
    return [rect for rect in (_rect(part) for part in text.split(";")) if rect and rect[2] > 0 and rect[3] > 0]


def _hex(value) -> str:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return ""
    return "" if number < 0 else "#%06x" % (number & 0xFFFFFF)


class TextController(Observable):
    _own_copy: tuple | None = None  # (Text, Dokument, Start, Inhalt) der letzten Kopie aus Novadesk
    nameChanged, name = prop(str, "name", "")
    pathChanged, path = prop(str, "path", "")
    dirtyChanged, dirty = prop(bool, "dirty", False)
    savingChanged, saving = prop(bool, "saving", False)
    readyChanged, ready = prop(bool, "ready", False)
    zoomChanged, zoom = prop(int, "zoom", 100)
    docWidthChanged, docWidth = prop(int, "docWidth", 12474)  # Twips, alle Seiten mit Abständen
    docHeightChanged, docHeight = prop(int, "docHeight", 17406)
    pagesChanged, pages = prop(list, "pages", [])  # [[x, y, Breite, Höhe]] in Twips
    cursorChanged, cursor = prop(list, "cursor", [])  # Schreibmarke [x, y, Breite, Höhe]
    cursorVisibleChanged, cursorVisible = prop(bool, "cursorVisible", True)
    selectionChanged, selection = prop(list, "selection", [])  # [[x, y, Breite, Höhe]]
    graphicChanged, graphic = prop(list, "graphic", [])  # ausgewähltes Bild bzw. Objekt
    boldChanged, bold = prop(bool, "bold", False)
    italicChanged, italic = prop(bool, "italic", False)
    underlineChanged, underline = prop(bool, "underline", False)
    strikeChanged, strike = prop(bool, "strike", False)
    fontNameChanged, fontName = prop(str, "fontName", "")
    fontSizeChanged, fontSize = prop(str, "fontSize", "")
    fontColorChanged, fontColor = prop(str, "fontColor", "")
    alignChanged, align = prop(str, "align", "left")
    bulletsChanged, bullets = prop(bool, "bullets", False)
    numberingChanged, numbering = prop(bool, "numbering", False)
    styleNameChanged, styleName = prop(str, "styleName", "")
    canUndoChanged, canUndo = prop(bool, "canUndo", False)
    canRedoChanged, canRedo = prop(bool, "canRedo", False)
    canCopyChanged, canCopy = prop(bool, "canCopy", False)
    trackChangesChanged, trackChanges = prop(bool, "trackChanges", False)
    spellingChanged, spelling = prop(bool, "spelling", True)
    marksChanged, marks = prop(bool, "marks", False)  # Formatierungszeichen
    pageTextChanged, pageText = prop(str, "pageText", "")  # »Seite 1 von 1«
    wordTextChanged, wordText = prop(str, "wordText", "")  # »58 Wörter«
    languageTextChanged, languageText = prop(str, "languageText", "")  # »Deutsch«
    landscapeChanged, landscape = prop(bool, "landscape", False)
    sidebarChanged, sidebar = prop(bool, "sidebar", True)  # Formatvorlagen rechts (wie im Design offen)
    pointerChanged, pointer = prop(str, "pointer", "")  # Mauszeiger über dem Text (»text«, »hand« …)
    findResultChanged, findResult = prop(str, "findResult", "")

    tilesInvalidated = Signal(int, int, int, int)  # Twips; Breite 0 = alles
    caretMoved = Signal()  # Schreibmarke sichtbar machen (nach Tasten und Suchen)
    findRequested = Signal()  # Strg+F: Suchleiste zeigen
    contextMenuRequested = Signal()

    def __init__(self, reader, service, ident: str, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.reader = reader
        self.app = reader.app
        self.service = service
        self.ident = ident
        self.sourcePath = ""  # wie ein PDF-Dokument ohne umgewandelte Quelle
        self.panels: dict = {}
        self.currentPage = 0
        self.pageCount = 0
        self.isText = True
        self.session = None  # kein PDF (der Reader rendert für Texte keine Seiten)
        self.doc = 0  # Nummer im Textkern
        self.generation = 0
        self.password: str | None = None
        self._closed = False
        self._follow = False  # nach Tasten: die Schreibmarke im Blick behalten
        self._move: tuple | None = None  # Mausbewegung, die noch geschickt werden soll
        self._move_busy = False
        self._save_then: list[Callable[[bool], None]] = []
        service.lost.connect(self._engine_lost)
        service.event.connect(self._on_event)

    # Gemeinsame Grundzüge mit PDF-Dokumenten (für den Reader) ---------------------------------------------------
    @property
    def busy_saving(self) -> bool:
        return self.saving

    def goTo(self, _page: int) -> None:  # noqa: N802
        pass

    def write_recovery_now(self) -> None:
        pass

    # Öffnen ----------------------------------------------------------------------------------------------------------
    def open(self, path: str, done: Callable[[], None], failed: Callable[[BaseException], None], password: str | None = None) -> None:
        """Datei im Textkern öffnen (``path`` leer: neuer Text). ``done``/``failed`` im GUI-Thread."""
        self.path = path
        self.name = Path(path).name if path else self.name or "Dokument1.docx"
        self.password = password
        args: dict = {"path": str(Path(path).resolve()) if path else "", "language": "de-DE"}
        if password:
            args["password"] = password

        def opened(result: dict) -> None:
            if self._closed:
                self.service.submit("close", {"doc": result["doc"]})
                return
            self.doc = int(result["doc"])
            self.generation = self.service.generation
            self._apply_size(result)
            for kind, payload in self.service.claim(self.generation, self.doc):
                self._on_event(self.generation, self.doc, kind, payload)
            self.ready = True
            done()

        self.service.submit("open", args, opened, failed)

    def _call(self, command: str, args: dict | None = None, done: Callable | None = None, failed: Callable | None = None,
              *, quiet: bool = False, priority: int = NORMAL) -> None:
        """Befehl für dieses Dokument (Nummer ergänzt). Fehler: Hinweis, außer ``quiet``."""
        if self._closed or not self.doc:
            return
        payload = {"doc": self.doc}
        payload.update(args or {})

        def error(exc: BaseException) -> None:
            if failed is not None:
                failed(exc)
            if quiet or self._closed or isinstance(exc, text.EngineGone):
                return
            message = str(exc) if isinstance(exc, text.TextError) else "Das hat nicht geklappt."
            self.app.notify("reader", "warning", message, title=self.name, auto_hide=8000)

        def finished(result) -> None:
            if not self._closed and done is not None:
                done(result)

        self.service.submit(command, payload, finished, error, generation=self.generation, priority=priority)

    def uno(self, command: str, args: dict | None = None, *, follow: bool = False) -> None:
        """Befehl von LibreOffice (».uno:Bold«) mit Argumenten {Name: (Typ, Wert)}."""
        if follow:
            self._follow = True
        values = {key: {"type": kind, "value": value} for key, (kind, value) in (args or {}).items()}
        self._call("uno", {"command": command, "args": values}, priority=INPUT)

    # Ereignisse des Kerns ----------------------------------------------------------------------------------------
    def _on_event(self, generation: int, doc: int, kind: int, payload: str) -> None:
        if self._closed or doc != self.doc or generation != self.generation:
            return
        if kind == INVALIDATE_TILES:
            rect = _rect(payload) if payload.strip() != "EMPTY" else []
            if rect:
                self.tilesInvalidated.emit(*rect)
            else:
                self.tilesInvalidated.emit(0, 0, 0, 0)
        elif kind == INVALIDATE_CURSOR:
            rect = payload
            if payload.lstrip().startswith("{"):
                try:
                    rect = str(json.loads(payload).get("rectangle") or "")
                except ValueError:
                    rect = ""
            values = _rect(rect)
            if values:
                self.cursor = values
                if self._follow:
                    self._follow = False
                    self.caretMoved.emit()
        elif kind == CURSOR_VISIBLE:
            self.cursorVisible = payload.strip() == "true"
        elif kind == TEXT_SELECTION:
            self.selection = _rects(payload)
        elif kind == GRAPHIC_SELECTION:
            rect = _rect(payload) if not payload.startswith("EMPTY") else []
            self.graphic = rect if rect and rect[2] > 0 and rect[3] > 0 else []
        elif kind == STATE_CHANGED:
            self._state(payload)
        elif kind == DOCUMENT_SIZE_CHANGED:
            self._call("size", {}, self._apply_size, quiet=True)
        elif kind == SEARCH_NOT_FOUND:
            self.findResult = "Nicht gefunden"
        elif kind == MOUSE_POINTER:
            self.pointer = payload.strip()
        elif kind == HYPERLINK_CLICKED:
            self._open_link(payload.strip())
        elif kind == ERROR:
            _log().info("Textkern meldet: %s", payload[:300])

    def _apply_size(self, data: dict) -> None:
        if not isinstance(data, dict):
            return
        self.docWidth = int(data.get("width") or self.docWidth)
        self.docHeight = int(data.get("height") or self.docHeight)
        pages = [list(page) for page in data.get("pages") or []]
        if pages:
            self.pages = pages
            self.pageCount = len(pages)
            self.landscape = pages[0][2] > pages[0][3]

    def _state(self, payload: str) -> None:
        if payload.lstrip().startswith("{"):
            try:
                data = json.loads(payload)
            except ValueError:
                return
            name, value = str(data.get("commandName") or ""), data.get("state")
            value = value if isinstance(value, str) else json.dumps(value)
        else:
            name, _sep, value = payload.partition("=")
        flags = {".uno:Bold": "bold", ".uno:Italic": "italic", ".uno:Underline": "underline", ".uno:Strikeout": "strike",
                 ".uno:DefaultBullet": "bullets", ".uno:DefaultNumbering": "numbering", ".uno:TrackChanges": "trackChanges",
                 ".uno:SpellOnline": "spelling", ".uno:ControlCodes": "marks"}
        if name in flags:
            setattr(self, flags[name], value == "true")
        elif name == ".uno:CharFontName":
            self.fontName = value
        elif name == ".uno:FontHeight":
            size = value.strip()
            self.fontSize = size[:-2] if size.endswith(".0") else size
        elif name in (".uno:Color", ".uno:FontColor"):
            self.fontColor = _hex(value)
        elif name in (".uno:LeftPara", ".uno:CenterPara", ".uno:RightPara", ".uno:JustifyPara"):
            if value == "true":
                self.align = {".uno:LeftPara": "left", ".uno:CenterPara": "center", ".uno:RightPara": "right"}.get(name, "justify")
        elif name == ".uno:StyleApply":
            self.styleName = STYLE_LABELS.get(value, value)
        elif name == ".uno:ModifiedStatus":
            was = self.dirty
            self.dirty = value == "true"
            if was != self.dirty:
                self.reader.tab_changed(self)
        elif name == ".uno:Undo":
            self.canUndo = value == "enabled"
        elif name == ".uno:Redo":
            self.canRedo = value == "enabled"
        elif name == ".uno:Copy":
            self.canCopy = value == "enabled"
        elif name == ".uno:StatePageNumber":
            self.pageText = value.split(" (")[0].strip()
        elif name == ".uno:StateWordCount":
            self.wordText = value.split(",")[0].strip()
        elif name == ".uno:LanguageStatus":
            self.languageText = value.split(";")[0].split(" (")[0].strip()

    def _open_link(self, url: str) -> None:
        from PySide6.QtGui import QDesktopServices

        if url.lower().startswith(("http://", "https://", "mailto:")):
            QDesktopServices.openUrl(QUrl(url))

    # Eingaben (vom Zeichenbereich) ----------------------------------------------------------------------------------
    def key(self, char: int, code: int) -> None:
        self._follow = True
        self._call("key", {"char": char, "code": code}, quiet=True, priority=INPUT)

    def type_text(self, value: str) -> None:
        if value:
            self._follow = True
            self._call("text", {"text": value}, quiet=True, priority=INPUT)

    def mouse(self, kind: int, x: int, y: int, count: int = 1, buttons: int = 1, mods: int = 0) -> None:
        """Maus in Twips. Bewegungen werden zusammengefasst (höchstens eine unterwegs, die neueste gewinnt)."""
        if kind == 2:
            self._move = (x, y, count, buttons, mods)
            if not self._move_busy:
                self._send_move()
            return
        self._move = None
        self._call("mouse", {"type": kind, "x": x, "y": y, "count": count, "buttons": buttons, "mods": mods}, quiet=True, priority=INPUT)

    def _send_move(self) -> None:
        move, self._move = self._move, None
        if move is None:
            self._move_busy = False
            return
        self._move_busy = True
        x, y, count, buttons, mods = move
        self._call("mouse", {"type": 2, "x": x, "y": y, "count": count, "buttons": buttons, "mods": mods},
                   lambda _result: self._send_move(), lambda _exc: setattr(self, "_move_busy", False), quiet=True, priority=INPUT)

    def graphic_drag(self, kind: int, x: int, y: int) -> None:
        """Bild verschieben bzw. Größe ändern: Anfang (0) und Ende (1) des Ziehens in Twips."""
        self._call("graphic", {"type": kind, "x": x, "y": y}, quiet=True, priority=INPUT)

    def request_tile(self, args: dict, done: Callable[[bytes], None], failed: Callable[[BaseException], None]) -> None:
        self._call("tile", args, done, failed, quiet=True, priority=TILE)

    def set_visible_area(self, x: int, y: int, w: int, h: int) -> None:
        self._call("visible", {"x": x, "y": y, "w": w, "h": h}, quiet=True)

    def set_client_zoom(self, tile_px: int, tile_twips: int) -> None:
        self._call("zoom", {"pw": tile_px, "ph": tile_px, "tw": tile_twips, "th": tile_twips}, quiet=True)

    # Formate ---------------------------------------------------------------------------------------------------------
    @Slot(str)
    def toggle(self, key: str) -> None:
        commands = {"bold": ".uno:Bold", "italic": ".uno:Italic", "underline": ".uno:Underline", "strike": ".uno:Strikeout",
                    "bullets": ".uno:DefaultBullet", "numbering": ".uno:DefaultNumbering", "superscript": ".uno:SuperScript",
                    "subscript": ".uno:SubScript", "trackChanges": ".uno:TrackChanges", "spelling": ".uno:SpellOnline",
                    "marks": ".uno:ControlCodes", "indent": ".uno:IncrementIndent", "outdent": ".uno:DecrementIndent",
                    "clear": ".uno:ResetAttributes"}
        if key in commands:
            self.uno(commands[key])

    @Slot(str)
    def setAlign(self, kind: str) -> None:  # noqa: N802
        command = {"left": ".uno:LeftPara", "center": ".uno:CenterPara", "right": ".uno:RightPara", "justify": ".uno:JustifyPara"}.get(kind)
        if command:
            self.align = kind
            self.uno(command)

    @Slot(str)
    def setFont(self, name: str) -> None:  # noqa: N802
        if name:
            self.fontName = name
            self.uno(".uno:CharFontName", {"CharFontName.FamilyName": ("string", name)})

    @Slot(str)
    def setFontSize(self, size: str) -> None:  # noqa: N802
        try:
            value = float(str(size).replace(",", "."))
        except ValueError:
            return
        if 1 <= value <= 999:
            self.fontSize = str(size)
            self.uno(".uno:FontHeight", {"FontHeight.Height": ("float", value)})

    @Slot(str)
    def setFontColor(self, color: str) -> None:  # noqa: N802
        value = int(color.lstrip("#"), 16) if color else -1
        self.fontColor = color
        self.uno(".uno:Color", {"Color": ("long", value)})

    @Slot(str)
    def applyStyle(self, label: str) -> None:  # noqa: N802
        """Formatvorlage (Name wie in der Oberfläche, z. B. »Überschrift 1«) auf den Absatz anwenden."""
        name = STYLE_NAMES.get(label, label)
        if name:
            self.styleName = label
            self.uno(".uno:StyleApply", {"Style": ("string", name), "FamilyName": ("string", "ParagraphStyles")})

    @Slot(result=list)
    def styleList(self) -> list:  # noqa: N802
        return [label for _name, label in STYLES]

    # Bearbeiten ------------------------------------------------------------------------------------------------------
    @Slot()
    def undo(self) -> None:
        self.uno(".uno:Undo", follow=True)

    @Slot()
    def redo(self) -> None:
        self.uno(".uno:Redo", follow=True)

    @Slot()
    def selectAll(self) -> None:  # noqa: N802
        self.uno(".uno:SelectAll")

    @Slot()
    def copy(self) -> None:
        self._copy(False)

    @Slot()
    def cut(self) -> None:
        self._copy(True)

    def _copy(self, cut: bool) -> None:
        # LibreOffice behält eine eigene Kopie (mit allen Formaten) – Einfügen im selben Text nimmt die, nicht das HTML
        self.uno(".uno:Copy")

        def done(data: dict) -> None:
            from PySide6.QtCore import QMimeData
            from PySide6.QtGui import QGuiApplication

            data = data or {}
            plain = base64.b64decode(data.get("text/plain;charset=utf-8") or "").decode("utf-8", "replace")
            html = ""
            for key, value in data.items():
                if key.startswith("text/html"):
                    html = base64.b64decode(value).decode("utf-8", "replace")
            if not plain and not html:
                return
            mime = QMimeData()
            if html:
                mime.setHtml(html)
            mime.setText(plain)
            mime.setData(TEXT_CLIP_FORMAT, b"1")
            QGuiApplication.clipboard().setMimeData(mime)
            TextController._own_copy = (id(self), doc, generation, plain)
            if cut:
                self.key(0, KEY_DELETE)

        generation, doc = self.generation, self.doc
        self._call("selection", {"mimes": ["text/html", "text/plain;charset=utf-8"]}, done, priority=INPUT)

    @Slot()
    def paste(self) -> None:
        """Einfügen aus der Zwischenablage von Windows: formatierter Text (HTML), Bild oder reiner Text."""
        from PySide6.QtCore import QBuffer, QIODevice
        from PySide6.QtGui import QGuiApplication

        mime = QGuiApplication.clipboard().mimeData()
        if mime is None:
            return
        own = TextController._own_copy
        if own is not None and own[:3] == (id(self), self.doc, self.generation) and mime.hasText() and mime.text() == own[3]:
            self.uno(".uno:Paste", follow=True)
            return
        if mime.hasHtml() and mime.html().strip():
            kind, data = "text/html", mime.html().encode("utf-8")
        elif mime.hasImage():
            image = QGuiApplication.clipboard().image()
            buffer = QBuffer()
            buffer.open(QIODevice.OpenModeFlag.WriteOnly)
            image.save(buffer, "PNG")
            kind, data = "image/png", bytes(buffer.data())
        elif mime.hasText() and mime.text():
            kind, data = "text/plain;charset=utf-8", mime.text().encode("utf-8")
        else:
            return
        self._follow = True

        def done(ok) -> None:
            if not ok and kind == "text/html" and mime.hasText():
                self._call("paste", {"mime": "text/plain;charset=utf-8", "data": base64.b64encode(mime.text().encode("utf-8")).decode("ascii")},
                           priority=INPUT)

        self._call("paste", {"mime": kind, "data": base64.b64encode(data).decode("ascii")}, done, priority=INPUT)

    @Slot()
    def pastePlain(self) -> None:  # noqa: N802
        """Unformatiert einfügen (nur der Text)."""
        from PySide6.QtGui import QGuiApplication

        value = QGuiApplication.clipboard().text()
        if value:
            self._follow = True
            self._call("paste", {"mime": "text/plain;charset=utf-8", "data": base64.b64encode(value.encode("utf-8")).decode("ascii")},
                       priority=INPUT)

    # Einfügen und Seite ------------------------------------------------------------------------------------------------
    @Slot()
    def insertImage(self) -> None:  # noqa: N802
        from .. import files

        paths = files.open_files("Bild einfügen", self.app.initial_dir("reader", self.reader.source_dir),
                                 "Bilder (*.png *.jpg *.jpeg *.gif *.bmp *.tif *.tiff *.svg);;Alle Dateien (*.*)")
        if paths:
            self.uno(".uno:InsertGraphic", {"FileName": ("string", QUrl.fromLocalFile(str(Path(paths[0]).resolve())).toString())})

    @Slot(int, int)
    def insertTable(self, rows: int, cols: int) -> None:  # noqa: N802
        self.uno(".uno:InsertTable", {"Columns": ("long", max(1, min(50, cols))), "Rows": ("long", max(1, min(500, rows)))}, follow=True)

    @Slot()
    def insertPageBreak(self) -> None:  # noqa: N802
        self.uno(".uno:InsertPagebreak", follow=True)

    @Slot(str)
    def insertField(self, kind: str) -> None:  # noqa: N802
        command = {"page": ".uno:InsertPageNumberField", "pages": ".uno:InsertPageCountField", "date": ".uno:InsertDateField"}.get(kind)
        if command:
            self.uno(command, follow=True)

    @Slot(str)
    def headerFooter(self, kind: str) -> None:  # noqa: N802
        """Kopf- bzw. Fußzeile einschalten (»header«/»footer«)."""
        command = ".uno:InsertPageHeader" if kind == "header" else ".uno:InsertPageFooter"
        self.uno(command, {"On": ("boolean", True)})

    @Slot(bool)
    def setLandscape(self, landscape: bool) -> None:  # noqa: N802
        if not self.pages or landscape == self.landscape:
            return
        _x, _y, width, height = self.pages[0]
        width, height = round(width * 2540 / 1440), round(height * 2540 / 1440)  # Twips → 1/100 mm
        short, long = sorted((width, height))
        width, height = (long, short) if landscape else (short, long)
        self.uno(".uno:AttributePageSize", {"AttributePageSize.Width": ("long", width), "AttributePageSize.Height": ("long", height)})

    @Slot(str)
    def setMargins(self, kind: str) -> None:  # noqa: N802
        if kind not in MARGINS:
            return
        left, right, top, bottom = MARGINS[kind]
        self.uno(".uno:PageLRMargin", {"Left": ("long", left), "Right": ("long", right)})
        self.uno(".uno:PageULMargin", {"Upper": ("long", top), "Lower": ("long", bottom)})

    # Suchen ------------------------------------------------------------------------------------------------------------
    @Slot(str, bool)
    def find(self, value: str, backward: bool) -> None:
        if not value:
            self.findResult = ""
            return
        self.findResult = ""
        self.uno(".uno:ExecuteSearch", {"SearchItem.SearchString": ("string", value), "SearchItem.Backward": ("boolean", bool(backward)),
                                        "SearchItem.Command": ("long", 0)}, follow=True)

    @Slot(str, str, bool)
    def replace(self, value: str, replacement: str, everything: bool) -> None:
        if not value:
            return
        self.findResult = ""
        self.uno(".uno:ExecuteSearch", {"SearchItem.SearchString": ("string", value), "SearchItem.ReplaceString": ("string", replacement),
                                        "SearchItem.Command": ("long", 3 if everything else 2)}, follow=True)

    # Ansicht -----------------------------------------------------------------------------------------------------------
    @Slot(int)
    def setZoom(self, value: int) -> None:  # noqa: N802
        self.zoom = max(MIN_ZOOM, min(MAX_ZOOM, int(value)))

    @Slot(int)
    def zoomStep(self, direction: int) -> None:  # noqa: N802
        if direction > 0:
            bigger = [step for step in ZOOM_STEPS if step > self.zoom]
            self.setZoom(bigger[0] if bigger else MAX_ZOOM)
        else:
            smaller = [step for step in ZOOM_STEPS if step < self.zoom]
            self.setZoom(smaller[-1] if smaller else MIN_ZOOM)

    @Slot()
    def toggleSidebar(self) -> None:  # noqa: N802
        self.sidebar = not self.sidebar

    # Speichern, PDF, Drucken -------------------------------------------------------------------------------------------
    def save(self, target: str | None = None, *, force: bool = False, then: Callable[[bool], None] | None = None) -> None:
        """Speichern (``target`` = Speichern unter). ``then(erfolgreich)`` danach."""
        del force
        if self.saving:
            if then is not None:
                self._save_then.append(then)
            return
        if not target:
            if not self.path or Path(self.path).suffix.lower() not in SAVE_SUFFIXES:
                target = self._pick_target()
                if not target:
                    if then is not None:
                        then(False)
                    return
            else:
                target = self.path
        if not self.doc:
            self.app.notify("reader", "error", "Der Textkern läuft nicht – der Text wird neu geladen.", title="Nicht gespeichert")
            if then is not None:
                then(False)
            return
        if then is not None:
            self._save_then.append(then)
        self.saving = True
        self.app.set_status(f"Wird gespeichert: {Path(target).name} …", "busy")

        def done(_result) -> None:
            self.saving = False
            self.path = str(Path(target))
            self.name = Path(target).name
            self.dirty = False
            self.reader.tab_changed(self)
            self.reader.remember_recent(self.path)
            self.app.set_status(f"Gespeichert: {self.name}", "success")
            self._finish_save(True)

        def failed(exc: BaseException) -> None:
            self.saving = False
            message = str(exc) if isinstance(exc, text.TextError) else "Der Text ließ sich nicht speichern."
            self.app.notify("reader", "error", message, title="Nicht gespeichert")
            self._finish_save(False)

        self._call("save", {"path": str(Path(target).resolve()), "options": "TakeOwnership"}, done, failed, quiet=True)

    def save_and_wait(self, timeout: float = 600.0) -> bool:
        """Beim Beenden: speichern und warten, bis es fertig ist (``True`` = gespeichert)."""
        from PySide6.QtCore import QEventLoop, QTimer

        result: dict = {}
        loop = QEventLoop()

        def finished(ok: bool) -> None:
            result["ok"] = ok
            loop.quit()

        self.save(then=finished)
        if "ok" not in result:
            QTimer.singleShot(int(timeout * 1000), loop.quit)
            loop.exec()
        return bool(result.get("ok"))

    def _finish_save(self, ok: bool) -> None:
        callbacks, self._save_then = self._save_then, []
        for callback in callbacks:
            callback(ok)

    def _pick_target(self, suggestion: str = "") -> str:
        from .. import files

        folder = str(Path(self.path).parent) if self.path else self.app.initial_dir("reader", self.reader.source_dir)
        stem = Path(self.name or "Dokument1").stem
        suffix = Path(self.path).suffix.lower() if self.path and Path(self.path).suffix.lower() in SAVE_SUFFIXES else ".docx"
        target = files.save_file("Speichern unter", suggestion or str(Path(folder) / (stem + suffix)), SAVE_FILTER)
        if target and Path(target).suffix.lower() not in SAVE_SUFFIXES:
            target += ".docx"
        return target

    @Slot()
    def saveNow(self) -> None:  # noqa: N802
        self.save()

    # Gleiche Namen wie bei PDF-Dokumenten (Strg+S, Strg+Umschalt+S, Strg+P, Strg+F aus Fenster und Reader)
    @Slot()
    def saveDocument(self) -> None:  # noqa: N802
        self.save()

    @Slot()
    def saveDocumentAs(self) -> None:  # noqa: N802
        self.saveAs()

    @Slot()
    def printDocument(self) -> None:  # noqa: N802
        self.printText()

    @Slot()
    def requestSearch(self) -> None:  # noqa: N802
        self.findRequested.emit()

    @Slot()
    def saveAs(self) -> None:  # noqa: N802
        target = self._pick_target()
        if target:
            self.save(target)

    @Slot()
    def exportPdf(self) -> None:  # noqa: N802
        target = self.reader.pick_save_pdf(Path(self.name or "Dokument").stem + ".pdf", "Als PDF speichern")
        if not target:
            return
        self.app.set_status("PDF wird erstellt …", "busy")

        def done(_result) -> None:
            name = Path(target).name
            self.app.set_status(f"Gespeichert: {name}", "success")
            self.app.notify("reader", "success", f"»{name}« wurde gespeichert.", title="Als PDF gespeichert", auto_hide=10000,
                            actions=[("Öffnen", lambda: self.reader.open_paths([target]))])

        self._call("export", {"path": str(Path(target).resolve()), "format": "pdf"}, done)

    @Slot()
    def printText(self) -> None:  # noqa: N802
        """Drucken: die Seiten als PDF vorbereiten, dann der Druckdialog von Windows (wie bei PDFs)."""
        folder = Path(tempfile.mkdtemp(prefix="novadesk-druck-"))
        target = folder / (Path(self.name or "Dokument").stem + ".pdf")
        self.app.set_status("Druck wird vorbereitet …", "busy")

        def done(_result) -> None:
            from ..sheet.printing import print_pdf

            try:
                print_pdf(self.app, str(target), self.name)
            finally:
                try:
                    target.unlink()
                    folder.rmdir()
                except OSError:
                    pass

        self._call("export", {"path": str(target), "format": "pdf"}, done)

    # Schließen ---------------------------------------------------------------------------------------------------------
    def shutdown(self, discard_recovery: bool = True) -> None:
        del discard_recovery
        self._closed = True
        if self.doc:
            self.service.release(self.generation, self.doc)
            self.service.submit("close", {"doc": self.doc}, generation=self.generation)

    def _engine_lost(self, generation: int) -> None:
        """Der Textkern ist abgestürzt: Der Text ist dort fort – aus der Datei neu öffnen (ungespeicherte Änderungen
        sind verloren) bzw. ein neuer leerer Text."""
        if self._closed or generation != self.generation or not self.doc:
            return
        self.doc = 0
        self.ready = False
        lost = self.dirty
        self.app.notify("reader", "error",
                        ("Ungespeicherte Änderungen sind verloren. " if lost else "") + "Der Text wird neu geöffnet.",
                        title="Textkern neu gestartet")
        self.dirty = False
        self.selection, self.graphic = [], []
        self.reader.tab_changed(self)
        self.open(self.path, lambda: self.tilesInvalidated.emit(0, 0, 0, 0),
                  lambda exc: self.app.notify("reader", "error", str(exc), title=self.name), self.password)

    def _get_kind(self) -> str:
        return "text"

    _constant = Signal()
    kind = Property(str, _get_kind, notify=_constant)
