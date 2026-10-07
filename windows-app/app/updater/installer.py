"""Setup starten – erst nach dem Beenden der App, nie durch Überschreiben eigener Dateien.

Die App startet den Hilfsprozess ``launch.py`` (mit der eingebetteten Laufzeit, ohne
Konsolenfenster, vom App-Prozess gelöst) und beendet sich dann wie über das Schließen-Kreuz.
Der Hilfsprozess wartet auf ihr Ende, prüft das Setup erneut und startet es. Das Inno-Setup
aktualisiert die vorhandene Installation (gleiche AppId) und bietet am Ende »PDF Tool starten«
an. Benutzerdaten liegen außerhalb des Programmordners und bleiben unberührt.

Protokoll (Kategorie ``installer``): Start des Hilfsprozesses mit dem Namen des Setups – ohne
Ordner. Was der Hilfsprozess danach tut, steht in seinem eigenen Protokoll (``update-start.log``).
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from diagnostics.applog import INSTALLER
from diagnostics.applog import get as get_log

LAUNCH_SCRIPT = Path(__file__).resolve().with_name("launch.py")
DETACHED_PROCESS = 0x00000008
CREATE_NEW_PROCESS_GROUP = 0x00000200
CREATE_BREAKAWAY_FROM_JOB = 0x01000000
logger = get_log(INSTALLER)


def helper_python() -> Path:
    """Python der laufenden App – unter Windows ``pythonw.exe`` (kein Konsolenfenster)."""
    executable = Path(sys.executable)
    if os.name == "nt":
        windowed = executable.with_name("pythonw.exe")
        if windowed.is_file():
            return windowed
    return executable


def command(setup: Path, sha256: str, wait_pid: int, log: Path | None = None, python: Path | None = None) -> list[str]:
    args = [str(python or helper_python()), "-I", str(LAUNCH_SCRIPT), "--setup", str(setup), "--sha256", sha256, "--wait", str(int(wait_pid))]
    if log is not None:
        args += ["--log", str(log)]
    return args


class Launcher:
    """Startet den Hilfsprozess. Tests ersetzen ihn durch eine Attrappe (``qtapp.updates.create_launcher``)."""

    def __init__(self, python: Path | None = None) -> None:
        self.python = python

    def start(self, setup: Path, sha256: str, wait_pid: int, log: Path | None = None) -> subprocess.Popen:
        args = command(setup, sha256, wait_pid, log, self.python)
        options: dict = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL, "close_fds": True, "cwd": str(Path(setup).parent)}
        if os.name == "nt":
            flags = DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
            try:
                helper = subprocess.Popen(args, creationflags=flags | CREATE_BREAKAWAY_FROM_JOB, **options)
            except OSError:
                # Läuft die App in einem Job ohne Erlaubnis zum Lösen: ohne diese Angabe starten
                helper = subprocess.Popen(args, creationflags=flags, **options)
        else:
            helper = subprocess.Popen(args, start_new_session=True, **options)
        logger.info("Hilfsprozess gestartet: %s startet nach dem Ende von Prozess %d", Path(setup).name, int(wait_pid))
        return helper
