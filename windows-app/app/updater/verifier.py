"""SHA-256-Prüfung: Prüfsummendatei lesen, Hash einer Datei berechnen und vergleichen.

Format der Prüfsummendatei (so schreibt sie ``build.py`` seit 2.2.0, wie ``sha256sum``)::

    <64 Hex-Zeichen><2 Leerzeichen><Dateiname><Zeilenende>

Gelesen wird robust: Zeilenende LF oder CRLF, optionales BOM, Groß- oder Kleinbuchstaben,
ein Leerzeichen oder ``*`` (Binärmodus) vor dem Namen, ``SHA256 (<Name>) = <Hash>`` (BSD) oder
nur der Hash allein. Steht ein Dateiname dabei, muss er genau dem Setup entsprechen. Mehrdeutige
oder widersprüchliche Angaben gelten als ungültig – ohne gültige Prüfsumme keine Installation.
"""

from __future__ import annotations

import hashlib
import hmac
import re
from pathlib import Path
from typing import Callable

_HEX = re.compile(r"^[0-9a-fA-F]{64}$")
_LINE = re.compile(r"^(?P<hash>[0-9a-fA-F]{64})(?:(?: \*| {1,2})(?P<name>\S.*))?$")
_BSD = re.compile(r"^SHA256 \((?P<name>.+)\) = (?P<hash>[0-9a-fA-F]{64})$")
CHUNK = 1024 * 1024


class ChecksumError(ValueError):
    """Die Prüfsummendatei fehlt, ist ungültig oder gehört zu einer anderen Datei."""


def parse_checksum(content: bytes | str, expected_name: str) -> str:
    """Prüfsumme (64 Hex-Zeichen, klein) für ``expected_name`` aus dem Inhalt einer ``.sha256``-Datei."""
    if isinstance(content, (bytes, bytearray)):
        if len(content) > 64 * 1024:
            raise ChecksumError("Prüfsummendatei ist zu groß")
        try:
            text = bytes(content).decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise ChecksumError("Prüfsummendatei ist kein Text") from exc
    else:
        text = str(content).lstrip("﻿")
    named: set[str] = set()
    bare: set[str] = set()
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = _LINE.match(line) or _BSD.match(line)
        if match is None:
            raise ChecksumError("Prüfsummendatei hat ein unbekanntes Format")
        digest = match.group("hash").lower()
        name = match.group("name")
        if name is None:
            bare.add(digest)
        elif name.strip() == expected_name:
            named.add(digest)
        # Zeilen für andere Dateien werden übergangen
    found = named or bare
    if not found:
        raise ChecksumError(f"Keine Prüfsumme für {expected_name}")
    if len(found) > 1 or (named and bare and bare != named):
        raise ChecksumError("Prüfsummendatei ist widersprüchlich")
    return found.pop()


def file_sha256(path: str | Path, cancelled: Callable[[], bool] | None = None) -> str:
    """SHA-256 einer Datei (in Blöcken, abbrechbar über ``cancelled``)."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while True:
            if cancelled is not None and cancelled():
                raise InterruptedError("Prüfung abgebrochen")
            block = handle.read(CHUNK)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def is_sha256(value: str) -> bool:
    return bool(_HEX.match(str(value or "")))


def same_digest(left: str, right: str) -> bool:
    """Vergleich zweier Prüfsummen (Groß-/Kleinschreibung egal, zeitkonstant)."""
    if not (is_sha256(left) and is_sha256(right)):
        return False
    return hmac.compare_digest(left.lower(), right.lower())


def matches(path: str | Path, expected: str, cancelled: Callable[[], bool] | None = None) -> bool:
    """Hat die Datei genau diese Prüfsumme? Fehlt die Datei: ``False``."""
    if not is_sha256(expected):
        return False
    try:
        return same_digest(file_sha256(path, cancelled), expected)
    except OSError:
        return False
