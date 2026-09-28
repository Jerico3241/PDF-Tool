"""Startet die Oberfläche und zeigt Fehler in einem Windows-Dialog.

Aufruf durch die Verknüpfungen: runtime\\pythonw.exe -s -OO app\\start.py
(pythonw.exe öffnet kein Konsolenfenster).
"""

from __future__ import annotations

import os
import sys
import traceback
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
INSTALL_DIR = APP_DIR.parent
RUNTIME = INSTALL_DIR / "runtime"
APP_NAME = "PDF Tool"


def _message(title: str, text: str, error: bool = True) -> None:
    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(0, text[-2000:], title, 0x10 if error else 0x40)
    except Exception:
        pass


def _log_path() -> Path:
    base = os.environ.get("APPDATA")
    folder = Path(base) / "PDF-Tool" if base else INSTALL_DIR
    return folder / "fehler.log"


def fail(text: str) -> None:
    log = _log_path()
    try:
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text(text, encoding="utf-8")
    except OSError:
        pass
    _message(APP_NAME, text)
    raise SystemExit(1)


def prepare_env() -> None:
    os.chdir(APP_DIR)
    sys.path.insert(0, str(APP_DIR))
    tcl = RUNTIME / "tcl" / "tcl8.6"
    tk = RUNTIME / "tcl" / "tk8.6"
    dlls = RUNTIME / "DLLs"
    if tcl.is_dir():
        os.environ.setdefault("TCL_LIBRARY", str(tcl))
    if tk.is_dir():
        os.environ.setdefault("TK_LIBRARY", str(tk))
    os.environ["PATH"] = str(RUNTIME) + os.pathsep + str(dlls) + os.pathsep + os.environ.get("PATH", "")


def main() -> None:
    prepare_env()
    try:
        import tkinter  # noqa: F401
    except Exception:
        fail(
            "Die Fenster-Oberfläche konnte nicht geladen werden.\n\n"
            + traceback.format_exc()
        )
    try:
        import vertragdesk

        vertragdesk.main()
    except Exception:
        fail("Die App ist beim Start abgestürzt.\n\n" + traceback.format_exc())


if __name__ == "__main__":
    main()
