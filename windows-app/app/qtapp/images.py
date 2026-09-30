"""Bilder für QML: Symbole (eingefärbt), Mica-Material und Vorschau-Seiten.

* ``image://icons/<name>/<RRGGBB>`` – Fluent-Symbol (SVG) in der gewünschten Farbe und Größe
* ``image://mica/<generation>/<light|dark>/<Breite>x<Höhe>`` – Mica aus dem Desktophintergrund
* ``image://preview/<token>/<seite>/<maßstab>`` – eine gerenderte Vorschauseite (aus dem Zwischenspeicher)
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QByteArray, QFile, QIODevice, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtQuick import QQuickImageProvider
from PySide6.QtSvg import QSvgRenderer

ICON_DIR = Path(__file__).resolve().parent.parent / "qml" / "icons"
ICON_RESOURCE = ":/qml/icons"  # im Setup: eingebaute Ressource (qml_rc)


def read_icon(name: str, folder: Path = ICON_DIR) -> bytes:
    """SVG eines Symbols – aus der eingebauten Ressource, sonst aus dem Ordner ``qml/icons``."""
    resource = QFile(f"{ICON_RESOURCE}/{name}.svg")
    if resource.exists() and resource.open(QIODevice.OpenModeFlag.ReadOnly):
        try:
            return bytes(resource.readAll().data())
        finally:
            resource.close()
    try:
        return (folder / f"{name}.svg").read_bytes()
    except OSError:
        return b""


def pil_to_qimage(image) -> QImage:
    """PIL-Bild (RGB/RGBA) → eigenständiges QImage (auch in Hintergrund-Threads erlaubt)."""
    if image.mode not in ("RGB", "RGBA"):
        image = image.convert("RGB")
    data = image.tobytes()
    if image.mode == "RGBA":
        qimage = QImage(data, image.width, image.height, image.width * 4, QImage.Format.Format_RGBA8888)
    else:
        qimage = QImage(data, image.width, image.height, image.width * 3, QImage.Format.Format_RGB888)
    return qimage.copy()  # löst das Bild von ``data``


class IconProvider(QQuickImageProvider):
    """Fluent System Icons (MIT) als SVG, eingefärbt und scharf in jeder Skalierung."""

    def __init__(self, folder: Path = ICON_DIR) -> None:
        super().__init__(QQuickImageProvider.ImageType.Image)
        self.folder = folder
        self._svg: dict[str, bytes] = {}
        self._cache: dict[tuple[str, str, int, int], QImage] = {}
        self._lock = threading.Lock()

    def requestImage(self, ident: str, size: QSize, requested: QSize) -> QImage:  # noqa: N802 - Qt-Schnittstelle
        name, _, color = ident.partition("/")
        color = (color or "000000").lstrip("#")[-6:]
        width = requested.width() if requested.width() > 0 else 20
        height = requested.height() if requested.height() > 0 else width
        key = (name, color, width, height)
        with self._lock:
            cached = self._cache.get(key)
            if cached is None:
                cached = self._render(name, color, width, height)
                if len(self._cache) > 600:
                    self._cache.clear()
                self._cache[key] = cached
        size.setWidth(cached.width())
        size.setHeight(cached.height())
        return cached

    def _render(self, name: str, color: str, width: int, height: int) -> QImage:
        data = self._svg.get(name)
        if data is None:
            data = self._svg[name] = read_icon(name, self.folder)
        image = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(Qt.GlobalColor.transparent)
        if data:
            colored = data.replace(b"<path ", b'<path fill="#' + color.encode("ascii", "ignore") + b'" ')
            renderer = QSvgRenderer(QByteArray(colored))
            painter = QPainter(image)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            renderer.render(painter, QRectF(0, 0, width, height))
            painter.end()
        return image


class MicaProvider(QQuickImageProvider):
    """Mica-Material: weichgezeichneter, eingefärbter Desktophintergrund (klein – QML skaliert weich)."""

    def __init__(self, source) -> None:
        super().__init__(QQuickImageProvider.ImageType.Image)
        self.source = source

    def requestImage(self, ident: str, size: QSize, requested: QSize) -> QImage:  # noqa: N802
        parts = ident.split("/")
        dark = len(parts) > 1 and parts[1] == "dark"
        try:
            width, height = (int(v) for v in parts[2].split("x"))
        except (IndexError, ValueError):
            width, height = 1920, 1080
        grid = None
        try:
            with self.source._lock:  # noqa: SLF001 - gleiche Sperre wie beim Laden
                grid = self.source._grid((0, 0, max(1, width), max(1, height)), dark)  # noqa: SLF001
        except Exception:  # noqa: BLE001 - ohne Material bleibt die einfarbige Fläche
            grid = None
        if grid is None:
            image = QImage(1, 1, QImage.Format.Format_RGB32)
            image.fill(QColor("#202020" if dark else "#F3F3F3"))
        else:
            image = pil_to_qimage(grid)
        size.setWidth(image.width())
        size.setHeight(image.height())
        return image


class AppIconProvider(QQuickImageProvider):
    """Das App-Symbol (``assets/icon.ico``) in der gewünschten Größe – für »Über«."""

    def __init__(self, path: Path) -> None:
        super().__init__(QQuickImageProvider.ImageType.Image)
        self.path = path

    def requestImage(self, ident: str, size: QSize, requested: QSize) -> QImage:  # noqa: N802
        from PySide6.QtGui import QImageReader

        wanted = requested.width() if requested.width() > 0 else 64
        best = QImage()
        reader = QImageReader(str(self.path))
        for _index in range(max(1, reader.imageCount())):
            image = reader.read()
            if image.isNull():
                break
            if best.isNull() or (best.width() < wanted and image.width() > best.width()) or (wanted <= image.width() < best.width()):
                best = image
            if not reader.jumpToNextImage():
                break
        if best.isNull():
            best = QImage(1, 1, QImage.Format.Format_ARGB32_Premultiplied)
            best.fill(Qt.GlobalColor.transparent)
        elif best.width() != wanted:
            best = best.scaled(wanted, wanted, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        size.setWidth(best.width())
        size.setHeight(best.height())
        return best


class PreviewProvider(QQuickImageProvider):
    """Gerenderte Vorschauseiten – gerendert wird im Hintergrund, hier nur ausgeliefert."""

    def __init__(self, lookup: Callable[[str], QImage | None]) -> None:
        super().__init__(QQuickImageProvider.ImageType.Image)
        self.lookup = lookup

    def requestImage(self, ident: str, size: QSize, requested: QSize) -> QImage:  # noqa: N802
        image = self.lookup(ident)
        if image is None:
            image = QImage(1, 1, QImage.Format.Format_RGB32)
            image.fill(QColor("#FFFFFF"))
        size.setWidth(image.width())
        size.setHeight(image.height())
        return image
