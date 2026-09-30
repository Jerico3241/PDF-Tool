"""Mica für den Client-Bereich.

DWM legt Mica (DWMSBT_MAINWINDOW) hinter das ganze Fenster, Tk übermalt den
Client-Bereich aber deckend. Deshalb erhält die Titelleiste echtes DWM-Mica,
während der Navigationsbereich dasselbe Material aus dem Desktophintergrund
berechnet – mit dem Rezept, das Windows für Mica verwendet:

1. stark weichgezeichneter Desktophintergrund,
2. Luminosity-Blend mit der Grundfarbe (#F3F3F3 hell, #202020 dunkel),
3. Color-Blend mit derselben Grundfarbe (50 % hell, 80 % dunkel).

Das Ergebnis ist ein sehr dezenter Farbhauch des Hintergrundbilds. Ist kein
Bild verfügbar, wird die einfarbige Grundfarbe verwendet – genau wie Windows
es bei inaktiven Fenstern tut.
"""

from __future__ import annotations

import threading
from pathlib import Path

from PIL import Image, ImageFilter

import winsys as windows

GRID_WIDTH = 96
LIGHT_TINT = (243, 243, 243)
DARK_TINT = (32, 32, 32)
LIGHT_TINT_OPACITY = 0.5
DARK_TINT_OPACITY = 0.8


def _lum(c: tuple[float, float, float]) -> float:
    return 0.3 * c[0] + 0.59 * c[1] + 0.11 * c[2]


def _clip(c: tuple[float, float, float]) -> tuple[float, float, float]:
    lum = _lum(c)
    lo, hi = min(c), max(c)
    r, g, b = c
    if lo < 0:
        r, g, b = (lum + (x - lum) * lum / (lum - lo) if lum != lo else lum for x in (r, g, b))
    if hi > 1:
        r, g, b = (lum + (x - lum) * (1 - lum) / (hi - lum) if hi != lum else lum for x in (r, g, b))
    return r, g, b


def _set_lum(c: tuple[float, float, float], lum: float) -> tuple[float, float, float]:
    d = lum - _lum(c)
    return _clip((c[0] + d, c[1] + d, c[2] + d))


def tint_pixel(pixel: tuple[int, int, int], dark: bool) -> tuple[int, int, int]:
    tint = DARK_TINT if dark else LIGHT_TINT
    opacity = DARK_TINT_OPACITY if dark else LIGHT_TINT_OPACITY
    base = tuple(x / 255 for x in pixel)
    lum = _lum(tuple(x / 255 for x in tint))
    step1 = _set_lum(base, lum)  # Luminosity-Blend: Helligkeit der Grundfarbe, Farbton des Bildes
    lum1 = _lum(step1)
    final = tuple(a + (lum1 - a) * opacity for a in step1)  # Color-Blend mit neutraler Grundfarbe
    return tuple(max(0, min(255, int(round(x * 255)))) for x in final)  # type: ignore[return-value]


class MicaSource:
    """Berechnet Mica-Ausschnitte für Bildschirmbereiche."""

    def __init__(self) -> None:
        self._wallpaper: Image.Image | None = None
        self._loaded = False
        self._grids: dict[tuple, Image.Image] = {}
        self._lock = threading.Lock()
        self.available = False
        self.generation = 0  # zählt geladene Hintergrundbilder (Schlüssel für zwischengespeicherte Ausschnitte)

    # Laden ------------------------------------------------------------------
    def load(self) -> bool:
        """Liest den Desktophintergrund (im Hintergrund-Thread aufrufen)."""
        try:
            image = self._read_wallpaper()
        except Exception:
            image = None
        with self._lock:
            self._wallpaper = image
            self._grids.clear()
            self._loaded = True
            self.available = image is not None
            self.generation += 1
        return self.available

    @staticmethod
    def _read_wallpaper() -> Image.Image | None:
        path = windows.wallpaper_path()
        if path and Path(path).is_file():
            img = Image.open(path)
            try:
                img.draft("RGB", (480, 480))
            except Exception:
                pass
            img = img.convert("RGB")
            img.thumbnail((480, 480))
            return img
        color = windows.desktop_color()
        if color:
            return Image.new("RGB", (16, 9), color)
        return None

    # Berechnen ----------------------------------------------------------------
    def _grid(self, monitor: tuple[int, int, int, int], dark: bool) -> Image.Image | None:
        wallpaper = self._wallpaper
        if wallpaper is None:
            return None
        mw = max(1, monitor[2] - monitor[0])
        mh = max(1, monitor[3] - monitor[1])
        key = (mw, mh, dark)
        found = self._grids.get(key)
        if found is not None:
            return found
        gw = GRID_WIDTH
        gh = max(1, round(GRID_WIDTH * mh / mw))
        style, tile = windows.wallpaper_style()
        if style == 2 and not tile:  # Strecken
            placed = wallpaper.resize((gw, gh), Image.BILINEAR)
        elif style == 6 and not tile:  # Anpassen: Rand in Desktopfarbe
            fill = windows.desktop_color() or "#000000"
            placed = Image.new("RGB", (gw, gh), fill)
            copy = wallpaper.copy()
            copy.thumbnail((gw, gh))
            placed.paste(copy, ((gw - copy.width) // 2, (gh - copy.height) // 2))
        else:  # Ausfüllen (Standard) und alle übrigen Varianten
            ratio = mw / mh
            w, h = wallpaper.size
            if w / h > ratio:
                cw = h * ratio
                box = ((w - cw) / 2, 0, (w + cw) / 2, h)
            else:
                ch = w / ratio
                box = (0, (h - ch) / 2, w, (h + ch) / 2)
            placed = wallpaper.resize((gw, gh), Image.BOX, box=box)
        blurred = placed.filter(ImageFilter.GaussianBlur(radius=4))
        tinted = Image.new("RGB", blurred.size)
        tinted.putdata([tint_pixel(p, dark) for p in blurred.getdata()])
        self._grids[key] = tinted
        return tinted

    def region(
        self,
        screen_box: tuple[int, int, int, int],
        size: tuple[int, int],
        monitor: tuple[int, int, int, int],
        dark: bool,
    ) -> Image.Image | None:
        """Mica für den Bildschirmbereich ``screen_box`` (x0, y0, x1, y1) in Pixelgröße ``size``."""
        with self._lock:
            grid = self._grid(monitor, dark)
        if grid is None:
            return None
        mx, my = monitor[0], monitor[1]
        mw = max(1, monitor[2] - monitor[0])
        mh = max(1, monitor[3] - monitor[1])
        gx = grid.width / mw
        gy = grid.height / mh
        x0, y0, x1, y1 = screen_box
        def clamp(value: float, limit: int) -> float:
            return max(0.0, min(float(limit), value))

        extent = (
            clamp((x0 - mx) * gx, grid.width - 1),
            clamp((y0 - my) * gy, grid.height - 1),
            clamp((x1 - mx) * gx, grid.width),
            clamp((y1 - my) * gy, grid.height),
        )
        width, height = max(1, size[0]), max(1, size[1])
        return grid.transform((width, height), Image.EXTENT, extent, Image.BILINEAR)
