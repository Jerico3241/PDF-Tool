"""Vorlagen 2.0: eine vollständige, wiederverwendbare Darstellung einer Vertragsübersicht.

Eine Vorlage speichert genau die Einstellungen, die PDF Tool für die PDF tatsächlich kennt:

* ``TemplateMetadata``: stabile ID (UUID), Name, Beschreibung, Zeitstempel. Der Name ist nur
  die Anzeige – umbenennen, duplizieren und verweisen (Kundenakte, Stapel, Standardvorlage)
  geschieht über die ID.
* ``TemplateLayout``: Seitenformat (A4 hoch/quer), Logo, Logo-Breite, Titel, Untertitel und
  Dateinamensschema.
* ``TemplateRichText``: Kopf- und Fußzeile samt Formatierung (``richtext.RichText``).
* ``TemplateRuleReference``: Zyklus-Regeln und das zugeordnete Regelwerk.

Spalten, Ränder und Farben der PDF sind fest vorgegeben – dafür gibt es keine Einstellung und
daher auch kein Feld in der Vorlage.

Übernommene Vorlagen älterer Versionen (bis 2.7) können einzelne Darstellungswerte nicht
enthalten (``None``): Beim Anwenden bleibt der aktuelle Wert dann – wie bisher – unverändert.
Kopf-/Fußzeile und Zyklus-Regeln werden bei der Übernahme mit denselben Funktionen wie bisher
bestimmt (``appstate.header_rich_from`` usw.); das Anwenden ergibt exakt dasselbe wie in 2.7.

Gespeichert wird je Vorlage eine JSON-Datei mit ``schema_version`` (``repository.py``).
``to_entry`` liefert das bisherige Wörterbuch einer Vorlage – so verwenden Einzelmodus, Stapel
und Kundenakte dieselben Funktionen wie bisher (``overview.template_layout`` usw.).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field, replace
from datetime import datetime

from appstate import (
    FOOTER_EXPLICIT,
    FOOTER_FORMAT,
    HEADER_FORMAT,
    footer_rich_from,
    header_rich_from,
    normalize_regeln,
)
from richtext import FOOTER_ALIGN, FOOTER_STYLE, HEADER_ALIGN, HEADER_STYLE, RichText
from storage import SchemaError, check_schema, safe_id

SCHEMA_VERSION = 1
KIND = "Vorlage"
FORMATS = ("hoch", "quer")
LAYOUT_KEYS = ("format", "logo", "logo_breite", "titel", "untertitel", "dateiname")
MAX_NAME = 120
MAX_DESCRIPTION = 2000
ENTRY_ID = "id"  # zusätzliche Schlüssel im bisherigen Wörterbuch einer Vorlage
ENTRY_RULE_SET = "regelwerk"
ENTRY_DESCRIPTION = "beschreibung"


def new_id() -> str:
    return str(uuid.uuid4())


def valid_id(value) -> bool:
    return safe_id(value)


def now_iso() -> str:
    """Lokale Zeit mit Zeitzone und Mikrosekunden – zuletzt gespeicherte Vorlagen sortieren vorn."""
    return datetime.now().astimezone().isoformat(timespec="microseconds")


def clean_name(value) -> str:
    """Name einer Vorlage: eine Zeile, ohne äußere Leerzeichen, höchstens ``MAX_NAME`` Zeichen."""
    text = " ".join(str(value or "").split())
    return text[:MAX_NAME]


def _opt_text(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return f"{value:g}" if isinstance(value, float) else str(value)
    return value if isinstance(value, str) else None


@dataclass(frozen=True)
class TemplateMetadata:
    id: str
    name: str
    description: str = ""
    created_at: str = ""
    updated_at: str = ""


@dataclass(frozen=True)
class TemplateLayout:
    """Darstellung der PDF. ``None``: nicht festgelegt – der aktuelle Wert bleibt beim Anwenden."""

    format: str | None = None
    logo: str | None = None
    logo_breite: str | None = None
    titel: str | None = None
    untertitel: str | None = None
    dateiname: str | None = None

    def to_dict(self) -> dict:
        return {key: getattr(self, key) for key in LAYOUT_KEYS if getattr(self, key) is not None}

    @classmethod
    def from_dict(cls, data) -> "TemplateLayout":
        data = data if isinstance(data, dict) else {}
        values = {key: _opt_text(data.get(key)) for key in LAYOUT_KEYS}
        if values["format"] not in FORMATS:
            values["format"] = None
        return cls(**values)


@dataclass(frozen=True)
class TemplateRichText:
    """Kopf- oder Fußzeile: reiner Text und Formatierung (``RichText.to_dict()``)."""

    text: str
    format: dict | None = None

    def rich(self, header: bool) -> RichText:
        style, align = (HEADER_STYLE, HEADER_ALIGN) if header else (FOOTER_STYLE, FOOTER_ALIGN)
        return RichText.from_storage(self.text, self.format, style, align)

    @classmethod
    def of(cls, rich: RichText) -> "TemplateRichText":
        return cls(rich.text, rich.to_dict())

    def to_dict(self) -> dict:
        return {"text": self.text, "format": self.format}

    @classmethod
    def from_dict(cls, data, header: bool) -> "TemplateRichText":
        """Gespeicherter Text; Fehlendes oder Ungültiges ergibt den Standard (leer bzw. Standard-Fußzeile)."""
        if isinstance(data, dict) and isinstance(data.get("text"), str):
            fmt = data.get("format") if isinstance(data.get("format"), dict) else None
            return cls.of(RichText.from_storage(data["text"], fmt, *((HEADER_STYLE, HEADER_ALIGN) if header else (FOOTER_STYLE, FOOTER_ALIGN))))
        return cls.of(header_rich_from({}) if header else footer_rich_from({}))


@dataclass(frozen=True)
class TemplateRuleReference:
    """Regeln einer Vorlage: Zyklus-Regeln (wie bisher) und das zugeordnete Regelwerk.

    ``rule_set_id``: ID eines Regelwerks, ``""`` = bewusst keines, ``None`` = nicht festgelegt
    (übernommene ältere Vorlage: beim Anwenden bleibt das aktuelle Regelwerk).
    """

    cycle_rules: tuple[tuple[str, str], ...] = ()
    rule_set_id: str | None = None

    def cycle_list(self) -> list[dict]:
        return [{"enthaelt": nadel, "zyklus": zyklus} for nadel, zyklus in self.cycle_rules]

    @staticmethod
    def cycles_from(raw) -> tuple[tuple[str, str], ...]:
        return tuple((regel["enthaelt"], regel["zyklus"]) for regel in normalize_regeln(raw))


@dataclass(frozen=True)
class Template:
    meta: TemplateMetadata
    layout: TemplateLayout = field(default_factory=TemplateLayout)
    header: TemplateRichText = field(default_factory=lambda: TemplateRichText.from_dict(None, True))
    footer: TemplateRichText = field(default_factory=lambda: TemplateRichText.from_dict(None, False))
    rules: TemplateRuleReference = field(default_factory=TemplateRuleReference)

    @property
    def id(self) -> str:
        return self.meta.id

    @property
    def name(self) -> str:
        return self.meta.name

    def with_meta(self, **changes) -> "Template":
        return replace(self, meta=replace(self.meta, **changes))

    # Bisheriges Wörterbuch einer Vorlage (Einzelmodus, Stapel, Kundenakte) ------------------------------
    def to_entry(self) -> dict:
        """Wie bis 2.7 gespeichert – plus ``id``, ``regelwerk`` (falls festgelegt) und Beschreibung."""
        entry: dict = {ENTRY_ID: self.id, "name": self.name, **self.layout.to_dict()}
        entry["kopfzeile"] = self.header.text
        entry[HEADER_FORMAT] = self.header.format
        entry["fusszeile"] = self.footer.text
        entry[FOOTER_FORMAT] = self.footer.format
        entry[FOOTER_EXPLICIT] = True
        entry["regeln"] = self.rules.cycle_list()
        if self.rules.rule_set_id is not None:
            entry[ENTRY_RULE_SET] = self.rules.rule_set_id
        if self.meta.description:
            entry[ENTRY_DESCRIPTION] = self.meta.description
        return entry

    @classmethod
    def from_entry(cls, entry: dict, template_id: str | None = None, created_at: str = "", updated_at: str = "") -> "Template":
        """Vorlage aus dem bisherigen Wörterbuch (Übernahme aus 2.7 oder ``to_entry``)."""
        stamp = updated_at or created_at or now_iso()
        ident = template_id or (entry.get(ENTRY_ID) if valid_id(entry.get(ENTRY_ID)) else None) or new_id()
        rule_set = entry.get(ENTRY_RULE_SET)
        return cls(
            meta=TemplateMetadata(
                id=ident,
                name=clean_name(entry.get("name")),
                description=str(entry.get(ENTRY_DESCRIPTION) or "")[:MAX_DESCRIPTION],
                created_at=created_at or stamp,
                updated_at=stamp,
            ),
            layout=TemplateLayout.from_dict({key: entry.get(key) for key in LAYOUT_KEYS}),
            # Dieselben Regeln wie bisher beim Anwenden: fehlende Kopfzeile = leer, fehlende
            # oder alte leere Fußzeile = Standard, fehlende Zyklus-Regeln = keine.
            header=TemplateRichText.of(header_rich_from(entry)),
            footer=TemplateRichText.of(footer_rich_from(entry)),
            rules=TemplateRuleReference(
                cycle_rules=TemplateRuleReference.cycles_from(entry.get("regeln") or []),
                rule_set_id=rule_set if isinstance(rule_set, str) else None,
            ),
        )

    # Datei ----------------------------------------------------------------------------------------
    def to_dict(self) -> dict:
        return {
            "schema_version": SCHEMA_VERSION,
            "id": self.id,
            "name": self.name,
            "description": self.meta.description,
            "created_at": self.meta.created_at,
            "updated_at": self.meta.updated_at,
            "layout": self.layout.to_dict(),
            "header": self.header.to_dict(),
            "footer": self.footer.to_dict(),
            "cycle_rules": self.rules.cycle_list(),
            "rule_set_id": self.rules.rule_set_id,
        }

    @classmethod
    def from_dict(cls, data) -> "Template":
        """Gespeicherte Vorlage lesen. ``SchemaError``/``NewerSchema`` bei ungültigen oder neueren Daten."""
        check_schema(data, SCHEMA_VERSION, KIND)
        ident = data.get("id")
        if not valid_id(ident):
            raise SchemaError(f"{KIND}: ID fehlt oder ist ungültig")
        name = clean_name(data.get("name"))
        if not name:
            raise SchemaError(f"{KIND}: Name fehlt")
        rule_set = data.get("rule_set_id")
        return cls(
            meta=TemplateMetadata(
                id=ident,
                name=name,
                description=str(data.get("description") or "")[:MAX_DESCRIPTION],
                created_at=str(data.get("created_at") or ""),
                updated_at=str(data.get("updated_at") or data.get("created_at") or ""),
            ),
            layout=TemplateLayout.from_dict(data.get("layout")),
            header=TemplateRichText.from_dict(data.get("header"), True),
            footer=TemplateRichText.from_dict(data.get("footer"), False),
            rules=TemplateRuleReference(
                cycle_rules=TemplateRuleReference.cycles_from(data.get("cycle_rules") or []),
                rule_set_id=rule_set if isinstance(rule_set, str) and (rule_set == "" or valid_id(rule_set)) else None,
            ),
        )
