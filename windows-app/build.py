"""Baut die Windows-Setup-Datei von PDF Tool mit Inno Setup.

    python windows-app/build.py

Ablauf:
 1. alte Build-Dateien bereinigen (build/, dist/)
 2. Version aus windows-app/VERSION lesen und prüfen (``X.Y.Z`` oder Beta ``X.Y.Z-beta.N``)
 3. Windows-Python (python.org) laden und prüfen
 4. Python-Pakete aus runtime-requirements.txt laden (win_amd64, mit Prüfsummen),
    darunter PySide6-Essentials (Qt 6, Qt Quick) in exakt gepinnter Version
 5. Laufzeit verschlanken (ohne tkinter/Tcl/Tk; von PySide6 nur die benötigten Module,
    Plugins und QML-Module – siehe qtruntime.py) und vorkompilieren
 6. App und Assets kopieren; die QML-Oberfläche als Qt-Ressource bündeln (app/qml_rc.py,
    siehe qmlres.py) – lose QML-Dateien kommen nicht ins Setup; Texterkennung (Tesseract) nach
    ocr\\ übernehmen – nur tesseract.exe und die DLLs, die es laut Importtabellen lädt, dazu die
    Sprachdaten (``prepare_ocr``)
 7. Assistentenbilder aus assets/icon.ico erzeugen
 8. Inno Setup (ISCC.exe) aufrufen
 9. Setup prüfen, SHA-256 schreiben, optional signieren; Release-Dateien prüfen
    (``release_check.py``: Namen, Version, Prüfsumme gehört exakt zum Setup)

Ergebnis:  windows-app/dist/PDF-Tool-Setup-<Version>.exe (+ .sha256), z. B.
           PDF-Tool-Setup-2.7.2.exe bzw. PDF-Tool-Setup-2.8.0-beta.1.exe

Voraussetzungen (Windows):
  * Python 3.13 (64 Bit) mit pip, Pillow und PySide6-Essentials (gleiche Version wie in
    runtime-requirements.txt; liefert rcc für die QML-Ressourcen) – dieselbe Hauptversion
    wie die mitgelieferte Laufzeit, damit vorkompilierte .pyc-Dateien passen
  * Inno Setup 6.6 oder neuer (https://jrsoftware.org/isdl.php)
  * 7-Zip (7z.exe) zum Entpacken des Tesseract-Installers – auf den Windows-Rechnern von GitHub
    vorinstalliert; sonst Umgebungsvariable SEVENZIP auf 7z.exe setzen
  * Internetzugang (python.org, PyPI, GitHub)

ISCC.exe wird automatisch gesucht (PATH, Umgebungsvariable ISCC,
"C:\\Program Files (x86)\\Inno Setup 6", "C:\\Program Files\\Inno Setup 6",
"%LOCALAPPDATA%\\Programs\\Inno Setup 6"). Unter Linux/macOS kann ISCC über
Wine laufen: ISCC=/pfad/zu/ISCC.exe setzen.

Signieren (sobald ein Code-Signing-Zertifikat vorhanden ist): Umgebungsvariable
SIGN_COMMAND setzen, z. B.
  SIGN_COMMAND=signtool sign /fd sha256 /tr http://timestamp.digicert.com /td sha256 /a "{file}"
Der Befehl wird nach dem Bau auf die Setup-Datei angewendet.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shlex
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import qmlres  # noqa: E402 - QML-Oberfläche als Qt-Ressource
import qtruntime  # noqa: E402 - PySide6 verschlanken
import release_check  # noqa: E402 - Versionsformat und Prüfung der Release-Dateien

ROOT = Path(__file__).resolve().parent
APP = ROOT / "app"
ASSETS = ROOT / "assets"
ISS = ROOT / "installer" / "PDF-Tool.iss"
SETUP_PREFIX = "PDF-Tool-Setup"
CACHE = ROOT / ".cache"
BUILD = ROOT / "build"
DIST = ROOT / "dist"
PAYLOAD = BUILD / "payload"
WIZARD = BUILD / "wizard"

PYTHON_VERSION = "3.13.15"
PYTHON_ZIP = f"python-{PYTHON_VERSION}-amd64.zip"
PYTHON_URL = f"https://www.python.org/ftp/python/{PYTHON_VERSION}/{PYTHON_ZIP}"
PYTHON_SHA256 = "6479223746cdfb79d25865110d6f524ac98de081324e119af1dc3ae36bddc7a5"
REQUIREMENTS = ROOT / "runtime-requirements.txt"

# Texterkennung (OCR): Tesseract für Windows (64 Bit), gebaut von der UB Mannheim und im Release 5.5.3 von
# tesseract-ocr veröffentlicht (NSIS-Installer, signiert). Entpackt mit 7-Zip; ins Setup kommen nur
# tesseract.exe und die DLLs, die es laut Importtabellen braucht (``qtruntime.dependency_closure``) – keine
# Trainingswerkzeuge, kein ICU/Pango/Cairo, keine NSIS-Plugins.
TESSERACT_VERSION = "5.5.3.20260724"
TESSERACT_SETUP = f"tesseract-ocr-w64-setup-{TESSERACT_VERSION}.exe"
TESSERACT_URL = f"https://github.com/tesseract-ocr/tesseract/releases/download/5.5.3/{TESSERACT_SETUP}"
TESSERACT_SHA256 = "bee9e3434bd94fd65387d9be28cd467a41f61b1275383b55b0f59a1331270ae4"
# Die DLLs, die tesseract.exe direkt oder indirekt lädt (geprüft mit ``objdump -p`` und
# ``qtruntime.pe_imports``). Weicht die berechnete Liste ab, bricht der Build ab: Liste und
# THIRD_PARTY_LICENSES.md gehören dann gemeinsam angepasst.
TESSERACT_DLLS = (
    "libLerc.dll", "libarchive-13.dll", "libb2-1.dll", "libbrotlicommon.dll", "libbrotlidec.dll",
    "libbz2-1.dll", "libcurl-4.dll", "libdeflate.dll", "libexpat-1.dll", "libgcc_s_seh-1.dll",
    "libgif-7.dll", "libiconv-2.dll", "libidn2-0.dll", "libintl-8.dll", "libjbig-0.dll", "libjpeg-8.dll",
    "libleptonica-6.dll", "liblz4.dll", "liblzma-5.dll", "libopenjp2-7.dll", "libpng16-16.dll",
    "libpsl-5.dll", "libsharpyuv-0.dll", "libssh2-1.dll", "libstdc++-6.dll", "libtesseract-5.dll",
    "libtiff-6.dll", "libunistring-5.dll", "libwebp-7.dll", "libwebpmux-3.dll", "libwinpthread-1.dll",
    "libzstd.dll", "zlib1.dll",
)
# Sprachdaten: tessdata_fast (Integer-LSTM, Apache-2.0) – Deutsch 1,5 MB und Englisch 4,1 MB statt
# 8,6/15,4 MB (tessdata_best) bzw. 15,4/23,5 MB (tessdata). tessdata_best ist laut Projekt bei schwierigen
# Vorlagen genauer, aber größer und langsamer; für gedruckte Dokumente reicht tessdata_fast. Dieselben
# Dateien (gleiche SHA-256) liefert z. B. Ubuntu 24.04 aus. osd: Lageerkennung (quer gescannte Seiten).
TESSDATA_COMMIT = "87416418657359cb625c412a48b6e1d6d41c29bd"  # tesseract-ocr/tessdata_fast, main
TESSDATA_URL = f"https://raw.githubusercontent.com/tesseract-ocr/tessdata_fast/{TESSDATA_COMMIT}/{{name}}"
TESSDATA = {
    "deu.traineddata": "19d219bbb6672c869d20a9636c6816a81eb9a71796cb93ebe0cb1530e2cdb22d",
    "eng.traineddata": "7d4322bd2a7749724879683fc3912cb542f19906c83bcc1a52132556427170b2",
    "osd.traineddata": "9cf5d576fcc47564f11265841e5ca839001e7e6f38ff7f7aacf46d15a96b00ff",
}
OCR = PAYLOAD / "ocr"  # passt zu tools/pdf_editor/ocr.py (BUNDLED_DIR)

# KI-Assistent (optional, ab 3.2): llama.cpp (MIT, ggml-org) – das offizielle Paket für Windows auf dem Prozessor
# (x64, alle CPU-Varianten). Ins Setup kommen nur llama-server.exe, die DLLs aus seinen Importtabellen und die
# Rechenwerke ggml-cpu-*.dll (llama-server wählt je nach Prozessor selbst eines) – keine weiteren Programme, kein
# RPC- oder GPU-Backend. Die Lizenztexte aller eingebauten Bestandteile (llama.cpp, cpp-httplib, BoringSSL, LLVM
# OpenMP, nlohmann/json) gibt das Paket selbst aus (``llama.exe licenses``); sie kommen nach ai\LICENSES.txt.
# Sprachmodelle gehören nicht ins Setup – sie werden nur auf Wunsch geladen (assistant/catalog.py).
LLAMA_RELEASE = "b11476"  # ggml-org/llama.cpp, Commit 988190680d5a89fce97de3c20df2c2813731fd61
LLAMA_ZIP = f"llama-{LLAMA_RELEASE}-bin-win-cpu-x64.zip"
LLAMA_URL = f"https://github.com/ggml-org/llama.cpp/releases/download/{LLAMA_RELEASE}/{LLAMA_ZIP}"
LLAMA_SHA256 = ""
LLAMA_BACKENDS = "ggml-cpu-*.dll"  # lädt llama-server zur Laufzeit (nicht in den Importtabellen)
AI = PAYLOAD / "ai"  # passt zu assistant/runtime.py (BUNDLED_DIR)

# Was die App zur Laufzeit nicht braucht – seit 2.7.0 auch kein tkinter/Tcl/Tk mehr (Qt-Oberfläche)
RUNTIME_REMOVE = [
    "include", "libs", "Scripts", "Doc", "Tools", "__install__.json",
    "Lib/test", "Lib/idlelib", "Lib/turtledemo", "Lib/ensurepip", "Lib/venv",
    "Lib/pydoc_data", "Lib/turtle.py", "Lib/tkinter", "tcl",
    "DLLs/_tkinter.pyd", "DLLs/tcl86t.dll", "DLLs/tk86t.dll",
]
RUNTIME_REMOVE_GLOBS = [
    "DLLs/_test*.pyd", "DLLs/_ctypes_test.pyd", "DLLs/xxlimited*.pyd", "**/*.pdb",
    "Lib/site-packages/pip", "Lib/site-packages/pip-*",
]
# Im Setup verboten: die frühere Tk-Oberfläche
FORBIDDEN_PAYLOAD = [
    "runtime/DLLs/_tkinter.pyd", "runtime/DLLs/tcl86t.dll", "runtime/DLLs/tk86t.dll", "runtime/tcl",
    "runtime/Lib/tkinter", "app/vertragdesk.py", "app/ui", "app/qml",
]
SITE_REMOVE_DIRS = {"tests"}  # pandas/tests, numpy/_core/tests …
SITE_REMOVE_SUFFIXES = {".pyi", ".pxd", ".pyx", ".c", ".h", ".cpp", ".lib", ".a"}

# Diese Dateien müssen im fertigen Paket liegen
REQUIRED_PAYLOAD = [
    "VERSION",
    "README.txt",
    "THIRD_PARTY_LICENSES.md",
    "LICENSE",
    "runtime/pythonw.exe",
    "runtime/python313.dll",
    "runtime/Lib/site-packages/pandas/__init__.py",
    "runtime/Lib/site-packages/numpy/__init__.py",
    "runtime/Lib/site-packages/openpyxl/__init__.py",
    "runtime/Lib/site-packages/xlrd/__init__.py",
    "runtime/Lib/site-packages/reportlab/__init__.py",
    "runtime/Lib/site-packages/PIL/__init__.py",
    "runtime/Lib/site-packages/pikepdf/__init__.py",
    "runtime/Lib/site-packages/packaging/__init__.py",
    "runtime/Lib/site-packages/pypdfium2/__init__.py",
    "runtime/Lib/site-packages/pypdf/__init__.py",
    "runtime/Lib/site-packages/pypdfium2_raw/pdfium.dll",
    "runtime/Lib/site-packages/shiboken6/__init__.py",
    "runtime/Lib/site-packages/shiboken6/Shiboken.pyd",
    "runtime/Lib/site-packages/PySide6/__init__.py",
    "runtime/Lib/site-packages/PySide6/QtCore.pyd",
    "runtime/Lib/site-packages/PySide6/QtGui.pyd",
    "runtime/Lib/site-packages/PySide6/QtWidgets.pyd",
    "runtime/Lib/site-packages/PySide6/QtQml.pyd",
    "runtime/Lib/site-packages/PySide6/QtQuick.pyd",
    "runtime/Lib/site-packages/PySide6/QtQuickControls2.pyd",
    "runtime/Lib/site-packages/PySide6/QtSvg.pyd",
    "runtime/Lib/site-packages/PySide6/QtNetwork.pyd",
    "runtime/Lib/site-packages/PySide6/plugins/tls/qschannelbackend.dll",
    "runtime/Lib/site-packages/PySide6/Qt6Core.dll",
    "runtime/Lib/site-packages/PySide6/Qt6Quick.dll",
    "runtime/Lib/site-packages/PySide6/Qt6QuickControls2Basic.dll",
    "runtime/Lib/site-packages/PySide6/plugins/platforms/qwindows.dll",
    "runtime/Lib/site-packages/PySide6/plugins/imageformats/qico.dll",
    "runtime/Lib/site-packages/PySide6/qml/QtQuick/qmldir",
    "runtime/Lib/site-packages/PySide6/qml/QtQuick/Controls/Basic/qmldir",
    "runtime/Lib/site-packages/PySide6/qml/QtQuick/Templates/qmldir",
    "runtime/Lib/site-packages/PySide6/qml/QtQuick/Layouts/qmldir",
    "runtime/Lib/site-packages/PySide6/qml/QtQuick/Shapes/qmldir",
    "app/start.py",
    "app/qml_rc.py",
    "app/engine.py",
    "app/appstate.py",
    "app/excelstyle.py",
    "app/richtext.py",
    "app/pdffonts.py",
    "app/design.py",
    "app/mica.py",
    "app/winsys.py",
    "app/qtapp/application.py",
    "app/qtapp/app.py",
    "app/qtapp/repair.py",
    "app/qtapp/settings.py",
    "app/qtapp/theme.py",
    "app/qtapp/contracts/overview.py",
    "app/qtapp/contracts/richtext.py",
    "app/qtapp/contracts/customers.py",
    "app/qtapp/contracts/preview.py",
    "app/qtapp/contracts/batch.py",
    "app/qtapp/contracts/comparison.py",
    "app/qtapp/contracts/tool.py",
    "app/qtapp/updates.py",
    "app/updater/__init__.py",
    "app/updater/semver.py",
    "app/updater/models.py",
    "app/updater/policy.py",
    "app/updater/github.py",
    "app/updater/verifier.py",
    "app/updater/state.py",
    "app/updater/schedule.py",
    "app/updater/store.py",
    "app/updater/notes.py",
    "app/updater/transport.py",
    "app/updater/service.py",
    "app/updater/installer.py",
    "app/updater/launch.py",
    "app/tools/__init__.py",
    "app/tools/registry.py",
    "app/tools/contract_overview/preview.py",
    "app/tools/contract_overview/overview.py",
    "app/tools/contract_overview/batch/__init__.py",
    "app/tools/contract_overview/batch/models.py",
    "app/tools/contract_overview/batch/analyzer.py",
    "app/tools/contract_overview/batch/resolver.py",
    "app/tools/contract_overview/batch/processor.py",
    "app/tools/contract_overview/history/__init__.py",
    "app/tools/contract_overview/history/models.py",
    "app/tools/contract_overview/history/compare.py",
    "app/tools/contract_overview/history/repository.py",
    "app/tools/contract_overview/history/report.py",
    "app/tools/contract_overview/customers/models.py",
    "app/tools/contract_overview/customers/matching.py",
    "app/tools/contract_overview/customers/repository.py",
    "app/tools/contract_overview/customers/migration.py",
    "app/tools/contract_overview/customers/texts.py",
    "app/tools/pdf_repair/models.py",
    "app/tools/pdf_repair/engine.py",
    "app/tools/pdf_repair/process.py",
    "app/tools/pdf_repair/presentation.py",
    "app/tools/pdf_repair/recovery/__init__.py",
    "app/tools/pdf_repair/recovery/lenient.py",
    "app/tools/pdf_repair/recovery/scanner.py",
    "app/tools/pdf_repair/recovery/rebuild.py",
    "app/tools/pdf_editor/ocr.py",
    "assets/icon.ico",
    "assets/hott_logo_final.png",
    "ocr/tesseract.exe",
    "ocr/LICENSE.txt",
    "ocr/tessdata/pdf.ttf",
    "ocr/tessdata/deu.traineddata",
    "ocr/tessdata/eng.traineddata",
    "ocr/tessdata/osd.traineddata",
    "app/assistant/runtime.py",
    "app/qtapp/assistant.py",
    "ai/llama-server.exe",
    "ai/LICENSES.txt",
]
# Native Bibliotheken der PDF-Engines (Dateinamen enthalten eine Prüfsumme)
REQUIRED_NATIVE = [
    "runtime/Lib/site-packages/pikepdf/_core.cp313-win_amd64.pyd",
    "runtime/Lib/site-packages/pikepdf.libs/qpdf*.dll",
    "runtime/Lib/site-packages/pikepdf.libs/msvcp140*.dll",
]


def log(text: str) -> None:
    print(text, flush=True)


def fail(text: str) -> None:
    if os.environ.get("GITHUB_ACTIONS") == "true":  # in der CI auch als Fehlermeldung am Lauf
        print("::error title=build.py::" + text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A"), flush=True)
    raise SystemExit(f"FEHLER: {text}")


# --- Version -----------------------------------------------------------------------


def read_version() -> str:
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    if not release_check.valid_version(version):
        fail(f"VERSION hat kein gültiges Format (X.Y.Z oder X.Y.Z-beta.N): {version!r}")
    return version


# --- Downloads ------------------------------------------------------------------------


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def download(url: str, dest: Path, expected: str) -> Path:
    if dest.is_file() and sha256(dest) == expected:
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    log(f"Lade {url}")
    part = dest.with_suffix(dest.suffix + ".part")
    with urllib.request.urlopen(url) as response, part.open("wb") as out:
        shutil.copyfileobj(response, out)
    part.replace(dest)
    actual = sha256(dest)
    if actual != expected:
        dest.unlink()
        fail(f"Prüfsumme stimmt nicht: {dest.name} – erwartet {expected or '(keine eingetragen)'}, geladen {actual}")
    return dest


def requirement_pins() -> list[tuple[str, str]]:
    pins = []
    for line in REQUIREMENTS.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        name, _, rest = line.partition("==")
        pins.append((name.strip(), rest.split()[0]))
    return pins


def fetch_wheels() -> list[Path]:
    target = CACHE / "wheels"
    target.mkdir(parents=True, exist_ok=True)
    subprocess.check_call(
        [
            sys.executable, "-m", "pip", "download", "--quiet", "--disable-pip-version-check",
            "--require-hashes", "--no-deps", "--only-binary=:all:",
            "--platform", "win_amd64",
            "--python-version", ".".join(PYTHON_VERSION.split(".")[:2]),
            "--implementation", "cp",
            "-r", str(REQUIREMENTS), "-d", str(target),
        ]
    )
    wheels = []
    for name, version in requirement_pins():
        stem = name.lower().replace("-", "_")
        found = sorted(target.glob(f"{stem}-{version}-*.whl"))
        if not found:
            fail(f"Wheel fehlt: {name} {version}")
        wheels.append(found[-1])
    return wheels


# --- Laufzeit ----------------------------------------------------------------------------


def remove(path: Path) -> None:
    if path.is_dir():
        shutil.rmtree(path)
    elif path.exists():
        path.unlink()


def install_wheel(wheel: Path, site: Path) -> None:
    with zipfile.ZipFile(wheel) as archive:
        for member in archive.infolist():
            name = member.filename
            if ".data/" in name:
                _prefix, _, rest = name.partition(".data/")
                kind, _, inner = rest.partition("/")
                if kind not in ("purelib", "platlib") or not inner:
                    continue  # Skripte und Header werden nicht gebraucht
                name = inner
            target = site / name
            if member.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(member) as src, target.open("wb") as dst:
                shutil.copyfileobj(src, dst)


def trim_runtime(runtime: Path) -> None:
    for rel in RUNTIME_REMOVE:
        remove(runtime / rel)
    for pattern in RUNTIME_REMOVE_GLOBS:
        for path in list(runtime.glob(pattern)):
            remove(path)
    site = runtime / "Lib" / "site-packages"
    for path in sorted(site.rglob("*"), key=lambda p: len(p.parts), reverse=True):
        if not path.exists():
            continue
        if path.is_dir() and path.name in SITE_REMOVE_DIRS:
            remove(path)
        elif path.is_file() and path.suffix in SITE_REMOVE_SUFFIXES:
            remove(path)
    for cache in list(runtime.rglob("__pycache__")):
        remove(cache)


def python_for_runtime() -> list[str] | None:
    """Ein Python mit derselben Hauptversion wie die Laufzeit (für .pyc-Dateien)."""
    wanted = ".".join(PYTHON_VERSION.split(".")[:2])
    candidates = [sys.executable, shutil.which(f"python{wanted}"), shutil.which("py") and "py"]
    for candidate in candidates:
        if not candidate:
            continue
        cmd = [candidate, f"-{wanted}"] if candidate == "py" else [candidate]
        try:
            out = subprocess.check_output(cmd + ["-c", "import sys; print('%d.%d' % sys.version_info[:2])"], text=True).strip()
        except (OSError, subprocess.CalledProcessError):
            continue
        if out == wanted:
            return cmd
    return None


def compile_tree(python: list[str], path: Path, mode: str) -> None:
    cmd = python + ["-m", "compileall", "-q", "-j", "0", "-o", "2", "--invalidation-mode", mode, str(path)]
    subprocess.check_call(cmd)


# --- Texterkennung (Tesseract) ------------------------------------------------------------


def find_7zip() -> str:
    env = os.environ.get("SEVENZIP")
    candidates: list[str] = [env] if env else []
    candidates += [found for found in (shutil.which("7z"), shutil.which("7zz")) if found]
    for base in (os.environ.get("ProgramFiles"), os.environ.get("ProgramW6432"), os.environ.get("ProgramFiles(x86)")):
        if base:
            candidates.append(os.path.join(base, "7-Zip", "7z.exe"))
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return candidate
    fail(
        "7-Zip (7z.exe) wurde nicht gefunden – es entpackt den Tesseract-Installer.\n"
        "Bitte 7-Zip installieren (https://www.7-zip.org) oder die Umgebungsvariable SEVENZIP auf 7z.exe setzen."
    )
    return ""


def unpacked_file(folder: Path, name: str, source: str = "Tesseract-Installer") -> Path:
    """Genau eine Datei dieses Namens im entpackten Paket (NSIS-Plugins zählen nicht)."""
    found = [path for path in folder.rglob(name) if path.is_file() and "$PLUGINSDIR" not in path.parts]
    if len(found) != 1:
        fail(f"Im {source} {'fehlt' if not found else 'mehrfach'}: {name}")
    return found[0]


def prepare_ocr(target: Path) -> None:
    """Tesseract nach ``target`` (``ocr\\``): tesseract.exe, die DLLs aus seinen Importtabellen, die Lizenz
    (Apache-2.0, gilt auch für die Sprachdaten) und tessdata mit pdf.ttf (Schrift der Textebene) und den
    Sprachdaten. Original-Dateien, unverändert; alles mit SHA-256 geprüft."""
    setup = download(TESSERACT_URL, CACHE / TESSERACT_SETUP, TESSERACT_SHA256)
    unpacked = BUILD / "tesseract"
    remove(unpacked)
    log(f"Entpacke Tesseract {TESSERACT_VERSION} (7-Zip) …")
    subprocess.check_call([find_7zip(), "x", "-y", "-bso0", "-bsp0", f"-o{unpacked}", str(setup)])
    executable = unpacked_file(unpacked, "tesseract.exe")
    needed = qtruntime.dependency_closure([executable], [executable.parent])
    names = {path.name for path in needed}
    if names != set(TESSERACT_DLLS):
        fail(
            "Die DLLs von Tesseract weichen von TESSERACT_DLLS ab – Liste und THIRD_PARTY_LICENSES.md anpassen. "
            f"Neu: {', '.join(sorted(names - set(TESSERACT_DLLS))) or '-'}; entfallen: {', '.join(sorted(set(TESSERACT_DLLS) - names)) or '-'}"
        )
    (target / "tessdata").mkdir(parents=True)
    shutil.copy2(executable, target / executable.name)
    for path in sorted(needed):
        shutil.copy2(path, target / path.name)
    shutil.copy2(unpacked_file(unpacked, "LICENSE"), target / "LICENSE.txt")
    shutil.copy2(unpacked_file(unpacked, "pdf.ttf"), target / "tessdata" / "pdf.ttf")
    for name, digest in TESSDATA.items():
        shutil.copy2(download(TESSDATA_URL.format(name=name), CACHE / f"tessdata-{TESSDATA_COMMIT[:12]}" / name, digest), target / "tessdata" / name)
    size = sum(path.stat().st_size for path in target.rglob("*") if path.is_file())
    log(f"Texterkennung: tesseract.exe, {len(needed)} DLLs, Sprachdaten {', '.join(TESSDATA)} ({size / 1e6:.1f} MB)")
    remove(unpacked)


def prepare_ai(target: Path, search: list[Path]) -> None:
    """llama.cpp nach ``target`` (``ai\\``): llama-server.exe, die DLLs aus seinen Importtabellen (aus dem Paket, die
    Laufzeit von Microsoft Visual C++ notfalls aus ``search`` – dieselben Dateien wie die von Python und PySide6),
    alle Rechenwerke ``ggml-cpu-*.dll`` und die Lizenztexte. Original-Dateien, unverändert; das Paket mit SHA-256
    geprüft."""
    archive = download(LLAMA_URL, CACHE / LLAMA_ZIP, LLAMA_SHA256)
    unpacked = BUILD / "llama"
    remove(unpacked)
    log(f"Entpacke llama.cpp {LLAMA_RELEASE} …")
    with zipfile.ZipFile(archive) as bundle:
        bundle.extractall(unpacked)
    server = unpacked_file(unpacked, "llama-server.exe", "Paket von llama.cpp")
    folder = server.parent
    backends = sorted(folder.glob(LLAMA_BACKENDS))
    if not backends:
        fail(f"Im Paket von llama.cpp fehlen die Rechenwerke {LLAMA_BACKENDS}")
    needed = qtruntime.dependency_closure([server, *backends], [folder, *search])
    target.mkdir(parents=True)
    for path in [server, *backends, *sorted(needed)]:
        shutil.copy2(path, target / path.name)
    problems = release_check.check_ai(PAYLOAD)
    problems = [problem for problem in problems if "LICENSES.txt" not in problem]
    if problems:
        fail("KI-Laufzeit unvollständig: " + "; ".join(problems))
    # Lizenzen aller eingebauten Bestandteile – vom Programm des Pakets selbst ausgegeben
    app = folder / "llama.exe"
    if not app.is_file():
        fail("Im Paket von llama.cpp fehlt llama.exe (gibt die Lizenzen aus)")
    texts = subprocess.run([str(app), "licenses"], cwd=str(folder), capture_output=True, timeout=120, check=False)
    licenses = texts.stdout.decode("utf-8", "replace").replace("\r\n", "\n")
    if texts.returncode != 0 or "License for llama.cpp" not in licenses or "MIT License" not in licenses:
        fail(f"Die Lizenzen von llama.cpp ließen sich nicht ausgeben (Code {texts.returncode})")
    (target / "LICENSES.txt").write_text(licenses.strip() + "\n", encoding="utf-8")
    names = [line.removeprefix("License for ").strip() for line in licenses.splitlines() if line.startswith("License for ")]
    size = sum(path.stat().st_size for path in target.iterdir() if path.is_file())
    log(f"KI-Laufzeit: llama-server.exe, {len(backends)} Rechenwerke, {len(needed)} DLLs, Lizenzen: {', '.join(names)} ({size / 1e6:.1f} MB)")
    if os.environ.get("GITHUB_ACTIONS") == "true":  # Inhalt am Lauf vermerken (Abgleich mit THIRD_PARTY_LICENSES.md)
        files = ", ".join(f"{path.name} ({path.stat().st_size // 1024} KB)" for path in sorted(target.iterdir()))
        print(f"::notice title=KI-Laufzeit im Setup::{files} · Lizenzen: {', '.join(names)}", flush=True)
    remove(unpacked)


def prepare_payload(version: str, compile_pyc: bool) -> None:
    runtime = PAYLOAD / "runtime"
    runtime.mkdir(parents=True)
    python_zip = download(PYTHON_URL, CACHE / PYTHON_ZIP, PYTHON_SHA256)
    log(f"Entpacke Python {PYTHON_VERSION} …")
    with zipfile.ZipFile(python_zip) as archive:
        archive.extractall(runtime)
    log("Lade Pakete …")
    site = runtime / "Lib" / "site-packages"
    for wheel in fetch_wheels():
        log(f"  {wheel.name}")
        install_wheel(wheel, site)
    trim_runtime(runtime)
    qtruntime.trim(site, log)

    shutil.copytree(APP, PAYLOAD / "app", ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo", "qml_rc.py"))
    # QML-Oberfläche als Qt-Ressource (qrc:/qml/…) statt loser Dateien
    log("Bündle die QML-Oberfläche (rcc) …")
    try:
        qmlres.compile_resources(PAYLOAD / "app" / "qml_rc.py", APP / "qml")
    except (FileNotFoundError, ImportError) as exc:
        fail(f"QML-Ressourcen konnten nicht erzeugt werden ({exc}). PySide6-Essentials im Build-Python installieren.")
    remove(PAYLOAD / "app" / "qml")
    shutil.copytree(ASSETS, PAYLOAD / "assets")
    shutil.copy2(ROOT / "README.txt", PAYLOAD / "README.txt")
    shutil.copy2(ROOT.parent / "THIRD_PARTY_LICENSES.md", PAYLOAD / "THIRD_PARTY_LICENSES.md")
    shutil.copy2(ROOT.parent / "LICENSE", PAYLOAD / "LICENSE")  # GPL-3.0 von PDF Tool, ohne Zustimmungsseite im Setup
    (PAYLOAD / "VERSION").write_text(version + "\n", encoding="utf-8")
    prepare_ocr(OCR)
    prepare_ai(AI, [runtime, site / "PySide6"])

    if compile_pyc:
        python = python_for_runtime()
        if python:
            log(f"Kompiliere .pyc mit {' '.join(python)} …")
            compile_tree(python, runtime / "Lib", "unchecked-hash")  # wird nie verändert
            compile_tree(python, PAYLOAD / "app", "checked-hash")  # bei Updates ersetzt
        else:
            log(f"Hinweis: kein Python {PYTHON_VERSION.rsplit('.', 1)[0]} gefunden – .pyc entstehen beim ersten Start.")

    missing = [rel for rel in REQUIRED_PAYLOAD if not (PAYLOAD / rel).is_file()]
    missing += [pattern for pattern in REQUIRED_NATIVE if not any(path.is_file() for path in PAYLOAD.glob(pattern))]
    if missing:
        fail("Im Paket fehlen: " + ", ".join(missing))
    forbidden = [rel for rel in FORBIDDEN_PAYLOAD if (PAYLOAD / rel).exists()]
    if forbidden:
        fail("Im Paket darf nicht liegen: " + ", ".join(forbidden))
    problems = release_check.check_ocr(PAYLOAD)
    if problems:
        fail("Texterkennung im Paket unvollständig: " + "; ".join(problems))
    problems = release_check.check_ai(PAYLOAD)
    if problems:
        fail("KI-Laufzeit im Paket unvollständig: " + "; ".join(problems))


# --- Assistentenbilder -------------------------------------------------------------


def wizard_images() -> None:
    """App-Symbol für den Installationsassistenten in mehreren DPI-Stufen (transparent)."""
    try:
        from PIL import Image
    except ImportError:
        log("Hinweis: Pillow fehlt – Standardbilder von Inno Setup werden verwendet.")
        return
    WIZARD.mkdir(parents=True, exist_ok=True)
    icon = Image.open(ASSETS / "icon.ico")
    icon.size = max(icon.info.get("sizes", {(256, 256)}))
    icon = icon.convert("RGBA")
    for label, scale in (("100", 1.0), ("125", 1.25), ("150", 1.5), ("200", 2.0)):
        small = round(55 * scale)
        img = Image.new("RGBA", (small, small), (0, 0, 0, 0))
        inner = round(48 * scale)
        img.alpha_composite(icon.resize((inner, inner), Image.LANCZOS), ((small - inner) // 2, (small - inner) // 2))
        img.save(WIZARD / f"small-{label}.png")
        width, height = round(164 * scale), round(314 * scale)
        big = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        size = round(112 * scale)
        big.alpha_composite(icon.resize((size, size), Image.LANCZOS), ((width - size) // 2, round(72 * scale)))
        big.save(WIZARD / f"wizard-{label}.png")


# --- Inno Setup -------------------------------------------------------------------------


def find_iscc() -> list[str]:
    env = os.environ.get("ISCC")
    candidates: list[str] = [env] if env else []
    found = shutil.which("ISCC") or shutil.which("iscc")
    if found:
        candidates.append(found)
    for base in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles"), os.environ.get("LOCALAPPDATA") and os.path.join(os.environ["LOCALAPPDATA"], "Programs")):
        if base:
            candidates.append(os.path.join(base, "Inno Setup 6", "ISCC.exe"))
    candidates += [r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe", r"C:\Program Files\Inno Setup 6\ISCC.exe"]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            if sys.platform != "win32" and candidate.lower().endswith(".exe"):
                wine = shutil.which("wine")
                if not wine:
                    fail("ISCC.exe gefunden, aber Wine fehlt, um es unter diesem System auszuführen.")
                return [wine, candidate]
            return [candidate]
    fail(
        "Inno Setup 6 (ISCC.exe) wurde nicht gefunden.\n"
        "Bitte Inno Setup 6.6 oder neuer installieren (https://jrsoftware.org/isdl.php)\n"
        "oder die Umgebungsvariable ISCC auf ISCC.exe setzen."
    )
    return []


def to_iscc_path(path: Path, iscc: list[str]) -> str:
    if len(iscc) == 2:  # über Wine: Z:-Laufwerk
        return "Z:" + str(path.resolve()).replace("/", "\\")
    return str(path.resolve())


def run_iscc(iscc: list[str], version: str) -> Path:
    defines = {
        "AppVersion": version,
        "AppNumericVersion": release_check.numeric_version(version),
        "PayloadDir": to_iscc_path(PAYLOAD, iscc),
        "OutputDir": to_iscc_path(DIST, iscc),
        "WizardDir": to_iscc_path(WIZARD, iscc),
    }
    cmd = iscc + ["/Q"] + [f"/D{key}={value}" for key, value in defines.items()] + [to_iscc_path(ISS, iscc)]
    log("Inno Setup: " + " ".join(cmd[-1:]))
    subprocess.check_call(cmd)
    return DIST / f"{SETUP_PREFIX}-{version}.exe"


def validate(setup: Path, version: str) -> None:
    if not setup.is_file():
        fail(f"Setup-Datei fehlt: {setup}")
    size = setup.stat().st_size
    if size < 20 * 1024 * 1024:
        fail(f"Setup-Datei ist verdächtig klein ({size} Bytes)")
    data = setup.read_bytes()
    if not data.startswith(b"MZ"):
        fail("Setup-Datei ist keine Windows-Programmdatei")
    # VS_FIXEDFILEINFO: Signatur 0xFEEF04BD, danach Strukturversion und Dateiversion (MS, LS)
    index = data.find(b"\xbd\x04\xef\xfe")
    if index < 0:
        fail("Keine Versionsinformation in der Setup-Datei")
    ms = int.from_bytes(data[index + 8 : index + 12], "little")
    ls = int.from_bytes(data[index + 12 : index + 16], "little")
    found = f"{ms >> 16}.{ms & 0xFFFF}.{ls >> 16}"
    if found != release_check.numeric_version(version):
        fail(f"Dateiversion der Setup-Datei ist {found}, erwartet {release_check.numeric_version(version)}")
    if setup.name != f"{SETUP_PREFIX}-{version}.exe":
        fail(f"Unerwarteter Dateiname: {setup.name}")


def sign(setup: Path) -> None:
    command = os.environ.get("SIGN_COMMAND")
    if not command:
        log("Hinweis: nicht signiert (SIGN_COMMAND ist nicht gesetzt).")
        return
    args = [part.replace("{file}", str(setup)) for part in shlex.split(command, posix=(os.name != "nt"))]
    log("Signiere …")
    subprocess.check_call(args)


def main() -> None:
    parser = argparse.ArgumentParser(description="Baut PDF-Tool-Setup-<Version>.exe mit Inno Setup.")
    parser.add_argument("--no-compile", action="store_true", help="keine .pyc-Dateien vorkompilieren")
    parser.add_argument("--reuse-payload", action="store_true", help="vorhandenes build/payload wiederverwenden (nur Installer neu bauen)")
    args = parser.parse_args()

    version = read_version()
    log(f"PDF Tool {version}")
    iscc = find_iscc()
    remove(DIST)
    if not (args.reuse_payload and PAYLOAD.is_dir()):
        remove(BUILD)
        prepare_payload(version, not args.no_compile)
    else:
        (PAYLOAD / "VERSION").write_text(version + "\n", encoding="utf-8")
    wizard_images()
    DIST.mkdir(parents=True, exist_ok=True)
    setup = run_iscc(iscc, version)
    sign(setup)
    validate(setup, version)
    checksum = sha256(setup)
    # Format wie ``sha256sum``: <Hash><2 Leerzeichen><Dateiname><LF> – so liest es auch der Updater
    (setup.parent / (setup.name + ".sha256")).write_bytes(release_check.checksum_line(checksum, setup.name).encode("ascii"))
    problems = release_check.check(DIST, version)
    if problems:
        fail("Release-Dateien sind nicht in Ordnung: " + "; ".join(problems))
    log(f"Fertig: {setup} ({setup.stat().st_size / 1e6:.1f} MB)")
    log(f"SHA-256: {checksum}")


if __name__ == "__main__":
    main()
