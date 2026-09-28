"""Werkzeuge von PDF Tool.

Jedes Werkzeug ist ein eigenes Paket mit eigener Oberfläche und eigener Logik.
Die Startseite und die Navigation lesen nur die Beschreibung (``ToolInfo``);
Werkzeuge greifen nicht auf die Daten anderer Werkzeuge zu.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ToolInfo:
    key: str  # Navigationsschlüssel des Werkzeugs
    title: str
    description: str
    glyph: str  # Symbol (Segoe Fluent Icons)
    pages: tuple[str, ...]  # Seiten des Werkzeugs; die erste ist der Einstieg
    shortcut: str = ""  # Tastenkürzel zum Öffnen, z. B. »Strg+2«
