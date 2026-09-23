"""Kantengeglättete Formen für Tk.

Der Tk-Canvas zeichnet unter Windows ohne Kantenglättung. Runde Ecken,
Kreise und der Fortschrittsring werden deshalb mit Pillow in vierfacher
Auflösung gerendert, verkleinert und als PhotoImage zwischengespeichert.

Flächen mit veränderlicher Breite (Schaltflächen, Eingabefelder) werden als
»3-Slice« gezeichnet: zwei gerenderte Eckstücke und dazwischen einfarbige
Canvas-Rechtecke. Eine Breitenänderung verschiebt dann nur noch Elemente,
ohne ein neues Bild zu rendern.
"""

from __future__ import annotations

import base64
import io
import math
from collections import OrderedDict
from typing import Callable

import tkinter as tk
from PIL import Image, ImageDraw

from .theme import rgb

SUPERSAMPLE = 4
_RESAMPLE_BOX = getattr(Image, "Resampling", Image).BOX


def _rgba(color: str | None, alpha: int = 255) -> tuple[int, int, int, int]:
    if not color:
        return (0, 0, 0, 0)
    red, green, blue = rgb(color)
    return (red, green, blue, alpha)


def _finish(img: Image.Image, width: int, height: int, background: str | None, alpha: float = 1.0) -> Image.Image:
    small = img.resize((max(1, width), max(1, height)), _RESAMPLE_BOX)
    if alpha < 1.0:
        channel = small.getchannel("A").point(lambda value: int(value * alpha))
        small.putalpha(channel)
    if background:
        base = Image.new("RGBA", small.size, _rgba(background))
        base.alpha_composite(small)
        return base.convert("RGB")
    return small


def rounded_box(
    width: int,
    height: int,
    radius: float,
    fill: str | None,
    stroke: str | None = None,
    edge: str | None = None,
    edge_side: str = "bottom",
    stroke_width: float = 1,
    background: str | None = None,
    edge_width: float | None = None,
    alpha: float = 1.0,
) -> Image.Image:
    """Abgerundetes Rechteck mit optionalem Rahmen und abgesetzter Kante.

    ``edge`` färbt die untere (oder obere) Rahmenkante anders ein – so wie der
    »Elevation Border« von WinUI-Schaltflächen.
    """
    ss = SUPERSAMPLE
    w, h = max(1, width) * ss, max(1, height) * ss
    r = max(0.0, min(radius, width / 2, height / 2)) * ss
    base_color = stroke or fill
    img = Image.new("RGBA", (w, h), _rgba(base_color, 0))
    draw = ImageDraw.Draw(img)
    sw = stroke_width * ss if stroke else 0
    if stroke:
        ew = (edge_width if edge_width is not None else stroke_width) * ss
        if edge:
            draw.rounded_rectangle((0, 0, w - 1, h - 1), radius=r, fill=_rgba(edge))
            if edge_side == "bottom":
                draw.rounded_rectangle((0, 0, w - 1, h - 1 - ew), radius=r, fill=_rgba(stroke))
            else:
                draw.rounded_rectangle((0, ew, w - 1, h - 1), radius=r, fill=_rgba(stroke))
        else:
            draw.rounded_rectangle((0, 0, w - 1, h - 1), radius=r, fill=_rgba(stroke))
        if fill:
            inner = max(0.0, r - sw)
            box = (sw, sw, w - 1 - sw, h - 1 - sw)
            if edge and edge_side == "bottom":
                box = (sw, sw, w - 1 - sw, h - 1 - max(sw, ew))
            elif edge:
                box = (sw, max(sw, ew), w - 1 - sw, h - 1 - sw)
            if box[2] > box[0] and box[3] > box[1]:
                draw.rounded_rectangle(box, radius=inner, fill=_rgba(fill))
        else:
            inner = max(0.0, r - sw)
            box = (sw, sw, w - 1 - sw, h - 1 - sw)
            if box[2] > box[0] and box[3] > box[1]:
                draw.rounded_rectangle(box, radius=inner, fill=_rgba(stroke, 0))
    elif fill:
        draw.rounded_rectangle((0, 0, w - 1, h - 1), radius=r, fill=_rgba(fill))
    return _finish(img, width, height, background, alpha)


def focus_ring(width: int, height: int, radius: float, outer: str, inner: str, thickness: float = 2, background: str | None = None) -> Image.Image:
    """Fokusrahmen nach WinUI: außen 2 px kontrastreich, innen 1 px gegenfarbig."""
    ss = SUPERSAMPLE
    w, h = max(1, width) * ss, max(1, height) * ss
    r = max(0.0, radius) * ss
    t = thickness * ss
    img = Image.new("RGBA", (w, h), _rgba(outer, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle((0, 0, w - 1, h - 1), radius=r, fill=_rgba(outer))
    draw.rounded_rectangle((t, t, w - 1 - t, h - 1 - t), radius=max(0.0, r - t), fill=_rgba(inner))
    t2 = t + ss
    draw.rounded_rectangle((t2, t2, w - 1 - t2, h - 1 - t2), radius=max(0.0, r - t2), fill=_rgba(inner, 0))
    return _finish(img, width, height, background)


def circle(diameter: int, fill: str | None, stroke: str | None = None, stroke_width: float = 1, background: str | None = None) -> Image.Image:
    return rounded_box(diameter, diameter, diameter / 2, fill, stroke, stroke_width=stroke_width, background=background)


def ring_arc(diameter: int, thickness: float, start: float, extent: float, color: str, track: str | None = None, background: str | None = None) -> Image.Image:
    """Bogen mit runden Enden für den Fortschrittsring (Winkel in Grad, 0 = oben, im Uhrzeigersinn)."""
    ss = SUPERSAMPLE
    size = max(1, diameter) * ss
    t = thickness * ss
    img = Image.new("RGBA", (size, size), _rgba(color, 0))
    draw = ImageDraw.Draw(img)
    box = (t / 2, t / 2, size - 1 - t / 2, size - 1 - t / 2)
    if track:
        draw.ellipse(box, outline=_rgba(track), width=int(round(t)))
    if extent > 0.5:
        # Pillow misst ab 3 Uhr im Uhrzeigersinn.
        a0 = start - 90
        a1 = a0 + extent
        draw.arc(box, a0, a1, fill=_rgba(color), width=int(round(t)))
        radius = (size - t) / 2
        cx = cy = size / 2
        for angle in (a0, a1):
            rad = math.radians(angle)
            x = cx + radius * math.cos(rad)
            y = cy + radius * math.sin(rad)
            draw.ellipse((x - t / 2, y - t / 2, x + t / 2, y + t / 2), fill=_rgba(color))
    return _finish(img, diameter, diameter, background)


def corner(radius: int, which: str, outside: str, fill: str, stroke: str | None) -> Image.Image:
    """Ein einzelnes Eckstück (r × r) für Rahmen mit runden Ecken.

    ``which``: "nw", "ne", "sw" oder "se". Außen liegt die Farbe der Unterlage.
    """
    size = max(1, radius)
    big = rounded_box(size * 2, size * 2, size, fill, stroke, background=outside)
    boxes = {
        "nw": (0, 0, size, size),
        "ne": (size, 0, size * 2, size),
        "sw": (0, size, size, size * 2),
        "se": (size, size, size * 2, size * 2),
    }
    return big.crop(boxes[which])


def _slices(img: Image.Image, cap: int) -> tuple[Image.Image, Image.Image, list[tuple[int, int, str]]]:
    """Zerlegt ein Bild in linkes/rechtes Eckstück und farbige Zeilenstreifen der Mitte."""
    width, height = img.size
    left = img.crop((0, 0, cap, height))
    right = img.crop((width - cap, 0, width, height))
    column = img.crop((cap, 0, cap + 1, height)).convert("RGBA")
    runs: list[list] = []
    for y in range(height):
        red, green, blue, alpha = column.getpixel((0, y))
        color = f"#{red:02X}{green:02X}{blue:02X}" if alpha >= 128 else None
        if runs and runs[-1][2] == color and runs[-1][1] == y:
            runs[-1][1] = y + 1
        else:
            runs.append([y, y + 1, color])
    return left, right, [(y0, y1, color) for y0, y1, color in runs if color is not None]


def slice_cap(radius: float) -> int:
    """Breite eines Eckstücks: Radius plus Kantenglättung und Rahmen."""
    return int(math.ceil(radius)) + 2


def box_slices(height: int, radius: float, fill: str | None, stroke: str | None = None, edge: str | None = None, edge_side: str = "bottom", stroke_width: float = 1, background: str | None = None, edge_width: float | None = None):
    cap = slice_cap(radius)
    img = rounded_box(2 * cap + 1, height, radius, fill, stroke, edge, edge_side, stroke_width, background, edge_width)
    return _slices(img, cap)


def ring_slices(height: int, radius: float, outer: str, inner: str, thickness: float = 2, background: str | None = None):
    cap = slice_cap(radius)
    img = focus_ring(2 * cap + 1, height, radius, outer, inner, thickness, background)
    return _slices(img, cap)


def to_photo(master: tk.Misc, img: Image.Image) -> tk.PhotoImage:
    buffer = io.BytesIO()
    img.save(buffer, format="PNG", compress_level=1)
    return tk.PhotoImage(master=master, data=base64.b64encode(buffer.getvalue()))


class ImageCache:
    """LRU-Cache für PhotoImages.

    Widgets halten selbst Referenzen auf ihre angezeigten Bilder. Verdrängt
    der Cache ein Bild, bleibt es deshalb sichtbar, solange es verwendet wird.
    """

    def __init__(self, master: tk.Misc, limit: int = 900) -> None:
        self.master = master
        self.limit = limit
        self._items: OrderedDict = OrderedDict()

    def get(self, key: tuple, factory: Callable[[], Image.Image]) -> tk.PhotoImage:
        found = self._items.get(key)
        if found is not None:
            self._items.move_to_end(key)
            return found
        photo = to_photo(self.master, factory())
        self._items[key] = photo
        if len(self._items) > self.limit:
            self._items.popitem(last=False)
        return photo

    def slices(self, key: tuple, factory: Callable[[], tuple]) -> tuple:
        """(linkes Eckbild, rechtes Eckbild, Streifen, Eckbreite) – einmal gerendert, beliebig breit."""
        found = self._items.get(key)
        if found is not None:
            self._items.move_to_end(key)
            return found
        left, right, runs = factory()
        value = (to_photo(self.master, left), to_photo(self.master, right), tuple(runs), left.size[0])
        self._items[key] = value
        if len(self._items) > self.limit:
            self._items.popitem(last=False)
        return value

    def box_slices(self, height, radius, fill, stroke=None, edge=None, edge_side="bottom", background=None, stroke_width=1, edge_width=None) -> tuple:
        key = ("box-slices", height, radius, fill, stroke, edge, edge_side, background, stroke_width, edge_width)
        return self.slices(key, lambda: box_slices(height, radius, fill, stroke, edge, edge_side, stroke_width, background, edge_width))

    def ring_slices(self, height, radius, outer, inner, background=None, thickness=2) -> tuple:
        key = ("ring-slices", height, radius, outer, inner, background, thickness)
        return self.slices(key, lambda: ring_slices(height, radius, outer, inner, thickness, background))

    def box(self, width, height, radius, fill, stroke=None, edge=None, edge_side="bottom", background=None, stroke_width=1, edge_width=None, alpha=1.0) -> tk.PhotoImage:
        key = ("box", width, height, radius, fill, stroke, edge, edge_side, background, stroke_width, edge_width, alpha)
        return self.get(key, lambda: rounded_box(width, height, radius, fill, stroke, edge, edge_side, stroke_width, background, edge_width, alpha))

    def ring(self, width, height, radius, outer, inner, background=None, thickness=2) -> tk.PhotoImage:
        key = ("focus", width, height, radius, outer, inner, background, thickness)
        return self.get(key, lambda: focus_ring(width, height, radius, outer, inner, thickness, background))

    def circle(self, diameter, fill, stroke=None, background=None, stroke_width=1) -> tk.PhotoImage:
        key = ("circle", diameter, fill, stroke, background, stroke_width)
        return self.get(key, lambda: circle(diameter, fill, stroke, stroke_width, background))

    def corner(self, radius, which, outside, fill, stroke) -> tk.PhotoImage:
        key = ("corner", radius, which, outside, fill, stroke)
        return self.get(key, lambda: corner(radius, which, outside, fill, stroke))

    def arc(self, diameter, thickness, start, extent, color, background=None, track=None) -> tk.PhotoImage:
        key = ("arc", diameter, thickness, round(start, 1), round(extent, 1), color, background, track)
        return self.get(key, lambda: ring_arc(diameter, thickness, start, extent, color, track, background))
