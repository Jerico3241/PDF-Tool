"""QML-Oberfläche als Qt-Ressource bündeln (für Setup und Tests).

    python windows-app/qmlres.py <Ausgabe.py>

Alle Dateien unter ``app/qml`` (QML, ``qmldir``, Symbole) kommen unter dem Präfix ``/qml`` in
eine Ressource. ``rcc`` aus PySide6 erzeugt daraus ein Python-Modul (``qml_rc.py``); die App
lädt die Oberfläche dann aus ``qrc:/qml/Main.qml`` – unabhängig vom Arbeitsverzeichnis und ohne
lose QML-Dateien im Programmordner.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parent
QML_DIR = ROOT / "app" / "qml"
PREFIX = "/"  # Dateien liegen unter qrc:/qml/…
SKIP_SUFFIXES = {".qmlc", ".jsc", ".pyc"}


def resource_files(qml_dir: Path = QML_DIR) -> list[Path]:
    files = [
        path
        for path in sorted(qml_dir.rglob("*"))
        if path.is_file() and path.suffix not in SKIP_SUFFIXES and "__pycache__" not in path.parts
    ]
    if not (qml_dir / "Main.qml") in files:
        raise FileNotFoundError(f"Main.qml fehlt in {qml_dir}")
    return files


def qrc_text(qml_dir: Path = QML_DIR) -> str:
    """Ressourcenbeschreibung: jede Datei unter ``qml/<relativer Pfad>``."""
    lines = ['<!DOCTYPE RCC>', '<RCC version="1.0">', f'<qresource prefix="{PREFIX}">']
    for path in resource_files(qml_dir):
        alias = "qml/" + path.relative_to(qml_dir).as_posix()
        lines.append(f'  <file alias="{escape(alias)}">{escape(path.resolve().as_posix())}</file>')
    lines += ["</qresource>", "</RCC>", ""]
    return "\n".join(lines)


def find_rcc() -> Path:
    """``rcc`` aus dem installierten PySide6 (gleiche Qt-Version wie die Laufzeit)."""
    import PySide6

    base = Path(PySide6.__file__).resolve().parent
    for candidate in (base / "rcc.exe", base / "Qt" / "libexec" / "rcc", base / "Qt" / "bin" / "rcc", base / "rcc"):
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(f"rcc nicht gefunden (PySide6 in {base})")


def compile_resources(output: Path, qml_dir: Path = QML_DIR) -> Path:
    """``qml_rc.py`` erzeugen. Löst ``subprocess.CalledProcessError`` aus, wenn rcc scheitert."""
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="pdftool-qrc-") as folder:
        qrc = Path(folder) / "qml.qrc"
        qrc.write_text(qrc_text(qml_dir), encoding="utf-8")
        env = dict(os.environ, LC_ALL="C.UTF-8") if sys.platform != "win32" else None
        subprocess.run([str(find_rcc()), "-g", "python", "--compress-algo", "zlib", "-o", str(output), str(qrc)], check=True, env=env, capture_output=True)
    text = output.read_text(encoding="utf-8")
    if "qRegisterResourceData" not in text:
        raise RuntimeError("rcc hat kein gültiges Ressourcenmodul erzeugt")
    return output


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    print(compile_resources(Path(sys.argv[1])))
