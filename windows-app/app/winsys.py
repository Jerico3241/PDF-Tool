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
    Tab-Leiste und Hintergrund erhalten dasselbe Material aus dem Desktophintergrund (``mica``).
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
def set_window_identity(hwnd: int, exe: str | Path | None, name: str = "Novadesk") -> bool:
    """Taskleiste: Name, Symbol und Neustart-Befehl des Fensters festlegen. Ohne diese Angaben nimmt Windows sie vom
    Prozess – ``pythonw.exe`` – und zeigt beim Rechtsklick auf das Symbol »Python« mit dem Python-Logo (findet es
    keine Startmenü-Verknüpfung mit derselben App-Kennung, etwa nach einem Start über »Öffnen mit«).
    Eigenschaften des Fensters: PKEY_AppUserModel_ID, …_RelaunchCommand, …_RelaunchIconResource und
    …_RelaunchDisplayNameResource (nur zusammen wirksam)."""
    import ctypes
    from ctypes import wintypes

    if not hwnd or exe is None:
        return False

    class GUID(ctypes.Structure):
        _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD), ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]

    class PROPERTYKEY(ctypes.Structure):
        _fields_ = [("fmtid", GUID), ("pid", wintypes.DWORD)]

    class PROPVARIANT(ctypes.Structure):
        _fields_ = [("vt", ctypes.c_ushort), ("r1", ctypes.c_ushort), ("r2", ctypes.c_ushort), ("r3", ctypes.c_ushort), ("value", ctypes.c_void_p), ("extra", ctypes.c_void_p)]

    def guid(text: str) -> GUID:
        value = GUID()
        ctypes.oledll.ole32.CLSIDFromString(ctypes.c_wchar_p("{" + text + "}"), ctypes.byref(value))
        return value

    app_model = guid("9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3")
    store = ctypes.c_void_p()
    ctypes.oledll.shell32.SHGetPropertyStoreForWindow(ctypes.c_void_p(hwnd), ctypes.byref(guid("886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99")), ctypes.byref(store))
    vtable = ctypes.cast(ctypes.cast(store, ctypes.POINTER(ctypes.c_void_p))[0], ctypes.POINTER(ctypes.c_void_p))
    release = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(vtable[2])
    set_value = ctypes.WINFUNCTYPE(ctypes.HRESULT, ctypes.c_void_p, ctypes.POINTER(PROPERTYKEY), ctypes.POINTER(PROPVARIANT))(vtable[6])
    commit = ctypes.WINFUNCTYPE(ctypes.HRESULT, ctypes.c_void_p)(vtable[7])
    keep = []  # Zeichenketten leben bis nach Commit
    try:
        # Reihenfolge wichtig: die Neustart-Angaben vor der Kennung
        values = ((2, f'"{exe}"'), (3, f"{exe},0"), (4, name), (5, APP_USER_MODEL_ID))
        for pid, text in values:
            buffer = ctypes.create_unicode_buffer(text)
            keep.append(buffer)
            variant = PROPVARIANT(vt=31, value=ctypes.cast(buffer, ctypes.c_void_p))  # VT_LPWSTR
            set_value(store, ctypes.byref(PROPERTYKEY(app_model, pid)), ctypes.byref(variant))
        commit(store)
    finally:
        release(store)
    return True


@_safe(False)
def allow_foreground() -> bool:
    """»Öffnen mit« bei laufender App: Der neue Prozess (vom Explorer gestartet, darf in den
    Vordergrund) erlaubt der laufenden App, ihr Fenster nach vorn zu holen."""
    import ctypes

    ASFW_ANY = -1
    return bool(ctypes.windll.user32.AllowSetForegroundWindow(ASFW_ANY))


@_safe(False)
def bring_to_front(hwnd: int) -> bool:
    """Fenster sicher nach vorn holen, wenn ein anderes Programm vorn ist (z. B. Outlook öffnet einen Anhang in der
    schon laufenden App). Windows lehnt ``SetForegroundWindow`` sonst oft ab und lässt nur die Taskleiste blinken –
    das Fenster mit der PDF bliebe unsichtbar hinter Outlook. Kurz an die Eingabe des vorderen Fensters
    anhängen, dann ist es erlaubt."""
    import ctypes

    user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
    user32.GetForegroundWindow.restype = ctypes.c_void_p
    foreground = user32.GetForegroundWindow()
    if not hwnd or foreground == hwnd:
        return True
    own = kernel32.GetCurrentThreadId()
    other = user32.GetWindowThreadProcessId(ctypes.c_void_p(foreground), None) if foreground else 0
    attached = bool(other) and other != own and bool(user32.AttachThreadInput(own, other, True))
    try:
        user32.BringWindowToTop(ctypes.c_void_p(hwnd))
        return bool(user32.SetForegroundWindow(ctypes.c_void_p(hwnd)))
    finally:
        if attached:
            user32.AttachThreadInput(own, other, False)


RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"  # Start mit Windows (nur dieser Benutzer)


@_safe(None)
def run_entry(name: str) -> str | None:
    """Befehl eines Eintrags unter »Start mit Windows« (HKCU\\…\\Run), ``None`` ohne Eintrag."""
    try:
        value = _registry_value(RUN_KEY, name)
    except OSError:
        return None
    return str(value)


@_safe(False)
def set_run_entry(name: str, command: str | None) -> bool:
    """Eintrag unter »Start mit Windows« setzen (``command``) bzw. entfernen (``None``). True bei Erfolg."""
    import winreg

    if command is None:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
                winreg.DeleteValue(key, name)
        except FileNotFoundError:
            pass
        return True
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        winreg.SetValueEx(key, name, 0, winreg.REG_SZ, command)
    return True


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
