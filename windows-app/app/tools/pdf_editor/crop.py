"""Seiten zuschneiden: den sichtbaren Bereich (``/CropBox``) verkleinern oder zurücksetzen.

Ränder werden in der **Anzeige** angegeben (links, oben, rechts, unten in Punkten – wie man die Seite
sieht, auch gedreht) und für jede gewählte Seite auf ihre eigene Größe angewendet. Zuschneiden blendet
nur aus: Der Inhalt außerhalb bleibt in der Datei (zum Entfernen gibt es »Schwärzen«).
"""

from __future__ import annotations

from pikepdf import Array

from .commands import History, record
from .document import DEFAULT_MEDIABOX, EditorDocument, _box, inherited
from .errors import EditorError

MIN_SIZE = 36.0  # kleinster sichtbarer Bereich (Punkte)
WHITE = 245  # heller als das gilt als leer (Ränder erkennen)
PROBE_WIDTH = 500  # Pixelbreite für die Erkennung der Ränder


def crop_pages(document: EditorDocument, history: History, indexes: list[int], margins: tuple[float, float, float, float]) -> int:
    document.ensure_editable("assemble")
    chosen = sorted({int(i) for i in indexes if 0 <= int(i) < document.page_count})
    left, top, right, bottom = (max(0.0, float(value)) for value in margins)
    if not chosen:
        return 0
    boxes = {}
    for index in chosen:
        geo = document.geometry(index)
        view = (left, top, geo.width - right, geo.height - bottom)
        if view[2] - view[0] < MIN_SIZE or view[3] - view[1] < MIN_SIZE:
            raise EditorError(f"Auf Seite {index + 1} bliebe zu wenig sichtbar.")
        rect = geo.rect_to_page(view)
        media = _box(inherited(document.pdf.pages[index].obj, "/MediaBox")) or DEFAULT_MEDIABOX
        rect = (max(rect[0], media[0]), max(rect[1], media[1]), min(rect[2], media[2]), min(rect[3], media[3]))
        boxes[index] = rect
    with record(document, history, "Seiten zuschneiden" if len(chosen) > 1 else "Seite zuschneiden", pages=tuple(chosen)) as rec:
        for index, rect in boxes.items():
            page = rec.page(index)
            page.CropBox = Array([round(value, 3) for value in rect])
    return len(chosen)


def reset_crop(document: EditorDocument, history: History, indexes: list[int]) -> int:
    """Zuschnitt aufheben (wieder die ganze Seite)."""
    document.ensure_editable("assemble")
    chosen = [i for i in sorted({int(i) for i in indexes if 0 <= int(i) < document.page_count}) if "/CropBox" in document.pdf.pages[i].obj]
    if not chosen:
        return 0
    with record(document, history, "Zuschnitt aufheben", pages=tuple(chosen)) as rec:
        for index in chosen:
            page = rec.page(index)
            del page["/CropBox"]
    return len(chosen)


def content_margins(document: EditorDocument, index: int, padding: float = 6.0) -> tuple[float, float, float, float]:
    """Vorschlag für »Ränder entfernen«: Abstand des Inhalts zu den Seitenrändern (Anzeige-Punkte),
    abzüglich eines kleinen Abstands. Eine leere Seite ergibt keine Ränder."""
    from .render import render_page

    geo = document.geometry(index)
    raster = render_page(document, index, PROBE_WIDTH, annotations=True)
    from .render import to_pil

    image = to_pil(raster).convert("L")
    box = image.point(lambda value: 255 if value < WHITE else 0).getbbox()
    if box is None:
        return (0.0, 0.0, 0.0, 0.0)
    scale = raster.width / max(1.0, geo.width)
    x0, y0, x1, y1 = (value / scale for value in box)
    return (
        max(0.0, x0 - padding),
        max(0.0, y0 - padding),
        max(0.0, geo.width - x1 - padding),
        max(0.0, geo.height - y1 - padding),
    )
