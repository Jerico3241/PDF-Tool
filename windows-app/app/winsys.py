"""Windows-spezifische Helfer an einer Stelle – ohne Oberflächen-Bibliothek.

Jede Funktion liefert auf anderen Systemen, unter älteren Windows-Versionen oder bei
einem Fehler einen sicheren Standardwert. Aufrufer müssen deshalb keine eigenen
try/except-Blöcke um Windows-APIs legen.
"""

from __future__ import annotations

import sys
from pathlib import Path

IS_WINDOWS = sys.platform == "win32"

# --- Windows-Builds -------------------------------------------------------
BUILD_WIN8 = 9200  # erstes Windows mit DWM-Cloaking (DWMWA_CLOAK)
BUILD_WIN10_1809 = 17763  # erstes Build mit DWMWA_USE_IMMERSIVE_DARK_MODE (Attribut 19)
BUILD_WIN10_20H1 = 19041  # Dark-Mode-Attribut hat die offizielle Nummer 20
BUILD_WIN11 = 22000  # Windows 11 21H2: runde Ecken, Titelleistenfarben
BUILD_WIN11_22H2 = 22621  # Windows 11 22H2: DWMWA_SYSTEMBACKDROP_TYPE

# --- DWM-Fensterattribute (dwmapi.h, DWMWINDOWATTRIBUTE) -------------------
DWMWA_CLOAK = 13  # Fenster verbergen, obwohl es gezeichnet wird (ab Windows 8)
DWMWA_USE_IMMERSIVE_DARK_MODE_BEFORE_20H1 = 19
DWMWA_USE_IMMERSIVE_DARK_MODE = 20  # dunkle Titelleiste
DWMWA_WINDOW_CORNER_PREFERENCE = 33  # Eckenradius (nur Windows 11)
DWMWA_CAPTION_COLOR = 35  # Hintergrundfarbe der Titelleiste (nur Windows 11)
DWMWA_TEXT_COLOR = 36  # Textfarbe der Titelleiste (nur Windows 11)
DWMWA_SYSTEMBACKDROP_TYPE = 38  # Systemmaterial hinter dem Fenster (ab 22H2)
DWMWA_MICA_EFFECT = 1029  # undokumentiert, Windows 11 21H2 (vor DWMWA_SYSTEMBACKDROP_TYPE)
DWMWCP_ROUND = 2  # 8 px, Standard für Hauptfenster
DWMSBT_NONE = 1
DWMSBT_MAINWINDOW = 2  # Mica
DWMWA_COLOR_DEFAULT = 0xFFFFFFFF  # Systemfarbe verwenden

# --- SystemParametersInfo --------------------------------------------------
SPI_GETDESKWALLPAPER = 0x0073
SPI_GETCLIENTAREAANIMATION = 0x1042  # Einstellungen > Barrierefreiheit > Animationseffekte

SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010
SWP_FRAMECHANGED = 0x0020

PERSONALIZE_KEY = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
ACCENT_KEY = r"Software\Microsoft\Windows\CurrentVersion\Explorer\Accent"
DWM_KEY = r"Software\Microsoft\Windows\DWM"
DESKTOP_KEY = r"Control Panel\Desktop"

APP_USER_MODEL_ID = "Jerico.PDFTool"  # Taskleisten-Gruppe (wie die Startmenü-Verknüpfung)
APP_MUTEX = "Jerico.PDFTool.Instanz"  # Inno Setup (AppMutex) erkennt damit eine laufende App
_mutex_handle = None


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
    """Die Akzentabstufungen, die Windows selbst verwendet.

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


def wallpaper_state() -> tuple:
    """Desktophintergrund (Datei, Änderungszeit, Anordnung, Farbe) – neu laden nur bei Änderung."""
    path = wallpaper_path() or ""
    try:
        stamp = Path(path).stat().st_mtime_ns if path else None
    except OSError:
        stamp = None
    return (path, stamp, wallpaper_style(), desktop_color())


# --- Fensterrahmen (DWM) ----------------------------------------------------------


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


def apply_window_chrome(hwnd: int, dark: bool, caption: str | None = None, text: str | None = None, mica: bool = False) -> str:
    """Titelleiste in das Design einbinden: dunkler Modus, runde Ecken, Mica bzw. Farbe der App.

    Die App zeichnet ihren Inhalt deckend; DWM-Mica ist deshalb nur in der Titelleiste zu sehen –
    Navigation und Hintergrund erhalten dasselbe Material aus dem Desktophintergrund (``mica``).
    Rückgabe: ``"mica"`` (DWM-Material in der Titelleiste), ``"solid"`` (Titelleiste in der Farbe
    der App) oder ``"none"`` (ältere Systeme: nur heller bzw. dunkler Rahmen).
    """
    if not IS_WINDOWS or not hwnd or is_wine():
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


def can_cloak() -> bool:
    """DWM-Cloaking verfügbar? (Windows 8 und neuer; Wine meldet es nur zum Schein.)"""
    return IS_WINDOWS and windows_build() >= BUILD_WIN8 and not is_wine()


@_safe(False)
def set_cloak(hwnd: int, cloaked: bool) -> bool:
    """Fenster über DWM verbergen bzw. wieder zeigen.

    Ein verborgenes (»cloaked«) Fenster ist sichtbar im Sinne von Windows: Es zeichnet seinen
    Inhalt, DWM stellt es aber nicht dar. So erscheint das erste fertig gezeichnete Bild in
    einem Zug – ohne weißes oder halb aufgebautes Fenster. True, wenn DWM den Aufruf annahm.
    """
    if not hwnd:
        return False
    return _set_attribute(hwnd, DWMWA_CLOAK, 1 if cloaked else 0)


def mica_supported() -> bool:
    """Mica ist ein Material von Windows 11 – und nur mit aktiven Transparenzeffekten sichtbar."""
    if not IS_WINDOWS or is_wine():
        return False
    return windows_build() >= BUILD_WIN11 and transparency_enabled()


# --- Prozess ------------------------------------------------------------------


@_safe(None)
def register_app_identity() -> None:
    """Taskleiste gruppiert das Fenster unter der Startmenü-Verknüpfung; Setup erkennt die laufende App."""
    global _mutex_handle
    import ctypes

    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(ctypes.c_wchar_p(APP_USER_MODEL_ID))
    kernel32 = ctypes.windll.kernel32
    kernel32.CreateMutexW.restype = ctypes.c_void_p
    _mutex_handle = kernel32.CreateMutexW(None, False, APP_MUTEX)


@_safe(False)
def allow_foreground() -> bool:
    """»Öffnen mit« bei laufender App: Der neue Prozess (vom Explorer gestartet, darf in den
    Vordergrund) erlaubt der laufenden App, ihr Fenster nach vorn zu holen."""
    import ctypes

    ASFW_ANY = -1
    return bool(ctypes.windll.user32.AllowSetForegroundWindow(ASFW_ANY))


def open_path(path: str | Path) -> None:
    """Datei oder Ordner mit der Standardanwendung öffnen. Löst OSError aus."""
    import os

    if hasattr(os, "startfile"):
        os.startfile(str(path))  # type: ignore[attr-defined]
        return
    import subprocess

    subprocess.Popen(["xdg-open", str(path)])


# --- Dateien ---------------------------------------------------------------
@_safe("unknown")
def replace_access(path: str | Path) -> str:
    """Ließe sich die Datei jetzt ersetzen? Öffnet sie probeweise mit Löschrecht (wie es
    ``MoveFileEx`` beim Ersetzen braucht) und schließt sie sofort wieder.

    ``"ok"``, ``"in_use"`` (ein anderes Programm hält sie ohne Freigabe zum Löschen offen),
    ``"denied"`` (keine Berechtigung), ``"missing"`` – sonst ``"unknown"`` (auch außerhalb von Windows)."""
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    create = kernel32.CreateFileW
    create.argtypes = (wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE)
    create.restype = wintypes.HANDLE
    delete, share_all, open_existing, normal = 0x00010000, 0x00000007, 3, 0x00000080
    handle = create(str(path), delete, share_all, None, open_existing, normal, None)
    if handle is None or handle == ctypes.c_void_p(-1).value:
        error = ctypes.get_last_error()
        if error in (32, 33):  # ERROR_SHARING_VIOLATION, ERROR_LOCK_VIOLATION
            return "in_use"
        if error == 5:  # ERROR_ACCESS_DENIED
            return "denied"
        if error in (2, 3):  # Datei oder Pfad nicht gefunden
            return "missing"
        return "unknown"
    close = kernel32.CloseHandle
    close.argtypes = (wintypes.HANDLE,)
    close(handle)
    return "ok"
