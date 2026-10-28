"""Das Bild einer Folie (QML: ``SlideImage``) – für die Folienleiste und das Vorführen im Vollbild.

Der Kern malt eine beliebige Folie, ohne dass die Präsentation zu ihr wechseln muss (``thumb``). Dieses Element
fragt das Bild in seiner eigenen Größe an (etwas verzögert, damit beim Tippen nicht jede Folie neu entsteht),
zeigt es bis zum nächsten Bild weiter und zeichnet es auf weißem Grund.
"""

from __future__ import annotations

from PySide6.QtCore import Property, QObject, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QImage, QPainter
from PySide6.QtQuick import QQuickItem, QQuickPaintedItem

DELAY_MS = 120
MAX_PX = 2048


class SlideImage(QQuickPaintedItem):
    controllerChanged = Signal()
    partChanged = Signal()
    revisionChanged = Signal()
    pixelRatioChanged = Signal()

    def __init__(self, parent: QQuickItem | None = None) -> None:
        super().__init__(parent)
        self._controller = None
        self._part = 0
        self._revision = 0
        self._pixel_ratio = 1.0
        self._image: QImage | None = None
        self._pending = False
        self._wanted: tuple = ()  # (Folie, Breite, Höhe) des Bildes, das gerade geholt wird bzw. da ist
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(DELAY_MS)
        self._timer.timeout.connect(self._request)
        self.setOpaquePainting(True)
        self.setAntialiasing(False)
        self.widthChanged.connect(self._timer.start)
        self.heightChanged.connect(self._timer.start)

    # Eigenschaften ------------------------------------------------------------------------------------------------
    def _get_controller(self):
        return self._controller

    def _set_controller(self, controller) -> None:
        if controller is not self._controller:
            self._controller = controller
            self._image = None
            self._wanted = ()
            self.controllerChanged.emit()
            self._timer.start()

    def _get_part(self) -> int:
        return self._part

    def _set_part(self, value: int) -> None:
        value = max(0, int(value))
        if value != self._part:
            self._part = value
            self.partChanged.emit()
            self._timer.start()

    def _get_revision(self) -> int:
        return self._revision

    def _set_revision(self, value: int) -> None:
        if int(value) != self._revision:
            self._revision = int(value)
            self.revisionChanged.emit()
            self._timer.start()

    def _get_pixel_ratio(self) -> float:
        return self._pixel_ratio

    def _set_pixel_ratio(self, value: float) -> None:
        value = float(value) if value and value > 0 else 1.0
        if value != self._pixel_ratio:
            self._pixel_ratio = value
            self.pixelRatioChanged.emit()
            self._timer.start()

    controller = Property(QObject, _get_controller, _set_controller, notify=controllerChanged)
    part = Property(int, _get_part, _set_part, notify=partChanged)
    revision = Property(int, _get_revision, _set_revision, notify=revisionChanged)
    # Nie über ``self.window()``: PySide hängt das Fenster sonst an dieses Element
    pixelRatio = Property(float, _get_pixel_ratio, _set_pixel_ratio, notify=pixelRatioChanged)

    # Bild holen ---------------------------------------------------------------------------------------------------
    def _request(self) -> None:
        controller = self._controller
        if controller is None or not getattr(controller, "ready", False) or self._pending:
            return
        width = max(1, min(MAX_PX, int(round(self.width() * self._pixel_ratio))))
        height = max(1, min(MAX_PX, int(round(self.height() * self._pixel_ratio))))
        if self.width() < 2 or self.height() < 2:
            return
        wanted = (self._part, width, height, self._revision)
        if wanted == self._wanted and self._image is not None:
            return
        self._pending = True

        def done(data: bytes, wanted=wanted, owner=controller) -> None:
            self._pending = False
            if owner is not self._controller:
                return
            if len(data) == wanted[1] * wanted[2] * 4:
                image = QImage(data, wanted[1], wanted[2], wanted[1] * 4, QImage.Format.Format_ARGB32_Premultiplied).copy()
                image.setDevicePixelRatio(self._pixel_ratio)
                self._image = image
                self._wanted = wanted
                self.update()
            self._check_again()

        def failed(_exc, owner=controller) -> None:
            self._pending = False
            if owner is self._controller:
                self._check_again()

        controller.request_thumb(self._part, width, height, done, failed)

    def _check_again(self) -> None:
        """Hat sich die Folie oder der Inhalt geändert, während das Bild unterwegs war: noch einmal."""
        if not self._wanted or self._wanted[0] != self._part or self._wanted[3] != self._revision:
            self._timer.start()

    # Zeichnen -----------------------------------------------------------------------------------------------------
    def paint(self, painter: QPainter) -> None:
        area = QRectF(0, 0, self.width(), self.height())
        painter.fillRect(area, Qt.GlobalColor.white)
        if self._image is not None and not self._image.isNull():
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
            painter.drawImage(area, self._image)
        elif not self._pending and not self._timer.isActive():
            self._timer.start()
