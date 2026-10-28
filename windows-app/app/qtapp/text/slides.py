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
from pathlib import Path
from typing import Callable

from PySide6.QtCore import Property, QObject, QTimer, Signal, Slot

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

    def _get_notes(self) -> QObject:
        return self._notes

    _notes_constant = Signal()
    notes = Property(QObject, _get_notes, notify=_notes_constant)

    # Öffnen ------------------------------------------------------------------------------------------------------
    def open(self, path: str, done: Callable[[], None], failed: Callable[[BaseException], None],
             password: str | None = None) -> None:
        self.name = Path(path).name if path else self.name or "Präsentation1.pptx"

        def opened() -> None:
            self.refresh_parts()
            self.refresh_notes()
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
        self._call("thumb", {"part": int(part), "pw": int(pw), "ph": int(ph), "w": self.docWidth, "h": self.docHeight},
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
        self.presentIndex = self.slideIndex
        self.presenting = True

    @Slot()
    def presentFromStart(self) -> None:  # noqa: N802
        self.presentIndex = 0
        self.presenting = True

    @Slot()
    def endPresent(self) -> None:  # noqa: N802
        if self.presenting:
            self.presenting = False
            self.goSlide(self.presentIndex)

    @Slot(int)
    def presentStep(self, direction: int) -> None:  # noqa: N802
        index = self.presentIndex + (1 if direction > 0 else -1)
        if index < 0:
            return
        if index >= self.slideCount:
            self.endPresent()
            return
        self.presentIndex = index

