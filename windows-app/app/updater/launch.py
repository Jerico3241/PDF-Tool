"""Hilfsprozess: startet das Setup erst, wenn PDF Tool beendet ist.

Aufruf durch die App (``installer.Launcher``) – ohne Konsolenfenster, im isolierten Modus::

    runtime\\pythonw.exe -I app\\updater\\launch.py --setup <Setup> --sha256 <Hash> --wait <PID> [--log <Datei>]
        [--silent] [--restart <PDF-Tool.exe>]

1. Warten, bis der Prozess ``--wait`` (die App) beendet ist – höchstens 120 Sekunden. Ist sie
   dann noch nicht beendet, startet das Setup trotzdem; es erkennt eine laufende App selbst
   und bittet, sie zu schließen.
2. Das Setup unmittelbar vor dem Start erneut prüfen: Name ``PDF-Tool-Setup-<Version>.exe``,
   Datei vorhanden, SHA-256 stimmt. Sonst wird die Datei gelöscht, ein Hinweis erscheint und
   nichts wird gestartet.
3. Setup starten. Mit ``--silent`` (seit 4.0, »Jetzt installieren«): ohne Fragen des Assistenten – nur
   ein Fortschrittsfenster (``/SILENT /SUPPRESSMSGBOXES /NORESTART /NOCANCEL``); der Hilfsprozess wartet
   auf das Ende und startet danach PDF Tool neu (``--restart``). Gelingt das stille Setup nicht (Fehlercode,
   Start verweigert), startet es wie per Doppelklick – sichtbar, die Installation lässt sich dort fertig
   machen. Ohne ``--silent``: wie per Doppelklick (Windows: ShellExecute), sichtbar, ohne Parameter.

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
INSTALL_SECONDS = 900.0  # stilles Setup: höchstens so lange warten
SILENT_ARGS = ("/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/NOCANCEL")
RESTART_NAME = "PDF-Tool.exe"
SETUP_NAME = re.compile(r"^PDF-Tool-Setup-[0-9A-Za-z.+-]+\.exe$")
HEX = re.compile(r"^[0-9a-fA-F]{64}$")
TITLE = "PDF Tool – Update"
NOT_VERIFIED = "Das heruntergeladene Update konnte nicht verifiziert werden und wurde daher nicht installiert."
NOT_STARTED = "Das Setup konnte nicht gestartet werden."
NOT_INSTALLED = "Das Update ließ sich nicht im Hintergrund installieren. Das Setup wird jetzt angezeigt – bitte dort die Installation abschließen."

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


def install_silently(setup: Path, log_file: Path | None, timeout: float = INSTALL_SECONDS) -> int:
    """Stilles Setup starten und auf sein Ende warten – Rückgabe: Code des Setups (0 = installiert)."""
    args = [str(setup), *SILENT_ARGS]
    if log_file is not None:
        args.append(f"/LOG={log_file}")
    options: dict = {"cwd": str(setup.parent), "stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
    process = subprocess.Popen(args, **options)  # noqa: S603 - geprüftes Setup, feste Parameter
    try:
        return process.wait(timeout)
    except subprocess.TimeoutExpired:
        return -1  # läuft weiter; die App startet nicht neu, das Fortschrittsfenster bleibt sichtbar


def restart(app: Path) -> bool:
    """PDF Tool nach dem Update wieder starten (nur das eigene Startprogramm)."""
    if app.name != RESTART_NAME or not app.is_file():
        return False
    flags = 0x00000008 | 0x00000200 if os.name == "nt" else 0  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    options: dict = {"cwd": str(app.parent), "stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL, "close_fds": True}
    if os.name == "nt":
        subprocess.Popen([str(app)], creationflags=flags, **options)  # noqa: S603
    else:
        subprocess.Popen([str(app)], start_new_session=True, **options)  # noqa: S603
    return True


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
    parser.add_argument("--silent", action="store_true", help="ohne Fragen installieren, danach neu starten")
    parser.add_argument("--restart", type=Path, default=None, help="PDF-Tool.exe – nach dem stillen Update starten")
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
    if args.silent:
        setup_log = args.log.with_name("update-setup.log") if args.log is not None else None
        try:
            code = install_silently(setup, setup_log)
        except OSError as exc:  # z. B. Start verweigert (Rechte): sichtbar weiter
            code = None
            log(f"Stilles Setup nicht gestartet: {exc}")
        if code == 0:
            log(f"Update installiert: {setup.name}")
            if args.restart is not None:
                try:
                    started = restart(args.restart)
                except OSError as exc:
                    started = False
                    log(f"Neustart fehlgeschlagen: {exc}")
                log("PDF Tool neu gestartet." if started else "PDF Tool nicht neu gestartet.")
            return OK
        if code == -1:
            log("Das Setup läuft noch nach dem Zeitlimit – kein Neustart.")
            return OK
        if code is not None:
            log(f"Stilles Setup endete mit Code {code} – das Setup wird sichtbar gestartet.")
        message(NOT_INSTALLED)
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
