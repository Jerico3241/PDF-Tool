"""Eine geöffnete Präsentation (in QML: ``Reader.current`` mit ``kind`` »praesentation«): Folien, Layouts, Notizen
und das Vorführen.

Eine Präsentation lebt wie ein Text im Textkern (LibreOfficeKit in einem eigenen Prozess) – darum ist
``SlidesController`` ein ``TextController`` mit allem, was Texte können (tippen, Formate, Kopieren, Suchen,
Speichern, Als PDF). Dazu kommen die Folien: ``slideCount``/``slideIndex`` sagen, welche Folie gezeigt wird,
``newSlide``, ``duplicateSlide``, ``deleteSlide`` und ``moveSlide`` ändern die Reihenfolge, ``setLayout`` das Layout.
Die Notizen stehen in einer zweiten Ansicht des Kerns im Notizen-Modus (``NotesController``): Die Folie bleibt
sichtbar, während unter ihr die Notizen bearbeitet werden.
"""

from __future__ import annotations

import logging
import shutil
import tempfile
from pathlib import Path
from typing import Callable

from PySide6.QtCore import Property, QObject, QSize, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QImage

from ..base import Observable, prop
from .document import TextController
from .service import INPUT, NORMAL, TILE

SAVE_FILTER = "PowerPoint-Präsentation (*.pptx);;OpenDocument-Präsentation (*.odp);;PowerPoint 97–2003 (*.ppt)"
SAVE_SUFFIXES = (".pptx", ".odp", ".ppt")
# Ereignisse der Notizenansicht (kernel.NOTES_BASE + Nummer)
NOTES_BASE = 1000
# Der Notizenrahmen auf der Notizenseite (Anteile der Seite): unter dem Bild der Folie, mit Rand ringsum
NOTES_FRAME = (0.07, 0.465, 0.86, 0.47)
MAX_NOTES_ZOOM = 90  # die Notizen stehen nicht größer da als nötig, auch in einem breiten Fenster
# Layouts von LibreOffice (.uno:AssignLayout): Name in der Oberfläche → Nummer
LAYOUTS = (
    ("Titelfolie", 0),
    ("Titel und Inhalt", 1),
    ("Zwei Inhalte", 3),
    ("Nur Titel", 19),
    ("Leer", 20),
)
# Formen zum Aufziehen (danach mit der Maus auf der Folie ziehen)
SHAPES = (
    ("Textfeld", "text", ".uno:Text"),
    ("Rechteck", "rectangle", ".uno:BasicShapes.rectangle"),
    ("Ellipse", "ellipse", ".uno:BasicShapes.ellipse"),
    ("Linie", "line", ".uno:Line"),
    ("Pfeil", "arrow", ".uno:LineArrowEnd"),
)
# Designs (seit 5.0 Beta 6) für alle Folienmaster: Hintergrund (Farbe, zweite Farbe für einen Verlauf), Titel und Text
# (Schrift, Farbe), Akzent (Farbe, Form: leiste links, linie unten, band oben, ecke rechts oben)
DESIGNS = (
    {"key": "weiss", "label": "Weiß", "background": ("#FFFFFF", ""), "title": ("Calibri", "#1F1F1F"),
     "text": ("Calibri", "#404040"), "accent": ("#0F6CBD", "linie")},
    {"key": "blau", "label": "Blau", "background": ("#1F4E79", "#2E75B6"), "title": ("Segoe UI", "#FFFFFF"),
     "text": ("Segoe UI", "#DDEBF7"), "accent": ("#FFC000", "leiste")},
    {"key": "orange", "label": "Orange", "background": ("#FFFFFF", ""), "title": ("Segoe UI", "#1F1F1F"),
     "text": ("Segoe UI", "#404040"), "accent": ("#E8590C", "ecke")},
    {"key": "gruen", "label": "Grün", "background": ("#F3F8F1", ""), "title": ("Georgia", "#2E5E2B"),
     "text": ("Georgia", "#3B4A39"), "accent": ("#5BA33B", "leiste")},
    {"key": "sand", "label": "Sand", "background": ("#FAF6EE", ""), "title": ("Georgia", "#5A3E1B"),
     "text": ("Georgia", "#4A4036"), "accent": ("#C08A3E", "linie")},
    {"key": "nacht", "label": "Nacht", "background": ("#1B1B1F", "#2D2D35"), "title": ("Segoe UI", "#FFFFFF"),
     "text": ("Segoe UI", "#C8C8D0"), "accent": ("#4CC2FF", "band")},
    {"key": "violett", "label": "Violett", "background": ("#3A1F5D", "#6B3FA0"), "title": ("Segoe UI", "#FFFFFF"),
     "text": ("Segoe UI", "#EDE6F6"), "accent": ("#F5A623", "band")},
    {"key": "grau", "label": "Grau", "background": ("#F2F2F2", ""), "title": ("Verdana", "#262626"),
     "text": ("Verdana", "#404040"), "accent": ("#7F7F7F", "linie")},
)
# Übergänge (Name in der Oberfläche, Schlüssel im Kern, Symbol)
TRANSITIONS = (
    ("Ohne", "keiner", "dismiss_circle"),
    ("Überblenden", "blenden", "transparency_square"),
    ("Durch Schwarz", "schwarz", "circle_half_fill"),
    ("Schieben", "schieben", "arrow_import"),
    ("Wischen", "wischen", "arrow_right"),
    ("Überdecken", "aufdecken", "slide_transition"),
)
DURATIONS = ("0,5", "1", "1,5", "2", "3")  # Dauer des Übergangs (Sekunden)
ADVANCES = (0, 3, 5, 10, 15, 30)  # weiter nach … Sekunden (0: beim Klicken)
VIDEO_FILTER = "Videos (*.mp4 *.m4v *.mov *.wmv *.avi *.mkv *.webm);;Alle Dateien (*.*)"
AUDIO_FILTER = "Töne (*.mp3 *.wav *.m4a *.wma *.ogg *.flac *.aac);;Alle Dateien (*.*)"
MIME_TYPES = {
    ".mp4": "video/mp4", ".m4v": "video/mp4", ".mov": "video/quicktime", ".wmv": "video/x-ms-wmv",
    ".avi": "video/x-msvideo", ".mkv": "video/x-matroska", ".webm": "video/webm", ".mp3": "audio/mpeg",
    ".wav": "audio/x-wav", ".m4a": "audio/mp4", ".wma": "audio/x-ms-wma", ".ogg": "audio/ogg", ".flac": "audio/flac",
    ".aac": "audio/aac",
}
AUDIO_SUFFIXES = (".mp3", ".wav", ".m4a", ".wma", ".ogg", ".flac", ".aac")
MAX_MEDIA_BYTES = 500 * 1024 * 1024  # größere Videos lieber verkleinern: die Präsentation trägt sie mit sich
EXPORT_SIZES = (("1280 × 720 (HD)", 1280), ("1920 × 1080 (Full HD)", 1920), ("3840 × 2160 (4K)", 3840))


def _log():
    return logging.getLogger("pdftool.text")


class NotesController(Observable):
    """Die Notizen der gezeigten Folie – für denselben Zeichenbereich wie ein Text (``TextCanvas``), aber auf den
    Notizenrahmen beschnitten: Der Kern rechnet auf der ganzen Notizenseite, hier liegt der Rahmen bei 0, 0."""

    readyChanged, ready = prop(bool, "ready", False)
    zoomChanged, zoom = prop(int, "zoom", 100)
    docWidthChanged, docWidth = prop(int, "docWidth", 8000)
    docHeightChanged, docHeight = prop(int, "docHeight", 4000)
    pagesChanged, pages = prop(list, "pages", [])
    cursorChanged, cursor = prop(list, "cursor", [])
    cursorVisibleChanged, cursorVisible = prop(bool, "cursorVisible", True)
    selectionChanged, selection = prop(list, "selection", [])
    graphicChanged, graphic = prop(list, "graphic", [])

    tilesInvalidated = Signal(int, int, int, int)
    caretMoved = Signal()

    def __init__(self, slides: SlidesController) -> None:
        super().__init__(slides)
        self.slides = slides
        self.origin = (0, 0)  # linke obere Ecke des Notizenrahmens auf der Seite (Twips)
        self.pageSize = (11906, 16838)
        self._width = 0.0  # zuletzt gemeldete Breite der Notizenleiste (Pixel)

    # Größe ------------------------------------------------------------------------------------------------------
    def apply_page(self, width: int, height: int) -> None:
        """Die Notizenseite ist da: den Rahmen daraus berechnen."""
        self.pageSize = (int(width), int(height))
        left, top, frame_width, frame_height = NOTES_FRAME
        self.origin = (int(width * left), int(height * top))
        self.docWidth = max(1, int(width * frame_width))
        self.docHeight = max(1, int(height * frame_height))
        self.pages = [[0, 0, self.docWidth, self.docHeight]]
        self.ready = True
        self.fit(self._width)  # die Seitengröße kam erst jetzt: Zoom noch einmal wählen

    @Slot(float)
    def fit(self, width: float) -> None:
        """Zoom so wählen, dass der Notizenrahmen in die Breite ``width`` (Pixel) passt."""
        self._width = float(width)
        if width > 0 and self.docWidth > 0:
            zoom = max(10, min(MAX_NOTES_ZOOM, int(round(width * 15.0 * 100.0 / self.docWidth))))
            if zoom != self.zoom:
                self.zoom = zoom

    # Ereignisse des Kerns (vom Dokument weitergereicht) ---------------------------------------------------------
    def on_event(self, kind: int, payload: str) -> None:
        from .document import _rect, _rects

        if kind == 0:
            rect = _rect(payload) if payload.strip() != "EMPTY" else []
            if rect:
                x, y = self.origin
                self.tilesInvalidated.emit(rect[0] - x, rect[1] - y, rect[2], rect[3])
            else:
                self.tilesInvalidated.emit(0, 0, 0, 0)
        elif kind == 1:
            import json

            text = payload
            if payload.lstrip().startswith("{"):
                try:
                    text = str(json.loads(payload).get("rectangle") or "")
                except ValueError:
                    text = ""
            values = _rect(text)
            if values:
                x, y = self.origin
                self.cursor = [values[0] - x, values[1] - y, values[2], values[3]]
                self.caretMoved.emit()  # die Schreibmarke im Blick behalten (der Rahmen ist höher als die Leiste)
        elif kind == 2:
            x, y = self.origin
            self.selection = [[r[0] - x, r[1] - y, r[2], r[3]] for r in _rects(payload)]
        elif kind == 5:
            self.cursorVisible = payload.strip() == "true"
        elif kind == 13:
            self.slides.refresh_notes()

    # Was der Zeichenbereich braucht ------------------------------------------------------------------------------
    def request_tile(self, args: dict, done: Callable, failed: Callable) -> None:
        x, y = self.origin
        values = dict(args)
        values["x"], values["y"], values["notes"] = int(args["x"]) + x, int(args["y"]) + y, True
        self.slides._call("tile", values, done, failed, quiet=True, priority=TILE)  # noqa: SLF001

    def set_client_zoom(self, tile_px: int, tile_twips: int) -> None:
        self.slides._call("zoom", {"pw": tile_px, "ph": tile_px, "tw": tile_twips, "th": tile_twips, "notes": True},  # noqa: SLF001
                          quiet=True)

    def set_visible_area(self, x: int, y: int, w: int, h: int) -> None:
        left, top = self.origin
        self.slides._call("visible", {"x": x + left, "y": y + top, "w": w, "h": h, "notes": True}, quiet=True)  # noqa: SLF001

    def key(self, char: int, code: int) -> None:
        self.slides._call("key", {"char": char, "code": code, "notes": True}, quiet=True, priority=INPUT)  # noqa: SLF001

    def type_text(self, value: str) -> None:
        if value:
            self.slides._call("text", {"text": value, "notes": True}, quiet=True, priority=INPUT)  # noqa: SLF001

    def mouse(self, kind: int, x: int, y: int, count: int = 1, buttons: int = 1, mods: int = 0) -> None:
        left, top = self.origin
        self.slides._call("mouse", {"type": kind, "x": x + left, "y": y + top, "count": count, "buttons": buttons,  # noqa: SLF001
                                    "mods": mods, "notes": True}, quiet=True, priority=INPUT)

    def graphic_drag(self, kind: int, x: int, y: int) -> None:
        left, top = self.origin
        self.slides._call("graphic", {"type": kind, "x": x + left, "y": y + top, "notes": True},  # noqa: SLF001
                          quiet=True, priority=INPUT)


class SlidesController(TextController):
    KIND = "praesentation"
    SAVE_FILTER = SAVE_FILTER
    SAVE_SUFFIXES = SAVE_SUFFIXES
    DEFAULT_NAME = "Präsentation1"

    slideCountChanged, slideCount = prop(int, "slideCount", 1)
    slideIndexChanged, slideIndex = prop(int, "slideIndex", 0)
    slideNamesChanged, slideNames = prop(list, "slideNames", [])
    slideRevisionChanged, slideRevision = prop(int, "slideRevision", 0)  # steigt, wenn die Folienbilder alt sind
    notesOpenChanged, notesOpen = prop(bool, "notesOpen", True)
    panelChanged, panel = prop(str, "panel", "slides")  # Seitenleiste rechts: »slides«, »layouts« oder zu («»)
    fittingChanged, fitting = prop(bool, "fitting", True)  # Folie füllt die Ansicht (bis jemand selbst zoomt)
    presentingChanged, presenting = prop(bool, "presenting", False)
    presentIndexChanged, presentIndex = prop(int, "presentIndex", 0)
    # Seit 5.0 Beta 6: Folienmaster, Übergänge je Folie, Videos und Töne, Export
    presentForwardChanged, presentForward = prop(bool, "presentForward", True)  # zuletzt vorwärts geblättert
    masterModeChanged, masterMode = prop(bool, "masterMode", False)
    transitionsChanged, transitions = prop(list, "transitions", [])  # je Folie {kind, duration, advance}
    mediaChanged, media = prop(list, "media", [])  # {part, url, x, y, w, h (Anteile der Folie), loop, audio}
    exportingChanged, exporting = prop(bool, "exporting", False)
    exportProgressChanged, exportProgress = prop(float, "exportProgress", 0.0)
    showFramesChanged, showFrames = prop(list, "showFrames", [])  # beim Vorführen: je Folie die Adresse ihres Bilds

    def __init__(self, reader, service, ident: str, parent: QObject | None = None) -> None:
        super().__init__(reader, service, ident, parent)
        self.sidebar = True  # die Folienleiste rechts ist offen (wie im Entwurf)
        self._notes = NotesController(self)
        self._thumbs = QTimer(self)  # Folienbilder nicht bei jedem Tastendruck neu
        self._thumbs.setSingleShot(True)
        self._thumbs.setInterval(400)
        self._thumbs.timeout.connect(self._bump_revision)
        self._parts = QTimer(self)  # nach Befehlen, die Folien ändern: Anzahl und Namen holen
        self._parts.setSingleShot(True)
        self._parts.setInterval(250)
        self._parts.timeout.connect(self.refresh_parts)
        self._writer = None  # Video, das gerade entsteht
        self._export_cancel = False
        self._show_folder: Path | None = None  # Bilder der Folien zum Vorführen
        self._show_run = 0

    def _get_notes(self) -> QObject:
        return self._notes

    def shutdown(self, discard_recovery: bool = True) -> None:
        self.cancelExport()
        self._drop_show()
        super().shutdown(discard_recovery)

    _notes_constant = Signal()
    notes = Property(QObject, _get_notes, notify=_notes_constant)

    # Öffnen ------------------------------------------------------------------------------------------------------
    def open(self, path: str, done: Callable[[], None], failed: Callable[[BaseException], None],
             password: str | None = None) -> None:
        self.name = Path(path).name if path else self.name or "Präsentation1.pptx"

        def opened() -> None:
            self.refresh_parts()
            self.refresh_notes()
            self.refresh_transitions()
            done()

        super().open(path, opened, failed, password)

    def refresh_parts(self) -> None:
        """Anzahl, Namen und gezeigte Folie aus dem Kern holen."""
        def got(result) -> None:
            if not isinstance(result, dict):
                return
            self.slideCount = max(1, int(result.get("count") or 1))
            self.slideNames = [str(name) for name in result.get("names") or []]
            self.slideIndex = max(0, min(self.slideCount - 1, int(result.get("current") or 0)))
            self._bump_revision()
            if not self.masterMode and len(self.transitions) != self.slideCount:
                self.refresh_transitions()

        self._call("parts", {}, got, quiet=True)

    def refresh_notes(self) -> None:
        """Die Notizenansicht (zweite Ansicht im Kern) anlegen bzw. auf die gezeigte Folie stellen."""
        def got(result) -> None:
            if isinstance(result, dict):
                self._notes.apply_page(int(result.get("width") or 11906), int(result.get("height") or 16838))
                self._notes.tilesInvalidated.emit(0, 0, 0, 0)

        self._call("notes", {"part": self.slideIndex}, got, quiet=True)

    def _bump_revision(self) -> None:
        self.slideRevision = self.slideRevision + 1

    # Ereignisse ---------------------------------------------------------------------------------------------------
    def _on_event(self, generation: int, doc: int, kind: int, payload: str) -> None:
        if self._closed or doc != self.doc or generation != self.generation:
            return
        if kind >= NOTES_BASE:
            self._notes.on_event(kind - NOTES_BASE, payload)
            return
        super()._on_event(generation, doc, kind, payload)
        if kind == 0:  # etwas wurde neu gezeichnet: die Folienbilder stimmen nicht mehr
            self._thumbs.start()

    # Folien -------------------------------------------------------------------------------------------------------
    @Slot(int)
    def goSlide(self, index: int) -> None:  # noqa: N802
        index = max(0, min(self.slideCount - 1, int(index)))
        if index == self.slideIndex and self.ready:
            return

        def done(result) -> None:
            if isinstance(result, dict):
                current = result.get("current")
                self.slideIndex = int(current) if current is not None else index
                self._apply_size(result)
                self.tilesInvalidated.emit(0, 0, 0, 0)
                self.refresh_notes()

        self._call("part", {"part": index}, done, priority=INPUT)

    @Slot()
    def nextSlide(self) -> None:  # noqa: N802
        self.goSlide(self.slideIndex + 1)

    @Slot()
    def previousSlide(self) -> None:  # noqa: N802
        self.goSlide(self.slideIndex - 1)

    @Slot()
    def newSlide(self) -> None:  # noqa: N802
        self.uno(".uno:InsertPage")
        self._parts.start()

    @Slot()
    def duplicateSlide(self) -> None:  # noqa: N802
        self.uno(".uno:DuplicatePage")
        self._parts.start()

    @Slot()
    def deleteSlide(self) -> None:  # noqa: N802
        if self.slideCount <= 1:
            self.app.notify("reader", "warning", "Eine Präsentation braucht mindestens eine Folie.", title=self.name,
                            auto_hide=6000)
            return
        self.uno(".uno:DeletePage")
        self._parts.start()

    @Slot(int)
    def moveSlide(self, direction: int) -> None:  # noqa: N802
        """Folie nach vorn (-1) bzw. nach hinten (+1) schieben."""
        if direction < 0 and self.slideIndex == 0:
            return
        if direction > 0 and self.slideIndex >= self.slideCount - 1:
            return
        self.uno(".uno:MovePageUp" if direction < 0 else ".uno:MovePageDown")
        self._parts.start()

    @Slot(int)
    def setLayout(self, layout: int) -> None:  # noqa: N802
        self.uno(".uno:AssignLayout", {"WhatLayout": ("long", int(layout))})
        self._thumbs.start()

    @Slot(result=list)
    def layoutList(self) -> list:  # noqa: N802
        return [{"label": label, "value": value} for label, value in LAYOUTS]

    @Slot(str)
    def insertShape(self, key: str) -> None:  # noqa: N802
        """Form wählen – danach zieht man sie auf der Folie mit der Maus auf (wie in PowerPoint)."""
        command = next((command for _label, name, command in SHAPES if name == key), "")
        if command:
            self.uno(command)

    @Slot(result=list)
    def shapeList(self) -> list:  # noqa: N802
        return [{"label": label, "key": name} for label, name, _command in SHAPES]

    def request_thumb(self, part: int, pw: int, ph: int, done: Callable, failed: Callable) -> None:
        """Bild einer Folie (ohne zu ihr zu wechseln) – für die Folienleiste und das Vorführen."""
        # Im Folienmaster sind die Teile die Master (Bearbeitungsmodus 1 von LibreOffice)
        self._call("thumb", {"part": int(part), "pw": int(pw), "ph": int(ph), "w": self.docWidth, "h": self.docHeight,
                             "mode": 1 if self.masterMode else 0},
                   done, failed, quiet=True, priority=TILE)

    # Zoom: die Folie füllt die Ansicht, bis jemand selbst zoomt ---------------------------------------------------
    @Slot(float, float)
    def fitSlide(self, width: float, height: float) -> None:  # noqa: N802
        """Zoom so wählen, dass die ganze Folie in ``width`` × ``height`` (Pixel) passt – mit etwas Rand."""
        if not self.fitting or width < 40 or height < 40 or self.docWidth <= 0 or self.docHeight <= 0:
            return
        scale = min((width - 48) * 15.0 / self.docWidth, (height - 40) * 15.0 / self.docHeight)
        zoom = max(10, min(400, int(round(scale * 100))))
        if zoom != self.zoom:
            self.zoom = zoom

    @Slot(int)
    def setZoom(self, value: int) -> None:  # noqa: N802
        self.fitting = False
        super().setZoom(value)

    @Slot()
    def fitAgain(self) -> None:  # noqa: N802
        """»An die Ansicht anpassen«: wieder die ganze Folie zeigen."""
        self.fitting = True
        self.fitRequested.emit()

    fitRequested = Signal()

    # Notizen und Seitenleiste --------------------------------------------------------------------------------------
    @Slot()
    def toggleNotes(self) -> None:  # noqa: N802
        self.notesOpen = not self.notesOpen

    @Slot(str)
    def togglePanel(self, key: str) -> None:  # noqa: N802
        """Seitenleiste rechts: denselben Inhalt noch einmal gewählt schließt sie."""
        self.panel = "" if self.panel == key else key

    # Vorführen ----------------------------------------------------------------------------------------------------
    @Slot()
    def present(self) -> None:
        """Vollbild ab der gezeigten Folie (F5)."""
        self._start_show(self.slideIndex)

    @Slot()
    def presentFromStart(self) -> None:  # noqa: N802
        self._start_show(0)

    def _start_show(self, index: int) -> None:
        if self.masterMode:
            self.app.notify("reader", "warning", "Bitte zuerst die Masteransicht schließen.", title="Präsentieren", auto_hide=6000)
            return
        self.presentIndex = index
        self.presentForward = True
        self._render_show(index)
        self.refresh_media()  # Videos und Töne kommen gleich nach (die Folie steht schon)
        self.refresh_transitions()
        self.presenting = True

    def _render_show(self, first: int) -> None:
        """Die Folien in Bildschirmgröße malen lassen, wie sie beim Vorführen aussehen (ohne leere Platzhalter): erst
        die gezeigte und die folgenden, dann die davor. ``showFrames`` füllt sich nach und nach."""
        from PySide6.QtGui import QGuiApplication

        self._drop_show()
        self._show_run += 1
        run = self._show_run
        screen = QGuiApplication.primaryScreen()
        pixels = screen.size() * screen.devicePixelRatio() if screen is not None else QSize(1920, 1080)
        width, height = self._export_size(min(3840, max(640, int(min(pixels.width(), pixels.height() * self.docWidth / max(1, self.docHeight))))))
        folder = Path(tempfile.mkdtemp(prefix="novadesk-vorfuehren-"))
        self._show_folder = folder
        count = self.slideCount
        frames = [""] * count
        self.showFrames = list(frames)
        order = list(range(first, count)) + list(range(first - 1, -1, -1))

        def each(index: int, path: Path) -> None:
            if run != self._show_run:
                return
            frames[index] = QUrl.fromLocalFile(str(path)).toString()
            self.showFrames = list(frames)

        self._render_slides(folder, width, height, "png", order, each, lambda: None, lambda: run != self._show_run)

    def _drop_show(self) -> None:
        self._show_run += 1
        if self._show_folder is not None:
            shutil.rmtree(self._show_folder, ignore_errors=True)
            self._show_folder = None
        self.showFrames = []

    @Slot()
    def endPresent(self) -> None:  # noqa: N802
        if self.presenting:
            self.presenting = False
            self._drop_show()
            self.goSlide(self.presentIndex)

    @Slot(int)
    def presentStep(self, direction: int) -> None:  # noqa: N802
        index = self.presentIndex + (1 if direction > 0 else -1)
        if index < 0:
            return
        if index >= self.slideCount:
            self.endPresent()
            return
        self.presentForward = direction > 0
        self.presentIndex = index

    # Designs und Hintergrund (seit 5.0 Beta 6) -----------------------------------------------------------------------
    @Slot(result=list)
    def designList(self) -> list:  # noqa: N802
        return [{"key": d["key"], "label": d["label"], "background": list(d["background"]), "title": d["title"][1],
                 "text": d["text"][1], "font": d["title"][0], "accent": d["accent"][0], "shape": d["accent"][1]}
                for d in DESIGNS]

    @Slot(str)
    def applyDesign(self, key: str) -> None:  # noqa: N802
        design = next((d for d in DESIGNS if d["key"] == key), None)
        if design is None or not self.ready:
            return
        background, title, text, accent = design["background"], design["title"], design["text"], design["accent"]
        values = [background[0], background[1], title[0], title[1], text[0], text[1], accent[0], accent[1]]
        self.macro("DesignAnwenden", [value.lstrip("#") for value in values], lambda _result: self._changed_all(),
                   self._macro_failed("Design"), module="Folien")
        self.app.set_status(f"Design »{design['label']}« für alle Folien", "success")

    @Slot(str, bool)
    def setBackground(self, color: str, every: bool) -> None:  # noqa: N802
        """Hintergrund der Folie (bzw. aller Folien) in einer Farbe; leer: wieder wie im Design."""
        self.macro("FolienHintergrund", [color.lstrip("#"), "", -1 if every else self.slideIndex], lambda _result: self._changed_all(),
                   self._macro_failed("Hintergrund"), module="Folien")

    def _changed_all(self) -> None:
        self.tilesInvalidated.emit(0, 0, 0, 0)
        self._bump_revision()
        self.dirty = True

    def _macro_failed(self, title: str):
        def failed(exc) -> None:
            self.app.notify("reader", "error", str(exc), title=title, auto_hide=10000)
        return failed

    # Folienmaster -------------------------------------------------------------------------------------------------
    @Slot()
    def toggleMaster(self) -> None:  # noqa: N802
        """Folienmaster bearbeiten (alle Folien mit diesem Master ändern sich mit) bzw. zurück zu den Folien."""
        if not self.ready or self.presenting:
            return
        entering = not self.masterMode
        self.masterMode = entering
        self._call("uno", {"command": ".uno:SlideMasterPage" if entering else ".uno:CloseMasterView", "wait": 1.5},
                   lambda _result: self._master_switched(), priority=INPUT)

    def _master_switched(self) -> None:
        self.refresh_parts()
        self._call("size", {}, self._apply_size, quiet=True)
        self.tilesInvalidated.emit(0, 0, 0, 0)
        self.fitRequested.emit()
        if not self.masterMode:
            self.refresh_notes()
            self.refresh_transitions()

    # Übergänge ----------------------------------------------------------------------------------------------------
    def refresh_transitions(self) -> None:
        def got(result) -> None:
            entries = []
            for record in result or []:
                fields = str(record).split("\x1f")
                if len(fields) < 4:
                    continue
                kind, duration, change, seconds = fields[:4]
                entries.append({"kind": kind, "duration": _number(duration, 1.0),
                                "advance": _number(seconds, 0.0) if change.strip() == "1" else 0.0})
            self.transitions = entries

        self.macro("Uebergaenge", [], got, lambda _exc: None, module="Folien")

    def _transition(self, index: int | None = None) -> dict:
        index = self.slideIndex if index is None else index
        if 0 <= index < len(self.transitions):
            return dict(self.transitions[index])
        return {"kind": "keiner", "duration": 1.0, "advance": 0.0}

    def _set_transition(self, entry: dict, every: bool = False) -> None:
        if self.masterMode:
            return
        advance = float(entry.get("advance") or 0)
        values = [entry.get("kind") or "keiner", _text(float(entry.get("duration") or 1.0)),
                  _text(advance) if advance > 0 else "", -1 if every else self.slideIndex]

        def done(_result) -> None:
            self.dirty = True
            self.refresh_transitions()

        self.macro("UebergangSetzen", values, done, self._macro_failed("Übergang"), module="Folien")

    @Slot(result=list)
    def transitionList(self) -> list:  # noqa: N802
        return [{"label": label, "key": key, "icon": icon} for label, key, icon in TRANSITIONS]

    @Slot(result=list)
    def durationList(self) -> list:  # noqa: N802
        return list(DURATIONS)

    @Slot(result=list)
    def advanceList(self) -> list:  # noqa: N802
        return [{"label": "Beim Klicken" if seconds == 0 else f"Nach {seconds} Sekunden", "value": seconds} for seconds in ADVANCES]

    @Slot(str)
    def setTransition(self, kind: str) -> None:  # noqa: N802
        entry = self._transition()
        entry["kind"] = kind
        self._set_transition(entry)

    @Slot(str)
    def setTransitionDuration(self, value: str) -> None:  # noqa: N802
        entry = self._transition()
        entry["duration"] = _number(value, 1.0)
        self._set_transition(entry)

    @Slot(int)
    def setAdvance(self, seconds: int) -> None:  # noqa: N802
        entry = self._transition()
        entry["advance"] = float(seconds)
        self._set_transition(entry)

    @Slot()
    def transitionToAll(self) -> None:  # noqa: N802
        """Übergang, Dauer und »weiter nach« der gezeigten Folie für alle Folien."""
        self._set_transition(self._transition(), every=True)
        self.app.set_status("Übergang für alle Folien übernommen", "success")

    # Video und Ton ------------------------------------------------------------------------------------------------
    @Slot(str)
    def insertMedia(self, kind: str) -> None:  # noqa: N802
        from .. import files

        audio = kind == "ton"
        path = files.open_file("Ton einfügen" if audio else "Video einfügen",
                               self.app.initial_dir("reader", self.reader.source_dir), AUDIO_FILTER if audio else VIDEO_FILTER)
        if not path:
            return
        source = Path(path)
        try:
            size = source.stat().st_size
        except OSError as exc:
            self.app.notify("reader", "error", f"Die Datei ist nicht lesbar ({exc.strerror or exc}).", title=source.name)
            return
        if size > MAX_MEDIA_BYTES:
            self.app.notify("reader", "warning", "Das Video ist größer als 500 MB. Bitte vorher verkleinern – die Präsentation "
                            "nimmt es mit und würde sonst sehr groß.", title=source.name, auto_hide=12000)
            return
        suffix = source.suffix.lower()
        audio = audio or suffix in AUDIO_SUFFIXES
        width, height = _video_size(source) if not audio else (0, 0)
        url = QUrl.fromLocalFile(str(source.resolve())).toString()
        index = self.slideIndex

        def insert(frame: QImage) -> None:
            from . import video

            if self._closed:
                return
            # Vorschaubild selbst mitgeben: LibreOffice bräuchte für eins aus dem Video mitunter viele Sekunden
            folder = Path(tempfile.mkdtemp(prefix="novadesk-medien-"))
            image = folder / "vorschau.png"
            poster = image if video.poster(frame, width, height, audio).save(str(image), "PNG") else None

            def tidy() -> None:
                shutil.rmtree(folder, ignore_errors=True)

            def done(_result) -> None:
                tidy()
                self._changed_all()
                self.app.set_status(f"Eingefügt: {source.name} – spielt beim Präsentieren", "success")

            def failed(exc) -> None:
                tidy()
                self._macro_failed("Video einfügen" if not audio else "Ton einfügen")(exc)

            self.macro("MedienEinfuegen", [url, "ton" if audio else "video", width, height, MIME_TYPES.get(suffix, ""), index,
                                           QUrl.fromLocalFile(str(poster)).toString() if poster else ""], done, failed, module="Folien")

        if audio:
            insert(QImage())
            return
        try:
            from .video import FrameGrabber

            FrameGrabber(str(source), self).done.connect(insert)
        except Exception:  # noqa: BLE001 – ohne Qt Multimedia: dunkles Vorschaubild
            insert(QImage())

    def refresh_media(self, then: Callable[[], None] | None = None) -> None:
        """Videos und Töne aller Folien (für das Vorführen): Lage als Anteil der Folie, Datei zum Abspielen."""
        width = max(1.0, self.docWidth * 2540 / 1440)  # Twips → 1/100 mm
        height = max(1.0, self.docHeight * 2540 / 1440)

        def got(result) -> None:
            entries = []
            for record in result or []:
                fields = str(record).split("\x1f")
                if len(fields) < 7 or not fields[1]:
                    continue
                url = QUrl(fields[1])
                path = url.toLocalFile() if url.isLocalFile() else ""
                mime = fields[7] if len(fields) > 7 else ""
                entries.append({"part": int(_number(fields[0], 0)), "url": url.toString(), "path": path,
                                "x": _number(fields[2], 0) / width, "y": _number(fields[3], 0) / height,
                                "w": _number(fields[4], 0) / width, "h": _number(fields[5], 0) / height,
                                "loop": fields[6] == "1", "audio": mime.startswith("audio")})
            self.media = entries
            if then is not None:
                then()

        def failed(_exc) -> None:
            self.media = []
            if then is not None:
                then()

        self.macro("Medien", [], got, failed, module="Folien")

    @Slot(int, result=list)
    def mediaOn(self, part: int) -> list:  # noqa: N802
        return [entry for entry in self.media if entry["part"] == part]

    # Export: Bilder und Video -------------------------------------------------------------------------------------
    def _export_size(self, width: int) -> tuple[int, int]:
        ratio = self.docHeight / self.docWidth if self.docWidth > 0 else 9 / 16
        height = int(round(width * ratio / 2)) * 2  # gerade (Video)
        if height > 4096:
            height = 4096
            width = int(round(height / ratio / 2)) * 2
        return width, max(2, height)

    def _render_slides(self, folder: Path, width: int, height: int, kind: str, order: list[int],
                       each: Callable[[int, Path], None], then: Callable[[], None], stop: Callable[[], bool]) -> None:
        """Folien in ``width`` × ``height`` als Bilder (``kind`` png oder jpg) nach ``folder`` malen lassen – wie beim
        Vorführen, ohne leere Platzhalter (Makro »FolienBilder«); je zwei Folien ein Auftrag, damit Klicks und Tasten
        dazwischen drankommen."""
        pending = [index for index in order if 0 <= index < self.slideCount]

        def step() -> None:
            if self._closed or stop():
                return
            if not pending:
                then()
                return
            batch = [pending.pop(0)]
            while pending and len(batch) < 2 and pending[0] == batch[-1] + 1:
                batch.append(pending.pop(0))

            def done(_result) -> None:
                if self._closed or stop():
                    return
                for index in batch:
                    path = folder / f"folie-{index + 1}.{kind}"
                    if path.is_file():
                        each(index, path)
                step()

            def failed(exc) -> None:
                if not self._closed and not stop():
                    self._export_done()
                    self.app.notify("reader", "error", str(exc), title="Folienbilder")

            self.macro("FolienBilder", [QUrl.fromLocalFile(str(folder)).toString(), width, height, kind, batch[0], batch[-1]],
                       done, failed, module="Folien")

        step()

    def _render_all(self, width: int, height: int, kind: str, each: Callable[[int, Path], None], then: Callable[[], None],
                    weight: float = 1.0) -> None:
        """Alle Folien für einen Export: ``each`` je Bild (Datei in einem Arbeitsordner, danach gelöscht)."""
        folder = Path(tempfile.mkdtemp(prefix="novadesk-export-"))
        count = max(1, self.slideCount)
        seen = [0]

        def one(index: int, path: Path) -> None:
            each(index, path)
            seen[0] += 1
            self.exportProgress = seen[0] / count * weight

        def finished() -> None:
            then()
            shutil.rmtree(folder, ignore_errors=True)

        def stop() -> bool:
            if self._export_cancel:
                shutil.rmtree(folder, ignore_errors=True)
                self._export_done()
                return True
            return False

        self._render_slides(folder, width, height, kind, list(range(self.slideCount)), one, finished, stop)

    def _export_start(self) -> bool:
        if self.exporting or not self.ready:
            return False
        if self.masterMode:
            self.app.notify("reader", "warning", "Bitte zuerst die Masteransicht schließen.", title="Export", auto_hide=6000)
            return False
        self._export_cancel = False
        self.exporting = True
        self.exportProgress = 0.0
        return True

    def _export_done(self) -> None:
        self.exporting = False
        self._writer = None

    @Slot()
    def cancelExport(self) -> None:  # noqa: N802
        self._export_cancel = True
        if self._writer is not None:
            self._writer.cancel()

    @Slot()
    def exportImages(self) -> None:  # noqa: N802
        from .. import files

        fields = [
            {"key": "format", "type": "choice", "label": "Dateiformat", "value": "png",
             "options": [{"key": "png", "label": "PNG (verlustfrei)"}, {"key": "jpg", "label": "JPEG (kleinere Dateien)"}]},
            {"key": "size", "type": "choice", "label": "Größe", "value": "1920",
             "options": [{"key": str(value), "label": label} for label, value in EXPORT_SIZES]},
            {"key": "note", "type": "note", "label": "Jede Folie wird ein eigenes Bild, z. B. »Folie 01.png«."},
        ]
        answer, values = self._form("Folien als Bilder speichern", fields, "Weiter")
        if answer != "primary":
            return
        folder = files.pick_folder("Ordner für die Bilder", self.app.initial_dir("reader", str(Path(self.path).parent) if self.path else ""))
        if not folder or not self._export_start():
            return
        suffix = "jpg" if values.get("format") == "jpg" else "png"
        width, height = self._export_size(int(_number(values.get("size"), 1920)))
        stem = Path(self.name or "Präsentation").stem
        digits = max(2, len(str(self.slideCount)))
        target = Path(folder)
        written: list[str] = []

        def each(index: int, source: Path) -> None:
            path = target / f"{stem} – Folie {index + 1:0{digits}d}.{suffix}"
            try:
                shutil.move(str(source), str(path))
            except OSError as exc:
                _log().warning("Folienbild %s: %s", path, exc)
                return
            written.append(str(path))

        def then() -> None:
            self._export_done()
            if not written:
                self.app.notify("reader", "error", "Die Bilder ließen sich nicht speichern.", title="Folien als Bilder")
                return
            self.app.remember_dir("reader", str(target))
            self.app.notify("reader", "success", f"{len(written)} Bilder gespeichert in »{target.name}«.",
                            title="Folien als Bilder", auto_hide=10000, actions=[("Ordner öffnen", lambda: _open(target))])

        self.app.set_status("Folien werden als Bilder gespeichert …", "busy")
        self._render_all(width, height, suffix, each, then)

    @Slot()
    def exportVideo(self) -> None:  # noqa: N802
        from .. import files
        from . import video

        if not video.available():
            self.app.notify("reader", "error", "Auf diesem PC fehlt ein Videoformat zum Speichern.", title="Als Video speichern")
            return
        fields = [
            {"key": "size", "type": "choice", "label": "Größe", "value": "1920",
             "options": [{"key": str(value), "label": label} for label, value in EXPORT_SIZES[:2]]},
            {"key": "seconds", "type": "choice", "label": "Jede Folie zeigen", "value": "auto",
             "options": [{"key": "auto", "label": "Wie eingestellt (sonst 5 Sekunden)"}] +
                        [{"key": str(n), "label": f"{n} Sekunden"} for n in (3, 5, 8, 10, 15)]},
            {"key": "transitions", "type": "check", "label": "Übergänge als Überblenden zeigen", "value": True},
            {"key": "note", "type": "note", "label": "Videos und Töne auf den Folien kommen nicht mit ins Video."},
        ]
        answer, values = self._form("Als Video speichern", fields, "Weiter")
        if answer != "primary":
            return
        folder = str(Path(self.path).parent) if self.path else self.app.initial_dir("reader", self.reader.source_dir)
        target = files.save_file("Als Video speichern", str(Path(folder) / (Path(self.name or "Präsentation").stem + ".mp4")),
                                 "Video (*.mp4)")
        if not target:
            return
        if not target.lower().endswith(".mp4"):
            target += ".mp4"
        if not self._export_start():
            return
        width, height = self._export_size(int(_number(values.get("size"), 1920)))
        fixed = values.get("seconds")
        with_transitions = bool(values.get("transitions"))
        slides: list = []

        def each(index: int, path: Path) -> None:
            image = QImage(str(path)).convertToFormat(QImage.Format.Format_RGB32)
            if image.isNull():
                return
            entry = self._transition(index)
            seconds = float(entry.get("advance") or 0) if fixed == "auto" else _number(fixed, 5.0)
            slides.append(video.Slide(image, seconds if seconds > 0 else 5.0,
                                      entry.get("kind", "keiner") if with_transitions else "keiner"))

        def then() -> None:
            try:
                writer = video.VideoWriter(target, slides, QSize(width, height), self)
            except (RuntimeError, ImportError) as exc:
                self._export_done()
                self.app.notify("reader", "error", str(exc), title="Als Video speichern")
                return
            self._writer = writer
            writer.progress.connect(lambda share: setattr(self, "exportProgress", 0.3 + 0.7 * share))
            writer.finished.connect(finished)
            writer.failed.connect(failed)
            self.app.set_status("Video wird geschrieben …", "busy")
            writer.start()

        def finished(path: str) -> None:
            self._export_done()
            name = Path(path).name
            self.app.set_status(f"Gespeichert: {name}", "success")
            self.app.notify("reader", "success", f"»{name}« wurde gespeichert.", title="Als Video gespeichert", auto_hide=10000,
                            actions=[("Abspielen", lambda: _open(Path(path))), ("Ordner öffnen", lambda: _open(Path(path).parent))])

        def failed(message: str) -> None:
            self._export_done()
            if message:
                self.app.notify("reader", "error", message, title="Als Video speichern")
            else:
                self.app.set_status("Video abgebrochen", "neutral")

        self.app.set_status("Folien werden vorbereitet …", "busy")
        self._render_all(width, height, "png", each, then, weight=0.3)

    def _form(self, title: str, fields: list[dict], primary: str) -> tuple[str, dict]:
        answer, data = self.app.dialogs.ask("sheet_form", title, "", primary=primary, secondary="Abbrechen",
                                            data={"fields": fields}, width=460)
        values = {field["key"]: field.get("value") for field in fields if field.get("key")}
        values.update({key: value for key, value in (data or {}).items() if key != "fields"})
        return answer, values


def _number(value, default: float) -> float:
    try:
        return float(str(value).replace(",", ".").strip())
    except (TypeError, ValueError):
        return default


def _text(value: float) -> str:
    return f"{value:g}"


def _open(path: Path) -> None:
    from .. import files

    try:
        files.open_path(path)
    except OSError:
        pass


def _video_size(path: Path) -> tuple[int, int]:
    """Breite und Höhe eines MP4/MOV-Videos aus dem Kopf der Datei (»tkhd« der Videospur); sonst (0, 0) = 16:9."""
    import struct

    try:
        with path.open("rb") as handle:
            data = handle.read(4 * 1024 * 1024)
            size = path.stat().st_size
            if size > len(data):  # »moov« steht oft am Ende
                handle.seek(max(len(data), size - 4 * 1024 * 1024))
                data += handle.read()
    except OSError:
        return 0, 0
    best = (0, 0)
    start = 0
    while True:
        at = data.find(b"tkhd", start)
        if at < 4:
            break
        start = at + 4
        version = data[at + 4] if at + 4 < len(data) else 0
        offset = at + 4 + (88 if version == 1 else 76)
        if offset + 8 > len(data):
            break
        width, height = struct.unpack(">II", data[offset:offset + 8])
        width, height = width >> 16, height >> 16
        if width and height:
            best = (width, height)
            break
    return best
