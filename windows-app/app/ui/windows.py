"""Windows-spezifische Helfer an einer Stelle.

Jede Funktion liefert auf anderen Systemen, unter älteren Windows-Versionen
oder bei einem Fehler einen sicheren Standardwert. Aufrufer müssen deshalb
keine eigenen try/except-Blöcke um Windows-APIs legen.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Callable

IS_WINDOWS = sys.platform == "win32"

# --- Windows-Builds -------------------------------------------------------
BUILD_WIN10_1809 = 17763  # erstes Build mit DWMWA_USE_IMMERSIVE_DARK_MODE (Attribut 19)
BUILD_WIN10_20H1 = 19041  # Dark-Mode-Attribut hat die offizielle Nummer 20
BUILD_WIN11 = 22000  # Windows 11 21H2: runde Ecken, Titelleistenfarben, Mica (inoffiziell)
BUILD_WIN11_22H2 = 22621  # Windows 11 22H2: DWMWA_SYSTEMBACKDROP_TYPE

# --- DWM-Fensterattribute (dwmapi.h, DWMWINDOWATTRIBUTE) -------------------
DWMWA_USE_IMMERSIVE_DARK_MODE_BEFORE_20H1 = 19
DWMWA_USE_IMMERSIVE_DARK_MODE = 20  # dunkle Titelleiste
DWMWA_WINDOW_CORNER_PREFERENCE = 33  # Eckenradius (nur Windows 11)
DWMWA_BORDER_COLOR = 34  # Farbe des 1-px-Fensterrahmens (nur Windows 11)
DWMWA_CAPTION_COLOR = 35  # Hintergrundfarbe der Titelleiste (nur Windows 11)
DWMWA_TEXT_COLOR = 36  # Textfarbe der Titelleiste (nur Windows 11)
DWMWA_SYSTEMBACKDROP_TYPE = 38  # Systemmaterial hinter dem Fenster (ab 22H2)
DWMWA_MICA_EFFECT = 1029  # undokumentiert, Windows 11 21H2 (vor DWMWA_SYSTEMBACKDROP_TYPE)

# DWM_WINDOW_CORNER_PREFERENCE
DWMWCP_DEFAULT = 0
DWMWCP_DONOTROUND = 1
DWMWCP_ROUND = 2  # 8 px, Standard für Hauptfenster
DWMWCP_ROUNDSMALL = 3  # 4 px, für Menüs und Tooltips

# DWM_SYSTEMBACKDROP_TYPE
DWMSBT_AUTO = 0
DWMSBT_NONE = 1
DWMSBT_MAINWINDOW = 2  # Mica
DWMSBT_TRANSIENTWINDOW = 3  # Acrylic
DWMSBT_TABBEDWINDOW = 4  # Mica Alt

# Sonderwerte für Farbattribute
DWMWA_COLOR_DEFAULT = 0xFFFFFFFF  # Systemfarbe verwenden
DWMWA_COLOR_NONE = 0xFFFFFFFE  # Rahmen nicht zeichnen

# --- SystemParametersInfo --------------------------------------------------
SPI_GETDESKWALLPAPER = 0x0073
SPI_GETWORKAREA = 0x0030
SPI_GETCLIENTAREAANIMATION = 0x1042  # Einstellungen > Barrierefreiheit > Animationseffekte

# --- Fensternachrichten ------------------------------------------------------
WM_SETTINGCHANGE = 0x001A
WM_THEMECHANGED = 0x031A
WM_DWMCOLORIZATIONCOLORCHANGED = 0x0320
WM_DROPFILES = 0x0233
GWLP_WNDPROC = -4

# SetWindowPos-Flags, um den Rahmen nach Attributänderungen neu zeichnen zu lassen
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010
SWP_FRAMECHANGED = 0x0020

MONITOR_DEFAULTTONEAREST = 2

PERSONALIZE_KEY = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
ACCENT_KEY = r"Software\Microsoft\Windows\CurrentVersion\Explorer\Accent"
DWM_KEY = r"Software\Microsoft\Windows\DWM"
DESKTOP_KEY = r"Control Panel\Desktop"


def _safe(default):
    """Dekorator: Fehler und Nicht-Windows-Systeme liefern ``default``."""

    def wrap(func):
        def inner(*args, **kwargs):
            if not IS_WINDOWS:
                return default
            try:
                return func(*args, **kwargs)
            except Exception:
                return default

        inner.__name__ = func.__name__
        inner.__doc__ = func.__doc__
        return inner

    return wrap


def _registry_value(path: str, name: str, hive: str = "HKCU"):
    import winreg

    root = winreg.HKEY_CURRENT_USER if hive == "HKCU" else winreg.HKEY_LOCAL_MACHINE
    with winreg.OpenKey(root, path) as key:
        value, _kind = winreg.QueryValueEx(key, name)
    return value


# --- Version --------------------------------------------------------------


@_safe(0)
def windows_build() -> int:
    """Build-Nummer von Windows, 0 auf anderen Systemen."""
    build = int(sys.getwindowsversion().build)
    if build < 10240:
        # Ohne Kompatibilitätsmanifest meldet Windows 8.x; die Registry kennt den echten Stand.
        build = int(_registry_value(r"SOFTWARE\Microsoft\Windows NT\CurrentVersion", "CurrentBuildNumber", "HKLM"))
    return build


def is_windows_11() -> bool:
    return windows_build() >= BUILD_WIN11


@_safe(False)
def is_wine() -> bool:
    """Wine meldet sich über ntdll.wine_get_version. Dort gibt es kein DWM-Material."""
    import ctypes

    return hasattr(ctypes.windll.ntdll, "wine_get_version")


# --- DPI --------------------------------------------------------------------


@_safe(None)
def enable_dpi_awareness() -> None:
    """Scharfe Darstellung bei 125–200 %.

    Tk 8.6 reagiert nicht auf WM_DPICHANGED. System-DPI-Bewusstsein ist deshalb
    die stabile Wahl: auf dem Hauptmonitor scharf, auf Monitoren mit anderer
    Skalierung skaliert Windows das Fenster selbst.
    """
    import ctypes

    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)  # PROCESS_SYSTEM_DPI_AWARE
    except Exception:
        ctypes.windll.user32.SetProcessDPIAware()


# --- Systemeinstellungen ------------------------------------------------------


@_safe(True)
def apps_use_light_theme() -> bool:
    """Einstellungen > Personalisierung > Farben > Standard-App-Modus."""
    return bool(_registry_value(PERSONALIZE_KEY, "AppsUseLightTheme"))


@_safe(True)
def transparency_enabled() -> bool:
    """Einstellungen > Personalisierung > Farben > Transparenzeffekte."""
    return bool(_registry_value(PERSONALIZE_KEY, "EnableTransparency"))


@_safe(True)
def client_area_animations() -> bool:
    """Einstellungen > Barrierefreiheit > Visuelle Effekte > Animationseffekte."""
    import ctypes

    value = ctypes.c_int(1)
    if not ctypes.windll.user32.SystemParametersInfoW(SPI_GETCLIENTAREAANIMATION, 0, ctypes.byref(value), 0):
        return True
    return bool(value.value)


def _abgr_to_hex(value: int) -> str:
    red = value & 0xFF
    green = (value >> 8) & 0xFF
    blue = (value >> 16) & 0xFF
    return f"#{red:02X}{green:02X}{blue:02X}"


@_safe(None)
def accent_palette() -> dict[str, str] | None:
    """Die acht Akzentabstufungen, die Windows selbst verwendet.

    AccentPalette enthält acht RGBA-Farben: Light3, Light2, Light1, Akzent,
    Dark1, Dark2, Dark3 und einen ungenutzten Eintrag.
    """
    try:
        raw = bytes(_registry_value(ACCENT_KEY, "AccentPalette"))
    except OSError:
        raw = b""
    names = ("light3", "light2", "light1", "base", "dark1", "dark2", "dark3")
    if len(raw) >= 28:
        return {name: "#{:02X}{:02X}{:02X}".format(*raw[i * 4 : i * 4 + 3]) for i, name in enumerate(names)}
    value = int(_registry_value(DWM_KEY, "AccentColor"))
    return {"base": _abgr_to_hex(value)}


@_safe("")
def wallpaper_path() -> str:
    import ctypes

    buffer = ctypes.create_unicode_buffer(1024)
    if not ctypes.windll.user32.SystemParametersInfoW(SPI_GETDESKWALLPAPER, len(buffer), buffer, 0):
        return ""
    return buffer.value


@_safe((10, 0))
def wallpaper_style() -> tuple[int, int]:
    """(WallpaperStyle, TileWallpaper): 10 Ausfüllen, 6 Anpassen, 2 Strecken, 0 Zentriert, 22 Spanne."""
    style = int(str(_registry_value(DESKTOP_KEY, "WallpaperStyle") or "10"))
    try:
        tile = int(str(_registry_value(DESKTOP_KEY, "TileWallpaper") or "0"))
    except OSError:
        tile = 0
    return style, tile


@_safe(None)
def desktop_color() -> str | None:
    import ctypes

    COLOR_DESKTOP = 1
    return _abgr_to_hex(int(ctypes.windll.user32.GetSysColor(COLOR_DESKTOP)))


# --- Fenster -------------------------------------------------------------------


def frame_hwnd(toplevel) -> int:
    """HWND des äußeren Rahmenfensters eines Tk-Toplevels."""
    if not IS_WINDOWS:
        return 0
    try:
        return int(toplevel.wm_frame(), 16)
    except Exception:
        try:
            import ctypes

            return int(ctypes.windll.user32.GetParent(toplevel.winfo_id()) or toplevel.winfo_id())
        except Exception:
            return 0


def _colorref(hex_color: str) -> int:
    value = hex_color.lstrip("#")
    red, green, blue = int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)
    return red | (green << 8) | (blue << 16)


@_safe(False)
def _set_attribute(hwnd: int, attribute: int, value: int) -> bool:
    import ctypes

    raw = ctypes.c_uint(value & 0xFFFFFFFF)
    result = ctypes.windll.dwmapi.DwmSetWindowAttribute(
        ctypes.c_void_p(hwnd), ctypes.c_uint(attribute), ctypes.byref(raw), ctypes.sizeof(raw)
    )
    return int(result) >= 0


@_safe(None)
def refresh_frame(hwnd: int) -> None:
    import ctypes

    ctypes.windll.user32.SetWindowPos(
        ctypes.c_void_p(hwnd), None, 0, 0, 0, 0,
        SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED,
    )


def mica_supported() -> bool:
    """Echtes DWM-Material ist nur unter Windows 11 mit aktiven Transparenzeffekten sichtbar."""
    if not IS_WINDOWS or is_wine():
        return False
    return windows_build() >= BUILD_WIN11 and transparency_enabled()


def apply_window_chrome(
    hwnd: int,
    dark: bool,
    caption: str | None = None,
    text: str | None = None,
    mica: bool = False,
) -> str:
    """Titelleiste in das Fluent-Design einbinden.

    Rückgabe: ``"mica"`` wenn DWM das Mica-Material übernommen hat, ``"solid"``
    wenn eine einfarbige Titelleiste gesetzt wurde, sonst ``"none"``.
    """
    if not IS_WINDOWS or not hwnd:
        return "none"
    build = windows_build()
    if build >= BUILD_WIN10_1809:
        attribute = DWMWA_USE_IMMERSIVE_DARK_MODE if build >= BUILD_WIN10_20H1 else DWMWA_USE_IMMERSIVE_DARK_MODE_BEFORE_20H1
        _set_attribute(hwnd, attribute, 1 if dark else 0)
    result = "none"
    if build >= BUILD_WIN11:
        _set_attribute(hwnd, DWMWA_WINDOW_CORNER_PREFERENCE, DWMWCP_ROUND)
        applied = False
        if mica and mica_supported():
            if build >= BUILD_WIN11_22H2:
                applied = _set_attribute(hwnd, DWMWA_SYSTEMBACKDROP_TYPE, DWMSBT_MAINWINDOW)
            else:
                applied = _set_attribute(hwnd, DWMWA_MICA_EFFECT, 1)
        if applied:
            # Eine eigene Titelleistenfarbe würde das Material überdecken.
            _set_attribute(hwnd, DWMWA_CAPTION_COLOR, DWMWA_COLOR_DEFAULT)
            _set_attribute(hwnd, DWMWA_TEXT_COLOR, DWMWA_COLOR_DEFAULT)
            result = "mica"
        else:
            if build >= BUILD_WIN11_22H2:
                _set_attribute(hwnd, DWMWA_SYSTEMBACKDROP_TYPE, DWMSBT_NONE)
            else:
                _set_attribute(hwnd, DWMWA_MICA_EFFECT, 0)
            if caption and _set_attribute(hwnd, DWMWA_CAPTION_COLOR, _colorref(caption)):
                result = "solid"
            if text:
                _set_attribute(hwnd, DWMWA_TEXT_COLOR, _colorref(text))
    refresh_frame(hwnd)
    return result


def round_popup(hwnd: int, small: bool = False, border: str | None = None) -> bool:
    """Runde Ecken für rahmenlose Fenster (Aufklappliste, Tooltip). True, wenn DWM rundet."""
    if not IS_WINDOWS or not hwnd or windows_build() < BUILD_WIN11 or is_wine():
        return False
    ok = _set_attribute(hwnd, DWMWA_WINDOW_CORNER_PREFERENCE, DWMWCP_ROUNDSMALL if small else DWMWCP_ROUND)
    if ok and border:
        _set_attribute(hwnd, DWMWA_BORDER_COLOR, _colorref(border))
    return ok


GWL_EXSTYLE = -20
WS_EX_NOACTIVATE = 0x08000000  # Klicks aktivieren das Fenster nicht (Aufklapplisten)
WS_EX_TOOLWINDOW = 0x00000080


@_safe(False)
def set_no_activate(hwnd: int) -> bool:
    """Popup-Fenster sollen dem Hauptfenster beim Anklicken nicht den Fokus nehmen."""
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
    user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.SetWindowLongPtrW.restype = ctypes.c_ssize_t
    user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
    style = user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
    user32.SetWindowLongPtrW(hwnd, GWL_EXSTYLE, style | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW)
    return True


@_safe(None)
def monitor_rects(hwnd: int) -> tuple[tuple[int, int, int, int], tuple[int, int, int, int]] | None:
    """(Monitor, Arbeitsbereich) des Monitors, auf dem das Fenster liegt."""
    import ctypes
    from ctypes import wintypes

    class MONITORINFO(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD),
            ("rcMonitor", wintypes.RECT),
            ("rcWork", wintypes.RECT),
            ("dwFlags", wintypes.DWORD),
        ]

    user32 = ctypes.windll.user32
    user32.MonitorFromWindow.restype = ctypes.c_void_p
    user32.MonitorFromWindow.argtypes = [ctypes.c_void_p, wintypes.DWORD]
    monitor = user32.MonitorFromWindow(ctypes.c_void_p(hwnd), MONITOR_DEFAULTTONEAREST)
    info = MONITORINFO()
    info.cbSize = ctypes.sizeof(MONITORINFO)
    user32.GetMonitorInfoW.argtypes = [ctypes.c_void_p, ctypes.POINTER(MONITORINFO)]
    if not user32.GetMonitorInfoW(ctypes.c_void_p(monitor), ctypes.byref(info)):
        return None
    mon, work = info.rcMonitor, info.rcWork
    return (mon.left, mon.top, mon.right, mon.bottom), (work.left, work.top, work.right, work.bottom)


class TimerResolution:
    """Erhöht die Timer-Auflösung nur solange Animationen laufen.

    Windows taktet Timer standardmäßig mit 15,6 ms. Für flüssige 60 FPS wird
    während einer Animation 1 ms angefordert und danach sofort freigegeben.
    """

    def __init__(self) -> None:
        self._active = False

    def acquire(self) -> None:
        if self._active or not IS_WINDOWS:
            return
        try:
            import ctypes

            ctypes.windll.winmm.timeBeginPeriod(1)
            self._active = True
        except Exception:
            self._active = False

    def release(self) -> None:
        if not self._active:
            return
        try:
            import ctypes

            ctypes.windll.winmm.timeEndPeriod(1)
        except Exception:
            pass
        self._active = False


class WindowHook:
    """Fängt Fensternachrichten ab, die Tk nicht weitergibt.

    * WM_DROPFILES: Dateien aus dem Explorer ins Fenster ziehen
    * WM_SETTINGCHANGE / WM_DWMCOLORIZATIONCOLORCHANGED: Windows-Design oder
      Akzentfarbe wurde geändert

    Die Rückrufe werden über ``schedule`` (z. B. ``root.after``) in die
    Tk-Ereignisschleife verlegt und nie direkt in der Fensterprozedur ausgeführt.
    """

    def __init__(
        self,
        hwnd: int,
        schedule: Callable[[Callable[[], None]], None],
        on_drop: Callable[[list[str]], None] | None = None,
        on_settings: Callable[[str], None] | None = None,
    ) -> None:
        self.hwnd = hwnd
        self._schedule = schedule
        self._on_drop = on_drop
        self._on_settings = on_settings
        self._proc = None
        self._old = None
        self.installed = False
        if IS_WINDOWS and hwnd:
            try:
                self._install()
                self.installed = True
            except Exception:
                self.installed = False

    def _install(self) -> None:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        shell32 = ctypes.windll.shell32
        LRESULT = ctypes.c_ssize_t
        user32.GetWindowLongPtrW.restype = ctypes.c_void_p
        user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.SetWindowLongPtrW.restype = ctypes.c_void_p
        user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_void_p]
        user32.CallWindowProcW.restype = LRESULT
        user32.CallWindowProcW.argtypes = [ctypes.c_void_p, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        shell32.DragQueryFileW.argtypes = [ctypes.c_void_p, wintypes.UINT, ctypes.c_wchar_p, wintypes.UINT]
        shell32.DragQueryFileW.restype = wintypes.UINT
        shell32.DragFinish.argtypes = [ctypes.c_void_p]
        prototype = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
        old = user32.GetWindowLongPtrW(self.hwnd, GWLP_WNDPROC)
        self._old = old

        def proc(handle, msg, wparam, lparam):
            try:
                if msg == WM_DROPFILES and self._on_drop is not None:
                    count = shell32.DragQueryFileW(wparam, 0xFFFFFFFF, None, 0)
                    files = []
                    buffer = ctypes.create_unicode_buffer(32768)
                    for index in range(count):
                        shell32.DragQueryFileW(wparam, index, buffer, len(buffer))
                        files.append(buffer.value)
                    shell32.DragFinish(wparam)
                    callback = self._on_drop
                    self._schedule(lambda: callback(files))
                    return 0
                if msg in (WM_SETTINGCHANGE, WM_DWMCOLORIZATIONCOLORCHANGED, WM_THEMECHANGED) and self._on_settings:
                    area = ""
                    if msg == WM_SETTINGCHANGE and lparam:
                        try:
                            area = ctypes.wstring_at(lparam) or ""
                        except Exception:
                            area = ""
                    elif msg == WM_DWMCOLORIZATIONCOLORCHANGED:
                        area = "ImmersiveColorSet"
                    callback = self._on_settings
                    self._schedule(lambda: callback(area))
            except Exception:
                pass
            return user32.CallWindowProcW(old, handle, msg, wparam, lparam)

        self._proc = prototype(proc)
        user32.SetWindowLongPtrW(self.hwnd, GWLP_WNDPROC, ctypes.cast(self._proc, ctypes.c_void_p))
        if self._on_drop is not None:
            shell32.DragAcceptFiles(ctypes.c_void_p(self.hwnd), True)

    def remove(self) -> None:
        if not self.installed:
            return
        try:
            import ctypes
            from ctypes import wintypes

            user32 = ctypes.windll.user32
            user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_void_p]
            user32.SetWindowLongPtrW(self.hwnd, GWLP_WNDPROC, self._old)
        except Exception:
            pass
        self.installed = False


APP_USER_MODEL_ID = "Jerico.UebersichtenErsteller"  # muss zur AppUserModelID der Verknüpfungen (Inno Setup) passen
APP_MUTEX = "Jerico.UebersichtenErsteller.Instanz"  # Inno Setup (AppMutex) erkennt damit eine laufende App
_mutex_handle = None


@_safe(None)
def register_app_identity() -> None:
    """Taskleiste gruppiert das Fenster unter der Startmenü-Verknüpfung; Setup erkennt die laufende App."""
    global _mutex_handle
    import ctypes

    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(ctypes.c_wchar_p(APP_USER_MODEL_ID))
    kernel32 = ctypes.windll.kernel32
    kernel32.CreateMutexW.restype = ctypes.c_void_p
    _mutex_handle = kernel32.CreateMutexW(None, False, APP_MUTEX)


def open_path(path: str | Path) -> None:
    """Datei oder Ordner mit der Standardanwendung öffnen. Löst OSError aus."""
    import os

    if hasattr(os, "startfile"):
        os.startfile(str(path))  # type: ignore[attr-defined]
        return
    import subprocess

    subprocess.Popen(["xdg-open", str(path)])
