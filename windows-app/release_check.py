"""Release-Dateien vor der Veröffentlichung prüfen – im Build (``build.py``) und im Release-Workflow.

    python windows-app/release_check.py windows-app/dist
    python windows-app/release_check.py dist --github-output "$GITHUB_OUTPUT"

Geprüft wird:

* ``windows-app/VERSION`` ist eine gültige Version – stabil ``X.Y.Z`` oder Beta ``X.Y.Z-beta.N``
  (Semantic Versioning, keine anderen Vorabkennungen)
* im Ordner liegen genau ``PDF-Tool-Setup-<Version>.exe`` und ``PDF-Tool-Setup-<Version>.exe.sha256``
* die Prüfsummendatei hat das Format von ``sha256sum``: ``<64 Hex-Zeichen><2 Leerzeichen><Dateiname>``
  und ein Zeilenende – und nennt genau dieses Setup
* die Prüfsumme gehört exakt zum Setup (SHA-256 neu berechnet)
* die Dateiversion im Setup ist ``X.Y.Z`` (ohne Vorabkennung – Windows kennt nur Zahlen)
* die Release Notes ``windows-app/release-notes/<Version>.md`` sind vorhanden
* im Paket, aus dem das Setup entsteht (``build/payload`` neben ``dist``, sofern vorhanden, oder
  ``--payload``), liegt die Texterkennung vollständig: ``ocr\\tesseract.exe`` (64 Bit), jede DLL, die es
  direkt oder indirekt lädt (außer denen von Windows), und die Sprachdaten ``deu``, ``eng``, ``osd``
  (``check_ocr`` – auch ``build.py`` ruft es auf)

Mit ``--github-output`` schreibt das Skript die Angaben für den Release-Schritt: ``version``,
``tag`` (``v<Version>``), ``title`` (``PDF Tool <Version>``), ``prerelease`` (``true`` für Beta),
``setup``, ``checksum`` und ``notes``. Ein Beta-Release wird damit immer als GitHub-Vorabversion
veröffentlicht, ein stabiles nie – eine Beta wird nie automatisch zu Stable.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "app"))
from updater.semver import Version  # noqa: E402 - dieselbe SemVer-Auswertung wie der Updater

SETUP_PREFIX = "PDF-Tool-Setup-"
_CHECKSUM = re.compile(r"^(?P<hash>[0-9a-f]{64})  (?P<name>[^\r\n]+)\r?\n$")
# Texterkennung im Paket (build.py, ``prepare_ocr``)
OCR_DIR = "ocr"
OCR_LANGUAGES = ("deu", "eng", "osd")
OCR_FILES = ("LICENSE.txt", "tessdata/pdf.ttf")
OCR_MIN_LANGUAGE_SIZE = 500_000  # kleinere Sprachdaten sind abgeschnitten (tessdata_fast: deu 1,5 MB)
# DLLs, die Windows selbst mitbringt (System32) – alle anderen, die tesseract.exe lädt, müssen in ocr\ liegen
WINDOWS_DLLS = frozenset({
    "advapi32.dll", "bcrypt.dll", "crypt32.dll", "dbghelp.dll", "gdi32.dll", "iphlpapi.dll", "kernel32.dll", "msvcrt.dll",
    "ntdll.dll", "ole32.dll", "oleaut32.dll", "psapi.dll", "rpcrt4.dll", "secur32.dll", "shell32.dll", "shlwapi.dll",
    "ucrtbase.dll", "user32.dll", "userenv.dll", "version.dll", "winmm.dll", "wldap32.dll", "ws2_32.dll",
})
PE_MACHINE_X64 = 0x8664
AI_DIR = "ai"  # KI-Assistent: llama.cpp (assistant/runtime.py)
AI_SERVER = "llama-server.exe"
AI_BACKENDS = "ggml-cpu-*.dll"  # Rechenwerke, die llama-server zur Laufzeit lädt


def parse(version: str) -> Version | None:
    try:
        parsed = Version.parse(version)
    except ValueError:
        return None
    if parsed.build or str(parsed) != version.strip():
        return None
    if parsed.prerelease and not (len(parsed.prerelease) == 2 and parsed.prerelease[0] == "beta" and parsed.prerelease[1].isdigit() and int(parsed.prerelease[1]) >= 1):
        return None
    return parsed


def valid_version(version: str) -> bool:
    """``2.7.2`` oder ``2.8.0-beta.1`` – sonst nichts (auch kein ``-rc1``, kein ``+build``)."""
    return parse(version) is not None


def is_beta(version: str) -> bool:
    parsed = parse(version)
    return parsed is not None and parsed.is_prerelease


def numeric_version(version: str) -> str:
    """Zahlenteil für die Windows-Dateiversion: ``2.8.0-beta.1`` → ``2.8.0``."""
    parsed = parse(version)
    if parsed is None:
        raise ValueError(f"Ungültige Version: {version!r}")
    return ".".join(str(part) for part in parsed.core)


def checksum_line(digest: str, name: str) -> str:
    return f"{digest.lower()}  {name}\n"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def pe_file_version(path: Path) -> str | None:
    """Dateiversion (``X.Y.Z``) aus der Versionsressource einer Windows-Programmdatei."""
    data = Path(path).read_bytes()
    if not data.startswith(b"MZ"):
        return None
    index = data.find(b"\xbd\x04\xef\xfe")  # VS_FIXEDFILEINFO
    if index < 0:
        return None
    ms = int.from_bytes(data[index + 8 : index + 12], "little")
    ls = int.from_bytes(data[index + 12 : index + 16], "little")
    return f"{ms >> 16}.{ms & 0xFFFF}.{ls >> 16}"


def check(dist: Path, version: str, notes_dir: Path | None = None, min_size: int = 20 * 1024 * 1024) -> list[str]:
    """Probleme der Release-Dateien in ``dist`` (leer = in Ordnung)."""
    problems: list[str] = []
    if not valid_version(version):
        return [f"VERSION ist ungültig: {version!r} (erlaubt: X.Y.Z oder X.Y.Z-beta.N)"]
    dist = Path(dist)
    name = f"{SETUP_PREFIX}{version}.exe"
    setup = dist / name
    checksum = dist / (name + ".sha256")
    found = sorted(path.name for path in dist.glob(f"{SETUP_PREFIX}*")) if dist.is_dir() else []
    unexpected = [item for item in found if item not in (name, checksum.name)]
    if unexpected:
        problems.append("Unerwartete Dateien: " + ", ".join(unexpected))
    if not setup.is_file():
        return problems + [f"Setup fehlt: {name}"]
    if not checksum.is_file():
        return problems + [f"Prüfsummendatei fehlt: {checksum.name}"]
    if setup.stat().st_size < min_size:
        problems.append(f"Setup ist verdächtig klein ({setup.stat().st_size} Bytes)")
    file_version = pe_file_version(setup)
    if file_version != numeric_version(version):
        problems.append(f"Dateiversion des Setups ist {file_version}, erwartet {numeric_version(version)}")
    try:
        text = checksum.read_bytes().decode("ascii")
    except UnicodeDecodeError:
        text = ""
    match = _CHECKSUM.match(text)
    if match is None:
        problems.append("Prüfsummendatei hat nicht das Format »<SHA-256>  <Dateiname>« mit Zeilenende")
    else:
        if match.group("name") != name:
            problems.append(f"Prüfsummendatei nennt {match.group('name')!r} statt {name!r}")
        if match.group("hash") != sha256(setup):
            problems.append("Prüfsumme gehört nicht zum Setup")
    notes = (notes_dir or HERE / "release-notes") / f"{version}.md"
    if not notes.is_file():
        problems.append(f"Release Notes fehlen: release-notes/{version}.md")
    return problems


def pe_machine(path: Path) -> int | None:
    """Zielprozessor einer Windows-Programmdatei (``0x8664`` = 64 Bit) oder ``None``."""
    with open(path, "rb") as handle:
        head = handle.read(4096)
    if head[:2] != b"MZ" or len(head) < 0x40:
        return None
    offset = int.from_bytes(head[0x3C:0x40], "little")
    if head[offset : offset + 4] != b"PE\0\0":
        return None
    return int.from_bytes(head[offset + 4 : offset + 6], "little")


def check_ocr(payload: Path) -> list[str]:
    """Probleme der Texterkennung im Paket (leer = in Ordnung): ``ocr\\tesseract.exe`` für 64 Bit, jede DLL,
    die es direkt oder indirekt lädt, liegt daneben oder gehört zu Windows (``WINDOWS_DLLS``), keine
    überzähligen DLLs, Sprachdaten ``OCR_LANGUAGES``, ``pdf.ttf`` und die Lizenz."""
    if str(HERE) not in sys.path:
        sys.path.insert(0, str(HERE))
    from qtruntime import pe_imports  # dieselbe Auswertung der Importtabellen wie für PySide6

    folder = Path(payload) / OCR_DIR
    executable = folder / "tesseract.exe"
    if not executable.is_file():
        return [f"Texterkennung fehlt im Paket: {OCR_DIR}/tesseract.exe"]
    problems: list[str] = []
    if pe_machine(executable) != PE_MACHINE_X64:
        problems.append(f"{OCR_DIR}/tesseract.exe ist keine Windows-Programmdatei für 64 Bit")
    present = {path.name.lower(): path for path in folder.glob("*.dll")}
    missing: set[str] = set()
    seen: set[Path] = set()
    queue = [executable]
    while queue:
        current = queue.pop()
        if current in seen:
            continue
        seen.add(current)
        for name in pe_imports(current):
            key = name.lower()
            if key in present:
                queue.append(present[key])
            elif key not in WINDOWS_DLLS and not key.startswith(("api-ms-win-", "ext-ms-win-")):
                missing.add(name)
    if missing:
        problems.append(f"Für die Texterkennung fehlen DLLs in {OCR_DIR}/: " + ", ".join(sorted(missing, key=str.lower)))
    unused = sorted(path.name for path in present.values() if path not in seen)
    if unused:
        problems.append(f"Nicht benötigte DLLs in {OCR_DIR}/: " + ", ".join(unused))
    for language in OCR_LANGUAGES:
        data = folder / "tessdata" / f"{language}.traineddata"
        if not data.is_file() or data.stat().st_size < OCR_MIN_LANGUAGE_SIZE:
            problems.append(f"Sprachdaten fehlen: {OCR_DIR}/tessdata/{language}.traineddata")
    for rel in OCR_FILES:
        if not (folder / rel).is_file():
            problems.append(f"Im Paket fehlt: {OCR_DIR}/{rel}")
    return problems


def check_ai(payload: Path) -> list[str]:
    """Probleme der KI-Laufzeit im Paket (leer = in Ordnung): ``ai\\llama-server.exe`` für 64 Bit, mindestens ein
    Rechenwerk ``ggml-cpu-*.dll``, jede DLL, die beide direkt oder indirekt laden, liegt daneben oder gehört zu
    Windows, keine weiteren Programme oder DLLs (auch kein RPC- oder GPU-Backend) und die Lizenztexte."""
    if str(HERE) not in sys.path:
        sys.path.insert(0, str(HERE))
    from qtruntime import pe_imports

    folder = Path(payload) / AI_DIR
    executable = folder / AI_SERVER
    if not executable.is_file():
        return [f"KI-Laufzeit fehlt im Paket: {AI_DIR}/{AI_SERVER}"]
    problems: list[str] = []
    if pe_machine(executable) != PE_MACHINE_X64:
        problems.append(f"{AI_DIR}/{AI_SERVER} ist keine Windows-Programmdatei für 64 Bit")
    backends = sorted(folder.glob(AI_BACKENDS))
    if not backends:
        problems.append(f"Keine Rechenwerke in {AI_DIR}/ ({AI_BACKENDS})")
    present = {path.name.lower(): path for path in folder.glob("*.dll")}
    missing: set[str] = set()
    seen: set[Path] = set()
    queue = [executable, *backends]
    while queue:
        current = queue.pop()
        if current in seen:
            continue
        seen.add(current)
        for name in pe_imports(current):
            key = name.lower()
            if key in present:
                queue.append(present[key])
            elif key not in WINDOWS_DLLS and not key.startswith(("api-ms-win-", "ext-ms-win-")):
                missing.add(name)
    if missing:
        problems.append(f"Für die KI-Laufzeit fehlen DLLs in {AI_DIR}/: " + ", ".join(sorted(missing, key=str.lower)))
    unused = sorted(path.name for path in present.values() if path not in seen)
    if unused:
        problems.append(f"Nicht benötigte DLLs in {AI_DIR}/: " + ", ".join(unused))
    programs = sorted(path.name for path in folder.glob("*.exe") if path.name.lower() != AI_SERVER)
    if programs:
        problems.append(f"Weitere Programme in {AI_DIR}/: " + ", ".join(programs))
    licenses = folder / "LICENSES.txt"
    if not licenses.is_file() or "License for llama.cpp" not in licenses.read_text(encoding="utf-8", errors="replace"):
        problems.append(f"Im Paket fehlen die Lizenzen der KI-Laufzeit: {AI_DIR}/LICENSES.txt")
    return problems


def outputs(version: str) -> dict[str, str]:
    name = f"{SETUP_PREFIX}{version}.exe"
    return {
        "version": version,
        "tag": f"v{version}",
        "title": f"PDF Tool {version}",
        "prerelease": "true" if is_beta(version) else "false",
        "setup": name,
        "checksum": name + ".sha256",
        "notes": f"windows-app/release-notes/{version}.md",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Release-Dateien prüfen (Setup, Prüfsumme, Version, Release Notes)")
    parser.add_argument("dist", type=Path, help="Ordner mit Setup und .sha256")
    parser.add_argument("--version", default=None, help="Version (Standard: windows-app/VERSION)")
    parser.add_argument("--github-output", type=Path, default=None, help="Angaben für den Release-Schritt anhängen")
    parser.add_argument("--payload", type=Path, default=None, help="Paketordner des Setups prüfen (Standard: build/payload neben dist, sofern vorhanden)")
    args = parser.parse_args(argv)
    version = (args.version or (HERE / "VERSION").read_text(encoding="utf-8")).strip()
    problems = check(args.dist, version)
    payload = args.payload or Path(args.dist).resolve().parent / "build" / "payload"
    if args.payload is not None or payload.is_dir():
        problems += check_ocr(payload)
        if not problems:
            print(f"Paket: Texterkennung vollständig ({OCR_DIR}/tesseract.exe, Sprachdaten {', '.join(OCR_LANGUAGES)})")
    if problems:
        for problem in problems:
            print(f"FEHLER: {problem}", file=sys.stderr)
        return 1
    values = outputs(version)
    if args.github_output:
        with open(args.github_output, "a", encoding="utf-8") as handle:
            for key, value in values.items():
                handle.write(f"{key}={value}\n")
    kind = "Beta (GitHub-Vorabversion)" if values["prerelease"] == "true" else "Stable"
    print(f"OK: {values['setup']} · {kind} · Tag {values['tag']} · SHA-256 {sha256(Path(args.dist) / values['setup'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
