"""Per E-Mail senden: Das E-Mail-Programm des Benutzers öffnet eine neue Nachricht mit der Datei als Anhang.

Gesendet wird nie von PDF Tool – das E-Mail-Programm zeigt die Nachricht, der Benutzer sendet sie selbst.

* Windows: Simple MAPI (``MAPISendMailW`` aus ``mapi32.dll``, sonst ``MAPISendMail``) mit ``MAPI_DIALOG`` und
  ``MAPI_LOGON_UI`` – nur, wenn ein E-Mail-Programm dafür eingetragen ist (sonst zeigte Windows selbst eine
  Fehlermeldung).
* Ohne MAPI oder nach einem Fehler (nicht, wenn der Benutzer abbricht): ``mailto:`` mit Empfänger und Betreff
  (ohne Anhang) und die Datei im Explorer markiert – die Oberfläche bittet dann, die Datei selbst anzuhängen.
* Andere Systeme (Tests): immer dieser zweite Weg.

``send_file`` wartet, solange das E-Mail-Programm die Nachricht zeigt (MAPI) – deshalb ruft
``send_and_report`` es im Hintergrund auf. Protokolliert werden nur Fehlercodes – nie Pfade, Adressen oder
Inhalte.
"""

from __future__ import annotations

import ctypes
import os
import re
import sys
import threading
from pathlib import Path
from urllib.parse import quote

IS_WINDOWS = sys.platform == "win32"

# Ergebnis von ``send_file``
OK = "ok"  # das E-Mail-Programm hat die Nachricht mit Anhang übernommen
CANCELLED = "cancelled"  # im E-Mail-Programm abgebrochen
MANUAL = "manual"  # neue Nachricht ohne Anhang geöffnet, Datei im Explorer markiert – bitte selbst anhängen
NO_CLIENT = "noclient"  # kein E-Mail-Programm gefunden: nur die Datei im Explorer markiert
MISSING = "missing"  # die Datei gibt es nicht
BUSY = "busy"  # eine Nachricht von PDF Tool ist im E-Mail-Programm noch offen

# Simple MAPI (MAPI.h)
MAPI_LOGON_UI = 0x00000001
MAPI_DIALOG = 0x00000008
MAPI_TO = 1
SUCCESS_SUCCESS = 0
MAPI_USER_ABORT = 1
NO_POSITION = 0xFFFFFFFF  # (ULONG)-1: Anhang nicht im Text platziert

ULONG = ctypes.c_uint32  # ULONG/FLAGS unter Windows: 32 Bit (auch 64-Bit-Prozess)
ULONG_PTR = ctypes.c_size_t  # LHANDLE, ULONG_PTR: so breit wie ein Zeiger

_ADDRESS = re.compile(r"^[^@\s,;:<>\"'()\[\]]+@[^@\s,;:<>\"'()\[\]]+\.[^@\s,;:<>\"'()\[\]]+$")
_BUSY = threading.Lock()  # höchstens eine Nachricht zugleich (Simple MAPI erlaubt keine zweite)


class MapiRecipDescW(ctypes.Structure):
    _fields_ = [
        ("ulReserved", ULONG),
        ("ulRecipClass", ULONG),
        ("lpszName", ctypes.c_wchar_p),
        ("lpszAddress", ctypes.c_wchar_p),
        ("ulEIDSize", ULONG),
        ("lpEntryID", ctypes.c_void_p),
    ]


class MapiFileDescW(ctypes.Structure):
    _fields_ = [
        ("ulReserved", ULONG),
        ("flFlags", ULONG),
        ("nPosition", ULONG),
        ("lpszPathName", ctypes.c_wchar_p),
        ("lpszFileName", ctypes.c_wchar_p),
        ("lpFileType", ctypes.c_void_p),
    ]


class MapiMessageW(ctypes.Structure):
    _fields_ = [
        ("ulReserved", ULONG),
        ("lpszSubject", ctypes.c_wchar_p),
        ("lpszNoteText", ctypes.c_wchar_p),
        ("lpszMessageType", ctypes.c_wchar_p),
        ("lpszDateReceived", ctypes.c_wchar_p),
        ("lpszConversationID", ctypes.c_wchar_p),
        ("flFlags", ULONG),
        ("lpOriginator", ctypes.POINTER(MapiRecipDescW)),
        ("nRecipCount", ULONG),
        ("lpRecips", ctypes.POINTER(MapiRecipDescW)),
        ("nFileCount", ULONG),
        ("lpFiles", ctypes.POINTER(MapiFileDescW)),
    ]


# ANSI-Fassung (ältere MAPI ohne ``MAPISendMailW``): gleicher Aufbau, Texte in der ANSI-Codepage
class MapiRecipDesc(ctypes.Structure):
    _fields_ = [
        ("ulReserved", ULONG),
        ("ulRecipClass", ULONG),
        ("lpszName", ctypes.c_char_p),
        ("lpszAddress", ctypes.c_char_p),
        ("ulEIDSize", ULONG),
        ("lpEntryID", ctypes.c_void_p),
    ]


class MapiFileDesc(ctypes.Structure):
    _fields_ = [
        ("ulReserved", ULONG),
        ("flFlags", ULONG),
        ("nPosition", ULONG),
        ("lpszPathName", ctypes.c_char_p),
        ("lpszFileName", ctypes.c_char_p),
        ("lpFileType", ctypes.c_void_p),
    ]


class MapiMessage(ctypes.Structure):
    _fields_ = [
        ("ulReserved", ULONG),
        ("lpszSubject", ctypes.c_char_p),
        ("lpszNoteText", ctypes.c_char_p),
        ("lpszMessageType", ctypes.c_char_p),
        ("lpszDateReceived", ctypes.c_char_p),
        ("lpszConversationID", ctypes.c_char_p),
        ("flFlags", ULONG),
        ("lpOriginator", ctypes.POINTER(MapiRecipDesc)),
        ("nRecipCount", ULONG),
        ("lpRecips", ctypes.POINTER(MapiRecipDesc)),
        ("nFileCount", ULONG),
        ("lpFiles", ctypes.POINTER(MapiFileDesc)),
    ]


def valid_address(text: str) -> bool:
    """Eine einzelne E-Mail-Adresse (``name@firma.de``) – nur dann wird der Empfänger vorausgefüllt."""
    return bool(_ADDRESS.match(str(text or "").strip()))


def mailto_url(to: str = "", subject: str = "", body: str = "") -> str:
    """``mailto:``-Adresse (RFC 6068, UTF-8) mit Empfänger, Betreff und Text – nie mit Anhang."""
    query = [f"{name}={quote(value, safe='')}" for name, value in (("subject", subject), ("body", body)) if value]
    address = quote(to, safe="@+") if valid_address(to) else ""
    return "mailto:" + address + ("?" + "&".join(query) if query else "")


def send_file(path: str, subject: str = "", to: str = "", body: str = "") -> str:
    """Neue Nachricht mit ``path`` als Anhang im E-Mail-Programm öffnen (``MAPI_DIALOG``: der Benutzer sieht sie und
    sendet selbst). Ergebnis: ``OK``, ``CANCELLED``, ``MANUAL``, ``NO_CLIENT``, ``MISSING`` oder ``BUSY``.

    Wartet, solange das E-Mail-Programm die Nachricht zeigt – im Hintergrund aufrufen."""
    path = os.path.abspath(str(path))
    if not os.path.isfile(path):
        return MISSING
    to = to.strip() if valid_address(to) else ""
    if not _BUSY.acquire(blocking=False):
        return BUSY
    com = False
    try:
        com = _com_init()
        if IS_WINDOWS:
            import winsys

            winsys.allow_foreground()  # das E-Mail-Programm (eigener Prozess) darf seine Nachricht nach vorn holen
        try:
            code = _mapi_send(path, subject, to, body) if IS_WINDOWS else None
        except Exception as exc:  # noqa: BLE001 - Fehler im E-Mail-Programm: Weg über mailto:
            _log().warning("E-Mail: Simple MAPI nicht nutzbar (%s) – neue Nachricht ohne Anhang", type(exc).__name__)
            code = None
        if code == SUCCESS_SUCCESS:
            return OK
        if code == MAPI_USER_ABORT:
            return CANCELLED
        if code is not None:
            _log().info("E-Mail: Simple MAPI meldet Fehler %d – neue Nachricht ohne Anhang", code)
        opened = open_url(mailto_url(to, subject, body))
        show_in_folder(path)
        return MANUAL if opened else NO_CLIENT
    finally:
        if com:
            _com_done()
        _BUSY.release()


# Simple MAPI ---------------------------------------------------------------------------------------------------
def _mapi_send(path: str, subject: str, to: str, body: str) -> int | None:
    """Rückgabewert von ``MAPISendMailW`` bzw. ``MAPISendMail`` – ``None``, wenn kein E-Mail-Programm Simple MAPI
    anbietet (dann der Weg über ``mailto:``)."""
    if not IS_WINDOWS or not _mapi_client():
        return None
    try:
        library = ctypes.WinDLL("mapi32.dll")
    except OSError:
        return None
    wide = getattr(library, "MAPISendMailW", None)
    if wide is not None:
        return _send_wide(wide, path, subject, to, body)
    ansi = getattr(library, "MAPISendMail", None)
    if ansi is not None:
        return _send_ansi(ansi, path, subject, to, body)
    return None


def _send_wide(function, path: str, subject: str, to: str, body: str) -> int:
    attachment = MapiFileDescW(0, 0, NO_POSITION, path, os.path.basename(path), None)
    recipients = (MapiRecipDescW * 1)()
    if to:
        recipients[0] = MapiRecipDescW(0, MAPI_TO, to, "SMTP:" + to, 0, None)
    message = MapiMessageW()
    message.lpszSubject = subject
    message.lpszNoteText = body
    message.nRecipCount = 1 if to else 0
    message.lpRecips = ctypes.cast(recipients, ctypes.POINTER(MapiRecipDescW)) if to else None
    message.nFileCount = 1
    message.lpFiles = ctypes.pointer(attachment)
    function.argtypes = (ULONG_PTR, ULONG_PTR, ctypes.POINTER(MapiMessageW), ULONG, ULONG)
    function.restype = ULONG
    return int(function(0, 0, ctypes.byref(message), MAPI_DIALOG | MAPI_LOGON_UI, 0))


def _send_ansi(function, path: str, subject: str, to: str, body: str) -> int | None:
    try:
        encoded = [text.encode("mbcs") for text in (path, os.path.basename(path), subject, body, to, "SMTP:" + to)]
    except (UnicodeEncodeError, LookupError):
        return None  # nicht in der ANSI-Codepage darstellbar: Weg über mailto:
    path_a, file_name, subject_a, body_a, to_a, address_a = encoded
    attachment = MapiFileDesc(0, 0, NO_POSITION, path_a, file_name, None)
    recipients = (MapiRecipDesc * 1)()
    if to:
        recipients[0] = MapiRecipDesc(0, MAPI_TO, to_a, address_a, 0, None)
    message = MapiMessage()
    message.lpszSubject = subject_a
    message.lpszNoteText = body_a
    message.nRecipCount = 1 if to else 0
    message.lpRecips = ctypes.cast(recipients, ctypes.POINTER(MapiRecipDesc)) if to else None
    message.nFileCount = 1
    message.lpFiles = ctypes.pointer(attachment)
    function.argtypes = (ULONG_PTR, ULONG_PTR, ctypes.POINTER(MapiMessage), ULONG, ULONG)
    function.restype = ULONG
    return int(function(0, 0, ctypes.byref(message), MAPI_DIALOG | MAPI_LOGON_UI, 0))


def _mapi_client() -> bool:
    """Ist ein E-Mail-Programm für Simple MAPI eingetragen (»Clients\\Mail«, Benutzer vor Computer)? Ohne Eintrag
    zeigte ``mapi32.dll`` selbst eine Fehlermeldung."""
    try:
        import winreg
    except ImportError:
        return False
    for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        try:
            with winreg.OpenKey(root, r"Software\Clients\Mail") as key:
                value, _kind = winreg.QueryValueEx(key, "")
        except OSError:
            continue
        if isinstance(value, str) and value.strip():
            return True
    return False


def _com_init() -> bool:
    """COM im aufrufenden Thread (Simple MAPI, Shell) – ``True``, wenn danach ``_com_done`` folgen muss."""
    if not IS_WINDOWS:
        return False
    try:
        result = ctypes.WinDLL("ole32").CoInitializeEx(None, 0x2)  # COINIT_APARTMENTTHREADED
    except (OSError, AttributeError):
        return False
    return result in (0, 1)  # S_OK, S_FALSE (schon eingerichtet)


def _com_done() -> None:
    try:
        ctypes.WinDLL("ole32").CoUninitialize()
    except (OSError, AttributeError):
        pass


# Ersatzweg: mailto: und Explorer ------------------------------------------------------------------------------------
def open_url(url: str) -> bool:
    """``mailto:`` mit dem Standardprogramm öffnen – ``False``, wenn keins dafür eingetragen ist."""
    if IS_WINDOWS:
        try:
            os.startfile(url)  # type: ignore[attr-defined]  # noqa: S606 - ShellExecute, wie ein Klick auf einen mailto-Link
        except OSError:
            return False
        return True
    from . import files

    try:
        return bool(files.open_url(url))
    except Exception:  # noqa: BLE001 - ohne Standardprogramm: wie nicht geöffnet
        return False


def show_in_folder(path: str) -> bool:
    """Ordner der Datei im Explorer öffnen und die Datei markieren (andere Systeme: nur den Ordner)."""
    if IS_WINDOWS:
        if _select_in_explorer(path):
            return True
        import subprocess

        try:
            subprocess.Popen(f'explorer /select,"{os.path.normpath(path)}"')  # noqa: S602,S607 - Pfade enthalten kein »"«
        except OSError:
            return False
        return True
    from . import files

    try:
        files.open_path(Path(path).parent)
    except OSError:
        return False
    return True


def _select_in_explorer(path: str) -> bool:
    try:
        shell32 = ctypes.WinDLL("shell32")
        create, select, free = shell32.ILCreateFromPathW, shell32.SHOpenFolderAndSelectItems, shell32.ILFree
    except (OSError, AttributeError):
        return False
    create.argtypes, create.restype = (ctypes.c_wchar_p,), ctypes.c_void_p
    select.argtypes, select.restype = (ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p, ctypes.c_uint32), ctypes.c_long
    free.argtypes, free.restype = (ctypes.c_void_p,), None
    item = create(os.path.normpath(path))
    if not item:
        return False
    try:
        return select(item, 0, None, 0) == 0
    finally:
        free(item)


# Für die Oberfläche --------------------------------------------------------------------------------------------------
def send_and_report(app, path: str, area: str, to: str = "", subject: str = "") -> None:
    """``send_file`` im Hintergrund (das E-Mail-Programm kann warten, bis die Nachricht gesendet ist) und das Ergebnis
    melden: Statuszeile, beim Ersatzweg oder einem Fehler ein Hinweis im Bereich ``area``. Betreff: der Dateiname."""
    name = Path(path).name
    # Kein Fortschrittsring: das E-Mail-Programm kann die Nachricht beliebig lange offen halten
    app.set_status(f"Neue E-Mail mit »{name}« im E-Mail-Programm …", "info")

    def failed(exc: BaseException, _details: str) -> None:
        _log().warning("E-Mail: unerwarteter Fehler (%s)", type(exc).__name__)
        app.notify(area, "error", "Das E-Mail-Programm konnte nicht geöffnet werden.", title="Senden nicht möglich", actions=(("Pfad kopieren", lambda: app.copy_path(path)),))

    app.worker.run(lambda: send_file(path, subject=subject or name, to=to), lambda outcome: report(app, outcome, path, area), failed)


def report(app, outcome: str, path: str, area: str) -> None:
    """Ergebnis von ``send_file`` anzeigen (Statuszeile bzw. Hinweis im Bereich ``area``)."""
    name = Path(path).name
    copy = (("Pfad kopieren", lambda: app.copy_path(path)),)
    if outcome == OK:
        app.set_status(f"»{name}« wurde an Ihr E-Mail-Programm übergeben.", "success")
    elif outcome == CANCELLED:
        app.set_status("Senden per E-Mail abgebrochen.", "neutral")
    elif outcome == MANUAL:
        app.notify(area, "info", f"Ihr E-Mail-Programm konnte die Datei nicht selbst anhängen. Eine neue Nachricht ist geöffnet und »{name}« im Explorer markiert – bitte ziehen Sie die Datei in die Nachricht.",
                   title="Bitte Anhang hinzufügen", actions=copy)
    elif outcome == NO_CLIENT:
        app.notify(area, "warning", f"Es ist kein E-Mail-Programm eingerichtet. »{name}« ist im Explorer markiert – Sie können die Datei in Ihrem E-Mail-Programm oder Webmail anhängen.",
                   title="Kein E-Mail-Programm gefunden", actions=copy)
    elif outcome == BUSY:
        app.notify(area, "info", "Im E-Mail-Programm ist noch eine Nachricht von PDF Tool geöffnet – bitte zuerst senden oder schließen.", title="E-Mail-Programm ist beschäftigt", auto_hide=8000)
    else:
        app.notify(area, "error", f"Die Datei »{name}« gibt es nicht mehr.", title="Senden nicht möglich")


def _log():
    from diagnostics.applog import UI, get

    return get(UI)
