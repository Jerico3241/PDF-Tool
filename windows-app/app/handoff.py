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
        return False  # die laufende App antwortet nicht: normal starten
    try:
        os.close(handle)
    except OSError:
        pass
    return bool(reply) and reply[0].startswith(b"ok")
