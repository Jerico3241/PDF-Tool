"""Koordinaten: PDF-Benutzerraum der Seite ↔ Anzeige.

* **Seite** – PDF-Punkte, Ursprung unten links, ungedreht (so stehen Text, Bilder und
  Anmerkungen in der Datei).
* **Anzeige** – Punkte der dargestellten Seite: CropBox als sichtbarer Bereich, ``/Rotate``
  angewendet, Ursprung oben links, y wächst nach unten. Die Oberfläche multipliziert nur noch mit
  dem Zoom. Dieselbe Abbildung verwendet PDFium beim Darstellen (``FPDF_PageToDevice``).
"""

from __future__ import annotations

from dataclasses import dataclass

Rect = tuple[float, float, float, float]  # x0, y0, x1, y1


def normalize(rect: Rect) -> Rect:
    x0, y0, x1, y1 = rect
    return (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))


def union(a: Rect | None, b: Rect | None) -> Rect | None:
    if a is None:
        return b
    if b is None:
        return a
    return (min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3]))


def intersects(a: Rect, b: Rect) -> bool:
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def inflate(rect: Rect, by: float) -> Rect:
    return (rect[0] - by, rect[1] - by, rect[2] + by, rect[3] + by)


def contains(rect: Rect, x: float, y: float) -> bool:
    return rect[0] <= x <= rect[2] and rect[1] <= y <= rect[3]


@dataclass(frozen=True)
class PageGeometry:
    crop: Rect  # sichtbarer Bereich der Seite (CropBox, auf die MediaBox begrenzt)
    rotation: int = 0  # 0, 90, 180 oder 270 (im Uhrzeigersinn)

    @property
    def width(self) -> float:
        """Breite der angezeigten Seite (Punkte)."""
        w, h = self.crop[2] - self.crop[0], self.crop[3] - self.crop[1]
        return h if self.rotation in (90, 270) else w

    @property
    def height(self) -> float:
        w, h = self.crop[2] - self.crop[0], self.crop[3] - self.crop[1]
        return w if self.rotation in (90, 270) else h

    def to_view(self, x: float, y: float) -> tuple[float, float]:
        x0, y0, x1, y1 = self.crop
        if self.rotation == 90:
            return y - y0, x - x0
        if self.rotation == 180:
            return x1 - x, y - y0
        if self.rotation == 270:
            return y1 - y, x1 - x
        return x - x0, y1 - y

    def to_page(self, u: float, v: float) -> tuple[float, float]:
        x0, y0, x1, y1 = self.crop
        if self.rotation == 90:
            return x0 + v, y0 + u
        if self.rotation == 180:
            return x1 - u, y0 + v
        if self.rotation == 270:
            return x1 - v, y1 - u
        return x0 + u, y1 - v

    def rect_to_view(self, rect: Rect) -> Rect:
        a = self.to_view(rect[0], rect[1])
        b = self.to_view(rect[2], rect[3])
        return normalize((a[0], a[1], b[0], b[1]))

    def rect_to_page(self, rect: Rect) -> Rect:
        a = self.to_page(rect[0], rect[1])
        b = self.to_page(rect[2], rect[3])
        return normalize((a[0], a[1], b[0], b[1]))


def rotation_of(value) -> int:
    """``/Rotate`` auf 0/90/180/270 bringen (auch negative und große Werte; Unsinn → 0)."""
    try:
        angle = int(value)
    except (TypeError, ValueError):
        return 0
    angle %= 360
    return angle if angle in (0, 90, 180, 270) else 0
