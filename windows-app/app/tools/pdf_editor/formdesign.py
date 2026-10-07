"""Formulare gestalten (Formularmodus): neue Felder anlegen – Textfeld, Kontrollkästchen, Optionsfeld
(Gruppe), Auswahlliste (Dropdown) und Liste –, Felder verschieben, in der Größe ändern, löschen, duplizieren
und ihre Eigenschaften ändern (Name, Kurzinfo, Pflichtfeld, schreibgeschützt, mehrzeilig, Zeichenzahl,
Schriftgröße, Ausrichtung, Optionen, Exportwert, Rahmen und Hintergrund).

Neue Felder sind gewöhnliche AcroForm-Felder mit eigenem Erscheinungsbild für jeden Zustand – sie sehen in
jedem Programm gleich aus und lassen sich dort ausfüllen. Bearbeitet wird je Widget (das Kästchen auf der
Seite); bei Optionsfeldern gehört jedes Widget als Option zu einer Gruppe. Jede Änderung ist ein Schritt für
»Rückgängig«; bestehende Arrays, Dictionaries und Streams werden nie in place verändert (siehe ``commands``).

XFA-Formulare werden nicht verändert: Ein Programm, das XFA darstellt, würde neue AcroForm-Felder nicht zeigen.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import pikepdf
from pikepdf import Array, Dictionary, Name, String

from . import commands, forms
from .commands import History
from .content import fmt
from .document import EditorDocument
from .errors import UnsupportedEdit
from .forms import BUTTON, CHECKBOX, COMBO, LIST, RADIO, SIGNATURE, TEXT
from .geometry import Rect, normalize

KINDS = (TEXT, CHECKBOX, RADIO, COMBO, LIST)  # lassen sich anlegen
BASE_NAMES = {TEXT: "Textfeld", CHECKBOX: "Kontrollkästchen", RADIO: "Optionsgruppe", COMBO: "Auswahl", LIST: "Liste"}
TITLES = {TEXT: "Textfeld", CHECKBOX: "Kontrollkästchen", RADIO: "Optionsfeld", COMBO: "Dropdown", LIST: "Liste"}
SIZES = {TEXT: (180.0, 22.0), CHECKBOX: (14.0, 14.0), RADIO: (14.0, 14.0), COMBO: (150.0, 22.0), LIST: (150.0, 64.0)}
DEFAULT_OPTIONS = ("Option 1", "Option 2", "Option 3")
MIN_SIZE = 6.0  # kleinstes Feld (pt)
MAX_NAME = 120
MAX_EXPORT = 60
MAX_OPTIONS = 500
FONT_SIZES = (0.0, 6.0, 7.0, 8.0, 9.0, 10.0, 11.0, 12.0, 14.0, 16.0, 18.0, 20.0, 24.0, 28.0, 36.0)  # 0 = automatisch
ALIGNS = ("left", "center", "right")
FLAG_NO_TOGGLE_OFF = 1 << 14
TEXT_DA = "/Helv 0 Tf 0 g"
BUTTON_DA = "/ZaDb 0 Tf 0 g"
BORDER = (0.45, 0.45, 0.45)
BACKGROUND = (1.0, 1.0, 1.0)
MARK = "PDF Tool"  # Felder aus PDF Tool (Erscheinungsbild bei Größenänderung neu)
PROPERTIES = ("name", "tooltip", "required", "readOnly", "multiline", "maxLength", "fontSize", "align", "options", "export", "border", "background")


@dataclass(frozen=True)
class DesignWidget:
    """Ein Feld-Widget auf einer Seite – mit den Eigenschaften seines Feldes."""

    key: str  # Widget (Objektnummer der Anmerkung)
    field: str  # Feld (bei Feldern mit nur einem Widget dieselbe Nummer)
    name: str  # vollständiger Name (»Adresse.Ort«)
    kind: str
    page: int
    rect: Rect
    export: str = ""  # Kontrollkästchen/Optionsfeld: Wert im Zustand »ein« (ohne »/«)
    tooltip: str = ""
    required: bool = False
    read_only: bool = False
    multiline: bool = False
    max_length: int = 0
    font_size: float = 0.0  # 0 = automatisch
    align: str = "left"
    options: tuple[str, ...] = ()  # Auswahl/Liste: angezeigte Einträge
    border: bool = True
    background: bool = True
    siblings: int = 1  # Widgets des Feldes (Optionsgruppe: Anzahl Optionen)
    ours: bool = False


# --- Lesen ----------------------------------------------------------------------------------------------------
def list_widgets(document: EditorDocument) -> list[DesignWidget]:
    """Alle Widgets aller Felder (Reihenfolge des Formulars)."""
    pdf = document.pdf
    if not isinstance(pdf.Root.get("/AcroForm"), Dictionary):
        return []
    acroform = pdf.acroform
    annot_pages = _annot_pages(pdf)
    result: list[DesignWidget] = []
    for item, members in forms._groups(document):  # noqa: SLF001 - gemeinsame Feldlogik
        try:
            kind = _kind(item)
            if kind is None:
                continue
            props = _props(item, kind)
            annots = [annot.obj for member in members for annot in acroform.get_annotations_for_field(member)]
            for annot in annots:
                if not annot.is_indirect or annot.objgen not in annot_pages:
                    continue
                rect = forms._rect(annot)  # noqa: SLF001
                if rect is None:
                    continue
                mk = annot.get("/MK")
                result.append(DesignWidget(
                    key=_key(annot), field=_key(item.obj), kind=kind, page=annot_pages[annot.objgen], rect=rect,
                    export=_export(annot) if kind in (CHECKBOX, RADIO) else "",
                    border=isinstance(mk, Dictionary) and _has_color(mk.get("/BC")),
                    background=isinstance(mk, Dictionary) and _has_color(mk.get("/BG")),
                    siblings=len(annots), ours=str(annot.get("/PTEditor", "")) == MARK, **props,
                ))
        except (pikepdf.PdfError, AttributeError, TypeError, ValueError):
            continue
    return result


def _annot_pages(pdf: pikepdf.Pdf) -> dict:
    found = {}
    for index, page in enumerate(pdf.pages):
        annots = page.obj.get("/Annots")
        if isinstance(annots, Array):
            for annot in annots:
                if isinstance(annot, Dictionary) and annot.is_indirect:
                    found.setdefault(annot.objgen, index)
    return found


def _kind(item) -> str | None:
    field_type = str(item.field_type or "")
    flags = int(item.flags or 0)
    if field_type == "/Tx":
        return TEXT
    if field_type == "/Btn":
        if flags & forms.FLAG_PUSHBUTTON:
            return BUTTON
        return RADIO if flags & forms.FLAG_RADIO else CHECKBOX
    if field_type == "/Ch":
        return COMBO if flags & forms.FLAG_COMBO else LIST
    if field_type == "/Sig":
        return SIGNATURE
    return None


def _props(item, kind: str) -> dict:
    flags = int(item.flags or 0)
    size, _color = forms._da(item)  # noqa: SLF001
    max_length = item.get_inheritable_field_value("/MaxLen")
    tooltip = item.obj.get("/TU")
    return {
        "name": str(item.fully_qualified_name),
        "tooltip": str(tooltip) if isinstance(tooltip, String) else "",
        "required": bool(flags & forms.FLAG_REQUIRED),
        "read_only": bool(flags & forms.FLAG_READ_ONLY),
        "multiline": kind == TEXT and bool(flags & forms.FLAG_MULTILINE),
        "max_length": int(max_length) if kind == TEXT and max_length is not None else 0,
        "font_size": float(size),
        "align": ALIGNS[int(item.quadding or 0)] if 0 <= int(item.quadding or 0) < 3 else "left",
        "options": tuple(display for _export_value, display in forms._options(item.obj, item)) if kind in (COMBO, LIST) else (),  # noqa: SLF001
    }


def _key(obj) -> str:
    return f"{obj.objgen[0]}-{obj.objgen[1]}"


def _export(annot) -> str:
    """Wert im Zustand »ein« (Name ohne »/«) – aus den Erscheinungsbildern des Widgets."""
    ap = annot.get("/AP")
    normal = ap.get("/N") if isinstance(ap, Dictionary) else None
    if isinstance(normal, Dictionary):
        for state in normal.keys():
            if str(state) != "/Off":
                return str(state)[1:]
    state = annot.get("/AS")
    return str(state)[1:] if isinstance(state, Name) and str(state) != "/Off" else ""


def _has_color(value) -> bool:
    return isinstance(value, Array) and len(value) > 0


def _locate(document: EditorDocument, key: str):
    """(Feld, Widget, alle Widgets des Feldes, Art, Seite) zu einem Widget-Schlüssel."""
    pdf = document.pdf
    if isinstance(pdf.Root.get("/AcroForm"), Dictionary):
        acroform = pdf.acroform
        annot_pages = _annot_pages(pdf)
        for item, members in forms._groups(document):  # noqa: SLF001
            annots = [annot.obj for member in members for annot in acroform.get_annotations_for_field(member)]
            for annot in annots:
                if annot.is_indirect and _key(annot) == key and annot.objgen in annot_pages:
                    kind = _kind(item)
                    if kind is None:
                        break
                    return item, annot, annots, kind, annot_pages[annot.objgen]
    raise UnsupportedEdit("Das Formularfeld ist nicht mehr vorhanden.")


def _names(document: EditorDocument) -> set[str]:
    if not isinstance(document.pdf.Root.get("/AcroForm"), Dictionary):
        return set()
    return {str(item.fully_qualified_name) for item, _members in forms._groups(document)}  # noqa: SLF001


def _next_name(names: set[str], base: str) -> str:
    """»Textfeld 1«, »Textfeld 2« … – der erste freie Name."""
    number = 1
    while f"{base} {number}" in names:
        number += 1
    return f"{base} {number}"


def _copy_name(names: set[str], name: str, prefix: str = "") -> str:
    """Name für eine Kopie: »Name« → »Name 2«, »Textfeld 3« → »Textfeld 4« (der nächste freie; ``prefix``:
    Gruppe des Feldes, z. B. »Adresse.«)."""
    match = re.fullmatch(r"(.*?)\s*(\d+)", name)
    base, number = (match.group(1), int(match.group(2)) + 1) if match and match.group(1) else (name, 2)
    while f"{prefix}{base} {number}" in names:
        number += 1
    return f"{base} {number}"


def _clean_name(name: str) -> str:
    name = " ".join(str(name).split())
    if not name:
        raise UnsupportedEdit("Bitte einen Namen für das Feld angeben.")
    if "." in name:
        raise UnsupportedEdit("Feldnamen dürfen keinen Punkt enthalten (der Punkt trennt Gruppen von Feldern).")
    if len(name) > MAX_NAME:
        raise UnsupportedEdit(f"Der Name ist zu lang (höchstens {MAX_NAME} Zeichen).")
    return name


def _clean_export(value: str) -> str:
    value = " ".join(str(value).split())
    if not value:
        raise UnsupportedEdit("Bitte einen Exportwert angeben (z. B. »Ja«).")
    if value == "Off":
        raise UnsupportedEdit("»Off« steht für »nicht gewählt« und lässt sich nicht als Exportwert verwenden.")
    if len(value) > MAX_EXPORT:
        raise UnsupportedEdit(f"Der Exportwert ist zu lang (höchstens {MAX_EXPORT} Zeichen).")
    return value


def _check(document: EditorDocument) -> None:
    document.ensure_editable("edit")
    document.ensure_editable("annotate")
    if getattr(document.report, "xfa", False) or (isinstance(document.pdf.Root.get("/AcroForm"), Dictionary) and "/XFA" in document.pdf.Root.AcroForm):
        raise UnsupportedEdit("Dieses PDF enthält ein XFA-Formular. Felder lassen sich darin ausfüllen, aber nicht neu anlegen oder umgestalten.")


def _valid_rect(rect: Rect) -> Rect:
    rect = normalize(tuple(float(v) for v in rect))  # type: ignore[arg-type]
    if rect[2] - rect[0] < MIN_SIZE or rect[3] - rect[1] < MIN_SIZE:
        raise UnsupportedEdit(f"Das Feld ist zu klein (mindestens {MIN_SIZE:g} × {MIN_SIZE:g} pt).")
    return tuple(round(v, 3) for v in rect)  # type: ignore[return-value]


# --- Bausteine ------------------------------------------------------------------------------------------------
def _keep(rec, obj, *keys: str) -> None:
    """Einträge für »Rückgängig« merken – jeden Eintrag einzeln, damit nichts doppelt (mit einem
    Zwischenstand) erfasst wird."""
    for key in keys:
        rec.object(obj, (key,))


def _form(rec, document: EditorDocument) -> Dictionary:
    """Das AcroForm-Dictionary (wird angelegt, wenn das PDF noch keins hat) – mit Standardschrift für
    Textfelder (/Helv) und Symbolschrift für Kästchen (/ZaDb) in den Formularressourcen."""
    pdf = document.pdf
    form = pdf.Root.get("/AcroForm")
    if not isinstance(form, Dictionary):
        rec.root(("/AcroForm",))
        pdf.Root.AcroForm = pdf.make_indirect(Dictionary(Fields=Array([]), DA=String(TEXT_DA)))
        form = pdf.Root.AcroForm
    _keep(rec, form, "/Fields", "/DA", "/DR")
    if not isinstance(form.get("/Fields"), Array):
        form.Fields = Array([])
    if not isinstance(form.get("/DA"), String):
        form.DA = String(TEXT_DA)
    resources = form.get("/DR")
    fonts = resources.get("/Font") if isinstance(resources, Dictionary) else None
    if not (isinstance(fonts, Dictionary) and "/Helv" in fonts and "/ZaDb" in fonts):
        new_fonts = Dictionary({str(k): v for k, v in fonts.items()}) if isinstance(fonts, Dictionary) else Dictionary()
        if "/Helv" not in new_fonts:
            new_fonts.Helv = pdf.make_indirect(Dictionary(Type=Name.Font, Subtype=Name.Type1, BaseFont=Name.Helvetica, Encoding=Name.WinAnsiEncoding))
        if "/ZaDb" not in new_fonts:
            new_fonts.ZaDb = pdf.make_indirect(Dictionary(Type=Name.Font, Subtype=Name.Type1, BaseFont=Name.ZapfDingbats))
        new_resources = Dictionary({str(k): v for k, v in resources.items()}) if isinstance(resources, Dictionary) else Dictionary()
        new_resources.Font = new_fonts
        form.DR = new_resources
    return form


class _FieldView:
    """Was die Erscheinungsbilder aus ``forms`` vom Feld brauchen (/DA und /Q mit Vererbung) – auch für ein
    Feld, das gerade erst entsteht."""

    def __init__(self, form, node) -> None:
        self.form, self.node = form, node

    def _inherited(self, key: str):
        node, depth = self.node, 0
        while isinstance(node, Dictionary) and depth < 32:
            if key in node:
                return node[key]
            node, depth = node.get("/Parent"), depth + 1
        return self.form.get(key) if isinstance(self.form, Dictionary) else None

    @property
    def default_appearance(self) -> bytes:
        value = self._inherited("/DA")
        return bytes(value) if isinstance(value, String) else TEXT_DA.encode()

    @property
    def quadding(self) -> int:
        try:
            value = int(self._inherited("/Q") or 0)
        except (TypeError, ValueError):
            return 0
        return value if 0 <= value <= 2 else 0

    @property
    def flags(self) -> int:
        try:
            return int(self._inherited("/Ff") or 0)
        except (TypeError, ValueError):
            return 0

    @property
    def options(self) -> tuple[tuple[str, str], ...]:
        """(Exportwert, Anzeige) aus /Opt (auch geerbt)."""
        raw = self._inherited("/Opt")
        result = []
        if isinstance(raw, Array):
            for entry in raw:
                if isinstance(entry, Array) and len(entry) >= 2:
                    result.append((str(entry[0]), str(entry[1])))
                else:
                    result.append((str(entry), str(entry)))
        return tuple(result)


def _state_stream(pdf: pikepdf.Pdf, annot, ops: list[str]) -> pikepdf.Object:
    """Erscheinungsbild eines Zustands (Form-XObject in der Größe des Widgets, gedreht wie /MK /R)."""
    width, height = forms._box(annot)  # noqa: SLF001
    stream = pdf.make_stream("\n".join(ops).encode("latin-1"))
    stream.Type = Name.XObject
    stream.Subtype = Name.Form
    stream.BBox = Array([0, 0, round(width, 3), round(height, 3)])
    stream.Resources = Dictionary()
    mk = annot.get("/MK")
    rotation = int(mk.get("/R", 0)) % 360 if isinstance(mk, Dictionary) else 0
    if rotation:
        matrix = {90: [0, 1, -1, 0, height, 0], 180: [-1, 0, 0, -1, width, height], 270: [0, -1, 1, 0, 0, width]}[rotation]
        stream.Matrix = Array(matrix)
    return stream


def _circle(cx: float, cy: float, r: float) -> str:
    from .annotations import _ellipse

    return _ellipse(cx - r, cy - r, cx + r, cy + r)


def _button_appearance(pdf: pikepdf.Pdf, annot, kind: str, on: str) -> None:
    """Kontrollkästchen (Haken) und Optionsfeld (Punkt): Erscheinungsbilder für »ein« (``on``) und »aus«
    – gezeichnet, ohne Schrift, damit sie überall gleich aussehen."""
    width, height = forms._box(annot)  # noqa: SLF001
    mk = annot.get("/MK")
    fill = mk.get("/BG") if isinstance(mk, Dictionary) else None
    border = mk.get("/BC") if isinstance(mk, Dictionary) else None
    if kind == RADIO:
        r = max(1.0, min(width, height) / 2 - 0.5)
        cx, cy = width / 2, height / 2
        base = []
        if _has_color(fill):
            base.append(forms._color_ops(tuple(float(v) for v in fill)) + " " + _circle(cx, cy, r) + " f")  # noqa: SLF001
        if _has_color(border):
            base.append(_stroke_ops(border) + " 1 w " + _circle(cx, cy, r) + " S")
        mark = ["0 g " + _circle(cx, cy, max(0.8, r * 0.45)) + " f"]
    else:
        base = forms._background(annot, width, height)  # noqa: SLF001
        side = min(width, height)
        ox, oy = (width - side) / 2, (height - side) / 2
        line = max(0.8, side * 0.12)
        mark = [f"q 0 G {fmt(line)} w 1 J 1 j {fmt(ox + side * 0.22)} {fmt(oy + side * 0.52)} m {fmt(ox + side * 0.42)} {fmt(oy + side * 0.28)} l {fmt(ox + side * 0.80)} {fmt(oy + side * 0.76)} l S Q"]
    off = _state_stream(pdf, annot, base or ["n"])
    shown = _state_stream(pdf, annot, base + mark)
    annot.AP = Dictionary(N=Dictionary({on: shown, "/Off": off}), D=Dictionary({on: shown, "/Off": off}))


def _stroke_ops(color) -> str:
    values = tuple(float(v) for v in color)
    return f"{fmt(values[0])} G" if len(values) == 1 else " ".join(fmt(v) for v in values) + " RG"


def _refresh(pdf: pikepdf.Pdf, form, holder, annots: list, kind: str, *, buttons: bool = True) -> None:
    """Erscheinungsbilder aller Widgets eines Feldes neu erzeugen (nach Größe oder Eigenschaften).
    ``buttons=False``: fremde Kästchen behalten ihr Aussehen (nur die aus PDF Tool werden neu gezeichnet)."""
    view = _FieldView(form, holder)
    if kind in (TEXT, COMBO):
        value = holder.get("/V")
        text = str(value) if isinstance(value, String) else ""
        if kind == COMBO:
            text = dict(view.options).get(text, text)
        multiline = kind == TEXT and bool(view.flags & forms.FLAG_MULTILINE)
        comb_length = holder.get("/MaxLen")
        comb = int(comb_length) if kind == TEXT and view.flags & forms.FLAG_COMB and comb_length is not None else 0
        for annot in annots:
            forms._text_appearance(pdf, view, annot, text, comb=comb, multiline=multiline)  # noqa: SLF001
    elif kind == LIST:
        value = holder.get("/V")
        for annot in annots:
            forms._list_appearance(pdf, view, annot, view.options, str(value) if isinstance(value, String) else "")  # noqa: SLF001
    elif kind in (CHECKBOX, RADIO):
        for annot in annots:
            if not buttons and str(annot.get("/PTEditor", "")) != MARK:
                continue
            on = _export(annot) or ("Ja" if kind == CHECKBOX else "Option 1")
            _button_appearance(pdf, annot, kind, "/" + on)


def _new_widget(pdf: pikepdf.Pdf, page_obj, rect: Rect, rotation: int, *, kind: str) -> Dictionary:
    mk = Dictionary(BC=Array(list(BORDER)), BG=Array(list(BACKGROUND)))
    if rotation:
        mk.R = rotation
    if kind == CHECKBOX:
        mk.CA = String("4")  # Haken in ZapfDingbats (falls ein Programm das Bild selbst erzeugt)
    elif kind == RADIO:
        mk.CA = String("l")  # Punkt
    return Dictionary(Type=Name.Annot, Subtype=Name.Widget, Rect=Array(list(rect)), F=4, P=page_obj, MK=mk,
                      BS=Dictionary(W=1, S=Name.S), PTEditor=String(MARK))


# --- Anlegen --------------------------------------------------------------------------------------------------
def create(document: EditorDocument, history: History, page: int, kind: str, rect: Rect, *, name: str = "", options=None) -> str:
    """Neues Feld (``kind``: Textfeld, Kontrollkästchen, Optionsfeld, Dropdown, Liste) im Rechteck ``rect``
    (PDF-Koordinaten). Liefert den Schlüssel des Widgets. Optionsfelder entstehen als Gruppe mit einer
    Option – weitere Optionen mit ``add_option``."""
    _check(document)
    if kind not in KINDS:
        raise UnsupportedEdit("Diese Art von Feld lässt sich nicht anlegen.")
    if not 0 <= page < document.page_count:
        raise UnsupportedEdit("Diese Seite gibt es nicht.")
    rect = _valid_rect(rect)
    names = _names(document)
    name = _clean_name(name) if name else _next_name(names, BASE_NAMES[kind])
    if name in names:
        raise UnsupportedEdit(f"Ein Feld »{name}« gibt es schon.")
    choices = [str(item) for item in (options if options is not None else DEFAULT_OPTIONS)]
    pdf = document.pdf
    page_obj = pdf.pages[page].obj
    rotation = document.geometry(page).rotation
    with commands.record(document, history, f"{TITLES[kind]} hinzufügen", pages=(page,)) as rec:
        form = _form(rec, document)
        _keep(rec, page_obj, "/Annots")
        widget = _new_widget(pdf, page_obj, rect, rotation, kind=kind)
        if kind == RADIO:
            field = pdf.make_indirect(Dictionary(FT=Name.Btn, Ff=forms.FLAG_RADIO | FLAG_NO_TOGGLE_OFF, T=String(name), V=Name.Off, DA=String(BUTTON_DA)))
            widget.Parent = field
            widget.AS = Name.Off
            widget = pdf.make_indirect(widget)
            field.Kids = Array([widget])
            _button_appearance(pdf, widget, RADIO, "/Option 1")
        else:
            widget.T = String(name)
            if kind == TEXT:
                widget.FT, widget.DA = Name.Tx, String(TEXT_DA)
            elif kind == CHECKBOX:
                widget.FT, widget.Ff, widget.DA, widget.V, widget.AS = Name.Btn, 0, String(BUTTON_DA), Name.Off, Name.Off
            else:
                widget.FT, widget.DA = Name.Ch, String(TEXT_DA)
                widget.Ff = forms.FLAG_COMBO if kind == COMBO else 0
                widget.Opt = Array([String(choice) for choice in choices])
            widget = pdf.make_indirect(widget)
            field = widget
            if kind == CHECKBOX:
                _button_appearance(pdf, widget, CHECKBOX, "/Ja")
            else:
                _refresh(pdf, form, widget, [widget], kind)
        form.Fields = Array([*list(form.Fields), field])
        annots = page_obj.get("/Annots")
        page_obj.Annots = Array([*(list(annots) if isinstance(annots, Array) else []), widget])
    return _key(widget)


def add_option(document: EditorDocument, history: History, key: str, rect: Rect | None = None) -> str:
    """Optionsgruppe um eine Option erweitern (neben bzw. unter dem Widget ``key`` oder in ``rect``)."""
    _check(document)
    item, annot, annots, kind, page = _locate(document, key)
    if kind != RADIO:
        raise UnsupportedEdit("Optionen gibt es nur bei Optionsfeldern.")
    holder = item.obj
    kids = holder.get("/Kids")
    if not isinstance(kids, Array) or annot.get("/Parent") is None:
        raise UnsupportedEdit("Diese Optionsgruppe lässt sich nicht erweitern.")
    exports = {_export(widget) for widget in annots}
    number = len(annots) + 1
    while f"Option {number}" in exports:
        number += 1
    if rect is None:
        box = forms._rect(annot)  # noqa: SLF001
        gap = (box[3] - box[1]) + 6
        rect = (box[0], box[1] - gap, box[2], box[3] - gap)
    rect = _valid_rect(rect)
    pdf = document.pdf
    page_obj = pdf.pages[page].obj
    with commands.record(document, history, "Option hinzufügen", pages=(page,)) as rec:
        _keep(rec, page_obj, "/Annots")
        _keep(rec, holder, "/Kids")
        widget = Dictionary({str(k): v for k, v in annot.items() if str(k) not in ("/AP", "/AS", "/Rect", "/NM", "/M")})
        widget.Rect = Array(list(rect))
        widget.AS = Name.Off
        widget.P = page_obj
        widget = pdf.make_indirect(widget)
        _button_appearance(pdf, widget, RADIO, f"/Option {number}")
        holder.Kids = Array([*list(kids), widget])
        page_annots = page_obj.get("/Annots")
        page_obj.Annots = Array([*(list(page_annots) if isinstance(page_annots, Array) else []), widget])
    return _key(widget)


# --- Verschieben, Größe, Löschen, Duplizieren --------------------------------------------------------------------
def move(document: EditorDocument, history: History, keys, dx: float, dy: float) -> None:
    """Widgets um (dx, dy) PDF-Punkte verschieben (ein Schritt für »Rückgängig«)."""
    _check(document)
    found = [_locate(document, key) for key in dict.fromkeys(keys)]
    if not found or (abs(dx) < 0.01 and abs(dy) < 0.01):
        return
    pages = tuple(sorted({entry[4] for entry in found}))
    with commands.record(document, history, "Feld verschieben" if len(found) == 1 else "Felder verschieben", pages=pages) as rec:
        for _item, annot, _annots, _kind_, _page in found:
            _keep(rec, annot, "/Rect")
            box = forms._rect(annot)  # noqa: SLF001
            annot.Rect = Array([round(v, 3) for v in (box[0] + dx, box[1] + dy, box[2] + dx, box[3] + dy)])


def resize(document: EditorDocument, history: History, key: str, rect: Rect) -> None:
    """Widget auf ``rect`` (PDF-Koordinaten) setzen. Text, Auswahl und Kästchen aus PDF Tool erhalten ein
    passendes Erscheinungsbild; fremde Kästchen, Schaltflächen und Signaturfelder werden mitskaliert."""
    _check(document)
    item, annot, _annots, kind, page = _locate(document, key)
    rect = _valid_rect(rect)
    pdf = document.pdf
    with commands.record(document, history, "Feldgröße ändern", pages=(page,)) as rec:
        _keep(rec, annot, "/Rect", "/AP")
        annot.Rect = Array(list(rect))
        if kind in (TEXT, COMBO, LIST) or (kind in (CHECKBOX, RADIO) and str(annot.get("/PTEditor", "")) == MARK):
            _refresh(pdf, pdf.Root.AcroForm, item.obj, [annot], kind)


def delete(document: EditorDocument, history: History, keys) -> None:
    """Widgets löschen; ein Feld ohne Widgets verschwindet ganz (auch aus der Berechnungsreihenfolge)."""
    _check(document)
    found = [_locate(document, key) for key in dict.fromkeys(keys)]
    if not found:
        return
    pdf = document.pdf
    form = pdf.Root.AcroForm
    gone = {annot.objgen for _item, annot, _annots, _kind_, _page in found}
    pages = tuple(sorted({entry[4] for entry in found}))
    with commands.record(document, history, "Feld löschen" if len(found) == 1 else "Felder löschen", pages=pages) as rec:
        _keep(rec, form, "/Fields", "/CO")
        for page in pages:
            page_obj = pdf.pages[page].obj
            _keep(rec, page_obj, "/Annots")
            kept = [annot for annot in page_obj.Annots if not (isinstance(annot, Dictionary) and annot.is_indirect and annot.objgen in gone)]
            if kept:
                page_obj.Annots = Array(kept)
            else:
                del page_obj["/Annots"]
        removed: set = set()
        for item, annot, annots, kind, _page in found:
            holder = item.obj
            if holder.objgen in removed:
                continue
            left = [widget for widget in annots if widget.objgen not in gone]
            if left and holder.objgen != annot.objgen:
                # Optionsgruppe (oder Feld mit mehreren Widgets) bleibt: nur die gelöschten Kinder entfernen
                kids = holder.get("/Kids")
                if isinstance(kids, Array):
                    _keep(rec, holder, "/Kids", "/V")
                    holder.Kids = Array([kid for kid in kids if not (isinstance(kid, Dictionary) and kid.is_indirect and kid.objgen in gone)])
                    if kind == RADIO and isinstance(holder.get("/V"), Name) and str(holder.V)[1:] not in {_export(widget) for widget in left}:
                        holder.V = Name.Off
                continue
            removed.add(holder.objgen)
            _detach(rec, form, holder, removed)


def _detach(rec, form, node, removed: set) -> None:
    """Feld aus seinem Elternfeld bzw. aus /Fields lösen; leere Elternfelder gehen mit. /Fields und /CO
    des Formulars hat der Aufrufer schon gemerkt."""
    parent = node.get("/Parent")
    if isinstance(parent, Dictionary) and isinstance(parent.get("/Kids"), Array):
        _keep(rec, parent, "/Kids")
        kids = [kid for kid in parent.Kids if not (isinstance(kid, Dictionary) and kid.is_indirect and kid.objgen == node.objgen)]
        if kids:
            parent.Kids = Array(kids)
            return
        parent.Kids = Array([])
        removed.add(parent.objgen)
        _detach(rec, form, parent, removed)
        return
    form.Fields = Array([entry for entry in form.Fields if not (isinstance(entry, Dictionary) and entry.is_indirect and entry.objgen == node.objgen)])
    order = form.get("/CO")
    if isinstance(order, Array):
        rest = [entry for entry in order if not (isinstance(entry, Dictionary) and entry.is_indirect and entry.objgen in removed)]
        if rest:
            form.CO = Array(rest)
        else:
            del form["/CO"]


def duplicate(document: EditorDocument, history: History, keys, dx: float, dy: float) -> list[str]:
    """Kopien der Widgets um (dx, dy) versetzt. Optionsfelder bekommen eine neue Option in derselben Gruppe,
    alle anderen werden ein eigenes Feld mit neuem Namen (Wert und Aussehen wie das Original)."""
    _check(document)
    found = [_locate(document, key) for key in dict.fromkeys(keys)]
    if not found:
        return []
    for _item, _annot, _annots, kind, _page in found:
        if kind in (SIGNATURE, BUTTON):
            raise UnsupportedEdit("Signaturfelder und Schaltflächen lassen sich nicht duplizieren.")
    pdf = document.pdf
    names = _names(document)
    created: list[str] = []
    pages = tuple(sorted({entry[4] for entry in found}))
    with commands.group(document, history, "Feld duplizieren" if len(found) == 1 else "Felder duplizieren"):
        for item, annot, annots, kind, page in found:
            box = forms._rect(annot)  # noqa: SLF001
            target = (box[0] + dx, box[1] + dy, box[2] + dx, box[3] + dy)
            if kind == RADIO:
                created.append(add_option(document, history, _key(annot), target))
                continue
            page_obj = pdf.pages[page].obj
            holder = item.obj
            full = str(item.fully_qualified_name)
            prefix = full.rsplit(".", 1)[0] + "." if "." in full and isinstance(holder.get("/Parent"), Dictionary) else ""
            name = _copy_name(names, full.rsplit(".", 1)[-1] if prefix else full, prefix)
            names.add(prefix + name)
            with commands.record(document, history, "Feld duplizieren", pages=pages) as rec:
                form = _form(rec, document)
                _keep(rec, page_obj, "/Annots")
                fields = {str(k): v for k, v in holder.items() if str(k) in ("/FT", "/Ff", "/V", "/DV", "/DA", "/Q", "/Opt", "/MaxLen", "/TU", "/Parent", "/TI", "/I")}
                widget_keys = {str(k): v for k, v in annot.items() if str(k) not in ("/Parent", "/T", "/Kids", "/NM", "/M", "/P", "/Rect")}
                copy = Dictionary({**widget_keys, **fields})
                copy.T = String(name)
                copy.Rect = Array([round(v, 3) for v in target])
                copy.P = page_obj
                copy = pdf.make_indirect(copy)
                parent = copy.get("/Parent")
                if isinstance(parent, Dictionary) and isinstance(parent.get("/Kids"), Array):
                    _keep(rec, parent, "/Kids")
                    parent.Kids = Array([*list(parent.Kids), copy])
                else:
                    if "/Parent" in copy:
                        del copy["/Parent"]
                    form.Fields = Array([*list(form.Fields), copy])
                page_annots = page_obj.get("/Annots")
                page_obj.Annots = Array([*(list(page_annots) if isinstance(page_annots, Array) else []), copy])
                created.append(_key(copy))
    return created


# --- Eigenschaften --------------------------------------------------------------------------------------------
def set_properties(document: EditorDocument, history: History, key: str, changes: dict) -> None:
    """Eigenschaften des Feldes zum Widget ``key`` ändern (``PROPERTIES``); ``export`` gilt nur für dieses
    Widget (Kontrollkästchen, Option einer Gruppe). Danach passen die Erscheinungsbilder aller Widgets."""
    _check(document)
    unknown = set(changes) - set(PROPERTIES)
    if unknown:
        raise UnsupportedEdit("Unbekannte Eigenschaft: " + ", ".join(sorted(unknown)))
    item, annot, annots, kind, page = _locate(document, key)
    holder = item.obj
    pdf = document.pdf
    form = pdf.Root.AcroForm
    view = _FieldView(form, holder)
    flags = view.flags
    plan: dict = {}
    if "name" in changes:
        name = _clean_name(changes["name"])
        current = str(item.fully_qualified_name)
        prefix = current.rsplit(".", 1)[0] + "." if "." in current else ""
        if prefix + name != current and prefix + name in _names(document):
            raise UnsupportedEdit(f"Ein Feld »{prefix + name}« gibt es schon.")
        plan["name"] = name
    if "tooltip" in changes:
        plan["tooltip"] = str(changes["tooltip"]).strip()
    for flag_name, bit in (("required", forms.FLAG_REQUIRED), ("readOnly", forms.FLAG_READ_ONLY)):
        if flag_name in changes:
            flags = flags | bit if changes[flag_name] else flags & ~bit
    value = holder.get("/V")
    text_value = str(value) if isinstance(value, String) else ""
    if "multiline" in changes:
        if kind != TEXT:
            raise UnsupportedEdit("Mehrzeilig gibt es nur bei Textfeldern.")
        flags = flags | forms.FLAG_MULTILINE if changes["multiline"] else flags & ~forms.FLAG_MULTILINE
        if not changes["multiline"] and "\n" in text_value:
            plan["value"] = text_value.replace("\r\n", "\n").replace("\n", " ")
    if "maxLength" in changes:
        if kind != TEXT:
            raise UnsupportedEdit("Eine Zeichenzahl gibt es nur bei Textfeldern.")
        length = int(changes["maxLength"] or 0)
        if length < 0 or length > 100000:
            raise UnsupportedEdit("Die Zeichenzahl muss zwischen 0 (beliebig) und 100000 liegen.")
        if length and len(plan.get("value", text_value)) > length:
            raise UnsupportedEdit(f"Der eingetragene Text ist länger als {length} Zeichen – bitte erst kürzen.")
        plan["maxLength"] = length
    if "fontSize" in changes:
        if kind not in (TEXT, COMBO, LIST):
            raise UnsupportedEdit("Eine Schriftgröße gibt es nur bei Text-, Auswahl- und Listenfeldern.")
        size = float(changes["fontSize"] or 0)
        if size < 0 or size > 144:
            raise UnsupportedEdit("Die Schriftgröße muss zwischen 0 (automatisch) und 144 pt liegen.")
        plan["fontSize"] = size
    if "align" in changes:
        if kind not in (TEXT, COMBO):
            raise UnsupportedEdit("Eine Ausrichtung gibt es nur bei Text- und Auswahlfeldern.")
        if changes["align"] not in ALIGNS:
            raise UnsupportedEdit("Unbekannte Ausrichtung.")
        plan["align"] = ALIGNS.index(changes["align"])
    if "options" in changes:
        if kind not in (COMBO, LIST):
            raise UnsupportedEdit("Optionen gibt es nur bei Dropdown- und Listenfeldern.")
        entries = [" ".join(str(entry).split()) for entry in changes["options"]]
        entries = list(dict.fromkeys(entry for entry in entries if entry))
        if not entries:
            raise UnsupportedEdit("Bitte mindestens eine Option angeben.")
        if len(entries) > MAX_OPTIONS:
            raise UnsupportedEdit(f"Höchstens {MAX_OPTIONS} Optionen.")
        plan["options"] = entries
    if "export" in changes:
        if kind not in (CHECKBOX, RADIO):
            raise UnsupportedEdit("Einen Exportwert gibt es nur bei Kontrollkästchen und Optionsfeldern.")
        export = _clean_export(changes["export"])
        old = _export(annot)
        if export != old and kind == RADIO and export in {_export(widget) for widget in annots if widget.objgen != annot.objgen}:
            raise UnsupportedEdit("Diesen Exportwert hat schon eine andere Option der Gruppe.")
        if export != old:
            plan["export"] = (old, export)
    for look in ("border", "background"):
        if look in changes:
            plan[look] = bool(changes[look])
    plan["flags"] = flags
    with commands.record(document, history, "Feldeigenschaften ändern", pages=(page,)) as rec:
        _keep(rec, holder, "/T", "/TU", "/Ff", "/DA", "/Q", "/MaxLen", "/Opt", "/V", "/DV")
        for widget in annots:
            _keep(rec, widget, "/AP", "/AS", "/MK")
        if "name" in plan:
            holder.T = String(plan["name"])
        if "tooltip" in plan:
            if plan["tooltip"]:
                holder.TU = String(plan["tooltip"])
            elif "/TU" in holder:
                del holder["/TU"]
        if plan["flags"] != view.flags:
            holder.Ff = plan["flags"]
        if "value" in plan:
            holder.V = String(plan["value"])
        if "maxLength" in plan:
            if plan["maxLength"]:
                holder.MaxLen = plan["maxLength"]
            elif "/MaxLen" in holder:
                del holder["/MaxLen"]
        if "fontSize" in plan:
            holder.DA = String(_with_size(view.default_appearance.decode("latin-1", "replace"), plan["fontSize"]))
        if "align" in plan:
            holder.Q = plan["align"]
        if "options" in plan:
            holder.Opt = Array([String(entry) for entry in plan["options"]])
            current = holder.get("/V")
            if isinstance(current, String) and str(current) and str(current) not in plan["options"]:
                holder.V = String("")
            default = holder.get("/DV")
            if isinstance(default, String) and str(default) not in plan["options"]:
                del holder["/DV"]
        if "export" in plan:
            old, new = plan["export"]
            _rename_state(annot, "/" + old if old else "", "/" + new)
            state_holder = holder if kind == RADIO else annot
            if isinstance(state_holder.get("/V"), Name) and str(state_holder.V) == "/" + old:
                state_holder.V = Name("/" + new)
        for look, entry, color in (("border", "/BC", BORDER), ("background", "/BG", BACKGROUND)):
            if look in plan:
                for widget in annots:
                    mk = widget.get("/MK")
                    fresh = Dictionary({str(k): v for k, v in mk.items()}) if isinstance(mk, Dictionary) else Dictionary()
                    if plan[look]:
                        fresh[entry] = Array(list(color))
                    elif entry in fresh:
                        del fresh[entry]
                    widget.MK = fresh
        # Sichtbares geändert: Erscheinungsbilder neu (fremde Kästchen nur bei neuem Rahmen/Hintergrund)
        looks = any(name in plan for name in ("value", "maxLength", "fontSize", "align", "options", "border", "background")) or "multiline" in changes
        if looks:
            _refresh(pdf, form, holder, annots, kind, buttons="border" in plan or "background" in plan)


def _with_size(da: str, size: float) -> str:
    """/DA mit neuer Schriftgröße (Schrift und Farbe bleiben)."""
    match = re.search(r"(/[^\s/\[\]()<>{}%]+)\s+[\d.]+\s+Tf", da)
    font = match.group(1) if match else "/Helv"
    color = re.search(r"([\d.]+\s+[\d.]+\s+[\d.]+\s+rg|[\d.]+\s+g)(?:\s|$)", da)
    return f"{font} {fmt(size)} Tf {color.group(1) if color else '0 g'}"


def _rename_state(annot, old: str, new: str) -> None:
    """Zustand »ein« eines Kästchens umbenennen (Erscheinungsbilder und aktueller Zustand)."""
    ap = annot.get("/AP")
    if isinstance(ap, Dictionary):
        fresh = Dictionary()
        for appearance_key, states in ap.items():
            if isinstance(states, Dictionary):
                fresh[str(appearance_key)] = Dictionary({(new if str(state) == old or (not old and str(state) != "/Off") else str(state)): stream for state, stream in states.items()})
            else:
                fresh[str(appearance_key)] = states
        annot.AP = fresh
    if old and isinstance(annot.get("/AS"), Name) and str(annot.AS) == old:
        annot.AS = Name(new)
