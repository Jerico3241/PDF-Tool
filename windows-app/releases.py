"""Veröffentlichte Versionen für die Update-Tests der CI bestimmen – nach SemVer, nie alphabetisch.

Der normale Workflow prüft genau ein echtes Installer-Update: von der unmittelbar vorherigen
stabilen Version auf die neue (für 2.7.0: 2.6.1 → 2.7.0). Der manuelle Workflow »Deep
Compatibility Test« kann dagegen alle älteren stabilen Versionen prüfen (ab 2.2.0 – ältere
Setups kennt ``tests/smoke_installer.ps1`` nicht).

Aufruf (in der CI, mit der GitHub-CLI ``gh``)::

    python windows-app/releases.py previous            # z. B. »2.6.1«
    python windows-app/releases.py all --json          # z. B. ["2.2.0", "2.3.0", …]
    python windows-app/releases.py all --only 2.4.0,2.5.0 --json

Stabil heißt: Tag ``vMAJOR.MINOR.PATCH`` ohne Vorabkennung (``-rc1`` …), weder Entwurf noch
Vorabversion. Die aktuelle Version steht in ``windows-app/VERSION``.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Iterable

HERE = Path(__file__).resolve().parent
OLDEST_SUPPORTED = (2, 2, 0)  # älteste Vorversion, die smoke_installer.ps1 installieren und prüfen kann
_TAG = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")

Version = tuple[int, int, int]


def parse(value: str) -> Version | None:
    """``"v2.6.1"`` → ``(2, 6, 1)``; Vorabversionen (``2.7.0-rc1``) und Fremdes → ``None``."""
    match = _TAG.match(str(value).strip())
    return tuple(int(part) for part in match.groups()) if match else None  # type: ignore[return-value]


def text(version: Version) -> str:
    return ".".join(str(part) for part in version)


def stable_versions(releases: Iterable[dict]) -> list[Version]:
    """Stabile, veröffentlichte Versionen aus ``gh release list --json tagName,isDraft,isPrerelease``."""
    found = set()
    for release in releases:
        if release.get("isDraft") or release.get("isPrerelease"):
            continue
        version = parse(release.get("tagName", ""))
        if version is not None:
            found.add(version)
    return sorted(found)


def previous_stable(current: Version, versions: Iterable[Version]) -> Version | None:
    """Unmittelbar vorherige stabile Version (größte Version kleiner als ``current``)."""
    older = [version for version in versions if version < current]
    return max(older) if older else None


def older_stable(current: Version, versions: Iterable[Version], oldest: Version = OLDEST_SUPPORTED) -> list[Version]:
    """Alle stabilen Versionen vor ``current`` ab ``oldest`` – aufsteigend (für den manuellen Volltest)."""
    return sorted(version for version in set(versions) if oldest <= version < current)


def current_version() -> Version:
    version = parse((HERE / "VERSION").read_text(encoding="utf-8"))
    if version is None:
        raise SystemExit("windows-app/VERSION enthält keine Version MAJOR.MINOR.PATCH")
    return version


def published_releases(repo: str | None) -> list[dict]:
    command = ["gh", "release", "list", "--limit", "200", "--json", "tagName,isDraft,isPrerelease"]
    if repo:
        command += ["--repo", repo]
    result = subprocess.run(command, check=True, capture_output=True, text=True, encoding="utf-8")
    return json.loads(result.stdout or "[]")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Versionen für die Update-Tests bestimmen (SemVer)")
    parser.add_argument("mode", choices=("previous", "all"), help="previous: unmittelbar vorherige stabile Version; all: alle älteren stabilen Versionen")
    parser.add_argument("--repo", default=None, help="owner/name (Standard: Repository des Arbeitsordners)")
    parser.add_argument("--releases", type=Path, default=None, help="Liste der Releases als JSON-Datei statt »gh release list« (Tests)")
    parser.add_argument("--only", default="", help="nur diese Versionen (kommagetrennt, müssen veröffentlicht sein)")
    parser.add_argument("--json", action="store_true", help="Ausgabe als JSON")
    args = parser.parse_args(argv)
    releases = json.loads(args.releases.read_text(encoding="utf-8")) if args.releases else published_releases(args.repo)
    versions = stable_versions(releases)
    current = current_version()
    if args.mode == "previous":
        previous = previous_stable(current, versions)
        if previous is None:
            print(f"Keine stabile Version vor {text(current)} veröffentlicht", file=sys.stderr)
            return 1
        print(json.dumps(text(previous)) if args.json else text(previous))
        return 0
    chosen = older_stable(current, versions)
    if args.only.strip():
        wanted = [parse(item) for item in args.only.split(",") if item.strip()]
        unknown = [item for item, version in zip(args.only.split(","), wanted) if version is None or version not in chosen]
        if unknown:
            print(f"Nicht als stabile Vorversion veröffentlicht: {', '.join(item.strip() for item in unknown)}", file=sys.stderr)
            return 1
        chosen = sorted(set(wanted))  # type: ignore[arg-type]
    names = [text(version) for version in chosen]
    print(json.dumps(names) if args.json else "\n".join(names))
    return 0


if __name__ == "__main__":
    sys.exit(main())
