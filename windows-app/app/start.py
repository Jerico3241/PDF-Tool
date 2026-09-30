"""Startet PDF Tool und zeigt Fehler beim Start in einem Windows-Dialog.

Aufruf durch die Verknüpfungen: runtime\\pythonw.exe -s -OO app\\start.py
(pythonw.exe öffnet kein Konsolenfenster).

Die Oberfläche ist eine Qt-Quick-Anwendung (PySide6). Sie hängt nicht vom Arbeitsverzeichnis
ab: Die QML-Dateien kommen aus der eingebauten Ressource ``qml_rc`` (bzw. im Quellbaum aus dem
Ordner ``qml``), alle anderen Pfade werden relativ zu dieser Datei bestimmt.
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
# Qt-Einstellungen von außen (z. B. einer anderen Qt-Installation) dürfen die App nicht stören.
FOREIGN_QT_VARIABLES = ("QT_PLUGIN_PATH", "QML2_IMPORT_PATH", "QML_IMPORT_PATH", "QT_QPA_PLATFORM_PLUGIN_PATH", "QT_QUICK_CONTROLS_STYLE", "QT_QUICK_CONTROLS_CONF")


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
    if str(APP_DIR) not in sys.path:
        sys.path.insert(0, str(APP_DIR))
    dlls = RUNTIME / "DLLs"
    if RUNTIME.is_dir():
        os.environ["PATH"] = str(RUNTIME) + os.pathsep + str(dlls) + os.pathsep + os.environ.get("PATH", "")
    for name in FOREIGN_QT_VARIABLES:
        os.environ.pop(name, None)


def main() -> None:
    prepare_env()
    try:
        from PySide6 import QtCore, QtQml, QtQuick  # noqa: F401
    except Exception:
        fail("Die Oberfläche (Qt) konnte nicht geladen werden.\n\n" + traceback.format_exc())
    try:
        from qtapp.application import main as run

        code = run()
    except Exception:
        fail("Die App ist beim Start abgestürzt.\n\n" + traceback.format_exc())
    raise SystemExit(code)


if __name__ == "__main__":
    main()
