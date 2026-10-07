"""Grundbegriffe des Updaters: Kanal, Zustand, Fehlerarten, Release und Assets.

Entscheidungen fallen anhand dieser Werte – nie anhand angezeigter (deutscher) Texte.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from .semver import Version

# Die beiden Tags, die als Update in Frage kommen: ``vX.Y.Z`` und ``vX.Y.Z-beta.N`` (N ab 1) –
# genau so, ohne weitere Kennungen (``-rc.1``, ``-dev``, ``+build.5`` …), mit »v«, nur ASCII-Ziffern.
_CORE_TAG = r"v(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)"
_STABLE_TAG = re.compile(_CORE_TAG)
_BETA_TAG = re.compile(_CORE_TAG + r"-beta\.[1-9][0-9]*")


class Channel(str, Enum):
    """Update-Kanal. Stable ist der Standard; Beta nur nach bewusster Wahl."""

    STABLE = "stable"
    BETA = "beta"

    @classmethod
    def from_config(cls, value: object) -> "Channel":
        """Gespeicherter Wert → Kanal; fehlend oder unbekannt → Stable (nie ungefragt Beta)."""
        try:
            return cls(str(value).strip().lower())
        except ValueError:
            return cls.STABLE


class UpdateState(str, Enum):
    """Zentraler Zustand des Updaters (siehe ``state.py`` für die erlaubten Übergänge)."""

    IDLE = "idle"
    CHECKING = "checking"
    UP_TO_DATE = "up_to_date"
    AVAILABLE = "available"
    DOWNLOADING = "downloading"
    VERIFYING = "verifying"
    READY = "ready"
    INSTALLING = "installing"
    CANCELLED = "cancelled"
    ERROR = "error"


class ErrorKind(str, Enum):
    """Warum der letzte Schritt nicht geklappt hat."""

    CHECK_FAILED = "check_failed"  # offline, Zeitüberschreitung, Serverfehler, ungültige Antwort
    RATE_LIMITED = "rate_limited"  # GitHub-Anfragelimit erreicht
    DOWNLOAD_FAILED = "download_failed"  # Setup oder Prüfsumme nicht vollständig geladen
    VERIFY_FAILED = "verify_failed"  # Prüfsumme fehlt, ist ungültig oder passt nicht
    INSTALL_FAILED = "install_failed"  # Setup fehlt oder ließ sich nicht starten


@dataclass(frozen=True)
class Asset:
    """Eine Datei eines Releases (Setup oder Prüfsummendatei)."""

    name: str
    size: int
    url: str
    digest: str = ""  # SHA-256 laut GitHub (``sha256:…``), falls angegeben – nur zum Gegenprüfen


@dataclass(frozen=True)
class Release:
    """Ein veröffentlichtes Release mit den Angaben, die der Updater braucht."""

    version: Version
    tag: str
    title: str
    notes: str
    published: datetime | None
    page: str  # Seite des Releases auf GitHub
    prerelease: bool  # auf GitHub als Vorabversion markiert
    draft: bool
    installer: Asset | None = None
    checksum: Asset | None = None
    problems: tuple[str, ...] = field(default_factory=tuple)  # warum das Release unvollständig ist

    @property
    def complete(self) -> bool:
        """Setup und Prüfsummendatei mit den erwarteten Namen sind vorhanden."""
        return self.installer is not None and self.checksum is not None

    @property
    def is_beta(self) -> bool:
        """Vorabversion – nach SemVer-Kennung oder laut GitHub-Markierung."""
        return self.version.is_prerelease or self.prerelease

    @property
    def channel(self) -> Channel | None:
        """Kanal, für den das Release gedacht ist – aus Tag und Markierung auf GitHub:

        * ``vX.Y.Z``, nicht als Vorabversion markiert → Stable,
        * ``vX.Y.Z-beta.N``, als Vorabversion markiert → Beta,
        * alles andere → ``None`` (nie angeboten): andere Kennungen (``-rc.1``, ``-alpha.1``,
          ``-dev``, ``+build.5`` …) auch ohne Markierung, ein Beta-Tag ohne Markierung, ein
          Stable-Tag mit Markierung.
        """
        if _STABLE_TAG.fullmatch(self.tag):
            return None if self.prerelease else Channel.STABLE
        if _BETA_TAG.fullmatch(self.tag):
            return Channel.BETA if self.prerelease else None
        return None
