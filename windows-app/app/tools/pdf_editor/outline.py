"""Gliederung (Lesezeichen) eines PDFs lesen – zur Navigation – und bearbeiten: hinzufügen,
umbenennen, löschen, verschieben, Ziel ändern. Unveränderte Lesezeichen bleiben beim Speichern, wie
sie sind."""

from __future__ import annotations

from dataclasses import dataclass

from pikepdf import Array, Dictionary, Name, String

from pdfium_lock import PDFIUM_LOCK

from .commands import History, record
from .document import EditorDocument
from .errors import EditorError

MAX_ITEMS = 5000
MAX_DEPTH = 16


@dataclass(frozen=True)
class OutlineEntry:
    level: int  # 0 = oberste Ebene
    title: str
    page: int  # Seitenindex oder -1 (Ziel außerhalb des Dokuments / andere Aktion)
    children: int  # Anzahl direkter und offener Unterpunkte (PDF /Count, ohne Vorzeichen)
    open: bool


def read_outline(document: EditorDocument) -> list[OutlineEntry]:
    entries: list[OutlineEntry] = []
    with PDFIUM_LOCK:
        view = document.view()
        try:
            for bookmark in view.get_toc(max_depth=MAX_DEPTH):
                if len(entries) >= MAX_ITEMS:
                    break
                title = (bookmark.get_title() or "").replace("\r", " ").replace("\n", " ").strip() or "(ohne Titel)"
                count = bookmark.get_count()
                entries.append(OutlineEntry(bookmark.level, title, _target(view, bookmark), abs(count), count >= 0))
        except Exception:  # noqa: BLE001 - eine beschädigte Gliederung verhindert nie das Lesen
            return entries
    return entries


def _target(view, bookmark) -> int:
    import pypdfium2.raw as r

    dest = bookmark.get_dest()
    index = dest.get_index() if dest is not None else None
    if index is None:
        action = r.FPDFBookmark_GetAction(bookmark.raw)
        if action and r.FPDFAction_GetType(action) == r.PDFACTION_GOTO:
            raw_dest = r.FPDFAction_GetDest(view.raw, action)
            if raw_dest:
                index = r.FPDFDest_GetDestPageIndex(view.raw, raw_dest)
    return index if index is not None and 0 <= index < len(view) else -1


# --- Bearbeiten ---------------------------------------------------------------------------------------------------
# Jede Änderung schreibt einen **neuen** Lesezeichenbaum (neue Dictionaries; Ziele und Aktionen werden
# als Verweise übernommen) und setzt ``/Outlines`` darauf – der bisherige Baum bleibt unverändert und
# dient Rückgängig. Adressiert wird mit der Nummer in der angezeigten Liste (Vorordnung: Eintrag, dann
# seine Unterpunkte – dieselbe Reihenfolge, in der PDFium die Gliederung liefert).

KEEP_KEYS = ("/Dest", "/A", "/C", "/F", "/SE")


@dataclass
class Node:
    title: str
    keys: dict  # Ziel bzw. Aktion, Farbe, Stil – unverändert übernommen
    open: bool
    children: list


def read_tree(document: EditorDocument) -> list[Node]:
    root = document.pdf.Root.get("/Outlines")
    if not isinstance(root, Dictionary):
        return []
    seen: set = set()
    count = [0]

    def level(first, depth: int) -> list[Node]:
        nodes: list[Node] = []
        item = first
        while isinstance(item, Dictionary) and count[0] < MAX_ITEMS:
            key = item.objgen if item.is_indirect else id(item)
            if key in seen:
                break
            seen.add(key)
            count[0] += 1
            try:
                title = str(item.get("/Title", "")).replace("\r", " ").replace("\n", " ").strip()
            except (TypeError, ValueError):
                title = ""
            children = level(item.get("/First"), depth + 1) if depth < MAX_DEPTH else []
            raw_count = item.get("/Count")
            nodes.append(Node(title or "(ohne Titel)", {k: item[k] for k in KEEP_KEYS if k in item}, raw_count is None or int(raw_count) >= 0, children))
            item = item.get("/Next")
        return nodes

    return level(root.get("/First"), 0)


def _flat(nodes: list[Node]) -> list[tuple[list[Node], int]]:
    """(Geschwisterliste, Position) je Eintrag in Vorordnung."""
    out: list[tuple[list[Node], int]] = []

    def walk(siblings: list[Node]) -> None:
        for position, node in enumerate(siblings):
            out.append((siblings, position))
            walk(node.children)

    walk(nodes)
    return out


def _parent_of(nodes: list[Node], siblings: list[Node]) -> tuple[list[Node], int] | None:
    for holder, position in _flat(nodes):
        if holder[position].children is siblings:
            return holder, position
    return None


def _dest(document: EditorDocument, page: int) -> Array:
    if not 0 <= page < document.page_count:
        raise EditorError("Diese Seite gibt es nicht.")
    geo = document.geometry(page)
    left, top = geo.to_page(0.0, 0.0)
    return Array([document.pdf.pages[page].obj, Name.XYZ, round(left, 2), round(top, 2), None])


def _write(document: EditorDocument, rec, nodes: list[Node]) -> None:
    pdf = document.pdf
    rec.root(("/Outlines",))
    if not nodes:
        if "/Outlines" in pdf.Root:
            del pdf.Root["/Outlines"]
        return
    root = pdf.make_indirect(Dictionary(Type=Name.Outlines))

    def build(level: list[Node], parent) -> tuple[list, int]:
        items = []
        visible = 0
        for node in level:
            item = pdf.make_indirect(Dictionary(Title=String(node.title), Parent=parent))
            for key, value in node.keys.items():
                item[key] = value
            items.append(item)
        for index, (item, node) in enumerate(zip(items, level)):
            if index > 0:
                item.Prev = items[index - 1]
            if index < len(items) - 1:
                item.Next = items[index + 1]
            kids, kid_visible = build(node.children, item)
            if kids:
                item.First, item.Last = kids[0], kids[-1]
                item.Count = kid_visible if node.open else -kid_visible
            visible += 1 + (kid_visible if (kids and node.open) else 0)
        return items, visible

    items, visible = build(nodes, root)
    root.First, root.Last, root.Count = items[0], items[-1], visible
    pdf.Root.Outlines = root


def _edit(document: EditorDocument, history: History, title: str, change) -> int:
    document.ensure_editable()
    nodes = read_tree(document)
    with record(document, history, title) as rec:
        result = change(nodes)
        _write(document, rec, nodes)
    return result


def _locate(nodes: list[Node], index: int) -> tuple[list[Node], int]:
    flat = _flat(nodes)
    if not 0 <= index < len(flat):
        raise EditorError("Das Lesezeichen ist nicht mehr vorhanden.")
    return flat[index]


def add_bookmark(document: EditorDocument, history: History, title: str, page: int, *, after: int | None = None, child: bool = False) -> int:
    """Neues Lesezeichen auf ``page`` – hinter ``after`` (gleiche Ebene) bzw. als letzter Unterpunkt
    (``child``); ohne ``after`` am Ende. Liefert seine Nummer in der Liste."""
    title = title.strip() or f"Seite {page + 1}"
    node = Node(title, {"/Dest": _dest(document, page)}, True, [])

    def change(nodes: list[Node]) -> int:
        if after is None:
            nodes.append(node)
        else:
            siblings, position = _locate(nodes, after)
            if child:
                siblings[position].children.append(node)
                siblings[position].open = True
            else:
                siblings.insert(position + 1, node)
        return next(i for i, (holder, pos) in enumerate(_flat(nodes)) if holder[pos] is node)

    return _edit(document, history, "Lesezeichen hinzufügen", change)


def rename_bookmark(document: EditorDocument, history: History, index: int, title: str) -> None:
    title = title.strip()
    if not title:
        raise EditorError("Ein Lesezeichen braucht einen Namen.")

    def change(nodes: list[Node]) -> int:
        siblings, position = _locate(nodes, index)
        siblings[position].title = title
        return index

    _edit(document, history, "Lesezeichen umbenennen", change)


def delete_bookmark(document: EditorDocument, history: History, index: int) -> None:
    def change(nodes: list[Node]) -> int:
        siblings, position = _locate(nodes, index)
        del siblings[position]
        return index

    _edit(document, history, "Lesezeichen löschen", change)


def set_bookmark_page(document: EditorDocument, history: History, index: int, page: int) -> None:
    def change(nodes: list[Node]) -> int:
        siblings, position = _locate(nodes, index)
        keys = {k: v for k, v in siblings[position].keys.items() if k not in ("/Dest", "/A")}
        keys["/Dest"] = _dest(document, page)
        siblings[position].keys = keys
        return index

    _edit(document, history, "Lesezeichen-Ziel ändern", change)


def move_bookmark(document: EditorDocument, history: History, index: int, direction: str) -> int:
    """``up``/``down`` (unter Geschwistern), ``in`` (Unterpunkt des vorigen), ``out`` (eine Ebene
    höher, direkt hinter den bisherigen Oberpunkt). Liefert die neue Nummer."""

    def change(nodes: list[Node]) -> int:
        siblings, position = _locate(nodes, index)
        node = siblings[position]
        if direction == "up" and position > 0:
            siblings[position - 1], siblings[position] = siblings[position], siblings[position - 1]
        elif direction == "down" and position < len(siblings) - 1:
            siblings[position + 1], siblings[position] = siblings[position], siblings[position + 1]
        elif direction == "in" and position > 0:
            del siblings[position]
            siblings[position - 1].children.append(node)
            siblings[position - 1].open = True
        elif direction == "out":
            parent = _parent_of(nodes, siblings)
            if parent is None:
                return index
            holder, parent_position = parent
            del siblings[position]
            holder.insert(parent_position + 1, node)
        else:
            return index
        return next(i for i, (holder, pos) in enumerate(_flat(nodes)) if holder[pos] is node)

    return _edit(document, history, "Lesezeichen verschieben", change)
