"""Regelwerk 2.0: deklarative Regeln für die Werte einer Vertragsübersicht.

Ein Regelwerk (``RuleSet``) enthält sortierte Regeln (``Rule``). Eine Regel prüft Bedingungen
(``Condition``) – alle oder mindestens eine – und führt dann ihre Aktionen (``Action``) aus.
Es gibt keine Skripte, keinen Code und keine regulären Ausdrücke der Benutzer: nur die hier
festgelegten Felder, Vergleiche und Aktionen.

Felder sind genau die Spalten der Vertragsübersicht (``engine.Vertragsdaten.anzeige``):

=================  =================  ========  ==========================================
Schlüssel          Anzeige            Typ       änderbar
=================  =================  ========  ==========================================
``nummer``         Vertragsnummer     Text      nein – Identität im Vertragsvergleich
``art``            Art                Text      ja
``beschreibung``   Beschreibung       Text      ja
``beginn``         Beginn             Datum     nein
``zyklus``         Abrechnungszyklus  Text      ja
``netto``          Netto              Zahl      nein – Beträge verändert kein Regelwerk
``zahlungsart``    Zahlungsart        Text      ja
=================  =================  ========  ==========================================

Ein Vertragsende gibt es in den Vertragslisten nicht – daher auch kein solches Feld.

Gespeichert wird je Regelwerk eine JSON-Datei mit ``schema_version`` (``repository.py``).
Ungültige Bedingungen oder Aktionen (z. B. »Netto größer als abc«) bleiben gespeichert und
werden angezeigt; die Regel wird dann nie ausgeführt (``Rule.problems``).
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field, replace
from datetime import date, datetime
from decimal import Decimal
from enum import Enum

from storage import SchemaError, check_schema, safe_id

SCHEMA_VERSION = 1
KIND = "Regelwerk"
MAX_NAME = 120
MAX_TEXT = 500
MATCH_ALL = "all"
MATCH_ANY = "any"
EMPTY_VALUES = ("", "–", "-")  # so erscheinen fehlende Werte in der PDF


class FieldType(str, Enum):
    TEXT = "text"
    NUMBER = "number"
    DATE = "date"


@dataclass(frozen=True)
class FieldDef:
    key: str
    label: str
    type: FieldType
    editable: bool


FIELDS: tuple[FieldDef, ...] = (
    FieldDef("nummer", "Vertragsnummer", FieldType.TEXT, False),
    FieldDef("art", "Art", FieldType.TEXT, True),
    FieldDef("beschreibung", "Beschreibung", FieldType.TEXT, True),
    FieldDef("beginn", "Beginn", FieldType.DATE, False),
    FieldDef("zyklus", "Abrechnungszyklus", FieldType.TEXT, True),
    FieldDef("netto", "Netto", FieldType.NUMBER, False),
    FieldDef("zahlungsart", "Zahlungsart", FieldType.TEXT, True),
)
FIELD = {definition.key: definition for definition in FIELDS}
EDITABLE = tuple(definition.key for definition in FIELDS if definition.editable)


@dataclass(frozen=True)
class OperatorDef:
    key: str
    label: str
    needs_value: bool = True


OPERATORS: dict[FieldType, tuple[OperatorDef, ...]] = {
    FieldType.TEXT: (
        OperatorDef("equals", "ist gleich"),
        OperatorDef("not_equals", "ist nicht gleich"),
        OperatorDef("contains", "enthält"),
        OperatorDef("not_contains", "enthält nicht"),
        OperatorDef("starts_with", "beginnt mit"),
        OperatorDef("ends_with", "endet mit"),
        OperatorDef("empty", "ist leer", False),
        OperatorDef("not_empty", "ist nicht leer", False),
    ),
    FieldType.NUMBER: (
        OperatorDef("eq", "gleich"),
        OperatorDef("ne", "ungleich"),
        OperatorDef("gt", "größer als"),
        OperatorDef("lt", "kleiner als"),
        OperatorDef("ge", "größer oder gleich"),
        OperatorDef("le", "kleiner oder gleich"),
        OperatorDef("empty", "ist leer", False),
        OperatorDef("not_empty", "ist nicht leer", False),
    ),
    FieldType.DATE: (
        OperatorDef("before", "vor"),
        OperatorDef("after", "nach"),
        OperatorDef("on", "am"),
        OperatorDef("empty", "ist leer", False),
        OperatorDef("not_empty", "ist nicht leer", False),
    ),
}


@dataclass(frozen=True)
class ActionDef:
    key: str
    label: str
    needs_value: bool = True


ACTIONS: tuple[ActionDef, ...] = (
    ActionDef("set", "setzen auf"),
    ActionDef("replace", "Text ersetzen"),
    ActionDef("prefix", "Präfix hinzufügen"),
    ActionDef("suffix", "Suffix hinzufügen"),
    ActionDef("clear", "leeren", False),
)
ACTION = {definition.key: definition for definition in ACTIONS}


def operator_def(field_key: str, operator: str) -> OperatorDef | None:
    definition = FIELD.get(field_key)
    if definition is None:
        return None
    return next((op for op in OPERATORS[definition.type] if op.key == operator), None)


def new_id() -> str:
    return str(uuid.uuid4())


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="microseconds")


def clean_name(value) -> str:
    return " ".join(str(value or "").split())[:MAX_NAME]


def _text(value, limit: int = MAX_TEXT) -> str:
    if value is None or isinstance(value, bool):
        return ""
    if isinstance(value, (int, float)):
        return f"{value:g}" if isinstance(value, float) else str(value)
    return str(value)[:limit] if isinstance(value, str) else ""


# --- Werte lesen ----------------------------------------------------------------------------------------


def parse_number(text) -> Decimal | None:
    """Zahl wie in der PDF: »1.234,50«, »1234,5«, »49.90« oder »12«."""
    from tools.contract_overview.history.models import amount

    if isinstance(text, str) and not text.strip():
        return None
    return amount(text)


_DATE_DE = re.compile(r"^\s*(\d{1,2})\.(\d{1,2})\.(\d{4})\s*$")
_DATE_ISO = re.compile(r"^\s*(\d{4})-(\d{2})-(\d{2})\s*$")


def parse_date(text) -> date | None:
    """Datum »TT.MM.JJJJ« (wie in der PDF) oder ISO »JJJJ-MM-TT«."""
    if isinstance(text, date):
        return text
    raw = str(text or "")
    for pattern, order in ((_DATE_DE, (3, 2, 1)), (_DATE_ISO, (1, 2, 3))):
        match = pattern.match(raw)
        if match:
            try:
                return date(int(match.group(order[0])), int(match.group(order[1])), int(match.group(order[2])))
            except ValueError:
                return None
    return None


# --- Bedingungen, Aktionen, Regeln --------------------------------------------------------------------------


@dataclass(frozen=True)
class Condition:
    field: str = "beschreibung"
    operator: str = "contains"
    value: str = ""

    def problem(self) -> str:
        definition = FIELD.get(self.field)
        if definition is None:
            return "Unbekanntes Feld"
        op = operator_def(self.field, self.operator)
        if op is None:
            return "Dieser Vergleich passt nicht zum Feld"
        if not op.needs_value:
            return ""
        if not self.value.strip():
            return "Wert fehlt"
        if definition.type is FieldType.NUMBER and parse_number(self.value) is None:
            return "Keine gültige Zahl"
        if definition.type is FieldType.DATE and parse_date(self.value) is None:
            return "Kein gültiges Datum (TT.MM.JJJJ)"
        return ""

    def to_dict(self) -> dict:
        return {"field": self.field, "operator": self.operator, "value": self.value}

    @classmethod
    def from_dict(cls, data) -> "Condition":
        return cls(_text(data.get("field"), 40), _text(data.get("operator"), 40), _text(data.get("value")))


@dataclass(frozen=True)
class Action:
    kind: str = "set"
    field: str = "art"
    value: str = ""
    find: str = ""  # nur »Text ersetzen«: zu ersetzender Text

    def problem(self) -> str:
        definition = ACTION.get(self.kind)
        if definition is None:
            return "Unbekannte Aktion"
        target = FIELD.get(self.field)
        if target is None:
            return "Unbekanntes Feld"
        if not target.editable:
            return f"»{target.label}« kann nicht geändert werden"
        if self.kind == "replace" and not self.find.strip():
            return "Zu ersetzender Text fehlt"
        if self.kind in ("set", "prefix", "suffix") and not self.value.strip():
            return "Wert fehlt"
        return ""

    def to_dict(self) -> dict:
        data = {"type": self.kind, "field": self.field, "value": self.value}
        if self.kind == "replace":
            data["find"] = self.find
        return data

    @classmethod
    def from_dict(cls, data) -> "Action":
        return cls(_text(data.get("type"), 40), _text(data.get("field"), 40), _text(data.get("value")), _text(data.get("find")))


@dataclass(frozen=True)
class Rule:
    id: str
    name: str = ""
    active: bool = True
    match: str = MATCH_ALL
    conditions: tuple[Condition, ...] = ()
    actions: tuple[Action, ...] = ()

    def problems(self) -> list[str]:
        """Gründe, warum die Regel nicht ausgeführt wird (leer: ausführbar)."""
        found: list[str] = []
        if self.match not in (MATCH_ALL, MATCH_ANY):
            found.append("Unbekannte Verknüpfung der Bedingungen")
        for index, condition in enumerate(self.conditions, 1):
            reason = condition.problem()
            if reason:
                found.append(f"Bedingung {index}: {reason}")
        if not self.actions:
            found.append("Keine Aktion")
        for index, action in enumerate(self.actions, 1):
            reason = action.problem()
            if reason:
                found.append(f"Aktion {index}: {reason}")
        return found

    def runnable(self) -> bool:
        return self.active and not self.problems()

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "active": self.active,
            "match": self.match,
            "conditions": [condition.to_dict() for condition in self.conditions],
            "actions": [action.to_dict() for action in self.actions],
        }

    @classmethod
    def from_dict(cls, data) -> "Rule":
        if not isinstance(data, dict):
            raise SchemaError(f"{KIND}: Regel ist kein Datensatz")
        ident = data.get("id")
        if not safe_id(ident):
            raise SchemaError(f"{KIND}: Regel ohne gültige ID")
        match = data.get("match")
        return cls(
            id=ident,
            name=clean_name(data.get("name")),
            active=data.get("active") is not False,
            match=match if match in (MATCH_ALL, MATCH_ANY) else MATCH_ALL,
            conditions=tuple(Condition.from_dict(item) for item in data.get("conditions") or [] if isinstance(item, dict)),
            actions=tuple(Action.from_dict(item) for item in data.get("actions") or [] if isinstance(item, dict)),
        )


@dataclass(frozen=True)
class RuleSet:
    id: str
    name: str
    description: str = ""
    active: bool = True
    rules: tuple[Rule, ...] = ()
    created_at: str = ""
    updated_at: str = ""

    def with_(self, **changes) -> "RuleSet":
        return replace(self, **changes)

    def rule(self, rule_id: str) -> Rule | None:
        return next((rule for rule in self.rules if rule.id == rule_id), None)

    def runnable_rules(self) -> tuple[Rule, ...]:
        return tuple(rule for rule in self.rules if rule.runnable()) if self.active else ()

    def to_dict(self) -> dict:
        return {
            "schema_version": SCHEMA_VERSION,
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "active": self.active,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "rules": [rule.to_dict() for rule in self.rules],
        }

    @classmethod
    def from_dict(cls, data) -> "RuleSet":
        check_schema(data, SCHEMA_VERSION, KIND)
        ident = data.get("id")
        if not safe_id(ident):
            raise SchemaError(f"{KIND}: ID fehlt oder ist ungültig")
        name = clean_name(data.get("name"))
        if not name:
            raise SchemaError(f"{KIND}: Name fehlt")
        rules: list[Rule] = []
        seen: set[str] = set()
        for item in data.get("rules") or []:
            rule = Rule.from_dict(item)
            if rule.id in seen:
                raise SchemaError(f"{KIND}: Regel-ID doppelt")
            seen.add(rule.id)
            rules.append(rule)
        return cls(
            id=ident,
            name=name,
            description=_text(data.get("description"), 2000),
            active=data.get("active") is not False,
            rules=tuple(rules),
            created_at=str(data.get("created_at") or ""),
            updated_at=str(data.get("updated_at") or data.get("created_at") or ""),
        )

    def fingerprint(self) -> str:
        """Kurzer Schlüssel des Inhalts (Vorschau, Vergleich: »haben sich die Regeln geändert?«)."""
        import hashlib
        import json

        payload = json.dumps({"active": self.active, "rules": [rule.to_dict() for rule in self.rules]}, ensure_ascii=False, sort_keys=True)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def new_rule(name: str = "") -> Rule:
    """Neue Regel mit einer leeren Bedingung und einer leeren Aktion (zum Ausfüllen)."""
    return Rule(id=new_id(), name=clean_name(name), conditions=(Condition(),), actions=(Action(),))
