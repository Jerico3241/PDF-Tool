"""Hilfsprozess: startet das Setup erst, wenn PDF Tool beendet ist.

Aufruf durch die App (``installer.Launcher``) – ohne Konsolenfenster, im isolierten Modus::

    runtime\\pythonw.exe -I app\\updater\\launch.py --setup <Setup> --sha256 <Hash> --wait <PID> [--log <Datei>]

1. Warten, bis der Prozess ``--wait`` (die App) beendet ist – höchstens 120 Sekunden. Ist sie
   dann noch nicht beendet, startet das Setup trotzdem; es erkennt eine laufende App selbst
   und bittet, sie zu schließen.
2. Das Setup unmittelbar vor dem Start erneut prüfen: Name ``PDF-Tool-Setup-<Version>.exe``,
   Datei vorhanden, SHA-256 stimmt. Sonst wird die Datei gelöscht, ein Hinweis erscheint und
   nichts wird gestartet.
3. Setup starten wie per Doppelklick (Windows: ShellExecute) – sichtbar, ohne stille Parameter.

Nur Standardbibliothek. Das Protokoll (``--log``) enthält nur Zeitpunkte, Dateinamen und
Ergebnisse.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import os
import re
import subprocess
import sys
import time
from pathlib import Path

WAIT_SECONDS = 120.0
SETUP_NAME = re.compile(r"^PDF-Tool-Setup-[0-9A-Za-z.+-]+\.exe$")
HEX = re.compile(r"^[0-9a-fA-F]{64}$")
TITLE = "PDF Tool – Update"
NOT_VERIFIED = "Das heruntergeladene Update konnte nicht verifiziert werden und wurde daher nicht installiert."
NOT_STARTED = "Das Setup konnte nicht gestartet werden."

OK, NOT_VERIFIED_CODE, START_FAILED_CODE, USAGE_CODE = 0, 2, 3, 4


class Log:
    def __init__(self, path: Path | None) -> None:
        self.path = path
        if path is not None:
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("", encoding="utf-8")
            except OSError:
                self.path = None

    def __call__(self, text: str) -> None:
        if self.path is None:
            return
        try:
            with open(self.path, "a", encoding="utf-8") as handle:
                handle.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {text}\n")
        except OSError:
            pass


def _alive_posix(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    try:  # beendet, aber noch nicht abgeholt (Zombie) gilt als beendet
        state = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0]
        return state != "Z"
    except (OSError, IndexError):
        return True


def wait_for_exit(pid: int, timeout: float = WAIT_SECONDS) -> bool:
    """``True``, sobald der Prozess beendet ist (oder nicht existiert); ``False`` nach Ablauf der Zeit."""
    if pid <= 0:
        return True
    if os.name == "nt":
        import ctypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.restype = ctypes.c_void_p
        kernel32.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
        kernel32.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        kernel32.WaitForSingleObject.restype = ctypes.c_uint32
        kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        synchronize = 0x00100000
        handle = kernel32.OpenProcess(synchronize, 0, pid)
        if not handle:
            return True  # Prozess gibt es nicht (mehr)
        try:
            return kernel32.WaitForSingleObject(handle, int(timeout * 1000)) != 0x102  # WAIT_TIMEOUT
        finally:
            kernel32.CloseHandle(handle)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not _alive_posix(pid):
            return True
        time.sleep(0.05)
    return not _alive_posix(pid)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verified(setup: Path, expected: str) -> bool:
    if not SETUP_NAME.match(setup.name) or not HEX.match(expected or "") or not setup.is_file():
        return False
    try:
        return hmac.compare_digest(sha256(setup), expected.lower())
    except OSError:
        return False


def start(setup: Path) -> None:
    """Setup starten wie per Doppelklick – sichtbar, ohne Parameter."""
    if os.name == "nt":
        os.startfile(str(setup))  # noqa: S606 - ShellExecute (Benutzerkontensteuerung/Hinweise wie gewohnt)
    else:
        subprocess.Popen([str(setup)], cwd=str(setup.parent), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)


def message(text: str) -> None:
    if os.name == "nt":
        try:
            import ctypes

            ctypes.windll.user32.MessageBoxW(0, text, TITLE, 0x10 | 0x10000)  # Fehler, im Vordergrund
            return
        except (ImportError, AttributeError, OSError, TypeError, ValueError):
            pass  # kein Hinweisfenster möglich (ohne Oberfläche): es bleibt nur stderr
    print(text, file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Setup nach dem Beenden von PDF Tool starten")
    parser.add_argument("--setup", required=True, type=Path)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--wait", type=int, default=0, help="Prozess-ID der App")
    parser.add_argument("--timeout", type=float, default=WAIT_SECONDS)
    parser.add_argument("--log", type=Path, default=None)
    try:
        args = parser.parse_args(argv)
    except SystemExit:
        return USAGE_CODE
    log = Log(args.log)
    setup = args.setup.resolve()
    log(f"Warten auf das Ende von PDF Tool (Prozess {args.wait}) …")
    if wait_for_exit(args.wait, args.timeout):
        log("PDF Tool ist beendet.")
    else:
        log("PDF Tool läuft noch – das Setup wird trotzdem gestartet und fordert zum Schließen auf.")
    if not verified(setup, args.sha256):
        log(f"Prüfung fehlgeschlagen: {setup.name} – nicht gestartet, Datei entfernt.")
        try:
            if SETUP_NAME.match(setup.name):
                setup.unlink()
        except OSError:
            pass
        message(NOT_VERIFIED)
        return NOT_VERIFIED_CODE
    log(f"SHA-256 geprüft: {setup.name}")
    try:
        start(setup)
    except OSError as exc:
        log(f"Start fehlgeschlagen: {exc}")
        message(f"{NOT_STARTED}\n\n{exc}")
        return START_FAILED_CODE
    log(f"Setup gestartet: {setup.name}")
    return OK


if __name__ == "__main__":
    sys.exit(main())
