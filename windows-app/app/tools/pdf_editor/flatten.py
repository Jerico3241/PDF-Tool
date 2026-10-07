"""Reduzieren: Formularfelder und Kommentare fest in die Seiten übernehmen.

Danach sind sie Teil des Seiteninhalts – sie sehen in jedem Programm gleich aus, lassen sich aber
nicht mehr ändern, ausfüllen oder einzeln löschen. Üblich vor dem Weitergeben ausgefüllter Formulare.

Ablauf je Anmerkung (nach PDF-Norm, Algorithmus 8.1): das normale Erscheinungsbild (``/AP /N``, bei
Kontrollkästchen und Optionsfeldern der Zustand ``/AS``) wird als Formular-XObject in die Seite
gezeichnet – mit der Abbildung von ``/BBox`` × ``/Matrix`` auf ``/Rect`` und der Deckkraft ``/CA`` der
Anmerkung. Danach verschwindet die Anmerkung, bei Formularfeldern auch das Feld (und leere
Elternfelder); ohne verbleibende Felder entfällt das Formular.

Nicht übernommen werden: ausgeblendete Anmerkungen (``Hidden``/``NoView``) – sie werden nur
entfernt –, Signaturfelder (bleiben Felder) und Anmerkungen ohne Erscheinungsbild (bleiben, wie sie
sind; gezählt in ``skipped``). Links bleiben immer erhalten. Ein Schritt für Rückgängig.
"""

from __future__ import annotations

from dataclasses import dataclass

import pikepdf
from pikepdf import Array, Dictionary, Name

from . import forms
from .commands import History, group, own_resources, record
from .content import append_content, fmt
from .document import EditorDocument
from .geometry import normalize

FLAG_HIDDEN = 2
FLAG_NOVIEW = 32
XOBJECT_PREFIX = "/PTFlat"
STATE_PREFIX = "/PTFlatGS"
KEEP_ALWAYS = (Name.Link, Name.Popup)


@dataclass
class FlattenResult:
    fields: int = 0
    comments: int = 0
    hidden: int = 0  # ausgeblendete Anmerkungen (entfernt, nicht gezeichnet)
    skipped: int = 0  # ohne Erscheinungsbild bzw. Signaturfelder – unverändert

    @property
    def total(self) -> int:
        return self.fields + self.comments


def count(document: EditorDocument) -> dict:
    """Was sich reduzieren ließe: Formularfelder (Widgets) und Kommentare."""
    widgets = comments = 0
    for page in document.pdf.pages:
        annots = page.obj.get("/Annots")
        if not isinstance(annots, Array):
            continue
        for annot in annots:
            if not isinstance(annot, Dictionary):
                continue
            subtype = annot.get("/Subtype")
            if subtype == Name.Widget:
                widgets += 1
            elif subtype not in KEEP_ALWAYS:
                comments += 1
    return {"fields": widgets, "comments": comments}


def flatten(document: EditorDocument, history: History, *, fields: bool = True, comments: bool = True, pages: list[int] | None = None) -> FlattenResult:
    document.ensure_editable()
    pdf = document.pdf
    indexes = sorted(set(pages)) if pages is not None else list(range(document.page_count))
    result = FlattenResult()
    if not (fields or comments) or not indexes:
        return result
    with group(document, history, "Reduzieren"):
        if fields:
            _refresh_appearances(document, history)
        with record(document, history, "Reduzieren", pages=tuple(indexes)) as rec:
            rec.root(("/AcroForm",))
            removed_widgets: set[tuple[int, int]] = set()
            for index in indexes:
                page = rec.page(index)
                annots = page.get("/Annots")
                if not isinstance(annots, Array):
                    continue
                kept, ops, flattened = [], [], set()
                resources = None
                for annot in annots:
                    if not isinstance(annot, Dictionary):
                        kept.append(annot)
                        continue
                    subtype = annot.get("/Subtype")
                    is_widget = subtype == Name.Widget
                    wanted = (is_widget and fields) or (comments and not is_widget and subtype not in KEEP_ALWAYS)
                    if not wanted:
                        kept.append(annot)
                        continue
                    if is_widget and _field_type(annot) == Name.Sig:
                        result.skipped += 1
                        kept.append(annot)
                        continue
                    flags = int(annot.get("/F", 0) or 0)
                    if flags & (FLAG_HIDDEN | FLAG_NOVIEW):
                        result.hidden += 1
                        flattened.add(_key(annot))
                        if is_widget:
                            removed_widgets.add(_key(annot))
                        continue
                    stream = _appearance(annot)
                    placement = _placement(annot, stream) if stream is not None else None
                    if placement is None:
                        result.skipped += 1
                        kept.append(annot)
                        continue
                    if resources is None:
                        resources = own_resources(page, pdf, "/XObject", "/ExtGState")
                    name = _free_name(resources.XObject, XOBJECT_PREFIX)
                    resources.XObject[name] = _as_form(pdf, stream)
                    state = ""
                    alpha = _alpha(annot)
                    if alpha < 0.999:
                        state = _free_name(resources.ExtGState, STATE_PREFIX)
                        resources.ExtGState[state] = Dictionary(Type=Name.ExtGState, CA=alpha, ca=alpha)
                    matrix = " ".join(fmt(value) for value in placement)
                    ops.append(f"q {state + ' gs ' if state else ''}{matrix} cm {name} Do Q")
                    flattened.add(_key(annot))
                    if is_widget:
                        result.fields += 1
                        removed_widgets.add(_key(annot))
                    else:
                        result.comments += 1
                # Notizfenster reduzierter Kommentare gehen mit
                kept = [a for a in kept if not (isinstance(a, Dictionary) and a.get("/Subtype") == Name.Popup and _key(a.get("/Parent")) in flattened)]
                if ops:
                    append_content(pdf, page, "\n".join(ops).encode("latin-1"))
                if flattened:
                    if kept:
                        page.Annots = Array(kept)
                    else:
                        del page["/Annots"]
            if removed_widgets:
                _remove_fields(pdf, rec, removed_widgets)
    return result


# --- Hilfen ------------------------------------------------------------------------------------------------------
def _refresh_appearances(document: EditorDocument, history: History) -> None:
    """Verlangt das Formular, dass der Betrachter Erscheinungsbilder neu aufbaut (``NeedAppearances``),
    zeigen die gespeicherten womöglich alte Werte – dann zuerst für jedes Feld neu erzeugen."""
    form = document.pdf.Root.get("/AcroForm")
    if not (isinstance(form, Dictionary) and bool(form.get("/NeedAppearances", False))):
        return
    for info in forms.list_fields(document):
        if info.editable and info.kind in (forms.TEXT, forms.COMBO, forms.LIST):
            try:
                forms.set_value(document, history, info.key, info.value)
            except Exception:  # noqa: BLE001 - dann bleibt das gespeicherte Erscheinungsbild
                continue


def _field_type(annot: Dictionary):
    node, depth = annot, 0
    while isinstance(node, Dictionary) and depth < 32:
        if "/FT" in node:
            return node.FT
        node = node.get("/Parent")
        depth += 1
    return None


def _appearance(annot: Dictionary):
    ap = annot.get("/AP")
    if not isinstance(ap, Dictionary):
        return None
    normal = ap.get("/N")
    if isinstance(normal, Dictionary) and not isinstance(normal, pikepdf.Stream):
        state = annot.get("/AS")
        normal = normal.get(state) if state is not None else None
    return normal if isinstance(normal, pikepdf.Stream) else None


def _placement(annot: Dictionary, stream: pikepdf.Stream):
    """Matrix A, die die mit ``/Matrix`` abgebildete ``/BBox`` auf ``/Rect`` legt (ohne ``/Matrix`` –
    die wendet ``Do`` selbst an)."""
    try:
        rect = normalize(tuple(float(v) for v in annot.Rect))
        bbox = [float(v) for v in stream.get("/BBox", [])]
        matrix = [float(v) for v in stream.get("/Matrix", [1, 0, 0, 1, 0, 0])]
    except (TypeError, ValueError, AttributeError):
        return None
    if len(bbox) != 4 or len(matrix) != 6:
        return None
    a, b, c, d, e, f = matrix
    corners = [(a * x + c * y + e, b * x + d * y + f) for x in (bbox[0], bbox[2]) for y in (bbox[1], bbox[3])]
    x0, x1 = min(p[0] for p in corners), max(p[0] for p in corners)
    y0, y1 = min(p[1] for p in corners), max(p[1] for p in corners)
    if x1 - x0 < 1e-6 or y1 - y0 < 1e-6 or rect[2] - rect[0] < 1e-6 or rect[3] - rect[1] < 1e-6:
        return None
    sx = (rect[2] - rect[0]) / (x1 - x0)
    sy = (rect[3] - rect[1]) / (y1 - y0)
    return (sx, 0.0, 0.0, sy, rect[0] - x0 * sx, rect[1] - y0 * sy)


def _as_form(pdf: pikepdf.Pdf, stream: pikepdf.Stream) -> pikepdf.Stream:
    """Das Erscheinungsbild als Formular-XObject – fehlt ``/Subtype /Form``, eine Kopie mit den
    nötigen Einträgen (das Original bleibt unverändert)."""
    if stream.get("/Subtype") == Name.Form:
        return stream
    copy = pdf.make_stream(stream.read_bytes())
    for key, value in stream.items():
        if key not in ("/Length", "/Filter", "/DecodeParms", "/DL"):
            copy[key] = value
    copy.Type = Name.XObject
    copy.Subtype = Name.Form
    return copy


def _alpha(annot: Dictionary) -> float:
    try:
        return max(0.0, min(1.0, float(annot.get("/CA", 1.0))))
    except (TypeError, ValueError):
        return 1.0


def _free_name(container: Dictionary, prefix: str) -> str:
    number = 1
    while f"{prefix}{number}" in container:
        number += 1
    return f"{prefix}{number}"


def _key(obj):
    try:
        return obj.objgen if obj.is_indirect else id(obj)
    except AttributeError:
        return id(obj)


def _remove_fields(pdf: pikepdf.Pdf, rec, widgets: set) -> None:
    """Reduzierte Widgets aus dem Formular nehmen: aus ``/Kids`` ihrer Felder, leere Felder aus ihren
    Eltern bzw. aus ``/Fields``; ohne Felder entfällt das Formular."""
    form = pdf.Root.get("/AcroForm")
    if not isinstance(form, Dictionary):
        return

    def prune(items, depth: int = 0) -> list:
        kept = []
        for item in items:
            if not isinstance(item, Dictionary) or depth > 32:
                kept.append(item)
                continue
            if _key(item) in widgets:
                continue  # Feld und Widget in einem (oder Widget als Kind)
            kids = item.get("/Kids")
            if isinstance(kids, Array):
                remaining = prune(list(kids), depth + 1)
                if len(remaining) != len(kids):
                    if not remaining:
                        continue  # Feld ohne Widgets
                    rec.object(item, ("/Kids",))
                    item.Kids = Array(remaining)
            kept.append(item)
        return kept

    fields = form.get("/Fields")
    remaining = prune(list(fields)) if isinstance(fields, Array) else []
    if not remaining:
        del pdf.Root["/AcroForm"]
        return
    fresh = Dictionary({key: value for key, value in form.items()})
    fresh.Fields = Array(remaining)
    pdf.Root.AcroForm = pdf.make_indirect(fresh)
