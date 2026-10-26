"""Der Zeichenbereich eines Textes (QML: ``TextCanvas``): Seiten auf grauem Grund, Kacheln aus dem Textkern,
Schreibmarke, Auswahl und ausgewähltes Bild – dazu Maus, Mausrad, Tastatur und Eingabemethode.

Lagen: Der Kern rechnet in Twips (1/1440 Zoll); bei 100 % sind 15 Twips ein Pixel. Alle Seiten stehen untereinander
in einer Fläche (``docWidth`` × ``docHeight``), schmaler als das Fenster wird sie mittig gezeigt. Gezeichnet wird in
Kacheln zu 512 Pixeln, die der Kern auf Anfrage liefert (scharf auch bei 125 % und 150 % Anzeigeskalierung); bis eine
neue Kachel da ist, bleibt die alte stehen (auch aus dem vorigen Zoom, vergrößert) – nichts blinkt beim Tippen.
"""

from __future__ import annotations

import time

from PySide6.QtCore import Property, QObject, QPointF, QRect, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QCursor, QImage, QPainter, QPainterPath
from PySide6.QtQuick import QQuickItem, QQuickPaintedItem

from .document import MOD_ALT, MOD_CTRL, MOD_SHIFT

TWIPS_PER_PX = 15.0  # 96 dpi
TILE_PX = 512
MAX_PENDING = 6  # Kacheln gleichzeitig beim Kern
GAP_BOTTOM = 24  # Abstand unter der letzten Seite (Pixel)
BLINK_MS = 530
DOUBLE_CLICK_MS = 450
HANDLE = 8  # Anfasser eines Bildes (Pixel)
AUTOSCROLL_MS = 40

# Tasten von LibreOffice (com.sun.star.awt.Key)
_KEYS = {
    Qt.Key.Key_Down: 1024, Qt.Key.Key_Up: 1025, Qt.Key.Key_Left: 1026, Qt.Key.Key_Right: 1027,
    Qt.Key.Key_Home: 1028, Qt.Key.Key_End: 1029, Qt.Key.Key_PageUp: 1030, Qt.Key.Key_PageDown: 1031,
    Qt.Key.Key_Return: 1280, Qt.Key.Key_Enter: 1280, Qt.Key.Key_Escape: 1281, Qt.Key.Key_Tab: 1282,
    Qt.Key.Key_Backtab: 1282, Qt.Key.Key_Backspace: 1283, Qt.Key.Key_Space: 1284, Qt.Key.Key_Insert: 1285,
    Qt.Key.Key_Delete: 1286,
}
_CHARS = {1280: 13, 1282: 9, 1283: 8, 1281: 27, 1284: 32}
# Strg+Taste, die Novadesk selbst hat (Speichern, Drucken, Suchen, Tabs …): nicht an den Kern
_APP_KEYS = {Qt.Key.Key_S, Qt.Key.Key_P, Qt.Key.Key_F, Qt.Key.Key_N, Qt.Key.Key_O, Qt.Key.Key_W, Qt.Key.Key_Q,
             Qt.Key.Key_G, Qt.Key.Key_H, Qt.Key.Key_T, Qt.Key.Key_K, Qt.Key.Key_D, Qt.Key.Key_Plus, Qt.Key.Key_Minus,
             Qt.Key.Key_Equal, Qt.Key.Key_0, Qt.Key.Key_1, Qt.Key.Key_2, Qt.Key.Key_3, Qt.Key.Key_4, Qt.Key.Key_5,
             Qt.Key.Key_6, Qt.Key.Key_F1, Qt.Key.Key_Return, Qt.Key.Key_Enter}


def awt_key(key: int) -> int:
    """Taste von Qt → Tastencode von LibreOffice (0 = keine)."""
    if key in _KEYS:
        return _KEYS[key]
    if Qt.Key.Key_A <= key <= Qt.Key.Key_Z:
        return 512 + (key - Qt.Key.Key_A)
    if Qt.Key.Key_0 <= key <= Qt.Key.Key_9:
        return 256 + (key - Qt.Key.Key_0)
    if Qt.Key.Key_F1 <= key <= Qt.Key.Key_F24:
        return 768 + (key - Qt.Key.Key_F1)
    return 0


def awt_modifiers(modifiers) -> int:
    value = 0
    if modifiers & Qt.KeyboardModifier.ShiftModifier:
        value |= MOD_SHIFT
    if modifiers & Qt.KeyboardModifier.ControlModifier:
        value |= MOD_CTRL
    if modifiers & Qt.KeyboardModifier.AltModifier:
        value |= MOD_ALT
    return value


class TextCanvas(QQuickPaintedItem):
    controllerChanged = Signal()
    scrollChanged = Signal()
    extentChanged = Signal()
    colorsChanged = Signal()
    contextMenuRequested = Signal(float, float)

    def __init__(self, parent: QQuickItem | None = None) -> None:
        super().__init__(parent)
        self._controller = None
        self._scroll_x = 0.0
        self._scroll_y = 0.0
        self._colors = {"background": QColor("#E9E9E9"), "paper": QColor("#FFFFFF"), "caret": QColor("#000000"),
                        "selection": QColor(0, 120, 212, 70), "accent": QColor("#0F6CBD")}
        self._tiles: dict[tuple[int, int], QImage] = {}
        self._dirty: set[tuple[int, int]] = set()
        self._pending: set[tuple[int, int]] = set()
        self._versions: dict[tuple[int, int], int] = {}
        self._grid: tuple = ()  # (Zoom, Pixelverhältnis): zu dem gehören die Kacheln
        self._old: tuple | None = None  # (Kachelbreite in Twips, Kacheln) des vorigen Zooms – bis die neuen da sind
        self._blink_on = True
        self._pixel_ratio = 1.0
        self._blink = QTimer(self)
        self._blink.setInterval(BLINK_MS)
        self._blink.timeout.connect(self._toggle_blink)
        self._area_timer = QTimer(self)
        self._area_timer.setSingleShot(True)
        self._area_timer.setInterval(150)
        self._area_timer.timeout.connect(self._send_area)
        self._autoscroll = QTimer(self)
        self._autoscroll.setInterval(AUTOSCROLL_MS)
        self._autoscroll.timeout.connect(self._autoscroll_step)
        self._clicks = (0.0, QPointF(), 0)  # Zeit, Ort, Anzahl des letzten Klicks
        self._pressed = 0  # gedrückte Tasten der Maus (LibreOffice)
        self._drag: dict | None = None  # Bild ziehen
        self._last_mouse = QPointF()
        self._cursor_shape = Qt.CursorShape.ArrowCursor
        self.setAcceptedMouseButtons(Qt.MouseButton.LeftButton | Qt.MouseButton.RightButton | Qt.MouseButton.MiddleButton)
        self.setAcceptHoverEvents(True)
        self.setFlag(QQuickItem.Flag.ItemAcceptsInputMethod, True)
        self.setActiveFocusOnTab(True)
        self.setOpaquePainting(True)
        self.setAntialiasing(False)
        self.widthChanged.connect(self._geometry_changed)
        self.heightChanged.connect(self._geometry_changed)

    # Eigenschaften ---------------------------------------------------------------------------------------------------
    def _get_controller(self):
        return self._controller

    def _set_controller(self, controller) -> None:
        if controller is self._controller:
            return
        old = self._controller
        if old is not None:
            old._view_scroll = (self._scroll_x, self._scroll_y)  # noqa: SLF001 - Lage je Tab merken
            for signal, slot in self._connections(old):
                try:
                    signal.disconnect(slot)
                except (RuntimeError, TypeError):
                    pass
        self._controller = controller
        self._reset_tiles()
        self._old = None
        self._drag = None
        self._pressed = 0
        if controller is not None:
            for signal, slot in self._connections(controller):
                signal.connect(slot)
            self._scroll_x, self._scroll_y = getattr(controller, "_view_scroll", (0.0, 0.0))
        else:
            self._scroll_x = self._scroll_y = 0.0
        self.controllerChanged.emit()
        self._extent_changed()

    def _connections(self, controller) -> list:
        return [
            (controller.tilesInvalidated, self._invalidate),
            (controller.zoomChanged, self._zoom_changed),
            (controller.docWidthChanged, self._extent_changed),
            (controller.docHeightChanged, self._extent_changed),
            (controller.pagesChanged, self.update),
            (controller.cursorChanged, self._cursor_changed),
            (controller.cursorVisibleChanged, self.update),
            (controller.selectionChanged, self.update),
            (controller.graphicChanged, self.update),
            (controller.caretMoved, self.ensureCaretVisible),
            (controller.readyChanged, self._extent_changed),
        ]

    controller = Property(QObject, _get_controller, _set_controller, notify=controllerChanged)

    def _get_scroll_x(self) -> float:
        return self._scroll_x

    def _set_scroll_x(self, value: float) -> None:
        value = max(0.0, min(float(value), self._max_scroll_x()))
        if abs(value - self._scroll_x) >= 0.01:
            self._scroll_x = value
            self._scrolled()

    def _get_scroll_y(self) -> float:
        return self._scroll_y

    def _set_scroll_y(self, value: float) -> None:
        value = max(0.0, min(float(value), self._max_scroll_y()))
        if abs(value - self._scroll_y) >= 0.01:
            self._scroll_y = value
            self._scrolled()

    scrollX = Property(float, _get_scroll_x, _set_scroll_x, notify=scrollChanged)
    scrollY = Property(float, _get_scroll_y, _set_scroll_y, notify=scrollChanged)

    def _get_content_width(self) -> float:
        return self._doc_px()[0]

    def _get_content_height(self) -> float:
        return self._doc_px()[1] + GAP_BOTTOM

    def _get_view_width(self) -> float:
        return max(1.0, self.width())

    def _get_view_height(self) -> float:
        return max(1.0, self.height())

    contentWidth = Property(float, _get_content_width, notify=extentChanged)
    contentHeight = Property(float, _get_content_height, notify=extentChanged)
    viewWidth = Property(float, _get_view_width, notify=extentChanged)
    viewHeight = Property(float, _get_view_height, notify=extentChanged)

    def _color_property(key: str, notify):  # noqa: N805 - Hilfsfunktion beim Anlegen der Klasse
        def getter(self) -> QColor:
            return self._colors[key]

        def setter(self, value) -> None:
            color = QColor(value)
            if color != self._colors[key]:
                self._colors[key] = color
                self.colorsChanged.emit()
                self.update()

        return Property(QColor, getter, setter, notify=notify)

    backgroundColor = _color_property("background", colorsChanged)
    paperColor = _color_property("paper", colorsChanged)
    caretColor = _color_property("caret", colorsChanged)
    selectionColor = _color_property("selection", colorsChanged)
    accentColor = _color_property("accent", colorsChanged)
    del _color_property

    # Pixelverhältnis des Bildschirms (aus QML: ``Screen.devicePixelRatio``). Nie über ``self.window()``: PySide hängt
    # das Fenster dann an diesen Bereich – endet er (Text geschlossen), löscht es das ganze Fenster mit.
    pixelRatioChanged = Signal()

    def _get_pixel_ratio(self) -> float:
        return self._pixel_ratio

    def _set_pixel_ratio(self, value: float) -> None:
        value = float(value) if value and value > 0 else 1.0
        if value != self._pixel_ratio:
            self._pixel_ratio = value
            self.pixelRatioChanged.emit()
            self.update()

    pixelRatio = Property(float, _get_pixel_ratio, _set_pixel_ratio, notify=pixelRatioChanged)

    # Lagen -----------------------------------------------------------------------------------------------------------
    def _scale(self) -> float:
        """Pixel je Twip."""
        zoom = self._controller.zoom if self._controller is not None else 100
        return zoom / 100.0 / TWIPS_PER_PX

    def _doc_px(self) -> tuple[float, float]:
        if self._controller is None:
            return 0.0, 0.0
        scale = self._scale()
        return self._controller.docWidth * scale, self._controller.docHeight * scale

    def _offset_x(self) -> float:
        width = self._doc_px()[0]
        return max(0.0, (self.width() - width) / 2) if width < self.width() else 0.0

    def _max_scroll_x(self) -> float:
        return max(0.0, self._doc_px()[0] - self.width())

    def _max_scroll_y(self) -> float:
        return max(0.0, self._doc_px()[1] + GAP_BOTTOM - self.height())

    def to_view(self, x: float, y: float) -> QPointF:
        scale = self._scale()
        return QPointF(self._offset_x() + x * scale - self._scroll_x, y * scale - self._scroll_y)

    def to_doc(self, point: QPointF) -> tuple[int, int]:
        scale = self._scale()
        return (int(round((point.x() - self._offset_x() + self._scroll_x) / scale)),
                int(round((point.y() + self._scroll_y) / scale)))

    def _view_rect(self, rect: list[int]) -> QRectF:
        scale = self._scale()
        top_left = self.to_view(rect[0], rect[1])
        return QRectF(top_left.x(), top_left.y(), rect[2] * scale, rect[3] * scale)

    def _dpr(self) -> float:
        return self._pixel_ratio

    def _tile_twips(self) -> int:
        return max(1, int(round(TILE_PX / self._scale())))

    # Kacheln -----------------------------------------------------------------------------------------------------------
    def _reset_tiles(self) -> None:
        self._tiles = {}
        self._dirty = set()
        self._pending = set()
        self._versions = {}
        self._grid = ()

    def _invalidate(self, x: int, y: int, w: int, h: int) -> None:
        if w <= 0 or h <= 0:
            keys = set(self._tiles)
        else:
            size = self._tile_twips()
            keys = {(i, j) for i in range(max(0, x // size), (x + w) // size + 1) for j in range(max(0, y // size), (y + h) // size + 1)}
        for key in keys:
            self._versions[key] = self._versions.get(key, 0) + 1
            if key in self._tiles:
                self._dirty.add(key)
        self._old = None if w <= 0 else self._old
        self.update()
        QTimer.singleShot(0, self._request_visible)

    def _zoom_changed(self) -> None:
        if self._tiles and self._grid:
            self._old = (self._grid[2], dict(self._tiles))
        self._reset_tiles()
        self._extent_changed()
        self._area_timer.start()

    def _visible_tiles(self) -> list[tuple[int, int]]:
        if self._controller is None or not self._controller.ready:
            return []
        size = self._tile_twips()
        left, top = self.to_doc(QPointF(0, 0))
        right, bottom = self.to_doc(QPointF(self.width(), self.height()))
        margin = size // 2  # etwas darüber und darunter vorab
        doc_w, doc_h = self._controller.docWidth, self._controller.docHeight
        left, right = max(0, left), min(doc_w, right)
        top, bottom = max(0, top - margin), min(doc_h, bottom + margin)
        pages = self._controller.pages
        keys = []
        for j in range(top // size, bottom // size + 1):
            for i in range(left // size, right // size + 1):
                rect = (i * size, j * size, size, size)
                if pages and not any(_intersects(rect, page) for page in pages):
                    continue  # nur Abstand zwischen den Seiten
                keys.append((i, j))
        # zuerst, was zu sehen ist (von oben nach unten), dann der Vorrat
        center_top, center_bottom = max(0, top + margin), bottom - margin
        keys.sort(key=lambda k: (0 if center_top <= k[1] * size + size and k[1] * size <= center_bottom else 1, k[1], k[0]))
        return keys

    def _request_visible(self) -> None:
        controller = self._controller
        if controller is None or not controller.ready:
            return
        dpr = self._dpr()
        grid = (controller.zoom, round(dpr, 3), self._tile_twips())
        if grid != self._grid:
            if self._grid and self._tiles:
                self._old = (self._grid[2], dict(self._tiles))
            self._reset_tiles()
            self._grid = grid
            controller.set_client_zoom(int(round(TILE_PX * dpr)), self._tile_twips())
        size = self._tile_twips()
        pixels = max(1, int(round(TILE_PX * dpr)))
        for key in self._visible_tiles():
            if len(self._pending) >= MAX_PENDING:
                break
            if key in self._pending or (key in self._tiles and key not in self._dirty):
                continue
            self._pending.add(key)
            version = self._versions.get(key, 0)
            args = {"pw": pixels, "ph": pixels, "x": key[0] * size, "y": key[1] * size, "w": size, "h": size}

            def done(data: bytes, key=key, version=version, grid=grid, pixels=pixels, owner=controller) -> None:
                if owner is not self._controller or grid != self._grid:
                    return
                self._pending.discard(key)
                if len(data) == pixels * pixels * 4:
                    image = QImage(data, pixels, pixels, pixels * 4, QImage.Format.Format_ARGB32_Premultiplied).copy()
                    image.setDevicePixelRatio(self._dpr())
                    self._tiles[key] = image
                    if self._versions.get(key, 0) == version:
                        self._dirty.discard(key)
                    else:
                        self._dirty.add(key)
                if not self._pending:
                    self._old = None if all(k in self._tiles for k in self._visible_tiles()) else self._old
                self.update()
                self._request_visible()

            def failed(_exc, key=key, grid=grid, owner=controller) -> None:
                if owner is self._controller and grid == self._grid:
                    self._pending.discard(key)

            controller.request_tile(args, done, failed)

    # Zeichnen ----------------------------------------------------------------------------------------------------------
    def paint(self, painter: QPainter) -> None:
        painter.fillRect(QRectF(0, 0, self.width(), self.height()), self._colors["background"])
        controller = self._controller
        if controller is None:
            return
        pages = [self._view_rect(page) for page in controller.pages] or [self._view_rect([0, 0, controller.docWidth, controller.docHeight])]
        view = QRectF(0, 0, self.width(), self.height())
        clip = QPainterPath()
        for rect in pages:
            if rect.intersects(view):
                painter.fillRect(rect, self._colors["paper"])
                clip.addRect(rect)
        painter.save()
        painter.setClipPath(clip)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        if self._old is not None:
            old_size, tiles = self._old
            for (i, j), image in tiles.items():
                target = self._tile_target(i, j, old_size)
                if target.intersects(view.toRect()):
                    painter.drawImage(target, image)
        size = self._tile_twips()
        for (i, j), image in self._tiles.items():
            target = self._tile_target(i, j, size)
            if target.intersects(view.toRect()):
                painter.drawImage(target, image)
        for rect in controller.selection:
            painter.fillRect(self._view_rect(rect), self._colors["selection"])
        painter.restore()
        if controller.graphic:
            self._paint_graphic(painter, self._view_rect(controller.graphic))
        if self.hasActiveFocus() and controller.cursorVisible and controller.cursor and self._blink_on and not controller.graphic:
            rect = self._view_rect(controller.cursor)
            width = 2.0 if controller.zoom >= 175 else 1.0
            painter.fillRect(QRectF(round(rect.x()), rect.y(), width, max(rect.height(), 8.0)), self._colors["caret"])
        QTimer.singleShot(0, self._request_visible)

    def _tile_target(self, i: int, j: int, size: int) -> QRect:
        a = self.to_view(i * size, j * size)
        b = self.to_view((i + 1) * size, (j + 1) * size)
        x0, y0, x1, y1 = round(a.x()), round(a.y()), round(b.x()), round(b.y())
        return QRect(x0, y0, max(1, x1 - x0), max(1, y1 - y0))

    def _paint_graphic(self, painter: QPainter, rect: QRectF) -> None:
        if self._drag is not None and self._drag.get("preview") is not None:
            rect = self._drag["preview"]
        accent = self._colors["accent"]
        painter.setPen(accent)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(rect.adjusted(0, 0, -1, -1))
        painter.setBrush(self._colors["paper"])
        for point in _handles(rect).values():
            painter.drawRect(QRectF(point.x() - HANDLE / 2, point.y() - HANDLE / 2, HANDLE, HANDLE))

    # Schreibmarke ----------------------------------------------------------------------------------------------------
    def _cursor_changed(self) -> None:
        self._blink_on = True
        if self.hasActiveFocus():
            self._blink.start()
        self.update()

    def _toggle_blink(self) -> None:
        self._blink_on = not self._blink_on
        if self._controller is not None and self._controller.cursor:
            rect = self._view_rect(self._controller.cursor)
            self.update(QRect(int(rect.x()) - 2, int(rect.y()) - 2, 6, int(rect.height()) + 4))

    def focusInEvent(self, event) -> None:  # noqa: N802
        super().focusInEvent(event)
        self._blink_on = True
        self._blink.start()
        self.update()

    def focusOutEvent(self, event) -> None:  # noqa: N802
        super().focusOutEvent(event)
        self._blink.stop()
        self.update()

    def ensureCaretVisible(self) -> None:  # noqa: N802
        if self._controller is None or not self._controller.cursor:
            return
        rect = self._view_rect(self._controller.cursor)
        margin = 40.0
        if rect.top() < margin:
            self.scrollY = self._scroll_y + rect.top() - margin
        elif rect.bottom() > self.height() - margin:
            self.scrollY = self._scroll_y + rect.bottom() - self.height() + margin
        if rect.left() < margin:
            self.scrollX = self._scroll_x + rect.left() - margin
        elif rect.right() > self.width() - margin:
            self.scrollX = self._scroll_x + rect.right() - self.width() + margin

    # Bildlauf ------------------------------------------------------------------------------------------------------------
    def _extent_changed(self) -> None:
        self._scroll_x = max(0.0, min(self._scroll_x, self._max_scroll_x()))
        self._scroll_y = max(0.0, min(self._scroll_y, self._max_scroll_y()))
        self.extentChanged.emit()
        self.scrollChanged.emit()
        self.update()
        self._area_timer.start()

    def _geometry_changed(self) -> None:
        self._extent_changed()

    def _scrolled(self) -> None:
        self.scrollChanged.emit()
        self.update()
        self._area_timer.start()

    def scrollBy(self, dx: float, dy: float) -> None:  # noqa: N802
        if dx:
            self.scrollX = self._scroll_x + dx
        if dy:
            self.scrollY = self._scroll_y + dy

    def _send_area(self) -> None:
        if self._controller is None or not self._controller.ready:
            return
        left, top = self.to_doc(QPointF(0, 0))
        right, bottom = self.to_doc(QPointF(self.width(), self.height()))
        self._controller.set_visible_area(max(0, left), max(0, top), max(1, right - max(0, left)), max(1, bottom - max(0, top)))

    def wheelEvent(self, event) -> None:  # noqa: N802
        controller = self._controller
        if controller is None:
            event.ignore()
            return
        delta = event.angleDelta()
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            if delta.y():
                controller.zoomStep(1 if delta.y() > 0 else -1)
            event.accept()
            return
        pixel = event.pixelDelta()
        if not pixel.isNull():
            dx, dy = -pixel.x(), -pixel.y()
        else:
            dx, dy = -delta.x() / 120 * 48, -delta.y() / 120 * 48 * 1.5
        if event.modifiers() & Qt.KeyboardModifier.ShiftModifier and not dx:
            dx, dy = dy, 0
        self.scrollBy(dx, dy)
        event.accept()

    # Maus --------------------------------------------------------------------------------------------------------------
    def _on_page(self, point: QPointF) -> bool:
        if self._controller is None:
            return False
        x, y = self.to_doc(point)
        return any(page[0] <= x <= page[0] + page[2] and page[1] <= y <= page[1] + page[3] for page in self._controller.pages)

    def _graphic_hit(self, point: QPointF) -> str:
        """Über dem ausgewählten Bild: Anfasser (»n«, »se« …), »move« oder ""."""
        if self._controller is None or not self._controller.graphic:
            return ""
        rect = self._view_rect(self._controller.graphic)
        for name, handle in _handles(rect).items():
            if abs(point.x() - handle.x()) <= HANDLE and abs(point.y() - handle.y()) <= HANDLE:
                return name
        return "move" if rect.contains(point) else ""

    def mousePressEvent(self, event) -> None:  # noqa: N802
        controller = self._controller
        if controller is None or not controller.ready:
            event.ignore()
            return
        self.forceActiveFocus(Qt.FocusReason.MouseFocusReason)
        point = event.position()
        self._last_mouse = point
        button = {Qt.MouseButton.LeftButton: 1, Qt.MouseButton.MiddleButton: 2, Qt.MouseButton.RightButton: 4}.get(event.button(), 1)
        mods = awt_modifiers(event.modifiers())
        if button == 1:
            hit = self._graphic_hit(point)
            if hit:
                # ausgewähltes Bild: verschieben oder an einem Anfasser die Größe ändern (beim Loslassen)
                rect = self._view_rect(controller.graphic)
                start = _handles(rect).get(hit, point) if hit != "move" else point
                self._drag = {"hit": hit, "start": QPointF(start), "rect": rect, "preview": None}
                controller.graphic_drag(0, *self.to_doc(start))
                event.accept()
                return
        stamp, place, count = self._clicks
        now = time.monotonic()
        near = abs(point.x() - place.x()) <= 4 and abs(point.y() - place.y()) <= 4
        count = count % 3 + 1 if (now - stamp) * 1000 <= DOUBLE_CLICK_MS and near else 1
        self._clicks = (now, QPointF(point), count)
        x, y = self.to_doc(point)
        self._pressed = button
        controller.mouse(0, x, y, count, button, mods)
        if button == 4:
            controller.mouse(1, x, y, 1, button, mods)
            self._pressed = 0
            self.contextMenuRequested.emit(point.x(), point.y())
        event.accept()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        controller = self._controller
        if controller is None:
            return
        point = event.position()
        self._last_mouse = point
        if self._drag is not None:
            self._drag["preview"] = _dragged(self._drag, point)
            self.update()
            return
        if not self._pressed:
            return
        x, y = self.to_doc(point)
        controller.mouse(2, x, y, 1, self._pressed, awt_modifiers(event.modifiers()))
        if point.y() < 0 or point.y() > self.height() or point.x() < 0 or point.x() > self.width():
            if not self._autoscroll.isActive():
                self._autoscroll.start()
        else:
            self._autoscroll.stop()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        controller = self._controller
        self._autoscroll.stop()
        if controller is None:
            return
        point = event.position()
        if self._drag is not None:
            drag, self._drag = self._drag, None
            moved = abs(point.x() - drag["start"].x()) > 2 or abs(point.y() - drag["start"].y()) > 2
            end = point if moved else drag["start"]
            controller.graphic_drag(1, *self.to_doc(end))
            self.update()
            return
        if not self._pressed:
            return
        x, y = self.to_doc(point)
        button, self._pressed = self._pressed, 0
        controller.mouse(1, x, y, self._clicks[2], button, awt_modifiers(event.modifiers()))

    def _autoscroll_step(self) -> None:
        if not self._pressed or self._controller is None:
            self._autoscroll.stop()
            return
        point = self._last_mouse
        dy = point.y() - self.height() if point.y() > self.height() else point.y() if point.y() < 0 else 0
        dx = point.x() - self.width() if point.x() > self.width() else point.x() if point.x() < 0 else 0
        self.scrollBy(max(-40.0, min(40.0, dx)), max(-40.0, min(40.0, dy)))
        clamped = QPointF(max(0.0, min(self.width(), point.x())), max(0.0, min(self.height(), point.y())))
        self._controller.mouse(2, *self.to_doc(clamped), 1, self._pressed, 0)

    def hoverMoveEvent(self, event) -> None:  # noqa: N802
        point = event.position()
        hit = self._graphic_hit(point)
        shapes = {"move": Qt.CursorShape.SizeAllCursor, "n": Qt.CursorShape.SizeVerCursor, "s": Qt.CursorShape.SizeVerCursor,
                  "w": Qt.CursorShape.SizeHorCursor, "e": Qt.CursorShape.SizeHorCursor, "nw": Qt.CursorShape.SizeFDiagCursor,
                  "se": Qt.CursorShape.SizeFDiagCursor, "ne": Qt.CursorShape.SizeBDiagCursor, "sw": Qt.CursorShape.SizeBDiagCursor}
        shape = shapes.get(hit) or (Qt.CursorShape.IBeamCursor if self._on_page(point) else Qt.CursorShape.ArrowCursor)
        if shape != self._cursor_shape:
            self._cursor_shape = shape
            self.setCursor(QCursor(shape))

    # Tastatur ----------------------------------------------------------------------------------------------------------
    def keyPressEvent(self, event) -> None:  # noqa: N802
        controller = self._controller
        if controller is None or not controller.ready:
            event.ignore()
            return
        key = event.key()
        modifiers = event.modifiers()
        ctrl = bool(modifiers & Qt.KeyboardModifier.ControlModifier)
        alt = bool(modifiers & Qt.KeyboardModifier.AltModifier)
        shift = bool(modifiers & Qt.KeyboardModifier.ShiftModifier)
        text = event.text()
        if ctrl and alt and text and text.isprintable():  # AltGr (@, €, {, …)
            controller.type_text(text)
            event.accept()
            return
        if ctrl and not alt:
            if key == Qt.Key.Key_C or (key == Qt.Key.Key_Insert and not shift):
                controller.copy()
            elif key == Qt.Key.Key_X:
                controller.cut()
            elif key == Qt.Key.Key_V:
                controller.pastePlain() if shift else controller.paste()
            elif key == Qt.Key.Key_Z:
                controller.redo() if shift else controller.undo()
            elif key == Qt.Key.Key_Y:
                controller.redo()
            elif key == Qt.Key.Key_A:
                controller.selectAll()
            elif key in _APP_KEYS or key == Qt.Key.Key_Tab:
                event.ignore()  # Tastenkürzel von Novadesk
                return
            else:
                code = awt_key(key)
                if not code:
                    event.ignore()
                    return
                controller.key(ord(text.lower()) if len(text) == 1 and text.isprintable() else 0, code | awt_modifiers(modifiers))
            event.accept()
            return
        if shift and key == Qt.Key.Key_Delete:
            controller.cut()
            event.accept()
            return
        if shift and key == Qt.Key.Key_Insert:
            controller.paste()
            event.accept()
            return
        code = _KEYS.get(key, 0)
        if code and key != Qt.Key.Key_Space:
            if key == Qt.Key.Key_Escape and not controller.graphic and not controller.selection:
                event.ignore()  # Esc gehört dann Novadesk (Suchleiste, Vollbild …)
                return
            if key == Qt.Key.Key_Backtab:
                modifiers |= Qt.KeyboardModifier.ShiftModifier
            controller.key(_CHARS.get(code, 0), code | awt_modifiers(modifiers))
            event.accept()
            return
        if alt and not ctrl:
            event.ignore()  # Alt+Buchstabe: Menüs von Novadesk
            return
        if text and text.isprintable():
            controller.type_text(text)
            event.accept()
            return
        code = awt_key(key)
        if code and Qt.Key.Key_F1 <= key <= Qt.Key.Key_F24:
            event.ignore()  # F-Tasten: Novadesk (Hilfe, Vollbild …)
            return
        event.ignore()

    def inputMethodEvent(self, event) -> None:  # noqa: N802
        """Tottasten (^, ´, `) und Eingabehilfen: der fertige Text wird getippt."""
        text = event.commitString()
        if text and self._controller is not None and self._controller.ready:
            self._controller.type_text(text)
        event.accept()

    def inputMethodQuery(self, query):  # noqa: N802
        if query == Qt.InputMethodQuery.ImEnabled:
            return True
        if query == Qt.InputMethodQuery.ImCursorRectangle and self._controller is not None and self._controller.cursor:
            return self._view_rect(self._controller.cursor)
        return super().inputMethodQuery(query)


def _intersects(a, b) -> bool:
    return a[0] < b[0] + b[2] and b[0] < a[0] + a[2] and a[1] < b[1] + b[3] and b[1] < a[1] + a[3]


def _handles(rect: QRectF) -> dict[str, QPointF]:
    cx, cy = rect.center().x(), rect.center().y()
    return {"nw": rect.topLeft(), "n": QPointF(cx, rect.top()), "ne": rect.topRight(), "e": QPointF(rect.right(), cy),
            "se": rect.bottomRight(), "s": QPointF(cx, rect.bottom()), "sw": rect.bottomLeft(), "w": QPointF(rect.left(), cy)}


def _dragged(drag: dict, point: QPointF) -> QRectF:
    """Vorschau beim Ziehen eines Bildes (verschoben bzw. an einem Anfasser in der Größe geändert)."""
    rect = QRectF(drag["rect"])
    dx, dy = point.x() - drag["start"].x(), point.y() - drag["start"].y()
    hit = drag["hit"]
    if hit == "move":
        return rect.translated(dx, dy)
    if "w" in hit:
        rect.setLeft(min(rect.right() - 4, rect.left() + dx))
    if "e" in hit:
        rect.setRight(max(rect.left() + 4, rect.right() + dx))
    if "n" in hit:
        rect.setTop(min(rect.bottom() - 4, rect.top() + dy))
    if "s" in hit:
        rect.setBottom(max(rect.top() + 4, rect.bottom() + dy))
    return rect

