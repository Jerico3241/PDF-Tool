"""Werkzeuge von PDF Tool.

Jedes Werkzeug ist ein eigenes Paket mit eigener Logik (ohne Oberflächencode); seine Seiten
stehen in QML (``qml/PdfTool/Pages``), seine Controller in ``qtapp``. Startseite und Tab-Leiste
lesen nur die Beschreibung (``ToolInfo``); Werkzeuge greifen nicht auf die Daten anderer
Werkzeuge zu.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ToolInfo:
    key: str  # Navigationsschlüssel des Werkzeugs
    title: str
    description: str
    icon: str  # Symbol (Name eines Fluent-Symbols in qml/icons)
    pages: tuple[str, ...]  # Seiten des Werkzeugs; die erste ist der Einstieg
    shortcut: str = ""  # Tastenkürzel zum Öffnen, z. B. »Strg+2«
