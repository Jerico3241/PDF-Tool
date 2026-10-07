"""Dokument bereinigen: versteckte und mitreisende Daten vor dem Weitergeben entfernen.

Was entfernt werden kann (je ein Schalter):

* **Metadaten** – Dokumentinformationen (Titel, Autor, Programm, Datum …) und XMP-Metadaten, auch
  die einzelner Seiten.
* **JavaScript und automatische Aktionen** – Skripte des Dokuments, Aktionen beim Öffnen und bei
  Ereignissen (``/AA``), Skript-, Start-, Sende- und Importaktionen von Links, Lesezeichen und
  Formularfeldern. PDF Tool führt JavaScript ohnehin nie aus; bereinigt bleibt es auch in anderen
  Programmen wirkungslos.
* **Anhänge** – eingebettete Dateien und Dateianhang-Kommentare.
* **Kommentare** – alle Anmerkungen außer Links und Formularfeldern (samt ihrer Notizfenster).
* **Versteckte Daten** – Miniaturbilder, private Daten von Programmen (``/PieceInfo``),
  Web-Capture-Daten und alternative Darstellungen.

Gezählt und gemeldet wird nur, *was* entfernt wurde – nie Inhalte. Alles in einem Schritt für
Rückgängig; vorhandene Objekte werden nicht in place verändert, ohne ihre Einträge vorher zu merken.
"""

from __future__ import annotations

from dataclasses import dataclass, fields

import pikepdf
from pikepdf import Array, Dictionary, Name

from .commands import History, record
from .document import EditorDocument

UNSAFE_ACTIONS = ("/JavaScript", "/Launch", "/SubmitForm", "/ImportData", "/Rendition", "/RichMediaExecute")
HIDDEN_ROOT = ("/PieceInfo", "/SpiderInfo")
HIDDEN_PAGE = ("/Thumb", "/PieceInfo")
MAX_FIELDS = 20_000
MAX_OUTLINE = 20_000


@dataclass(frozen=True)
class CleanOptions:
    metadata: bool = True
    javascript: bool = True
    attachments: bool = True
    comments: bool = False
    hidden: bool = True


@dataclass
class Findings:
    """Anzahl je Art – vor dem Bereinigen (was es gibt) bzw. danach (was entfernt wurde)."""

    metadata: int = 0
    javascript: int = 0
    attachments: int = 0
    comments: int = 0
    hidden: int = 0

    @property
    def total(self) -> int:
        return sum(getattr(self, item.name) for item in fields(self))

    def as_dict(self) -> dict:
        return {item.name: getattr(self, item.name) for item in fields(self)}


def inspect(document: EditorDocument) -> Findings:
    """Was ließe sich entfernen? (nur zählen, nichts ändern)"""
    return _walk(document, CleanOptions(True, True, True, True, True), None)


def clean(document: EditorDocument, history: History, options: CleanOptions) -> Findings:
    """Gewählte Daten entfernen – ein Schritt für Rückgängig. Liefert, was entfernt wurde."""
    document.ensure_editable()
    found = inspect(document)
    wanted = Findings(**{name: (count if getattr(options, name) else 0) for name, count in found.as_dict().items()})
    if not wanted.total:
        return Findings()
    with record(document, history, "Dokument bereinigen", pages=tuple(range(document.page_count))) as rec:
        removed = _walk(document, options, rec)
    return removed


# --- Durchgang (zählen bzw. entfernen) -----------------------------------------------------------------------------
def _walk(document: EditorDocument, options: CleanOptions, rec) -> Findings:
    pdf = document.pdf
    root = pdf.Root
    result = Findings()
    change = rec is not None

    # Dokumentebene ------------------------------------------------------------------------------------------
    if change:
        rec.object(pdf.trailer, ("/Info",))
        rec.root(("/Metadata", "/Names", "/OpenAction", "/AA", "/AF", *HIDDEN_ROOT))
    if options.metadata:
        info = pdf.trailer.get("/Info")
        if isinstance(info, Dictionary) and len(info.keys()):
            result.metadata += len(info.keys())
            if change:
                pdf.trailer.Info = pdf.make_indirect(Dictionary())
        if "/Metadata" in root:
            result.metadata += 1
            if change:
                del root["/Metadata"]
    names = root.get("/Names")
    drop_names = []
    if isinstance(names, Dictionary):
        if options.javascript and "/JavaScript" in names:
            result.javascript += max(1, _name_tree_size(names.get("/JavaScript")))
            drop_names.append("/JavaScript")
        if options.attachments and "/EmbeddedFiles" in names:
            result.attachments += _name_tree_size(names.get("/EmbeddedFiles"))
            drop_names.append("/EmbeddedFiles")
        if options.hidden and "/AlternatePresentations" in names:
            result.hidden += 1
            drop_names.append("/AlternatePresentations")
        if change and drop_names:
            fresh = Dictionary({key: value for key, value in names.items() if key not in drop_names})
            if len(fresh.keys()):
                root.Names = pdf.make_indirect(fresh)
            else:
                del root["/Names"]
    if options.javascript:
        action = root.get("/OpenAction")
        if isinstance(action, Dictionary) and _unsafe(action):
            result.javascript += 1
            if change:
                del root["/OpenAction"]
        if "/AA" in root:
            result.javascript += 1
            if change:
                del root["/AA"]
    if options.attachments and change and isinstance(root.get("/AF"), Array):
        del root["/AF"]  # Verweise auf die eingebetteten Dateien (schon gezählt)
    if options.hidden:
        for key in HIDDEN_ROOT:
            if key in root:
                result.hidden += 1
                if change:
                    del root[key]

    # Seiten und ihre Anmerkungen -----------------------------------------------------------------------------
    for index, page in enumerate(pdf.pages):
        obj = page.obj
        if change:
            rec.page(index)
            rec.object(obj, ("/AA", "/Metadata", "/AF", *HIDDEN_PAGE))
        if options.javascript and "/AA" in obj:
            result.javascript += 1
            if change:
                del obj["/AA"]
        if options.metadata and "/Metadata" in obj:
            result.metadata += 1
            if change:
                del obj["/Metadata"]
        if options.attachments and change and isinstance(obj.get("/AF"), Array):
            del obj["/AF"]
        if options.hidden:
            for key in HIDDEN_PAGE:
                if key in obj:
                    result.hidden += 1
                    if change:
                        del obj[key]
        annots = obj.get("/Annots")
        if not isinstance(annots, Array):
            continue
        kept: list = []
        dropped: set = set()
        for annot in annots:
            if not isinstance(annot, Dictionary):
                kept.append(annot)
                continue
            subtype = annot.get("/Subtype")
            if subtype == Name.FileAttachment and options.attachments:
                result.attachments += 1
                dropped.add(_ident(annot))
                continue
            if options.comments and subtype not in (Name.Link, Name.Widget, Name.Popup, Name.FileAttachment):
                result.comments += 1
                dropped.add(_ident(annot))
                continue
            if options.javascript:
                result.javascript += _strip_actions(annot, rec)
            kept.append(annot)
        if dropped:
            # Notizfenster entfernter Kommentare gehen mit
            final = [annot for annot in kept if not (isinstance(annot, Dictionary) and annot.get("/Subtype") == Name.Popup and _ident(annot.get("/Parent")) in dropped)]
            if options.comments:
                final = [annot for annot in final if not (isinstance(annot, Dictionary) and annot.get("/Subtype") == Name.Popup)]
            if change:
                if final:
                    obj.Annots = Array(final)
                else:
                    del obj["/Annots"]

    # Formularfelder und Lesezeichen --------------------------------------------------------------------------
    if options.javascript:
        form = root.get("/AcroForm")
        if isinstance(form, Dictionary):
            for field in _fields(form.get("/Fields")):
                result.javascript += _strip_actions(field, rec)
        for item in _outline_items(root.get("/Outlines")):
            result.javascript += _strip_actions(item, rec, keys=("/A",))
    return result


def _strip_actions(obj: Dictionary, rec, keys=("/AA", "/A")) -> int:
    """Automatische Aktionen und unsichere Aktionen eines Objekts entfernen (bzw. zählen)."""
    count = 0
    remove = []
    if "/AA" in keys and "/AA" in obj:
        remove.append("/AA")
    action = obj.get("/A")
    if "/A" in keys and isinstance(action, Dictionary) and _unsafe(action):
        remove.append("/A")
    if remove:
        count = len(remove)
        if rec is not None:
            rec.object(obj, ("/AA", "/A"))
            for key in remove:
                del obj[key]
    return count


def _unsafe(action: Dictionary, depth: int = 0) -> bool:
    """Skript-, Start-, Sende- oder Importaktion – auch in einer Kette (``/Next``)."""
    if depth > 16:
        return True
    if str(action.get("/S", "")) in UNSAFE_ACTIONS:
        return True
    following = action.get("/Next")
    if isinstance(following, Dictionary):
        return _unsafe(following, depth + 1)
    if isinstance(following, Array):
        return any(isinstance(item, Dictionary) and _unsafe(item, depth + 1) for item in following)
    return False


def _ident(obj) -> tuple[int, int] | int:
    try:
        return obj.objgen if obj.is_indirect else id(obj)
    except AttributeError:
        return id(obj)


def _name_tree_size(node, depth: int = 0) -> int:
    if not isinstance(node, Dictionary) or depth > 32:
        return 0
    total = len(node.get("/Names", [])) // 2 if isinstance(node.get("/Names"), Array) else 0
    kids = node.get("/Kids")
    if isinstance(kids, Array):
        total += sum(_name_tree_size(kid, depth + 1) for kid in kids)
    return total


def _fields(items, depth: int = 0):
    if not isinstance(items, Array) or depth > 32:
        return
    seen = 0
    for item in items:
        if not isinstance(item, Dictionary):
            continue
        seen += 1
        if seen > MAX_FIELDS:
            return
        yield item
        yield from _fields(item.get("/Kids"), depth + 1)


def _outline_items(outlines):
    if not isinstance(outlines, Dictionary):
        return
    stack, seen = [outlines.get("/First")], set()
    while stack and len(seen) < MAX_OUTLINE:
        item = stack.pop()
        while isinstance(item, Dictionary) and len(seen) < MAX_OUTLINE:
            key = _ident(item)
            if key in seen:
                break
            seen.add(key)
            yield item
            stack.append(item.get("/First"))
            item = item.get("/Next")


__all__ = ["CleanOptions", "Findings", "clean", "inspect", "pikepdf"]
