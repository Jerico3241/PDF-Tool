"""Seiten darstellen (PDFium): ganze Seite, Ausschnitt für hohe Zoomstufen, Miniatur.

Ergebnis sind rohe Pixel (``BGRx``, 4 Byte je Pixel) – die Oberfläche macht daraus ohne Kopie
über PIL ein ``QImage`` (Format ``RGB32``). Formularfelder und Anmerkungen werden mit ihren
Erscheinungsbildern dargestellt; PDF-JavaScript führt PDFium in diesem Build nicht aus.

Grenzen schützen den Speicher: Ein ganzes Seitenbild hat höchstens ``MAX_PIXELS`` Pixel. Darüber
zeigt die Oberfläche die Seite in dieser Auflösung und stellt den sichtbaren Ausschnitt zusätzlich
scharf dar (``render_region``).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from pdfium_lock import PDFIUM_LOCK

from .document import EditorDocument
from .geometry import Rect

MAX_PIXELS = 16_000_000  # ≈ 64 MB je Bild; z. B. A4 bis ≈ 400 % bei 96 dpi
MIN_SIDE = 8


@dataclass(frozen=True)
class Raster:
    """Gerenderte Pixel: ``data`` (BGRx), ``width``, ``height``, ``stride`` (Bytes je Zeile)."""

    data: bytes
    width: int
    height: int
    stride: int

    @property
    def nbytes(self) -> int:
        return len(self.data)


def full_scale(document: EditorDocument, index: int, width_px: int) -> float:
    """Maßstab (Pixel je Punkt) für ein Seitenbild der Breite ``width_px`` – innerhalb der Grenze."""
    geo = document.geometry(index)
    scale = max(MIN_SIDE, width_px) / max(1.0, geo.width)
    pixels = geo.width * geo.height * scale * scale
    if pixels > MAX_PIXELS:
        scale *= math.sqrt(MAX_PIXELS / pixels)
    return scale


def render_page(document: EditorDocument, index: int, width_px: int, *, annotations: bool = True) -> Raster:
    """Ganze Seite in (höchstens) ``width_px`` Pixel Breite."""
    scale = full_scale(document, index, width_px)
    return _render(document, index, scale, (0.0, 0.0, 0.0, 0.0), annotations)


def render_region(document: EditorDocument, index: int, region: Rect, scale: float, *, annotations: bool = True) -> Raster:
    """Ausschnitt ``region`` (Anzeige-Punkte: x0, y0, x1, y1, Ursprung oben links) im Maßstab ``scale``."""
    geo = document.geometry(index)
    x0 = max(0.0, min(region[0], geo.width))
    y0 = max(0.0, min(region[1], geo.height))
    x1 = max(x0, min(region[2], geo.width))
    y1 = max(y0, min(region[3], geo.height))
    if (x1 - x0) * (y1 - y0) * scale * scale > MAX_PIXELS:
        scale = math.sqrt(MAX_PIXELS / max(1.0, (x1 - x0) * (y1 - y0)))
    # PDFium schneidet in Punkten von den Rändern der gedrehten Seite ab: links, unten, rechts, oben
    crop = (x0, geo.height - y1, geo.width - x1, y0)
    return _render(document, index, scale, crop, annotations)


def _render(document: EditorDocument, index: int, scale: float, crop: tuple[float, float, float, float], annotations: bool) -> Raster:
    import pypdfium2.raw as pdfium_c

    with PDFIUM_LOCK:
        page = document.view()[index]
        try:
            bitmap = page.render(
                scale=scale,
                crop=crop,
                may_draw_forms=True,
                draw_annots=annotations,
                fill_color=(255, 255, 255, 255),
                force_bitmap_format=pdfium_c.FPDFBitmap_BGRx,
                limit_image_cache=True,
            )
            try:
                width, height, stride = bitmap.width, bitmap.height, bitmap.stride
                data = bytes(bitmap.buffer)
            finally:
                bitmap.close()
        finally:
            page.close()
    return Raster(data, width, height, stride)


def to_pil(raster: Raster):
    """Für Export und Tests: Raster → PIL-Bild (RGB)."""
    from PIL import Image

    return Image.frombuffer("RGBX", (raster.width, raster.height), raster.data, "raw", "BGRX", raster.stride, 1).convert("RGB")
