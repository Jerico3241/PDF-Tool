"""Welche Vorlage gilt – dieselbe Reihenfolge im Einzelmodus und im Stapel.

1. explizite Auswahl für diesen Vorgang (Stapel: im Eintrag gewählt)
2. Vorlage der Kundenakte – nur mit eingeschalteter Kundenakte
3. Standardvorlage des Stapels
4. Standardvorlage (Vorlagen → »Als Standard festlegen«)
5. keine Vorlage: globale Standardwerte (aktuelle »Darstellung«)

Je Stufe gilt: ``None`` = nicht festgelegt (nächste Stufe), ``""`` = bewusst keine Vorlage
(Ende, es gelten die globalen Standardwerte), sonst ein Verweis (ID ab 2.8, Name bis 2.7).
Fehlt die Vorlage eines Verweises, gilt die nächste Stufe – bei einer ``strict``-Stufe (im
Stapel-Eintrag bewusst gewählt) endet die Suche dagegen mit einem offenen Punkt: Eine bewusst
gewählte Vorlage wird nie still durch eine andere ersetzt.

Im Einzelmodus wählt der Benutzer die Vorlage selbst (Stufe 1). Die Standardvorlage wird beim
Beginn einer neuen Übersicht geladen; eine Kundenakte mit »Vorlage automatisch verwenden« lädt
danach ihre Vorlage (sie hat Vorrang).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Sequence

SOURCE_ITEM = "Eintrag"
SOURCE_CUSTOMER = "Kundenakte"
SOURCE_BATCH = "Stapel"
SOURCE_DEFAULT = "Standardvorlage"


@dataclass(frozen=True)
class Level:
    ref: str | None
    source: str
    strict: bool = False


@dataclass
class Choice:
    entry: dict | None = None  # Wörterbuch der Vorlage (``Template.to_entry``)
    source: str = ""  # Stufe, auf der die Entscheidung fiel ("" = keine Stufe)
    ref: str = ""  # gewählter Verweis ("" = keine Vorlage)
    missing: list[tuple[str, str]] = field(default_factory=list)  # (Verweis, Stufe) ohne Vorlage
    blocked: bool = False  # bewusst gewählte Vorlage fehlt (offener Punkt)


def choose(levels: Sequence[Level], find: Callable[[str], dict | None]) -> Choice:
    choice = Choice()
    for level in levels:
        if level.ref is None:
            continue
        if level.ref == "":
            choice.source = level.source
            return choice
        entry = find(level.ref)
        if entry is None:
            choice.missing.append((level.ref, level.source))
            if level.strict:
                choice.source = level.source
                choice.ref = level.ref
                choice.blocked = True
                return choice
            continue
        choice.entry = entry
        choice.source = level.source
        choice.ref = level.ref
        return choice
    return choice
