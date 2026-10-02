"""PySide6 in der Windows-Laufzeit auf das Nötige beschränken (für build.py).

Die Wheels von PySide6-Essentials bringen neben Qt Quick viele Werkzeuge und Module mit
(Designer, Linguist, Material-/Fusion-Stile, Dialoge, SQL, Tests …). Im Setup bleibt nur,
was PDF Tool zur Laufzeit lädt:

* Python-Module (``.pyd``): ``PYTHON_MODULES`` – genau die, die ``import PySide6.…`` der App
  (auch indirekt, z. B. QtQml → QtNetwork) lädt. QtPrintSupport (seit 3.0.0) druckt aus dem PDF
  Reader; der Druck unter Windows steckt in ``Qt6PrintSupport.dll`` selbst (kein Plugin).
* Qt-Plugins: ``PLUGINS`` – Fensterplattform, Bildformate (ICO für das Fenstersymbol, JPEG/WebP/SVG
  für Logos und Symbole), TLS über Schannel (HTTPS für die Update-Prüfung, seit 2.7.2).
* QML-Module: ``QML_MODULES`` – ermittelt mit ``qmlimportscanner``; von Qt Quick Controls nur der
  Stil »Basic«, den die App fest einstellt.
* DLLs: alle, die diese Dateien laut Importtabelle (auch verzögert geladen) brauchen – transitiv.
  Nicht benötigte Qt-DLLs (auch der 20-MB-Software-OpenGL-Ersatz ``opengl32sw.dll``: Qt Quick
  zeichnet unter Windows mit Direct3D 11, ohne Grafikkarte über WARP) entfallen.

``python qtruntime.py <site-packages>`` zeigt, was bliebe (ohne etwas zu löschen).
"""

from __future__ import annotations

import shutil
import struct
import sys
from pathlib import Path

PYTHON_MODULES = ("QtCore", "QtGui", "QtWidgets", "QtNetwork", "QtOpenGL", "QtQml", "QtQuick", "QtQuickControls2", "QtSvg", "QtPrintSupport")
PLUGINS = (
    "platforms/qwindows.dll",
    "platforms/qoffscreen.dll",  # Prüfungen ohne Bildschirm (Laufzeittest)
    "imageformats/qico.dll",
    "imageformats/qjpeg.dll",
    "imageformats/qsvg.dll",
    "imageformats/qwebp.dll",
    "iconengines/qsvgicon.dll",
    "tls/qschannelbackend.dll",  # HTTPS für Updates (Zertifikate prüft Windows selbst)
)
# QML-Module (Ordner unter PySide6/qml); bei Qt Quick Controls nur Basic und die gemeinsamen Teile
QML_MODULES = (
    "QtQml",
    "QtQml/Models",
    "QtQml/WorkerScript",
    "QtQuick",
    "QtQuick/Controls",
    "QtQuick/Controls/Basic",
    "QtQuick/Controls/Basic/impl",
    "QtQuick/Controls/impl",
    "QtQuick/Layouts",
    "QtQuick/Shapes",
    "QtQuick/Templates",
    "QtQuick/Window",
)
QML_ROOT_FILES = ("builtins.qmltypes", "jsroot.qmltypes")
# Ordner des PySide6-Pakets, die zur Laufzeit nicht gebraucht werden
REMOVE_DIRS = ("doc", "glue", "include", "lib", "metatypes", "resources", "scripts", "translations", "typesystems", "examples")
# Diese Python-Dateien des Pakets bleiben (Rest von PySide6 sind .pyd/.dll)
KEEP_PY_DIRS = ("support",)


# --- Importtabellen (PE) ---------------------------------------------------------------------


def _sections(data: bytes, header: int, count: int) -> list[tuple[int, int, int, int]]:
    result = []
    for index in range(count):
        base = header + 40 * index
        virtual_size, virtual_address, raw_size, raw_pointer = struct.unpack_from("<IIII", data, base + 8)
        result.append((virtual_address, max(virtual_size, raw_size), raw_pointer, raw_size))
    return result


def _offset(rva: int, sections) -> int | None:
    for virtual_address, size, raw_pointer, _raw_size in sections:
        if virtual_address <= rva < virtual_address + size:
            return raw_pointer + (rva - virtual_address)
    return None


def _cstring(data: bytes, offset: int) -> str:
    end = data.index(b"\0", offset)
    return data[offset:end].decode("ascii", "replace")


def pe_imports(path: Path) -> list[str]:
    """Namen der DLLs, die eine Windows-Programmdatei (DLL/PYD/EXE) importiert – auch verzögert.
    Keine oder eine beschädigte PE-Datei: leere Liste."""
    data = Path(path).read_bytes()
    try:
        return _pe_imports(data)
    except (struct.error, ValueError, IndexError):
        return []


def _pe_imports(data: bytes) -> list[str]:
    if data[:2] != b"MZ":
        return []
    pe = struct.unpack_from("<I", data, 0x3C)[0]
    if data[pe : pe + 4] != b"PE\0\0":
        return []
    sections_count = struct.unpack_from("<H", data, pe + 6)[0]
    optional_size = struct.unpack_from("<H", data, pe + 20)[0]
    optional = pe + 24
    magic = struct.unpack_from("<H", data, optional)[0]
    directories = optional + (112 if magic == 0x20B else 96)
    sections = _sections(data, optional + optional_size, sections_count)
    names: list[str] = []
    # Normale Importe (Verzeichnis 1): IMAGE_IMPORT_DESCRIPTOR, 20 Byte, Name bei +12
    import_rva = struct.unpack_from("<I", data, directories + 8)[0]
    offset = _offset(import_rva, sections) if import_rva else None
    while offset is not None and offset + 20 <= len(data):
        entry = struct.unpack_from("<IIIII", data, offset)
        if not any(entry):
            break
        name_offset = _offset(entry[3], sections)
        if name_offset is not None:
            names.append(_cstring(data, name_offset))
        offset += 20
    # Verzögert geladene Importe (Verzeichnis 13): ImgDelayDescr, 32 Byte, Name bei +4
    delay_rva = struct.unpack_from("<I", data, directories + 13 * 8)[0]
    offset = _offset(delay_rva, sections) if delay_rva else None
    while offset is not None and offset + 32 <= len(data):
        attributes, name_rva = struct.unpack_from("<II", data, offset)
        if not name_rva:
            break
        if not attributes & 1:  # alte Form mit absoluten Adressen – bei 64 Bit nicht üblich
            break
        name_offset = _offset(name_rva, sections)
        if name_offset is not None:
            names.append(_cstring(data, name_offset))
        offset += 32
    return names


def dependency_closure(roots: list[Path], search: list[Path]) -> set[Path]:
    """Alle Dateien aus ``search``-Ordnern, die ``roots`` direkt oder indirekt importieren."""
    index: dict[str, Path] = {}
    for folder in search:
        for candidate in folder.glob("*.dll"):
            index.setdefault(candidate.name.lower(), candidate)
    needed: set[Path] = set()
    queue = [root for root in roots if root.is_file()]
    seen: set[Path] = set()
    while queue:
        current = queue.pop()
        if current in seen:
            continue
        seen.add(current)
        for name in pe_imports(current):
            dependency = index.get(name.lower())
            if dependency is not None and dependency not in needed:
                needed.add(dependency)
                queue.append(dependency)
    return needed


# --- Verschlanken -------------------------------------------------------------------------------


def _remove(path: Path) -> int:
    if path.is_dir():
        size = sum(p.stat().st_size for p in path.rglob("*") if p.is_file())
        shutil.rmtree(path)
        return size
    if path.exists():
        size = path.stat().st_size
        path.unlink()
        return size
    return 0


def _qml_keep(qml: Path) -> set[Path]:
    keep: set[Path] = {qml / name for name in QML_ROOT_FILES}
    for module in QML_MODULES:
        folder = qml / module
        if not folder.is_dir():
            raise FileNotFoundError(f"QML-Modul fehlt: {module}")
        for child in folder.iterdir():
            if child.is_file():
                keep.add(child)
    return keep


def plan(site: Path) -> tuple[set[Path], set[Path]]:
    """(bleibt, entfällt) – alle Dateien unter PySide6/ und shiboken6/."""
    pyside = site / "PySide6"
    shiboken = site / "shiboken6"
    if not (pyside / "QtCore.pyd").is_file():
        raise FileNotFoundError(f"PySide6 (Windows) nicht gefunden: {pyside}")
    keep: set[Path] = set()
    roots: list[Path] = []
    for module in PYTHON_MODULES:
        pyd = pyside / f"{module}.pyd"
        if not pyd.is_file():
            raise FileNotFoundError(f"PySide6-Modul fehlt: {pyd.name}")
        keep.add(pyd)
        roots.append(pyd)
    for plugin in PLUGINS:
        path = pyside / "plugins" / plugin
        if not path.is_file():
            raise FileNotFoundError(f"Qt-Plugin fehlt: {plugin}")
        keep.add(path)
        roots.append(path)
    qml_files = _qml_keep(pyside / "qml")
    keep |= qml_files
    roots += [path for path in qml_files if path.suffix == ".dll"]
    shiboken_pyd = shiboken / "Shiboken.pyd"
    keep.add(shiboken_pyd)
    roots.append(shiboken_pyd)
    keep |= dependency_closure(roots, [pyside, shiboken])
    # Python-Teile: Paketdateien der obersten Ebene und die Hilfsmodule
    keep |= {path for path in pyside.glob("*.py")}
    keep |= {path for path in shiboken.glob("*.py")}
    for folder in KEEP_PY_DIRS:
        keep |= {path for path in (pyside / folder).rglob("*.py")}
    everything = {path for base in (pyside, shiboken) for path in base.rglob("*") if path.is_file()}
    return keep, everything - keep


def trim(site: Path, log=print) -> tuple[int, int]:
    """Nicht benötigte Dateien von PySide6/shiboken6 entfernen. Gibt (behalten, entfernt) in Byte zurück."""
    keep, drop = plan(site)
    removed = 0
    for path in sorted(drop):
        removed += _remove(path)
    pyside = site / "PySide6"
    for name in REMOVE_DIRS:
        removed += _remove(pyside / name)
    # leere Ordner aufräumen
    for folder in sorted((p for base in (pyside, site / "shiboken6") for p in base.rglob("*") if p.is_dir()), key=lambda p: len(p.parts), reverse=True):
        try:
            folder.rmdir()
        except OSError:
            pass
    kept = sum(path.stat().st_size for path in keep if path.exists())
    log(f"PySide6: {kept / 1e6:.1f} MB behalten, {removed / 1e6:.1f} MB entfernt")
    return kept, removed


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    keep, drop = plan(Path(sys.argv[1]))
    base = Path(sys.argv[1])
    for path in sorted(keep):
        print(f"{path.stat().st_size / 1e6:8.2f}  {path.relative_to(base)}")
    print(f"behalten: {sum(p.stat().st_size for p in keep) / 1e6:.1f} MB, entfällt: {sum(p.stat().st_size for p in drop) / 1e6:.1f} MB")
