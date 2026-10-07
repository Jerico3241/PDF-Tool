"""Ein geöffnetes Dokument im Arbeitsthread des Editors.

Alle Methoden laufen **nur** im Arbeitsthread (``engine.Engine``) – nie im GUI-Thread. Die
Oberfläche erhält Ergebnisse als einfache Werte (Listen, Wörterbücher, ``QImage``). Koordinaten
für die Oberfläche sind **Anzeige-Punkte** der Seite (Ursprung oben links, Drehung der Seite
berücksichtigt); umgerechnet wird hier mit der Seitengeometrie.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

from tools.pdf_editor import annotations, attachments, commands, export, formdesign, forms, images, metadata, objectops, ocr, outline, pages, recovery, render, save, textedit, textlayer
from tools.pdf_editor import objects as object_edit
from tools.pdf_editor.document import EditorDocument
from tools.pdf_editor.errors import EditorError
from tools.pdf_editor.geometry import normalize, union

from .engine import raster_to_qimage


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
        self._objects: dict[int, object_edit.PageObjects] = {}  # Objektmodell je Seite (Stand des Dokuments)
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
        document.revision = 1
        document.saved_state = -1  # wiederhergestellt = ungespeichert (auch nach Rückgängig)
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

    # Objekt bearbeiten ------------------------------------------------------------------------------------------
    def page_objects(self, page: int) -> object_edit.PageObjects:
        """Segmente, Wörter (und Bilder) einer Seite – je Stand des Dokuments einmal analysiert."""
        cached = self._objects.get(page)
        if cached is None or cached.revision != self.document.revision:
            cached = object_edit.analyze(self.document, page)
            self._objects[page] = cached
            if len(self._objects) > 12:
                self._objects.pop(next(iter(self._objects)))
        return cached

    def objects(self, page: int) -> dict:
        if not 0 <= page < self.document.page_count:
            return {"page": page, "revision": self.document.revision, "segments": [], "images": [], "message": ""}
        return object_edit.describe(self.document, self.page_objects(page))

    def _object_result(self, outcome, page: int) -> dict:
        geo = self.document.geometry(page)
        return {"mode": outcome.mode, "label": outcome.label, "notes": list(outcome.notes), "view": list(geo.rect_to_view(outcome.bounds)), "page": page}

    def object_edit(self, page: int, ident: str, text: str) -> dict:
        return self._object_result(object_edit.edit_text(self.document, self.history, self.page_objects(page), ident, text), page)

    def _mixed_result(self, area, page: int) -> dict:
        """Ergebnis einer Bedienung mit gemischter Auswahl – der Modus ehrlich: »neu gesetzt«, sobald ein Teil
        neu gesetzt wurde (nicht nur der zuletzt geänderte)."""
        geo = self.document.geometry(page)
        last = self.history.last
        steps = last.commands if isinstance(last, commands.CommandGroup) else ([last] if last is not None else [])
        modes = [step.info.get("mode", "") for step in steps]
        mode = next((wanted for wanted in (textedit.OVERLAY, textedit.RECONSTRUCTED) if wanted in modes), textedit.NATIVE)
        return {"mode": mode, "label": textedit.MODE_LABELS[mode], "notes": [], "view": list(geo.rect_to_view(area)) if area else [], "page": page}

    @staticmethod
    def _only_text(idents) -> bool:
        return all(objectops.parse(ident).kind == objectops.TEXT for ident in idents)

    def object_delete(self, page: int, idents: list[str]) -> dict:
        found = self.page_objects(page)
        if self._only_text(idents):
            return self._object_result(object_edit.delete(self.document, self.history, found, list(idents)), page)
        return self._mixed_result(objectops.delete(self.document, self.history, found, list(idents)), page)

    def _page_shift(self, page: int, du: float, dv: float) -> tuple[float, float]:
        """Verschiebung in der Anzeige (Punkte) → Seitenkoordinaten (Drehung der Seite berücksichtigt)."""
        geo = self.document.geometry(page)
        x0, y0 = geo.to_page(0.0, 0.0)
        x1, y1 = geo.to_page(du, dv)
        return x1 - x0, y1 - y0

    def object_move(self, page: int, idents: list[str], du: float, dv: float) -> dict:
        dx, dy = self._page_shift(page, du, dv)
        found = self.page_objects(page)
        if self._only_text(idents):
            return self._object_result(object_edit.move(self.document, self.history, found, list(idents), dx, dy), page)
        return self._mixed_result(objectops.move_each(self.document, self.history, found, {ident: (dx, dy) for ident in idents}, title="Verschieben"), page)

    def object_style(self, page: int, idents: list[str], name: str, value) -> dict:
        """Eine Eigenschaft der Auswahl ändern: Text (Größe, Zeichenabstand, Farbe, Schrift, Fett, Kursiv),
        Vektorobjekte (Strich-, Füllfarbe, Linienstärke) und für alle die Deckkraft."""
        found = self.page_objects(page)
        if name in ("color", "stroke", "fill"):
            converted = _rgb(str(value))
            if converted is None:
                raise EditorError("Diese Farbe lässt sich nicht verwenden.")
        elif name in ("size", "spacing", "width", "opacity"):
            converted = float(value)
        elif name == "family":
            converted = str(value)
        elif name in ("bold", "italic"):
            converted = bool(value)
        else:
            raise EditorError("Diese Eigenschaft lässt sich nicht ändern.")
        if name in ("size", "spacing", "color") and self._only_text(idents):
            outcome = object_edit.restyle(self.document, self.history, found, list(idents), **{name: converted})
            return self._object_result(outcome, page)
        return self._mixed_result(objectops.style(self.document, self.history, found, list(idents), name, converted), page)

    def object_duplicate(self, page: int, idents: list[str]) -> dict:
        dx, dy = self._page_shift(page, 12.0, 12.0)  # in der Anzeige nach rechts unten versetzt
        found = self.page_objects(page)
        if len(idents) == 1 and self._only_text(idents):
            return self._object_result(object_edit.duplicate(self.document, self.history, found, idents[0], (dx, dy)), page)
        return self._mixed_result(objectops.duplicate(self.document, self.history, found, list(idents), (dx, dy)), page)

    def _view_boxes(self, found, idents, *, readable: bool = False) -> dict[str, tuple[float, float, float, float]]:
        geo = self.document.geometry(found.page)
        boxes = (objectops.bounds_of_readable if readable else objectops.bounds_of)(self.document, found, idents)
        return {ident: geo.rect_to_view(box) for ident, box in boxes.items()}

    def object_align(self, page: int, idents: list[str], how: str) -> dict:
        """Ausrichten in der Anzeige (links, Mitte, rechts, oben, Mitte, unten) bzw. gleichmäßig verteilen
        (waagerecht, senkrecht) – auch auf gedrehten Seiten und für gemischte Auswahlen."""
        found = self.page_objects(page)
        boxes = self._view_boxes(found, idents)
        if len(boxes) < 2:
            raise EditorError("Zum Ausrichten mindestens zwei Objekte auswählen.")
        moves: dict[str, tuple[float, float]] = {}
        if how in ("left", "top", "right", "bottom"):
            index = {"left": 0, "top": 1, "right": 2, "bottom": 3}[how]
            edge = (min if index in (0, 1) else max)(box[index] for box in boxes.values())
            for ident, box in boxes.items():
                moves[ident] = (edge - box[index], 0.0) if index in (0, 2) else (0.0, edge - box[index])
        elif how in ("hcenter", "vcenter"):
            area = None
            for box in boxes.values():
                area = union(area, box)
            if how == "hcenter":
                middle = (area[0] + area[2]) / 2
                moves = {ident: (middle - (box[0] + box[2]) / 2, 0.0) for ident, box in boxes.items()}
            else:
                middle = (area[1] + area[3]) / 2
                moves = {ident: (0.0, middle - (box[1] + box[3]) / 2) for ident, box in boxes.items()}
        elif how in ("hspace", "vspace"):
            if len(boxes) < 3:
                raise EditorError("Zum Verteilen mindestens drei Objekte auswählen.")
            lo, hi = (0, 2) if how == "hspace" else (1, 3)
            ordered = sorted(boxes.items(), key=lambda item: (item[1][lo] + item[1][hi]) / 2)
            total = sum(box[hi] - box[lo] for _ident, box in ordered)
            start, end = ordered[0][1][lo], ordered[-1][1][hi]
            gap = (end - start - total) / (len(ordered) - 1)
            position = start
            for ident, box in ordered:
                shift = position - box[lo]
                moves[ident] = (shift, 0.0) if how == "hspace" else (0.0, shift)
                position += box[hi] - box[lo] + gap
        else:
            raise EditorError("Unbekannte Ausrichtung.")
        shifts = {ident: self._page_shift(page, du, dv) for ident, (du, dv) in moves.items() if abs(du) > 0.01 or abs(dv) > 0.01}
        if not shifts:
            return {"mode": textedit.NATIVE, "label": textedit.MODE_LABELS[textedit.NATIVE], "notes": [], "view": [], "page": page}
        title = "Verteilen" if how in ("hspace", "vspace") else "Ausrichten"
        result = self._mixed_result(objectops.move_each(self.document, self.history, found, shifts, title=title), page)
        result["views"] = [[box[0] + moves[ident][0], box[1] + moves[ident][1], box[2] + moves[ident][0], box[3] + moves[ident][1]] for ident, box in boxes.items()]
        return result

    def _view_transform(self, page: int, func) -> tuple:
        """Abbildung in der Anzeige (u, v → u', v') als Matrix im Seitenraum."""
        geo = self.document.geometry(page)

        def mapped(x: float, y: float) -> tuple[float, float]:
            return geo.to_page(*func(*geo.to_view(x, y)))

        return tuple(round(value, 9) for value in objectops.affine(mapped))

    def object_rotate(self, page: int, idents: list[str], degrees: float) -> dict:
        """Auswahl um ihre Mitte drehen – ``degrees`` im Uhrzeigersinn, wie in der Anzeige."""
        found = self.page_objects(page)
        boxes = self._view_boxes(found, idents)
        area = None
        for box in boxes.values():
            area = union(area, box)
        if area is None:
            raise EditorError("Es ist nichts ausgewählt.")
        cu, cv = (area[0] + area[2]) / 2, (area[1] + area[3]) / 2
        rad = math.radians(float(degrees))
        cos, sin = round(math.cos(rad), 12), round(math.sin(rad), 12)

        def turn(u: float, v: float) -> tuple[float, float]:
            du, dv = u - cu, v - cv  # v zeigt nach unten: so dreht es im Uhrzeigersinn
            return cu + du * cos - dv * sin, cv + du * sin + dv * cos

        result = self._mixed_result(objectops.transform(self.document, self.history, found, list(idents), self._view_transform(page, turn), title="Drehen"), page)
        views = []
        for box in boxes.values():
            corners = [turn(u, v) for u, v in ((box[0], box[1]), (box[2], box[1]), (box[0], box[3]), (box[2], box[3]))]
            views.append([min(c[0] for c in corners), min(c[1] for c in corners), max(c[0] for c in corners), max(c[1] for c in corners)])
        result["views"] = views
        return result

    def object_resize(self, page: int, idents: list[str], view_rect) -> dict:
        """Bilder und Vektorobjekte auf einen neuen Bereich (Anzeige) bringen – Text ändert man über die
        Schriftgröße."""
        if any(objectops.parse(ident).kind == objectops.TEXT for ident in idents):
            raise EditorError("Die Größe von Text ändert man über die Schriftgröße.")
        found = self.page_objects(page)
        old = None
        for box in self._view_boxes(found, idents).values():
            old = union(old, box)
        new = normalize(tuple(float(value) for value in view_rect))
        if old is None or new[2] - new[0] < 1 or new[3] - new[1] < 1:
            raise EditorError("Diese Größe ist zu klein.")
        sx = (new[2] - new[0]) / max(0.01, old[2] - old[0])
        sy = (new[3] - new[1]) / max(0.01, old[3] - old[1])

        def fit(u: float, v: float) -> tuple[float, float]:
            return new[0] + (u - old[0]) * sx, new[1] + (v - old[1]) * sy

        return self._mixed_result(objectops.transform(self.document, self.history, found, list(idents), self._view_transform(page, fit), title="Größe ändern"), page)

    def object_arrange(self, page: int, idents: list[str], front: bool) -> dict:
        return self._mixed_result(objectops.arrange(self.document, self.history, self.page_objects(page), list(idents), bool(front)), page)

    def object_copy(self, page: int, idents: list[str]) -> objectops.Clip:
        """Auswahl in die Zwischenablage der Objekte (das Dokument bleibt unverändert)."""
        return objectops.copy(self.document, self.page_objects(page), list(idents), self.ident)

    def object_picture(self, page: int, idents: list[str]):
        """Bild der Auswahl für andere Programme (Zwischenablage des Systems) – nur ohne Text: so, wie die
        Objekte auf der Seite zu sehen sind (bei einem Bild etwa in seiner Auflösung, höchstens 4000 Pixel)."""
        if not idents or any(objectops.parse(ident).kind == objectops.TEXT for ident in idents):
            return None
        found = self.page_objects(page)
        area = None
        for box in self._view_boxes(found, idents, readable=True).values():
            area = union(area, box)
        if area is None or area[2] - area[0] < 1 or area[3] - area[1] < 1:
            return None
        scale = 2.0
        if len(idents) == 1 and objectops.parse(idents[0]).kind == objectops.IMAGE:
            item = next((entry for entry in images.list_images(self.document, page) if entry.index == objectops.parse(idents[0]).index), None)
            if item is not None and item.pixels[0]:
                scale = item.pixels[0] / (area[2] - area[0])
        scale = max(1.0, min(scale, 4.0, 4000 / (area[2] - area[0]), 4000 / (area[3] - area[1])))
        return raster_to_qimage(render.render_region(self.document, page, tuple(area), scale))

    def object_paste(self, page: int, clip: objectops.Clip, at, nudge: int) -> dict:
        placed = objectops.paste(self.document, self.history, page, clip, tuple(at) if at else None, nudge=nudge)
        return {**self._mixed_result(None, page), "view": list(placed)}

    # Texterkennung (OCR) -----------------------------------------------------------------------------------------
    def ocr_scan(self, pages) -> tuple[list[dict], int]:
        """Welche Seiten brauchen eine Texterkennung? Dazu der Stand des Dokuments (für die spätere Prüfung)."""
        scans = ocr.scan_pages(self.document, pages)
        return [{"page": scan.page, "chars": scan.chars, "cover": scan.image_cover, "layer": scan.ocr_layer, "needs": scan.needs_ocr} for scan in scans], self.document.revision

    def ocr_image(self, page: int) -> tuple[bytes, int, int]:
        """Seitenbild für Tesseract (Graustufen-PNG), verwendete Auflösung und Stand des Dokuments."""
        png, dpi = ocr.render_page_image(self.document, page)
        return png, dpi, self.document.revision

    def ocr_apply(self, results: list, revision: int) -> int:
        """Erkannten Text als unsichtbare Textebene übernehmen – nur, wenn das Dokument noch so ist wie beim
        Erkennen (ein Schritt für Rückgängig)."""
        if self.document.revision != revision:
            raise ocr.OcrError("Das Dokument wurde während der Texterkennung geändert. Bitte den Text erneut erkennen.")
        return ocr.apply_text_layers(self.document, self.history, results)

    def ocr_remove(self, pages) -> int:
        return ocr.remove_text_layers(self.document, self.history, pages)

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
            result.append({
                "key": info.key, "page": info.page, "label": info.label, "subtype": info.subtype, "view": list(geo.rect_to_view(info.rect)),
                "contents": info.contents, "author": info.author, "modified": info.modified, "color": color, "ours": info.ours,
                "replyTo": info.reply_to, "width": info.width if info.width is not None else -1.0,
                "fill": "#%02X%02X%02X" % info.fill if info.fill else "", "opacity": info.opacity,
                "fontSize": info.font_size if info.font_size is not None else -1.0,
                "resizable": info.ours and info.subtype in annotations.RESIZABLE and not info.reply_to,
            })
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

    def restyle_annotation(self, key: str, name: str, value) -> None:
        """Eine Eigenschaft eines Kommentars: width, fill (Farbe oder leer = keine), opacity (0–1), fontSize."""
        if name == "width":
            annotations.restyle(self.document, self.history, key, width=float(value))
        elif name == "fill":
            annotations.restyle(self.document, self.history, key, fill=_rgb(str(value)) if value else None)
        elif name == "opacity":
            annotations.restyle(self.document, self.history, key, opacity=float(value))
        elif name == "fontSize":
            annotations.restyle(self.document, self.history, key, font_size=float(value))
        else:
            raise EditorError("Diese Eigenschaft lässt sich nicht ändern.")

    def resize_annotation(self, key: str, view_rect) -> None:
        page, _position, _annot = annotations.find(self.document, key)
        rect = self.document.geometry(page).rect_to_page(normalize(tuple(float(v) for v in view_rect)))
        annotations.resize(self.document, self.history, key, rect)

    def reply_annotation(self, key: str, text: str) -> str:
        return annotations.add_reply(self.document, self.history, key, text)

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

    # Formulare gestalten (Koordinaten der Anzeige, je Seite) --------------------------------------------------
    def design_widgets(self) -> list[dict]:
        result = []
        for item in formdesign.list_widgets(self.document):
            geo = self.document.geometry(item.page)
            result.append({
                "key": item.key, "field": item.field, "name": item.name, "kind": item.kind, "page": item.page,
                "view": [round(v, 2) for v in geo.rect_to_view(item.rect)], "export": item.export, "tooltip": item.tooltip,
                "required": item.required, "readOnly": item.read_only, "multiline": item.multiline, "maxLength": item.max_length,
                "fontSize": item.font_size, "align": item.align, "options": list(item.options), "border": item.border,
                "background": item.background, "siblings": item.siblings, "ours": item.ours,
            })
        return result

    def _page_rect(self, page: int, view_rect) -> tuple[float, float, float, float]:
        return self.document.geometry(page).rect_to_page(normalize(tuple(float(v) for v in view_rect)))

    def _free_spot(self, page: int, view_rect, gap: float = 8.0) -> list[float]:
        """Platz für eine Kopie: darunter, sonst rechts daneben, sonst leicht versetzt (in der Anzeige)."""
        geo = self.document.geometry(page)
        u0, v0, u1, v1 = view_rect
        width, height = u1 - u0, v1 - v0
        if v1 + gap + height <= geo.height:
            return [u0, v1 + gap, u1, v1 + gap + height]
        if u1 + gap + width <= geo.width:
            return [u1 + gap, v0, u1 + gap + width, v1]
        return [u0 + 12, v0 + 12, u1 + 12, v1 + 12]

    def _widget_view(self, key: str) -> tuple[int, list[float]]:
        for item in formdesign.list_widgets(self.document):
            if item.key == key:
                return item.page, list(self.document.geometry(item.page).rect_to_view(item.rect))
        raise EditorError("Das Formularfeld ist nicht mehr vorhanden.")

    def create_field(self, page: int, kind: str, view_rect) -> str:
        return formdesign.create(self.document, self.history, page, kind, self._page_rect(page, view_rect))

    def move_field(self, key: str, du: float, dv: float) -> None:
        page, view = self._widget_view(key)
        moved = self._page_rect(page, [view[0] + du, view[1] + dv, view[2] + du, view[3] + dv])
        current = self._page_rect(page, view)
        formdesign.move(self.document, self.history, [key], moved[0] - current[0], moved[1] - current[1])

    def resize_field(self, key: str, view_rect) -> None:
        page, _view = self._widget_view(key)
        formdesign.resize(self.document, self.history, key, self._page_rect(page, view_rect))

    def delete_field(self, key: str) -> None:
        formdesign.delete(self.document, self.history, [key])

    def duplicate_field(self, key: str) -> str:
        page, view = self._widget_view(key)
        target = self._page_rect(page, self._free_spot(page, view))
        current = self._page_rect(page, view)
        return formdesign.duplicate(self.document, self.history, [key], target[0] - current[0], target[1] - current[1])[0]

    def add_field_option(self, key: str) -> str:
        page, view = self._widget_view(key)
        return formdesign.add_option(self.document, self.history, key, self._page_rect(page, self._free_spot(page, view, 6.0)))

    def field_properties(self, key: str, changes: dict) -> None:
        formdesign.set_properties(self.document, self.history, key, changes)

    # Anhänge ------------------------------------------------------------------------------------------------------
    def attachments(self) -> list[dict]:
        return [{"key": item.key, "name": item.name, "description": item.description, "size": item.size, "modified": item.modified, "page": item.page, "openable": item.openable} for item in attachments.list_attachments(self.document)]

    def save_attachment(self, key: str, target: str) -> str:
        return str(attachments.save_to(self.document, key, target))

    def open_attachment(self, key: str, folder: str) -> str:
        return str(attachments.export_for_opening(self.document, key, folder))

    def add_attachment(self, path: str, description: str) -> str:
        return attachments.add(self.document, self.history, path, description)

    def remove_attachment(self, key: str) -> None:
        attachments.remove(self.document, self.history, key)

    # Seiten ------------------------------------------------------------------------------------------------------
    def rotate_pages(self, indexes: list[int], degrees: int) -> None:
        pages.rotate(self.document, self.history, indexes, degrees)

    def delete_pages(self, indexes: list[int], cut: bool = False) -> list[str]:
        return pages.delete(self.document, self.history, indexes, cut=cut)

    def duplicate_pages(self, indexes: list[int]) -> list[str]:
        return pages.duplicate(self.document, self.history, indexes)

    def insert_blank(self, index: int) -> None:
        pages.insert_blank(self.document, self.history, index)

    def move_pages(self, indexes: list[int], target: int) -> list[int]:
        return pages.move(self.document, self.history, indexes, target)

    def source_pages(self, path: str, password: str | None) -> int:
        """Seitenzahl einer anderen PDF (vor dem Einfügen – für die Auswahl der Seiten)."""
        source = pages.open_source(path, password)
        try:
            return len(source.pages)
        finally:
            source.close()

    def insert_file(self, index: int, path: str, password: str | None, chosen: list[int] | None = None) -> list[str]:
        source = pages.open_source(path, password)
        return pages.insert_from(self.document, self.history, index, source, chosen)

    def copy_pages(self, indexes: list[int]) -> bytes:
        return pages.copy_pages(self.document, indexes)

    def paste_pages(self, index: int, data: bytes) -> list[str]:
        import io

        import pikepdf

        source = pikepdf.open(io.BytesIO(data))
        return pages.insert_from(self.document, self.history, index, source, title="Seiten einfügen")

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
        underline=bool(style["underline"]) if style.get("underline") is not None else None,
        strike=bool(style["strike"]) if style.get("strike") is not None else None,
    )
