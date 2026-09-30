"""Fensterlage: gespeicherte Größe und Position wiederherstellen – immer auf einem sichtbaren Monitor.

Gespeichert wird in geräteunabhängigen Pixeln (``fenster_qt``). Die Angaben der Tk-Oberfläche
bis 2.6 (``fenster``, physische Pixel) werden nur gelesen, umgerechnet und geprüft – nie
verändert. Liegt die gespeicherte Lage auf keinem vorhandenen Monitor mehr (Monitor entfernt,
Auflösung geändert), erscheint das Fenster mittig auf dem Hauptmonitor.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QRect
from PySide6.QtGui import QGuiApplication, QWindow

CONFIG_KEY = "fenster_qt"
LEGACY_KEY = "fenster"
MIN_SIZE = (760, 540)  # darunter lässt sich das Layout nicht sinnvoll anordnen
DEFAULT_SIZE = (1140, 800)
VISIBLE_MIN = (160, 48)  # so viel vom Fenster (samt Titelleiste) muss auf einem Monitor liegen


@dataclass
class Placement:
    x: int
    y: int
    width: int
    height: int
    maximized: bool = False

    def rect(self) -> QRect:
        return QRect(self.x, self.y, self.width, self.height)


def _screens() -> list[QRect]:
    return [screen.availableGeometry() for screen in QGuiApplication.screens()]


def _primary() -> QRect:
    screen = QGuiApplication.primaryScreen()
    return screen.availableGeometry() if screen is not None else QRect(0, 0, 1280, 800)


def _visible(rect: QRect, screens: list[QRect]) -> bool:
    """Liegt genug vom Fenster – insbesondere die Titelleiste – auf einem Monitor?"""
    title = QRect(rect.x(), rect.y(), rect.width(), 32)
    for area in screens:
        shared = title.intersected(area)
        if shared.width() >= min(VISIBLE_MIN[0], rect.width()) and shared.height() >= min(VISIBLE_MIN[1] // 2, 16) and rect.y() >= area.y() - 8:
            return True
    return False


def _from_config(cfg: dict) -> Placement | None:
    saved = cfg.get(CONFIG_KEY)
    if isinstance(saved, dict):
        try:
            return Placement(int(saved["x"]), int(saved["y"]), int(saved["w"]), int(saved["h"]), bool(saved.get("max")))
        except (KeyError, TypeError, ValueError):
            return None
    legacy = cfg.get(LEGACY_KEY)
    if isinstance(legacy, dict):
        # Tk (bis 2.6) speicherte physische Pixel des Hauptmonitors – umrechnen, dann wie jede Lage prüfen.
        try:
            ratio = QGuiApplication.primaryScreen().devicePixelRatio() if QGuiApplication.primaryScreen() else 1.0
            ratio = ratio if ratio > 0 else 1.0
            width, height = int(legacy.get("w", 0) or 0), int(legacy.get("h", 0) or 0)
            x, y = legacy.get("x"), legacy.get("y")
            if width <= 0 or height <= 0 or not isinstance(x, int) or not isinstance(y, int):
                return Placement(0, 0, 0, 0, bool(legacy.get("max"))) if legacy.get("max") else None
            return Placement(round(x / ratio), round(y / ratio), round(width / ratio), round(height / ratio), bool(legacy.get("max")))
        except (TypeError, ValueError, AttributeError):
            return None
    return None


def initial_placement(cfg: dict) -> Placement:
    """Startlage: gespeichert und geprüft – sonst mittig auf dem Hauptmonitor."""
    screens = _screens() or [_primary()]
    primary = _primary()
    saved = _from_config(cfg)
    min_w, min_h = min(MIN_SIZE[0], primary.width()), min(MIN_SIZE[1], primary.height())
    if saved is not None and saved.width >= min_w and saved.height >= min_h:
        # Größe höchstens so groß wie der Monitor, auf dem das Fenster liegt
        host = next((area for area in screens if area.intersects(saved.rect())), primary)
        width, height = min(saved.width, host.width()), min(saved.height, host.height())
        placed = Placement(saved.x, saved.y, width, height, saved.maximized)
        if _visible(placed.rect(), screens):
            return placed
        return _centered(primary, width, height, saved.maximized)
    maximized = bool(saved.maximized) if saved is not None else False
    width = min(DEFAULT_SIZE[0], int(primary.width() * 0.9))
    height = min(DEFAULT_SIZE[1], int(primary.height() * 0.86))
    return _centered(primary, width, height, maximized)


def _centered(area: QRect, width: int, height: int, maximized: bool = False) -> Placement:
    width, height = min(width, area.width()), min(height, area.height())
    x = area.x() + max(0, (area.width() - width) // 2)
    y = area.y() + max(0, (area.height() - height) // 3)
    return Placement(x, y, width, height, maximized)


class WindowState:
    """Folgt der Fensterlage (nur im normalen Zustand) und liefert sie zum Speichern."""

    def __init__(self, window: QWindow, placement: Placement) -> None:
        self.window = window
        self.normal = placement
        self.maximized = placement.maximized
        for signal in (window.xChanged, window.yChanged, window.widthChanged, window.heightChanged):
            signal.connect(self._moved)
        window.visibilityChanged.connect(self._visibility)

    def apply(self) -> None:
        window = self.window
        min_w, min_h = MIN_SIZE
        primary = _primary()
        window.setMinimumWidth(min(min_w, primary.width()))
        window.setMinimumHeight(min(min_h, primary.height()))
        window.setGeometry(self.normal.rect())

    def _moved(self, *_args) -> None:
        if self.window.visibility() == QWindow.Visibility.Windowed:
            geometry = self.window.geometry()
            if geometry.width() > 0 and geometry.height() > 0:
                self.normal = Placement(geometry.x(), geometry.y(), geometry.width(), geometry.height())

    def _visibility(self, visibility) -> None:
        if visibility == QWindow.Visibility.Maximized:
            self.maximized = True
        elif visibility == QWindow.Visibility.Windowed:
            self.maximized = False
            self._moved()

    def config(self) -> dict:
        normal = self.normal
        return {CONFIG_KEY: {"x": normal.x, "y": normal.y, "w": normal.width, "h": normal.height, "max": bool(self.maximized)}}
