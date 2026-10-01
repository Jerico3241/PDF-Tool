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
    args = parser.parse_args(argv)
    version = (args.version or (HERE / "VERSION").read_text(encoding="utf-8")).strip()
    problems = check(args.dist, version)
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
