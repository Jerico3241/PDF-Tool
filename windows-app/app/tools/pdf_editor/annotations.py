"""Anmerkungen (Kommentare): markieren, unterstreichen, durchstreichen, Notiz, Freihand, Rechteck,
Ellipse, Linie, Pfeil und Textfeld – anlegen, ändern, verschieben, löschen und auflisten.

Jede neue Anmerkung bekommt ein eigenes Erscheinungsbild (``/AP``), damit sie in jedem Programm
gleich aussieht. Vorhandene Anmerkungen bleiben unverändert erhalten; verschieben lassen sich auch
fremde Anmerkungen (Rechteck und Geometrie werden verschoben, ihr Erscheinungsbild folgt).
Formularfelder (Widgets) und Links sind keine Kommentare – sie erscheinen hier nicht.

Ein Autor wird nur eingetragen, wenn er ausdrücklich angegeben ist (kein Windows-Benutzername
ohne Zustimmung in fremden Dateien).
"""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

import pikepdf
from pikepdf import Array, Dictionary, Name, String

from . import commands
from .commands import History
from .content import fmt
from .document import EditorDocument
from .errors import UnsupportedEdit
from .geometry import Rect, inflate, normalize, union

HIGHLIGHT, UNDERLINE, STRIKEOUT = "highlight", "underline", "strikeout"
NOTE, INK, SQUARE, CIRCLE, LINE, ARROW, TEXTBOX = "note", "ink", "square", "circle", "line", "arrow", "textbox"
SUBTYPES = {HIGHLIGHT: "/Highlight", UNDERLINE: "/Underline", STRIKEOUT: "/StrikeOut", NOTE: "/Text", INK: "/Ink", SQUARE: "/Square", CIRCLE: "/Circle", LINE: "/Line", ARROW: "/Line", TEXTBOX: "/FreeText"}
LABELS = {
    "/Highlight": "Markierung", "/Underline": "Unterstreichung", "/StrikeOut": "Durchstreichung", "/Squiggly": "Wellenlinie",
    "/Text": "Notiz", "/Ink": "Freihand", "/Square": "Rechteck", "/Circle": "Ellipse", "/Line": "Linie", "/Polygon": "Vieleck",
    "/PolyLine": "Linienzug", "/FreeText": "Textfeld", "/Stamp": "Stempel", "/Caret": "Einfügemarke", "/FileAttachment": "Dateianhang",
    "/Sound": "Ton", "/Redact": "Schwärzungsvorschlag",
}
HIDDEN = ("/Popup", "/Link", "/Widget")
DEFAULT_COLORS = {HIGHLIGHT: (255, 235, 59), UNDERLINE: (33, 150, 243), STRIKEOUT: (229, 57, 53), NOTE: (255, 193, 7), INK: (229, 57, 53), SQUARE: (229, 57, 53), CIRCLE: (229, 57, 53), LINE: (229, 57, 53), ARROW: (229, 57, 53), TEXTBOX: (0, 0, 0)}
NOTE_SIZE = 20.0
KAPPA = 0.5522847498  # Bézier-Näherung des Kreises


@dataclass(frozen=True)
class AnnotationInfo:
    key: str  # stabil, solange das Dokument offen ist (Objektnummer)
    page: int
    subtype: str
    label: str
    rect: Rect
    color: tuple[int, int, int] | None
    contents: str
    author: str
    modified: str
    ours: bool  # von PDF Tool angelegt (Erscheinungsbild wird neu erzeugt)


@dataclass
class Style:
    color: tuple[int, int, int] | None = None
    width: float = 2.0  # Linienstärke (Freihand, Formen, Linien, Rahmen des Textfelds)
    fill: tuple[int, int, int] | None = None  # Füllung (Rechteck, Ellipse, Textfeld)
    opacity: float = 1.0
    font_size: float = 12.0  # Textfeld
    author: str = ""
    extra: dict = field(default_factory=dict)


# --- Lesen --------------------------------------------------------------------------------------------------
def key_of(annot: pikepdf.Object, page: int, position: int) -> str:
    return f"{annot.objgen[0]}-{annot.objgen[1]}" if annot.is_indirect else f"p{page}-{position}"


def list_annotations(document: EditorDocument, page: int | None = None) -> list[AnnotationInfo]:
    """Kommentare einer Seite (oder aller Seiten) in der Reihenfolge der Seite."""
    result: list[AnnotationInfo] = []
    indexes = range(document.page_count) if page is None else [page]
    for index in indexes:
        annots = document.pdf.pages[index].obj.get("/Annots")
        if not isinstance(annots, Array):
            continue
        for position, annot in enumerate(annots):
            if not isinstance(annot, Dictionary):
                continue
            subtype = str(annot.get("/Subtype", ""))
            if subtype in HIDDEN or not subtype:
                continue
            rect = _rect(annot)
            if rect is None:
                continue
            result.append(AnnotationInfo(
                key_of(annot, index, position), index, subtype, LABELS.get(subtype, subtype.lstrip("/")), rect, _color(annot.get("/C")),
                _text(annot.get("/Contents")), _text(annot.get("/T")), _date(annot.get("/M")), str(annot.get("/PTEditor", "")) == "PDF Tool",
            ))
    return result


def find(document: EditorDocument, key: str) -> tuple[int, int, pikepdf.Object]:
    """(Seite, Position in /Annots, Anmerkung) zu einem Schlüssel."""
    for index in range(document.page_count):
        annots = document.pdf.pages[index].obj.get("/Annots")
        if not isinstance(annots, Array):
            continue
        for position, annot in enumerate(annots):
            if isinstance(annot, Dictionary) and key_of(annot, index, position) == key:
                return index, position, annot
    raise UnsupportedEdit("Der Kommentar ist nicht mehr vorhanden.")


def _rect(annot) -> Rect | None:
    try:
        return normalize(tuple(float(v) for v in annot.Rect))  # type: ignore[arg-type]
    except (AttributeError, TypeError, ValueError):
        return None


def _color(value) -> tuple[int, int, int] | None:
    try:
        numbers = [float(v) for v in value]
    except (TypeError, ValueError):
        return None
    if len(numbers) == 3:
        return tuple(int(round(max(0.0, min(1.0, v)) * 255)) for v in numbers)  # type: ignore[return-value]
    if len(numbers) == 1:
        gray = int(round(max(0.0, min(1.0, numbers[0])) * 255))
        return (gray, gray, gray)
    if len(numbers) == 4:
        c, m, y, k = numbers
        return tuple(int(round(255 * (1 - min(1.0, v + k)))) for v in (c, m, y))  # type: ignore[return-value]
    return None


def _text(value) -> str:
    if value is None:
        return ""
    try:
        return str(value).replace("\r\n", "\n").replace("\r", "\n")
    except (TypeError, ValueError):
        return ""


def _date(value) -> str:
    if value is None:
        return ""
    try:
        from pikepdf.models.metadata import decode_pdf_date

        return decode_pdf_date(str(value)).astimezone().strftime("%d.%m.%Y %H:%M")
    except (ValueError, TypeError, AttributeError):
        return ""


# --- Anlegen ------------------------------------------------------------------------------------------------
def add_markup(document: EditorDocument, history: History, page: int, kind: str, rects: list[Rect], *, style: Style | None = None, contents: str = "") -> str:
    """Text markieren, unterstreichen oder durchstreichen – ``rects``: Zeilenrechtecke der Auswahl."""
    if kind not in (HIGHLIGHT, UNDERLINE, STRIKEOUT):
        raise ValueError(kind)
    boxes = [normalize(r) for r in rects if abs(r[2] - r[0]) > 0.1 and abs(r[3] - r[1]) > 0.1]
    if not boxes:
        raise UnsupportedEdit("Es ist kein Text ausgewählt.")
    style = style or Style()
    quads = []
    for x0, y0, x1, y1 in boxes:
        quads += [x0, y1, x1, y1, x0, y0, x1, y0]
    annot = _base(document, page, kind, _union(boxes), style, contents)
    annot.QuadPoints = Array([round(v, 3) for v in quads])
    return _insert(document, history, page, annot, "Text " + {HIGHLIGHT: "markieren", UNDERLINE: "unterstreichen", STRIKEOUT: "durchstreichen"}[kind])


def add_note(document: EditorDocument, history: History, page: int, x: float, y: float, text: str, *, style: Style | None = None) -> str:
    """Notiz an einer Stelle (linke obere Ecke des Symbols, Seitenkoordinaten)."""
    style = style or Style()
    rect = (x, y - NOTE_SIZE, x + NOTE_SIZE, y)
    annot = _base(document, page, NOTE, rect, style, text)
    annot.Name = Name.Comment
    annot.Open = False
    annot.F = 4 | 8 | 16  # drucken, nicht zoomen, nicht drehen (Symbol bleibt aufrecht und gleich groß)
    return _insert(document, history, page, annot, "Notiz hinzufügen")


def add_ink(document: EditorDocument, history: History, page: int, strokes: list[list[tuple[float, float]]], *, style: Style | None = None) -> str:
    """Freihandzeichnung aus Strichen (Punktfolgen in Seitenkoordinaten)."""
    strokes = [stroke for stroke in strokes if len(stroke) >= 2]
    if not strokes:
        raise UnsupportedEdit("Die Zeichnung ist leer.")
    style = style or Style()
    box = None
    for stroke in strokes:
        for x, y in stroke:
            box = union(box, (x, y, x, y))
    annot = _base(document, page, INK, inflate(box, style.width / 2 + 1), style, "")
    annot.InkList = Array([Array([round(v, 2) for point in stroke for v in point]) for stroke in strokes])
    return _insert(document, history, page, annot, "Freihand zeichnen")


def add_shape(document: EditorDocument, history: History, page: int, kind: str, rect: Rect, *, style: Style | None = None, contents: str = "") -> str:
    """Rechteck oder Ellipse im Bereich ``rect`` (Seitenkoordinaten)."""
    if kind not in (SQUARE, CIRCLE):
        raise ValueError(kind)
    style = style or Style()
    rect = normalize(rect)
    if rect[2] - rect[0] < 1 or rect[3] - rect[1] < 1:
        raise UnsupportedEdit("Die Form ist zu klein.")
    annot = _base(document, page, kind, inflate(rect, style.width / 2), style, contents)
    if style.fill is not None:
        annot.IC = _rgb(style.fill)
    return _insert(document, history, page, annot, "Rechteck zeichnen" if kind == SQUARE else "Ellipse zeichnen")


def add_line(document: EditorDocument, history: History, page: int, start: tuple[float, float], end: tuple[float, float], *, arrow: bool = False, style: Style | None = None) -> str:
    style = style or Style()
    if math.hypot(end[0] - start[0], end[1] - start[1]) < 1:
        raise UnsupportedEdit("Die Linie ist zu kurz.")
    head = _arrow_size(style.width) if arrow else 0.0
    box = normalize((start[0], start[1], end[0], end[1]))
    annot = _base(document, page, ARROW if arrow else LINE, inflate(box, style.width / 2 + head + 1), style, "")
    annot.L = Array([round(v, 2) for v in (*start, *end)])
    annot.LE = Array([Name("/None"), Name.OpenArrow if arrow else Name("/None")])
    return _insert(document, history, page, annot, "Pfeil zeichnen" if arrow else "Linie zeichnen")


def add_textbox(document: EditorDocument, history: History, page: int, rect: Rect, text: str, *, style: Style | None = None) -> str:
    """Textfeld (FreeText) – Text steht in der Anzeige waagerecht, auch auf gedrehten Seiten."""
    style = style or Style(width=1.0)
    rect = normalize(rect)
    if rect[2] - rect[0] < 10 or rect[3] - rect[1] < 8:
        raise UnsupportedEdit("Das Textfeld ist zu klein.")
    if not text.strip():
        raise UnsupportedEdit("Es wurde kein Text eingegeben.")
    annot = _base(document, page, TEXTBOX, rect, style, text)
    color = style.color or DEFAULT_COLORS[TEXTBOX]
    annot.DA = String(f"/Helv {fmt(style.font_size)} Tf {_rgb_ops(color)} rg")
    annot.Q = 0
    rotation = document.geometry(page).rotation
    if rotation:
        annot.Rotate = rotation  # Hinweis für Programme, die das Textfeld selbst neu setzen
    return _insert(document, history, page, annot, "Textfeld hinzufügen")


# --- Ändern, Verschieben, Löschen -------------------------------------------------------------------------
def update(document: EditorDocument, history: History, key: str, *, contents: str | None = None, color: tuple[int, int, int] | None = None) -> None:
    """Inhalt bzw. Farbe ändern; das Erscheinungsbild eigener Anmerkungen wird neu erzeugt."""
    document.ensure_editable("annotate")
    page, _position, annot = find(document, key)
    with commands.record(document, history, "Kommentar ändern", pages=(page,)) as rec:
        rec.object(annot, ("/Contents", "/C", "/M", "/AP", "/DA"))
        if contents is not None:
            annot.Contents = String(contents)
        if color is not None:
            annot.C = _rgb(color)
            if annot.get("/Subtype") == Name.FreeText:
                size = _da_size(annot)
                annot.DA = String(f"/Helv {fmt(size)} Tf {_rgb_ops(color)} rg")
        annot.M = String(_now())
        if _ours(annot):
            _appearance(document, page, annot)


def move(document: EditorDocument, history: History, key: str, dx: float, dy: float) -> None:
    """Anmerkung verschieben (Rechteck und Geometrie)."""
    document.ensure_editable("annotate")
    page, _position, annot = find(document, key)
    with commands.record(document, history, "Kommentar verschieben", pages=(page,)) as rec:
        rec.object(annot, ("/Rect", "/QuadPoints", "/InkList", "/L", "/Vertices", "/CL", "/M", "/AP", "/RD"))
        rect = _rect(annot)
        annot.Rect = Array([round(v, 3) for v in (rect[0] + dx, rect[1] + dy, rect[2] + dx, rect[3] + dy)])
        for key_name in ("/QuadPoints", "/L", "/Vertices", "/CL"):
            if isinstance(annot.get(key_name), Array):
                annot[key_name] = _shift(annot[key_name], dx, dy)
        if isinstance(annot.get("/InkList"), Array):
            annot.InkList = Array([_shift(stroke, dx, dy) for stroke in annot.InkList])
        annot.M = String(_now())
        if _ours(annot):
            _appearance(document, page, annot)
        popup = annot.get("/Popup")
        if isinstance(popup, Dictionary) and _rect(popup) is not None:
            rec.object(popup, ("/Rect",))
            box = _rect(popup)
            popup.Rect = Array([round(v, 3) for v in (box[0] + dx, box[1] + dy, box[2] + dx, box[3] + dy)])


def delete(document: EditorDocument, history: History, key: str) -> None:
    """Kommentar entfernen (samt zugehöriger Popup-Notiz und Antworten darauf)."""
    document.ensure_editable("annotate")
    page, _position, annot = find(document, key)
    obj = document.pdf.pages[page].obj
    gone = {annot.objgen} if annot.is_indirect else set()
    popup = annot.get("/Popup")
    if isinstance(popup, Dictionary) and popup.is_indirect:
        gone.add(popup.objgen)
    annots = obj.Annots
    for item in annots:  # Antworten (IRT) auf den Kommentar gehen mit
        if isinstance(item, Dictionary) and isinstance(item.get("/IRT"), Dictionary) and item.IRT.objgen in gone:
            gone.add(item.objgen)
    with commands.record(document, history, "Kommentar löschen", pages=(page,)) as rec:
        rec.page(page, ("/Annots",))
        kept = [item for position, item in enumerate(annots) if not (isinstance(item, Dictionary) and (item.objgen in gone if item.is_indirect else key_of(item, page, position) == key))]
        if kept:
            obj.Annots = Array(kept)
        else:
            del obj["/Annots"]


# --- Bausteine -------------------------------------------------------------------------------------------------
def _base(document: EditorDocument, page: int, kind: str, rect: Rect, style: Style, contents: str) -> pikepdf.Object:
    document.ensure_editable("annotate")
    color = style.color or DEFAULT_COLORS[kind]
    now = _now()
    annot = Dictionary(
        Type=Name.Annot,
        Subtype=Name(SUBTYPES[kind]),
        Rect=Array([round(v, 3) for v in rect]),
        C=_rgb(color),
        F=4,
        NM=String(str(uuid.uuid4())),
        M=String(now),
        CreationDate=String(now),
        PTEditor=String("PDF Tool"),
    )
    if contents:
        annot.Contents = String(contents)
    if style.author:
        annot.T = String(style.author)
    if style.opacity < 1.0:
        annot.CA = round(max(0.05, style.opacity), 3)
    if kind in (INK, SQUARE, CIRCLE, LINE, ARROW, TEXTBOX):
        annot.BS = Dictionary(W=round(style.width, 2), S=Name.S)
    return annot


def _insert(document: EditorDocument, history: History, page: int, annot: Dictionary, title: str) -> str:
    pdf = document.pdf
    with commands.record(document, history, title, pages=(page,)) as rec:
        obj = rec.page(page, ("/Annots",))
        annot = pdf.make_indirect(annot)
        annot.P = obj
        _appearance(document, page, annot)
        annots = obj.get("/Annots")
        obj.Annots = Array([*(list(annots) if isinstance(annots, Array) else []), annot])
    return key_of(annot, page, 0)


def _ours(annot) -> bool:
    return str(annot.get("/PTEditor", "")) == "PDF Tool"


def _now() -> str:
    from pikepdf.models.metadata import encode_pdf_date

    return encode_pdf_date(datetime.now(timezone.utc))


def _rgb(color: tuple[int, int, int]) -> Array:
    return Array([round(v / 255, 4) for v in color])


def _rgb_ops(color: tuple[int, int, int]) -> str:
    return " ".join(fmt(v / 255) for v in color)


def _union(boxes: list[Rect]) -> Rect:
    box = None
    for item in boxes:
        box = union(box, item)
    return box  # type: ignore[return-value]


def _shift(array: Array, dx: float, dy: float) -> Array:
    values = [float(v) for v in array]
    return Array([round(v + (dx if i % 2 == 0 else dy), 3) for i, v in enumerate(values)])


def _arrow_size(width: float) -> float:
    return max(6.0, width * 4)


def _da_size(annot) -> float:
    import re

    match = re.search(r"([\d.]+)\s+Tf", _text(annot.get("/DA")))
    return float(match.group(1)) if match else 12.0


# --- Erscheinungsbilder ------------------------------------------------------------------------------------------
def _appearance(document: EditorDocument, page: int, annot: pikepdf.Object) -> None:
    """Erscheinungsbild (``/AP /N``) für eine eigene Anmerkung erzeugen – im Seitenraum (BBox = Rect)."""
    pdf = document.pdf
    subtype = annot.get("/Subtype")
    rect = _rect(annot)
    color = _color(annot.get("/C")) or (0, 0, 0)
    width = float(annot.BS.W) if isinstance(annot.get("/BS"), Dictionary) and "/W" in annot.BS else 1.0
    resources = Dictionary()
    ops: list[str] = []
    if subtype in (Name.Highlight, Name.Underline, Name.StrikeOut):
        values = [float(v) for v in annot.QuadPoints]
        quads = [values[i : i + 8] for i in range(0, len(values) - 7, 8)]
        if subtype == Name.Highlight:
            resources.ExtGState = Dictionary(GS0=Dictionary(Type=Name.ExtGState, BM=Name.Multiply))
            ops.append(f"/GS0 gs {_rgb_ops(color)} rg")
            for q in quads:
                ops.append(f"{fmt(q[4])} {fmt(q[5])} m {fmt(q[6])} {fmt(q[7])} l {fmt(q[2])} {fmt(q[3])} l {fmt(q[0])} {fmt(q[1])} l h f")
        else:
            ops.append(f"{_rgb_ops(color)} RG")
            for q in quads:
                height = abs(q[1] - q[5])
                thickness = max(0.6, height / 14)
                y = (q[5] + height * 0.12) if subtype == Name.Underline else (q[5] + height * 0.42)
                ops.append(f"{fmt(thickness)} w {fmt(q[4])} {fmt(y)} m {fmt(q[6])} {fmt(y)} l S")
    elif subtype == Name.Text:
        x0, y0, x1, y1 = rect
        ops += [f"{_rgb_ops(color)} rg 0.35 0.35 0.35 RG 0.8 w", f"{fmt(x0 + 1)} {fmt(y0 + 4)} {fmt(x1 - x0 - 2)} {fmt(y1 - y0 - 5)} re B",
                f"{fmt(x0 + 5)} {fmt(y0 + 4)} m {fmt(x0 + 4)} {fmt(y0)} l {fmt(x0 + 9)} {fmt(y0 + 4)} l f",
                "0.2 0.2 0.2 RG 1 w"] + [f"{fmt(x0 + 4)} {fmt(y1 - 5 - 3.5 * i)} m {fmt(x1 - 4)} {fmt(y1 - 5 - 3.5 * i)} l S" for i in range(3)]
    elif subtype == Name.Ink:
        ops.append(f"{_rgb_ops(color)} RG {fmt(width)} w 1 J 1 j")
        for stroke in annot.InkList:
            values = [float(v) for v in stroke]
            points = [(values[i], values[i + 1]) for i in range(0, len(values) - 1, 2)]
            ops.append(f"{fmt(points[0][0])} {fmt(points[0][1])} m " + " ".join(f"{fmt(x)} {fmt(y)} l" for x, y in points[1:]) + " S")
    elif subtype in (Name.Square, Name.Circle):
        x0, y0, x1, y1 = inflate(rect, -width / 2)
        fill = _color(annot.get("/IC"))
        ops.append(f"{_rgb_ops(color)} RG {fmt(width)} w" + (f" {_rgb_ops(fill)} rg" if fill else ""))
        paint = "B" if fill else "S"
        if subtype == Name.Square:
            ops.append(f"{fmt(x0)} {fmt(y0)} {fmt(x1 - x0)} {fmt(y1 - y0)} re {paint}")
        else:
            ops.append(_ellipse(x0, y0, x1, y1) + f" {paint}")
    elif subtype == Name.Line:
        x0, y0, x1, y1 = (float(v) for v in annot.L)
        ops.append(f"{_rgb_ops(color)} RG {fmt(width)} w 1 J 1 j {fmt(x0)} {fmt(y0)} m {fmt(x1)} {fmt(y1)} l S")
        ending = annot.get("/LE")
        if isinstance(ending, Array) and len(ending) == 2 and ending[1] == Name.OpenArrow:
            angle = math.atan2(y1 - y0, x1 - x0)
            size = _arrow_size(width)
            left = (x1 - size * math.cos(angle - 0.45), y1 - size * math.sin(angle - 0.45))
            right = (x1 - size * math.cos(angle + 0.45), y1 - size * math.sin(angle + 0.45))
            ops.append(f"{fmt(left[0])} {fmt(left[1])} m {fmt(x1)} {fmt(y1)} l {fmt(right[0])} {fmt(right[1])} l S")
    elif subtype == Name.FreeText:
        ops += _freetext(document, page, annot, rect, color, width, resources)
    else:
        return
    stream = pdf.make_stream("\n".join(ops).encode("latin-1"))
    stream.Type = Name.XObject
    stream.Subtype = Name.Form
    stream.BBox = Array([round(v, 3) for v in rect])
    stream.Resources = resources
    annot.AP = Dictionary(N=stream)


def _ellipse(x0: float, y0: float, x1: float, y1: float) -> str:
    cx, cy, rx, ry = (x0 + x1) / 2, (y0 + y1) / 2, (x1 - x0) / 2, (y1 - y0) / 2
    kx, ky = rx * KAPPA, ry * KAPPA
    return (f"{fmt(cx + rx)} {fmt(cy)} m "
            f"{fmt(cx + rx)} {fmt(cy + ky)} {fmt(cx + kx)} {fmt(cy + ry)} {fmt(cx)} {fmt(cy + ry)} c "
            f"{fmt(cx - kx)} {fmt(cy + ry)} {fmt(cx - rx)} {fmt(cy + ky)} {fmt(cx - rx)} {fmt(cy)} c "
            f"{fmt(cx - rx)} {fmt(cy - ky)} {fmt(cx - kx)} {fmt(cy - ry)} {fmt(cx)} {fmt(cy - ry)} c "
            f"{fmt(cx + kx)} {fmt(cy - ry)} {fmt(cx + rx)} {fmt(cy - ky)} {fmt(cx + rx)} {fmt(cy)} c h")


def _freetext(document: EditorDocument, page: int, annot, rect: Rect, color, width: float, resources: Dictionary) -> list[str]:
    """Textfeld: Rahmen, Hintergrund und umbrochener Text (aufrecht in der Anzeige)."""
    from . import textedit

    text = _text(annot.get("/Contents"))
    size = _da_size(annot)
    border = _color(annot.get("/C")) or (0, 0, 0)
    fill = _color(annot.get("/IC"))
    rotation = document.geometry(page).rotation
    x0, y0, x1, y1 = rect
    # Anzeige-Achsen im Seitenraum: rechts = u, unten = (u_y, −u_x)
    rad = math.radians(rotation)
    ux, uy = round(math.cos(rad), 12), round(math.sin(rad), 12)
    vertical = rotation in (90, 270)
    box_w, box_h = ((y1 - y0), (x1 - x0)) if vertical else ((x1 - x0), (y1 - y0))
    # obere linke Ecke in der Anzeige → Seitenraum
    corners = {0: (x0, y1), 90: (x0, y0), 180: (x1, y0), 270: (x1, y1)}
    ox, oy = corners.get(rotation, (x0, y1))
    key, font_obj, measure, encode = _ap_font(document.pdf, text.replace("\n", ""))
    resources.Font = Dictionary({key: font_obj})  # Schrift nur im Erscheinungsbild, nicht auf der Seite
    padding = 2.0 + width
    lines = textedit._wrap(text, max(1.0, box_w - 2 * padding), lambda value: measure(value, size))  # noqa: SLF001
    ops = []
    if fill is not None:
        ops.append(f"{_rgb_ops(fill)} rg {fmt(x0)} {fmt(y0)} {fmt(x1 - x0)} {fmt(y1 - y0)} re f")
    if width > 0:
        ops.append(f"{_rgb_ops(border)} RG {fmt(width)} w {fmt(x0 + width / 2)} {fmt(y0 + width / 2)} {fmt(x1 - x0 - width)} {fmt(y1 - y0 - width)} re S")
    ops.append(f"q {fmt(x0)} {fmt(y0)} {fmt(x1 - x0)} {fmt(y1 - y0)} re W n BT {key} {fmt(size)} Tf {_rgb_ops(color)} rg")
    step = size * 1.2
    for i, line in enumerate(lines):
        dx, dy = padding, padding + size * 0.85 + step * i
        if dy > box_h + size:
            break
        px = ox + dx * ux + dy * uy
        py = oy + dx * uy - dy * ux
        ops.append(f"{fmt(ux)} {fmt(uy)} {fmt(-uy)} {fmt(ux)} {fmt(px)} {fmt(py)} Tm <{encode(line).hex()}> Tj")
    ops.append("ET Q")
    return ops


def _ap_font(pdf: pikepdf.Pdf, text: str):
    """Schrift für das Erscheinungsbild eines Textfelds: Helvetica (WinAnsi), wenn sie alle Zeichen
    hat, sonst eine Systemschrift als eingebettete Teilmenge (nur mit erlaubter Einbettung)."""
    from .fonts import CannotEncode, Style as FontStyle, embed_truetype, find_system_font, standard_font, standard_width

    try:
        text.encode("cp1252")
        font = standard_font(pdf, "Helvetica")
        return "/Helv", font, (lambda value, at: sum(standard_width("Helvetica", char) for char in value) / 1000.0 * at), (lambda value: value.encode("cp1252"))
    except UnicodeEncodeError:
        pass
    path = find_system_font(FontStyle("Helvetica"))
    if path is None:
        raise UnsupportedEdit("Für diese Zeichen ist keine passende Schrift verfügbar.")
    try:
        embedded = embed_truetype(pdf, path, text)
    except CannotEncode as exc:
        raise UnsupportedEdit(f"Keine verfügbare Schrift enthält das Zeichen »{exc.char}«.") from exc
    except PermissionError as exc:
        raise UnsupportedEdit("Die passende Schrift erlaubt kein Einbetten.") from exc
    return "/PTF1", embedded.font, (lambda value, at, e=embedded: e.text_width(value, at)), embedded.encode
