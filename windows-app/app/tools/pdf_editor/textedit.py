"""Text bearbeiten: Blöcke erkennen, ändern, löschen und neuen Text hinzufügen.

Drei Wege – die Engine wählt den sichersten, der gelingt, und meldet ihn ehrlich:

* **Nativ** (``NATIVE``): Die Textoperatoren des Blocks erhalten den neuen Text in der
  Originalschrift (gleiche Schrift, Größe, Farbe, Position). Voraussetzung: Die Schrift kann jedes
  neue Zeichen kodieren **und** enthält dessen Glyphe (PDFium-Prüfung gegen die ».notdef«-Glyphe).
* **Rekonstruiert** (``RECONSTRUCTED``): Der Originaltext wird aus dem Inhaltsstrom entfernt und
  neu gesetzt – in der Originalschrift oder, wenn ihr Zeichen fehlen, in einer passenden Ersatz-
  schrift (Systemschrift als Teilmenge eingebettet, sofern ihre Lizenz das erlaubt, sonst
  Standardschrift). Auch bei geänderter Formatierung (Schrift, Größe, Farbe, Ausrichtung).
* **Überlagerung** (``OVERLAY``): Lässt sich der Originaltext nicht sicher entfernen (z. B. in einem
  Formular-XObject oder als unsichtbarer Text einer Texterkennung), wird er abgedeckt und der neue
  Text darübergesetzt. Der ursprüngliche Text bleibt **in der Datei enthalten** – das ist
  ausdrücklich keine Schwärzung.

Jede Änderung wird vor dem Übernehmen geprüft: Die Darstellung der Seite darf sich nur im
bearbeiteten Bereich ändern, der neue Text muss lesbar (extrahierbar) im PDF stehen und – außer bei
der Überlagerung – der bisherige Text entfernt sein. Schlägt die Prüfung fehl, wird die Änderung
verworfen und der nächste Weg versucht.

Schriften werden nie aus PDFs herausgelöst oder weitergegeben; eingebettet werden nur Teilmengen
von Systemschriften, deren Lizenz (OS/2 ``fsType``) das Einbetten erlaubt.
"""

from __future__ import annotations

import ctypes
import math
import re
import statistics
from dataclasses import dataclass, field
from typing import Callable

import pikepdf

from pdfium_lock import PDFIUM_LOCK

from . import commands, render, textlayer
from .commands import History
from .content import PageContent, ShowOp, append_content, fmt, mul, page_fonts, prune_fonts
from .document import EditorDocument
from .errors import Overflow, UnsupportedEdit  # noqa: F401 - Overflow: auch textedit.Overflow
from .fonts import CannotEncode, Style, embed_truetype, find_system_font, standard_font, standard_substitute, standard_width, style_of
from .geometry import Rect, inflate, normalize, union

NATIVE = "native"
RECONSTRUCTED = "reconstructed"
OVERLAY = "overlay"
MODE_LABELS = {
    NATIVE: "Direkt im PDF geändert (Originalschrift)",
    RECONSTRUCTED: "Neu gesetzt (Originaltext entfernt)",
    OVERLAY: "Kompatibilitätsmodus: Originaltext überdeckt – er bleibt in der Datei enthalten (keine Schwärzung)",
}
CHECK_SCALE = 1.5  # Pixel je Punkt für die Prüfung der Darstellung
DIFF_THRESHOLD = 40  # Grauwert-Unterschied, ab dem ein Pixel als geändert gilt
MIN_FONT_SIZE = 4.0
PAGE_MARGIN = 6.0  # Mindestabstand zum Seitenrand, wenn eine Zeile länger wird (Punkte)
FONT_PREFIX = "/PTF"  # Ressourcennamen der von PDF Tool hinzugefügten Schriften
INVISIBLE = 3  # Textdarstellungsmodus »unsichtbar« (z. B. Texterkennung über einem Scan)


@dataclass
class Run:
    """Text eines PDFium-Textobjekts (= eines Textoperators)."""

    obj: int  # Index unter den Textobjekten der obersten Ebene (−1: in einem Formular-XObject)
    text: str
    bounds: Rect
    baseline: tuple[float, float]  # Ursprung des ersten Zeichens (Seitenkoordinaten)
    size: float  # wirksame Schriftgröße in Punkten (Tf × Textmatrix × CTM)
    font: str  # Grundname der Schrift
    color: tuple[int, int, int]
    angle: float  # Richtung der Grundlinie in Grad (gegen den Uhrzeigersinn)
    render_mode: int = 0
    show: int = -1  # Index in ``PageContent.shows`` (nur bei obersten Objekten)


@dataclass
class Line:
    runs: list[Run]

    @property
    def text(self) -> str:
        return "".join(run.text for run in self.runs).rstrip("\r\n")

    @property
    def bounds(self) -> Rect:
        box = None
        for run in self.runs:
            box = union(box, run.bounds)
        return box or (0.0, 0.0, 0.0, 0.0)

    @property
    def baseline(self) -> tuple[float, float]:
        return self.runs[0].baseline


@dataclass
class Block:
    id: str
    page: int
    lines: list[Line]
    revision: int = 0  # Stand des Dokuments bei der Analyse
    native_reason: str = ""  # leer = Textoperatoren eindeutig zugeordnet

    @property
    def text(self) -> str:
        return "\n".join(line.text for line in self.lines)

    @property
    def bounds(self) -> Rect:
        box = None
        for line in self.lines:
            box = union(box, line.bounds)
        return box or (0.0, 0.0, 0.0, 0.0)

    @property
    def runs(self) -> list[Run]:
        return [run for line in self.lines for run in line.runs]

    @property
    def first(self) -> Run:
        return self.lines[0].runs[0]

    @property
    def font(self) -> str:
        return self.first.font

    @property
    def size(self) -> float:
        return round(statistics.median(run.size for run in self.runs), 2)

    @property
    def color(self) -> tuple[int, int, int]:
        return self.first.color

    @property
    def angle(self) -> float:
        return self.first.angle

    @property
    def uniform(self) -> bool:
        first = self.first
        return all(run.font == first.font and abs(run.size - first.size) <= max(0.2, first.size * 0.02) and run.color == first.color for run in self.runs)

    @property
    def nested(self) -> bool:
        return any(run.obj < 0 for run in self.runs)

    @property
    def invisible(self) -> bool:
        return any(run.render_mode == INVISIBLE for run in self.runs)

    @property
    def align(self) -> str:
        """Ausrichtung mehrzeiliger Blöcke (links, rechts, zentriert); einzelne Zeilen: links."""
        if len(self.lines) < 2:
            return "left"
        boxes = [line.bounds for line in self.lines]
        tolerance = max(1.0, self.size * 0.3)
        if max(b[0] for b in boxes) - min(b[0] for b in boxes) <= tolerance:
            return "left"
        if max(b[2] for b in boxes) - min(b[2] for b in boxes) <= tolerance:
            return "right"
        centers = [(b[0] + b[2]) / 2 for b in boxes]
        if max(centers) - min(centers) <= tolerance:
            return "center"
        return "left"

    @property
    def editable_natively(self) -> bool:
        return not self.native_reason and not self.invisible

    def describe(self) -> dict:
        style = style_of(self.font)
        reason = self.native_reason or ("Unsichtbarer Text (z. B. Texterkennung eines Scans)" if self.invisible else "")
        return {"id": self.id, "text": self.text, "bounds": self.bounds, "font": self.font, "size": self.size, "color": self.color, "bold": style.bold, "italic": style.italic, "native": not reason, "reason": reason, "lines": len(self.lines), "angle": self.angle, "align": self.align}


@dataclass
class EditOutcome:
    mode: str
    bounds: Rect  # Bereich des neuen Textes (Seitenkoordinaten)
    font: str  # verwendete Schrift
    notes: list[str] = field(default_factory=list)
    lines: int = 1

    @property
    def label(self) -> str:
        return MODE_LABELS[self.mode]


@dataclass
class TextStyle:
    """Formatierung für neuen bzw. umformatierten Text (``None`` = wie bisher)."""

    family: str | None = None  # »Helvetica«, »Times«, »Courier« oder Systemschrift (z. B. »Arial«)
    size: float | None = None
    color: tuple[int, int, int] | None = None
    bold: bool | None = None
    italic: bool | None = None
    align: str | None = None  # left, center, right
    underline: bool | None = None  # Linie unter dem Text (als Vektorlinie in der Textfarbe)
    strike: bool | None = None  # Linie durch den Text


# --- Analyse -------------------------------------------------------------------------------------------------
def analyze(document: EditorDocument, page: int) -> list[Block]:
    """Textblöcke einer Seite (Lesereihenfolge von PDFium), mit Zuordnung zu den Textoperatoren."""
    runs = _runs(document, page)
    content = None
    mapped = False
    reason = ""
    try:
        obj = document.pdf.pages[page].obj
        content = PageContent(document.pdf, obj, page_fonts(obj))
        mapped, reason = _map(document, page, content, runs)
    except (pikepdf.PdfError, ValueError, TypeError):
        reason = "Der Inhalt der Seite lässt sich nicht sicher lesen."
    blocks = _blocks(page, _lines(runs))
    for block in blocks:
        block.revision = document.revision
        if document.read_only:
            block.native_reason = document.read_only_reason
        elif not mapped:
            block.native_reason = reason or "Die Textstruktur der Seite lässt keine direkte Änderung zu."
        elif block.nested:
            block.native_reason = "Der Text liegt in einem eingebetteten Formular-Objekt."
        elif any(run.show < 0 for run in block.runs):
            block.native_reason = "Der Text ist keinem Textoperator eindeutig zugeordnet."
        else:
            codec = content.codec(content.shows[block.first.show].state.font) if content else None
            if codec is None or not codec.editable:
                block.native_reason = "Die Schrift dieses Textes lässt keine direkte Änderung zu."
    return blocks


def _handle(value) -> int:
    return ctypes.cast(value, ctypes.c_void_p).value or 0


def _runs(document: EditorDocument, page: int) -> list[Run]:
    import pypdfium2.raw as r

    runs: list[Run] = []
    with PDFIUM_LOCK:
        textpage = document.textpage(page)
        pdf_page = document.page_object(page)
        top = {}
        text_index = 0
        for index in range(r.FPDFPage_CountObjects(pdf_page.raw)):
            obj = r.FPDFPage_GetObject(pdf_page.raw, index)
            if r.FPDFPageObj_GetType(obj) == r.FPDF_PAGEOBJ_TEXT:
                top[_handle(obj)] = text_index
                text_index += 1
        total = textpage.count_chars()
        current = None
        matrix = r.FS_MATRIX()
        for i in range(total):
            if r.FPDFText_IsGenerated(textpage.raw, i) == 1:
                continue
            obj = r.FPDFText_GetTextObject(textpage.raw, i)
            key = _handle(obj)
            char = chr(r.FPDFText_GetUnicode(textpage.raw, i) or 0xFFFD)
            left, bottom, right, top_ = textpage.get_charbox(i, loose=True)
            box = normalize((left, bottom, right, top_))
            if current is None or current[0] != key:
                x, y = ctypes.c_double(), ctypes.c_double()
                r.FPDFText_GetCharOrigin(textpage.raw, i, x, y)
                r.FPDFText_GetMatrix(textpage.raw, i, matrix)  # Textmatrix × CTM (ohne Schriftgröße)
                size = float(r.FPDFText_GetFontSize(textpage.raw, i)) * math.hypot(matrix.c, matrix.d)
                buffer = ctypes.create_string_buffer(256)
                flags = ctypes.c_int()
                r.FPDFText_GetFontInfo(textpage.raw, i, buffer, 256, flags)
                red, green, blue, alpha = (ctypes.c_uint() for _ in range(4))
                r.FPDFText_GetFillColor(textpage.raw, i, red, green, blue, alpha)
                angle = round(math.degrees(math.atan2(matrix.b, matrix.a)), 1) % 360
                mode = int(r.FPDFTextObj_GetTextRenderMode(obj)) if obj else 0
                run = Run(top.get(key, -1), "", box, (x.value, y.value), round(size, 2), buffer.value.decode("latin-1", "replace"), (red.value, green.value, blue.value), angle, mode)
                runs.append(run)
                current = (key, run)
            run = current[1]
            run.text += char
            if char.strip():
                run.bounds = union(run.bounds, box) if run.text.strip() != char else box
    return [run for run in runs if run.text.strip()]


def _map(document: EditorDocument, page: int, content: PageContent, runs: list[Run]) -> tuple[bool, str]:
    """Textoperatoren mit Text ↔ PDFium-Textobjekte (gleiche Reihenfolge, gleicher Text)."""
    import pypdfium2.raw as r

    failed = (False, "Die Textstruktur der Seite lässt keine direkte Änderung zu.")
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
    shows = [i for i, show in enumerate(content.shows) if show.raw]  # leere Operatoren: kein Objekt
    if len(texts) != len(shows):
        return failed
    for show_index, text in zip(shows, texts):
        ours = re.sub(r"\s+", "", content.text_of(content.shows[show_index]))
        theirs = re.sub(r"\s+", "", text)
        if ours != theirs and theirs:
            return failed
    used: dict[int, int] = {}
    for run in runs:
        if run.obj >= 0:
            used[run.obj] = used.get(run.obj, 0) + 1
    for run in runs:
        if run.obj >= 0 and used[run.obj] == 1:
            run.show = shows[run.obj]
    return True, ""


def _lines(runs: list[Run]) -> list[Line]:
    lines: list[Line] = []
    for run in runs:
        if lines:
            last = lines[-1].runs[-1]
            if abs(run.angle - last.angle) < 1 and abs(run.angle) < 1:
                same_baseline = abs(run.baseline[1] - last.baseline[1]) <= max(1.0, 0.35 * max(run.size, last.size))
                gap = run.bounds[0] - last.bounds[2]
                if same_baseline and -0.5 * last.size <= gap <= 3.0 * max(run.size, last.size):
                    lines[-1].runs.append(run)
                    continue
        lines.append(Line([run]))
    return lines


def _blocks(page: int, lines: list[Line]) -> list[Block]:
    blocks: list[Block] = []
    for line in lines:
        if blocks and _continues(blocks[-1], line):
            blocks[-1].lines.append(line)
            continue
        blocks.append(Block(f"{page}-{len(blocks)}", page, [line]))
    return blocks


def _continues(block: Block, line: Line) -> bool:
    previous = block.lines[-1]
    a, b = previous.runs[0], line.runs[0]
    if a.obj < 0 or b.obj < 0 or abs(a.angle) > 0.5 or abs(b.angle) > 0.5:
        return False
    if a.font != b.font or abs(a.size - b.size) > max(0.3, a.size * 0.05) or a.color != b.color or a.render_mode != b.render_mode:
        return False
    step = previous.baseline[1] - line.baseline[1]
    if not 0.9 * a.size <= step <= 1.7 * a.size:  # üblicher Zeilenabstand 100–150 %
        return False
    if len(block.lines) >= 2:
        before = block.lines[-2].baseline[1] - previous.baseline[1]
        if abs(before - step) > 0.25 * a.size:
            return False
    pb, lb = previous.bounds, line.bounds
    left = abs(pb[0] - lb[0]) <= 1.5 * a.size
    right = abs(pb[2] - lb[2]) <= 1.0 * a.size
    center = abs((pb[0] + pb[2]) / 2 - (lb[0] + lb[2]) / 2) <= 1.0 * a.size
    return left or right or center


def find_block(blocks: list[Block], block_id: str) -> Block:
    for block in blocks:
        if block.id == block_id:
            return block
    raise UnsupportedEdit("Der Textblock ist nicht mehr vorhanden.")


def block_at(blocks: list[Block], x: float, y: float, tolerance: float = 2.0) -> Block | None:
    """Block an einer Stelle – bei Überschneidung der zuletzt gezeichnete (oben liegende)."""
    for block in reversed(blocks):
        b = inflate(block.bounds, tolerance)
        if b[0] <= x <= b[2] and b[1] <= y <= b[3]:
            return block
    return None


# --- Glyphenprüfung (PDFium) ------------------------------------------------------------------------------
NOTDEF_PROBES = ("\U0010fffd", "￿", "ༀ")  # Zeichen, die keine Schrift sinnvoll enthält


def _glyph_signature(font, char: str, size: float = 10.0):
    import pypdfium2.raw as r

    path = r.FPDFFont_GetGlyphPath(font, ord(char), size)
    if not path:
        return None
    count = r.FPDFGlyphPath_CountGlyphSegments(path)
    points = []
    for i in range(min(count, 400)):
        segment = r.FPDFGlyphPath_GetGlyphPathSegment(path, i)
        x, y = ctypes.c_float(), ctypes.c_float()
        r.FPDFPathSegment_GetPoint(segment, x, y)
        points.append((round(x.value, 2), round(y.value, 2), r.FPDFPathSegment_GetType(segment)))
    return (count, tuple(points))


def missing_glyphs(document: EditorDocument, page: int, run: Run, text: str) -> str:
    """Zeichen von ``text``, für die die Schrift des Textobjekts keine Glyphe hat."""
    import pypdfium2.raw as r

    if run.obj < 0:
        return "".join(sorted(set(text)))
    missing = []
    with PDFIUM_LOCK:
        pdf_page = document.page_object(page)
        objects = [r.FPDFPage_GetObject(pdf_page.raw, i) for i in range(r.FPDFPage_CountObjects(pdf_page.raw))]
        objects = [obj for obj in objects if r.FPDFPageObj_GetType(obj) == r.FPDF_PAGEOBJ_TEXT]
        font = r.FPDFTextObj_GetFont(objects[run.obj])
        notdef = {sig for sig in (_glyph_signature(font, probe) for probe in NOTDEF_PROBES) if sig is not None}
        for char in sorted(set(text)):
            if char.isspace():
                continue
            signature = _glyph_signature(font, char)
            if signature is None or signature in notdef or signature[0] == 0:
                missing.append(char)
    return "".join(missing)


# --- Bearbeiten ------------------------------------------------------------------------------------------------
@dataclass
class _Font:
    """Schrift für neu gesetzten Text samt Maß und Kodierung (Größe und Abstände eingerechnet)."""

    key: str  # Ressourcenname auf der Seite
    label: str
    encode: Callable[[str], bytes]
    measure: Callable[[str, float], float]  # (Text, Größe) → Breite in Punkten
    notes: list[str] = field(default_factory=list)


@dataclass
class _Spacing:
    """Zeichen- und Wortabstand sowie horizontale Skalierung – umgerechnet auf eine Textmatrix
    ohne Skalierung (so werden sie im neu gesetzten Text geschrieben)."""

    char: float = 0.0
    word: float = 0.0
    hscale: float = 1.0

    def header(self) -> str:
        parts = []
        if abs(self.char) > 1e-4:
            parts.append(f"{fmt(self.char)} Tc")
        if abs(self.word) > 1e-4:
            parts.append(f"{fmt(self.word)} Tw")
        if abs(self.hscale - 1.0) > 0.005:
            parts.append(f"{fmt(self.hscale * 100)} Tz")
        return " ".join(parts)


def edit_block(document: EditorDocument, history: History, block: Block, new_text: str, *, style: TextStyle | None = None, overflow: str = "ask", forced_mode: str | None = None) -> EditOutcome:
    """Textblock ändern (``new_text`` leer = löschen). ``overflow``: »ask« (``Overflow`` werfen),
    »grow« (zusätzliche Zeilen) oder »shrink« (Schrift verkleinern). ``forced_mode``: höchstens
    dieser Weg (die Überlagerung bleibt als letzter Ausweg)."""
    document.ensure_editable()
    if block.revision != document.revision:
        raise UnsupportedEdit("Der Textblock ist nicht mehr aktuell. Bitte erneut auswählen.")
    style = style or TextStyle()
    new_text = _normalize_input(new_text)
    changes_format = any(value is not None for value in (style.family, style.size, style.color, style.bold, style.italic)) or (style.align is not None and style.align != block.align) or bool(style.underline) or bool(style.strike)
    attempts = []
    if forced_mode in (None, NATIVE) and block.editable_natively and block.uniform and not changes_format:
        attempts.append(NATIVE)
    special = any(run.render_mode not in (0, INVISIBLE) for run in block.runs)  # Kontur, Beschneidung …
    if forced_mode in (None, NATIVE, RECONSTRUCTED) and block.editable_natively and not special:
        attempts.append(RECONSTRUCTED)
    attempts.append(OVERLAY)
    page = block.page
    before = render.render_page(document, page, _check_width(document, page))
    before_text = textlayer.text(document, page)
    reasons: list[str] = []
    for mode in attempts:
        try:
            outcome = _apply(document, history, block, new_text, style, overflow, mode, before, before_text)
        except _Rejected as rejected:
            reasons.append(rejected.reason)
            continue
        if mode == OVERLAY and block.invisible:
            outcome.notes.insert(0, "Unsichtbarer Text (z. B. Texterkennung eines Scans): Der neue Text steht sichtbar darüber, der erkannte Text bleibt in der Datei.")
        elif mode == OVERLAY and special:
            outcome.notes.insert(0, "Konturen oder Effekte des Originaltextes wurden nicht übernommen.")
        return outcome
    raise UnsupportedEdit("Der Text lässt sich hier nicht sicher ändern. " + (reasons[-1] if reasons else ""))


class _Rejected(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _normalize_input(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\t", "    ")
    return "".join(char for char in text if char == "\n" or (ord(char) >= 32 and not 0xD800 <= ord(char) <= 0xDFFF and char not in "  "))


def _apply(document: EditorDocument, history: History, block: Block, new_text: str, style: TextStyle, overflow: str, mode: str, before, before_text: str) -> EditOutcome:
    page = block.page
    obj = document.pdf.pages[page].obj
    content = PageContent(document.pdf, obj, page_fonts(obj))
    title = "Text löschen" if not new_text.strip() else "Text bearbeiten"
    with commands.record(document, history, title, pages=(page,)) as rec:
        rec.page(page)
        if mode == NATIVE:
            outcome = _native(document, block, new_text, content, overflow)
        else:
            outcome = _rebuild(document, block, new_text, style, content, overflow, mode)
        prune_fonts(document.pdf, obj, FONT_PREFIX)
        rec.info["mode"] = outcome.mode
        _verify(document, page, before, before_text, block, outcome, new_text)
        rec.fresh = True  # ``_verify`` hat die Darstellung des neuen Stands geladen
    return outcome


def _check_width(document: EditorDocument, page: int) -> int:
    return max(200, int(document.geometry(page).width * CHECK_SCALE))


def _wrap(text: str, width: float, measure: Callable[[str], float]) -> list[str]:
    """Absätze (``\\n``) an Wortgrenzen auf ``width`` umbrechen; zu lange Wörter bleiben ganz."""
    lines: list[str] = []
    for paragraph in text.split("\n"):
        current = ""
        for word in paragraph.split(" "):
            candidate = word if not current else current + " " + word
            if current and measure(candidate) > width + 0.5:
                lines.append(current)
                current = word
            else:
                current = candidate
        lines.append(current)
    return lines


def _direction(angle: float) -> tuple[float, float]:
    rad = math.radians(angle)
    return (math.cos(rad), math.sin(rad))


def _room(document: EditorDocument, page: int, origin: tuple[float, float], angle: float) -> float:
    """Platz von ``origin`` in Schreibrichtung bis zum Seitenrand (abzüglich ``PAGE_MARGIN``)."""
    x0, y0, x1, y1 = document.geometry(page).crop
    ux, uy = _direction(angle)
    limits = []
    if ux > 1e-6:
        limits.append((x1 - origin[0]) / ux)
    elif ux < -1e-6:
        limits.append((x0 - origin[0]) / ux)
    if uy > 1e-6:
        limits.append((y1 - origin[1]) / uy)
    elif uy < -1e-6:
        limits.append((y0 - origin[1]) / uy)
    return max(1.0, min(limits) - PAGE_MARGIN) if limits else math.inf


def _wrap_width(document: EditorDocument, block: Block) -> float:
    if len(block.lines) >= 2:
        return max(line.bounds[2] - line.bounds[0] for line in block.lines)
    return _room(document, block.page, block.first.baseline, block.angle)


def _scales(show: ShowOp) -> tuple[float, float]:
    """Punkte je Textraum-Einheit waagerecht und senkrecht (Textmatrix × CTM)."""
    m = mul(show.tm, show.ctm)
    return max(1e-6, math.hypot(m[0], m[1])), max(1e-6, math.hypot(m[2], m[3]))


def _native(document: EditorDocument, block: Block, new_text: str, content: PageContent, overflow: str) -> EditOutcome:
    shows = [content.shows[run.show] for run in block.runs]
    first_show = shows[0]
    if any(show.state.font != first_show.state.font or abs(show.state.size - first_show.state.size) > 1e-3 for show in shows):
        raise _Rejected("Uneinheitliche Schrift im Block")
    codec = content.codec(first_show.state.font)
    if codec is None or not codec.editable:
        raise _Rejected("Schrift nicht änderbar")
    plain = new_text.replace("\n", "")
    missing_char = codec.can_encode(plain)
    if missing_char is not None:
        raise _Rejected(f"Zeichen »{missing_char}« ist in der Originalschrift nicht kodiert")
    absent = missing_glyphs(document, block.page, block.first, plain)
    if absent:
        raise _Rejected(f"Der Originalschrift fehlen Zeichen: {absent}")
    sx, sy = _scales(first_show)
    state = first_show.state

    def measure(text: str) -> float:
        return codec.text_width(codec.encode(text), state.size, state.char_spacing, state.word_spacing, state.hscale) * sx

    lines = _wrap(new_text, _wrap_width(document, block), measure) if new_text else []
    available = len(block.lines)
    if len(lines) > available:
        if overflow == "ask":
            raise Overflow(len(lines), available)
        if overflow == "shrink":
            raise _Rejected("Verkleinern nur beim Neusetzen")
    step = _line_step(block)
    for i, line in enumerate(block.lines):
        line_shows = [content.shows[run.show] for run in line.runs]
        if i < len(lines):
            content.set_text(line_shows[0], codec.encode(lines[i]))
            for show in line_shows[1:]:
                content.blank(show)
        else:
            for show in line_shows:
                content.blank(show)
    extra = lines[available:]
    if extra:
        # Weitere Zeilen hinter der ersten Ausgabe der letzten Zeile: ``Td`` bezieht sich auf deren
        # Zeilenanfang; danach wird die Zeilenmatrix wiederhergestellt.
        anchor = content.shows[block.lines[-1].runs[0].show]
        dy = step / _scales(anchor)[1]
        inserted = []
        for text in extra:
            inserted.append(pikepdf.ContentStreamInstruction([0, -dy], pikepdf.Operator("Td")))
            inserted.append(pikepdf.ContentStreamInstruction([pikepdf.String(codec.encode(text))], pikepdf.Operator("Tj")))
        inserted.append(pikepdf.ContentStreamInstruction([0, dy * len(extra)], pikepdf.Operator("Td")))
        content.insert_after(anchor, inserted)
    content.commit()
    u = _direction(block.angle)
    down = (u[1], -u[0])
    bounds = block.bounds
    for i, text in enumerate(lines):
        if i < available:
            origin = block.lines[i].baseline
        else:
            last = block.lines[-1].baseline
            k = i - available + 1
            origin = (last[0] + k * step * down[0], last[1] + k * step * down[1])
        for point in _line_corners(origin, u, measure(text), block.size):
            bounds = union(bounds, (point[0], point[1], point[0], point[1]))
    return EditOutcome(NATIVE, bounds, codec.name, [], max(len(lines), 1))


def _line_step(block: Block) -> float:
    if len(block.lines) >= 2:
        return block.lines[0].baseline[1] - block.lines[1].baseline[1]
    return block.size * 1.2


def _remove_original(content: PageContent, block: Block) -> None:
    """Originaltext entfernen: eigene Textobjekte von PDF Tool (nur Text dieses Blocks) ganz, sonst
    nur den Text der Operatoren (Position, Zustand und alles andere bleiben)."""
    targets = {run.show for run in block.runs}
    handled: set[int] = set()
    for run in sorted(block.runs, key=lambda item: -item.show):
        if run.show in handled:
            continue
        show = content.shows[run.show]
        span = content.text_object(show)
        if span is not None:
            inside = [i for i, other in enumerate(content.shows) if span[0] <= other.index <= span[1]]
            ours = all(i in targets or not content.shows[i].raw for i in inside)
            fonts = content.fonts_in(*span)
            if ours and fonts and all(name.startswith(FONT_PREFIX) for name in fonts):
                handled.update(inside)
                content.remove_range(*span)
                continue
        content.blank(show)
        handled.add(run.show)


def _rebuild(document: EditorDocument, block: Block, new_text: str, style: TextStyle, content: PageContent, overflow: str, mode: str) -> EditOutcome:
    page = block.page
    pdf = document.pdf
    obj = pdf.pages[page].obj
    notes: list[str] = []
    cover = None
    if mode == OVERLAY:  # vor jeder Änderung messen
        fill = _background(document, page, block.bounds)
        area = _ink_extent(document, page, block, fill) if block.invisible else block.bounds
        cover = (inflate(area, 1.0), fill)
    original = content.shows[block.first.show] if block.first.show >= 0 and not block.nested else None
    font = _choose_font(document, block, new_text, style, content, original)
    if mode == RECONSTRUCTED:
        _remove_original(content, block)
        content.commit()
    spacing = _Spacing()
    if original is not None:
        sx, sy = _scales(original)
        codec = content.codec(original.state.font)
        word = original.state.word_spacing * sy if font.key == original.state.font and codec is not None and not codec.two_byte else 0.0
        spacing = _Spacing(original.state.char_spacing * sy, word, original.state.hscale * sx / sy)
    size = float(style.size or block.size)
    color = style.color or block.color
    align = style.align or block.align

    def measure(text: str, at: float) -> float:
        return (font.measure(text, at) + _spacing_width(text, spacing)) * spacing.hscale if text else 0.0

    width = _wrap_width(document, block)
    lines = _wrap(new_text, width, lambda text: measure(text, size)) if new_text else []
    available = len(block.lines)
    if len(lines) > available:
        if overflow == "ask":
            raise Overflow(len(lines), available)
        if overflow == "shrink":
            start = size
            while len(lines) > available and size > MIN_FONT_SIZE:
                size = max(MIN_FONT_SIZE, round(size * 0.92, 2))
                lines = _wrap(new_text, width, lambda text, at=size: measure(text, at))
            notes.append(f"Schriftgröße von {fmt(start)} auf {fmt(size)} pt verkleinert, damit der Text passt.")
            if len(lines) > available:
                notes.append("Der Text passt auch verkleinert nicht ganz – zusätzliche Zeilen wurden angefügt.")
    step = _line_step(block) * (size / block.size if block.size else 1.0)
    u = _direction(block.angle)
    down = (u[1], -u[0])
    upright = abs(block.angle) < 0.5
    if len(block.lines) >= 2:
        origin = (min(line.bounds[0] for line in block.lines), block.lines[0].baseline[1])
        box_width = width
    else:
        origin = block.first.baseline
        # Einzelne Zeile: Ausrichtung bezogen auf die bisherige Zeile (rechts: rechter Rand bleibt)
        box_width = block.bounds[2] - origin[0] if upright else 0.0
    out = []
    if cover is not None:
        rect, fill = cover
        out.append(f"{_rgb(fill)} rg {fmt(rect[0])} {fmt(rect[1])} {fmt(rect[2] - rect[0])} {fmt(rect[3] - rect[1])} re f")
    corners = []
    decorations: list[str] = []
    if lines:
        header = f"BT {font.key} {fmt(size)} Tf {_rgb(color)} rg"
        extra = spacing.header()
        out.append(header + (" " + extra if extra else ""))
        for i, text in enumerate(lines):
            measured = measure(text, size)
            dx = {"center": (box_width - measured) / 2, "right": box_width - measured}.get(align, 0.0) if box_width else 0.0
            x = origin[0] + dx * u[0] + step * i * down[0]
            y = origin[1] + dx * u[1] + step * i * down[1]
            out.append(f"{fmt(u[0])} {fmt(u[1])} {fmt(-u[1])} {fmt(u[0])} {fmt(x)} {fmt(y)} Tm <{font.encode(text).hex()}> Tj")
            corners += _line_corners((x, y), u, measured, size)
            decorations += _decorations((x, y), u, measured, size, color, style)
        out.append("ET")
        out += decorations
    if out:
        append_content(pdf, obj, "\n".join(out).encode("latin-1"))
    bounds = block.bounds if cover is None else union(block.bounds, cover[0])
    for point in corners:
        bounds = union(bounds, (point[0], point[1], point[0], point[1]))
    return EditOutcome(mode, bounds, font.label, font.notes + notes, max(1, len(lines)))


UNDERLINE_OFFSET = -0.12  # unter der Grundlinie (× Schriftgröße)
STRIKE_OFFSET = 0.28  # etwa Mitte der Kleinbuchstaben
DECORATION_WIDTH = 0.06  # Linienstärke (× Schriftgröße)


def _decorations(origin: tuple[float, float], u: tuple[float, float], width: float, size: float, color: tuple[int, int, int], style: TextStyle) -> list[str]:
    """Unterstreichen bzw. Durchstreichen einer Zeile als eigene Linie in der Textfarbe (mitgedreht)."""
    if width <= 0:
        return []
    up = (-u[1], u[0])
    result = []
    for wanted, offset in ((style.underline, UNDERLINE_OFFSET), (style.strike, STRIKE_OFFSET)):
        if not wanted:
            continue
        x0 = origin[0] + offset * size * up[0]
        y0 = origin[1] + offset * size * up[1]
        x1, y1 = x0 + width * u[0], y0 + width * u[1]
        result.append(f"q {_rgb(color)} RG {fmt(max(0.4, size * DECORATION_WIDTH))} w 0 J {fmt(x0)} {fmt(y0)} m {fmt(x1)} {fmt(y1)} l S Q")
    return result


def _spacing_width(text: str, spacing: _Spacing) -> float:
    return spacing.char * len(text) + spacing.word * text.count(" ")


def _line_corners(origin: tuple[float, float], u: tuple[float, float], width: float, size: float) -> list[tuple[float, float]]:
    """Ecken einer Textzeile (Oberlänge ≈ 0,9 × Größe, Unterlänge ≈ 0,3 × Größe)."""
    up = (-u[1], u[0])
    points = []
    for along in (0.0, width):
        for across in (size * 0.95, -size * 0.3):
            points.append((origin[0] + along * u[0] + across * up[0], origin[1] + along * u[1] + across * up[1]))
    return points


def _rgb(color: tuple[int, int, int]) -> str:
    return " ".join(fmt(value / 255) for value in color)


def _background(document: EditorDocument, page: int, bounds: Rect) -> tuple[int, int, int]:
    """Hintergrundfarbe um einen Bereich (Median der Randpixel) – für die Abdeckung."""
    geo = document.geometry(page)
    raster = render.render_page(document, page, int(geo.width * CHECK_SCALE))
    image = render.to_pil(raster)
    scale = image.width / geo.width
    u0, v0, u1, v1 = geo.rect_to_view(inflate(bounds, 2.0))
    box = [max(0, int(u0 * scale)), max(0, int(v0 * scale)), min(image.width - 1, int(u1 * scale)), min(image.height - 1, int(v1 * scale))]
    samples = []
    for x in range(box[0], box[2] + 1, 2):
        samples += [image.getpixel((x, box[1])), image.getpixel((x, box[3]))]
    for y in range(box[1], box[3] + 1, 2):
        samples += [image.getpixel((box[0], y)), image.getpixel((box[2], y))]
    if not samples:
        return (255, 255, 255)
    return tuple(int(statistics.median(channel)) for channel in zip(*samples))  # type: ignore[return-value]


def _ink_extent(document: EditorDocument, page: int, block: Block, background: tuple[int, int, int]) -> Rect:
    """Sichtbare Schrift um unsichtbaren Text (Texterkennung): Die erkannten Zeichen decken die
    Schrift im Scan oft nicht genau ab. Gesucht wird in der Zeile des Blocks nach links und rechts,
    solange nach höchstens ``size`` Abstand weitere »Tinte« folgt – damit die Abdeckung die
    sichtbare Schrift ganz verdeckt."""
    geo = document.geometry(page)
    if geo.rotation or abs(block.angle) > 0.5:
        return block.bounds
    raster = render.render_page(document, page, _check_width(document, page))
    image = render.to_pil(raster).convert("L")
    scale = image.width / geo.width
    x0, y0, x1, y1 = block.bounds
    pad = block.size * 0.25
    u0, v0, u1, v1 = geo.rect_to_view((x0, y0 - pad, x1, y1 + pad))
    top, bottom = max(0, int(v0 * scale)), min(image.height - 1, int(v1 * scale))
    if bottom <= top:
        return block.bounds
    level = sum(background) / 3
    band = image.crop((0, top, image.width, bottom + 1))
    width, height = band.size
    pixels = band.load()

    def ink(column: int) -> bool:
        return any(abs(pixels[column, row] - level) > 60 for row in range(0, height, max(1, height // 24)))

    gap = max(2, int(block.size * scale))
    left, right = max(0, int(u0 * scale)), min(width - 1, int(u1 * scale))
    column, since = left - 1, 0
    while column >= 0 and since <= gap:
        since = 0 if ink(column) else since + 1
        if since == 0:
            left = column
        column -= 1
    column, since = right + 1, 0
    while column < width and since <= gap:
        since = 0 if ink(column) else since + 1
        if since == 0:
            right = column
        column += 1
    page_left = geo.to_page(left / scale, 0)[0]
    page_right = geo.to_page((right + 1) / scale, 0)[0]
    return (min(x0, page_left), y0 - pad, max(x1, page_right), y1 + pad)


def _choose_font(document: EditorDocument, block: Block, new_text: str, style: TextStyle, content: PageContent, original: ShowOp | None) -> _Font:
    """Schrift für neu gesetzten Text: Originalschrift, sonst Systemschrift (Teilmenge), sonst
    Standardschrift (Helvetica/Times/Courier, WinAnsi)."""
    text = new_text.replace("\n", "")
    base = style_of(block.font)
    wanted = Style(style.family or base.family, base.bold if style.bold is None else style.bold, base.italic if style.italic is None else style.italic)
    if original is not None and style.family is None and style.bold is None and style.italic is None and block.uniform:
        codec = content.codec(original.state.font)
        if codec is not None and codec.editable and codec.can_encode(text) is None and not missing_glyphs(document, block.page, block.first, text):
            return _Font(original.state.font, codec.name, codec.encode, lambda value, at, c=codec: c.text_width(c.encode(value), at))
    font = new_font(document, block.page, wanted, text)
    if font.label.lower().replace(" ", "") != block.font.split("+")[-1].lower().replace(" ", "") and style.family is None:
        font.notes.insert(0, f"Ersatzschrift: {font.label}, da die Originalschrift die Zeichen nicht enthält oder nicht verwendet werden kann.")
    return font


def new_font(document: EditorDocument, page: int, wanted: Style, text: str) -> _Font:
    """Schrift für neuen Text auf der Seite anlegen: Standardschrift, wenn sie alle Zeichen hat
    (Helvetica/Times/Courier), sonst eine Systemschrift als eingebettete Teilmenge."""
    pdf = document.pdf
    obj = pdf.pages[page].obj
    family = wanted.family.lower()
    standard_family = family in ("helvetica", "times", "courier", "arial", "timesnewroman", "couriernew") or not find_system_font(wanted)
    if standard_family:
        try:
            text.encode("cp1252")
            name = standard_substitute(wanted)
            key = _standard_key(pdf, obj, name)
            return _Font(key, name, lambda value: value.encode("cp1252"), lambda value, at, n=name: sum(standard_width(n, char) for char in value) / 1000.0 * at)
        except UnicodeEncodeError:
            pass
    path = find_system_font(wanted)
    missing = ""
    refused = False
    if path is not None:
        try:
            embedded = embed_truetype(pdf, path, text or " ")
            key = _add_font(pdf, obj, embedded.font)
            return _Font(key, embedded.name, embedded.encode, lambda value, at, e=embedded: e.text_width(value, at))
        except CannotEncode as exc:
            missing = exc.char
        except PermissionError:
            refused = True
        except (OSError, ValueError, KeyError):
            pass
    try:
        text.encode("cp1252")
    except UnicodeEncodeError as exc:
        char = missing or text[exc.start]
        if refused:
            raise _Rejected(f"Die Schrift für das Zeichen »{char}« erlaubt kein Einbetten") from exc
        raise _Rejected(f"Keine verfügbare Schrift enthält das Zeichen »{char}«") from exc
    name = standard_substitute(wanted)
    key = _standard_key(pdf, obj, name)
    return _Font(key, name, lambda value: value.encode("cp1252"), lambda value, at, n=name: sum(standard_width(n, char) for char in value) / 1000.0 * at)


def _add_font(pdf: pikepdf.Pdf, page: pikepdf.Object, font: pikepdf.Object) -> str:
    fonts = commands.own_resources(page, pdf, "/Font").Font
    n = 1
    while f"{FONT_PREFIX}{n}" in fonts:
        n += 1
    key = f"{FONT_PREFIX}{n}"
    fonts[key] = font
    return key


def _standard_key(pdf: pikepdf.Pdf, page: pikepdf.Object, name: str) -> str:
    """Standardschrift der Seite wiederverwenden (eine je Schnitt), sonst neu anlegen."""
    from .document import inherited

    resources = inherited(page, "/Resources")
    fonts = resources.get("/Font") if isinstance(resources, pikepdf.Dictionary) else None
    if isinstance(fonts, pikepdf.Dictionary):
        for key, font in fonts.items():
            if str(key).startswith(FONT_PREFIX) and isinstance(font, pikepdf.Dictionary) and font.get("/Subtype") == pikepdf.Name.Type1 and str(font.get("/BaseFont", "")) == "/" + name and font.get("/Encoding") == pikepdf.Name.WinAnsiEncoding:
                return str(key)
    return _add_font(pdf, page, standard_font(pdf, name))


def _squash(text: str) -> str:
    return re.sub(r"\s+", "", text)


def _verify(document: EditorDocument, page: int, before, before_text: str, block: Block, outcome: EditOutcome, new_text: str) -> None:
    """Prüfen: Änderung nur im erwarteten Bereich, neuer Text lesbar, alter Text entfernt (außer bei
    der Überlagerung). Sonst ``_Rejected`` – die Änderung wird dann zurückgenommen."""
    from PIL import ImageChops, ImageDraw

    document.touch()  # Darstellung aus dem geänderten Stand
    after = render.render_page(document, page, before.width)
    a = render.to_pil(before).convert("L")
    b = render.to_pil(after).convert("L")
    if a.size != b.size:
        raise _Rejected("Seitengröße hat sich geändert")
    diff = ImageChops.difference(a, b).point(lambda value: 255 if value > DIFF_THRESHOLD else 0)
    geo = document.geometry(page)
    scale = a.width / geo.width
    allowed = inflate(union(block.bounds, outcome.bounds), 2.5)
    u0, v0, u1, v1 = geo.rect_to_view(allowed)
    ImageDraw.Draw(diff).rectangle([int(u0 * scale) - 2, int(v0 * scale) - 2, int(u1 * scale) + 2, int(v1 * scale) + 2], fill=0)
    if diff.getbbox() is not None:
        raise _Rejected("Die Änderung hätte die Seite außerhalb des Textes verändert")
    if outcome.mode == OVERLAY:
        return
    found = _squash(textlayer.text(document, page))
    wanted = _squash(new_text)
    if wanted and wanted not in found:
        raise _Rejected("Der neue Text ist im PDF nicht lesbar")
    old = _squash(block.text)
    if old and old not in wanted and found.count(old) >= _squash(before_text).count(old):
        raise _Rejected("Der bisherige Text ist noch vorhanden")


# --- Neuer Text ------------------------------------------------------------------------------------------------
def add_text(document: EditorDocument, history: History, page: int, x: float, y: float, text: str, *, style: TextStyle | None = None, width: float | None = None) -> EditOutcome:
    """Neuen Text einfügen. ``x``, ``y``: linke obere Ecke **in der Anzeige** (als Seitenkoordinaten);
    ``width``: Breite des Textrahmens für Umbruch und Ausrichtung (``None`` = ohne Umbruch). Der Text
    steht in der Anzeige waagerecht – auch auf gedrehten Seiten."""
    document.ensure_editable()
    style = style or TextStyle()
    text = _normalize_input(text)
    if not text.strip():
        raise UnsupportedEdit("Es wurde kein Text eingegeben.")
    size = float(style.size or 12.0)
    color = style.color or (0, 0, 0)
    wanted = Style(style.family or "Helvetica", bool(style.bold), bool(style.italic))
    angle = document.geometry(page).rotation % 360  # Anzeige-Drehung im Uhrzeigersinn ausgleichen
    u = _direction(angle)
    down = (u[1], -u[0])
    with commands.record(document, history, "Text hinzufügen", pages=(page,)) as rec:
        obj = rec.page(page)
        try:
            font = new_font(document, page, wanted, text.replace("\n", ""))
        except _Rejected as rejected:
            raise UnsupportedEdit(rejected.reason + ".") from rejected
        lines = _wrap(text, width, lambda value: font.measure(value, size)) if width else text.split("\n")
        box_width = width or max(font.measure(line, size) for line in lines)
        step = size * 1.2
        out = [f"BT {font.key} {fmt(size)} Tf {_rgb(color)} rg"]
        corners = [(x, y)]
        decorations: list[str] = []
        for i, line in enumerate(lines):
            measured = font.measure(line, size)
            dx = {"center": (box_width - measured) / 2, "right": box_width - measured}.get(style.align or "left", 0.0)
            dy = size * 0.8 + step * i  # Grundlinie: etwa die Oberlänge unter der Oberkante
            px = x + dx * u[0] + dy * down[0]
            py = y + dx * u[1] + dy * down[1]
            out.append(f"{fmt(u[0])} {fmt(u[1])} {fmt(-u[1])} {fmt(u[0])} {fmt(px)} {fmt(py)} Tm <{font.encode(line).hex()}> Tj")
            corners += _line_corners((px, py), u, measured, size)
            decorations += _decorations((px, py), u, measured, size, color, style)
        out.append("ET")
        out += decorations
        append_content(document.pdf, obj, "\n".join(out).encode("latin-1"))
        rec.info["mode"] = NATIVE
    bounds = None
    for point in corners:
        bounds = union(bounds, (point[0], point[1], point[0], point[1]))
    return EditOutcome(NATIVE, bounds or (x, y, x, y), font.label, font.notes, len(lines))
