"""Wiedererkennung bekannter Kunden über Rechnungsempfänger-E-Mails.

Normalisiert wird bewusst zurückhaltend: Leerzeichen am Rand entfernen und
Groß-/Kleinschreibung ignorieren. ``+tags``, Punkte und Domains bleiben unverändert.

Ergebnis ist ein ``MatchResult`` mit einer Art (``MatchKind``) – die Oberfläche
entscheidet anhand der Art, was sie anbietet; Texte gehören nicht in diese Logik.
Die Funktion arbeitet mit beliebigen E-Mail-Listen (eine Excel oder viele) und ist
damit unabhängig vom Formular.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Iterable, Mapping, Sequence

# Grundlegende Prüfung: genau ein @, kein Leerzeichen, Domain mit Punkt
EMAIL_RE = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s.]+")
_SPLIT_RE = re.compile(r"[;,\s]+")


def normalize_email(value) -> str:
    """Randleerzeichen entfernen, Kleinbuchstaben – sonst nichts (keine Tags, Punkte, Domains)."""
    if not isinstance(value, str):
        return ""
    # lower() statt casefold(): »ß« bleibt »ß«, die Adresse wird nicht umgeschrieben.
    return value.strip().lower()


def is_valid_email(value) -> bool:
    email = normalize_email(value)
    return 3 <= len(email) <= 254 and EMAIL_RE.fullmatch(email) is not None


def split_emails(text) -> list[str]:
    """Gültige Adressen aus einem Text mit mehreren Angaben (z. B. »a@x.de; b@x.de«), normalisiert."""
    found: list[str] = []
    for part in _SPLIT_RE.split(text if isinstance(text, str) else ""):
        email = normalize_email(part.strip("<>\"'()[]"))
        if is_valid_email(email) and email not in found:
            found.append(email)
    return found


class MatchKind(str, Enum):
    NONE = "no_match"  # keine bekannte Adresse
    SINGLE = "single_match"  # alle bekannten Adressen gehören derselben Kundenakte
    AMBIGUOUS = "ambiguous_match"  # eine Adresse ist mehreren Kundenakten zugeordnet (Altdaten)
    CONFLICT = "conflicting_matches"  # Adressen gehören verschiedenen Kundenakten


@dataclass(frozen=True)
class MatchResult:
    kind: MatchKind
    customer_ids: tuple[str, ...] = ()  # Kandidaten in Reihenfolge des ersten Auftretens
    owners: Mapping[str, tuple[str, ...]] = field(default_factory=dict)  # bekannte Adresse → Kundenakten
    unknown: tuple[str, ...] = ()  # gültige Adressen ohne Zuordnung
    emails: tuple[str, ...] = ()  # alle gültigen, normalisierten Adressen der Eingabe

    @property
    def customer_id(self) -> str | None:
        return self.customer_ids[0] if self.kind is MatchKind.SINGLE else None

    def emails_of(self, customer_id: str) -> tuple[str, ...]:
        return tuple(email for email, ids in self.owners.items() if customer_id in ids)


def match_emails(emails: Iterable[str], owners_of: Callable[[str], Sequence[str]] | Mapping[str, Sequence[str]]) -> MatchResult:
    """Adressen (z. B. alle Rechnungsempfänger einer Excel) gegen bekannte Zuordnungen prüfen."""
    lookup = owners_of.get if isinstance(owners_of, Mapping) else owners_of
    seen: list[str] = []
    for raw in emails:
        email = normalize_email(raw)
        if is_valid_email(email) and email not in seen:
            seen.append(email)
    owners: dict[str, tuple[str, ...]] = {}
    unknown: list[str] = []
    candidates: list[str] = []
    for email in seen:
        ids = tuple(dict.fromkeys(lookup(email) or ()))  # type: ignore[operator]
        if not ids:
            unknown.append(email)
            continue
        owners[email] = ids
        for ident in ids:
            if ident not in candidates:
                candidates.append(ident)
    if not candidates:
        kind = MatchKind.NONE
    elif any(len(ids) > 1 for ids in owners.values()):
        kind = MatchKind.AMBIGUOUS
    elif len(candidates) == 1:
        kind = MatchKind.SINGLE
    else:
        kind = MatchKind.CONFLICT
    return MatchResult(kind, tuple(candidates), owners, tuple(unknown), tuple(seen))
