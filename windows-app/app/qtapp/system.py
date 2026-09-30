"""Änderungen der Windows-Einstellungen sofort übernehmen (Design, Akzentfarbe, Animationseffekte).

Windows meldet sie dem Fenster als Nachricht (``WM_SETTINGCHANGE``, ``WM_THEMECHANGED``,
``WM_DWMCOLORIZATIONCOLORCHANGED``, ``WM_SYSCOLORCHANGE``). Mehrere Meldungen in kurzer Folge
werden gesammelt; danach liest ``ThemeController.refresh_system()`` die Einstellungen neu –
nur echte Änderungen wirken. Zusätzlich beim Zurückkehren in die App (falls eine Meldung
fehlte, z. B. nach dem Entsperren des PCs).
"""

from __future__ import annotations

import ctypes
import sys
from typing import Callable

from PySide6.QtCore import QAbstractNativeEventFilter, Qt
from PySide6.QtGui import QGuiApplication

WM_SETTINGCHANGE = 0x001A
WM_SYSCOLORCHANGE = 0x0015
WM_THEMECHANGED = 0x031A
WM_DWMCOLORIZATIONCOLORCHANGED = 0x0320
WATCHED = {WM_SETTINGCHANGE, WM_SYSCOLORCHANGE, WM_THEMECHANGED, WM_DWMCOLORIZATIONCOLORCHANGED}
DELAY_MS = 250


class _Msg(ctypes.Structure):
    _fields_ = [
        ("hwnd", ctypes.c_void_p),
        ("message", ctypes.c_uint),
        ("wParam", ctypes.c_size_t),
        ("lParam", ctypes.c_ssize_t),
        ("time", ctypes.c_uint32),
        ("x", ctypes.c_long),
        ("y", ctypes.c_long),
    ]


class SettingsWatcher(QAbstractNativeEventFilter):
    """Ruft ``changed()`` (verzögert, gesammelt) bei geänderten Windows-Einstellungen auf."""

    def __init__(self, schedule: Callable[[str, int, Callable[[], None]], None], changed: Callable[[], None]) -> None:
        super().__init__()
        self._schedule = schedule
        self._changed = changed
        self.notifications = 0  # Tests, Diagnose

    def notify(self) -> None:
        self.notifications += 1
        self._schedule("system-settings", DELAY_MS, self._changed)

    def nativeEventFilter(self, event_type, message):  # noqa: N802 - Qt-Schnittstelle
        try:
            if bytes(event_type) == b"windows_generic_MSG" and message:
                if _Msg.from_address(int(message)).message in WATCHED:
                    self.notify()
        except (TypeError, ValueError, OverflowError):
            pass
        return False, 0


def watch(app, theme) -> SettingsWatcher | None:
    """Beobachtung einrichten (nur unter Windows Nachrichten; überall: Rückkehr in die App)."""
    qt_app = QGuiApplication.instance()
    if qt_app is None:
        return None
    watcher = SettingsWatcher(app.timers.later, theme.refresh_system)

    def state_changed(state) -> None:
        if state == Qt.ApplicationState.ApplicationActive:
            app.timers.later("system-settings", DELAY_MS, theme.refresh_system)

    qt_app.applicationStateChanged.connect(state_changed)
    if sys.platform == "win32":
        qt_app.installNativeEventFilter(watcher)
    watcher.state_changed = state_changed  # Verbindung lebt so lange wie der Beobachter
    return watcher


def unwatch(watcher: SettingsWatcher | None) -> None:
    qt_app = QGuiApplication.instance()
    if watcher is None or qt_app is None:
        return
    try:
        qt_app.applicationStateChanged.disconnect(watcher.state_changed)
    except (RuntimeError, TypeError):
        pass
    if sys.platform == "win32":
        qt_app.removeNativeEventFilter(watcher)
