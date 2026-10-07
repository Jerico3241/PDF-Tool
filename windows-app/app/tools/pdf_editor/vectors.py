"""Vektorobjekte (Linien, Rechtecke, Kurven, Flächen) als Objekte: auflisten, verschieben, drehen,
skalieren, löschen, umfärben, Linienstärke und Deckkraft ändern.

Ein Vektorobjekt ist ein auf der obersten Ebene gezeichneter Pfad – vom ersten Aufbau-Operator
(``m``, ``re`` …) bis zum zeichnenden Operator (``S``, ``f``, ``B`` …). PDFium legt für jeden solchen
Pfad ein Pfadobjekt in derselben Reihenfolge an; stimmt die Anzahl nicht, bleiben die Pfade der Seite
unangetastet (nur anzeigen). Pfade in Formular-XObjects, reine Zuschneidepfade (``W n``) und Pfade,
die zugleich zuschneiden (``W f``), werden nicht geändert.

Geändert wird wie bei Bildern nur die Umgebung des Pfades: eine Klammer ``q … Q`` mit Matrix (``cm``),
Farbe, Linienstärke oder Deckkraft (eigene ExtGState-Ressource) – die Pfaddaten bleiben unverändert.
Neue Inhaltsströme statt Änderungen in place, alles über ``commands.record`` (Rückgängig).
"""

from __future__ import annotations

import ctypes
import math
from dataclasses import dataclass

import pikepdf
from pikepdf import Dictionary, Name, Operator

from pdfium_lock import PDFIUM_LOCK

from . import commands
from .content import Matrix, PageContent, PathOp, invert, mul, page_fonts
from .document import EditorDocument
from .errors import UnsupportedEdit
from .geometry import Rect, normalize

MAX_PATHS = 4000  # mehr Pfade auf einer Seite (Pläne, Diagramme): nur anzeigen
BACKGROUND_SHARE = 0.85  # Flächen, die fast die ganze Seite bedecken, sind Hintergrund – kein Objekt
STATE_PREFIX = "/PTGS"  # eigene ExtGState-Ressourcen (Deckkraft)


@dataclass(frozen=True)
class PathItem:
    index: int  # Nummer unter den Pfaden der Seite (Reihenfolge im Inhalt)
    bounds: Rect  # Seitenkoordinaten (mit Linienbreite)
    stroke: tuple[int, int, int] | None  # Strichfarbe (None: kein Strich)
    fill: tuple[int, int, int] | None  # Füllfarbe (None: keine Fläche)
    width: float  # Linienstärke (Seitenpunkte, ungefähr)
    opacity: float  # Deckkraft 0…1 (Fläche bzw. Strich)
    editable: bool
    reason: str = ""


# --- Lesen ----------------------------------------------------------------------------------------------------
def list_paths(document: EditorDocument, page: int) -> list[PathItem]:
    """Sichtbare Vektorobjekte der Seite (ohne Hintergrundflächen) – mit Zuordnung zum Inhaltsstrom."""
    import pypdfium2.raw as r

    found = []
    with PDFIUM_LOCK:
        pdf_page = document.page_object(page)
        count = r.FPDFPage_CountObjects(pdf_page.raw)
        for i in range(count):
            obj = r.FPDFPage_GetObject(pdf_page.raw, i)
            if r.FPDFPageObj_GetType(obj) != r.FPDF_PAGEOBJ_PATH:
                continue
            if len(found) >= MAX_PATHS:
                return []
            left, bottom, right, top = (ctypes.c_float() for _ in range(4))
            r.FPDFPageObj_GetBounds(obj, left, bottom, right, top)
            fill_mode, stroked = ctypes.c_int(), ctypes.c_int()
            r.FPDFPath_GetDrawMode(obj, fill_mode, stroked)
            width = ctypes.c_float()
            r.FPDFPageObj_GetStrokeWidth(obj, width)
            found.append((normalize((left.value, bottom.value, right.value, top.value)), _rgba(obj, r.FPDFPageObj_GetStrokeColor) if stroked.value else None, _rgba(obj, r.FPDFPageObj_GetFillColor) if fill_mode.value else None, float(width.value)))
    content, reason = _content(document, page)
    ops = content.paths if content is not None else []
    mapped = content is not None and len(ops) == len(found)
    if content is not None and not mapped:
        reason = "Die Vektorgrafik der Seite lässt keine Änderung zu."
    geo = document.geometry(page)
    page_area = max(1.0, (geo.crop[2] - geo.crop[0]) * (geo.crop[3] - geo.crop[1]))
    result = []
    for number, (bounds, stroke, fill, width) in enumerate(found):
        if stroke is None and fill is None:
            continue  # unsichtbar
        if stroke is not None and stroke[3] == 0 and (fill is None or fill[3] == 0):
            continue
        area = (bounds[2] - bounds[0]) * (bounds[3] - bounds[1])
        if fill is not None and area >= BACKGROUND_SHARE * page_area:
            continue  # Hintergrund der Seite
        if bounds[2] < geo.crop[0] or bounds[0] > geo.crop[2] or bounds[3] < geo.crop[1] or bounds[1] > geo.crop[3]:
            continue  # außerhalb des sichtbaren Bereichs
        op = ops[number] if mapped else None
        why = ""
        if op is None:
            why = reason or "Dieses Objekt lässt sich nicht bearbeiten."
        elif op.clip:
            why = "Dieser Pfad schneidet zugleich den folgenden Inhalt zu und lässt sich nicht ändern."
        elif document.read_only:
            why = document.read_only_reason
        scale = math.sqrt(abs(op.ctm[0] * op.ctm[3] - op.ctm[1] * op.ctm[2])) if op is not None else 1.0
        alpha = (stroke[3] if stroke is not None else fill[3]) / 255.0
        result.append(PathItem(number, bounds, stroke[:3] if stroke else None, fill[:3] if fill else None, round(width * scale, 3), round(alpha, 3), not why, why))
    return result


def _rgba(obj, getter) -> tuple[int, int, int, int]:
    red, green, blue, alpha = (ctypes.c_uint() for _ in range(4))
    getter(obj, red, green, blue, alpha)
    return (red.value, green.value, blue.value, alpha.value)


def _content(document: EditorDocument, page: int) -> tuple[PageContent | None, str]:
    obj = document.pdf.pages[page].obj
    try:
        return PageContent(document.pdf, obj, page_fonts(obj)), ""
    except (pikepdf.PdfError, ValueError, TypeError):
        return None, "Der Inhalt der Seite lässt sich nicht sicher lesen."


def path_op(document: EditorDocument, page: int, index: int, content: PageContent | None = None) -> tuple[PageContent, PathOp]:
    """Inhalt der Seite und Pfad Nummer ``index`` – wirft ``UnsupportedEdit``, wenn er nicht änderbar ist."""
    item = next((it for it in list_paths(document, page) if it.index == index), None)
    if item is None:
        raise UnsupportedEdit("Das Objekt ist nicht mehr vorhanden. Bitte erneut auswählen.")
    if not item.editable:
        raise UnsupportedEdit(item.reason)
    if content is None:
        content, reason = _content(document, page)
        if content is None:
            raise UnsupportedEdit(reason)
    return content, content.paths[index]


# --- Ändern (ohne Verlauf – der Aufrufer zeichnet auf) ---------------------------------------------------------
def _is(ins, operator: str) -> bool:
    return not isinstance(ins, pikepdf.ContentStreamInlineImage) and str(ins.operator) == operator


def _op(operator: str, *operands) -> pikepdf.ContentStreamInstruction:
    return pikepdf.ContentStreamInstruction(list(operands), Operator(operator))


WRAP_STATE = ("cm", "gs", "rg", "RG", "g", "G", "k", "K", "w")  # erlaubt zwischen eigener Klammer und Pfad


def _own_wrap(content: PageContent, op: PathOp) -> int | None:
    """Position von ``q``, wenn der Pfad allein in einer Klammer ``q [Matrix/Zustand] Pfad Q`` steht."""
    ins = content.instructions
    i = op.start - 1
    while i >= 0 and not _is(ins[i], "q") and str(getattr(ins[i], "operator", "")) in WRAP_STATE:
        i -= 1
    if i >= 0 and _is(ins[i], "q") and op.index + 1 < len(ins) and _is(ins[op.index + 1], "Q"):
        return i
    return None


def _ensure_wrap(content: PageContent, op: PathOp) -> int:
    """Eigene Klammer ``q … Q`` um den Pfad (eine vorhandene wird genutzt); liefert die Position von ``q``."""
    found = _own_wrap(content, op)
    if found is not None:
        return found
    ins = content.instructions
    ins.insert(op.index + 1, _op("Q"))
    _shift_ops(content, op.index + 1, 1, skip=op)
    ins.insert(op.start, _op("q"))
    _shift_ops(content, op.start, 1, skip=op)
    op.start += 1
    op.index += 1
    return op.start - 1


def _shift_ops(content: PageContent, position: int, by: int, skip: PathOp | None = None) -> None:
    """Positionen aller Operatoren ab ``position`` verschieben (``skip`` passt der Aufrufer selbst an)."""
    for other in content.paths:
        if other is skip:
            continue
        if other.start >= position:
            other.start += by
        if other.index >= position:
            other.index += by
    for image in content.images:
        if image.index >= position:
            image.index += by
    for show in content.shows:
        if show.index >= position:
            show.index += by


def transform(content: PageContent, op: PathOp, matrix: Matrix) -> None:
    """Pfad mit ``matrix`` (Seitenkoordinaten, Punkt × Matrix) umformen."""
    try:
        inner = mul(mul(op.ctm, matrix), invert(op.ctm))
    except ValueError as exc:
        raise UnsupportedEdit("Dieses Objekt lässt sich nicht umformen.") from exc
    _ensure_wrap(content, op)
    ins = content.instructions
    # Matrix direkt vor dem Pfadaufbau (dort gilt genau die CTM des Pfades); eine eigene zusammenfassen
    before = op.start - 1
    if _is(ins[before], "cm") and len(ins[before].operands) == 6:
        old = tuple(float(v) for v in ins[before].operands)
        ins[before] = _cm(mul(inner, old))
    else:
        ins.insert(op.start, _cm(inner))
        _shift_ops(content, op.start, 1, skip=op)
        op.start += 1
        op.index += 1


def _cm(m: Matrix):
    return pikepdf.ContentStreamInstruction([round(v, 6) for v in m], Operator("cm"))


def delete(content: PageContent, op: PathOp) -> None:
    ins = content.instructions
    q = _own_wrap(content, op)
    start, end = (q, op.index + 1) if q is not None else (op.start, op.index)
    del ins[start : end + 1]
    removed = end - start + 1
    for other in content.paths:
        if other.start > end:
            other.start -= removed
            other.index -= removed
    for image in content.images:
        if image.index > end:
            image.index -= removed
    for show in content.shows:
        if show.index > end:
            show.index -= removed


def restyle(content: PageContent, op: PathOp, *, stroke: tuple[int, int, int] | None = None, fill: tuple[int, int, int] | None = None, width: float | None = None, state: str | None = None) -> None:
    """Strichfarbe, Füllfarbe, Linienstärke (Seitenpunkte) bzw. ExtGState (Deckkraft) nur für diesen Pfad."""
    q = _ensure_wrap(content, op)
    ins = content.instructions
    added = []
    if stroke is not None:
        added.append(_op("RG", *[round(v / 255.0, 4) for v in stroke]))
    if fill is not None:
        added.append(_op("rg", *[round(v / 255.0, 4) for v in fill]))
    if width is not None:
        scale = math.sqrt(abs(op.ctm[0] * op.ctm[3] - op.ctm[1] * op.ctm[2])) or 1.0
        added.append(_op("w", round(max(0.0, width) / scale, 4)))
    if state is not None:
        added.append(_op("gs", Name(state)))
    if not added:
        return
    position = op.start  # direkt vor dem Pfadaufbau (nach Matrix und früheren Zuständen dieser Klammer)
    for item in added:
        # gleiche Zustandsanweisung in der eigenen Klammer ersetzen statt anzuhäufen
        operator = str(item.operator)
        for j in range(q + 1, position):
            if str(getattr(ins[j], "operator", "")) == operator and operator != "gs":
                ins[j] = item
                break
            if operator == "gs" and _is(ins[j], "gs") and str(ins[j].operands[0]).startswith(STATE_PREFIX):
                ins[j] = item
                break
        else:
            ins.insert(position, item)
            _shift_ops(content, position, 1, skip=op)
            op.start += 1
            op.index += 1
            position += 1


def alpha_state(pdf: pikepdf.Pdf, page: pikepdf.Object, opacity: float, stroke: float | None = None) -> str:
    """Eigene ExtGState-Ressource mit dieser Deckkraft (Fläche ``opacity``, Strich ``stroke`` bzw. gleich) –
    eine vorhandene gleiche wird wiederverwendet."""
    fill_value = round(max(0.0, min(1.0, float(opacity))), 3)
    stroke_value = fill_value if stroke is None else round(max(0.0, min(1.0, float(stroke))), 3)
    states = commands.own_resources(page, pdf, "/ExtGState").ExtGState
    for name, existing in states.items():
        if str(name).startswith(STATE_PREFIX) and isinstance(existing, Dictionary) and set(existing.keys()) <= {"/Type", "/CA", "/ca"} and float(existing.get("/CA", -1)) == stroke_value and float(existing.get("/ca", -1)) == fill_value:
            return str(name)
    number = 1
    while f"{STATE_PREFIX}{number}" in states:
        number += 1
    name = f"{STATE_PREFIX}{number}"
    states[name] = pdf.make_indirect(Dictionary(Type=Name.ExtGState, CA=stroke_value, ca=fill_value))
    return name


def rotation(center: tuple[float, float], degrees: float) -> Matrix:
    """Drehung um ``center`` (Seitenkoordinaten; positiv = gegen den Uhrzeigersinn wie in PDF)."""
    cx, cy = center
    rad = math.radians(degrees)
    cos, sin = round(math.cos(rad), 12), round(math.sin(rad), 12)
    return mul(mul((1.0, 0.0, 0.0, 1.0, -cx, -cy), (cos, sin, -sin, cos, 0.0, 0.0)), (1.0, 0.0, 0.0, 1.0, cx, cy))


def scaling(anchor: tuple[float, float], sx: float, sy: float) -> Matrix:
    ax, ay = anchor
    return mul(mul((1.0, 0.0, 0.0, 1.0, -ax, -ay), (sx, 0.0, 0.0, sy, 0.0, 0.0)), (1.0, 0.0, 0.0, 1.0, ax, ay))


def snippet(content: PageContent, op: PathOp) -> list:
    """Anweisungen, die den Pfad mit seinem Zustand noch einmal zeichnen (für Kopien)."""
    ins = content.instructions
    body = list(ins[op.start : op.index + 1])
    return [_op("q"), _cm(op.ctm), *op.graphics.replay(), *body, _op("Q")]
