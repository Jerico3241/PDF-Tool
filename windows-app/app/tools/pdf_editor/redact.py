"""Schwärzen: Inhalte in markierten Bereichen endgültig entfernen und deckend überdecken.

Anders als eine Überlagerung bleibt nichts in der Datei zurück. Je markiertem Bereich einer Seite:

* **Text** – jedes Zeichen, dessen Glyphe den Bereich berührt, wird aus dem Inhaltsstrom entfernt;
  an seine Stelle tritt ein reiner Abstand gleicher Breite (der übrige Text bleibt, wo er ist). Das
  gilt auch für unsichtbaren Text (z. B. Texterkennung über Scans) und für Text in
  Formular-XObjects (die Seite bekommt eine eigene, geänderte Kopie).
* **Bilder** – die Bildpunkte unter dem Bereich werden geschwärzt (auch die Transparenzmaske, die
  sonst die Form verriete); das Bild wird neu geschrieben. Die Seite bekommt eine eigene Kopie, andere
  Seiten mit demselben Bild bleiben unverändert.
* **Grafiken** (Linien, Flächen), die ganz im Bereich liegen, werden entfernt; Grafiken, die nur
  teilweise hineinragen, bleiben und werden überdeckt.
* **Anmerkungen** (Kommentare, Links, Formularfelder), die den Bereich berühren, werden entfernt –
  Formularfelder samt Feld. Miniaturbild der Seite und Ersatztexte (``/ActualText``, ``/Alt``) im
  Inhalt und im Strukturbaum dieser Seiten werden entfernt.
* Danach wird der Bereich deckend gefüllt (Standard: Schwarz).

**Prüfung:** Am Ende liest PDFium die Seite neu; liegt in einem Bereich noch ein Zeichen, wird die
Seite als Bild geschwärzt (Seite mit den Abdeckungen gerendert, 200 dpi) – ihr Text ist dann nicht
mehr durchsuchbar, das Ergebnis nennt die Seite. Ebenso, wenn sich ein Bild nicht sicher bearbeiten
lässt (z. B. JBIG2, Inline-Bild, Maske). Alles ist ein Schritt für Rückgängig – bis zum Speichern.

Gesucht werden kann nach Mustern (IBAN mit Prüfziffer, E-Mail-Adressen, Telefonnummern, Datumsangaben)
und eigenen Begriffen. Inhalte werden nie protokolliert.
"""

from __future__ import annotations

import io
import re
import zlib
from dataclasses import dataclass, field

import pikepdf
from pikepdf import Array, Dictionary, Name, Operator

from pdfium_lock import PDFIUM_LOCK

from . import textlayer
from .commands import History, own_resources, record
from .content import PATH_BUILD, IDENTITY, PageContent, _num, apply, append_content, fmt, invert, mul, page_fonts, page_xobjects
from .document import EditorDocument
from .errors import EditorError
from .geometry import Rect, intersects, normalize

FORM_DEPTH = 8
MIN_OVERLAP = 0.5  # Punkte: so weit muss eine Glyphe in den Bereich ragen
RASTER_DPI = 200
PATTERNS = ("iban", "email", "phone", "date")
PATTERN_LABELS = {"iban": "IBAN", "email": "E-Mail-Adresse", "phone": "Telefonnummer", "date": "Datum", "term": "Begriff"}


@dataclass(frozen=True)
class Mark:
    page: int
    rect: Rect  # Seitenkoordinaten


@dataclass
class RedactResult:
    areas: int = 0
    chars: int = 0
    images: int = 0
    paths: int = 0
    annotations: int = 0
    rasterized: list[int] = field(default_factory=list)  # Seiten, die als Bild geschwärzt wurden
    notes: list[str] = field(default_factory=list)


@dataclass
class Match:
    page: int
    kind: str
    rects: list[Rect]  # Seitenkoordinaten (je Zeile ein Rechteck)
    text: str  # für die Liste in der Oberfläche – nie protokollieren


class _Unsafe(Exception):
    """Ein Teil der Seite lässt sich nicht sicher bearbeiten – die Seite wird als Bild geschwärzt."""


# --- Suchen ---------------------------------------------------------------------------------------------------------
_REGEX = {
    "iban": re.compile(r"(?<![A-Za-z0-9])[A-Z]{2}\d{2}(?: ?[A-Z0-9]{4}){2,7}(?: ?[A-Z0-9]{1,3})?(?![A-Za-z0-9])"),
    "email": re.compile(r"(?<![\w.%+-])[\w.%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}(?![\w-])"),
    "phone": re.compile(r"(?<![\w+])(?:\+\d{1,3}[ /-]?(?:\(0\))?[ /-]?|\(?0)\d{1,5}\)?(?:[ /-]?\d{1,5}){1,5}(?!\w)"),
    "date": re.compile(r"(?<!\d)\d{1,2}\.\s?\d{1,2}\.\s?(?:19|20)\d{2}(?!\d)"),
}


def _iban_ok(text: str) -> bool:
    value = text.replace(" ", "")
    if not 15 <= len(value) <= 34:
        return False
    moved = value[4:] + value[:4]
    digits = "".join(str(int(char, 36)) for char in moved)
    return int(digits) % 97 == 1


def _phone_ok(text: str) -> bool:
    return 7 <= sum(char.isdigit() for char in text) <= 15


def find_matches(document: EditorDocument, kinds: list[str], terms: list[str], pages: list[int] | None = None, *, match_case: bool = False) -> list[Match]:
    """Fundstellen der gewählten Muster und Begriffe (in der Reihenfolge der Seiten)."""
    chosen = range(document.page_count) if pages is None else sorted({p for p in pages if 0 <= p < document.page_count})
    found: list[Match] = []
    for page in chosen:
        with PDFIUM_LOCK:
            text = document.textpage(page).get_text_range()
        spans: list[tuple[int, int, str]] = []
        for kind in kinds:
            regex = _REGEX.get(kind)
            if regex is None:
                continue
            for hit in regex.finditer(text):
                value = hit.group(0)
                if (kind == "iban" and not _iban_ok(value)) or (kind == "phone" and not _phone_ok(value)):
                    continue
                spans.append((hit.start(), hit.end(), kind))
        for term in terms:
            term = term.strip()
            if not term:
                continue
            for hit in re.finditer(re.escape(term), text, 0 if match_case else re.IGNORECASE):
                spans.append((hit.start(), hit.end(), "term"))
        spans.sort()
        last_end = -1
        for start, end, kind in spans:
            if start < last_end:
                continue  # überlappende Treffer nur einmal
            last_end = end
            rects = textlayer.rects(document, page, start, end - start)
            if rects:
                found.append(Match(page, kind, [normalize(r) for r in rects], text[start:end].replace("\r", " ").replace("\n", " ")))
    return found


# --- Schwärzen --------------------------------------------------------------------------------------------------------
def apply_marks(document: EditorDocument, history: History, marks: list[Mark], *, fill: tuple[int, int, int] = (0, 0, 0)) -> RedactResult:
    document.ensure_editable()
    by_page: dict[int, list[Rect]] = {}
    for mark in marks:
        rect = normalize(mark.rect)
        if 0 <= mark.page < document.page_count and rect[2] - rect[0] > 0.5 and rect[3] - rect[1] > 0.5:
            by_page.setdefault(mark.page, []).append(rect)
    result = RedactResult(areas=sum(len(rects) for rects in by_page.values()))
    if not by_page:
        return result
    pdf = document.pdf
    color = tuple(value / 255.0 for value in fill)
    title = "Schwärzen"
    with record(document, history, title, pages=tuple(sorted(by_page))) as rec:
        rec.root(("/AcroForm",))
        widgets: set = set()
        for page_index, rects in sorted(by_page.items()):
            page = rec.page(page_index)
            rec.object(page, ("/Thumb",))
            try:
                _redact_holder(pdf, page, rects, IDENTITY, result, 0, set(), page_holder=True)
            except _Unsafe as exc:
                _rasterize(document, page_index, page, rects, color)
                result.rasterized.append(page_index)
                result.notes.append(f"Seite {page_index + 1}: {exc} – die Seite wurde als Bild geschwärzt.")
            else:
                _cover(pdf, page, rects, color)
            result.annotations += _drop_annotations(page, rects, widgets)
            if "/Thumb" in page:
                del page["/Thumb"]
        if widgets:
            from .flatten import _remove_fields

            _remove_fields(pdf, rec, widgets)
        _strip_structure(pdf, rec, {pdf.pages[i].obj.objgen for i in by_page})
        # Prüfung mit PDFium: in keinem Bereich darf noch ein Zeichen liegen
        document.touch()
        leftovers = [index for index, rects in sorted(by_page.items()) if index not in result.rasterized and _chars_inside(document, index, rects)]
        for index in leftovers:
            page = document.pdf.pages[index].obj
            _rasterize(document, index, page, by_page[index], color)
            result.rasterized.append(index)
            result.notes.append(f"Seite {index + 1}: Text ließ sich nicht sicher entfernen – die Seite wurde als Bild geschwärzt.")
        if leftovers:
            document.touch()
            still = [index for index in leftovers if _chars_inside(document, index, by_page[index])]
            if still:
                raise EditorError("Die Schwärzung ließ sich nicht überprüfen. Es wurde nichts geändert.")
    result.rasterized.sort()
    return result


# --- Inhalt einer Seite bzw. eines Formular-XObjects ------------------------------------------------------------------
def _redact_holder(pdf: pikepdf.Pdf, holder, rects: list[Rect], outer, result: RedactResult, depth: int, stack: set, *, page_holder: bool) -> bool:
    """Inhalt von ``holder`` (Seite oder Formular-Kopie) bearbeiten. ``outer`` bildet den Raum des
    Inhalts auf die Seite ab. Liefert, ob sich etwas geändert hat."""
    content = PageContent(pdf, holder, page_fonts(holder))
    replacements: dict[int, list] = {}
    removed: set[int] = set()
    changed = False
    # Text
    for show in content.shows:
        new = _redact_show(content, show, rects, outer, result)
        if new is not None:
            replacements[show.index] = new
            changed = True
    # Grafiken, die ganz im Bereich liegen
    for path in content.paths:
        if path.clip:
            continue
        box = _path_box(content.instructions[path.start : path.index], mul(path.ctm, outer))
        if box is not None and any(_inside(box, rect) for rect in rects):
            removed.update(range(path.start, path.index + 1))
            result.paths += 1
            changed = True
    # Bilder und Formulare
    xobjects = page_xobjects(holder)
    new_entries: dict[str, pikepdf.Object] = {}
    for op in content.images:
        matrix = mul(op.ctm, outer)
        if op.kind == "inline":
            if any(intersects(_unit_box(matrix), rect) for rect in rects):
                raise _Unsafe("ein eingebettetes Inline-Bild")
            continue
        obj = xobjects.get(op.name)
        if obj is None:
            continue
        if op.kind == "image":
            if not any(intersects(_unit_box(matrix), rect) for rect in rects):
                continue
            new_entries[op.name] = _redact_image(pdf, obj, matrix, rects)
            result.images += 1
            changed = True
        elif op.kind == "form":
            form_matrix = tuple(_num(v) for v in obj.get("/Matrix", [1, 0, 0, 1, 0, 0]))
            full = mul(form_matrix, matrix)
            bbox = _bbox_box(obj, full)
            if bbox is not None and not any(intersects(bbox, rect) for rect in rects):
                continue
            if depth >= FORM_DEPTH or obj.objgen in stack:
                raise _Unsafe("verschachtelte Formular-Objekte")
            copy = _copy_form(pdf, obj)
            if _redact_holder(pdf, copy, rects, full, result, depth + 1, stack | {obj.objgen}, page_holder=False):
                new_entries[op.name] = copy
                changed = True
    if not changed:
        return False
    instructions = []
    for index, ins in enumerate(content.instructions):
        if index in removed:
            continue
        if index in replacements:
            instructions.extend(replacements[index])
            continue
        instructions.append(_strip_alternates(ins))
    data = pikepdf.unparse_content_stream(instructions)
    if page_holder:
        holder.Contents = pdf.make_stream(data)
        if new_entries:
            resources = own_resources(holder, pdf, "/XObject")
            for name, obj in new_entries.items():
                resources.XObject[name] = obj
    else:
        holder.write(data)
        if new_entries:
            resources = holder.get("/Resources")
            fresh = Dictionary({key: value for key, value in resources.items()}) if isinstance(resources, Dictionary) else Dictionary()
            xobjects_dict = fresh.get("/XObject")
            fresh.XObject = Dictionary({key: value for key, value in xobjects_dict.items()}) if isinstance(xobjects_dict, Dictionary) else Dictionary()
            for name, obj in new_entries.items():
                fresh.XObject[name] = obj
            holder.Resources = fresh
    return True


def _redact_show(content: PageContent, show, rects: list[Rect], outer, result: RedactResult):
    """Neue Anweisungen für einen Textoperator ohne die Glyphen in den Bereichen – oder ``None``."""
    ins = content.instructions[show.index]
    state = show.state
    if state.size == 0 or state.hscale == 0:
        return None
    codec = content.codec(state.font)
    full = mul(show.tm, mul(show.ctm, outer))
    if codec is None or not codec.editable:
        # Breiten unbekannt: grob schätzen; berührt der Operator einen Bereich, fällt die Seite auf Bild zurück
        width = max(1, len(show.raw)) * 0.6 * state.size * state.hscale
        box = _transform_box((0.0, state.rise - 0.25 * state.size, width, state.rise + state.size), full)
        if any(intersects(box, rect) for rect in rects):
            raise _Unsafe("Text in einer Schrift, deren Zeichenbreiten unbekannt sind")
        return None
    ascent, descent = _metrics(codec)
    items = list(ins.operands[0]) if show.operator == "TJ" and ins.operands else [ins.operands[-1] if ins.operands else pikepdf.String(b"")]
    x = 0.0
    out: list = []
    current = bytearray()
    removed = 0
    size, hscale = state.size, state.hscale
    for item in items:
        if isinstance(item, pikepdf.String):
            for code in codec.codes(bytes(item)):
                glyph = codec.width(code) / 1000.0 * size
                spacing = state.char_spacing + (state.word_spacing if code == b" " and not codec.two_byte else 0.0)
                advance = (glyph + spacing) * hscale
                box = _transform_box((x, state.rise + descent * size, x + max(glyph * hscale, 0.1), state.rise + ascent * size), full)
                if code.strip(b" ") and any(_overlap(box, rect) for rect in rects):
                    if current:
                        out.append(pikepdf.String(bytes(current)))
                        current = bytearray()
                    out.append(-advance * 1000.0 / (size * hscale))
                    removed += 1
                else:
                    current += code
                x += advance
        else:
            shift = _num(item)
            if current:
                out.append(pikepdf.String(bytes(current)))
                current = bytearray()
            out.append(shift)
            x -= shift / 1000.0 * size * hscale
    if not removed:
        return None
    if current:
        out.append(pikepdf.String(bytes(current)))
    result.chars += removed
    merged: list = []
    for item in out:
        if not isinstance(item, pikepdf.String) and merged and not isinstance(merged[-1], pikepdf.String):
            merged[-1] = merged[-1] + item
        else:
            merged.append(item)
    array = Array([round(item, 3) if not isinstance(item, pikepdf.String) else item for item in merged])
    new = []
    if show.operator == '"' and len(ins.operands) == 3:
        new.append(pikepdf.ContentStreamInstruction([ins.operands[0]], Operator("Tw")))
        new.append(pikepdf.ContentStreamInstruction([ins.operands[1]], Operator("Tc")))
    if show.operator in ("'", '"'):
        new.append(pikepdf.ContentStreamInstruction([], Operator("T*")))
    new.append(pikepdf.ContentStreamInstruction([array], Operator("TJ")))
    return new


def _metrics(codec) -> tuple[float, float]:
    ascent, descent = 0.85, -0.25
    descriptor = codec.descriptor
    if isinstance(descriptor, Dictionary):
        try:
            ascent = max(0.5, min(1.5, float(descriptor.get("/Ascent", 850)) / 1000.0))
            descent = min(-0.05, max(-0.6, float(descriptor.get("/Descent", -250)) / 1000.0))
        except (TypeError, ValueError):
            pass
    return ascent, descent


def _overlap(box: Rect, rect: Rect) -> bool:
    return min(box[2], rect[2]) - max(box[0], rect[0]) >= MIN_OVERLAP and min(box[3], rect[3]) - max(box[1], rect[1]) >= MIN_OVERLAP


def _inside(box: Rect, rect: Rect) -> bool:
    return box[0] >= rect[0] - 0.5 and box[1] >= rect[1] - 0.5 and box[2] <= rect[2] + 0.5 and box[3] <= rect[3] + 0.5


def _transform_box(box: Rect, matrix) -> Rect:
    points = [apply(matrix, x, y) for x in (box[0], box[2]) for y in (box[1], box[3])]
    return (min(p[0] for p in points), min(p[1] for p in points), max(p[0] for p in points), max(p[1] for p in points))


def _unit_box(matrix) -> Rect:
    return _transform_box((0.0, 0.0, 1.0, 1.0), matrix)


def _bbox_box(form: pikepdf.Stream, matrix) -> Rect | None:
    try:
        bbox = normalize(tuple(float(v) for v in form.BBox))
    except (AttributeError, TypeError, ValueError):
        return None
    return _transform_box(bbox, matrix)


def _path_box(instructions, matrix) -> Rect | None:
    points: list[tuple[float, float]] = []
    for ins in instructions:
        if isinstance(ins, pikepdf.ContentStreamInlineImage):
            continue
        op = str(ins.operator)
        values = [_num(v) for v in ins.operands]
        if op == "re" and len(values) == 4:
            x, y, w, h = values
            points += [(x, y), (x + w, y + h)]
        elif op in PATH_BUILD and values:
            points += [(values[i], values[i + 1]) for i in range(0, len(values) - 1, 2)]
    if not points:
        return None
    mapped = [apply(matrix, x, y) for x, y in points]
    return (min(p[0] for p in mapped), min(p[1] for p in mapped), max(p[0] for p in mapped), max(p[1] for p in mapped))


def _strip_alternates(ins):
    """Ersatztexte (``/ActualText``, ``/Alt``, ``/E``) aus markiertem Inhalt entfernen."""
    if isinstance(ins, pikepdf.ContentStreamInlineImage) or str(ins.operator) != "BDC" or len(ins.operands) != 2:
        return ins
    props = ins.operands[1]
    if not isinstance(props, Dictionary) or not any(key in props for key in ("/ActualText", "/Alt", "/E")):
        return ins
    fresh = Dictionary({key: value for key, value in props.items() if key not in ("/ActualText", "/Alt", "/E")})
    return pikepdf.ContentStreamInstruction([ins.operands[0], fresh], Operator("BDC"))


def _copy_form(pdf: pikepdf.Pdf, form: pikepdf.Stream) -> pikepdf.Stream:
    copy = pdf.make_stream(form.read_bytes())
    for key, value in form.items():
        if key not in ("/Length", "/Filter", "/DecodeParms", "/DL"):
            copy[key] = value
    return copy


# --- Bilder ------------------------------------------------------------------------------------------------------------
def _redact_image(pdf: pikepdf.Pdf, image: pikepdf.Stream, matrix, rects: list[Rect]) -> pikepdf.Stream:
    """Neues Bildobjekt mit geschwärzten Bildpunkten (und Maske). Wirft ``_Unsafe``."""
    if bool(image.get("/ImageMask", False)) or "/Mask" in image or "/Decode" in image:
        raise _Unsafe("ein Bild mit Maske")
    try:
        picture = pikepdf.PdfImage(image).as_pil_image()
    except Exception as exc:  # noqa: BLE001 - z. B. JBIG2
        raise _Unsafe("ein Bild, das sich nicht bearbeiten lässt") from exc
    width, height = picture.size
    if picture.mode == "P":
        picture = picture.convert("RGB")
    if picture.mode not in ("1", "L", "RGB", "CMYK"):
        raise _Unsafe("ein Bild in einem besonderen Farbraum")
    polygons = _pixel_polygons(matrix, rects, width, height)
    from PIL import ImageDraw

    picture = picture.copy()
    draw = ImageDraw.Draw(picture)
    black = {"1": 0, "L": 0, "RGB": (0, 0, 0), "CMYK": (0, 0, 0, 255)}[picture.mode]
    for polygon in polygons:
        draw.polygon(polygon, fill=black)
    original_filter = image.get("/Filter")
    jpeg = original_filter == Name.DCTDecode or (isinstance(original_filter, Array) and Name.DCTDecode in list(original_filter))
    new = _encode_image(pdf, picture, jpeg)
    smask = image.get("/SMask")
    if isinstance(smask, pikepdf.Stream):
        try:
            mask = pikepdf.PdfImage(smask).as_pil_image().convert("L").copy()
        except Exception as exc:  # noqa: BLE001
            raise _Unsafe("eine Transparenzmaske, die sich nicht bearbeiten lässt") from exc
        mask_draw = ImageDraw.Draw(mask)
        for polygon in _pixel_polygons(matrix, rects, *mask.size):
            mask_draw.polygon(polygon, fill=255)  # dort deckend: die Abdeckung zeigt, nicht die Form
        new.SMask = _encode_image(pdf, mask, False)
    for key in ("/Interpolate", "/Intent"):
        if key in image:
            new[key] = image[key]
    return new


def _pixel_polygons(matrix, rects: list[Rect], width: int, height: int) -> list[list[tuple[float, float]]]:
    """Bereiche (Seitenkoordinaten) → Vielecke in Bildpunkten (Zeile 0 oben)."""
    try:
        inverse = invert(matrix)
    except ValueError as exc:
        raise _Unsafe("ein Bild ohne Fläche") from exc
    polygons = []
    for rect in rects:
        corners = [apply(inverse, x, y) for x, y in ((rect[0], rect[1]), (rect[2], rect[1]), (rect[2], rect[3]), (rect[0], rect[3]))]
        polygons.append([(u * width, (1.0 - v) * height) for u, v in corners])
    return polygons


def _encode_image(pdf: pikepdf.Pdf, picture, jpeg: bool) -> pikepdf.Stream:
    mode = picture.mode
    space = {"1": Name.DeviceGray, "L": Name.DeviceGray, "RGB": Name.DeviceRGB, "CMYK": Name.DeviceCMYK}[mode]
    if jpeg and mode in ("L", "RGB"):
        buffer = io.BytesIO()
        picture.save(buffer, "JPEG", quality=92)
        return pdf.make_stream(buffer.getvalue(), Type=Name.XObject, Subtype=Name.Image, Width=picture.width, Height=picture.height, ColorSpace=space, BitsPerComponent=8, Filter=Name.DCTDecode)
    data = picture.tobytes()
    return pdf.make_stream(zlib.compress(data, 6), Type=Name.XObject, Subtype=Name.Image, Width=picture.width, Height=picture.height, ColorSpace=space, BitsPerComponent=1 if mode == "1" else 8, Filter=Name.FlateDecode)


# --- Abdecken, Anmerkungen, Strukturbaum ----------------------------------------------------------------------------
def _cover(pdf: pikepdf.Pdf, page, rects: list[Rect], color) -> None:
    ops = [f"{fmt(color[0])} {fmt(color[1])} {fmt(color[2])} rg"]
    ops += [f"{fmt(r[0])} {fmt(r[1])} {fmt(r[2] - r[0])} {fmt(r[3] - r[1])} re f" for r in rects]
    append_content(pdf, page, "\n".join(ops).encode("latin-1"))


def _drop_annotations(page, rects: list[Rect], widgets: set) -> int:
    annots = page.get("/Annots")
    if not isinstance(annots, Array):
        return 0
    kept, dropped = [], set()
    for annot in annots:
        if isinstance(annot, Dictionary) and annot.get("/Subtype") != Name.Popup:
            try:
                rect = normalize(tuple(float(v) for v in annot.Rect))
            except (AttributeError, TypeError, ValueError):
                rect = None
            if rect is not None and any(intersects(rect, mark) for mark in rects):
                key = annot.objgen if annot.is_indirect else id(annot)
                dropped.add(key)
                if annot.get("/Subtype") == Name.Widget:
                    widgets.add(key)
                continue
        kept.append(annot)
    if not dropped:
        return 0
    kept = [a for a in kept if not (isinstance(a, Dictionary) and a.get("/Subtype") == Name.Popup and isinstance(a.get("/Parent"), Dictionary) and a.Parent.objgen in dropped)]
    if kept:
        page.Annots = Array(kept)
    else:
        del page["/Annots"]
    return len(dropped)


def _strip_structure(pdf: pikepdf.Pdf, rec, pages: set) -> None:
    """Ersatztexte im Strukturbaum für die geschwärzten Seiten entfernen (Einträge vorher gemerkt)."""
    root = pdf.Root.get("/StructTreeRoot")
    if not isinstance(root, Dictionary):
        return
    stack, seen, visited = [root.get("/K")], set(), 0
    while stack and visited < 50_000:
        node = stack.pop()
        if isinstance(node, Array):
            stack.extend(list(node))
            continue
        if not isinstance(node, Dictionary):
            continue
        key = node.objgen if node.is_indirect else id(node)
        if key in seen:
            continue
        seen.add(key)
        visited += 1
        page = node.get("/Pg")
        on_page = isinstance(page, Dictionary) and page.objgen in pages
        if (on_page or page is None) and any(k in node for k in ("/Alt", "/ActualText", "/E")):
            rec.object(node, ("/Alt", "/ActualText", "/E"))
            for k in ("/Alt", "/ActualText", "/E"):
                if k in node:
                    del node[k]
        stack.append(node.get("/K"))


# --- Prüfung und Rückfall: Seite als Bild --------------------------------------------------------------------------
def _chars_inside(document: EditorDocument, index: int, rects: list[Rect]) -> bool:
    with PDFIUM_LOCK:
        textpage = document.textpage(index)
        for i in range(textpage.count_chars()):
            box = normalize(textpage.get_charbox(i, loose=False))
            if box[2] - box[0] <= 0 and box[3] - box[1] <= 0:
                continue
            if not textpage.get_text_range(i, 1).strip():
                continue
            if any(_overlap(box, rect) for rect in rects):
                return True
    return False


def _rasterize(document: EditorDocument, index: int, page, rects: list[Rect], color) -> None:
    """Seite (mit den Abdeckungen, ohne Anmerkungen) als Bild rendern und ihren Inhalt ersetzen."""
    pdf = document.pdf
    _cover(pdf, page, rects, color)
    document.touch()
    geo = document.geometry(index)
    crop = geo.crop
    with PDFIUM_LOCK:
        view = document.view()
        pdf_page = view[index]
        try:
            scale = RASTER_DPI / 72.0
            bitmap = pdf_page.render(scale=scale, rotation=(360 - geo.rotation) % 360, may_draw_forms=False, draw_annots=False)
            picture = bitmap.to_pil().convert("RGB")
            bitmap.close()
        finally:
            pdf_page.close()
    image = _encode_image(pdf, picture, True)
    width, height = crop[2] - crop[0], crop[3] - crop[1]
    page.Resources = Dictionary(XObject=Dictionary(PTRedactPage=image))
    page.Contents = pdf.make_stream(f"q {fmt(width)} 0 0 {fmt(height)} {fmt(crop[0])} {fmt(crop[1])} cm /PTRedactPage Do Q".encode("latin-1"))


__all__ = ["Mark", "Match", "PATTERNS", "PATTERN_LABELS", "RedactResult", "apply_marks", "find_matches"]
