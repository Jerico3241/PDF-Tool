"""Startbildschirm (seit 5.0, Entwurf ``3-startbildschirm.png``): steht, sobald Qt läuft, und geht mit dem ersten
Bild des Hauptfensters zu.

Er liegt dort und so groß, wie gleich das Hauptfenster erscheint (gespeicherte Lage, sonst mittig), und zeigt das
Symbol, den Namen und einen Ladebalken im blauen Verlauf. Gezeichnet mit QPainter statt QML: Er steht so vor der
QML-Engine und berührt sie nicht. Python treibt den Balken in Schritten voran (``step``) – während die Oberfläche lädt,
steht die Ereignisschleife, ein laufender Balken bliebe ohnehin stehen."""

from __future__ import annotations

from PySide6.QtCore import QCoreApplication, QEventLoop, QRect, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QGuiApplication, QIcon, QLinearGradient, QPainter, QPainterPath
from PySide6.QtWidgets import QWidget

import i18n
import winsys
from appstate import ICON_FILE

from .geometry import initial_placement

MAX_SECONDS = 60  # spätestens dann zu, auch wenn das Hauptfenster nie erscheint
ICON_SIZE = 200  # mit dem Rand im Symbol: das Zeichen selbst etwa 150 px breit
BAR_WIDTH = 220
BAR_HEIGHT = 4
BRAND = ("#3D8EF7", "#1E5CD8")  # Verlauf wie »Neu« auf der Startseite (Theme.brandStart/brandEnd)
LIGHT = {"background": "#F9F9F9", "text": "#1A1A1A", "secondary": "#5D5D5D", "track": "#E5E5E5"}
DARK = {"background": "#202020", "text": "#FFFFFF", "secondary": "#C5C5C5", "track": "#3A3A3A"}


def splash_dark(cfg: dict) -> bool:
    """Dunkel wie die App: Einstellung »Design«, sonst wie Windows."""
    mode = cfg.get("theme")
    if mode == "dark":
        return True
    if mode == "light":
        return False
    if winsys.IS_WINDOWS:
        return not winsys.apps_use_light_theme()
    return QGuiApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark


class SplashWindow(QWidget):
    def __init__(self, dark: bool, status: str) -> None:
        super().__init__(None, Qt.WindowType.SplashScreen | Qt.WindowType.FramelessWindowHint)
        self.setObjectName("splashWindow")
        self.setWindowTitle("Novadesk")
        self.colors = DARK if dark else LIGHT
        self.dark = dark
        self.status = status
        self.progress = 0.0
        self.icon = QIcon(str(ICON_FILE)) if ICON_FILE.is_file() else QIcon()
        self.setAutoFillBackground(False)

    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform | QPainter.RenderHint.TextAntialiasing)
        painter.fillRect(self.rect(), QColor(self.colors["background"]))
        center = self.width() / 2
        # Symbol, darunter Name, Ladebalken und Text – Lage wie im Entwurf (Gruppe etwa mittig)
        top = self.height() / 2 - 157
        icon_rect = QRect(round(center - ICON_SIZE / 2), round(top), ICON_SIZE, ICON_SIZE)
        if not self.icon.isNull():
            painter.drawPixmap(icon_rect, self.icon.pixmap(256, 256))  # größte Stufe aus icon.ico, glatt verkleinert
        name_font = QFont("Segoe UI Variable Display")
        name_font.setPixelSize(36)
        name_font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(name_font)
        painter.setPen(QColor(self.colors["text"]))
        name_top = top + ICON_SIZE + 15
        painter.drawText(QRectF(0, name_top, self.width(), 48), Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter, "Novadesk")
        bar_top = name_top + 61
        track = QRectF(center - BAR_WIDTH / 2, bar_top, BAR_WIDTH, BAR_HEIGHT)
        path = QPainterPath()
        path.addRoundedRect(track, BAR_HEIGHT / 2, BAR_HEIGHT / 2)
        painter.fillPath(path, QColor(self.colors["track"]))
        filled = QRectF(track.left(), track.top(), max(BAR_HEIGHT, BAR_WIDTH * max(0.0, min(1.0, self.progress))), BAR_HEIGHT)
        gradient = QLinearGradient(filled.topLeft(), filled.topRight())
        gradient.setColorAt(0, QColor(BRAND[0]))
        gradient.setColorAt(1, QColor(BRAND[1]))
        bar = QPainterPath()
        bar.addRoundedRect(filled, BAR_HEIGHT / 2, BAR_HEIGHT / 2)
        painter.fillPath(bar, gradient)
        status_font = QFont("Segoe UI Variable Text")
        status_font.setPixelSize(13)
        painter.setFont(status_font)
        painter.setPen(QColor(self.colors["secondary"]))
        painter.drawText(QRectF(0, bar_top + BAR_HEIGHT + 15, self.width(), 24), Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter, self.status)
        painter.end()


class Splash:
    """``Splash.show(cfg)`` – ``None``, wenn er sich nicht zeigen lässt (dann startet Novadesk eben ohne)."""

    def __init__(self, window: SplashWindow) -> None:
        self.window = window
        self._closed = False
        QTimer.singleShot(MAX_SECONDS * 1000, self.close)

    @classmethod
    def show(cls, cfg: dict) -> Splash | None:
        try:
            i18n.set_language(i18n.resolve(cfg.get("sprache") or "system"))
            window = SplashWindow(splash_dark(cfg), i18n.tr("Wird gestartet …"))
            place = initial_placement(cfg)
            area = place.rect()
            if place.maximized:
                screen = QGuiApplication.screenAt(area.center()) or QGuiApplication.primaryScreen()
                area = screen.availableGeometry() if screen is not None else area
            window.setGeometry(QRect(area))
            window.show()
            splash = cls(window)
            splash.step(0.1)
            return splash
        except Exception:  # noqa: BLE001 - der Startbildschirm darf den Start nie verhindern
            return None

    @property
    def progress(self) -> float:
        return self.window.progress

    def step(self, progress: float) -> None:
        """Balken auf ``progress`` (0 … 1, nur vorwärts) und gleich zeichnen."""
        if self._closed:
            return
        self.window.progress = max(self.window.progress, progress)
        self.window.repaint()
        QCoreApplication.processEvents(QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents, 30)

    def finish(self, main) -> None:
        """Mit dem ersten fertigen Bild des Hauptfensters schließen (ohne sichtbares Hauptfenster gleich)."""
        if self._closed:
            return
        self.step(1.0)
        if main is None or not main.isVisible():
            self.close()
            return

        def swapped() -> None:
            try:
                main.frameSwapped.disconnect(swapped)
            except (RuntimeError, TypeError):
                pass
            QTimer.singleShot(0, self.close)

        main.frameSwapped.connect(swapped)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self.window.close()
        self.window.deleteLater()
