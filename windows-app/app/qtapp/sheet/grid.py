"""Das Tabellenraster (QML: ``SheetGrid``): zeichnet Kopfzeilen, Zellen, Gitter, Rahmen, Auswahl und Filterknöpfe
und nimmt Maus, Mausrad und Tastatur entgegen.

Lagen: Spalten und Zeilen kommen in Pixeln bei 100 % aus ``model.Layout``; ``zoom`` vergrößert alles außer den
Kopfzeilen. Fixierte Zeilen/Spalten stehen fest, der Rest verschiebt sich um ``scrollX``/``scrollY`` (Pixel im
Zoom). Das Raster lädt nichts selbst – es meldet den sichtbaren Bereich an den ``SheetController``.
"""

from __future__ import annotations

from PySide6.QtCore import Property, QObject, QPointF, QRectF, Qt, QTimer, Signal, Slot
from PySide6.QtGui import QColor, QCursor, QFont, QFontMetricsF, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtQuick import QQuickItem, QQuickPaintedItem

from tools.sheet.engine import cell_name, column_name

from .model import MM100_TO_PX

HEADER_H = 26
PADDING = 4
RESIZE_GRIP = 4
FILL_HANDLE = 7
FILTER_BUTTON = 17
OVERFLOW_LOOKBACK = 12  # links aus dem Bild ragender Text: so viele Spalten davor prüfen
AUTOSCROLL_MS = 40


class SheetGrid(QQuickPaintedItem):
    controllerChanged = Signal()
    scrollChanged = Signal()
    extentChanged = Signal()
    viewChanged = Signal()  # Lagen haben sich geändert (Editor, Diagramme neu ausrichten)
    colorsChanged = Signal()
    pointModeChanged = Signal()
    referencePicked = Signal(str, bool)  # Zellbezug im Zeigemodus; True = den zuletzt eingefügten ersetzen
    contextMenuRequested = Signal(float, float, str)  # Lage, Bereich: »cell«, »cols«, »rows«
    filterButtonClicked = Signal(int, float, float)  # Spalte, Lage unter dem Knopf
    editRequested = Signal()  # Doppelklick auf eine Zelle

    def __init__(self, parent: QQuickItem | None = None) -> None:
        super().__init__(parent)
        self._controller = None
        self._scroll_x = 0.0
        self._scroll_y = 0.0
        self._point_mode = False
        self._view_revision = 0
        self._colors = {
            "header": QColor("#F5F5F5"), "headerText": QColor("#5D5D5D"), "headerLine": QColor("#E0E0E0"),
            "line": QColor("#E1E1E1"), "paper": QColor("#FFFFFF"), "text": QColor("#1A1A1A"), "accent": QColor("#0F6CBD"),
            "selectedHeader": QColor("#E1EBF7"), "selectedHeaderText": QColor("#0F548C"),
        }
        self._fonts: dict = {}
        self._color_cache: dict[str, QColor] = {}
        self._drag: dict | None = None
        self._hover_cursor = Qt.CursorShape.ArrowCursor
        self._autoscroll = QTimer(self)
        self._autoscroll.setInterval(AUTOSCROLL_MS)
        self._autoscroll.timeout.connect(self._autoscroll_step)
        self._last_mouse = QPointF()
        self.setAcceptedMouseButtons(Qt.MouseButton.LeftButton | Qt.MouseButton.RightButton)
        self.setAcceptHoverEvents(True)
        self.setFlag(QQuickItem.Flag.ItemIsFocusScope, False)
        self.setFlag(QQuickItem.Flag.ItemAcceptsInputMethod, True)
        self.setActiveFocusOnTab(True)
        self.setAntialiasing(False)
        self.setOpaquePainting(True)
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
            for signal, slot in self._connections(old):
                try:
                    signal.disconnect(slot)
                except (RuntimeError, TypeError):
                    pass
        self._controller = controller
        if controller is not None:
            for signal, slot in self._connections(controller):
                signal.connect(slot)
        self._scroll_x = self._scroll_y = 0.0
        self._drag = None
        self.controllerChanged.emit()
        self.scrollChanged.emit()
        self._layout_changed()

    def _connections(self, controller) -> list:
        return [
            (controller.revisionChanged, self.update),
            (controller.layoutRevisionChanged, self._layout_changed),
            (controller.zoomChanged, self._zoom_changed),
            (controller.activeSheetChanged, self._sheet_changed),
            (controller.cursorMoved, self.ensureCursorVisible),
            (controller.contentChanged, self.update),
        ]

    controller = Property(QObject, _get_controller, _set_controller, notify=controllerChanged)

    def _get_scroll_x(self) -> float:
        return self._scroll_x

    def _set_scroll_x(self, value: float) -> None:
        value = max(0.0, min(float(value), self._max_scroll_x()))
        if abs(value - self._scroll_x) < 0.01:
            return
        self._scroll_x = value
        self._scrolled()

    def _get_scroll_y(self) -> float:
        return self._scroll_y

    def _set_scroll_y(self, value: float) -> None:
        value = max(0.0, min(float(value), self._max_scroll_y()))
        if abs(value - self._scroll_y) < 0.01:
            return
        self._scroll_y = value
        self._scrolled()

    scrollX = Property(float, _get_scroll_x, _set_scroll_x, notify=scrollChanged)
    scrollY = Property(float, _get_scroll_y, _set_scroll_y, notify=scrollChanged)

    def _get_content_width(self) -> float:
        return self._extent()[0]

    def _get_content_height(self) -> float:
        return self._extent()[1]

    def _get_view_width(self) -> float:
        return max(1.0, self.width() - self._header_w() - self._frozen()[2])

    def _get_view_height(self) -> float:
        return max(1.0, self.height() - HEADER_H - self._frozen()[3])

    contentWidth = Property(float, _get_content_width, notify=extentChanged)
    contentHeight = Property(float, _get_content_height, notify=extentChanged)
    viewWidth = Property(float, _get_view_width, notify=extentChanged)
    viewHeight = Property(float, _get_view_height, notify=extentChanged)

    def _get_view_revision(self) -> int:
        return self._view_revision

    viewRevision = Property(int, _get_view_revision, notify=viewChanged)

    def _get_point_mode(self) -> bool:
        return self._point_mode

    def _set_point_mode(self, value: bool) -> None:
        if bool(value) != self._point_mode:
            self._point_mode = bool(value)
            self.pointModeChanged.emit()

    pointMode = Property(bool, _get_point_mode, _set_point_mode, notify=pointModeChanged)

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

    headerColor = _color_property("header", colorsChanged)
    headerTextColor = _color_property("headerText", colorsChanged)
    headerLineColor = _color_property("headerLine", colorsChanged)
    lineColor = _color_property("line", colorsChanged)
    paperColor = _color_property("paper", colorsChanged)
    textColor = _color_property("text", colorsChanged)
    accentColor = _color_property("accent", colorsChanged)
    selectedHeaderColor = _color_property("selectedHeader", colorsChanged)
    selectedHeaderTextColor = _color_property("selectedHeaderText", colorsChanged)
    del _color_property

    # Lagen -----------------------------------------------------------------------------------------------------------
    def _layout(self):
        return self._controller.layout() if self._controller is not None else None

    def _zoom(self) -> float:
        return (self._controller.zoom if self._controller is not None else 100) / 100.0

    def _header_w(self) -> float:
        layout = self._layout()
        last = (layout.used_rows if layout else 0) + 200
        if self._controller is not None:
            last = max(last, self._controller.cursorRow + 1, self._row_at(self.height() - 1) + 1 if layout else 0)
        digits = len(str(last))
        return max(40.0, digits * 8.0 + 18.0)

    def _frozen(self) -> tuple[int, int, float, float]:
        """Fixierte Zeilen, Spalten und deren Höhe/Breite (Pixel im Zoom)."""
        layout = self._layout()
        if layout is None:
            return 0, 0, 0.0, 0.0
        rows, cols = layout.freeze
        z = self._zoom()
        return rows, cols, layout.cols.start(cols) * z, layout.rows.start(rows) * z

    def x_of(self, col: int) -> float:
        layout = self._layout()
        z = self._zoom()
        fr, fc, fw, _fh = self._frozen()
        if col < fc:
            return self._header_w() + layout.cols.start(col) * z
        return self._header_w() + fw + (layout.cols.start(col) - layout.cols.start(fc)) * z - self._scroll_x

    def y_of(self, row: int) -> float:
        layout = self._layout()
        z = self._zoom()
        fr, _fc, _fw, fh = self._frozen()
        if row < fr:
            return HEADER_H + layout.rows.start(row) * z
        return HEADER_H + fh + (layout.rows.start(row) - layout.rows.start(fr)) * z - self._scroll_y

    def _col_at(self, x: float) -> int:
        layout = self._layout()
        z = self._zoom()
        _fr, fc, fw, _fh = self._frozen()
        x -= self._header_w()
        if x < fw:
            return layout.cols.index_at(max(0.0, x) / z)
        return min(layout.max_cols - 1, layout.cols.index_at((x - fw + self._scroll_x) / z + layout.cols.start(fc)))

    def _row_at(self, y: float) -> int:
        layout = self._layout()
        z = self._zoom()
        fr, _fc, _fw, fh = self._frozen()
        y -= HEADER_H
        if y < fh:
            return layout.rows.index_at(max(0.0, y) / z)
        return min(layout.max_rows - 1, layout.rows.index_at((y - fh + self._scroll_y) / z + layout.rows.start(fr)))

    def _cell_rect(self, row: int, col: int, merged: bool = True) -> QRectF:
        layout = self._layout()
        z = self._zoom()
        r1, c1 = row, col
        if merged:
            merge = layout.merge_at.get((row, col))
            if merge is not None:
                r1, c1 = merge[2], merge[3]
        x0, y0 = self.x_of(col), self.y_of(row)
        x1 = self.x_of(c1) + layout.cols.size(c1) * z
        y1 = self.y_of(r1) + layout.rows.size(r1) * z
        return QRectF(x0, y0, max(0.0, x1 - x0), max(0.0, y1 - y0))

    @Slot(int, int, result=QRectF)
    def cellRect(self, row: int, col: int) -> QRectF:  # noqa: N802
        """Lage einer Zelle (verbundene: der ganze Bereich) im Raster – für den Editor."""
        if self._layout() is None:
            return QRectF()
        return self._cell_rect(row, col)

    @Slot(float, float, float, float, result=QRectF)
    def objectRect(self, x: float, y: float, w: float, h: float) -> QRectF:  # noqa: N802
        """Lage eines Diagramms (Pixel bei 100 % ab A1) im Raster."""
        layout = self._layout()
        if layout is None:
            return QRectF()
        z = self._zoom()
        fr, fc, fw, fh = self._frozen()
        sx, sy = x * z, y * z
        left = self._header_w() + (sx if sx < fw else sx - self._scroll_x)
        top = HEADER_H + (sy if sy < fh else sy - self._scroll_y)
        return QRectF(left, top, w * z, h * z)

    @Slot(float, float, result="QVariantList")
    def sheetPoint(self, x: float, y: float) -> list:  # noqa: N802
        """Lage im Raster → Pixel bei 100 % ab A1 (Diagramme verschieben)."""
        z = self._zoom()
        fr, fc, fw, fh = self._frozen()
        sx = x - self._header_w()
        sy = y - HEADER_H
        sx = sx if sx < fw else sx + self._scroll_x
        sy = sy if sy < fh else sy + self._scroll_y
        return [sx / z, sy / z]

    @Slot(float, float, result="QVariantList")
    def cellAt(self, x: float, y: float) -> list:  # noqa: N802
        if self._layout() is None:
            return [0, 0]
        return [self._row_at(y), self._col_at(x)]

    def _extent(self) -> tuple[float, float]:
        """Scrollbare Breite/Höhe (ohne fixierte Teile): benutzter Bereich plus Reserve, mindestens bis zur Ansicht."""
        layout = self._layout()
        if layout is None:
            return 1.0, 1.0
        z = self._zoom()
        fr, fc, _fw, _fh = self._frozen()
        controller = self._controller
        last_col = max(layout.used_cols, controller.selection[3] if controller.selection[3] < layout.max_cols - 1 else 0) + 26
        last_row = max(layout.used_rows, controller.selection[2] if controller.selection[2] < layout.max_rows - 1 else 0) + 60
        last_col = min(layout.max_cols, last_col)
        last_row = min(layout.max_rows, last_row)
        width = (layout.cols.start(last_col) - layout.cols.start(fc)) * z
        height = (layout.rows.start(last_row) - layout.rows.start(fr)) * z
        width = max(width, self._scroll_x + self._get_view_width() * 1.5)
        height = max(height, self._scroll_y + self._get_view_height() * 1.5)
        return width, height

    def _max_scroll_x(self) -> float:
        layout = self._layout()
        if layout is None:
            return 0.0
        _fr, fc, _fw, _fh = self._frozen()
        return max(0.0, (layout.cols.start(layout.max_cols) - layout.cols.start(fc)) * self._zoom() - self._get_view_width())

    def _max_scroll_y(self) -> float:
        layout = self._layout()
        if layout is None:
            return 0.0
        fr, _fc, _fw, _fh = self._frozen()
        return max(0.0, (layout.rows.start(layout.max_rows) - layout.rows.start(fr)) * self._zoom() - self._get_view_height())

    # Änderungen ------------------------------------------------------------------------------------------------------
    def _scrolled(self) -> None:
        self.scrollChanged.emit()
        self.extentChanged.emit()
        self._view_revision += 1
        self.viewChanged.emit()
        self._report_viewport()
        self.update()

    def _layout_changed(self) -> None:
        self._fonts = {}
        self.extentChanged.emit()
        self._view_revision += 1
        self.viewChanged.emit()
        self._report_viewport()
        self.update()

    def _zoom_changed(self) -> None:
        self._layout_changed()
        self.ensureCursorVisible()

    def _sheet_changed(self) -> None:
        self._scroll_x = self._scroll_y = 0.0
        self.scrollChanged.emit()
        self._layout_changed()

    def _geometry_changed(self) -> None:
        self.extentChanged.emit()
        self._view_revision += 1
        self.viewChanged.emit()
        self._report_viewport()

    def _report_viewport(self) -> None:
        controller = self._controller
        if controller is None or self._layout() is None or self.width() <= 0 or self.height() <= 0:
            return
        _fr, fc, fw, fh = self._frozen()
        r0 = self._row_at(HEADER_H + fh + 1)
        r1 = self._row_at(self.height() - 1)
        c0 = self._col_at(self._header_w() + fw + 1)
        c1 = self._col_at(self.width() - 1)
        controller.set_viewport(r0, max(0, c0 - OVERFLOW_LOOKBACK if c0 > fc else c0), r1, c1)

    @Slot()
    def ensureCursorVisible(self) -> None:  # noqa: N802
        """Aktive Zelle (bzw. das Ende der Auswahl beim Erweitern) ins Bild holen."""
        controller = self._controller
        layout = self._layout()
        if controller is None or layout is None:
            return
        row, col = controller._end if hasattr(controller, "_end") else (controller.cursorRow, controller.cursorCol)
        self.ensureVisible(row, col)

    @Slot(int, int)
    def ensureVisible(self, row: int, col: int) -> None:  # noqa: N802
        layout = self._layout()
        if layout is None:
            return
        z = self._zoom()
        fr, fc, _fw, _fh = self._frozen()
        if col >= fc and col < layout.max_cols:
            left = (layout.cols.start(col) - layout.cols.start(fc)) * z
            right = left + layout.cols.size(col) * z
            view = self._get_view_width()
            if left < self._scroll_x:
                self._set_scroll_x(left)
            elif right > self._scroll_x + view:
                self._set_scroll_x(min(left, right - view))
        if row >= fr and row < layout.max_rows:
            top = (layout.rows.start(row) - layout.rows.start(fr)) * z
            bottom = top + layout.rows.size(row) * z
            view = self._get_view_height()
            if top < self._scroll_y:
                self._set_scroll_y(top)
            elif bottom > self._scroll_y + view:
                self._set_scroll_y(min(top, bottom - view))

    @Slot(float, float)
    def scrollBy(self, dx: float, dy: float) -> None:  # noqa: N802
        if dx:
            self._set_scroll_x(self._scroll_x + dx)
        if dy:
            self._set_scroll_y(self._scroll_y + dy)

    # Zeichnen --------------------------------------------------------------------------------------------------------
    def paint(self, painter: QPainter) -> None:
        colors = self._colors
        width, height = self.width(), self.height()
        painter.fillRect(QRectF(0, 0, width, height), colors["paper"])
        controller = self._controller
        layout = self._layout()
        if controller is None or layout is None or not layout.loaded:
            self._paint_headers_empty(painter)
            return
        hw = self._header_w()
        fr, fc, fw, fh = self._frozen()
        main_r0 = self._row_at(HEADER_H + fh + 0.5)
        main_r1 = self._row_at(height - 0.5)
        main_c0 = self._col_at(hw + fw + 0.5)
        main_c1 = self._col_at(width - 0.5)
        regions = [((main_r0, main_r1), (main_c0, main_c1), QRectF(hw + fw, HEADER_H + fh, width - hw - fw, height - HEADER_H - fh),
                    (fr, layout.max_rows - 1), (fc, layout.max_cols - 1))]
        if fr:
            regions.append(((0, fr - 1), (main_c0, main_c1), QRectF(hw + fw, HEADER_H, width - hw - fw, fh), (0, fr - 1), (fc, layout.max_cols - 1)))
        if fc:
            regions.append(((main_r0, main_r1), (0, fc - 1), QRectF(hw, HEADER_H + fh, fw, height - HEADER_H - fh), (fr, layout.max_rows - 1), (0, fc - 1)))
        if fr and fc:
            regions.append(((0, fr - 1), (0, fc - 1), QRectF(hw, HEADER_H, fw, fh), (0, fr - 1), (0, fc - 1)))
        for rows, cols, clip, row_bounds, col_bounds in regions:
            if clip.width() <= 0 or clip.height() <= 0:
                continue
            painter.save()
            painter.setClipRect(clip)
            self._paint_cells(painter, rows, cols, col_bounds)
            if controller.crosshair:
                self._paint_crosshair(painter, rows, cols)
            self._paint_selection(painter, row_bounds, col_bounds)
            painter.restore()
        self._paint_freeze_lines(painter, hw, fw, fh)
        self._paint_headers(painter, hw, (main_r0, main_r1), (main_c0, main_c1))
        self._paint_drag_guide(painter)

    def _qcolor(self, text: str | None) -> QColor | None:
        if not text:
            return None
        color = self._color_cache.get(text)
        if color is None:
            color = self._color_cache[text] = QColor(text)
        return color

    def _font(self, style: dict) -> QFont:
        z = self._zoom()
        key = (style.get("font"), style.get("size"), style.get("bold"), style.get("italic"), style.get("underline"), style.get("strike"), z)
        font = self._fonts.get(key)
        if font is None:
            font = QFont(str(style.get("font") or "Calibri"))
            font.setPixelSize(max(1, round(float(style.get("size") or 11) * 96 / 72 * z)))
            font.setBold(bool(style.get("bold")))
            font.setItalic(bool(style.get("italic")))
            font.setUnderline(bool(style.get("underline")))
            font.setStrikeOut(bool(style.get("strike")))
            font.setHintingPreference(QFont.HintingPreference.PreferVerticalHinting)
            self._fonts[key] = font
        return font

    def _paint_cells(self, painter: QPainter, rows: tuple[int, int], cols: tuple[int, int], col_bounds: tuple[int, int]) -> None:
        controller = self._controller
        layout = self._layout()
        cells = controller.sheet_cells()
        z = self._zoom()
        colors = self._colors
        r0, r1 = rows
        c0, c1 = cols
        # Merges, die den Bereich berühren (auch deren Ursprung außerhalb)
        merges = [m for m in layout.merges if not (m[2] < r0 or m[0] > r1 or m[3] < c0 or m[1] > c1)]
        xs = {c: self.x_of(c) for c in range(c0, c1 + 1)}
        ys = {r: self.y_of(r) for r in range(r0, r1 + 1)}
        right = {c: xs[c] + layout.cols.size(c) * z for c in xs}
        bottom = {r: ys[r] + layout.rows.size(r) * z for r in ys}
        styles = controller.styles
        default_style = cells.default_style
        # Hintergründe
        for r in range(r0, r1 + 1):
            for c in range(c0, c1 + 1):
                value = cells.get(r, c)
                if value is None or (r, c) in layout.covered or (r, c) in layout.merge_at:
                    continue
                background = self._qcolor((styles.get(value[2]) or {}).get("background"))
                if background is not None:
                    painter.fillRect(QRectF(xs[c], ys[r], right[c] - xs[c], bottom[r] - ys[r]), background)
        # Gitternetz
        if layout.grid:
            pen = QPen(colors["line"], 1)
            pen.setCosmetic(True)
            painter.setPen(pen)
            left_x, top_y = xs[c0], ys[r0]
            right_x, bottom_y = right[c1], bottom[r1]
            for c in range(c0, c1 + 1):
                if layout.cols.size(c) > 0:
                    x = round(right[c]) - 0.5
                    painter.drawLine(QPointF(x, top_y), QPointF(x, bottom_y))
            for r in range(r0, r1 + 1):
                if layout.rows.size(r) > 0:
                    y = round(bottom[r]) - 0.5
                    painter.drawLine(QPointF(left_x, y), QPointF(right_x, y))
            # Zellen mit Hintergrund decken das Gitter ab (wie Excel) – neu füllen ohne Gitterlinien innen
            for r in range(r0, r1 + 1):
                for c in range(c0, c1 + 1):
                    value = cells.get(r, c)
                    if value is None or (r, c) in layout.covered or (r, c) in layout.merge_at:
                        continue
                    background = self._qcolor((styles.get(value[2]) or {}).get("background"))
                    if background is not None:
                        painter.fillRect(QRectF(xs[c], ys[r], right[c] - xs[c] - 1, bottom[r] - ys[r] - 1), background)
        # Datenbalken (bedingte Formatierung): Balken von links, Länge = Anteil am größten Wert
        for r in range(r0, r1 + 1):
            for c in range(c0, c1 + 1):
                value = cells.get(r, c)
                bar = (styles.get(value[2]) or {}).get("bar") if value is not None else None
                if not bar or (r, c) in layout.covered:
                    continue
                color = QColor(self._qcolor(bar[0]) or colors["accent"])
                color.setAlphaF(0.75)
                inset = max(1.0, 2 * z)
                length = max(0.0, (right[c] - xs[c] - 2 * inset - 1) * float(bar[1]))
                if length > 0:
                    painter.fillRect(QRectF(xs[c] + inset, ys[r] + inset, length, bottom[r] - ys[r] - 2 * inset - 1), color)
        # Verbundene Zellen: Fläche ohne Gitter innen
        for m in merges:
            rect = self._cell_rect(m[0], m[1])
            value = cells.get(m[0], m[1])
            background = self._qcolor((styles.get(value[2]) or {}).get("background")) if value else None
            inner = QRectF(rect.x(), rect.y(), rect.width() - 1, rect.height() - 1) if layout.grid else rect
            painter.fillRect(inner, background or colors["paper"])
        # Text (mit Überlauf in leere Nachbarzellen)
        lookback = max(col_bounds[0], c0 - OVERFLOW_LOOKBACK)
        for r in range(r0, r1 + 1):
            if layout.rows.size(r) <= 0:
                continue
            for c in range(lookback, c1 + 1):
                value = cells.get(r, c)
                if value is None or not value[0] or (r, c) in layout.covered:
                    continue
                if c < c0 and (r, c) in layout.merge_at:
                    continue
                self._paint_text(painter, r, c, value, styles.get(value[2]) or styles.get(default_style) or {}, cells, layout, c1, col_bounds)
        for m in merges:
            if m[0] < r0 or m[1] < c0:
                value = cells.get(m[0], m[1])
                if value is not None and value[0]:
                    self._paint_text(painter, m[0], m[1], value, styles.get(value[2]) or {}, cells, layout, c1, col_bounds)
        # Rahmen
        for r in range(r0, r1 + 1):
            for c in range(c0, c1 + 1):
                value = cells.get(r, c)
                if value is None:
                    continue
                style = styles.get(value[2])
                if not style or not (style.get("top") or style.get("bottom") or style.get("left") or style.get("right")):
                    continue
                if (r, c) in layout.covered:
                    continue
                self._paint_borders(painter, self._cell_rect(r, c), style, z)
        self._paint_filter_buttons(painter, layout, rows, cols)

    def _paint_text(self, painter: QPainter, row: int, col: int, value: tuple, style: dict, cells, layout, last_col: int,
                    col_bounds: tuple[int, int]) -> None:
        text, kind = value[0], value[1]
        z = self._zoom()
        rect = self._cell_rect(row, col)
        if rect.width() <= 0 or rect.height() <= 0:
            return
        font = self._font(style)
        painter.setFont(font)
        metrics = QFontMetricsF(font)
        pad = PADDING * z
        halign = style.get("halign") or ""
        if not halign or halign == "justify":
            halign = {"n": "right", "e": "center"}.get(kind, "left") if not halign else "left"
        valign = style.get("valign") or "bottom"
        wrap = bool(style.get("wrap"))
        color = self._qcolor(style.get("color")) or self._colors["text"]
        painter.setPen(color)
        merged = (row, col) in layout.merge_at
        if wrap:
            flags = Qt.AlignmentFlag.AlignLeft if halign == "left" else Qt.AlignmentFlag.AlignRight if halign == "right" else Qt.AlignmentFlag.AlignHCenter
            flags |= {"top": Qt.AlignmentFlag.AlignTop, "center": Qt.AlignmentFlag.AlignVCenter}.get(valign, Qt.AlignmentFlag.AlignBottom)
            painter.save()
            painter.setClipRect(rect, Qt.ClipOperation.IntersectClip)
            painter.drawText(rect.adjusted(pad, 1, -pad, -1), int(flags | Qt.TextFlag.TextWordWrap), text)
            painter.restore()
            return
        width = metrics.horizontalAdvance(text)
        available = rect.width() - 2 * pad
        if kind == "n" and width > available + 0.5:
            # Zahl passt nicht: ### (wie Excel)
            hashes = max(1, int(available // max(1.0, metrics.horizontalAdvance("#"))))
            text, width, halign = "#" * hashes, metrics.horizontalAdvance("#" * hashes), "left"
        area = QRectF(rect)
        if width > available and not merged and kind != "n":
            # Überlauf in leere Nachbarzellen
            if halign == "left":
                c = col + 1
                while area.width() - 2 * pad < width and c < layout.max_cols and c <= last_col + 1:
                    neighbour = cells.get(row, c)
                    if (neighbour is not None and neighbour[0]) or (row, c) in layout.covered or (row, c) in layout.merge_at:
                        break
                    area.setRight(self.x_of(c) + layout.cols.size(c) * z)
                    c += 1
            elif halign == "right":
                c = col - 1
                while area.width() - 2 * pad < width and c >= col_bounds[0]:
                    neighbour = cells.get(row, c)
                    if (neighbour is not None and neighbour[0]) or (row, c) in layout.covered or (row, c) in layout.merge_at:
                        break
                    area.setLeft(self.x_of(c))
                    c -= 1
            elif halign == "center":
                grow = (width - available) / 2
                area.adjust(-grow, 0, grow, 0)
        if valign == "top":
            baseline = area.top() + 1 + metrics.ascent()
        elif valign == "center":
            baseline = area.center().y() + (metrics.ascent() - metrics.descent()) / 2
        else:
            baseline = area.bottom() - 2 - metrics.descent()
        if halign == "right":
            x = area.right() - pad - width
        elif halign == "center":
            x = area.center().x() - width / 2
        else:
            x = area.left() + pad
        painter.save()
        painter.setClipRect(area, Qt.ClipOperation.IntersectClip)
        painter.drawText(QPointF(x, baseline), text)
        painter.restore()

    def _paint_borders(self, painter: QPainter, rect: QRectF, style: dict, z: float) -> None:
        for side in ("top", "bottom", "left", "right"):
            line = style.get(side)
            if not line:
                continue
            color, width, kind = line[0], int(line[1]), int(line[2]) if len(line) > 2 else 0
            pen = QPen(self._qcolor(color) or QColor("#000000"))
            px = max(1.0, round(width * MM100_TO_PX * z))
            pen.setWidthF(px)
            pen.setCapStyle(Qt.PenCapStyle.SquareCap)
            if kind == 1:
                pen.setStyle(Qt.PenStyle.DotLine)
            elif kind in (2, 4):
                pen.setStyle(Qt.PenStyle.DashLine)
            painter.setPen(pen)
            offset = 0.5 if px % 2 else 0.0
            if side == "top":
                y = round(rect.top()) - 1 + offset
                painter.drawLine(QPointF(rect.left() - 1, y), QPointF(rect.right() - 1, y))
            elif side == "bottom":
                y = round(rect.bottom()) - 1 + offset
                painter.drawLine(QPointF(rect.left() - 1, y), QPointF(rect.right() - 1, y))
            elif side == "left":
                x = round(rect.left()) - 1 + offset
                painter.drawLine(QPointF(x, rect.top() - 1), QPointF(x, rect.bottom() - 1))
            else:
                x = round(rect.right()) - 1 + offset
                painter.drawLine(QPointF(x, rect.top() - 1), QPointF(x, rect.bottom() - 1))

    def _filter_buttons(self, layout) -> list[tuple[int, int, bool]]:
        info = layout.filter
        if not info or not info.get("range"):
            return []
        r0, c0, _r1, c1 = info["range"]
        active = info.get("active") or {}
        return [(r0, c, str(c) in active) for c in range(c0, c1 + 1)]

    def _filter_button_rect(self, row: int, col: int) -> QRectF:
        rect = self._cell_rect(row, col, merged=False)
        size = min(FILTER_BUTTON, rect.height() - 2, rect.width() - 2)
        return QRectF(rect.right() - size - 2, rect.bottom() - size - 2, size, size)

    def _paint_filter_buttons(self, painter: QPainter, layout, rows: tuple[int, int], cols: tuple[int, int]) -> None:
        for row, col, active in self._filter_buttons(layout):
            if not (rows[0] <= row <= rows[1] and cols[0] <= col <= cols[1]):
                continue
            button = self._filter_button_rect(row, col)
            if button.width() < 6:
                continue
            painter.setPen(QPen(self._colors["headerLine"], 1))
            painter.setBrush(self._colors["selectedHeader"] if active else self._colors["header"])
            painter.drawRect(button.adjusted(0.5, 0.5, -0.5, -0.5))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            center = button.center()
            color = self._colors["accent"] if active else self._colors["headerText"]
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(color)
            if active:
                # Trichter: gefiltert
                funnel = QPolygonF([QPointF(center.x() - 4, center.y() - 4), QPointF(center.x() + 4, center.y() - 4),
                                    QPointF(center.x() + 1, center.y()), QPointF(center.x() + 1, center.y() + 4),
                                    QPointF(center.x() - 1, center.y() + 4), QPointF(center.x() - 1, center.y())])
                painter.drawPolygon(funnel)
            else:
                painter.drawPolygon(QPolygonF([QPointF(center.x() - 3.5, center.y() - 1.5), QPointF(center.x() + 3.5, center.y() - 1.5),
                                               QPointF(center.x(), center.y() + 2.5)]))
            painter.setBrush(Qt.BrushStyle.NoBrush)

    def _paint_crosshair(self, painter: QPainter, rows: tuple[int, int], cols: tuple[int, int]) -> None:
        """Lese-Kreuz: Zeile und Spalte der aktiven Zelle leicht in der Akzentfarbe hinterlegt."""
        controller = self._controller
        layout = self._layout()
        z = self._zoom()
        row, col = controller.cursorRow, controller.cursorCol
        band = QColor(self._colors["accent"])
        band.setAlphaF(0.13)
        left, top = self.x_of(cols[0]), self.y_of(rows[0])
        right = self.x_of(cols[1]) + layout.cols.size(cols[1]) * z
        bottom = self.y_of(rows[1]) + layout.rows.size(rows[1]) * z
        if rows[0] <= row <= rows[1]:
            y = self.y_of(row)
            painter.fillRect(QRectF(left, y, right - left, layout.rows.size(row) * z), band)
        if cols[0] <= col <= cols[1]:
            x = self.x_of(col)
            painter.fillRect(QRectF(x, top, layout.cols.size(col) * z, bottom - top), band)

    def _paint_selection(self, painter: QPainter, row_bounds: tuple[int, int], col_bounds: tuple[int, int]) -> None:
        controller = self._controller
        layout = self._layout()
        z = self._zoom()
        r0, c0, r1, c1 = controller.selection
        sr0, sr1 = max(r0, row_bounds[0]), min(r1, row_bounds[1])
        sc0, sc1 = max(c0, col_bounds[0]), min(c1, col_bounds[1])
        if sr0 > sr1 or sc0 > sc1:
            return
        x0, y0 = self.x_of(sc0), self.y_of(sr0)
        x1 = self.x_of(sc1) + layout.cols.size(sc1) * z
        y1 = self.y_of(sr1) + layout.rows.size(sr1) * z
        area = QRectF(x0, y0, x1 - x0, y1 - y0)
        accent = self._colors["accent"]
        single = (r0, c0, r1, c1) == (r0, c0, r0, c0) or layout.merge_at.get((r0, c0)) == (r0, c0, r1, c1)
        if not single:
            fill = QColor(accent)
            fill.setAlphaF(0.12)
            path = QPainterPath()
            path.addRect(area)
            active = self._cell_rect(controller.cursorRow, controller.cursorCol)
            hole = QPainterPath()
            hole.addRect(active)
            painter.fillPath(path.subtracted(hole), fill)
        pen = QPen(accent, 2)
        pen.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        # Ränder nur dort, wo die Auswahl in diesem Teil wirklich endet
        left, top = round(area.left()), round(area.top())
        right, bottom = round(area.right()) - 1, round(area.bottom()) - 1
        if sc0 == c0:
            painter.drawLine(QPointF(left, top - 1), QPointF(left, bottom + 1))
        if sc1 == c1:
            painter.drawLine(QPointF(right, top - 1), QPointF(right, bottom + 1))
        if sr0 == r0:
            painter.drawLine(QPointF(left - 1, top), QPointF(right + 1, top))
        if sr1 == r1:
            painter.drawLine(QPointF(left - 1, bottom), QPointF(right + 1, bottom))
        if sr1 == r1 and sc1 == c1 and r1 < layout.max_rows - 1 and c1 < layout.max_cols - 1:
            handle = QRectF(right - FILL_HANDLE / 2 + 0.5, bottom - FILL_HANDLE / 2 + 0.5, FILL_HANDLE, FILL_HANDLE)
            painter.fillRect(handle.adjusted(-1, -1, 1, 1), self._colors["paper"])
            painter.fillRect(handle, accent)
        drag = self._drag
        if drag and drag.get("kind") == "fill" and drag.get("target"):
            fr0, fc0, fr1, fc1 = drag["target"]
            fx0, fy0 = self.x_of(fc0), self.y_of(fr0)
            fx1 = self.x_of(fc1) + layout.cols.size(fc1) * z
            fy1 = self.y_of(fr1) + layout.rows.size(fr1) * z
            dashed = QPen(self._colors["headerText"], 1, Qt.PenStyle.DashLine)
            painter.setPen(dashed)
            painter.drawRect(QRectF(fx0, fy0, fx1 - fx0 - 1, fy1 - fy0 - 1))

    def _paint_freeze_lines(self, painter: QPainter, hw: float, fw: float, fh: float) -> None:
        pen = QPen(self._colors["headerText"], 1)
        painter.setPen(pen)
        if fw > 0:
            x = round(hw + fw) - 0.5
            painter.drawLine(QPointF(x, HEADER_H), QPointF(x, self.height()))
        if fh > 0:
            y = round(HEADER_H + fh) - 0.5
            painter.drawLine(QPointF(hw, y), QPointF(self.width(), y))

    def _header_font(self) -> QFont:
        font = self._fonts.get("header")
        if font is None:
            font = QFont()
            font.setPixelSize(12)
            self._fonts["header"] = font
        return font

    def _paint_headers_empty(self, painter: QPainter) -> None:
        painter.fillRect(QRectF(0, 0, self.width(), HEADER_H), self._colors["header"])
        painter.fillRect(QRectF(0, 0, 40, self.height()), self._colors["header"])

    def _paint_headers(self, painter: QPainter, hw: float, rows: tuple[int, int], cols: tuple[int, int]) -> None:
        controller = self._controller
        layout = self._layout()
        z = self._zoom()
        colors = self._colors
        fr, fc, fw, fh = self._frozen()
        r0, c0, r1, c1 = controller.selection
        whole_cols = r0 == 0 and r1 == layout.max_rows - 1
        whole_rows = c0 == 0 and c1 == layout.max_cols - 1
        font = self._header_font()
        painter.setFont(font)
        line = QPen(colors["headerLine"], 1)
        # Spaltenköpfe
        painter.fillRect(QRectF(hw, 0, self.width() - hw, HEADER_H), colors["header"])
        col_ranges = [(0, fc - 1, QRectF(hw, 0, fw, HEADER_H))] if fc else []
        col_ranges.append((cols[0], cols[1], QRectF(hw + fw, 0, self.width() - hw - fw, HEADER_H)))
        for first, last, clip in col_ranges:
            painter.save()
            painter.setClipRect(clip)
            for c in range(first, last + 1):
                size = layout.cols.size(c) * z
                if size <= 0:
                    continue
                x = self.x_of(c)
                rect = QRectF(x, 0, size, HEADER_H)
                selected = c0 <= c <= c1
                if selected:
                    painter.fillRect(rect, colors["selectedHeader"])
                painter.setPen(colors["selectedHeaderText"] if selected else colors["headerText"])
                font.setBold(selected and whole_cols)
                painter.setFont(font)
                painter.drawText(rect, int(Qt.AlignmentFlag.AlignCenter), column_name(c))
                painter.setPen(line)
                painter.drawLine(QPointF(round(x + size) - 0.5, 0), QPointF(round(x + size) - 0.5, HEADER_H))
                if selected:
                    painter.fillRect(QRectF(x, HEADER_H - 2, size, 2), colors["accent"])
            painter.restore()
        # Zeilenköpfe
        painter.fillRect(QRectF(0, HEADER_H, hw, self.height() - HEADER_H), colors["header"])
        row_ranges = [(0, fr - 1, QRectF(0, HEADER_H, hw, fh))] if fr else []
        row_ranges.append((rows[0], rows[1], QRectF(0, HEADER_H + fh, hw, self.height() - HEADER_H - fh)))
        for first, last, clip in row_ranges:
            painter.save()
            painter.setClipRect(clip)
            for r in range(first, last + 1):
                size = layout.rows.size(r) * z
                if size <= 0:
                    continue
                y = self.y_of(r)
                rect = QRectF(0, y, hw, size)
                selected = r0 <= r <= r1
                if selected:
                    painter.fillRect(rect, colors["selectedHeader"])
                painter.setPen(colors["selectedHeaderText"] if selected else colors["headerText"])
                font.setBold(selected and whole_rows)
                painter.setFont(font)
                painter.drawText(rect, int(Qt.AlignmentFlag.AlignCenter), str(r + 1))
                painter.setPen(line)
                painter.drawLine(QPointF(0, round(y + size) - 0.5), QPointF(hw, round(y + size) - 0.5))
                if selected:
                    painter.fillRect(QRectF(hw - 2, y, 2, size), colors["accent"])
            painter.restore()
        font.setBold(False)
        # Ecke (alles auswählen) und Trennlinien
        painter.fillRect(QRectF(0, 0, hw, HEADER_H), colors["header"])
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(colors["headerLine"].darker(115))
        painter.drawPolygon(QPolygonF([QPointF(hw - 4, HEADER_H - 14), QPointF(hw - 4, HEADER_H - 4), QPointF(hw - 14, HEADER_H - 4)]))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(line)
        painter.drawLine(QPointF(0, HEADER_H - 0.5), QPointF(self.width(), HEADER_H - 0.5))
        painter.drawLine(QPointF(hw - 0.5, 0), QPointF(hw - 0.5, self.height()))

    def _paint_drag_guide(self, painter: QPainter) -> None:
        drag = self._drag
        if not drag or drag.get("kind") != "resize":
            return
        pen = QPen(self._colors["accent"], 1, Qt.PenStyle.DashLine)
        painter.setPen(pen)
        if drag["axis"] == "cols":
            x = round(drag["start"] + drag["size"]) - 0.5
            painter.drawLine(QPointF(x, 0), QPointF(x, self.height()))
        else:
            y = round(drag["start"] + drag["size"]) - 0.5
            painter.drawLine(QPointF(0, y), QPointF(self.width(), y))

    # Maus ------------------------------------------------------------------------------------------------------------
    def _area(self, pos: QPointF) -> str:
        hw = self._header_w()
        if pos.y() < HEADER_H and pos.x() < hw:
            return "corner"
        if pos.y() < HEADER_H:
            return "cols"
        if pos.x() < hw:
            return "rows"
        return "cells"

    def _resize_target(self, pos: QPointF, area: str) -> tuple[str, int, float] | None:
        """Maus auf einer Trennlinie im Kopf: (Achse, Index, Anfang) der Spalte/Zeile davor."""
        layout = self._layout()
        z = self._zoom()
        if area == "cols":
            col = self._col_at(pos.x())
            for candidate in (col, col - 1):
                if candidate < 0:
                    continue
                edge = self.x_of(candidate) + layout.cols.size(candidate) * z
                if abs(pos.x() - edge) <= RESIZE_GRIP and layout.cols.size(candidate) > 0:
                    return "cols", candidate, self.x_of(candidate)
        elif area == "rows":
            row = self._row_at(pos.y())
            for candidate in (row, row - 1):
                if candidate < 0:
                    continue
                edge = self.y_of(candidate) + layout.rows.size(candidate) * z
                if abs(pos.y() - edge) <= RESIZE_GRIP and layout.rows.size(candidate) > 0:
                    return "rows", candidate, self.y_of(candidate)
        return None

    def _on_fill_handle(self, pos: QPointF) -> bool:
        controller = self._controller
        layout = self._layout()
        z = self._zoom()
        r0, c0, r1, c1 = controller.selection
        if r1 >= layout.max_rows - 1 or c1 >= layout.max_cols - 1:
            return False
        x = self.x_of(c1) + layout.cols.size(c1) * z
        y = self.y_of(r1) + layout.rows.size(r1) * z
        return abs(pos.x() - x) <= FILL_HANDLE and abs(pos.y() - y) <= FILL_HANDLE

    def _filter_hit(self, pos: QPointF) -> int | None:
        layout = self._layout()
        for row, col, _active in self._filter_buttons(layout):
            if self._filter_button_rect(row, col).contains(pos):
                return col
        return None

    def mousePressEvent(self, event) -> None:  # noqa: N802
        controller = self._controller
        if controller is None or self._layout() is None:
            event.ignore()
            return
        self.forceActiveFocus(Qt.FocusReason.MouseFocusReason)
        pos = event.position()
        self._last_mouse = pos
        area = self._area(pos)
        shift = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
        if event.button() == Qt.MouseButton.RightButton:
            self._context_press(pos, area)
            event.accept()
            return
        if area == "corner":
            controller.selectAll()
        elif area in ("cols", "rows"):
            target = self._resize_target(pos, area)
            if target is not None:
                axis, index, start = target
                layout = self._layout()
                size = (layout.cols if axis == "cols" else layout.rows).size(index) * self._zoom()
                self._drag = {"kind": "resize", "axis": axis, "index": index, "start": start, "size": size}
                self.update()
            elif area == "cols":
                col = self._col_at(pos.x())
                controller.selectColumn(col, shift)
                self._drag = {"kind": "cols"}
            else:
                row = self._row_at(pos.y())
                controller.selectRow(row, shift)
                self._drag = {"kind": "rows"}
        else:
            column = self._filter_hit(pos)
            if column is not None:
                button = self._filter_button_rect(self._filter_buttons(self._layout())[0][0], column)
                self.filterButtonClicked.emit(column, button.left(), button.bottom())
                event.accept()
                return
            row, col = self._row_at(pos.y()), self._col_at(pos.x())
            if self._point_mode:
                self._drag = {"kind": "point", "anchor": (row, col)}
                self.referencePicked.emit(cell_name(row, col), False)
            elif self._on_fill_handle(pos) and not shift:
                self._drag = {"kind": "fill", "target": None}
            else:
                controller.select(row, col, shift)
                self._drag = {"kind": "cells"}
        event.accept()

    def _context_press(self, pos: QPointF, area: str) -> None:
        controller = self._controller
        r0, c0, r1, c1 = controller.selection
        layout = self._layout()
        if area == "cols":
            col = self._col_at(pos.x())
            if not (c0 <= col <= c1 and r0 == 0 and r1 == layout.max_rows - 1):
                controller.selectColumn(col, False)
        elif area == "rows":
            row = self._row_at(pos.y())
            if not (r0 <= row <= r1 and c0 == 0 and c1 == layout.max_cols - 1):
                controller.selectRow(row, False)
        elif area == "cells":
            row, col = self._row_at(pos.y()), self._col_at(pos.x())
            if not (r0 <= row <= r1 and c0 <= col <= c1):
                controller.select(row, col, False)
        self.contextMenuRequested.emit(pos.x(), pos.y(), "cell" if area in ("cells", "corner") else area)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        drag = self._drag
        if drag is None or self._controller is None:
            return
        pos = event.position()
        self._last_mouse = pos
        self._drag_to(pos)
        outside = pos.x() < self._header_w() or pos.y() < HEADER_H or pos.x() > self.width() or pos.y() > self.height()
        if outside and drag["kind"] in ("cells", "cols", "rows", "point", "fill"):
            if not self._autoscroll.isActive():
                self._autoscroll.start()
        else:
            self._autoscroll.stop()
        event.accept()

    def _drag_to(self, pos: QPointF) -> None:
        drag = self._drag
        controller = self._controller
        if drag is None or controller is None:
            return
        kind = drag["kind"]
        x = min(max(pos.x(), self._header_w() + 1), self.width() - 1)
        y = min(max(pos.y(), HEADER_H + 1), self.height() - 1)
        if kind == "resize":
            start = drag["start"]
            drag["size"] = max(0.0, (pos.x() if drag["axis"] == "cols" else pos.y()) - start)
            self.update()
        elif kind == "cells":
            controller.select(self._row_at(y), self._col_at(x), True)
        elif kind == "cols":
            controller.selectColumn(self._col_at(x), True)
        elif kind == "rows":
            controller.selectRow(self._row_at(y), True)
        elif kind == "point":
            row, col = self._row_at(y), self._col_at(x)
            ar, ac = drag["anchor"]
            text = cell_name(ar, ac) if (row, col) == (ar, ac) else f"{cell_name(min(ar, row), min(ac, col))}:{cell_name(max(ar, row), max(ac, col))}"
            if drag.get("text") != text:
                drag["text"] = text
                self.referencePicked.emit(text, True)
        elif kind == "fill":
            r0, c0, r1, c1 = controller.selection
            row, col = self._row_at(y), self._col_at(x)
            down, right = row - r1, col - c1
            up, left = r0 - row, c0 - col
            target = None
            if max(down, up) >= max(right, left):
                if down > 0:
                    target = (r0, c0, row, c1)
                elif up > 0:
                    target = (row, c0, r1, c1)
            else:
                if right > 0:
                    target = (r0, c0, r1, col)
                elif left > 0:
                    target = (r0, col, r1, c1)
            if drag.get("target") != target:
                drag["target"] = target
                drag["cell"] = (row, col)
                self.update()

    def _autoscroll_step(self) -> None:
        if self._drag is None:
            self._autoscroll.stop()
            return
        pos = self._last_mouse
        dx = dy = 0.0
        if pos.x() > self.width():
            dx = min(60.0, pos.x() - self.width())
        elif pos.x() < self._header_w():
            dx = -min(60.0, self._header_w() - pos.x())
        if pos.y() > self.height():
            dy = min(60.0, pos.y() - self.height())
        elif pos.y() < HEADER_H:
            dy = -min(60.0, HEADER_H - pos.y())
        if dx or dy:
            self.scrollBy(dx, dy)
            self._drag_to(pos)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        drag, self._drag = self._drag, None
        self._autoscroll.stop()
        controller = self._controller
        if drag is None or controller is None:
            return
        if drag["kind"] == "resize":
            controller.resize(drag["axis"], drag["index"], drag["size"] / self._zoom())
        elif drag["kind"] == "fill" and drag.get("target"):
            target = drag["target"]
            r0, c0, r1, c1 = controller.selection
            if target[2] > r1:
                controller.fillTo(target[2], c1)
            elif target[3] > c1:
                controller.fillTo(r1, target[3])
            elif target[0] < r0:
                controller.fillTo(target[0], c0)
            elif target[1] < c0:
                controller.fillTo(r0, target[1])
        self.update()
        event.accept()

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        controller = self._controller
        if controller is None or self._layout() is None:
            return
        pos = event.position()
        area = self._area(pos)
        if area in ("cols", "rows"):
            target = self._resize_target(pos, area)
            if target is not None:
                self._drag = None
                controller.autoFit(target[0], target[1])
            event.accept()
            return
        if area == "cells" and not self._point_mode:
            if self._on_fill_handle(pos):
                # Doppelklick aufs Ausfüllkästchen: bis zum Ende der Nachbarspalte (wie Excel)
                self._fill_down_auto()
            else:
                self.editRequested.emit()
                controller.startEdit()
        event.accept()

    def _fill_down_auto(self) -> None:
        controller = self._controller
        cells = controller.sheet_cells()
        r0, c0, r1, c1 = controller.selection
        neighbour = c0 - 1 if c0 > 0 else c1 + 1
        row = r1
        while cells.get(row + 1, neighbour) is not None and cells.get(row + 1, neighbour)[0]:
            row += 1
        if row > r1:
            controller.fillTo(row, c1)

    def hoverMoveEvent(self, event) -> None:  # noqa: N802
        if self._controller is None or self._layout() is None:
            return
        pos = event.position()
        area = self._area(pos)
        shape = Qt.CursorShape.ArrowCursor
        target = self._resize_target(pos, area) if area in ("cols", "rows") else None
        if target is not None:
            shape = Qt.CursorShape.SplitHCursor if target[0] == "cols" else Qt.CursorShape.SplitVCursor
        elif area == "cells" and self._on_fill_handle(pos):
            shape = Qt.CursorShape.CrossCursor
        if shape != self._hover_cursor:
            self._hover_cursor = shape
            self.setCursor(QCursor(shape))

    def wheelEvent(self, event) -> None:  # noqa: N802
        controller = self._controller
        if controller is None or self._layout() is None:
            event.ignore()
            return
        delta = event.angleDelta()
        modifiers = event.modifiers()
        if modifiers & Qt.KeyboardModifier.ControlModifier:
            if delta.y():
                controller.zoomStep(1 if delta.y() > 0 else -1)
            event.accept()
            return
        pixel = event.pixelDelta()
        z = self._zoom()
        row_px = self._layout().rows.default * z
        if not pixel.isNull():
            dx, dy = -pixel.x(), -pixel.y()
        else:
            dx = -delta.x() / 120 * 3 * row_px * 2
            dy = -delta.y() / 120 * 3 * row_px
        if modifiers & Qt.KeyboardModifier.ShiftModifier and not dx:
            dx, dy = dy * 2, 0
        self.scrollBy(dx, dy)
        event.accept()

    # Tastatur --------------------------------------------------------------------------------------------------------
    def keyPressEvent(self, event) -> None:  # noqa: N802
        controller = self._controller
        if controller is None or not controller.ready:
            event.ignore()
            return
        key = event.key()
        modifiers = event.modifiers()
        shift = bool(modifiers & Qt.KeyboardModifier.ShiftModifier)
        ctrl = bool(modifiers & Qt.KeyboardModifier.ControlModifier)
        alt = bool(modifiers & Qt.KeyboardModifier.AltModifier)
        Key = Qt.Key  # noqa: N806
        arrows = {Key.Key_Up: (-1, 0), Key.Key_Down: (1, 0), Key.Key_Left: (0, -1), Key.Key_Right: (0, 1)}
        if key in arrows and not alt:
            dr, dc = arrows[key]
            if ctrl:
                controller.jump(dr, dc, shift)
            else:
                controller.move(dr, dc, shift)
        elif key in (Key.Key_Return, Key.Key_Enter) and not ctrl:
            self._move_in_selection(-1 if shift else 1, 0)
        elif key == Key.Key_Tab or key == Key.Key_Backtab:
            self._move_in_selection(0, -1 if shift or key == Key.Key_Backtab else 1)
        elif key == Key.Key_Home:
            if ctrl:
                controller.select(0, 0, shift)
            else:
                controller.select(controller.cursorRow if not shift else controller._end[0], 0, shift)
            controller.cursorMoved.emit()
        elif key == Key.Key_End and ctrl:
            layout = self._layout()
            controller.select(max(0, layout.used_rows - 1), max(0, layout.used_cols - 1), shift)
            controller.cursorMoved.emit()
        elif key in (Key.Key_PageDown, Key.Key_PageUp):
            rows = max(1, int(self._get_view_height() / max(1.0, self._layout().rows.default * self._zoom())) - 1)
            if alt:
                controller.move(0, rows // 2 if key == Key.Key_PageDown else -(rows // 2), shift)
            else:
                controller.page(rows if key == Key.Key_PageDown else -rows, shift)
        elif key == Key.Key_F2:
            controller.startEdit()
        elif key == Key.Key_Delete:
            controller.clearContents()
        elif key == Key.Key_Backspace:
            controller.clearAndEdit()
        elif key == Key.Key_Space and ctrl:
            controller.selectColumn(controller.cursorCol, False)
        elif key == Key.Key_Space and shift:
            controller.selectRow(controller.cursorRow, False)
        elif ctrl and not alt and key == Key.Key_A:
            controller.selectAll()
        elif ctrl and not alt and key == Key.Key_E:
            controller.flashFill()
        elif ctrl and not alt and key == Key.Key_C:
            controller.copy()
        elif ctrl and not alt and key == Key.Key_X:
            controller.cut()
        elif ctrl and not alt and key == Key.Key_V:
            controller.paste()
        elif ctrl and not alt and key == Key.Key_Z:
            controller.undo()
        elif ctrl and not alt and key == Key.Key_Y:
            controller.redo()
        elif ctrl and not alt and key == Key.Key_B:
            controller.toggle("bold")
        elif ctrl and not alt and key == Key.Key_I:
            controller.toggle("italic")
        elif ctrl and not alt and key == Key.Key_U:
            controller.toggle("underline")
        elif ctrl and not alt and key == Key.Key_D:
            controller.fill("down")
        elif ctrl and not alt and key == Key.Key_R:
            controller.fill("right")
        elif ctrl and not alt and key in (Key.Key_Plus, Key.Key_Minus) and shift is False and False:
            pass
        else:
            text = event.text()
            if text and text.isprintable() and (not ctrl or alt):
                controller.typeText(text)
            else:
                event.ignore()
                return
        event.accept()

    def _move_in_selection(self, dr: int, dc: int) -> None:
        """Eingabe/Tab: innerhalb einer markierten Fläche weiter, sonst zur Nachbarzelle."""
        controller = self._controller
        r0, c0, r1, c1 = controller.selection
        layout = self._layout()
        single = (r0, c0) == (r1, c1) or layout.merge_at.get((r0, c0)) == (r0, c0, r1, c1)
        whole = r1 - r0 >= layout.max_rows - 1 or c1 - c0 >= layout.max_cols - 1
        if single or whole:
            controller.move(dr, dc, False)
            return
        row, col = controller.cursorRow + dr, controller.cursorCol + dc
        if dc:
            if col > c1:
                col, row = c0, row + 1 if row < r1 else r0
            elif col < c0:
                col, row = c1, row - 1 if row > r0 else r1
        else:
            if row > r1:
                row, col = r0, col + 1 if col < c1 else c0
            elif row < r0:
                row, col = r1, col - 1 if col > c0 else c1
        controller._anchor = (row, col)
        controller.cursorRow, controller.cursorCol = row, col
        controller.cellName = cell_name(row, col)
        controller.revision += 1
        controller._load_cell()
        self.ensureVisible(row, col)

    def inputMethodEvent(self, event) -> None:  # noqa: N802
        """Tottasten (^, ´, `) und Eingabehilfen: der fertige Text beginnt die Eingabe."""
        text = event.commitString()
        if text and self._controller is not None and self._controller.ready:
            self._controller.typeText(text)
        event.accept()

    def inputMethodQuery(self, query):  # noqa: N802
        if query == Qt.InputMethodQuery.ImEnabled:
            return True
        if query == Qt.InputMethodQuery.ImCursorRectangle and self._controller is not None and self._layout() is not None:
            return self._cell_rect(self._controller.cursorRow, self._controller.cursorCol)
        return super().inputMethodQuery(query)

