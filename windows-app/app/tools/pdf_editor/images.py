"""Bilder bearbeiten: auswählen, verschieben, skalieren, drehen, löschen, ersetzen und neue Bilder
(PNG/JPEG, auch mit Transparenz) einfügen.

Ein »Bild« ist auf der obersten Ebene der Seite gezeichnet: ``Do`` eines Bild-XObjects, ein
Inline-Bild oder ein Formular-XObject, das nur aus Bildern besteht (so betten z. B. ReportLab und
manche Office-Programme Logos ein). Bilder in Formularen mit weiterem Inhalt bleiben unangetastet.

Geändert wird nur die Platzierung im Inhaltsstrom (eine Matrix um den ``Do``-Aufruf) bzw. der
Aufruf selbst – die Bilddaten bleiben unverändert (beim Ersetzen kommt ein neues Bild hinzu).
Wie beim Text gilt: neue Inhaltsströme statt Änderungen in place, alles über ``commands.record``.
Die Ebene (Vorder-/Hintergrund) lässt sich nur für Bilder ändern, die PDF Tool eingefügt hat.
"""

from __future__ import annotations

import ctypes
import io
import math
import os
import zlib
from dataclasses import dataclass
from pathlib import Path

import pikepdf
from pikepdf import Name, Operator

from pdfium_lock import PDFIUM_LOCK

from . import commands
from .commands import History
from .content import ImageOp, Matrix, PageContent, append_content, fmt, invert, mul, page_fonts
from .document import EditorDocument
from .errors import UnsupportedEdit
from .geometry import Rect, normalize

IMAGE_PREFIX = "/PTI"  # Ressourcennamen der von PDF Tool eingefügten Bilder
MAX_PIXELS = 60_000_000  # größere Bilder werden abgelehnt (Speicher)
FORMATS = ("PNG", "JPEG")


@dataclass(frozen=True)
class ImageItem:
    index: int  # Nummer unter den Bildern der Seite (Reihenfolge im Inhalt)
    bounds: Rect  # Seitenkoordinaten, achsenparallel
    quad: tuple[tuple[float, float], ...]  # Ecken (unten links, unten rechts, oben rechts, oben links)
    pixels: tuple[int, int]
    kind: str  # image, inline, form
    ours: bool  # von PDF Tool eingefügt (Ebene änderbar)
    editable: bool
    reason: str = ""


# --- Lesen ------------------------------------------------------------------------------------------------
def list_images(document: EditorDocument, page: int) -> list[ImageItem]:
    """Bilder der Seite – mit Zuordnung zum Inhaltsstrom (sonst nur anzeigen, nicht bearbeiten)."""
    import pypdfium2.raw as r

    found = []
    with PDFIUM_LOCK:
        pdf_page = document.page_object(page)
        for i in range(r.FPDFPage_CountObjects(pdf_page.raw)):
            obj = r.FPDFPage_GetObject(pdf_page.raw, i)
            kind = r.FPDFPageObj_GetType(obj)
            if kind == r.FPDF_PAGEOBJ_IMAGE:
                found.append(("image", obj, _pixels(obj)))
            elif kind == r.FPDF_PAGEOBJ_FORM:
                inner = _only_images(obj)
                found.append(("form", obj, inner))
        items = []
        for number, (kind, obj, pixels) in enumerate(found):
            left, bottom, right, top = (ctypes.c_float() for _ in range(4))
            r.FPDFPageObj_GetBounds(obj, left, bottom, right, top)
            quad = r.FS_QUADPOINTSF()
            if r.FPDFPageObj_GetRotatedBounds(obj, quad):
                corners = ((quad.x1, quad.y1), (quad.x2, quad.y2), (quad.x3, quad.y3), (quad.x4, quad.y4))
            else:
                corners = ((left.value, bottom.value), (right.value, bottom.value), (right.value, top.value), (left.value, top.value))
            items.append((number, kind, normalize((left.value, bottom.value, right.value, top.value)), tuple((round(x, 3), round(y, 3)) for x, y in corners), pixels))
    content, reason = _content(document, page)
    ops = content.images if content is not None else []
    mapped = content is not None and len(ops) == len(items)
    if content is not None and not mapped:
        reason = "Die Bildstruktur der Seite lässt keine Änderung zu."
    result = []
    for number, kind, bounds, quad, pixels in items:
        op = ops[number] if mapped else None
        if kind == "form" and pixels is None:
            continue  # Formular mit anderem Inhalt (Text, Grafik) – kein Bild
        if op is not None and op.kind == "inline":
            kind = "inline"
        editable = op is not None and not document.read_only and (op.kind in ("image", "inline") or kind == "form")
        why = "" if editable else (document.read_only_reason or reason or "Dieses Bild lässt sich nicht bearbeiten.")
        result.append(ImageItem(number, bounds, quad, pixels or (0, 0), kind, bool(op is not None and op.name.startswith(IMAGE_PREFIX)), editable, why))
    return result


def _pixels(obj) -> tuple[int, int]:
    import pypdfium2.raw as r

    width, height = ctypes.c_uint(), ctypes.c_uint()
    if r.FPDFImageObj_GetImagePixelSize(obj, width, height):
        return (int(width.value), int(height.value))
    return (0, 0)


def _only_images(form, depth: int = 0) -> tuple[int, int] | None:
    """Pixelgröße des (ersten) Bildes, wenn ein Formular nur aus Bildern besteht – sonst ``None``."""
    import pypdfium2.raw as r

    count = r.FPDFFormObj_CountObjects(form)
    if count <= 0 or depth > 4:
        return None
    pixels = None
    for i in range(count):
        inner = r.FPDFFormObj_GetObject(form, i)
        kind = r.FPDFPageObj_GetType(inner)
        if kind == r.FPDF_PAGEOBJ_IMAGE:
            pixels = pixels or _pixels(inner)
        elif kind == r.FPDF_PAGEOBJ_FORM:
            nested = _only_images(inner, depth + 1)
            if nested is None:
                return None
            pixels = pixels or nested
        else:
            return None
    return pixels


def _content(document: EditorDocument, page: int) -> tuple[PageContent | None, str]:
    obj = document.pdf.pages[page].obj
    try:
        return PageContent(document.pdf, obj, page_fonts(obj)), ""
    except (pikepdf.PdfError, ValueError, TypeError):
        return None, "Der Inhalt der Seite lässt sich nicht sicher lesen."


def _op(document: EditorDocument, page: int, index: int) -> tuple[PageContent, ImageOp]:
    items = list_images(document, page)
    item = next((it for it in items if it.index == index), None)
    if item is None:
        raise UnsupportedEdit("Das Bild ist nicht mehr vorhanden.")
    if not item.editable:
        raise UnsupportedEdit(item.reason)
    content, reason = _content(document, page)
    if content is None:
        raise UnsupportedEdit(reason)
    return content, content.images[index]


# --- Platzierung ändern ---------------------------------------------------------------------------------------
def transform(document: EditorDocument, history: History, page: int, index: int, matrix: Matrix, *, title: str = "Bild ändern") -> None:
    """Bild mit ``matrix`` (Seitenkoordinaten, PDF-Konvention: Punkt × Matrix) umformen."""
    document.ensure_editable()
    content, op = _op(document, page, index)
    try:
        inner = mul(mul(op.ctm, matrix), invert(op.ctm))  # vor dem Zeichnen: CTM' = inner × CTM = CTM × matrix
    except ValueError as exc:
        raise UnsupportedEdit("Das Bild hat keine Fläche und lässt sich nicht umformen.") from exc
    with commands.record(document, history, title, pages=(page,)) as rec:
        rec.page(page)
        _apply_inner(content, op, inner)
        content.commit()


def _apply_inner(content: PageContent, op: ImageOp, inner: Matrix) -> None:
    """``inner`` direkt vor dem Zeichnen anwenden: vorhandene Klammer ``q … cm <Bild> Q`` nutzen,
    sonst eine neue um den Aufruf legen (die Verschachtelung wächst nicht bei jeder Änderung)."""
    ins = content.instructions
    i = op.index
    wrapped = i >= 2 and i + 1 < len(ins) and _is(ins[i - 2], "q") and _is(ins[i - 1], "cm") and len(ins[i - 1].operands) == 6 and _is(ins[i + 1], "Q")
    if wrapped:
        old = tuple(float(v) for v in ins[i - 1].operands)
        ins[i - 1] = _cm(mul(inner, old))
        return
    ins[i : i + 1] = [pikepdf.ContentStreamInstruction([], Operator("q")), _cm(inner), ins[i], pikepdf.ContentStreamInstruction([], Operator("Q"))]


def _is(ins, operator: str) -> bool:
    return not isinstance(ins, pikepdf.ContentStreamInlineImage) and str(ins.operator) == operator


def _cm(m: Matrix):
    return pikepdf.ContentStreamInstruction([round(v, 6) for v in m], Operator("cm"))


def translate(dx: float, dy: float) -> Matrix:
    return (1.0, 0.0, 0.0, 1.0, dx, dy)


def move_by(document: EditorDocument, history: History, page: int, index: int, dx: float, dy: float) -> None:
    transform(document, history, page, index, translate(dx, dy), title="Bild verschieben")


def fit(document: EditorDocument, history: History, page: int, index: int, bounds: Rect) -> None:
    """Bild auf neue (achsenparallele) Grenzen bringen – skalieren und verschieben."""
    item = next((it for it in list_images(document, page) if it.index == index), None)
    if item is None:
        raise UnsupportedEdit("Das Bild ist nicht mehr vorhanden.")
    x0, y0, x1, y1 = item.bounds
    nx0, ny0, nx1, ny1 = normalize(bounds)
    if min(x1 - x0, y1 - y0, nx1 - nx0, ny1 - ny0) < 0.5:
        raise UnsupportedEdit("Das Bild wäre zu klein.")
    sx, sy = (nx1 - nx0) / (x1 - x0), (ny1 - ny0) / (y1 - y0)
    matrix = mul(mul(translate(-x0, -y0), (sx, 0.0, 0.0, sy, 0.0, 0.0)), translate(nx0, ny0))
    transform(document, history, page, index, matrix, title="Bildgröße ändern")


def rotate_by(document: EditorDocument, history: History, page: int, index: int, degrees: float) -> None:
    """Um die Mitte drehen (positiv = gegen den Uhrzeigersinn, wie in PDF)."""
    item = next((it for it in list_images(document, page) if it.index == index), None)
    if item is None:
        raise UnsupportedEdit("Das Bild ist nicht mehr vorhanden.")
    cx, cy = (item.bounds[0] + item.bounds[2]) / 2, (item.bounds[1] + item.bounds[3]) / 2
    rad = math.radians(degrees)
    cos, sin = round(math.cos(rad), 12), round(math.sin(rad), 12)
    matrix = mul(mul(translate(-cx, -cy), (cos, sin, -sin, cos, 0.0, 0.0)), translate(cx, cy))
    transform(document, history, page, index, matrix, title="Bild drehen")


# --- Löschen, Ersetzen ----------------------------------------------------------------------------------------
def delete(document: EditorDocument, history: History, page: int, index: int) -> None:
    document.ensure_editable()
    content, op = _op(document, page, index)
    ins = content.instructions
    i = op.index
    with commands.record(document, history, "Bild löschen", pages=(page,)) as rec:
        obj = rec.page(page)
        if i >= 2 and i + 1 < len(ins) and _is(ins[i - 2], "q") and _is(ins[i - 1], "cm") and _is(ins[i + 1], "Q"):
            del ins[i - 2 : i + 2]
        else:
            del ins[i]
        content.commit()
        if op.name:
            _drop_unused_xobject(document.pdf, obj, op.name)


def _drop_unused_xobject(pdf: pikepdf.Pdf, page: pikepdf.Object, name: str) -> None:
    """XObject aus den Ressourcen der Seite nehmen, wenn kein ``Do`` der Seite es mehr nutzt."""
    for ins in pikepdf.parse_content_stream(page):
        if _is(ins, "Do") and ins.operands and str(ins.operands[0]) == name:
            return
    resources = commands.own_resources(page, pdf, "/XObject")
    if name in resources.XObject:
        del resources.XObject[name]


def replace(document: EditorDocument, history: History, page: int, index: int, path: str | os.PathLike) -> None:
    """Bild durch eine Datei ersetzen – an derselben Stelle und Ebene, im Bereich des alten Bildes
    eingepasst (Seitenverhältnis bleibt)."""
    document.ensure_editable()
    content, op = _op(document, page, index)
    pdf = document.pdf
    stream, (width, height) = image_xobject(pdf, Path(path).read_bytes())
    # Seitenverhältnis des bisherigen Platzes (Einheitsquadrat bzw. Formularbereich unter der CTM)
    old_w = math.hypot(op.ctm[0], op.ctm[1])
    old_h = math.hypot(op.ctm[2], op.ctm[3])
    unit: Matrix = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
    if op.kind == "form":
        # Das neue Bild füllt den Bereich des Formulars: Einheitsquadrat → BBox → Formularmatrix
        form = content.xobjects.get(op.name)
        try:
            bx0, by0, bx1, by1 = (float(v) for v in form.get("/BBox"))
            fx = tuple(float(v) for v in form.get("/Matrix", [1, 0, 0, 1, 0, 0]))
        except (TypeError, ValueError) as exc:
            raise UnsupportedEdit("Das Bild lässt sich nicht ersetzen.") from exc
        unit = mul((bx1 - bx0, 0.0, 0.0, by1 - by0, bx0, by0), fx)  # type: ignore[arg-type]
        whole = mul(unit, op.ctm)
        old_w, old_h = math.hypot(whole[0], whole[1]), math.hypot(whole[2], whole[3])
    if old_w < 1e-6 or old_h < 1e-6:
        raise UnsupportedEdit("Das Bild hat keine Fläche.")
    fit_w, fit_h = 1.0, 1.0
    if width / height > old_w / old_h:
        fit_h = (old_w / old_h) / (width / height)
    else:
        fit_w = (width / height) / (old_w / old_h)
    placement = mul((fit_w, 0.0, 0.0, fit_h, (1 - fit_w) / 2, (1 - fit_h) / 2), unit)
    with commands.record(document, history, "Bild ersetzen", pages=(page,)) as rec:
        obj = rec.page(page)
        name = _add_xobject(pdf, obj, stream)
        ins = content.instructions
        i = op.index
        ins[i] = pikepdf.ContentStreamInstruction([Name(name)], Operator("Do"))
        if placement != (1.0, 0.0, 0.0, 1.0, 0.0, 0.0):
            ins[i : i + 1] = [pikepdf.ContentStreamInstruction([], Operator("q")), _cm(placement), ins[i], pikepdf.ContentStreamInstruction([], Operator("Q"))]
        content.commit()
        if op.name:
            _drop_unused_xobject(pdf, obj, op.name)


# --- Einfügen, Ebene --------------------------------------------------------------------------------------------
def insert(document: EditorDocument, history: History, page: int, path: str | os.PathLike, view_rect: Rect) -> int:
    """Bild einfügen. ``view_rect``: Bereich in der Anzeige (Punkte, Ursprung oben links) – das
    Bild steht dort aufrecht, auch auf gedrehten Seiten. Liefert die Nummer des neuen Bildes."""
    document.ensure_editable()
    pdf = document.pdf
    stream, _pixels_ = image_xobject(pdf, Path(path).read_bytes())
    u0, v0, u1, v1 = normalize(view_rect)
    if u1 - u0 < 1 or v1 - v0 < 1:
        raise UnsupportedEdit("Der Bereich für das Bild ist zu klein.")
    geo = document.geometry(page)
    ox, oy = geo.to_page(u0, v1)  # untere linke Ecke in der Anzeige
    rad = math.radians(geo.rotation)
    ux, uy = round(math.cos(rad), 12), round(math.sin(rad), 12)
    w, h = u1 - u0, v1 - v0
    placement = (w * ux, w * uy, -h * uy, h * ux, ox, oy)
    with commands.record(document, history, "Bild einfügen", pages=(page,)) as rec:
        obj = rec.page(page)
        name = _add_xobject(pdf, obj, stream)
        append_content(pdf, obj, f"{' '.join(fmt(v) for v in placement)} cm {name} Do".encode("latin-1"))
    content, _reason = _content(document, page)
    return len(content.images) - 1 if content is not None else 0


def arrange(document: EditorDocument, history: History, page: int, index: int, front: bool) -> None:
    """Ein von PDF Tool eingefügtes Bild ganz nach vorn oder ganz nach hinten legen."""
    document.ensure_editable()
    content, op = _op(document, page, index)
    if not op.name.startswith(IMAGE_PREFIX):
        raise UnsupportedEdit("Die Ebene lässt sich nur für eingefügte Bilder ändern.")
    ins = content.instructions
    i = op.index
    if not (i >= 2 and i + 1 < len(ins) and _is(ins[i - 2], "q") and _is(ins[i - 1], "cm") and _is(ins[i + 1], "Q")):
        raise UnsupportedEdit("Die Ebene dieses Bildes lässt sich nicht ändern.")
    group = ins[i - 2 : i + 2]
    with commands.record(document, history, "In den Vordergrund" if front else "In den Hintergrund", pages=(page,)) as rec:
        obj = rec.page(page)
        del ins[i - 2 : i + 2]
        if front:
            content.commit()
            append_content(document.pdf, obj, pikepdf.unparse_content_stream(group[1:3]))
        else:
            ins[0:0] = group
            content.commit()


def _add_xobject(pdf: pikepdf.Pdf, page: pikepdf.Object, stream: pikepdf.Stream) -> str:
    xobjects = commands.own_resources(page, pdf, "/XObject").XObject
    n = 1
    while f"{IMAGE_PREFIX}{n}" in xobjects:
        n += 1
    name = f"{IMAGE_PREFIX}{n}"
    xobjects[name] = stream
    return name


# --- Bilddateien ------------------------------------------------------------------------------------------------
def image_xobject(pdf: pikepdf.Pdf, data: bytes) -> tuple[pikepdf.Stream, tuple[int, int]]:
    """PNG/JPEG → Bild-XObject. JPEG (RGB/Graustufen, ohne Drehung laut EXIF) bleibt unverändert,
    sonst verlustfrei (Flate); Transparenz wird zur weichen Maske (``/SMask``)."""
    from PIL import Image, ImageOps, UnidentifiedImageError

    try:
        image = Image.open(io.BytesIO(data))
        image.load()
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise UnsupportedEdit("Die Datei ist kein lesbares Bild (PNG oder JPEG).") from exc
    if image.format not in FORMATS:
        raise UnsupportedEdit("Nur PNG- und JPEG-Bilder lassen sich einfügen.")
    width, height = image.size
    if width < 1 or height < 1 or width * height > MAX_PIXELS:
        raise UnsupportedEdit("Das Bild ist zu groß (höchstens 60 Megapixel).")
    orientation = image.getexif().get(0x0112, 1) if hasattr(image, "getexif") else 1
    if image.format == "JPEG" and image.mode in ("RGB", "L") and orientation in (None, 1):
        stream = pdf.make_stream(b"")
        stream.write(data, filter=Name.DCTDecode, type_check=False)
        _image_dict(stream, width, height, "/DeviceGray" if image.mode == "L" else "/DeviceRGB")
        return stream, (width, height)
    image = ImageOps.exif_transpose(image)
    width, height = image.size
    alpha = None
    if image.mode in ("RGBA", "LA", "PA") or (image.mode == "P" and "transparency" in image.info):
        rgba = image.convert("RGBA")
        alpha = rgba.getchannel("A")
        image = rgba.convert("RGB")
        if alpha.getextrema() == (255, 255):
            alpha = None
    elif image.mode in ("I;16", "I;16B", "I;16L", "I"):
        image = image.point(lambda value: value / 256).convert("L")
    elif image.mode not in ("RGB", "L"):
        image = image.convert("RGB")
    stream = pdf.make_stream(b"")
    stream.write(zlib.compress(image.tobytes(), 6), filter=Name.FlateDecode, type_check=False)
    _image_dict(stream, width, height, "/DeviceGray" if image.mode == "L" else "/DeviceRGB")
    if alpha is not None:
        mask = pdf.make_stream(b"")
        mask.write(zlib.compress(alpha.tobytes(), 6), filter=Name.FlateDecode, type_check=False)
        _image_dict(mask, width, height, "/DeviceGray")
        stream.SMask = mask
    return stream, (width, height)


def _image_dict(stream: pikepdf.Stream, width: int, height: int, colorspace: str) -> None:
    stream.Type = Name.XObject
    stream.Subtype = Name.Image
    stream.Width = width
    stream.Height = height
    stream.ColorSpace = Name(colorspace)
    stream.BitsPerComponent = 8
