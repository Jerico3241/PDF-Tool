"""Links: auflisten (zum Anklicken in der Ansicht), setzen, ändern und löschen.

Ein Link ist eine Anmerkung ``/Link`` mit einem Bereich und einem Ziel: eine Seite dieses Dokuments
(``/Dest`` bzw. ``/A /GoTo``, auch benannte Ziele) oder eine Webadresse (``/A /URI``). Andere
Aktionen (Skripte, Programme starten, andere Dateien öffnen) führt PDF Tool nie aus – solche Links
erscheinen ohne Ziel.

Neue Links sind unsichtbar umrandet (``/Border [0 0 0]``) und tragen ``/NM`` mit »pdftool-link-…«.
Erlaubte Webadressen: ``http``, ``https`` und ``mailto``.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass

import pikepdf
from pikepdf import Array, Dictionary, Name, String

from .commands import History, record
from .document import EditorDocument
from .errors import EditorError
from .geometry import Rect, normalize

URI_SCHEMES = ("http://", "https://", "mailto:")
MAX_URI = 2000
NAME_PREFIX = "pdftool-link-"


@dataclass(frozen=True)
class LinkInfo:
    key: str  # Seite-Objektnummer (bzw. Position) – stabil bis zur nächsten Änderung der Seite
    page: int
    rect: Rect  # Seitenkoordinaten
    target_page: int  # -1 ohne Seitenziel
    uri: str  # "" ohne Webadresse
    ours: bool


def list_links(document: EditorDocument, page: int) -> list[LinkInfo]:
    pdf = document.pdf
    if not 0 <= page < document.page_count:
        return []
    pages = {p.obj.objgen: i for i, p in enumerate(pdf.pages)}
    annots = pdf.pages[page].obj.get("/Annots")
    result = []
    if not isinstance(annots, Array):
        return result
    for position, annot in enumerate(annots):
        if not isinstance(annot, Dictionary) or annot.get("/Subtype") != Name.Link:
            continue
        try:
            rect = normalize(tuple(float(v) for v in annot.Rect))
        except (AttributeError, TypeError, ValueError):
            continue
        target, uri = _target(pdf, annot, pages)
        name = str(annot.get("/NM", ""))
        result.append(LinkInfo(_key(annot, page, position), page, rect, target, uri, name.startswith(NAME_PREFIX)))
    return result


def check_uri(uri: str) -> str:
    """Webadresse prüfen und bereinigen – wirft ``EditorError`` mit verständlichem Grund."""
    value = uri.strip()
    if value and not value.lower().startswith(URI_SCHEMES):
        scheme = re.match(r"^([A-Za-z][A-Za-z0-9+.-]*):(?!\d)", value)
        if scheme is not None:
            raise EditorError("Erlaubt sind Webadressen (https://…) und E-Mail-Adressen (mailto:…).")
        value = ("mailto:" if "@" in value and "/" not in value else "https://") + value
    if not value.lower().startswith(URI_SCHEMES):
        raise EditorError("Erlaubt sind Webadressen (https://…) und E-Mail-Adressen (mailto:…).")
    if len(value) > MAX_URI or any(ord(char) < 32 for char in value) or re.search(r"\s", value):
        raise EditorError("Diese Adresse lässt sich nicht verwenden.")
    return value


def add_link(document: EditorDocument, history: History, page: int, rect: Rect, *, target_page: int | None = None, uri: str | None = None) -> str:
    document.ensure_editable("annotate")
    rect = normalize(rect)
    if rect[2] - rect[0] < 2 or rect[3] - rect[1] < 2:
        raise EditorError("Der Bereich für den Link ist zu klein.")
    annot = Dictionary(Type=Name.Annot, Subtype=Name.Link, Rect=Array([round(v, 2) for v in rect]), Border=Array([0, 0, 0]), H=Name.I, NM=String(NAME_PREFIX + uuid.uuid4().hex[:12]))
    _set_target(document, annot, target_page, uri)
    pdf = document.pdf
    with record(document, history, "Link hinzufügen", pages=(page,)) as rec:
        obj = rec.page(page)
        indirect = pdf.make_indirect(annot)
        annot_list = obj.get("/Annots")
        obj.Annots = Array([*(list(annot_list) if isinstance(annot_list, Array) else []), indirect])
        position = len(obj.Annots) - 1
    return _key(indirect, page, position)


def update_link(document: EditorDocument, history: History, key: str, *, target_page: int | None = None, uri: str | None = None) -> None:
    document.ensure_editable("annotate")
    page, position, annot = _find(document, key)
    with record(document, history, "Link ändern", pages=(page,)) as rec:
        rec.object(annot, ("/Dest", "/A"))
        for name in ("/Dest", "/A"):
            if name in annot:
                del annot[name]
        _set_target(document, annot, target_page, uri)


def delete_link(document: EditorDocument, history: History, key: str) -> None:
    document.ensure_editable("annotate")
    page, position, _annot = _find(document, key)
    with record(document, history, "Link löschen", pages=(page,)) as rec:
        obj = rec.page(page)
        remaining = [item for index, item in enumerate(obj.Annots) if index != position]
        if remaining:
            obj.Annots = Array(remaining)
        else:
            del obj["/Annots"]


def link_at(document: EditorDocument, page: int, x: float, y: float) -> LinkInfo | None:
    """Oberster Link an einem Punkt (Seitenkoordinaten)."""
    for link in reversed(list_links(document, page)):
        if link.rect[0] <= x <= link.rect[2] and link.rect[1] <= y <= link.rect[3]:
            return link
    return None


# --- Hilfen ------------------------------------------------------------------------------------------------------
def _key(annot, page: int, position: int) -> str:
    if annot.is_indirect:
        return f"{page}-{annot.objgen[0]}-{annot.objgen[1]}"
    return f"{page}-p{position}"


def _find(document: EditorDocument, key: str) -> tuple[int, int, Dictionary]:
    try:
        page = int(key.split("-", 1)[0])
    except ValueError as exc:
        raise EditorError("Der Link ist nicht mehr vorhanden.") from exc
    if 0 <= page < document.page_count:
        annots = document.pdf.pages[page].obj.get("/Annots")
        if isinstance(annots, Array):
            for position, annot in enumerate(annots):
                if isinstance(annot, Dictionary) and annot.get("/Subtype") == Name.Link and _key(annot, page, position) == key:
                    return page, position, annot
    raise EditorError("Der Link ist nicht mehr vorhanden.")


def _set_target(document: EditorDocument, annot: Dictionary, target_page: int | None, uri: str | None) -> None:
    if uri:
        annot.A = Dictionary(S=Name.URI, URI=String(check_uri(uri)))
    elif target_page is not None:
        if not 0 <= target_page < document.page_count:
            raise EditorError("Diese Seite gibt es nicht.")
        geo = document.geometry(target_page)
        left, top = geo.to_page(0.0, 0.0)
        annot.Dest = Array([document.pdf.pages[target_page].obj, Name.XYZ, round(left, 2), round(top, 2), None])
    else:
        raise EditorError("Bitte eine Seite oder eine Webadresse angeben.")


def _target(pdf: pikepdf.Pdf, annot: Dictionary, pages: dict) -> tuple[int, str]:
    dest = annot.get("/Dest")
    action = annot.get("/A")
    if dest is None and isinstance(action, Dictionary):
        kind = action.get("/S")
        if kind == Name.URI:
            value = str(action.get("/URI", ""))
            return -1, value if value.lower().startswith(URI_SCHEMES) else ""
        if kind == Name.GoTo:
            dest = action.get("/D")
    return _page_of(pdf, dest, pages), ""


def _page_of(pdf: pikepdf.Pdf, dest, pages: dict, depth: int = 0) -> int:
    if dest is None or depth > 4:
        return -1
    if isinstance(dest, (pikepdf.String, Name)):
        return _page_of(pdf, _named(pdf, str(dest).lstrip("/") if isinstance(dest, Name) else str(dest)), pages, depth + 1)
    if isinstance(dest, Dictionary) and "/D" in dest:
        return _page_of(pdf, dest.D, pages, depth + 1)
    if isinstance(dest, Array) and len(dest):
        first = dest[0]
        if isinstance(first, Dictionary) and first.is_indirect:
            return pages.get(first.objgen, -1)
        try:
            number = int(first)  # Seitennummer (Ziele in andere Dateien u. ä.)
            return number if 0 <= number < len(pdf.pages) else -1
        except (TypeError, ValueError):
            return -1
    return -1


def _named(pdf: pikepdf.Pdf, name: str):
    root = pdf.Root
    dests = root.get("/Dests")
    if isinstance(dests, Dictionary) and "/" + name in dests:
        return dests["/" + name]
    names = root.get("/Names")
    tree = names.get("/Dests") if isinstance(names, Dictionary) else None
    return _lookup(tree, name, 0)


def _lookup(node, name: str, depth: int):
    if not isinstance(node, Dictionary) or depth > 32:
        return None
    entries = node.get("/Names")
    if isinstance(entries, Array):
        for index in range(0, len(entries) - 1, 2):
            if str(entries[index]) == name:
                return entries[index + 1]
    kids = node.get("/Kids")
    if isinstance(kids, Array):
        for kid in kids:
            found = _lookup(kid, name, depth + 1)
            if found is not None:
                return found
    return None
