"""Objekte gemeinsam bearbeiten: Text (Segmente, Wörter), Bilder und Vektorobjekte einer Seite – verschieben,
drehen, skalieren, löschen, formatieren, duplizieren, Ebene ändern – und die Zwischenablage für Objekte.

* **Ein Schritt je Bedienung:** Gemischte Auswahlen (z. B. Text und Bild) laufen als ``commands.group`` –
  Rückgängig nimmt alles auf einmal zurück. Jede Teiländerung wird wie gewohnt geprüft (Darstellung nur im
  betroffenen Bereich verändert, Text der Seite gleich bzw. wie gewünscht).
* **Kennungen** wie in der Oberfläche: Text ``<Seite>-<n>`` bzw. ``<Seite>-<n>/w<k>`` (Wort), Bild
  ``<Seite>-i<n>``, Vektorobjekt ``<Seite>-v<n>``.
* **Zwischenablage:** Kopieren erzeugt eine kleine PDF mit einer Seite – die kopierten Objekte mit ihrem
  Grafikzustand und genau den Ressourcen, die sie brauchen (Schriften, Bilder, ExtGStates …). Einfügen
  übernimmt sie in eine Seite desselben oder eines anderen Dokuments (eigene Ressourcennamen, keine
  Kollisionen); Lage und Ausrichtung bleiben in der Anzeige gleich, auch zwischen unterschiedlich gedrehten
  Seiten. Text, der nicht nativ kopiert werden kann, wird beim Einfügen neu gesetzt.
"""

from __future__ import annotations

import io
import uuid
from dataclasses import dataclass, field

import pikepdf
from pikepdf import Array, Dictionary, Name

from . import commands, images, objects, textedit, vectors
from .commands import History
from .content import Matrix, PageContent, append_content, apply, page_fonts
from .document import EditorDocument, inherited
from .errors import ReadOnlyDocument, UnsupportedEdit
from .geometry import PageGeometry, Rect, inflate, normalize, union

TEXT, IMAGE, PATH = "text", "image", "path"
PASTE_PREFIX = "PTC"  # Ressourcennamen eingefügter Objekte
NUDGE = 12.0  # Einfügen an derselben Stelle: so weit versetzt (Anzeige-Punkte)


@dataclass(frozen=True)
class Ref:
    ident: str
    kind: str
    index: int  # Bild- bzw. Pfadnummer (−1 bei Text)


def parse(ident: str) -> Ref:
    _page, _sep, rest = str(ident).partition("-")
    if rest[:1] == "i" and rest[1:].isdigit():
        return Ref(ident, IMAGE, int(rest[1:]))
    if rest[:1] == "v" and rest[1:].isdigit():
        return Ref(ident, PATH, int(rest[1:]))
    return Ref(ident, TEXT, -1)


def _split(idents) -> tuple[list[Ref], list[Ref]]:
    refs = [parse(ident) for ident in idents]
    return [ref for ref in refs if ref.kind == TEXT], [ref for ref in refs if ref.kind != TEXT]


def _others(document: EditorDocument, page: int, refs: list[Ref]) -> tuple[dict, dict]:
    """Bilder und Vektorobjekte der Seite zu den Kennungen – alle müssen änderbar sein."""
    pictures = {item.index: item for item in images.list_images(document, page)} if any(ref.kind == IMAGE for ref in refs) else {}
    paths = {item.index: item for item in vectors.list_paths(document, page)} if any(ref.kind == PATH for ref in refs) else {}
    for ref in refs:
        item = (pictures if ref.kind == IMAGE else paths).get(ref.index)
        if item is None:
            raise UnsupportedEdit("Das Objekt ist nicht mehr vorhanden. Bitte erneut auswählen.")
        if not item.editable:
            raise UnsupportedEdit(item.reason or "Dieses Objekt lässt sich nicht bearbeiten.")
    return pictures, paths


def bounds_of(document: EditorDocument, found: objects.PageObjects, idents) -> dict[str, Rect]:
    """Lage (Seitenkoordinaten) je Kennung."""
    texts, others = _split(idents)
    result: dict[str, Rect] = {}
    for ref in texts:
        _segment, first, last = found.target(ref.ident)
        result[ref.ident] = found.bounds_of(first, last)
    if others:
        pictures, paths = _others(document, found.page, others)
        for ref in others:
            result[ref.ident] = (pictures if ref.kind == IMAGE else paths)[ref.index].bounds
    return result


def _ordered(content: PageContent, refs: list[Ref]) -> list[Ref]:
    """Von hinten nach vorn im Inhalt – Änderungen verschieben dann keine noch offenen Positionen."""
    def position(ref: Ref) -> int:
        return content.images[ref.index].index if ref.kind == IMAGE else content.paths[ref.index].index

    return sorted(refs, key=position, reverse=True)


def _check_others(document: EditorDocument, history: History, page: int, refs: list[Ref], change, title: str, area: Rect, *, drop: bool = False) -> None:
    """Bilder/Vektorobjekte ändern (``change(content, op, ref)``) – ein Schritt, danach geprüft."""
    before, before_text = objects._snapshot(document, page)  # noqa: SLF001
    try:
        with commands.record(document, history, title, pages=(page,)) as rec:
            obj = rec.page(page)
            content = PageContent(document.pdf, obj, page_fonts(obj))
            names = []
            for ref in _ordered(content, refs):
                op = content.images[ref.index] if ref.kind == IMAGE else content.paths[ref.index]
                change(content, op, ref)
                if drop and ref.kind == IMAGE and op.name:
                    names.append(op.name)
            content.commit()
            for name in names:
                images.drop_unused_xobject(document.pdf, obj, name)
            rec.info["mode"] = objects.NATIVE
            objects._verify(document, page, before, before_text, area, objects.ObjectOutcome(objects.NATIVE, area), None, None, wide=True)  # noqa: SLF001
            rec.fresh = True
    except objects._NotNative as reason:  # noqa: SLF001
        raise UnsupportedEdit("Das lässt sich hier nicht sicher ändern. " + str(reason)) from reason


def _corners(box: Rect, matrix: Matrix) -> Rect:
    out = None
    for x, y in ((box[0], box[1]), (box[2], box[1]), (box[0], box[3]), (box[2], box[3])):
        tx, ty = apply(matrix, x, y)
        out = union(out, (tx, ty, tx, ty))
    return out


# --- Verschieben, Umformen, Löschen ------------------------------------------------------------------------------
def move_each(document: EditorDocument, history: History, found: objects.PageObjects, shifts: dict[str, tuple[float, float]], *, title: str = "Verschieben") -> Rect:
    """Objekte jeweils um ihre Verschiebung (Seitenpunkte) – ein Schritt. Liefert den neuen Bereich."""
    texts, others = _split(shifts)
    boxes = bounds_of(document, found, shifts)
    area = None
    for ident, (dx, dy) in shifts.items():
        box = boxes[ident]
        area = union(area, union(box, (box[0] + dx, box[1] + dy, box[2] + dx, box[3] + dy)))
    with commands.group(document, history, title):
        if texts:
            objects.move_each(document, history, found, {ref.ident: shifts[ref.ident] for ref in texts}, title=title)
        if others:
            moved = {ref.ident: shifts[ref.ident] for ref in others}
            _others(document, found.page, others)

            def change(content, op, ref) -> None:
                matrix = (1.0, 0.0, 0.0, 1.0, *moved[ref.ident])
                if ref.kind == IMAGE:
                    images.transform_in(content, op, matrix)
                else:
                    vectors.transform(content, op, matrix)

            _check_others(document, history, found.page, others, change, title, inflate(area, 2.0))
    return area


def transform(document: EditorDocument, history: History, found: objects.PageObjects, idents: list[str], matrix: Matrix, *, title: str = "Drehen") -> Rect:
    """Objekte im Seitenraum umformen (Drehung um einen Punkt, Skalierung …) – ein Schritt."""
    texts, others = _split(idents)
    boxes = bounds_of(document, found, idents)
    area = None
    for box in boxes.values():
        area = union(area, union(box, _corners(box, matrix)))
    with commands.group(document, history, title):
        if texts:
            objects.transform_text(document, history, found, [ref.ident for ref in texts], matrix, title=title)
        if others:
            _others(document, found.page, others)

            def change(content, op, ref) -> None:
                if ref.kind == IMAGE:
                    images.transform_in(content, op, matrix)
                else:
                    vectors.transform(content, op, matrix)

            _check_others(document, history, found.page, others, change, title, inflate(area, 2.0))
    return area


def delete(document: EditorDocument, history: History, found: objects.PageObjects, idents: list[str]) -> Rect:
    texts, others = _split(idents)
    boxes = bounds_of(document, found, idents)
    area = None
    for box in boxes.values():
        area = union(area, box)
    title = "Objekte löschen" if len(idents) > 1 else ("Text löschen" if texts else ("Bild löschen" if others[0].kind == IMAGE else "Objekt löschen"))
    with commands.group(document, history, title):
        if texts:
            objects.delete(document, history, found, [ref.ident for ref in texts])
        if others:
            _others(document, found.page, others)

            def change(content, op, ref) -> None:
                if ref.kind == IMAGE:
                    images.delete_in(content, op)
                else:
                    vectors.delete(content, op)

            _check_others(document, history, found.page, others, change, title, inflate(area, 2.0), drop=True)
    return area


# --- Formatieren -----------------------------------------------------------------------------------------------------
def style(document: EditorDocument, history: History, found: objects.PageObjects, idents: list[str], name: str, value) -> Rect:
    """Eine Eigenschaft für die Auswahl ändern – je Objektart passend:

    * ``color``: Textfarbe; bei Vektorobjekten die Strich- bzw. (ohne Strich) die Füllfarbe
    * ``stroke``/``fill``/``width``: Strichfarbe, Füllfarbe, Linienstärke (nur Vektorobjekte)
    * ``size``/``spacing``: Schriftgröße, Zeichenabstand (nur Text)
    * ``family``/``bold``/``italic``: Schrift (nur Text, neu gesetzt)
    * ``opacity``: Deckkraft 0–1 (alle)
    """
    texts, others = _split(idents)
    boxes = bounds_of(document, found, idents)
    area = None
    for box in boxes.values():
        area = union(area, box)
    with commands.group(document, history, "Formatieren"):
        if texts:
            text_ids = [ref.ident for ref in texts]
            if name in ("size", "spacing", "color"):
                objects.restyle(document, history, found, text_ids, **{name: value})
            elif name == "opacity":
                objects.set_opacity(document, history, found, text_ids, float(value))
            elif name in ("family", "bold", "italic"):
                objects.refont(document, history, found, text_ids, **{name: value})
            elif name not in ("stroke", "fill", "width"):
                raise UnsupportedEdit("Diese Eigenschaft lässt sich nicht ändern.")
        if others:
            _pictures, paths = _others(document, found.page, others)
            if name == "opacity" or any(ref.kind == PATH for ref in others) and name in ("color", "stroke", "fill", "width"):
                state = {}

                def change(content, op, ref) -> None:
                    if name == "opacity":
                        if "name" not in state:
                            state["name"] = vectors.alpha_state(document.pdf, document.pdf.pages[found.page].obj, float(value))
                        if ref.kind == IMAGE:
                            images.alpha_in(content, op, state["name"])
                        else:
                            vectors.restyle(content, op, state=state["name"])
                        return
                    if ref.kind != PATH:
                        return
                    item = paths[ref.index]
                    if name == "width":
                        vectors.restyle(content, op, width=float(value))
                    elif name == "fill" or (name == "color" and item.stroke is None):
                        vectors.restyle(content, op, fill=tuple(value))
                    else:
                        vectors.restyle(content, op, stroke=tuple(value))

                _check_others(document, history, found.page, others, change, "Formatieren", inflate(area, 2.0 + (float(value) if name == "width" else 0.0)))
    return area


# --- Duplizieren, Ebene -------------------------------------------------------------------------------------------
def _snippets(document: EditorDocument, found: objects.PageObjects, content: PageContent, refs: list[Ref]) -> tuple[list[bytes], list[dict]]:
    """Anweisungen (je Objekt eigenständig, Seitenraum) und Texte, die neu gesetzt werden müssen."""
    parts: list[bytes] = []
    reset: list[dict] = []
    for ref in refs:
        if ref.kind == TEXT:
            segment, first, last = found.target(ref.ident)
            if segment.native:
                parts.append(objects._copy(content, found, first, last, (0.0, 0.0)))  # noqa: SLF001
            else:
                reset.append(_text_item(document, found, segment, first, last))
        elif ref.kind == IMAGE:
            parts.append(pikepdf.unparse_content_stream(images.snippet(content, content.images[ref.index])))
        else:
            parts.append(pikepdf.unparse_content_stream(vectors.snippet(content, content.paths[ref.index])))
    return parts, reset


def _text_item(document: EditorDocument, found: objects.PageObjects, segment, first: int, last: int) -> dict:
    style = textedit.style_of(segment.font)
    return {"text": found.text_of(first, last), "origin": found.glyphs[first].origin, "size": segment.size, "color": tuple(segment.color), "angle": segment.angle, "family": style.family, "bold": style.bold, "italic": style.italic}


def duplicate(document: EditorDocument, history: History, found: objects.PageObjects, idents: list[str], offset: tuple[float, float]) -> Rect:
    """Kopien der Auswahl um ``offset`` (Seitenpunkte) versetzt – ein Schritt."""
    objects._check_revision(document, found)  # noqa: SLF001
    refs = [parse(ident) for ident in idents]
    if not refs:
        raise UnsupportedEdit("Es ist nichts ausgewählt.")
    texts, others = _split(idents)
    if others:
        _others(document, found.page, others)
    boxes = bounds_of(document, found, idents)
    dx, dy = offset
    area = None
    for box in boxes.values():
        area = union(area, (box[0] + dx, box[1] + dy, box[2] + dx, box[3] + dy))
    page = found.page
    text = " ".join(found.text_of(*found.target(ref.ident)[1:]) for ref in texts)
    before, before_text = objects._snapshot(document, page)  # noqa: SLF001
    title = "Duplizieren"
    try:
        with commands.record(document, history, title, pages=(page,)) as rec:
            obj = rec.page(page)
            content = PageContent(document.pdf, obj, page_fonts(obj))
            parts, reset = _snippets(document, found, content, refs)
            if parts:
                append_content(document.pdf, obj, f"1 0 0 1 {dx:.4f} {dy:.4f} cm\n".encode("latin-1") + b"\n".join(parts))
            for item in reset:
                _set_text(document, page, item, (item["origin"][0] + dx, item["origin"][1] + dy))
            rec.info["mode"] = objects.NATIVE if not reset else objects.RECONSTRUCTED
            objects._verify_added(document, page, before, before_text, inflate(area, 2.0), text) if text else _verify_area(document, page, before, before_text, area)  # noqa: SLF001
            rec.fresh = True
    except objects._NotNative as reason:  # noqa: SLF001
        raise UnsupportedEdit("Das lässt sich hier nicht sicher duplizieren. " + str(reason)) from reason
    return area


def _set_text(document: EditorDocument, page: int, item: dict, origin: tuple[float, float]) -> None:
    from .fonts import Style

    try:
        font = textedit.new_font(document, page, Style(item["family"], item["bold"], item["italic"]), item["text"])
    except textedit._Rejected as rejected:  # noqa: SLF001
        raise objects._NotNative(rejected.reason) from rejected  # noqa: SLF001
    objects._append_text(document, page, font, item["size"], item["color"], origin, item["angle"], item["text"])  # noqa: SLF001


def _verify_area(document: EditorDocument, page: int, before, before_text: str, area: Rect) -> None:
    """Nur im Bereich ``area`` verändert, Text der Seite gleich."""
    objects._verify(document, page, before, before_text, area, objects.ObjectOutcome(objects.NATIVE, area), None, None, wide=True)  # noqa: SLF001


def arrange(document: EditorDocument, history: History, found: objects.PageObjects, idents: list[str], front: bool) -> Rect:
    """Bilder und Vektorobjekte ganz nach vorn bzw. ganz nach hinten legen (Reihenfolge untereinander bleibt)."""
    refs = [parse(ident) for ident in idents]
    if not refs or any(ref.kind == TEXT for ref in refs):
        raise UnsupportedEdit("Die Ebene lässt sich nur für Bilder und Vektorobjekte ändern.")
    _others(document, found.page, refs)
    page = found.page
    area = None
    for box in bounds_of(document, found, idents).values():
        area = union(area, box)
    title = "In den Vordergrund" if front else "In den Hintergrund"
    listed = {item.index for item in vectors.list_paths(document, page)}  # sichtbare Pfade ohne Hintergründe
    before, before_text = objects._snapshot(document, page)  # noqa: SLF001
    try:
        with commands.record(document, history, title, pages=(page,)) as rec:
            obj = rec.page(page)
            content = PageContent(document.pdf, obj, page_fonts(obj))
            ordered = sorted(refs, key=lambda ref: content.images[ref.index].index if ref.kind == IMAGE else content.paths[ref.index].index)
            snippets = [images.snippet(content, content.images[ref.index]) if ref.kind == IMAGE else vectors.snippet(content, content.paths[ref.index]) for ref in ordered]
            # Ganz nach hinten heißt: hinter alle Objekte – aber vor Hintergrundflächen der Seite (sonst verschwände
            # die Auswahl unter einer seitenfüllenden Fläche). Die Stelle liegt vor allen zu löschenden Anweisungen.
            first = min([show.index for show in content.shows] + [op.index for op in content.images] + [op.start for number, op in enumerate(content.paths) if number in listed] + [len(content.instructions)])
            position = 0 if front else _back_position(content.instructions, first)
            for ref in reversed(ordered):
                if ref.kind == IMAGE:
                    images.delete_in(content, content.images[ref.index])
                else:
                    vectors.delete(content, content.paths[ref.index])
            if front:
                content.commit()
                append_content(document.pdf, obj, b"\n".join(pikepdf.unparse_content_stream(part) for part in snippets))
            else:
                content.instructions[position:position] = [ins for part in snippets for ins in part]
                content.commit()
            # Geprüft: außerhalb der Auswahl unverändert, Text der Seite gleich
            _verify_area(document, page, before, before_text, inflate(area, 2.0))
            rec.info["mode"] = objects.NATIVE
            rec.fresh = True
    except objects._NotNative as reason:  # noqa: SLF001
        raise UnsupportedEdit("Die Ebene lässt sich hier nicht sicher ändern. " + str(reason)) from reason
    return area


PATH_BUILD_OPS = {"m", "l", "c", "v", "y", "h", "re"}
PATH_END_OPS = {"S", "s", "f", "F", "f*", "B", "B*", "b", "b*", "n"}
BASE_CHANGERS = {"cm", "W", "W*", "gs"}  # ändern Koordinaten, Zuschnitt oder Transparenz für alles Folgende


def _back_position(instructions, first: int) -> int:
    """Letzte Stelle vor Anweisung ``first`` auf oberster Ebene: kein ``q`` offen, außerhalb von Text und
    Pfadaufbau, davor kein ``cm``/Zuschnitt/``gs`` auf oberster Ebene – dort eingefügte Objekte (mit eigenem
    Zustand) erscheinen genau wie zuvor. Gibt es keine solche Stelle, ganz am Anfang."""
    depth, text, building, position = 0, False, False, 0
    for i, ins in enumerate(instructions[:first]):
        op = images._operator(ins)  # noqa: SLF001
        if depth == 0 and not text and op in BASE_CHANGERS:
            break
        if op == "q":
            depth += 1
        elif op == "Q":
            depth = max(0, depth - 1)
        elif op == "BT":
            text = True
        elif op == "ET":
            text = False
        elif op in PATH_BUILD_OPS:
            building = True
        elif op in PATH_END_OPS:
            building = False
        if depth == 0 and not text and not building:
            position = i + 1
    return position


# --- Zwischenablage -----------------------------------------------------------------------------------------------
@dataclass
class Clip:
    """Kopierte Objekte einer Seite."""

    data: bytes  # PDF mit einer Seite (Objekte + Ressourcen); leer, wenn nur neu zu setzende Texte
    bounds: Rect  # Bereich auf der Quellseite (Seitenkoordinaten)
    crop: Rect  # sichtbarer Bereich der Quellseite
    rotation: int  # /Rotate der Quellseite
    text: str  # Klartext (System-Zwischenablage)
    items: list[dict] = field(default_factory=list)  # Texte, die beim Einfügen neu gesetzt werden
    source: tuple[str, int] = ("", -1)  # (Dokument, Seite)
    token: str = field(default_factory=lambda: uuid.uuid4().hex)
    count: int = 0  # Anzahl kopierter Objekte

    def view_bounds(self) -> Rect:
        return PageGeometry(self.crop, self.rotation).rect_to_view(self.bounds)


RESOURCE_OPERATORS = {"Tf": "/Font", "Do": "/XObject", "gs": "/ExtGState", "sh": "/Shading"}


def _needed(instructions) -> dict[str, set[str]]:
    """Ressourcen, auf die Anweisungen verweisen (Schriften, XObjects, ExtGStates, Farbräume, Muster …)."""
    needed: dict[str, set[str]] = {}
    for ins in instructions:
        if isinstance(ins, pikepdf.ContentStreamInlineImage):
            continue
        op = str(ins.operator)
        operands = list(ins.operands)
        if op in RESOURCE_OPERATORS and operands and isinstance(operands[0], Name):
            needed.setdefault(RESOURCE_OPERATORS[op], set()).add(str(operands[0]))
        elif op in ("cs", "CS") and operands and isinstance(operands[0], Name) and str(operands[0]) not in ("/DeviceGray", "/DeviceRGB", "/DeviceCMYK", "/Pattern"):
            needed.setdefault("/ColorSpace", set()).add(str(operands[0]))
        elif op in ("scn", "SCN") and operands and isinstance(operands[-1], Name):
            needed.setdefault("/Pattern", set()).add(str(operands[-1]))
    return needed


def copy(document: EditorDocument, found: objects.PageObjects, idents: list[str], source_id: str = "") -> Clip:
    """Auswahl in eine Zwischenablage-PDF kopieren (das Dokument bleibt unverändert)."""
    if not document.permissions.copy:
        raise ReadOnlyDocument("Die Berechtigungen dieses PDFs erlauben kein Kopieren von Inhalten.")
    if found.revision != document.revision:
        raise UnsupportedEdit("Die Auswahl ist nicht mehr aktuell. Bitte erneut auswählen.")
    refs = [parse(ident) for ident in idents]
    if not refs:
        raise UnsupportedEdit("Es ist nichts ausgewählt.")
    texts, others = _split(idents)
    if others:
        _others_readable(document, found.page, others)
    page = found.page
    obj = document.pdf.pages[page].obj
    content = PageContent(document.pdf, obj, page_fonts(obj))
    parts, reset = _snippets(document, found, content, refs)
    boxes = bounds_of_readable(document, found, idents)
    area = None
    for box in boxes.values():
        area = union(area, box)
    geo = document.geometry(page)
    text = "\n".join(found.text_of(*found.target(ref.ident)[1:]) for ref in texts)
    data = b""
    if parts:
        body = b"\n".join(parts)
        clip = pikepdf.new()
        clip.add_blank_page(page_size=(geo.crop[2] - geo.crop[0], geo.crop[3] - geo.crop[1]))
        page_obj = clip.pages[0].obj
        page_obj.MediaBox = Array([round(v, 4) for v in geo.crop])
        resources = inherited(obj, "/Resources")
        copied = Dictionary()
        for category, names in _needed(pikepdf.parse_content_stream(clip.make_stream(body))).items():
            source = resources.get(category) if isinstance(resources, Dictionary) else None
            if not isinstance(source, Dictionary):
                continue
            target = Dictionary()
            for name in sorted(names):
                if name in source:
                    target[name] = clip.copy_foreign(source[name])
            copied[category] = target
        page_obj.Resources = copied
        page_obj.Contents = clip.make_stream(body)
        buffer = io.BytesIO()
        clip.save(buffer)
        clip.close()
        data = buffer.getvalue()
    return Clip(data, area, geo.crop, geo.rotation, text, reset, (source_id, page), count=len(refs))


def _others_readable(document: EditorDocument, page: int, refs: list[Ref]) -> tuple[dict, dict]:
    """Wie ``_others``, aber nur lesen: Kopieren geht auch in schreibgeschützten Dokumenten (sofern erlaubt)."""
    pictures = {item.index: item for item in images.list_images(document, page)} if any(ref.kind == IMAGE for ref in refs) else {}
    paths = {item.index: item for item in vectors.list_paths(document, page)} if any(ref.kind == PATH for ref in refs) else {}
    for ref in refs:
        item = (pictures if ref.kind == IMAGE else paths).get(ref.index)
        if item is None:
            raise UnsupportedEdit("Das Objekt ist nicht mehr vorhanden. Bitte erneut auswählen.")
        if not item.editable and not document.read_only:
            raise UnsupportedEdit(item.reason or "Dieses Objekt lässt sich nicht kopieren.")
    return pictures, paths


def bounds_of_readable(document: EditorDocument, found: objects.PageObjects, idents) -> dict[str, Rect]:
    texts, others = _split(idents)
    result: dict[str, Rect] = {}
    for ref in texts:
        _segment, first, last = found.target(ref.ident)
        result[ref.ident] = found.bounds_of(first, last)
    if others:
        pictures, paths = _others_readable(document, found.page, others)
        for ref in others:
            result[ref.ident] = (pictures if ref.kind == IMAGE else paths)[ref.index].bounds
    return result


def affine(func) -> Matrix:
    """Affine Abbildung (Punktfunktion) als Matrix."""
    e, f = func(0.0, 0.0)
    ax, ay = func(1.0, 0.0)
    cx, cy = func(0.0, 1.0)
    return (ax - e, ay - f, cx - e, cy - f, e, f)


def paste(document: EditorDocument, history: History, page: int, clip: Clip, at: tuple[float, float] | None = None, *, nudge: int = 0) -> Rect:
    """Objekte der Zwischenablage auf ``page`` einfügen – an der Anzeige-Stelle ``at`` (obere linke Ecke) bzw.
    an derselben Stelle wie im Original, ``nudge``-mal versetzt (wiederholtes Einfügen legt die Kopien
    nicht deckungsgleich übereinander). Liefert den Bereich in der Anzeige."""
    document.ensure_editable()
    if not clip.data and not clip.items:
        raise UnsupportedEdit("Die Zwischenablage enthält nichts zum Einfügen.")
    source = PageGeometry(clip.crop, clip.rotation)
    target = document.geometry(page)
    box = clip.view_bounds()
    if at is not None:
        du, dv = at[0] - box[0], at[1] - box[1]
    else:
        du = dv = NUDGE * max(0, int(nudge))
    # Im sichtbaren Bereich der Zielseite halten
    du = max(-box[0], min(du, target.width - box[2])) if box[2] - box[0] <= target.width else -box[0]
    dv = max(-box[1], min(dv, target.height - box[3])) if box[3] - box[1] <= target.height else -box[1]

    def place(x: float, y: float) -> tuple[float, float]:
        u, v = source.to_view(x, y)
        return target.to_page(u + du, v + dv)

    matrix = affine(place)
    placed = (box[0] + du, box[1] + dv, box[2] + du, box[3] + dv)
    area = target.rect_to_page(placed)
    before, before_text = objects._snapshot(document, page)  # noqa: SLF001
    try:
        with commands.record(document, history, "Einfügen", pages=(page,)) as rec:
            obj = rec.page(page)
            if clip.data:
                pdf = pikepdf.open(io.BytesIO(clip.data))
                document.adopt(pdf)  # Stream-Daten werden erst beim Speichern gelesen
                source_page = pdf.pages[0].obj
                renamed = _take_resources(document.pdf, obj, source_page)
                instructions = [_rename(ins, renamed) for ins in pikepdf.parse_content_stream(source_page)]
                append_content(document.pdf, obj, " ".join(f"{value:.6f}" for value in matrix).encode("latin-1") + b" cm\n" + pikepdf.unparse_content_stream(instructions))
            for item in clip.items:
                _set_text(document, page, {**item, "angle": (item["angle"] + target.rotation - clip.rotation) % 360}, place(*item["origin"]))
            rec.info["mode"] = objects.NATIVE if not clip.items else objects.RECONSTRUCTED
            _verify_paste(document, page, before, area, clip.text)
            rec.fresh = True
    except objects._NotNative as reason:  # noqa: SLF001
        raise UnsupportedEdit("Das lässt sich hier nicht sicher einfügen. " + str(reason)) from reason
    return placed


def _take_resources(pdf: pikepdf.Pdf, page: pikepdf.Object, source_page: pikepdf.Object) -> dict[tuple[str, str], str]:
    """Ressourcen der Zwischenablage-Seite in die Zielseite übernehmen – unter eigenen, freien Namen."""
    resources = source_page.get("/Resources")
    renamed: dict[tuple[str, str], str] = {}
    if not isinstance(resources, Dictionary):
        return renamed
    categories = [str(category) for category in resources.keys() if isinstance(resources[category], Dictionary)]
    own = commands.own_resources(page, pdf, *categories)
    for category in categories:
        target = own[category]
        for name, value in resources[category].items():
            number = 1
            while f"/{PASTE_PREFIX}{number}" in target:
                number += 1
            fresh = f"/{PASTE_PREFIX}{number}"
            target[fresh] = pdf.copy_foreign(value)
            renamed[(category, str(name))] = fresh
    return renamed


def _rename(ins, renamed: dict[tuple[str, str], str]):
    if isinstance(ins, pikepdf.ContentStreamInlineImage):
        return ins
    op = str(ins.operator)
    operands = list(ins.operands)
    category = RESOURCE_OPERATORS.get(op)
    if category and operands and isinstance(operands[0], Name) and (category, str(operands[0])) in renamed:
        operands[0] = Name(renamed[(category, str(operands[0]))])
    elif op in ("cs", "CS") and operands and isinstance(operands[0], Name) and ("/ColorSpace", str(operands[0])) in renamed:
        operands[0] = Name(renamed[("/ColorSpace", str(operands[0]))])
    elif op in ("scn", "SCN") and operands and isinstance(operands[-1], Name) and ("/Pattern", str(operands[-1])) in renamed:
        operands[-1] = Name(renamed[("/Pattern", str(operands[-1]))])
    else:
        return ins
    return pikepdf.ContentStreamInstruction(operands, ins.operator)


def _verify_paste(document: EditorDocument, page: int, before, area: Rect, text: str) -> None:
    from PIL import ImageChops, ImageDraw

    from . import render, textlayer

    document.touch()
    after = render.render_page(document, page, before.width)
    a = render.to_pil(before).convert("L")
    b = render.to_pil(after).convert("L")
    diff = ImageChops.difference(a, b).point(lambda value: 255 if value > textedit.DIFF_THRESHOLD else 0)
    geo = document.geometry(page)
    scale = a.width / geo.width
    u0, v0, u1, v1 = geo.rect_to_view(inflate(area, 3.0))
    ImageDraw.Draw(diff).rectangle([int(u0 * scale) - 2, int(v0 * scale) - 2, int(u1 * scale) + 2, int(v1 * scale) + 2], fill=0)
    if diff.getbbox() is not None:
        raise objects._NotNative("Das Einfügen hätte die Seite außerhalb des eingefügten Bereichs verändert")  # noqa: SLF001
    for line in [line for line in text.split("\n") if line.strip()][:20]:
        if textedit._squash(line) not in textedit._squash(textlayer.text(document, page)):  # noqa: SLF001
            raise objects._NotNative("Der eingefügte Text ist im PDF nicht lesbar")  # noqa: SLF001


def normalize_rect(rect) -> Rect:
    return normalize(tuple(float(v) for v in rect))
