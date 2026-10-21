"""Weiterer Start bei laufender App: Übergabe an die laufende App – ohne Qt, gleich zu Beginn von ``start.py``.

Läuft PDF Tool schon (sichtbar oder im Hintergrund), muss ein weiterer Start (Startmenü, Doppelklick auf eine PDF)
nur Bescheid geben und enden. Dafür lohnt es nicht, Qt und die Oberfläche zu laden: ``early_forward`` schreibt die
Nachricht direkt in die Named Pipe der laufenden App (``QLocalServer``, nur für diesen Benutzer) und wartet auf deren
»ok«. Klappt das nicht (keine App, ältere Version, Zeitüberschreitung), startet PDF Tool normal; ``qtapp.instance``
versucht die Übergabe dann noch einmal über Qt.

Übertragen werden nur Dateipfade und ob das Fenster gezeigt werden soll – keine Inhalte.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import threading
import time
from pathlib import Path

PREFIX = "PDFTool-Oeffnen-"
MAX_PATHS = 50
BACKGROUND_ARGUMENT = "--hintergrund"  # Start mit Windows: ohne Fenster
EARLY_TIMEOUT = 3.0  # Sekunden bis zur Antwort der laufenden App
BUSY_WAIT = 2.0  # Sekunden, die ein weiterer Start auf eine belegte Verbindung wartet


def server_name() -> str:
    """Name der Verbindung – je Benutzer verschieden, ohne Benutzernamen im Klartext."""
    ident = "|".join((os.environ.get("USERDOMAIN", ""), os.environ.get("USERNAME", ""), str(Path.home())))
    return PREFIX + hashlib.sha256(ident.encode("utf-8", "replace")).hexdigest()[:20]


def pdf_arguments(argv: list[str]) -> list[str]:
    """Dateipfade aus der Befehlszeile (Optionen wie ``-OO`` sind schon entfernt)."""
    paths = []
    for arg in argv:
        if not arg or arg.startswith("-"):
            continue
        path = Path(arg)
        if path.suffix.lower() == ".pdf" or path.is_file():
            paths.append(str(path.resolve()) if path.exists() else str(path))
    return paths[:MAX_PATHS]


ACTIVATION = "PDFTOOL_ACTIVATION"  # PDF-Tool.exe: »direkt« oder »COM« (DelegateExecute) – nur fürs Protokoll
START_EVENT = "PDFTOOL_START_EVENT"  # Name des Ereignisses, auf das PDF-Tool.exe wartet (siehe ``signal_started``)
ATTACHMENT_FOLDER = "Anhaenge"
ATTACHMENT_DAYS = 7  # gesicherte Anhänge so lange aufheben
_TRANSIENT_PARTS = ("\\content.outlook\\", "\\inetcache\\", "\\olk")


HANDOFF_LOG = "uebergabe.log"
HANDOFF_LOG_LIMIT = 64 * 1024


def handoff_log_path() -> Path:
    """Protokoll der Übergaben im Datenordner (``%APPDATA%\\PDF-Tool``) – nur Art des Ordners und Ergebnisse, keine
    Dateinamen."""
    override = os.environ.get("UE_DATA_DIR")
    if override:
        return Path(override) / HANDOFF_LOG
    base = os.environ.get("APPDATA")
    return (Path(base) if base else Path.home() / ".config") / "PDF-Tool" / HANDOFF_LOG


def note(text: str) -> None:
    """Eine Zeile ins Übergabe-Protokoll (Fehler beim Schreiben werden ignoriert, die Datei bleibt klein)."""
    try:
        path = handoff_log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.is_file() and path.stat().st_size > HANDOFF_LOG_LIMIT:
            path.replace(path.with_suffix(".log.1"))
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} [{os.getpid()}] {text}\n")
    except OSError:
        pass


def place_kind(path: str) -> str:
    """Art des Ordners für das Protokoll: »Outlook«, »Temp«, »Anhänge« oder »anderer Ordner« – nie der Pfad."""
    text = os.path.normcase(os.path.abspath(path)).replace("/", "\\").lower()
    if "\\content.outlook\\" in text or "\\olk" in text:
        return "Outlook"
    if "\\inetcache\\" in text:
        return "INetCache"
    if is_transient(path):
        return "Temp"
    return "anderer Ordner"


def attachments_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
    root = Path(base) if base else Path.home() / ".cache"
    return root / "PDF-Tool" / ATTACHMENT_FOLDER


def is_transient(path: str) -> bool:
    """Kopie, die das aufrufende Programm gleich wieder löscht: Outlook-Anhänge (``INetCache\\Content.Outlook``)
    und Dateien im Temp-Ordner (andere Mailprogramme, Browser)."""
    text = os.path.normcase(os.path.abspath(path)).replace("/", "\\").lower()
    if any(part in text for part in _TRANSIENT_PARTS):
        return True
    for name in ("TEMP", "TMP"):
        folder = os.environ.get(name)
        if folder:
            prefix = os.path.normcase(os.path.abspath(folder)).replace("/", "\\").lower().rstrip("\\") + "\\"
            if text.startswith(prefix):
                return True
    return False


def secure_transient(argv: list[str], target: Path | None = None) -> list[str]:
    """Anhänge aus Outlook & Co. sofort in einen eigenen Ordner kopieren und die Kopie öffnen. Outlook löscht seine
    Kopie, sobald das gestartete Programm endet – bei laufender App endet es gleich nach der Übergabe, und die App
    fände die Datei nicht mehr. Alles andere bleibt unverändert."""
    import shutil

    result, folder = [], None
    for arg in argv:
        if arg and not arg.startswith("-"):
            note(f"Start mit Datei über {os.environ.get(ACTIVATION, 'Befehlszeile')}: {place_kind(arg)}, kurzer Pfad: {'ja' if '~' in arg else 'nein'}, vorhanden: {'ja' if Path(arg).is_file() else 'nein'}, flüchtig: {'ja' if is_transient(arg) else 'nein'}")
        if arg and not arg.startswith("-") and is_transient(arg) and Path(arg).is_file():
            try:
                if folder is None:
                    base = target or attachments_dir()
                    _prune(base)
                    folder = base / (time.strftime("%Y%m%d-%H%M%S") + "-" + os.urandom(3).hex())
                    folder.mkdir(parents=True, exist_ok=True)
                copy = folder / Path(arg).name
                shutil.copyfile(arg, copy)  # ohne Schreibschutz der Outlook-Kopie
                note("Anhang gesichert")
                result.append(str(copy))
                continue
            except OSError as exc:
                note(f"Anhang nicht gesichert: {type(exc).__name__} {getattr(exc, 'winerror', None) or exc.errno}")  # dann wie bisher mit dem Original
        result.append(arg)
    return result


def _prune(base: Path) -> None:
    """Gesicherte Anhänge nach ``ATTACHMENT_DAYS`` Tagen entfernen – aber nie einen Ordner, in dem eine Datei nach
    dem Kopieren geändert wurde: Dort hat der Benutzer die Kopie bearbeitet und gespeichert."""
    import shutil

    limit = time.time() - ATTACHMENT_DAYS * 86400
    try:
        for folder in base.iterdir():
            if not folder.is_dir() or folder.stat().st_mtime >= limit:
                continue
            copied = _copy_time(folder.name)
            if copied is None or copied >= limit or _edited_since(folder, copied):
                continue  # Zeitpunkt unbekannt oder bearbeitet: lieber behalten
            shutil.rmtree(folder, ignore_errors=True)
    except OSError:
        pass


COPY_GRACE = 300  # Sekunden: so lange nach dem Zeitstempel im Ordnernamen gilt eine Datei noch als unveränderte Kopie


def _copy_time(name: str) -> float | None:
    """Zeitpunkt der Kopie aus dem Ordnernamen (``JJJJMMTT-HHMMSS-…``, siehe ``secure_transient``)."""
    try:
        return time.mktime(time.strptime(name[:15], "%Y%m%d-%H%M%S"))
    except (ValueError, OverflowError):
        return None


def _edited_since(folder: Path, copied: float) -> bool:
    try:
        return any(item.stat().st_mtime > copied + COPY_GRACE for item in folder.rglob("*"))
    except OSError:
        return True  # nicht lesbar: nicht löschen


def signal_started() -> None:
    """PDF-Tool.exe Bescheid geben: Die App startet selbst (keine laufende App), das Startprogramm darf enden. Bei einer
    Übergabe an die laufende App ruft ``start.py`` das nicht auf – PDF-Tool.exe endet dann erst mit diesem Prozess,
    also nach der Übergabe. Bis dahin hält es den Aufrufer (etwa Outlook) davon ab, seine Kopie zu löschen oder
    diesen Prozess zu beenden."""
    name = os.environ.pop(START_EVENT, "")
    if sys.platform != "win32" or not name:
        return
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        kernel32.OpenEventW.restype = ctypes.c_void_p
        handle = kernel32.OpenEventW(0x0002, False, name)  # EVENT_MODIFY_STATE
        if handle:
            kernel32.SetEvent(ctypes.c_void_p(handle))
            kernel32.CloseHandle(ctypes.c_void_p(handle))
    except Exception:  # noqa: BLE001 - dann wartet das Startprogramm nur bis zu seinem Zeitlimit
        pass


def message(paths: list[str], show: bool) -> bytes:
    return json.dumps({"open": paths[:MAX_PATHS], "show": bool(show)}).encode("utf-8") + b"\n"


def _connect(pipe: str, wait: float = BUSY_WAIT):
    """Named Pipe öffnen. Ist sie gerade belegt (z. B. mehrere Anhänge aus Outlook kurz nacheinander geöffnet: die
    laufende App bedient noch den vorigen Start), kurz warten und erneut versuchen – sonst startete ein zweites
    PDF Tool. ``None``: keine laufende App bzw. weiter belegt."""
    deadline = time.monotonic() + wait
    while True:
        try:
            return os.open(pipe, os.O_RDWR | getattr(os, "O_BINARY", 0))
        except FileNotFoundError:
            return None  # keine laufende App
        except OSError:
            if time.monotonic() >= deadline:
                return None
            time.sleep(0.05)


def early_forward(argv: list[str], name: str | None = None, timeout: float = EARLY_TIMEOUT) -> bool:
    """Nur Windows: Start an die laufende App übergeben. ``True``: angenommen – dieser Prozess kann sofort enden.

    Start mit Windows (``--hintergrund``) fragt nur, ob PDF Tool schon läuft (nichts wird gezeigt)."""
    if sys.platform != "win32":
        return False
    paths = pdf_arguments(argv)
    show = bool(paths) or BACKGROUND_ARGUMENT not in argv
    handle = _connect("\\\\.\\pipe\\" + (name or server_name()))
    if handle is None:
        if paths:
            note(f"Keine laufende App – Start mit {len(paths)} Datei(en)")
        return False  # keine laufende App
    reply: list[bytes] = []

    def talk() -> None:
        try:
            os.write(handle, message(paths, show))
            reply.append(os.read(handle, 16))
        except OSError:
            pass

    if paths or show:
        try:
            from winsys import allow_foreground

            allow_foreground()  # die laufende App darf ihr Fenster nach vorn holen
        except Exception:  # noqa: BLE001 - ohne Erlaubnis blinkt nur der Taskleisteneintrag
            pass
    worker = threading.Thread(target=talk, name="pdftool-uebergabe", daemon=True)
    worker.start()
    worker.join(timeout)
    if worker.is_alive():
        note(f"Übergabe von {len(paths)} Datei(en): keine Antwort der laufenden App")
        return False  # die laufende App antwortet nicht: normal starten
    try:
        os.close(handle)
    except OSError:
        pass
    accepted = bool(reply) and reply[0].startswith(b"ok")
    if paths:
        note(f"Übergabe von {len(paths)} Datei(en) an die laufende App: {'angenommen' if accepted else 'abgelehnt'}")
    return accepted
