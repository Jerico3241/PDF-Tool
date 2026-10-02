"""Ein geöffnetes Dokument im Arbeitsthread des Editors.

Alle Methoden laufen **nur** im Arbeitsthread (``engine.Engine``) – nie im GUI-Thread. Die
Oberfläche erhält Ergebnisse als einfache Werte (Listen, Wörterbücher, ``QImage``). Koordinaten
für die Oberfläche sind **Anzeige-Punkte** der Seite (Ursprung oben links, Drehung der Seite
berücksichtigt); umgerechnet wird hier mit der Seitengeometrie.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from tools.pdf_editor import annotations, commands, export, forms, images, metadata, outline, pages, recovery, render, save, textedit, textlayer
from tools.pdf_editor.document import EditorDocument
from tools.pdf_editor.errors import EditorError
from tools.pdf_editor.geometry import normalize

from .engine import raster_to_qimage

THUMB_WIDTH = 120


@dataclass
class PageText:
    """Zeichen einer Seite für Auswahl und Treffer (Anzeige-Punkte) – ohne Inhalte zu protokollieren."""

    revision: int
    boxes: list[tuple[float, float, float, float]]  # je Zeichen (u0, v0, u1, v1)
    spaces: list[bool]  # Leerzeichen/Zeilenwechsel (für Wortgrenzen)


class Session:
    def __init__(self, ident: str, document: EditorDocument) -> None:
        self.ident = ident
        self.document = document
        self.history = commands.History()
        self.recovery: recovery.RecoverySession | None = None
        self.recovered_from: recovery.SessionInfo | None = None
        self._texts: dict[int, PageText] = {}
        self._blocks: dict[int, tuple[int, list]] = {}
        self.closed = False

    # Öffnen, Zustand --------------------------------------------------------------------------------------
    @classmethod
    def open(cls, ident: str, path: str, password: str | None = None) -> "Session":
        return cls(ident, EditorDocument.open(path, password=password))

    @classmethod
    def from_recovery(cls, ident: str, info: recovery.SessionInfo, password: str | None = None) -> "Session":
        data = recovery.read_session(info)
        original = Path(info.original) if info.original else None
        document = EditorDocument.from_bytes(data, name=info.name, path=original, password=password, stamp=None)
        session = cls(ident, document)
        document.revision = 1  # wiederhergestellt = ungespeichert
        session.recovered_from = info
        return session

    def state(self) -> dict:
        doc = self.document
        report = doc.report
        sizes = []
        for index in range(doc.page_count):
            geo = doc.geometry(index)
            sizes.append([round(geo.width, 3), round(geo.height, 3)])
        return {
            "name": doc.name,
            "path": str(doc.path or ""),
            "pages": doc.page_count,
            "sizes": sizes,
            "revision": doc.revision,
            "dirty": doc.dirty,
            "undo": self.history.undo_title,
            "redo": self.history.redo_title,
            "readOnly": doc.read_only_reason,
            "encrypted": doc.encrypted,
            "signed": report.signed,
            "repaired": report.repaired,
            "javascript": report.javascript,
            "xfa": report.xfa,
            "permissions": {"edit": doc.permissions.edit, "annotate": doc.permissions.annotate, "fill": doc.permissions.fill_forms, "assemble": doc.permissions.assemble, "print": doc.permissions.print, "copy": doc.permissions.copy},
        }

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        if self.recovery is not None:
            self.recovery.discard()
            self.recovery = None
        self.document.close()

    # Darstellung --------------------------------------------------------------------------------------
    def render(self, page: int, width: int, kind: str = "page", region: tuple = ()):
        """Seitenbild in ``width`` Pixel Breite; ``kind == "region"``: nur der Ausschnitt ``region``
        (Anzeige-Punkte × 10) im Maßstab dieser Seitenbreite."""
        if not 0 <= page < self.document.page_count:
            return None
        if kind == "region" and len(region) == 4:
            geo = self.document.geometry(page)
            scale = width / max(1.0, geo.width)
            raster = render.render_region(self.document, page, tuple(value / 10 for value in region), scale)
        else:
            raster = render.render_page(self.document, page, width)
        return raster_to_qimage(raster)

    # Text, Auswahl, Suche ---------------------------------------------------------------------------------
    def page_text(self, page: int) -> PageText:
        cached = self._texts.get(page)
        if cached is not None and cached.revision == self.document.revision:
            return cached
        from pdfium_lock import PDFIUM_LOCK

        geo = self.document.geometry(page)
        boxes, spaces = [], []
        with PDFIUM_LOCK:
            textpage = self.document.textpage(page)
            total = textpage.count_chars()
            for i in range(total):
                left, bottom, right, top = textpage.get_charbox(i, loose=True)
                u0, v0, u1, v1 = geo.rect_to_view(normalize((left, bottom, right, top)))
                boxes.append((round(u0, 2), round(v0, 2), round(u1, 2), round(v1, 2)))
                char = textpage.get_text_range(i, 1)
                spaces.append(not char.strip())
        table = PageText(self.document.revision, boxes, spaces)
        self._texts[page] = table
        if len(self._texts) > 64:
            self._texts.pop(next(iter(self._texts)))
        return table

    def text(self, page: int, start: int, count: int) -> str:
        return textlayer.text(self.document, page, start, count)

    def selection_rects(self, page: int, start: int, count: int) -> list[list[float]]:
        geo = self.document.geometry(page)
        return [list(geo.rect_to_view(rect)) for rect in textlayer.rects(self.document, page, start, count)]

    def search_page(self, page: int, query: str, match_case: bool, whole_word: bool) -> list[list[list[float]]]:
        """Treffer einer Seite: je Treffer seine Rechtecke (Anzeige-Punkte)."""
        geo = self.document.geometry(page)
        return [[list(geo.rect_to_view(rect)) for rect in hit.rects] for hit in textlayer.search(self.document, page, query, match_case=match_case, whole_word=whole_word)]

    def outline(self) -> list[dict]:
        return [{"level": entry.level, "title": entry.title, "page": entry.page, "children": entry.children, "open": entry.open} for entry in outline.read_outline(self.document)]

    # Text bearbeiten ---------------------------------------------------------------------------------------
    def blocks(self, page: int) -> list[dict]:
        cached = self._blocks.get(page)
        if cached is None or cached[0] != self.document.revision:
            cached = (self.document.revision, textedit.analyze(self.document, page))
            self._blocks[page] = cached
            if len(self._blocks) > 16:
                self._blocks.pop(next(iter(self._blocks)))
        geo = self.document.geometry(page)
        result = []
        for block in cached[1]:
            info = block.describe()
            info["view"] = list(geo.rect_to_view(block.bounds))
            info["color"] = "#%02X%02X%02X" % tuple(block.color)
            info.pop("bounds", None)
            result.append(info)
        return result

    def _block(self, page: int, block_id: str):
        self.blocks(page)
        return textedit.find_block(self._blocks[page][1], block_id)

    def edit_block(self, page: int, block_id: str, text: str, overflow: str, style: dict | None) -> dict:
        block = self._block(page, block_id)
        outcome = textedit.edit_block(self.document, self.history, block, text, style=_text_style(style), overflow=overflow)
        return {"mode": outcome.mode, "label": outcome.label, "notes": list(outcome.notes), "font": outcome.font}

    def add_text(self, page: int, u: float, v: float, text: str, style: dict | None, width: float | None) -> dict:
        x, y = self.document.geometry(page).to_page(u, v)
        outcome = textedit.add_text(self.document, self.history, page, x, y, text, style=_text_style(style), width=width)
        return {"mode": outcome.mode, "label": "Text hinzugefügt", "notes": list(outcome.notes), "font": outcome.font}

    # Bilder ---------------------------------------------------------------------------------------------------
    def images(self, page: int) -> list[dict]:
        geo = self.document.geometry(page)
        return [{"index": item.index, "view": list(geo.rect_to_view(item.bounds)), "pixels": list(item.pixels), "kind": item.kind, "ours": item.ours, "editable": item.editable, "reason": item.reason} for item in images.list_images(self.document, page)]

    def move_image(self, page: int, index: int, du: float, dv: float) -> None:
        geo = self.document.geometry(page)
        x0, y0 = geo.to_page(0, 0)
        x1, y1 = geo.to_page(du, dv)
        images.move_by(self.document, self.history, page, index, x1 - x0, y1 - y0)

    def fit_image(self, page: int, index: int, view_rect) -> None:
        images.fit(self.document, self.history, page, index, self.document.geometry(page).rect_to_page(normalize(tuple(view_rect))))

    def rotate_image(self, page: int, index: int, clockwise: bool) -> None:
        images.rotate_by(self.document, self.history, page, index, -90 if clockwise else 90)

    def delete_image(self, page: int, index: int) -> None:
        images.delete(self.document, self.history, page, index)

    def replace_image(self, page: int, index: int, path: str) -> None:
        images.replace(self.document, self.history, page, index, path)

    def insert_image(self, page: int, path: str, view_rect) -> int:
        return images.insert(self.document, self.history, page, path, tuple(view_rect))

    def arrange_image(self, page: int, index: int, front: bool) -> None:
        images.arrange(self.document, self.history, page, index, front)

    # Anmerkungen -------------------------------------------------------------------------------------------
    def annotations(self, page: int | None = None) -> list[dict]:
        result = []
        for info in annotations.list_annotations(self.document, page):
            geo = self.document.geometry(info.page)
            color = "#%02X%02X%02X" % info.color if info.color else ""
            result.append({"key": info.key, "page": info.page, "label": info.label, "subtype": info.subtype, "view": list(geo.rect_to_view(info.rect)), "contents": info.contents, "author": info.author, "modified": info.modified, "color": color, "ours": info.ours})
        return result

    def markup(self, page: int, kind: str, view_rects: list, color: str, contents: str) -> str:
        geo = self.document.geometry(page)
        rects = [geo.rect_to_page(normalize(tuple(rect))) for rect in view_rects]
        return annotations.add_markup(self.document, self.history, page, kind, rects, style=annotations.Style(color=_rgb(color)), contents=contents)

    def add_note(self, page: int, u: float, v: float, text: str, color: str) -> str:
        x, y = self.document.geometry(page).to_page(u, v)
        return annotations.add_note(self.document, self.history, page, x, y, text, style=annotations.Style(color=_rgb(color)))

    def add_ink(self, page: int, strokes: list, color: str, width: float) -> str:
        geo = self.document.geometry(page)
        converted = [[geo.to_page(float(point[0]), float(point[1])) for point in stroke] for stroke in strokes]
        return annotations.add_ink(self.document, self.history, page, converted, style=annotations.Style(color=_rgb(color), width=width))

    def add_shape(self, page: int, kind: str, view_rect, color: str, width: float, fill: str) -> str:
        rect = self.document.geometry(page).rect_to_page(normalize(tuple(view_rect)))
        return annotations.add_shape(self.document, self.history, page, kind, rect, style=annotations.Style(color=_rgb(color), width=width, fill=_rgb(fill)))

    def add_line(self, page: int, start, end, arrow: bool, color: str, width: float) -> str:
        geo = self.document.geometry(page)
        return annotations.add_line(self.document, self.history, page, geo.to_page(*start), geo.to_page(*end), arrow=arrow, style=annotations.Style(color=_rgb(color), width=width))

    def add_textbox(self, page: int, view_rect, text: str, color: str, size: float) -> str:
        rect = self.document.geometry(page).rect_to_page(normalize(tuple(view_rect)))
        return annotations.add_textbox(self.document, self.history, page, rect, text, style=annotations.Style(color=_rgb(color), width=1.0, font_size=size))

    def update_annotation(self, key: str, contents: str | None, color: str) -> None:
        annotations.update(self.document, self.history, key, contents=contents, color=_rgb(color))

    def move_annotation(self, key: str, du: float, dv: float) -> None:
        page, _position, _annot = annotations.find(self.document, key)
        geo = self.document.geometry(page)
        x0, y0 = geo.to_page(0, 0)
        x1, y1 = geo.to_page(du, dv)
        annotations.move(self.document, self.history, key, x1 - x0, y1 - y0)

    def delete_annotation(self, key: str) -> None:
        annotations.delete(self.document, self.history, key)

    # Formulare ------------------------------------------------------------------------------------------------
    def fields(self) -> list[dict]:
        result = []
        for info in forms.list_fields(self.document):
            widgets = []
            for widget in info.widgets:
                geo = self.document.geometry(widget.page)
                widgets.append({"page": widget.page, "view": list(geo.rect_to_view(widget.rect))})
            value = info.value
            result.append({"key": info.key, "name": info.name, "kind": info.kind, "value": value if isinstance(value, bool) else str(value), "options": [{"value": export_, "label": label} for export_, label in info.options], "widgets": widgets, "onValues": list(info.on_values), "multiline": info.multiline, "maxLength": info.max_length, "editable": info.editable, "reason": info.reason, "required": info.required})
        return result

    def set_field(self, key: str, value) -> None:
        forms.set_value(self.document, self.history, key, value)

    # Seiten ------------------------------------------------------------------------------------------------------
    def rotate_pages(self, indexes: list[int], degrees: int) -> None:
        pages.rotate(self.document, self.history, indexes, degrees)

    def delete_pages(self, indexes: list[int]) -> list[str]:
        return pages.delete(self.document, self.history, indexes)

    def duplicate_pages(self, indexes: list[int]) -> list[str]:
        return pages.duplicate(self.document, self.history, indexes)

    def insert_blank(self, index: int) -> None:
        pages.insert_blank(self.document, self.history, index)

    def move_pages(self, indexes: list[int], target: int) -> list[int]:
        return pages.move(self.document, self.history, indexes, target)

    def insert_file(self, index: int, path: str, password: str | None) -> list[str]:
        source = pages.open_source(path, password)
        return pages.insert_from(self.document, self.history, index, source)

    def merge_files(self, paths: list[str]) -> list[str]:
        sources = [pages.open_source(path) for path in paths]
        return pages.merge(self.document, self.history, sources)

    def extract(self, indexes: list[int], target: str) -> str:
        return str(pages.extract(self.document, indexes, target))

    def split(self, ranges: list[list[int]], folder: str, stem: str) -> list[str]:
        return [str(path) for path in pages.split(self.document, ranges, folder, stem)]

    def export_images(self, indexes: list[int], folder: str, stem: str, fmt: str, dpi: int) -> list[str]:
        return [str(path) for path in export.export_pages(self.document, indexes, folder, stem, fmt=fmt, dpi=dpi)]

    # Eigenschaften ---------------------------------------------------------------------------------------------
    def properties(self) -> dict:
        """Eigenschaften für den Dialog: bearbeitbare Felder und fertige Angaben (nur Struktur)."""
        props = metadata.read(self.document)
        data = {key: getattr(props, key) for key in ("title", "author", "subject", "keywords")}
        yes_no = {True: "ja", False: "nein"}
        facts = [
            ("Datei", props.file_name),
            ("Ort", str(Path(props.path).parent) if props.path else "noch nicht gespeichert"),
            ("Größe", _size_text(props.size_bytes) if props.size_bytes else "–"),
            ("PDF-Version", props.pdf_version),
            ("Seiten", str(props.pages)),
            ("Seitengröße", props.page_size + " (erste Seite)"),
            ("Erstellt mit", props.creator or "–"),
            ("PDF-Erzeuger", props.producer or "–"),
            ("Erstellt", props.created or "–"),
            ("Geändert", props.modified or "–"),
            ("Verschlüsselung", props.encryption if props.encrypted else "keine"),
            ("Einschränkungen", ", ".join(props.restrictions) if props.restrictions else "keine"),
            ("Formular", props.form or "keines"),
            ("Digitale Signaturen", str(props.signatures) if props.signatures else "keine"),
            ("JavaScript", "enthalten (wird nie ausgeführt)" if props.javascript else "keines"),
            ("Anhänge", str(props.attachments) if props.attachments else "keine"),
            ("Ebenen", yes_no[bool(props.layers)]),
            ("Getaggt (barrierearm)", yes_no[bool(props.tagged)]),
            ("Für schnelle Webanzeige", yes_no[bool(props.linearized)]),
        ]
        data["facts"] = [{"label": label, "value": value} for label, value in facts]
        data["fonts"] = [{"label": name, "value": f"{kind} · {'eingebettet' if embedded else 'nicht eingebettet'}", "tone": "" if embedded else "caution"} for name, kind, embedded in props.fonts]
        data["fontsNote"] = "" if props.fonts_complete else f"Schriften der ersten {metadata.FONT_SCAN_PAGES} Seiten."
        return data

    def set_metadata(self, values: dict) -> None:
        metadata.update(self.document, self.history, **{key: values.get(key) for key in ("title", "author", "subject", "keywords")})

    # Rückgängig, Speichern, Sicherung -----------------------------------------------------------------------------
    def undo(self) -> str:
        command = self.history.undo(self.document)
        return command.title if command is not None else ""

    def redo(self) -> str:
        command = self.history.redo(self.document)
        return command.title if command is not None else ""

    def save(self, target: str | None, force: bool = False) -> dict:
        """Sicher speichern (``tools.pdf_editor.save``). Ohne Änderungen am selben Ort: nichts zu tun
        (z. B. ein weiteres Strg+S direkt nach dem Speichern) – die Datei bleibt, wie sie ist."""
        path = Path(target) if target else self.document.path
        if path is None:
            raise EditorError("Für dieses Dokument gibt es noch keinen Speicherort.")
        same = self.document.path is not None and save._same(self.document.path, path)  # noqa: SLF001
        if same and not self.document.dirty and not force and path.is_file():
            return {"path": str(path), "size": 0, "backup": "", "name": self.document.name, "checked": 0, "unchanged": True}
        result = save.save(self.document, path, backup_dir=recovery.backups_dir(), force=force)
        if self.recovery is not None:
            self.recovery.discard()
            self.recovery = None
        if self.recovered_from is not None:
            recovery.discard_session(self.recovered_from)
            self.recovered_from = None
        return {"path": str(result.path), "size": result.size, "backup": str(result.backup or ""), "name": self.document.name, "checked": result.checked_pages, "unchanged": False}

    def write_recovery(self) -> bool:
        """Ungespeicherten Stand sichern (für den Fall eines Absturzes)."""
        if not self.document.dirty or self.closed:
            return False
        if self.recovery is None:
            self.recovery = recovery.RecoverySession(self.document.name, self.document.path, self.document.encrypted)
        self.recovery.write(self.document.serialize(keep_encryption=True))
        if self.recovered_from is not None:
            recovery.discard_session(self.recovered_from)  # durch die neue Sitzung ersetzt
            self.recovered_from = None
        return True

    def discard_recovery(self) -> None:
        if self.recovery is not None:
            self.recovery.discard()
            self.recovery = None
        if self.recovered_from is not None:
            recovery.discard_session(self.recovered_from)
            self.recovered_from = None

    def print_image(self, page: int, dpi: int):
        """Seite für den Druck (Graustufen/Farbe wie angezeigt) in Druckerauflösung."""
        geo = self.document.geometry(page)
        return self.render(page, max(8, int(geo.width * dpi / 72)))


def _size_text(size: int) -> str:
    if size >= 1024 * 1024:
        return f"{size / 1024 / 1024:.1f} MB".replace(".", ",")
    return f"{max(1, round(size / 1024))} KB"


def _rgb(color: str | None) -> tuple[int, int, int] | None:
    if not color:
        return None
    text = str(color).lstrip("#")
    if len(text) == 8:  # #AARRGGBB aus QML
        text = text[2:]
    try:
        return (int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16))
    except (ValueError, IndexError):
        return None


def _text_style(style: dict | None):
    if not style:
        return None
    return textedit.TextStyle(
        family=style.get("family") or None,
        size=float(style["size"]) if style.get("size") else None,
        color=_rgb(style.get("color")),
        bold=style.get("bold"),
        italic=style.get("italic"),
        align=style.get("align") or None,
    )
