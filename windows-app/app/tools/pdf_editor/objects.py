"""Objekt bearbeiten: einzelne Textsegmente, Wörter und Bilder statt ganzer Textblöcke.

Unterschied zu »Text bearbeiten« (``textedit``): Dort ist die Einheit ein logischer Textblock (Absatz)
mit Cursor, Umbruch und Neusatz. Hier sind es die kleinsten sinnvollen Einheiten, wie sie im PDF
stehen – eine Zeile einer Adresse, eine Tabellenzelle, ein Wort –, die sich einzeln ändern,
verschieben, formatieren und löschen lassen. Alles andere auf der Seite bleibt, wo es ist.

**Segmentierung** (nur ein Modell – die Datei ändert sich erst mit einer Aktion). PDFium liefert je
Zeichen Box, Ursprung, Schrift, Größe, Farbe und Textobjekt (= Textoperator ``Tj``/``TJ``/``'``/``"``).
Eine sichtbare Zeile ist oft mehrere Operatoren, ein Operator manchmal mehrere Zeilen oder Spalten –
gruppiert wird deshalb nach Geometrie, nicht nach Operatoren:

1. Zeilen: Zeichen gleicher Richtung auf derselben Grundlinie (Abstand ≤ 35 % der Schriftgröße), in
   Schreibrichtung fortlaufend.
2. Segmente: innerhalb einer Zeile Trennung an großen Lücken (≥ 0,9 Geviert – Tabellenspalten,
   abgesetzte Werte) und an Wechseln von Schrift, Größe (> 15 %), Farbe oder Darstellungsart.
3. Wörter: innerhalb eines Segments an Leerzeichen oder geometrischen Lücken ≥ 0,15 Geviert (viele
   PDFs setzen Wortabstände als TJ-Verschiebung ohne Leerzeichen).

Toleranzen in Dokumentkoordinaten relativ zur Schriftgröße – unabhängig von Zoom und DPI.

**Änderungen im Inhaltsstrom (nativ).** Jeder betroffene Textoperator wird an Code-Grenzen in Teile
zerlegt – syntaktisch, die Darstellung bleibt identisch (Verschiebungen innerhalb von TJ bleiben an
ihrem Platz). Dann, nur für die Zielteile:

* Text ändern: neuer Text in der Originalschrift (Kodierung und Glyphen geprüft); eine
  TJ-Verschiebung hält alles Folgende an seinem Platz.
* Löschen: der Teil wird zu einer reinen Verschiebung gleicher Breite.
* Verschieben: eigene Textmatrix (``Tm``) für den Teil; danach Text- und Zeilenmatrix wie vorher.
* Größe, Farbe, Zeichenabstand: Zustand nur für den Teil, danach wiederhergestellt.

Geht das nicht nativ (Zeichen fehlen in der Schrift): **neu gesetzt** – Original entfernt, neuer Text
an derselben Stelle (``RECONSTRUCTED``). Liegt der Text in einem Formular-XObject oder ist er keinem
Operator sicher zugeordnet: **Überlagerung** als letzter Ausweg (Hintergrund gemessen, nicht pauschal
weiß; der Originaltext bleibt in der Datei – keine Schwärzung). Verschieben und Formatieren gibt es
nur nativ.

Jede Änderung wird geprüft (Darstellung nur im betroffenen Bereich verändert, Text lesbar) und ist
ein Schritt für Rückgängig. Gespeichert wird über ``save`` wie jede andere Änderung.
"""

from __future__ import annotations

import ctypes
import math
from collections import Counter
from dataclasses import dataclass, field

import pikepdf
from pikepdf import Operator

from pdfium_lock import PDFIUM_LOCK

from . import commands, render, textedit, textlayer
from .commands import History
from .content import PageContent, ShowOp, append_content, fmt, invert, mul, page_fonts
from .document import EditorDocument
from .errors import UnsupportedEdit
from .geometry import Rect, inflate, normalize, union

NATIVE, RECONSTRUCTED, OVERLAY = textedit.NATIVE, textedit.RECONSTRUCTED, textedit.OVERLAY
LINE_TOLERANCE = 0.35  # Abstand der Grundlinien (Anteil der Schriftgröße) für »dieselbe Zeile«
SEGMENT_GAP = 0.9  # Lücke in Geviert, ab der ein neues Segment beginnt
WORD_GAP = 0.15  # Lücke in Geviert ohne Leerzeichen, ab der ein neues Wort beginnt
SIZE_CHANGE = 0.15  # relative Größenänderung, ab der ein neues Segment beginnt
INVISIBLE = textedit.INVISIBLE
NO_TEXT = "Auf dieser Seite wurde kein bearbeitbarer PDF-Text erkannt."


# --- Modell ------------------------------------------------------------------------------------------------
@dataclass
class Glyph:
    char: str
    box: Rect  # Seitenkoordinaten (lose Zeichenbox)
    origin: tuple[float, float]  # Ursprung auf der Grundlinie
    run: int  # Index in ``PageObjects.runs``
    code: int = -1  # Position des Codes im Textoperator (−1: unbekannt)

    @property
    def space(self) -> bool:
        return not self.char.strip()


@dataclass
class TextRun:
    """Zeichen eines PDFium-Textobjekts (= eines Textoperators)."""

    obj: int  # Index unter den Textobjekten der obersten Ebene (−1: in einem Formular-XObject)
    font: str
    size: float
    color: tuple[int, int, int]
    angle: float
    render_mode: int
    glyphs: list[int] = field(default_factory=list)
    show: int = -1  # Index in ``PageContent.shows`` (−1: nicht sicher zugeordnet)
    exact: bool = False  # jeder Code ergibt genau ein Zeichen – Teilen an Code-Grenzen möglich


@dataclass
class Word:
    id: str
    first: int  # erster Glyph (einschließlich)
    last: int  # letzter Glyph (einschließlich)
    text: str
    bounds: Rect


@dataclass
class Segment:
    """Kleinste sinnvolle Texteinheit: zusammenhängender Text einer Zeile."""

    id: str
    page: int
    first: int
    last: int
    text: str
    bounds: Rect
    words: list[Word]
    font: str
    size: float
    color: tuple[int, int, int]
    angle: float
    line: int
    native_reason: str = ""

    @property
    def native(self) -> bool:
        return not self.native_reason


@dataclass
class PageObjects:
    page: int
    revision: int
    glyphs: list[Glyph]
    runs: list[TextRun]
    segments: list[Segment]
    mapped: bool
    reason: str

    def segment(self, ident: str) -> Segment:
        for segment in self.segments:
            if segment.id == ident:
                return segment
        raise UnsupportedEdit("Das Objekt ist nicht mehr vorhanden. Bitte erneut auswählen.")

    def target(self, ident: str) -> tuple[Segment, int, int]:
        """Segment oder Wort (``<segment>/w<n>``): (Segment, erster, letzter Glyph)."""
        segment_id, _, word = ident.partition("/")
        segment = self.segment(segment_id)
        if not word:
            return segment, segment.first, segment.last
        for item in segment.words:
            if item.id == ident:
                return segment, item.first, item.last
        raise UnsupportedEdit("Das Wort ist nicht mehr vorhanden. Bitte erneut auswählen.")

    def text_of(self, first: int, last: int) -> str:
        return "".join(glyph.char for glyph in self.glyphs[first : last + 1]).strip()

    def bounds_of(self, first: int, last: int) -> Rect:
        box = None
        for glyph in self.glyphs[first : last + 1]:
            if not glyph.space:
                box = union(box, glyph.box)
        return box or self.glyphs[first].box


# --- Analyse -------------------------------------------------------------------------------------------------
def analyze(document: EditorDocument, page: int) -> PageObjects:
    """Textsegmente und Wörter einer Seite (nur lesen)."""
    glyphs, runs = _glyphs(document, page)
    mapped, reason = False, ""
    try:
        obj = document.pdf.pages[page].obj
        content = PageContent(document.pdf, obj, page_fonts(obj))
        mapped, reason = _map(document, page, content, glyphs, runs)
    except (pikepdf.PdfError, ValueError, TypeError):
        content, reason = None, "Der Inhalt der Seite lässt sich nicht sicher lesen."
    result = PageObjects(page, document.revision, glyphs, runs, [], mapped, reason)
    result.segments = _segments(page, glyphs, runs)
    for segment in result.segments:
        segment.native_reason = _native_reason(document, result, content, segment)
    return result


def _handle(value) -> int:
    return ctypes.cast(value, ctypes.c_void_p).value or 0


def _glyphs(document: EditorDocument, page: int) -> tuple[list[Glyph], list[TextRun]]:
    import pypdfium2.raw as r

    glyphs: list[Glyph] = []
    runs: list[TextRun] = []
    with PDFIUM_LOCK:
        textpage = document.textpage(page)
        pdf_page = document.page_object(page)
        top: dict[int, int] = {}
        text_index = 0
        for index in range(r.FPDFPage_CountObjects(pdf_page.raw)):
            obj = r.FPDFPage_GetObject(pdf_page.raw, index)
            if r.FPDFPageObj_GetType(obj) == r.FPDF_PAGEOBJ_TEXT:
                top[_handle(obj)] = text_index
                text_index += 1
        current_key = None
        matrix = r.FS_MATRIX()
        for i in range(textpage.count_chars()):
            if r.FPDFText_IsGenerated(textpage.raw, i) == 1:
                continue
            obj = r.FPDFText_GetTextObject(textpage.raw, i)
            key = _handle(obj)
            if key != current_key:
                r.FPDFText_GetMatrix(textpage.raw, i, matrix)  # Textmatrix × CTM (ohne Schriftgröße)
                size = float(r.FPDFText_GetFontSize(textpage.raw, i)) * math.hypot(matrix.c, matrix.d)
                buffer = ctypes.create_string_buffer(256)
                flags = ctypes.c_int()
                r.FPDFText_GetFontInfo(textpage.raw, i, buffer, 256, flags)
                red, green, blue, alpha = (ctypes.c_uint() for _ in range(4))
                r.FPDFText_GetFillColor(textpage.raw, i, red, green, blue, alpha)
                angle = round(math.degrees(math.atan2(matrix.b, matrix.a)), 1) % 360
                mode = int(r.FPDFTextObj_GetTextRenderMode(obj)) if obj else 0
                runs.append(TextRun(top.get(key, -1), buffer.value.decode("latin-1", "replace"), round(size, 2), (red.value, green.value, blue.value), angle, mode))
                current_key = key
            char = chr(r.FPDFText_GetUnicode(textpage.raw, i) or 0xFFFD)
            left, bottom, right, top_ = textpage.get_charbox(i, loose=True)
            x, y = ctypes.c_double(), ctypes.c_double()
            r.FPDFText_GetCharOrigin(textpage.raw, i, x, y)
            runs[-1].glyphs.append(len(glyphs))
            glyphs.append(Glyph(char, normalize((left, bottom, right, top_)), (x.value, y.value), len(runs) - 1))
    return glyphs, runs


def _object_texts(document: EditorDocument, page: int) -> list[str]:
    import pypdfium2.raw as r

    texts: list[str] = []
    with PDFIUM_LOCK:
        textpage = document.textpage(page)
        pdf_page = document.page_object(page)
        for index in range(r.FPDFPage_CountObjects(pdf_page.raw)):
            obj = r.FPDFPage_GetObject(pdf_page.raw, index)
            if r.FPDFPageObj_GetType(obj) != r.FPDF_PAGEOBJ_TEXT:
                continue
            n = r.FPDFTextObj_GetText(obj, textpage.raw, None, 0)
            buffer = ctypes.create_string_buffer(max(2, n))
            r.FPDFTextObj_GetText(obj, textpage.raw, ctypes.cast(buffer, ctypes.POINTER(r.FPDF_WCHAR)), n)
            texts.append(buffer.raw[: max(0, n - 2)].decode("utf-16-le", "replace"))
    return texts


def _map(document: EditorDocument, page: int, content: PageContent, glyphs: list[Glyph], runs: list[TextRun]) -> tuple[bool, str]:
    """PDFium-Textobjekte ↔ Textoperatoren (gleiche Reihenfolge und gleicher Text, wie ``textedit``),
    dann je Operator Codes ↔ Zeichen (eins zu eins)."""
    import re

    failed = (False, "Die Textstruktur der Seite lässt keine direkte Änderung zu.")
    texts = _object_texts(document, page)
    shows = [i for i, show in enumerate(content.shows) if show.raw]
    if len(texts) != len(shows):
        return failed
    for show_index, text in zip(shows, texts):
        if re.sub(r"\s+", "", content.text_of(content.shows[show_index])) != re.sub(r"\s+", "", text) and text.strip():
            return failed
    used: dict[int, int] = {}
    for run in runs:
        if run.obj >= 0:
            used[run.obj] = used.get(run.obj, 0) + 1
    for run in runs:
        if run.obj < 0 or used[run.obj] != 1:
            continue  # Formular-XObject oder ein Objekt in mehreren Stücken: nicht sicher zuzuordnen
        run.show = shows[run.obj]
        show = content.shows[run.show]
        codec = content.codec(show.state.font)
        if codec is None or not codec.editable or _vertical(show, content):
            continue
        codes = codec.codes(show.raw)
        if len(codes) == len(run.glyphs):
            run.exact = True
            for position, glyph in enumerate(run.glyphs):
                glyphs[glyph].code = position
    return True, ""


def _vertical(show: ShowOp, content: PageContent) -> bool:
    font = content.fonts.get(show.state.font)
    return isinstance(font, pikepdf.Dictionary) and str(font.get("/Encoding", "")) == "/Identity-V"


def _direction(angle: float) -> tuple[float, float]:
    rad = math.radians(angle)
    return (math.cos(rad), math.sin(rad))


def _along(glyph: Glyph, u: tuple[float, float]) -> tuple[float, float]:
    """Anfang und Ende einer Zeichenbox in Schreibrichtung."""
    x0, y0, x1, y1 = glyph.box
    values = [x * u[0] + y * u[1] for x, y in ((x0, y0), (x1, y0), (x0, y1), (x1, y1))]
    return min(values), max(values)


def _segments(page: int, glyphs: list[Glyph], runs: list[TextRun]) -> list[Segment]:
    lines: list[list[int]] = []
    for index, glyph in enumerate(glyphs):
        run = runs[glyph.run]
        if run.render_mode == INVISIBLE:
            continue  # unsichtbarer Text (Texterkennung eines Scans): kein sichtbares Objekt
        if lines:
            last = glyphs[lines[-1][-1]]
            prev = runs[last.run]
            if abs(run.angle - prev.angle) < 1:
                u = _direction(run.angle)
                normal = (-u[1], u[0])
                dy = (glyph.origin[0] - last.origin[0]) * normal[0] + (glyph.origin[1] - last.origin[1]) * normal[1]
                dx = (glyph.origin[0] - last.origin[0]) * u[0] + (glyph.origin[1] - last.origin[1]) * u[1]
                size = max(run.size, prev.size, 1.0)
                if abs(dy) <= LINE_TOLERANCE * size and dx > -0.5 * size:
                    lines[-1].append(index)
                    continue
        lines.append([index])
    segments: list[Segment] = []
    for number, line in enumerate(lines):
        for part in _split_line(glyphs, runs, line):
            ink = [i for i in part if not glyphs[i].space]
            if not ink:
                continue
            first, last = ink[0], ink[-1]
            run = runs[glyphs[first].run]
            ident = f"{page}-{len(segments)}"
            words = _words(ident, glyphs, runs, first, last)
            box = None
            for i in ink:
                box = union(box, glyphs[i].box)
            text = "".join(glyphs[i].char for i in range(first, last + 1))
            segments.append(Segment(ident, page, first, last, text, box, words, run.font, run.size, run.color, run.angle, number))
    return segments


def _split_line(glyphs: list[Glyph], runs: list[TextRun], line: list[int]) -> list[list[int]]:
    parts: list[list[int]] = [[]]
    previous_ink: int | None = None
    for index in line:
        glyph = glyphs[index]
        if glyph.space:
            parts[-1].append(index)
            continue
        if previous_ink is not None:
            a, b = runs[glyphs[previous_ink].run], runs[glyph.run]
            u = _direction(b.angle)
            gap = _along(glyph, u)[0] - _along(glyphs[previous_ink], u)[1]
            size = max(a.size, b.size, 1.0)
            if (
                gap >= SEGMENT_GAP * size
                or a.font != b.font
                or abs(a.size - b.size) > SIZE_CHANGE * max(a.size, b.size)
                or a.color != b.color
                or a.render_mode != b.render_mode
            ):
                parts.append([])
        parts[-1].append(index)
        previous_ink = index
    return parts


def _words(ident: str, glyphs: list[Glyph], runs: list[TextRun], first: int, last: int) -> list[Word]:
    groups: list[list[int]] = []
    previous: int | None = None
    for index in range(first, last + 1):
        glyph = glyphs[index]
        if glyph.space:
            previous = None
            continue
        if previous is not None:
            run = runs[glyph.run]
            u = _direction(run.angle)
            gap = _along(glyph, u)[0] - _along(glyphs[previous], u)[1]
            if gap >= WORD_GAP * max(run.size, 1.0):
                previous = None
        if previous is None:
            groups.append([])
        groups[-1].append(index)
        previous = index
    words = []
    for number, group in enumerate(groups):
        box = None
        for i in group:
            box = union(box, glyphs[i].box)
        words.append(Word(f"{ident}/w{number}", group[0], group[-1], "".join(glyphs[i].char for i in range(group[0], group[-1] + 1)), box))
    return words


def _native_reason(document: EditorDocument, objects: PageObjects, content: PageContent | None, segment: Segment) -> str:
    if document.read_only:
        return document.read_only_reason
    if not objects.mapped or content is None:
        return objects.reason or "Die Textstruktur der Seite lässt keine direkte Änderung zu."
    for index in range(segment.first, segment.last + 1):
        run = objects.runs[objects.glyphs[index].run]
        if run.obj < 0:
            return "Der Text liegt in einem eingebetteten Formular-Objekt."
        if run.show < 0:
            return "Der Text ist keinem Textoperator eindeutig zugeordnet."
        if not run.exact:
            return "Die Schrift dieses Textes lässt keine direkte Änderung zu."
    return ""


# --- Treffer (Seitenkoordinaten) ---------------------------------------------------------------------------
def segment_at(objects: PageObjects, x: float, y: float, tolerance: float = 1.0) -> Segment | None:
    """Segment unter einem Punkt; bei Überschneidung das kleinste (genaueste)."""
    hits = [s for s in objects.segments if _inside(inflate(s.bounds, tolerance), x, y)]
    return min(hits, key=lambda s: (s.bounds[2] - s.bounds[0]) * (s.bounds[3] - s.bounds[1])) if hits else None


def word_at(segment: Segment, x: float, y: float, tolerance: float = 1.0) -> Word | None:
    hits = [w for w in segment.words if _inside(inflate(w.bounds, tolerance), x, y)]
    return hits[0] if hits else None


def _inside(rect: Rect, x: float, y: float) -> bool:
    return rect[0] <= x <= rect[2] and rect[1] <= y <= rect[3]


# --- Ändern ----------------------------------------------------------------------------------------------------
@dataclass
class ObjectOutcome:
    mode: str  # NATIVE, RECONSTRUCTED oder OVERLAY
    bounds: Rect  # betroffener Bereich nachher (Seitenkoordinaten)
    notes: list[str] = field(default_factory=list)

    @property
    def label(self) -> str:
        return textedit.MODE_LABELS[self.mode]  # dieselben Worte wie in »Text bearbeiten«


class _NotNative(Exception):
    """Diese Änderung geht im Inhaltsstrom nicht sicher – Grund für das Protokoll und die Meldung."""


@dataclass
class _Action:
    kind: str  # "text", "delete", "move", "size", "color", "spacing"
    data: bytes | None = None  # neuer Text (kodiert) – nur für den ersten Teil eines Segments
    shift: tuple[float, float] = (0.0, 0.0)  # Verschiebung (Benutzerraum des Operators)
    size: float = 0.0
    color: tuple[int, int, int] = (0, 0, 0)
    spacing: float = 0.0


def _check_revision(document: EditorDocument, objects: PageObjects) -> None:
    document.ensure_editable()
    if objects.revision != document.revision:
        raise UnsupportedEdit("Die Auswahl ist nicht mehr aktuell. Bitte erneut auswählen.")


def edit_text(document: EditorDocument, history: History, objects: PageObjects, ident: str, new_text: str) -> ObjectOutcome:
    """Text genau dieses Segments bzw. Worts ändern (leer = löschen) – sonst ändert sich nichts.
    Nativ in der Originalschrift, sonst neu gesetzt; Überlagerung nur als letzter Ausweg."""
    _check_revision(document, objects)
    segment, first, last = objects.target(ident)
    new_text = " ".join(new_text.replace("\r", "").replace("\n", " ").split())
    if not new_text:
        return delete(document, history, objects, [ident])
    old_text = objects.text_of(first, last)
    if new_text == old_text:
        return ObjectOutcome(NATIVE, objects.bounds_of(first, last))
    page = segment.page
    before, before_text = _snapshot(document, page)
    reasons = []
    if segment.native:
        for mode in (NATIVE, RECONSTRUCTED):
            try:
                with commands.record(document, history, "Text ändern", pages=(page,)) as rec:
                    rec.page(page)
                    outcome = (_edit_native if mode == NATIVE else _edit_rebuild)(document, objects, segment, first, last, new_text)
                    rec.info["mode"] = outcome.mode
                    _verify(document, page, before, before_text, objects.bounds_of(first, last), outcome, new_text, old_text)
                    rec.fresh = True
                return outcome
            except _NotNative as reason:
                reasons.append(str(reason))
    try:
        with commands.record(document, history, "Text ändern", pages=(page,)) as rec:
            rec.page(page)
            outcome = _overlay(document, objects, segment, first, last, new_text)
            rec.info["mode"] = outcome.mode
            _verify(document, page, before, before_text, objects.bounds_of(first, last), outcome, new_text, old_text)
            rec.fresh = True
    except _NotNative as reason:
        reasons.append(str(reason))
        raise UnsupportedEdit("Der Text lässt sich hier nicht sicher ändern. " + reasons[-1]) from reason
    if segment.native_reason:
        outcome.notes.insert(0, segment.native_reason)
    return outcome


def delete(document: EditorDocument, history: History, objects: PageObjects, idents: list[str]) -> ObjectOutcome:
    """Ausgewählte Segmente bzw. Wörter löschen – nur sie, nie den ganzen Block."""
    _check_revision(document, objects)
    targets = [objects.target(ident) for ident in idents]
    if not targets:
        raise UnsupportedEdit("Es ist nichts ausgewählt.")
    page = targets[0][0].page
    before, before_text = _snapshot(document, page)
    area = None
    for segment, first, last in targets:
        area = union(area, objects.bounds_of(first, last))
    native = all(segment.native for segment, _first, _last in targets)
    title = "Objekte löschen" if len(targets) > 1 else "Text löschen"
    try:
        with commands.record(document, history, title, pages=(page,)) as rec:
            rec.page(page)
            if native and len(targets) == 1 and (targets[0][1], targets[0][2]) != (targets[0][0].first, targets[0][0].last):
                outcome = _delete_word(document, objects, *targets[0])
            elif native:
                _apply(document, objects, [(first, last, _Action("delete")) for _segment, first, last in targets])
                outcome = ObjectOutcome(NATIVE, area)
            else:
                outcome = _cover(document, objects, targets)
            rec.info["mode"] = outcome.mode
            removed = [objects.text_of(first, last) for _segment, first, last in targets]
            _verify(document, page, before, before_text, area, outcome, "", removed)
            rec.fresh = True
    except _NotNative as reason:
        raise UnsupportedEdit("Das lässt sich hier nicht sicher löschen. " + str(reason)) from reason
    if outcome.mode == OVERLAY:
        outcome.notes.insert(0, "Der Text wurde überdeckt und bleibt in der Datei enthalten (keine Schwärzung).")
    return outcome


def _delete_word(document: EditorDocument, objects: PageObjects, segment: Segment, first: int, last: int) -> ObjectOutcome:
    """Ein Wort aus einem Segment löschen – samt einem Wortabstand; der Rest des Segments rückt nach."""
    following = next((word for word in segment.words if word.first > last), None)
    if following is not None:
        end = following.first - 1  # Wort und die Leerzeichen danach
        start_point, next_point = objects.glyphs[first].origin, objects.glyphs[following.first].origin
        shift = (start_point[0] - next_point[0], start_point[1] - next_point[1])
        _apply(document, objects, [(first, end, _Action("delete")), (following.first, segment.last, _Action("move", shift=shift))])
        rest = objects.bounds_of(following.first, segment.last)
        return ObjectOutcome(NATIVE, union(objects.bounds_of(first, last), union(rest, (rest[0] + shift[0], rest[1] + shift[1], rest[2] + shift[0], rest[3] + shift[1]))))
    previous = max((word.last for word in segment.words if word.last < first), default=None)
    start = previous + 1 if previous is not None else first  # letztes Wort: mit den Leerzeichen davor
    _apply(document, objects, [(start, last, _Action("delete"))])
    return ObjectOutcome(NATIVE, objects.bounds_of(first, last))


def move(document: EditorDocument, history: History, objects: PageObjects, idents: list[str], dx: float, dy: float, *, title: str = "Verschieben") -> ObjectOutcome:
    """Segmente bzw. Wörter um (dx, dy) Seitenpunkte verschieben (nur nativ – nie durch Überdecken)."""
    _check_revision(document, objects)
    targets = [objects.target(ident) for ident in idents]
    if not targets:
        raise UnsupportedEdit("Es ist nichts ausgewählt.")
    for segment, _first, _last in targets:
        if not segment.native:
            raise UnsupportedEdit("Dieser Text lässt sich nicht verschieben: " + segment.native_reason)
    page = targets[0][0].page
    before, before_text = _snapshot(document, page)
    old = new = None
    for _segment, first, last in targets:
        box = objects.bounds_of(first, last)
        old = union(old, box)
        new = union(new, (box[0] + dx, box[1] + dy, box[2] + dx, box[3] + dy))
    try:
        with commands.record(document, history, title, pages=(page,)) as rec:
            rec.page(page)
            _apply(document, objects, [(first, last, _Action("move", shift=(dx, dy))) for _segment, first, last in targets])
            outcome = ObjectOutcome(NATIVE, new)
            rec.info["mode"] = NATIVE
            _verify(document, page, before, before_text, union(old, new), outcome, None, None)
            rec.fresh = True
    except _NotNative as reason:
        raise UnsupportedEdit("Das lässt sich hier nicht sicher verschieben. " + str(reason)) from reason
    return outcome


def restyle(document: EditorDocument, history: History, objects: PageObjects, idents: list[str], *, size: float | None = None, color: tuple[int, int, int] | None = None, spacing: float | None = None) -> ObjectOutcome:
    """Schriftgröße, Farbe oder Zeichenabstand (eines davon je Aufruf) nur für die Auswahl ändern –
    nativ, alles Folgende bleibt an seinem Platz."""
    _check_revision(document, objects)
    chosen = [name for name, value in (("size", size), ("color", color), ("spacing", spacing)) if value is not None]
    if len(chosen) != 1:
        raise UnsupportedEdit("Bitte genau eine Eigenschaft ändern.")
    if size is not None and not 1.0 <= float(size) <= 400.0:
        raise UnsupportedEdit("Die Schriftgröße muss zwischen 1 und 400 pt liegen.")
    targets = [objects.target(ident) for ident in idents]
    if not targets:
        raise UnsupportedEdit("Es ist nichts ausgewählt.")
    for segment, _first, _last in targets:
        if not segment.native:
            raise UnsupportedEdit("Die Formatierung dieses Textes lässt sich nicht ändern: " + segment.native_reason)
    page = targets[0][0].page
    before, before_text = _snapshot(document, page)
    action = _Action(chosen[0], size=float(size or 0.0), color=tuple(color or (0, 0, 0)), spacing=float(spacing or 0.0))
    area = None
    for segment, first, last in targets:
        box = objects.bounds_of(first, last)
        if size is not None:
            factor = float(size) / max(0.1, segment.size)
            grow = max(0.0, factor - 1.0)
            box = inflate(_extend(box, segment.angle, (box[2] - box[0]) * factor), segment.size * grow * 1.2)
        elif spacing is not None:
            box = _extend(box, segment.angle, (box[2] - box[0]) + abs(float(spacing)) * (last - first + 1) * 1.5)
        area = union(area, box)
    changes = [(first, last, action) for _segment, first, last in targets]
    if len(targets) == 1 and action.kind in ("size", "spacing"):
        # Ein Wort mitten im Segment: der Rest des Segments rückt nach wie beim Ändern des Textes
        segment, first, last = targets[0]
        obj = document.pdf.pages[page].obj
        content = PageContent(document.pdf, obj, page_fonts(obj))
        if objects.mapped and all(objects.runs[objects.glyphs[i].run].exact for i in range(first, segment.last + 1)):
            delta = _width(content, objects, first, last, size=size, spacing=spacing) - _width(content, objects, first, last)
            shift = _reflow(objects, segment, first, last, delta)
            if shift is not None:
                changes.append((last + 1, segment.last, _Action("move", shift=shift)))
                rest = objects.bounds_of(last + 1, segment.last)
                area = union(area, union(rest, (rest[0] + shift[0], rest[1] + shift[1], rest[2] + shift[0], rest[3] + shift[1])))
    try:
        with commands.record(document, history, "Formatieren", pages=(page,)) as rec:
            rec.page(page)
            _apply(document, objects, changes)
            outcome = ObjectOutcome(NATIVE, area)
            rec.info["mode"] = NATIVE
            _verify(document, page, before, before_text, area, outcome, None, None, wide=size is not None or spacing is not None)
            rec.fresh = True
    except _NotNative as reason:
        raise UnsupportedEdit("Die Formatierung lässt sich hier nicht sicher ändern. " + str(reason)) from reason
    return outcome


# --- Inhaltsstrom umschreiben -------------------------------------------------------------------------------
def _apply(document: EditorDocument, objects: PageObjects, targets: list[tuple[int, int, _Action]]) -> None:
    """Zielbereiche (Glyphen) auf die Textoperatoren abbilden und diese umschreiben."""
    page = objects.page
    obj = document.pdf.pages[page].obj
    content = PageContent(document.pdf, obj, page_fonts(obj))
    if len(content.shows) and not objects.mapped:
        raise _NotNative(objects.reason)
    per_show: dict[int, list[tuple[int, int, _Action]]] = {}
    for first, last, action in targets:
        runs_seen: list[int] = []
        for index in range(first, last + 1):
            glyph = objects.glyphs[index]
            run = objects.runs[glyph.run]
            if run.show < 0 or not run.exact or glyph.code < 0:
                raise _NotNative("Der Text ist keinem Textoperator eindeutig zugeordnet.")
            if glyph.run not in runs_seen:
                runs_seen.append(glyph.run)
        for order, run_index in enumerate(runs_seen):
            codes = [objects.glyphs[i].code for i in objects.runs[run_index].glyphs if first <= i <= last]
            part = action
            if action.kind == "text" and order > 0:
                part = _Action("delete")  # neuer Text steht im ersten Teil, die übrigen Teile werden leer
            per_show.setdefault(objects.runs[run_index].show, []).append((min(codes), max(codes) + 1, part))
    for show_index in sorted(per_show, reverse=True):  # von hinten: frühere Positionen bleiben gültig
        ranges = sorted(per_show[show_index], key=lambda item: item[0])
        if any(ranges[i][1] > ranges[i + 1][0] for i in range(len(ranges) - 1)):
            raise _NotNative("Die Auswahl überschneidet sich.")
        show = content.shows[show_index]
        replacement = _rewrite(content, show, sorted(per_show[show_index], key=lambda item: item[0]))
        content.instructions[show.index : show.index + 1] = replacement
    content.commit()


def _elements(ins, operator: str) -> list:
    operands = list(ins.operands)
    if operator == "TJ":
        array = operands[0] if operands else []
        return [bytes(item) if isinstance(item, pikepdf.String) else float(item) for item in array]
    string = operands[-1] if operands else b""
    return [bytes(string)] if isinstance(string, pikepdf.String) else []


def _cut(elements: list, step: int, cuts: list[int]) -> tuple[list[tuple[int, int]], list[list]]:
    """Elemente (Strings, TJ-Verschiebungen) an Code-Grenzen teilen. Eine Verschiebung gehört zum Teil
    des Codes davor (vor dem ersten Code: zum ersten Teil) – so beginnt jeder Teil genau dort, wo
    sein erster Code gezeichnet wurde."""
    intervals = [(a, b) for a, b in zip(cuts, cuts[1:]) if b > a]
    pieces: list[list] = [[] for _ in intervals]

    def piece_of(code: int) -> int:
        for i, (a, b) in enumerate(intervals):
            if a <= code < b:
                return i
        return len(intervals) - 1

    code = 0
    for item in elements:
        if not isinstance(item, bytes):
            pieces[piece_of(code - 1) if code > 0 else 0].append(item)
            continue
        count = len(item) // step
        offset = 0
        while offset < count:
            i = piece_of(code)
            take = min(count - offset, intervals[i][1] - code)
            pieces[i].append(item[offset * step : (offset + take) * step])
            offset += take
            code += take
    return intervals, pieces


def _advance(piece: list, codec, state) -> float:
    total = 0.0
    for item in piece:
        if isinstance(item, bytes):
            total += codec.text_width(item, state.size, state.char_spacing, state.word_spacing, state.hscale)
        else:
            total -= item / 1000.0 * state.size * state.hscale
    return total


def _tj(items: list) -> pikepdf.ContentStreamInstruction:
    return pikepdf.ContentStreamInstruction([pikepdf.Array([pikepdf.String(item) if isinstance(item, bytes) else item for item in items])], Operator("TJ"))


def _op(operator: str, *operands) -> pikepdf.ContentStreamInstruction:
    return pikepdf.ContentStreamInstruction(list(operands), Operator(operator))


def _rewrite(content: PageContent, show: ShowOp, targets: list[tuple[int, int, _Action]]) -> list:
    ins = content.instructions[show.index]
    codec = content.codec(show.state.font)
    state = show.state
    if codec is None or not codec.editable or state.size == 0 or state.hscale == 0:
        raise _NotNative("Die Schrift dieses Textes lässt keine direkte Änderung zu.")
    step = 2 if codec.two_byte else 1
    total = len(show.raw) // step
    cuts = sorted({0, total, *(a for a, _b, _x in targets), *(b for _a, b, _x in targets)})
    intervals, pieces = _cut(_elements(ins, show.operator), step, cuts)
    out: list = []
    operands = list(ins.operands)
    if show.operator == "'":
        out.append(_op("T*"))
    elif show.operator == '"':
        out += [_op("Tw", operands[0]), _op("Tc", operands[1]), _op("T*")]
    font_key = pikepdf.Name(state.font)
    position = 0.0  # Vorschub (Textraum) seit Beginn des Operators
    for (a, b), piece in zip(intervals, pieces):
        action = next((x for start, end, x in targets if start == a and end == b), None)
        advance = _advance(piece, codec, state)
        if action is None:
            if piece:
                out.append(_tj(piece))
        elif action.kind in ("text", "delete"):
            lead = []
            for item in piece:
                if isinstance(item, bytes):
                    break
                lead.append(item)
            items = lead + ([action.data] if action.kind == "text" and action.data else [])
            correction = (_advance(items, codec, state) - advance) * 1000.0 / (state.size * state.hscale)
            if abs(correction) > 1e-4:
                items.append(round(correction, 4))
            if items:
                out.append(_tj(items))
        elif action.kind == "move":
            linear = (show.ctm[0], show.ctm[1], show.ctm[2], show.ctm[3], 0.0, 0.0)
            ux, uy = _apply_linear(invert(linear), action.shift)
            start = mul((1.0, 0.0, 0.0, 1.0, position, 0.0), show.tm)
            out.append(_op("Tm", *[round(v, 5) for v in (start[0], start[1], start[2], start[3], start[4] + ux, start[5] + uy)]))
            out.append(_tj(piece))
            out += _restore_position(show, position + advance)
        elif action.kind == "size":
            size = round(action.size / _scale(show), 4)  # Seitenpunkte → Schriftgröße im Textraum (Tm/CTM skalieren)
            out.append(_op("Tf", font_key, size))
            resized = type(state)(**{**state.__dict__, "size": size})
            correction = (_advance(piece, codec, resized) - advance) * 1000.0 / (size * state.hscale)
            out.append(_tj(piece + ([round(correction, 4)] if abs(correction) > 1e-4 else [])))
            out.append(_op("Tf", font_key, state.size))
        elif action.kind == "spacing":
            spacing = round(action.spacing / (state.hscale * _scale(show)), 4)  # Seitenpunkte → Tc im Textraum
            out.append(_op("Tc", spacing))
            spaced = type(state)(**{**state.__dict__, "char_spacing": spacing})
            correction = (_advance(piece, codec, spaced) - advance) * 1000.0 / (state.size * state.hscale)
            out.append(_tj(piece + ([round(correction, 4)] if abs(correction) > 1e-4 else [])))
            out.append(_op("Tc", state.char_spacing))
        elif action.kind == "color":
            r, g, b = (round(value / 255.0, 4) for value in action.color)
            out.append(_op("rg", r, g, b))
            out.append(_tj(piece))
            out += _fill_state(content, show.index)
        position += advance
    return out


def _apply_linear(m, point: tuple[float, float]) -> tuple[float, float]:
    a, b, c, d, _e, _f = m
    x, y = point
    return (a * x + c * y, b * x + d * y)


def _restore_position(show: ShowOp, offset: float) -> list:
    """Nach einem verschobenen Teil: Zeilen- und Textmatrix wie im Original (für alles Folgende)."""
    after = mul((1.0, 0.0, 0.0, 1.0, offset, 0.0), show.tm)
    relative = mul(after, invert(show.tlm))
    a, b, c, d, e, f = relative
    if abs(a - 1) > 1e-6 or abs(b) > 1e-6 or abs(c) > 1e-6 or abs(d - 1) > 1e-6 or abs(f) > 1e-4:
        raise _NotNative("Die Position des folgenden Textes ließe sich nicht wiederherstellen.")
    out = [_op("Tm", *[round(v, 5) for v in show.tlm])]
    if abs(e) > 1e-6:
        out.append(_tj([round(-e * 1000.0 / (show.state.size * show.state.hscale), 4)]))
    return out


FILL_OPERATORS = {"g", "rg", "k", "sc", "scn"}


def _fill_state(content: PageContent, index: int) -> list:
    """Anweisungen, die die Füllfarbe vor ``index`` wiederherstellen (Farbraum und Farbe)."""
    stack: list[tuple] = []
    space = color = None
    for ins in content.instructions[:index]:
        if isinstance(ins, pikepdf.ContentStreamInlineImage):
            continue
        op = str(ins.operator)
        if op == "q":
            stack.append((space, color))
        elif op == "Q":
            if stack:
                space, color = stack.pop()
        elif op == "cs":
            space, color = ins, None
        elif op in FILL_OPERATORS:
            color = ins
            if op in ("g", "rg", "k"):
                space = None
    if color is None and space is None:
        return [_op("g", 0)]  # Ausgangszustand: Schwarz
    out = []
    if space is not None:
        out.append(pikepdf.ContentStreamInstruction(list(space.operands), Operator("cs")))
    if color is not None:
        out.append(pikepdf.ContentStreamInstruction(list(color.operands), Operator(str(color.operator))))
    return out


# --- Neu setzen, Überdecken -------------------------------------------------------------------------------
def _edit_native(document: EditorDocument, objects: PageObjects, segment: Segment, first: int, last: int, new_text: str) -> ObjectOutcome:
    run = objects.runs[objects.glyphs[first].run]
    obj = document.pdf.pages[segment.page].obj
    content = PageContent(document.pdf, obj, page_fonts(obj))
    show = content.shows[run.show]
    codec = content.codec(show.state.font)
    if codec is None or not codec.editable:
        raise _NotNative("Schrift nicht änderbar")
    missing = codec.can_encode(new_text)
    if missing is not None:
        raise _NotNative(f"Zeichen »{missing}« ist in der Originalschrift nicht kodiert")
    absent = textedit.missing_glyphs(document, segment.page, run, new_text)
    if absent:
        raise _NotNative(f"Der Originalschrift fehlen Zeichen: {absent}")
    data = codec.encode(new_text)
    width = codec.text_width(data, show.state.size, show.state.char_spacing, show.state.word_spacing, show.state.hscale) * _scale(show)
    shift = _reflow(objects, segment, first, last, width - _width(content, objects, first, last))
    targets = [(first, last, _Action("text", data=data))]
    if shift is not None:
        targets.append((last + 1, segment.last, _Action("move", shift=shift)))
    _apply(document, objects, targets)
    return ObjectOutcome(NATIVE, _area(objects, segment, first, last, width, shift))


def _edit_rebuild(document: EditorDocument, objects: PageObjects, segment: Segment, first: int, last: int, new_text: str) -> ObjectOutcome:
    """Originalzeichen entfernen (nativ, Platz bleibt), neuen Text an derselben Grundlinie setzen."""
    font, size, color, origin, angle = _font_for(document, objects, segment, first, new_text)
    width = font.measure(new_text, size)
    obj = document.pdf.pages[segment.page].obj
    content = PageContent(document.pdf, obj, page_fonts(obj))
    shift = _reflow(objects, segment, first, last, width - _width(content, objects, first, last))
    targets = [(first, last, _Action("delete"))]
    if shift is not None:
        targets.append((last + 1, segment.last, _Action("move", shift=shift)))
    _apply(document, objects, targets)
    _append_text(document, segment.page, font, size, color, origin, angle, new_text)
    return ObjectOutcome(RECONSTRUCTED, _area(objects, segment, first, last, width, shift), list(font.notes))


def _width(content: PageContent, objects: PageObjects, first: int, last: int, *, size: float | None = None, spacing: float | None = None) -> float:
    """Vorschub der Zeichen ``first`` … ``last`` in Seitenpunkten (Schriftbreiten, ohne TJ-Abstände) –
    mit ``size``/``spacing`` (Seitenpunkte): so breit wären sie in dieser Größe bzw. mit diesem Abstand."""
    total = 0.0
    for run in {objects.glyphs[i].run for i in range(first, last + 1)}:
        info = objects.runs[run]
        show = content.shows[info.show]
        codec = content.codec(show.state.font)
        codes = codec.codes(show.raw)
        data = b"".join(codes[objects.glyphs[i].code] for i in info.glyphs if first <= i <= last)
        state, scale = show.state, _scale(show)
        font_size = state.size if size is None else size / scale
        char_spacing = state.char_spacing if spacing is None else spacing / (state.hscale * scale)
        total += codec.text_width(data, font_size, char_spacing, state.word_spacing, state.hscale) * scale
    return total


def _reflow(objects: PageObjects, segment: Segment, first: int, last: int, delta: float) -> tuple[float, float] | None:
    """Wort innerhalb eines Segments geändert: der Rest des Segments rückt um ``delta`` Punkte nach
    (wie beim Schreiben); alles außerhalb des Segments bleibt, wo es ist."""
    if last >= segment.last or abs(delta) < 0.01:
        return None
    u = _direction(segment.angle)
    return (u[0] * delta, u[1] * delta)


def _area(objects: PageObjects, segment: Segment, first: int, last: int, width: float, shift: tuple[float, float] | None) -> Rect:
    box = _extend(objects.bounds_of(first, last), segment.angle, width)
    if shift is not None:
        rest = objects.bounds_of(last + 1, segment.last)
        box = union(box, union(rest, (rest[0] + shift[0], rest[1] + shift[1], rest[2] + shift[0], rest[3] + shift[1])))
    return box


def _overlay(document: EditorDocument, objects: PageObjects, segment: Segment, first: int, last: int, new_text: str) -> ObjectOutcome:
    """Letzter Ausweg: Bereich mit der gemessenen Hintergrundfarbe überdecken, neuen Text darüber."""
    area = inflate(objects.bounds_of(first, last), 1.0)
    fill = textedit._background(document, segment.page, area)  # noqa: SLF001
    obj = document.pdf.pages[segment.page].obj
    append_content(document.pdf, obj, f"{textedit._rgb(fill)} rg {fmt(area[0])} {fmt(area[1])} {fmt(area[2] - area[0])} {fmt(area[3] - area[1])} re f".encode("latin-1"))  # noqa: SLF001
    font, size, color, origin, angle = _font_for(document, objects, segment, first, new_text)
    _append_text(document, segment.page, font, size, color, origin, angle, new_text)
    return ObjectOutcome(OVERLAY, _extend(area, angle, font.measure(new_text, size)), list(font.notes))


def _cover(document: EditorDocument, objects: PageObjects, targets) -> ObjectOutcome:
    obj = document.pdf.pages[targets[0][0].page].obj
    parts = []
    area = None
    for segment, first, last in targets:
        box = inflate(objects.bounds_of(first, last), 1.0)
        fill = textedit._background(document, segment.page, box)  # noqa: SLF001
        parts.append(f"{textedit._rgb(fill)} rg {fmt(box[0])} {fmt(box[1])} {fmt(box[2] - box[0])} {fmt(box[3] - box[1])} re f")  # noqa: SLF001
        area = union(area, box)
    append_content(document.pdf, obj, "\n".join(parts).encode("latin-1"))
    return ObjectOutcome(OVERLAY, area)


def _font_for(document: EditorDocument, objects: PageObjects, segment: Segment, first: int, text: str):
    glyph = objects.glyphs[first]
    style = textedit.style_of(segment.font)
    try:
        font = textedit.new_font(document, segment.page, style, text)
    except textedit._Rejected as rejected:  # noqa: SLF001
        raise _NotNative(rejected.reason) from rejected
    return font, segment.size, segment.color, glyph.origin, segment.angle


def _append_text(document: EditorDocument, page: int, font, size: float, color, origin, angle: float, text: str) -> None:
    u = _direction(angle)
    data = f"BT {font.key} {fmt(size)} Tf {textedit._rgb(color)} rg {fmt(u[0])} {fmt(u[1])} {fmt(-u[1])} {fmt(u[0])} {fmt(origin[0])} {fmt(origin[1])} Tm <{font.encode(text).hex()}> Tj ET"  # noqa: SLF001
    append_content(document.pdf, document.pdf.pages[page].obj, data.encode("latin-1"))


def _scale(show: ShowOp) -> float:
    m = mul(show.tm, show.ctm)
    return max(1e-6, math.hypot(m[0], m[1]))


def _extend(box: Rect, angle: float, width: float) -> Rect:
    """Bereich ``box`` in Schreibrichtung auf mindestens ``width`` verlängern (für die Prüfung)."""
    u = _direction(angle)
    x0, y0, x1, y1 = box
    corners = [(x0, y0), (x1, y0), (x0, y1), (x1, y1)]
    extended = [(x + u[0] * width, y + u[1] * width) for x, y in corners]
    out = box
    for x, y in extended:
        out = union(out, (x, y, x, y))
    return out


# --- Prüfen ----------------------------------------------------------------------------------------------------
def _snapshot(document: EditorDocument, page: int):
    return render.render_page(document, page, textedit._check_width(document, page)), textlayer.text(document, page)  # noqa: SLF001


def _verify(document: EditorDocument, page: int, before, before_text: str, old_area: Rect, outcome: ObjectOutcome, new_text: str | None, old_text: str | list[str] | None, *, wide: bool = False) -> None:
    """Darstellung nur im erwarteten Bereich verändert, neuer Text lesbar, alter entfernt – sonst
    ``_NotNative`` (die Änderung wird zurückgenommen). ``old_text`` als Liste: mehrere entfernte Stücke
    (Löschen mehrerer Objekte) – jedes muss so oft weniger vorkommen, wie es entfernt wurde."""
    from PIL import ImageChops, ImageDraw

    document.touch()
    after = render.render_page(document, page, before.width)
    a = render.to_pil(before).convert("L")
    b = render.to_pil(after).convert("L")
    if a.size != b.size:
        raise _NotNative("Seitengröße hat sich geändert")
    diff = ImageChops.difference(a, b).point(lambda value: 255 if value > textedit.DIFF_THRESHOLD else 0)
    geo = document.geometry(page)
    scale = a.width / geo.width
    allowed = inflate(union(old_area, outcome.bounds), 6.0 if wide else 2.5)
    u0, v0, u1, v1 = geo.rect_to_view(allowed)
    ImageDraw.Draw(diff).rectangle([int(u0 * scale) - 2, int(v0 * scale) - 2, int(u1 * scale) + 2, int(v1 * scale) + 2], fill=0)
    if diff.getbbox() is not None:
        raise _NotNative("Die Änderung hätte die Seite außerhalb der Auswahl verändert")
    found = textedit._squash(textlayer.text(document, page))  # noqa: SLF001
    if new_text is None:  # Verschieben, Formatieren: dieselben Zeichen (die Lesereihenfolge darf sich ändern)
        if Counter(found) != Counter(textedit._squash(before_text)):  # noqa: SLF001
            raise _NotNative("Der Text der Seite hätte sich verändert")
        return
    if outcome.mode != OVERLAY:
        wanted = textedit._squash(new_text)  # noqa: SLF001
        if wanted and wanted not in found:
            raise _NotNative("Der neue Text ist im PDF nicht lesbar")
        squashed_before = textedit._squash(before_text)  # noqa: SLF001
        pieces = Counter(textedit._squash(piece) for piece in (old_text if isinstance(old_text, list) else [old_text or ""]))  # noqa: SLF001
        for old, removed in pieces.items():
            if old and old not in wanted and found.count(old) > squashed_before.count(old) - removed:
                raise _NotNative("Der bisherige Text ist noch vorhanden")


# --- Duplizieren, Ausrichten -------------------------------------------------------------------------------
def duplicate(document: EditorDocument, history: History, objects: PageObjects, ident: str, offset: tuple[float, float] = (12.0, -12.0)) -> ObjectOutcome:
    """Segment bzw. Wort als neues Textobjekt versetzt kopieren – in derselben Schrift, Größe und Farbe
    (nativ: dieselben Codes und derselbe Textzustand); sonst neu gesetzt."""
    _check_revision(document, objects)
    segment, first, last = objects.target(ident)
    page = segment.page
    before, before_text = _snapshot(document, page)
    box = objects.bounds_of(first, last)
    moved = (box[0] + offset[0], box[1] + offset[1], box[2] + offset[0], box[3] + offset[1])
    text = objects.text_of(first, last)
    try:
        with commands.record(document, history, "Duplizieren", pages=(page,)) as rec:
            obj = rec.page(page)
            if segment.native:
                content = PageContent(document.pdf, obj, page_fonts(obj))
                append_content(document.pdf, obj, _copy(content, objects, first, last, offset))
                outcome = ObjectOutcome(NATIVE, moved)
            else:
                font, size, color, origin, angle = _font_for(document, objects, segment, first, text)
                _append_text(document, page, font, size, color, (origin[0] + offset[0], origin[1] + offset[1]), angle, text)
                outcome = ObjectOutcome(RECONSTRUCTED, moved, list(font.notes))
            rec.info["mode"] = outcome.mode
            _verify_added(document, page, before, before_text, moved, text)
            rec.fresh = True
    except _NotNative as reason:
        raise UnsupportedEdit("Das lässt sich hier nicht sicher duplizieren. " + str(reason)) from reason
    return outcome


def _copy(content: PageContent, objects: PageObjects, first: int, last: int, offset: tuple[float, float]) -> bytes:
    """Anweisungen, die die Zeichen ``first`` … ``last`` versetzt noch einmal zeichnen."""
    out: list = []
    runs: list[int] = []
    for index in range(first, last + 1):
        if objects.glyphs[index].run not in runs:
            runs.append(objects.glyphs[index].run)
    for run_index in runs:
        run = objects.runs[run_index]
        show = content.shows[run.show]
        codec = content.codec(show.state.font)
        step = 2 if codec.two_byte else 1
        codes = [objects.glyphs[i].code for i in run.glyphs if first <= i <= last]
        a, b = min(codes), max(codes) + 1
        total = len(show.raw) // step
        intervals, pieces = _cut(_elements(content.instructions[show.index], show.operator), step, sorted({0, a, b, total}))
        position = 0.0
        piece = []
        for (start, end), items in zip(intervals, pieces):
            if (start, end) == (a, b):
                piece = items
                break
            position += _advance(items, codec, show.state)
        state = show.state
        linear = (show.ctm[0], show.ctm[1], show.ctm[2], show.ctm[3], 0.0, 0.0)
        ux, uy = _apply_linear(invert(linear), offset)
        tm = mul((1.0, 0.0, 0.0, 1.0, position, 0.0), show.tm)
        out.append(_op("q"))
        out.append(_op("cm", *[round(v, 5) for v in show.ctm]))
        out += _fill_state(content, show.index)
        out.append(_op("BT"))
        out += [_op("Tf", pikepdf.Name(state.font), state.size), _op("Tc", state.char_spacing), _op("Tw", state.word_spacing), _op("Tz", round(state.hscale * 100, 4)), _op("Ts", state.rise), _op("Tr", state.render)]
        out.append(_op("Tm", *[round(v, 5) for v in (tm[0], tm[1], tm[2], tm[3], tm[4] + ux, tm[5] + uy)]))
        out.append(_tj(piece))
        out += [_op("ET"), _op("Q")]
    return pikepdf.unparse_content_stream(out)


def _verify_added(document: EditorDocument, page: int, before, before_text: str, area: Rect, text: str) -> None:
    from PIL import ImageChops, ImageDraw

    document.touch()
    after = render.render_page(document, page, before.width)
    a = render.to_pil(before).convert("L")
    b = render.to_pil(after).convert("L")
    diff = ImageChops.difference(a, b).point(lambda value: 255 if value > textedit.DIFF_THRESHOLD else 0)
    geo = document.geometry(page)
    scale = a.width / geo.width
    u0, v0, u1, v1 = geo.rect_to_view(inflate(area, 2.5))
    ImageDraw.Draw(diff).rectangle([int(u0 * scale) - 2, int(v0 * scale) - 2, int(u1 * scale) + 2, int(v1 * scale) + 2], fill=0)
    if diff.getbbox() is not None:
        raise _NotNative("Die Kopie hätte die Seite außerhalb ihres Bereichs verändert")
    found = textedit._squash(textlayer.text(document, page))  # noqa: SLF001
    if found.count(textedit._squash(text)) <= textedit._squash(before_text).count(textedit._squash(text)):  # noqa: SLF001
        raise _NotNative("Die Kopie ist im PDF nicht lesbar")


def align(objects: PageObjects, idents: list[str], how: str) -> dict[str, tuple[float, float]]:
    """Verschiebungen (Seitenpunkte) zum Ausrichten mehrerer Objekte: »left«, »right«, »top«,
    »bottom« (Seitenkoordinaten – auf gedrehten Seiten rechnet die Oberfläche um)."""
    boxes = {ident: objects.bounds_of(*objects.target(ident)[1:]) for ident in idents}
    if len(boxes) < 2:
        return {}
    if how == "left":
        edge = min(box[0] for box in boxes.values())
        return {ident: (edge - box[0], 0.0) for ident, box in boxes.items()}
    if how == "right":
        edge = max(box[2] for box in boxes.values())
        return {ident: (edge - box[2], 0.0) for ident, box in boxes.items()}
    if how == "top":
        edge = max(box[3] for box in boxes.values())
        return {ident: (0.0, edge - box[3]) for ident, box in boxes.items()}
    if how == "bottom":
        edge = min(box[1] for box in boxes.values())
        return {ident: (0.0, edge - box[1]) for ident, box in boxes.items()}
    raise UnsupportedEdit("Unbekannte Ausrichtung.")


def move_each(document: EditorDocument, history: History, objects: PageObjects, shifts: dict[str, tuple[float, float]], *, title: str = "Ausrichten") -> ObjectOutcome:
    """Mehrere Objekte unterschiedlich weit verschieben (ein Schritt für Rückgängig)."""
    _check_revision(document, objects)
    moving = {ident: shift for ident, shift in shifts.items() if abs(shift[0]) > 0.01 or abs(shift[1]) > 0.01}
    targets = [(objects.target(ident), shift) for ident, shift in moving.items()]
    if not targets:
        return ObjectOutcome(NATIVE, (0.0, 0.0, 0.0, 0.0))
    for (segment, _first, _last), _shift in targets:
        if not segment.native:
            raise UnsupportedEdit("Dieser Text lässt sich nicht verschieben: " + segment.native_reason)
    page = targets[0][0][0].page
    before, before_text = _snapshot(document, page)
    area = None
    for (_segment, first, last), shift in targets:
        box = objects.bounds_of(first, last)
        area = union(area, union(box, (box[0] + shift[0], box[1] + shift[1], box[2] + shift[0], box[3] + shift[1])))
    try:
        with commands.record(document, history, title, pages=(page,)) as rec:
            rec.page(page)
            _apply(document, objects, [(first, last, _Action("move", shift=shift)) for (_segment, first, last), shift in targets])
            outcome = ObjectOutcome(NATIVE, area)
            rec.info["mode"] = NATIVE
            _verify(document, page, before, before_text, area, outcome, None, None)
            rec.fresh = True
    except _NotNative as reason:
        raise UnsupportedEdit("Das lässt sich hier nicht sicher verschieben. " + str(reason)) from reason
    return outcome


# --- Für die Oberfläche --------------------------------------------------------------------------------------
def describe(document: EditorDocument, objects: PageObjects) -> dict:
    """Objekte einer Seite in Anzeige-Punkten (Ursprung oben links, Drehung der Seite berücksichtigt) –
    die Oberfläche prüft Treffer selbst, ohne bei jeder Mausbewegung nachzufragen."""
    from . import images as image_module

    geo = document.geometry(objects.page)
    obj = document.pdf.pages[objects.page].obj
    content = None
    if objects.mapped:
        try:
            content = PageContent(document.pdf, obj, page_fonts(obj))
        except (pikepdf.PdfError, ValueError, TypeError):
            content = None
    segments = []
    for segment in objects.segments:
        run = objects.runs[objects.glyphs[segment.first].run]
        show = content.shows[run.show] if content is not None and run.show >= 0 else None
        spacing = show.state.char_spacing * show.state.hscale * _scale(show) if show is not None else 0.0  # Seitenpunkte
        origin = objects.glyphs[segment.first].origin
        u, v = geo.to_view(*origin)
        segments.append({
            "id": segment.id,
            "kind": "text",
            "text": " ".join(word.text for word in segment.words),
            "view": [round(value, 2) for value in geo.rect_to_view(segment.bounds)],
            "words": [{"id": word.id, "text": word.text, "view": [round(value, 2) for value in geo.rect_to_view(word.bounds)]} for word in segment.words],
            "font": segment.font.split("+", 1)[-1],
            "size": segment.size,
            "color": "#%02X%02X%02X" % tuple(segment.color),
            "angle": round((segment.angle + geo.rotation) % 360, 1),
            "spacing": round(spacing, 3),
            "x": round(u, 2),
            "y": round(v, 2),
            "native": segment.native,
            "reason": segment.native_reason,
            "line": segment.line,
        })
    pictures = []
    for item in image_module.list_images(document, objects.page):
        pictures.append({"id": f"{objects.page}-i{item.index}", "kind": "image", "index": item.index, "view": [round(value, 2) for value in geo.rect_to_view(item.bounds)], "pixels": list(item.pixels), "editable": item.editable, "reason": item.reason})
    message = NO_TEXT if not segments else ""
    return {"page": objects.page, "revision": objects.revision, "segments": segments, "images": pictures, "message": message}
