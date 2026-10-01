"""Versionen nach Semantic Versioning 2.0.0 (https://semver.org) – nie als Text verglichen.

``2.9.0 < 2.10.0`` und ``2.7.3-beta.1 < 2.7.3-beta.2 < 2.7.3-beta.10 < 2.7.3``:

* Hauptversion, Nebenversion, Patch werden als Zahlen verglichen.
* Eine Vorabversion (``-beta.1``) ist kleiner als dieselbe Version ohne Vorabkennung.
* Vorabkennungen werden Teil für Teil verglichen: Zahlen als Zahlen, Zahlen vor Text,
  Text nach ASCII; eine kürzere Folge ist bei gleichem Anfang kleiner.
* Build-Metadaten (``+build.5``) spielen für die Reihenfolge keine Rolle.

Tags tragen ein vorangestelltes ``v`` (``v2.7.3-beta.1``). Nur Standardbibliothek.
"""

from __future__ import annotations

import re
from functools import total_ordering

_NUMBER = r"0|[1-9]\d*"
_IDENTIFIER = r"(?:0|[1-9]\d*|\d*[A-Za-z-][0-9A-Za-z-]*)"
_PATTERN = re.compile(
    rf"^(?P<major>{_NUMBER})\.(?P<minor>{_NUMBER})\.(?P<patch>{_NUMBER})"
    rf"(?:-(?P<pre>{_IDENTIFIER}(?:\.{_IDENTIFIER})*))?"
    r"(?:\+(?P<build>[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$"
)
# Anzeigenamen bekannter Vorabkennungen (»2.7.3 Beta 1«)
_LABELS = {"alpha": "Alpha", "beta": "Beta", "rc": "RC"}
_MAX_LENGTH = 128


@total_ordering
class Version:
    """Eine SemVer-Version. Gleichheit und Reihenfolge folgen der SemVer-Rangfolge."""

    __slots__ = ("major", "minor", "patch", "prerelease", "build")

    def __init__(self, major: int, minor: int, patch: int, prerelease: tuple[str, ...] = (), build: tuple[str, ...] = ()) -> None:
        self.major = int(major)
        self.minor = int(minor)
        self.patch = int(patch)
        self.prerelease = tuple(str(part) for part in prerelease)
        self.build = tuple(str(part) for part in build)

    # Einlesen -----------------------------------------------------------------------------------
    @classmethod
    def parse(cls, text: str) -> "Version":
        """``"2.7.3-beta.1"`` → Version; alles andere (auch ``"2.7"``, ``"v2.7.3"``) → ``ValueError``."""
        value = str(text).strip()
        match = _PATTERN.match(value) if len(value) <= _MAX_LENGTH else None
        if match is None:
            raise ValueError(f"Keine gültige Version (SemVer): {text!r}")
        pre = match.group("pre")
        build = match.group("build")
        return cls(
            int(match.group("major")),
            int(match.group("minor")),
            int(match.group("patch")),
            tuple(pre.split(".")) if pre else (),
            tuple(build.split(".")) if build else (),
        )

    @classmethod
    def from_tag(cls, tag: str) -> "Version | None":
        """Git-Tag ``"v2.7.3-beta.1"`` (oder ohne ``v``) → Version; ungültig → ``None``."""
        value = str(tag or "").strip()
        if value.startswith("v"):
            value = value[1:]
        try:
            return cls.parse(value)
        except ValueError:
            return None

    @classmethod
    def coerce(cls, text: str, fallback: str = "0.0.0") -> "Version":
        """Wie ``parse``, aber eine ungültige Angabe ergibt ``fallback`` (z. B. eine leere VERSION-Datei)."""
        try:
            return cls.parse(text)
        except ValueError:
            return cls.parse(fallback)

    # Eigenschaften --------------------------------------------------------------------------------
    @property
    def is_prerelease(self) -> bool:
        return bool(self.prerelease)

    @property
    def core(self) -> tuple[int, int, int]:
        return (self.major, self.minor, self.patch)

    @property
    def stage(self) -> str:
        """Art der Vorabversion in Kleinbuchstaben (``"beta"``) – leer bei einer stabilen Version."""
        return self.prerelease[0].lower() if self.prerelease else ""

    def label(self) -> str:
        """Für Hinweise: ``"2.7.3"``, ``"2.7.3 Beta 1"``, ``"2.7.3 RC 2"``."""
        core = f"{self.major}.{self.minor}.{self.patch}"
        if not self.prerelease:
            return core
        name = _LABELS.get(self.stage, self.prerelease[0])
        rest = " ".join(self.prerelease[1:])
        return f"{core} {name} {rest}".rstrip()

    # Rangfolge ------------------------------------------------------------------------------------
    def _key(self) -> tuple:
        if not self.prerelease:
            return (self.major, self.minor, self.patch, 1, ())
        parts = tuple((0, int(part), "") if part.isdigit() else (1, 0, part) for part in self.prerelease)
        return (self.major, self.minor, self.patch, 0, parts)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Version):
            return NotImplemented
        return self._key() == other._key()

    def __lt__(self, other: "Version") -> bool:
        if not isinstance(other, Version):
            return NotImplemented
        return self._key() < other._key()

    def __hash__(self) -> int:
        return hash(self._key())

    def __str__(self) -> str:
        text = f"{self.major}.{self.minor}.{self.patch}"
        if self.prerelease:
            text += "-" + ".".join(self.prerelease)
        if self.build:
            text += "+" + ".".join(self.build)
        return text

    def __repr__(self) -> str:
        return f"Version({str(self)!r})"

    @property
    def tag(self) -> str:
        """Git-Tag dieser Version: ``"v2.7.3-beta.1"``."""
        return "v" + str(self)
