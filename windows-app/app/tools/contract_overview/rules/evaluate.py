"""Regelwerk anwenden – deterministisch, nachvollziehbar, ohne die Excel zu verändern.

Ablauf je Vertrag
-----------------
1. Ausgangswerte sind die Werte der PDF ohne Regelwerk (``engine.Vertragsdaten.anzeige`` –
   bereinigte Beschreibung, Vertragsart, Zyklus-Regeln, formatierter Betrag …).
2. Die aktiven, vollständigen Regeln laufen der Reihe nach. Jede Regel prüft ihre Bedingungen
   gegen die **aktuellen** Werte – also einschließlich der Änderungen früherer Regeln.
3. Trifft sie zu, führt sie ihre Aktionen der Reihe nach aus. Ändern zwei Regeln dasselbe Feld,
   gilt die spätere (»später überschreibt früher«); die Vorschau zeigt beide.

Gleiche Eingaben und gleiche Regeln ergeben immer dasselbe Ergebnis. Die Excel-Datei wird nie
verändert – Regeln wirken nur auf die Werte der PDF (und damit auf den gespeicherten
Vertragsstand, der genau diese Werte festhält).

Texte werden ohne Groß-/Kleinschreibung und ohne äußere Leerzeichen verglichen; »–« (so steht
ein fehlender Wert in der PDF) gilt als leer. Zahl und Datum stammen aus den Rohwerten der Excel
(Netto, Beginn); Regeln können sie nicht ändern.

``Change`` ist die Spur einer Regel (Regel → Feld → alter Wert → neuer Wert). Sie dient der
Vorschau und wird nicht dauerhaft gespeichert – sie enthält Vertragsdaten.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Iterable, Sequence

from .models import (
    EMPTY_VALUES,
    FIELD,
    FIELDS,
    MATCH_ANY,
    Action,
    Condition,
    FieldType,
    Rule,
    RuleSet,
    parse_date,
    parse_number,
)


def _norm(text: str) -> str:
    return str(text or "").strip().casefold()


def is_empty(text: str) -> bool:
    return str(text or "").strip() in EMPTY_VALUES


@dataclass(frozen=True)
class Typed:
    """Zahl und Datum eines Vertrags aus den Rohwerten der Excel."""

    netto: Decimal | None = None
    beginn: date | None = None

    @classmethod
    def of(cls, vertrag) -> "Typed":
        """Aus ``engine.Vertragsdaten`` (Netto als Zahl oder Text, Beginn als ISO-Datum)."""
        return cls(parse_number(getattr(vertrag, "netto", None)), parse_date(getattr(vertrag, "beginn", None)))


@dataclass(frozen=True)
class Change:
    rule_id: str
    rule_name: str
    field: str
    before: str
    after: str


@dataclass
class Outcome:
    values: dict[str, str]
    changes: list[Change] = field(default_factory=list)
    hits: list[str] = field(default_factory=list)  # IDs der Regeln, deren Bedingungen zutrafen
    probes: list[str] = field(default_factory=list)  # Testmodus: ausgeschaltete Regeln, die zuträfen

    @property
    def changed(self) -> bool:
        return bool(self.changes)


# --- Übersetzte Regeln --------------------------------------------------------------------------------------


class _Check:
    __slots__ = ("field", "type", "operator", "text", "number", "day")

    def __init__(self, condition: Condition) -> None:
        definition = FIELD[condition.field]
        self.field = condition.field
        self.type = definition.type
        self.operator = condition.operator
        self.text = _norm(condition.value)
        self.number = parse_number(condition.value) if definition.type is FieldType.NUMBER else None
        self.day = parse_date(condition.value) if definition.type is FieldType.DATE else None

    def __call__(self, values: dict[str, str], typed: Typed) -> bool:
        op = self.operator
        if self.type is FieldType.NUMBER:
            number = typed.netto
            if op == "empty":
                return number is None
            if op == "not_empty":
                return number is not None
            if number is None:
                return False
            return {"eq": number == self.number, "ne": number != self.number, "gt": number > self.number, "lt": number < self.number, "ge": number >= self.number, "le": number <= self.number}[op]
        if self.type is FieldType.DATE:
            day = typed.beginn
            if op == "empty":
                return day is None
            if op == "not_empty":
                return day is not None
            if day is None:
                return False
            return {"before": day < self.day, "after": day > self.day, "on": day == self.day}[op]
        raw = values.get(self.field, "")
        if op == "empty":
            return is_empty(raw)
        if op == "not_empty":
            return not is_empty(raw)
        value = "" if is_empty(raw) else _norm(raw)
        if op == "equals":
            return value == self.text
        if op == "not_equals":
            return value != self.text
        if op == "contains":
            return self.text in value
        if op == "not_contains":
            return self.text not in value
        if op == "starts_with":
            return value.startswith(self.text)
        if op == "ends_with":
            return value.endswith(self.text)
        return False


class _Step:
    __slots__ = ("field", "kind", "value", "pattern")

    def __init__(self, action: Action) -> None:
        self.field = action.field
        self.kind = action.kind
        self.value = action.value
        self.pattern = re.compile(re.escape(action.find.strip()), re.IGNORECASE) if action.kind == "replace" else None

    def __call__(self, current: str) -> str:
        if self.kind == "set":
            return self.value.strip()
        if self.kind == "clear":
            return ""
        if self.kind == "replace":
            return self.pattern.sub(lambda _match: self.value, current).strip() if self.pattern else current
        base = "" if is_empty(current) else current
        if self.kind == "prefix":
            return (self.value + base) if base else self.value.strip()
        if self.kind == "suffix":
            return (base + self.value) if base else self.value.strip()
        return current


class _Compiled:
    __slots__ = ("id", "name", "any", "checks", "steps", "probe")

    def __init__(self, rule: Rule, number: int, probe: bool = False) -> None:
        self.id = rule.id
        self.name = rule.name or f"Regel {number}"
        self.any = rule.match == MATCH_ANY
        self.checks = tuple(_Check(condition) for condition in rule.conditions)
        self.steps = tuple(_Step(action) for action in rule.actions)
        self.probe = probe  # nur prüfen, nichts ändern (Testmodus für ausgeschaltete Regeln)

    def matches(self, values: dict[str, str], typed: Typed) -> bool:
        if not self.checks:
            return True  # ohne Bedingung: gilt für alle Verträge
        if self.any:
            return any(check(values, typed) for check in self.checks)
        return all(check(values, typed) for check in self.checks)


class Evaluator:
    """Ein Regelwerk, übersetzt für die Auswertung vieler Verträge (auch in Hintergrund-Threads).

    ``probe_inactive`` (nur Testmodus und Vorschau): ausgeschaltete, aber vollständige Regeln an
    ihrer Stelle mitprüfen – sie ändern nichts, ``Outcome.probes`` nennt nur, ob sie zuträfen.
    """

    def __init__(self, rule_set: RuleSet | None, probe_inactive: bool = False) -> None:
        self.rule_set = rule_set
        compiled: list[_Compiled] = []
        if rule_set is not None and rule_set.active:
            for number, rule in enumerate(rule_set.rules, 1):
                if rule.runnable():
                    compiled.append(_Compiled(rule, number))
                elif probe_inactive and not rule.active and not rule.problems():
                    compiled.append(_Compiled(rule, number, probe=True))
        self._rules: tuple[_Compiled, ...] = tuple(compiled)
        self._active = any(not rule.probe for rule in compiled)

    @property
    def active(self) -> bool:
        return self._active

    def apply(self, base: dict[str, str], typed: Typed | None = None) -> Outcome:
        """Regeln auf die Werte eines Vertrags anwenden (``base`` bleibt unverändert)."""
        values = dict(base)
        outcome = Outcome(values)
        if not self._rules:
            return outcome
        typed = typed or Typed()
        for rule in self._rules:
            if not rule.matches(values, typed):
                continue
            if rule.probe:
                outcome.probes.append(rule.id)
                continue
            outcome.hits.append(rule.id)
            for step in rule.steps:
                before = values.get(step.field, "")
                after = step(before)
                if after != before:
                    values[step.field] = after
                    outcome.changes.append(Change(rule.id, rule.name, step.field, before, after))
        return outcome

    def apply_contract(self, vertrag, base: dict[str, str]) -> Outcome:
        return self.apply(base, Typed.of(vertrag))


def evaluator_for(data: dict | RuleSet | None) -> Evaluator:
    """Regelwerk aus dem PDF-Auftrag (``RuleSet.to_dict()``) – ungültige Angaben: keines."""
    if data is None or isinstance(data, RuleSet):
        return Evaluator(data)
    from storage import SchemaError

    try:
        return Evaluator(RuleSet.from_dict(data))
    except SchemaError:
        return Evaluator(None)


# --- Vorschau: vorher → nachher ------------------------------------------------------------------------


@dataclass(frozen=True)
class FieldChange:
    field: str
    label: str
    before: str
    after: str
    rules: tuple[str, ...]  # Namen der Regeln, die das Feld geändert haben (Reihenfolge)

    @property
    def conflict(self) -> bool:
        """Mehrere Regeln haben dasselbe Feld geändert – die letzte gilt."""
        return len(self.rules) > 1


@dataclass(frozen=True)
class ContractChanges:
    nummer: str
    index: int  # Position in der Vertragsliste (eindeutig, auch bei doppelten Nummern)
    fields: tuple[FieldChange, ...]


@dataclass(frozen=True)
class RulePreview:
    total: int
    contracts: tuple[ContractChanges, ...]  # nur Verträge mit tatsächlichen Änderungen
    hits: dict[str, int]  # Regel-ID → Anzahl Verträge, auf die sie zutraf
    changed: dict[str, int]  # Regel-ID → Anzahl Verträge, die sie tatsächlich geändert hat
    fields: dict[str, int]  # Feld → Anzahl geänderter Verträge
    probes: dict[str, int] = field(default_factory=dict)  # ausgeschaltete Regel-ID → Anzahl, auf die sie zuträfe

    @property
    def affected(self) -> int:
        return len(self.contracts)

    @property
    def conflicts(self) -> int:
        return sum(1 for contract in self.contracts for change in contract.fields if change.conflict)


def summarize(outcome: Outcome, base: dict[str, str], index: int) -> ContractChanges | None:
    """Endgültige Änderungen je Feld (vorher → nachher) samt beteiligter Regeln."""
    by_field: dict[str, dict[str, str]] = {}
    for change in outcome.changes:
        by_field.setdefault(change.field, {}).setdefault(change.rule_id, change.rule_name)
    fields = tuple(
        FieldChange(definition.key, definition.label, base.get(definition.key, ""), outcome.values.get(definition.key, ""), tuple(by_field[definition.key].values()))
        for definition in FIELDS
        if definition.key in by_field and outcome.values.get(definition.key, "") != base.get(definition.key, "")
    )
    if not fields:
        return None
    return ContractChanges(base.get("nummer", ""), index, fields)


def preview(rule_set: RuleSet | None, contracts: Sequence[tuple[dict[str, str], Typed]], probe_inactive: bool = False) -> RulePreview:
    """Was das Regelwerk an diesen Verträgen ändert (Ausgangswerte und Zahl/Datum je Vertrag)."""
    evaluator = Evaluator(rule_set, probe_inactive=probe_inactive)
    hits: dict[str, int] = {}
    changed: dict[str, int] = {}
    fields: dict[str, int] = {}
    probes: dict[str, int] = {}
    affected: list[ContractChanges] = []
    for index, (base, typed) in enumerate(contracts):
        outcome = evaluator.apply(base, typed)
        for rule_id in dict.fromkeys(outcome.hits):
            hits[rule_id] = hits.get(rule_id, 0) + 1
        for rule_id in dict.fromkeys(outcome.probes):
            probes[rule_id] = probes.get(rule_id, 0) + 1
        for rule_id in dict.fromkeys(change.rule_id for change in outcome.changes):
            changed[rule_id] = changed.get(rule_id, 0) + 1
        summary = summarize(outcome, base, index)
        if summary is not None:
            affected.append(summary)
            for change in summary.fields:
                fields[change.field] = fields.get(change.field, 0) + 1
    return RulePreview(len(contracts), tuple(affected), hits, changed, fields, probes)


def contract_inputs(vertraege: Iterable, regeln=None) -> list[tuple[dict[str, str], Typed]]:
    """Ausgangswerte (wie in der PDF ohne Regelwerk) und Zahl/Datum je ``engine.Vertragsdaten``."""
    return [(vertrag.anzeige(regeln), Typed.of(vertrag)) for vertrag in vertraege]
