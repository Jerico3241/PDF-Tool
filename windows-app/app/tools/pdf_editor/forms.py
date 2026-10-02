"""Formulare (AcroForm) ausfüllen: Textfelder, Kontrollkästchen, Optionsfelder, Auswahl- und
Listenfelder – Werte setzen und das Erscheinungsbild jedes Widgets neu erzeugen, damit der Wert in
jedem Programm gleich aussieht (auch mit Zeichen außerhalb von WinAnsi, dann mit eingebetteter
Teilmenge einer Systemschrift).

Schreibgeschützte Felder, Passwort- und Signaturfelder werden nicht geändert. PDF-JavaScript
(Berechnungen, Formate, Prüfungen) wird nie ausgeführt. XFA-Formulare lassen sich nur über ihren
AcroForm-Teil ausfüllen – die Oberfläche weist darauf hin.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import pikepdf
from pikepdf import Array, Dictionary, Name, String

from . import commands
from .commands import History
from .content import fmt
from .document import EditorDocument
from .errors import UnsupportedEdit
from .geometry import Rect, normalize

TEXT, CHECKBOX, RADIO, COMBO, LIST, SIGNATURE, BUTTON = "text", "checkbox", "radio", "combo", "list", "signature", "button"
FLAG_READ_ONLY, FLAG_REQUIRED = 1, 2
FLAG_MULTILINE, FLAG_PASSWORD, FLAG_COMB = 1 << 12, 1 << 13, 1 << 24
FLAG_RADIO, FLAG_PUSHBUTTON, FLAG_COMBO = 1 << 15, 1 << 16, 1 << 17
PADDING = 2.0


@dataclass(frozen=True)
class Widget:
    page: int
    rect: Rect


@dataclass(frozen=True)
class FieldInfo:
    key: str  # Objektnummer des Feldes
    name: str  # vollständiger Name (»Adresse.Ort«)
    kind: str
    value: str | bool
    options: tuple[tuple[str, str], ...] = ()  # (Exportwert, Anzeige)
    widgets: tuple[Widget, ...] = ()
    read_only: bool = False
    required: bool = False
    multiline: bool = False
    max_length: int = 0
    on_values: tuple[str, ...] = ()  # Optionsfelder: Wert je Widget (gleiche Reihenfolge wie ``widgets``)
    editable: bool = True
    reason: str = ""
    extra: dict = field(default_factory=dict, compare=False)


# --- Lesen ----------------------------------------------------------------------------------------------------
def list_fields(document: EditorDocument) -> list[FieldInfo]:
    """Alle Endfelder des Formulars (in der Reihenfolge des Formulars)."""
    pdf = document.pdf
    if not isinstance(pdf.Root.get("/AcroForm"), Dictionary):
        return []
    acroform = pdf.acroform
    pages = {page.obj.objgen: index for index, page in enumerate(pdf.pages)}
    annot_pages = {}
    for index, page in enumerate(pdf.pages):
        annots = page.obj.get("/Annots")
        if isinstance(annots, Array):
            for annot in annots:
                if isinstance(annot, Dictionary) and annot.is_indirect:
                    annot_pages[annot.objgen] = index
    result = []
    for item, members in _groups(document):
        try:
            info = _info(document, acroform, item, members, pages, annot_pages)
        except (pikepdf.PdfError, AttributeError, TypeError, ValueError):
            continue
        if info is not None:
            result.append(info)
    return result


def _groups(document: EditorDocument) -> list[tuple[object, list]]:
    """Felder mit ihren Widgets. qpdf liefert die Knöpfe einer Optionsgruppe einzeln – sie gehören
    zum gemeinsamen Elternfeld (dort steht der Wert)."""
    groups: dict[tuple[int, int], tuple[object, list]] = {}
    for item in document.pdf.acroform.fields:
        holder = item
        if int(item.flags or 0) & FLAG_RADIO and "/T" not in item.obj and not item.parent.is_null:
            holder = item.parent
        key = holder.obj.objgen
        if key not in groups:
            groups[key] = (holder, [])
        groups[key][1].append(item)
    return list(groups.values())


def _info(document: EditorDocument, acroform, item, members: list, pages: dict, annot_pages: dict) -> FieldInfo | None:
    obj = item.obj
    field_type = str(item.field_type or "")
    flags = int(item.flags or 0)
    widgets = []
    on_values = []
    for annot in [annot for member in members for annot in acroform.get_annotations_for_field(member)]:
        annot_obj = annot.obj
        rect = _rect(annot_obj)
        page = annot_pages.get(annot_obj.objgen) if annot_obj.is_indirect else None
        if page is None:
            target = annot_obj.get("/P")
            page = pages.get(target.objgen) if isinstance(target, Dictionary) else None
        if rect is None or page is None:
            continue
        widgets.append(Widget(page, rect))
        if field_type == "/Btn":
            states = [str(key) for key in annot_obj.AP.N.keys()] if isinstance(annot_obj.get("/AP"), Dictionary) and isinstance(annot_obj.AP.get("/N"), Dictionary) else []
            on_values.append(next((state for state in states if state != "/Off"), ""))
    if not widgets:
        return None
    read_only = bool(flags & FLAG_READ_ONLY)
    reason = ""
    options: tuple = ()
    multiline = False
    max_length = 0
    if field_type == "/Tx":
        kind = TEXT
        value: str | bool = item.value_as_string
        multiline = bool(flags & FLAG_MULTILINE)
        max_length = int(item.get_inheritable_field_value("/MaxLen") or 0) if item.get_inheritable_field_value("/MaxLen") is not None else 0
        if flags & FLAG_PASSWORD:
            reason = "Passwortfelder werden nicht unterstützt."
    elif field_type == "/Btn":
        if flags & FLAG_PUSHBUTTON:
            kind, value, reason = BUTTON, "", "Schaltflächen lösen Aktionen aus und werden nicht ausgeführt."
        elif flags & FLAG_RADIO:
            kind = RADIO
            current = item.value
            value = str(current) if current is not None and str(current) != "/Off" else ""
        else:
            kind = CHECKBOX
            value = bool(item.is_checked)
    elif field_type == "/Ch":
        kind = COMBO if flags & FLAG_COMBO else LIST
        value = item.value_as_string
        options = _options(obj, item)
    elif field_type == "/Sig":
        kind, value, reason = SIGNATURE, "", "Signaturfelder lassen sich hier nicht ausfüllen."
    else:
        return None
    if read_only and not reason:
        reason = "Dieses Feld ist schreibgeschützt."
    if not reason and not document.permissions.fill_forms:
        reason = "Die Berechtigungen dieses PDFs erlauben kein Ausfüllen."
    key = f"{obj.objgen[0]}-{obj.objgen[1]}"
    return FieldInfo(key, str(item.fully_qualified_name), kind, value, options, tuple(widgets), read_only, bool(flags & FLAG_REQUIRED), multiline, max_length, tuple(on_values), not reason, reason)


def _options(obj, item) -> tuple[tuple[str, str], ...]:
    raw = item.get_inheritable_field_value("/Opt")
    result = []
    if isinstance(raw, Array):
        for entry in raw:
            if isinstance(entry, Array) and len(entry) >= 2:
                result.append((str(entry[0]), str(entry[1])))
            else:
                result.append((str(entry), str(entry)))
    return tuple(result)


def _rect(annot) -> Rect | None:
    try:
        return normalize(tuple(float(v) for v in annot.Rect))  # type: ignore[arg-type]
    except (AttributeError, TypeError, ValueError):
        return None


def find(document: EditorDocument, key: str):
    """(Feld, Widgets) zu einem Schlüssel."""
    if isinstance(document.pdf.Root.get("/AcroForm"), Dictionary):
        acroform = document.pdf.acroform
        for item, members in _groups(document):
            if f"{item.obj.objgen[0]}-{item.obj.objgen[1]}" == key:
                return item, [annot.obj for member in members for annot in acroform.get_annotations_for_field(member)]
    raise UnsupportedEdit("Das Formularfeld ist nicht mehr vorhanden.")


# --- Ausfüllen ------------------------------------------------------------------------------------------------
def set_value(document: EditorDocument, history: History, key: str, value) -> None:
    """Wert eines Feldes setzen: Text (``str``), Kontrollkästchen (``bool``), Optionsfeld
    (Exportwert der Option, »« = keine), Auswahl/Liste (Exportwert)."""
    document.ensure_editable("fill_forms")
    info = next((it for it in list_fields(document) if it.key == key), None)
    if info is None:
        raise UnsupportedEdit("Das Formularfeld ist nicht mehr vorhanden.")
    if not info.editable:
        raise UnsupportedEdit(info.reason)
    pdf = document.pdf
    item, annots = find(document, key)
    form = pdf.Root.AcroForm
    with commands.record(document, history, "Formular ausfüllen", pages=tuple(sorted({w.page for w in info.widgets}))) as rec:
        rec.object(form, ("/NeedAppearances",))
        rec.object(item.obj, ("/V", "/AS", "/AP"))
        for annot in annots:
            rec.object(annot, ("/AS", "/AP"))
        if info.kind == TEXT:
            text = str(value).replace("\r\n", "\n").replace("\r", "\n")
            if not info.multiline:
                text = text.replace("\n", " ")
            if info.max_length and len(text) > info.max_length:
                raise UnsupportedEdit(f"Höchstens {info.max_length} Zeichen.")
            item.set_value(String(text), False)
            for annot in annots:
                _text_appearance(pdf, item, annot, text, comb=info.max_length if int(item.flags or 0) & FLAG_COMB else 0, multiline=info.multiline)
        elif info.kind in (COMBO, LIST):
            exports = [export for export, _display in info.options]
            text = str(value)
            if info.options and text not in exports and text != "":
                raise UnsupportedEdit("Diesen Wert gibt es in der Auswahl nicht.")
            item.set_value(String(text), False)
            display = dict(info.options).get(text, text)
            for annot in annots:
                if info.kind == COMBO:
                    _text_appearance(pdf, item, annot, display, comb=0, multiline=False)
                else:
                    _list_appearance(pdf, item, annot, info.options, text)
        elif info.kind == CHECKBOX:
            on = next((state for state in info.on_values if state), "/Yes")
            item.set_value(Name(on) if value else Name.Off, False)
            for annot in annots:
                _set_state(annot, on if value else "/Off")
        elif info.kind == RADIO:
            choice = str(value)
            if choice and not choice.startswith("/"):
                choice = "/" + choice
            if choice and choice not in info.on_values:
                raise UnsupportedEdit("Diese Option gibt es nicht.")
            item.obj.V = Name(choice) if choice else Name.Off
            for annot, on in zip(annots, info.on_values):
                _set_state(annot, on if choice and on == choice else "/Off")
        else:
            raise UnsupportedEdit(info.reason or "Dieses Feld lässt sich nicht ausfüllen.")
        if "/NeedAppearances" in form:
            del form["/NeedAppearances"]  # Erscheinungsbilder sind erzeugt – kein Neuaufbau durch den Betrachter


def _set_state(annot, state: str) -> None:
    states = annot.AP.N.keys() if isinstance(annot.get("/AP"), Dictionary) and isinstance(annot.AP.get("/N"), Dictionary) else []
    annot.AS = Name(state) if state in states or state == "/Off" else Name.Off


# --- Erscheinungsbilder ---------------------------------------------------------------------------------------------
def _da(item) -> tuple[float, tuple[float, ...]]:
    """Schriftgröße (0 = automatisch) und Textfarbe aus /DA."""
    da = str(item.default_appearance or "")
    size_match = re.search(r"([\d.]+)\s+Tf", da)
    size = float(size_match.group(1)) if size_match else 0.0
    color: tuple[float, ...] = (0.0,)
    rgb = re.search(r"([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+rg", da)
    gray = re.search(r"([\d.]+)\s+g(?:\s|$)", da)
    if rgb:
        color = tuple(float(v) for v in rgb.groups())
    elif gray:
        color = (float(gray.group(1)),)
    return size, color


def _color_ops(color: tuple[float, ...]) -> str:
    return f"{fmt(color[0])} g" if len(color) == 1 else " ".join(fmt(v) for v in color) + " rg"


def _box(annot) -> tuple[float, float]:
    rect = _rect(annot) or (0, 0, 0, 0)
    width, height = rect[2] - rect[0], rect[3] - rect[1]
    mk = annot.get("/MK")
    rotation = int(mk.get("/R", 0)) % 360 if isinstance(mk, Dictionary) else 0
    return (height, width) if rotation in (90, 270) else (width, height)


def _form_stream(pdf: pikepdf.Pdf, annot, ops: list[str], resources: Dictionary) -> None:
    width, height = _box(annot)
    stream = pdf.make_stream("\n".join(ops).encode("latin-1"))
    stream.Type = Name.XObject
    stream.Subtype = Name.Form
    stream.BBox = Array([0, 0, round(width, 3), round(height, 3)])
    stream.Resources = resources
    mk = annot.get("/MK")
    rotation = int(mk.get("/R", 0)) % 360 if isinstance(mk, Dictionary) else 0
    if rotation:
        matrix = {90: [0, 1, -1, 0, height, 0], 180: [-1, 0, 0, -1, width, height], 270: [0, -1, 1, 0, 0, width]}[rotation]
        stream.Matrix = Array(matrix)
    states = annot.AP if isinstance(annot.get("/AP"), Dictionary) else None
    new = Dictionary({str(k): v for k, v in states.items()}) if states is not None else Dictionary()
    new.N = stream
    annot.AP = new  # neues Dictionary – das alte bleibt für Rückgängig unverändert


def _background(annot, width: float, height: float) -> list[str]:
    mk = annot.get("/MK")
    ops = []
    if isinstance(mk, Dictionary):
        fill = mk.get("/BG")
        border = mk.get("/BC")
        if isinstance(fill, Array) and len(fill):
            ops.append(_color_ops(tuple(float(v) for v in fill)) + f" 0 0 {fmt(width)} {fmt(height)} re f")
        if isinstance(border, Array) and len(border):
            stroke = _color_ops(tuple(float(v) for v in border)).replace(" rg", " RG").replace(" g", " G")
            ops.append(f"{stroke} 1 w 0.5 0.5 {fmt(width - 1)} {fmt(height - 1)} re S")
    return ops


def _text_appearance(pdf: pikepdf.Pdf, item, annot, text: str, *, comb: int, multiline: bool) -> None:
    from .annotations import _ap_font

    width, height = _box(annot)
    size, color = _da(item)
    key, font, measure, encode = _ap_font(pdf, text.replace("\n", "") or " ")
    quadding = int(item.quadding or 0)
    inner_w = max(1.0, width - 2 * PADDING)
    if not size:  # automatisch: an Höhe (einzeilig) bzw. 12 pt (mehrzeilig) – passend verkleinert
        size = 12.0 if multiline else max(4.0, min(12.0, (height - 2 * PADDING) * 0.75))
        if not multiline:
            while size > 4.0 and measure(text, size) > inner_w:
                size -= 0.5
    ops = _background(annot, width, height) + ["/Tx BMC", "q", f"1 1 {fmt(width - 2)} {fmt(height - 2)} re W n", "BT", f"{key} {fmt(size)} Tf {_color_ops(color)}"]
    if comb and not multiline:
        cell = width / comb
        for index, char in enumerate(text[:comb]):
            x = cell * index + (cell - measure(char, size)) / 2
            ops.append(f"1 0 0 1 {fmt(x)} {fmt((height - size * 0.72) / 2)} Tm <{encode(char).hex()}> Tj")
    elif multiline:
        from .textedit import _wrap

        lines = _wrap(text, inner_w, lambda value: measure(value, size))
        step = size * 1.15
        y = height - PADDING - size * 0.85
        for line in lines:
            if y < -size:
                break
            x = _align(quadding, PADDING, inner_w, measure(line, size))
            ops.append(f"1 0 0 1 {fmt(x)} {fmt(y)} Tm <{encode(line).hex()}> Tj")
            y -= step
    else:
        x = _align(quadding, PADDING, inner_w, measure(text, size))
        ops.append(f"1 0 0 1 {fmt(x)} {fmt((height - size * 0.72) / 2)} Tm <{encode(text).hex()}> Tj")
    ops += ["ET", "Q", "EMC"]
    _form_stream(pdf, annot, ops, Dictionary(Font=Dictionary({key: font})))


def _align(quadding: int, start: float, width: float, measured: float) -> float:
    if quadding == 1:
        return start + (width - measured) / 2
    if quadding == 2:
        return start + width - measured
    return start


def _list_appearance(pdf: pikepdf.Pdf, item, annot, options, selected: str) -> None:
    from .annotations import _ap_font

    width, height = _box(annot)
    size, color = _da(item)
    size = size or 11.0
    labels = [display for _export, display in options]
    key, font, measure, encode = _ap_font(pdf, "".join(labels) or " ")
    step = size * 1.15
    ops = _background(annot, width, height) + ["/Tx BMC", "q", f"1 1 {fmt(width - 2)} {fmt(height - 2)} re W n"]
    y = height - PADDING
    for export, display in options:
        if y - step < -step:
            break
        if export == selected:
            ops.append(f"0.6 0.75 0.95 rg 1 {fmt(y - step)} {fmt(width - 2)} {fmt(step)} re f")
        ops.append(f"BT {key} {fmt(size)} Tf {_color_ops(color)} 1 0 0 1 {fmt(PADDING)} {fmt(y - size * 0.95)} Tm <{encode(display).hex()}> Tj ET")
        y -= step
    ops += ["Q", "EMC"]
    _form_stream(pdf, annot, ops, Dictionary(Font=Dictionary({key: font})))
