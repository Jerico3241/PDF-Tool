"""Ablage der Updates – ein eigener Ordner außerhalb des Programmordners.

Windows: ``%LOCALAPPDATA%\\PDF-Tool-Updates`` (lokal, nicht im servergespeicherten Profil).
Das Programm selbst liegt unter ``%LOCALAPPDATA%\\PDF-Tool`` und wird vom Setup ersetzt –
Downloads gehören nicht hinein. ``UE_UPDATE_DIR`` legt den Ort fest (Tests, Prüfungen).

Dateien (Namen exakt wie im Release)::

    PDF-Tool-Setup-<Version>.exe.part     laufender Download – wird nie verwendet
    PDF-Tool-Setup-<Version>.exe          vollständig geladen *und* verifiziert
                                          (erst nach bestandener SHA-256-Prüfung umbenannt)
    PDF-Tool-Setup-<Version>.exe.sha256   die veröffentlichte Prüfsumme dazu
    releases.json                         Releases der letzten erfolgreichen Prüfung

Aufgeräumt werden ausschließlich diese Dateien – nie etwas anderes in diesem Ordner.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from datetime import datetime
from pathlib import Path

from . import github, schedule
from .models import Release

FOLDER = "PDF-Tool-Updates"
CACHE_FILE = "releases.json"
_OWN = re.compile(r"^PDF-Tool-Setup-[0-9A-Za-z.+-]+\.exe(?:\.part|\.sha256)?$")


def default_dir() -> Path:
    override = os.environ.get("UE_UPDATE_DIR")
    if override:
        return Path(override)
    base = os.environ.get("LOCALAPPDATA")
    if base:
        return Path(base) / FOLDER
    return Path.home() / ".cache" / FOLDER.lower()


def checksum_line(digest: str, name: str) -> str:
    """Eine Zeile im Format von ``sha256sum`` – wie ``build.py`` sie schreibt."""
    return f"{digest.lower()}  {name}\n"


class UpdateStore:
    """Dateien eines Update-Ordners."""

    def __init__(self, folder: str | Path, site: str = github.SITE) -> None:
        self.folder = Path(folder)
        self.site = site

    def ensure(self) -> Path:
        self.folder.mkdir(parents=True, exist_ok=True)
        return self.folder

    # Dateien eines Releases ----------------------------------------------------------------------
    def installer(self, release: Release) -> Path:
        return self.folder / github.installer_name(release.version)

    def partial(self, release: Release) -> Path:
        return self.folder / (github.installer_name(release.version) + ".part")

    def checksum_file(self, release: Release) -> Path:
        return self.folder / github.checksum_name(release.version)

    def cached(self, release: Release) -> Path | None:
        """Bereits geladenes Setup (gleiche Größe wie im Release) – die Prüfsumme prüft der Aufrufer."""
        path = self.installer(release)
        try:
            if release.installer is not None and path.is_file() and path.stat().st_size == release.installer.size:
                return path
        except OSError:
            pass
        return None

    def write_checksum(self, release: Release, digest: str) -> Path:
        path = self.checksum_file(release)
        self.ensure()
        path.write_text(checksum_line(digest, github.installer_name(release.version)), encoding="utf-8")
        return path

    def read_checksum(self, release: Release) -> str:
        from .verifier import ChecksumError, parse_checksum

        try:
            return parse_checksum(self.checksum_file(release).read_bytes(), github.installer_name(release.version))
        except (OSError, ChecksumError):
            return ""

    def remove(self, release: Release) -> None:
        """Setup, Teil-Download und Prüfsumme eines Releases entfernen (z. B. nach einer fehlgeschlagenen Prüfung)."""
        for path in (self.partial(release), self.installer(release), self.checksum_file(release)):
            _unlink(path)

    # Aufräumen -------------------------------------------------------------------------------------
    def own_files(self) -> list[Path]:
        try:
            return sorted(path for path in self.folder.iterdir() if path.is_file() and _OWN.match(path.name))
        except OSError:
            return []

    def cleanup(self, keep: Release | None = None) -> list[Path]:
        """Teil-Downloads, veraltete Setups und Prüfsummen entfernen – bis auf das Setup von ``keep``.

        Nur aufrufen, wenn gerade kein Download läuft (Teil-Downloads werden immer entfernt).
        """
        kept = set()
        if keep is not None:
            kept = {self.installer(keep).name, self.checksum_file(keep).name}
        removed = []
        for path in self.own_files():
            if path.name in kept:
                continue
            if _unlink(path):
                removed.append(path)
        return removed

    # Zwischenspeicher der letzten Prüfung -----------------------------------------------------------------
    def save_releases(self, releases: list[Release], checked: datetime) -> None:
        data = {"geprueft": schedule.format_time(checked), "releases": github.to_cache(releases)}
        try:
            self.ensure()
            fd, temp = tempfile.mkstemp(prefix=".releases-", suffix=".tmp", dir=str(self.folder))
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    json.dump(data, handle, ensure_ascii=False)
                os.replace(temp, self.folder / CACHE_FILE)
            finally:
                if os.path.exists(temp):
                    os.remove(temp)
        except OSError:
            pass  # ohne Zwischenspeicher wird beim nächsten Start einfach erneut geprüft

    def load_releases(self) -> tuple[list[Release], datetime | None]:
        try:
            data = json.loads((self.folder / CACHE_FILE).read_text(encoding="utf-8"))
            return github.parse_releases(data.get("releases"), self.site), schedule.parse_time(data.get("geprueft"))
        except (OSError, ValueError, AttributeError, TypeError):
            return [], None


def _unlink(path: Path) -> bool:
    try:
        path.unlink()
        return True
    except FileNotFoundError:
        return False
    except OSError:
        return False
