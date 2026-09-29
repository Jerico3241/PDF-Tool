"""Datenmodell der Kundenakte 2.0.

Jede Kundenakte hat eine stabile, zufällige ID (UUID). Firmenname, Kundennummer
und E-Mail-Adressen lassen sich ändern, ohne dass die Akte technisch neu entsteht –
die ID bleibt der Schlüssel (auch für spätere Funktionen wie Vertragsvergleiche).

Zeitstempel werden als ISO 8601 mit Zeitzone gespeichert, Pfade nur als Text:
PDF- und Excel-Dateien werden nie in den Datenordner kopiert.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime

SCHEMA_VERSION = 2  # Version 1: einfache Kundenhistorie in gui-config.json (bis 2.3)


def now_iso() -> str:
    # Mikrosekunden: kurz nacheinander verwendete Kundenakten bleiben unterscheidbar sortiert.
    return datetime.now().astimezone().isoformat(timespec="microseconds")


def new_id() -> str:
    return str(uuid.uuid4())


def parse_time(value: str) -> datetime | None:
    """ISO-Zeitstempel lesen; ungültige Werte ergeben ``None`` (nie eine Ausnahme)."""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.astimezone()


def _text(value) -> str:
    return value.strip() if isinstance(value, str) else ""


@dataclass
class TextBlock:
    """Kopf- oder Fußzeile einer Kundenakte: reiner Text und Formatierung (``RichText.to_dict()``)."""

    text: str
    format: dict | None = None

    def to_dict(self) -> dict:
        return {"text": self.text, "format": self.format}

    @classmethod
    def from_dict(cls, data) -> "TextBlock | None":
        if not isinstance(data, dict) or not isinstance(data.get("text"), str):
            return None
        fmt = data.get("format")
        return cls(data["text"], fmt if isinstance(fmt, dict) else None)


@dataclass
class Customer:
    """Eine Kundenakte. ``emails`` sind normalisiert; die erste Adresse gilt als primär."""

    id: str
    company: str = ""
    number: str = ""
    emails: list[str] = field(default_factory=list)
    note: str = ""
    # Einstellungen für Vertragsübersichten
    logo: str = ""
    target_dir: str = ""
    template: str = ""
    template_auto: bool = False  # bevorzugte Vorlage beim Übernehmen automatisch verwenden
    header: TextBlock | None = None  # None: keine eigene Kopfzeile
    footer: TextBlock | None = None  # None: keine eigene Fußzeile (die gültige bleibt)
    # Letzte Aktivität (wird automatisch fortgeschrieben)
    last_excel: str = ""
    last_pdf: str = ""
    last_used_at: str = ""
    created_at: str = ""
    updated_at: str = ""  # letzte bewusste Änderung der Akte
    origin: str = ""  # »kundenhistorie«: aus der Kundenhistorie bis 2.3 übernommen

    @property
    def label(self) -> str:
        return f"{self.company or 'Ohne Namen'} · {self.number or '–'}"

    @property
    def primary_email(self) -> str:
        return self.emails[0] if self.emails else ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "company": self.company,
            "number": self.number,
            "emails": list(self.emails),
            "note": self.note,
            "logo": self.logo,
            "target_dir": self.target_dir,
            "template": self.template,
            "template_auto": bool(self.template_auto),
            "header": self.header.to_dict() if self.header else None,
            "footer": self.footer.to_dict() if self.footer else None,
            "last_excel": self.last_excel,
            "last_pdf": self.last_pdf,
            "last_used_at": self.last_used_at,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "origin": self.origin,
        }

    @classmethod
    def from_dict(cls, data) -> "Customer | None":
        """Robust lesen: fehlende oder falsche Werte werden zu Standardwerten, nie zu Fehlern."""
        if not isinstance(data, dict):
            return None
        ident = _text(data.get("id"))
        if not ident:
            return None
        from .matching import normalize_email

        emails: list[str] = []
        for raw in data.get("emails") or []:
            email = normalize_email(raw)
            if email and email not in emails:
                emails.append(email)
        return cls(
            id=ident,
            company=_text(data.get("company")),
            number=_text(data.get("number")),
            emails=emails,
            note=data.get("note") if isinstance(data.get("note"), str) else "",
            logo=_text(data.get("logo")),
            target_dir=_text(data.get("target_dir")),
            template=_text(data.get("template")),
            template_auto=data.get("template_auto") is True,
            header=TextBlock.from_dict(data.get("header")),
            footer=TextBlock.from_dict(data.get("footer")),
            last_excel=_text(data.get("last_excel")),
            last_pdf=_text(data.get("last_pdf")),
            last_used_at=_text(data.get("last_used_at")),
            created_at=_text(data.get("created_at")),
            updated_at=_text(data.get("updated_at")),
            origin=_text(data.get("origin")),
        )
