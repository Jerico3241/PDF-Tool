"""Baut die Windows-Setup-Datei des Übersichten-Erstellers mit Inno Setup.

    python windows-app/build.py

Ablauf:
 1. alte Build-Dateien bereinigen (build/, dist/)
 2. Version aus windows-app/VERSION lesen und prüfen
 3. Windows-Python (python.org, inkl. tkinter/Tcl/Tk) laden und prüfen
 4. Python-Pakete aus runtime-requirements.txt laden (win_amd64, mit Prüfsummen)
 5. Laufzeit verschlanken und vorkompilieren, App und Assets kopieren
 6. Assistentenbilder aus assets/icon.ico erzeugen
 7. Inno Setup (ISCC.exe) aufrufen
 8. Setup prüfen, SHA-256 schreiben, optional signieren

Ergebnis:  windows-app/dist/Uebersichten-Ersteller-Setup-<Version>.exe (+ .sha256)

Voraussetzungen (Windows):
  * Python 3.13 (64 Bit) mit pip und Pillow – dieselbe Hauptversion wie die
    mitgelieferte Laufzeit, damit vorkompilierte .pyc-Dateien passen
  * Inno Setup 6.6 oder neuer (https://jrsoftware.org/isdl.php)
  * Internetzugang (python.org, PyPI)

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
import re
import shlex
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
APP = ROOT / "app"
ASSETS = ROOT / "assets"
ISS = ROOT / "installer" / "Uebersichten-Ersteller.iss"
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

# Was die App zur Laufzeit nicht braucht
RUNTIME_REMOVE = [
    "include", "libs", "Scripts", "Doc", "Tools", "__install__.json",
    "Lib/test", "Lib/idlelib", "Lib/turtledemo", "Lib/ensurepip", "Lib/venv",
    "Lib/pydoc_data", "Lib/turtle.py", "tcl/tk8.6/demos",
]
RUNTIME_REMOVE_GLOBS = [
    "DLLs/_test*.pyd", "DLLs/_ctypes_test.pyd", "DLLs/xxlimited*.pyd", "**/*.pdb",
    "tcl/*.lib", "tcl/*.sh", "Lib/site-packages/pip", "Lib/site-packages/pip-*",
]
SITE_REMOVE_DIRS = {"tests"}  # pandas/tests, numpy/_core/tests …
SITE_REMOVE_SUFFIXES = {".pyi", ".pxd", ".pyx", ".c", ".h", ".cpp", ".lib", ".a"}

# Diese Dateien müssen im fertigen Paket liegen
REQUIRED_PAYLOAD = [
    "VERSION",
    "README.txt",
    "runtime/pythonw.exe",
    "runtime/python313.dll",
    "runtime/DLLs/_tkinter.pyd",
    "runtime/DLLs/tcl86t.dll",
    "runtime/DLLs/tk86t.dll",
    "runtime/tcl/tcl8.6/init.tcl",
    "runtime/tcl/tk8.6/tk.tcl",
    "runtime/Lib/site-packages/pandas/__init__.py",
    "runtime/Lib/site-packages/numpy/__init__.py",
    "runtime/Lib/site-packages/openpyxl/__init__.py",
    "runtime/Lib/site-packages/xlrd/__init__.py",
    "runtime/Lib/site-packages/reportlab/__init__.py",
    "runtime/Lib/site-packages/PIL/__init__.py",
    "app/start.py",
    "app/vertragdesk.py",
    "app/engine.py",
    "app/appstate.py",
    "app/excelstyle.py",
    "app/richtext.py",
    "app/pdffonts.py",
    "app/ui/navigation.py",
    "app/ui/richtext.py",
    "assets/icon.ico",
    "assets/hott_logo_final.png",
]


def log(text: str) -> None:
    print(text, flush=True)


def fail(text: str) -> None:
    raise SystemExit(f"FEHLER: {text}")


# --- Version -----------------------------------------------------------------------


def read_version() -> str:
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        fail(f"VERSION hat kein gültiges Format (x.y.z): {version!r}")
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
    if sha256(dest) != expected:
        dest.unlink()
        fail(f"Prüfsumme stimmt nicht: {dest.name}")
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

    shutil.copytree(APP, PAYLOAD / "app", ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"))
    shutil.copytree(ASSETS, PAYLOAD / "assets")
    shutil.copy2(ROOT / "README.txt", PAYLOAD / "README.txt")
    (PAYLOAD / "VERSION").write_text(version + "\n", encoding="utf-8")

    if compile_pyc:
        python = python_for_runtime()
        if python:
            log(f"Kompiliere .pyc mit {' '.join(python)} …")
            compile_tree(python, runtime / "Lib", "unchecked-hash")  # wird nie verändert
            compile_tree(python, PAYLOAD / "app", "checked-hash")  # bei Updates ersetzt
        else:
            log(f"Hinweis: kein Python {PYTHON_VERSION.rsplit('.', 1)[0]} gefunden – .pyc entstehen beim ersten Start.")

    missing = [rel for rel in REQUIRED_PAYLOAD if not (PAYLOAD / rel).is_file()]
    if missing:
        fail("Im Paket fehlen: " + ", ".join(missing))


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
        "PayloadDir": to_iscc_path(PAYLOAD, iscc),
        "OutputDir": to_iscc_path(DIST, iscc),
        "WizardDir": to_iscc_path(WIZARD, iscc),
    }
    cmd = iscc + ["/Q"] + [f"/D{key}={value}" for key, value in defines.items()] + [to_iscc_path(ISS, iscc)]
    log("Inno Setup: " + " ".join(cmd[-1:]))
    subprocess.check_call(cmd)
    return DIST / f"Uebersichten-Ersteller-Setup-{version}.exe"


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
    if found != version:
        fail(f"Dateiversion der Setup-Datei ist {found}, erwartet {version}")
    if setup.name != f"Uebersichten-Ersteller-Setup-{version}.exe":
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
    parser = argparse.ArgumentParser(description="Baut Uebersichten-Ersteller-Setup-<Version>.exe mit Inno Setup.")
    parser.add_argument("--no-compile", action="store_true", help="keine .pyc-Dateien vorkompilieren")
    parser.add_argument("--reuse-payload", action="store_true", help="vorhandenes build/payload wiederverwenden (nur Installer neu bauen)")
    args = parser.parse_args()

    version = read_version()
    log(f"Übersichten-Ersteller {version}")
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
    (setup.parent / (setup.name + ".sha256")).write_text(f"{checksum}  {setup.name}\n", encoding="utf-8")
    log(f"Fertig: {setup} ({setup.stat().st_size / 1e6:.1f} MB)")
    log(f"SHA-256: {checksum}")


if __name__ == "__main__":
    main()
