"""Vergleich zweier Vertragsstände – ohne Oberfläche, ohne Dateizugriff.

Identität eines Vertrags ist die Vertragsnummer (als Text). Gleiche Nummer: derselbe
Vertrag (geändert oder unverändert); neue Nummer: neu; fehlende Nummer: entfernt.
Eine geänderte Vertragsnummer ergibt »entfernt« und »neu« – zusammengeführt wird nie
nach Ähnlichkeit. Beide Stände werden einmal über ein Wörterbuch nach Vertragsnummer
erschlossen (linearer Aufwand, auch bei großen Listen).
"""

from __future__ import annotations

from typing import Iterable, Sequence

from .models import FIELDS, ChangeKind, ContractChange, ContractComparison, ContractRecord, FieldChange, Snapshot


def keyed(records: Iterable[ContractRecord]) -> dict[str, ContractRecord]:
    """Verträge nach Vertragsnummer in ihrer Reihenfolge. Kommt eine Nummer mehrfach vor,
    wird das n-te Vorkommen mit dem n-ten verglichen (»10001«, »10001#2« …)."""
    result: dict[str, ContractRecord] = {}
    seen: dict[str, int] = {}
    for record in records:
        number = record.contract_number
        seen[number] = seen.get(number, 0) + 1
        key = number if seen[number] == 1 else f"{number}#{seen[number]}"
        result[key] = record
    return result


def field_changes(old: ContractRecord, new: ContractRecord) -> tuple[FieldChange, ...]:
    """Alle geänderten Felder mit altem und neuem (normalisiertem) Wert."""
    changes = []
    for name in FIELDS:
        before, after = old.value(name), new.value(name)
        if before != after:
            changes.append(FieldChange(name, before, after))
    return tuple(changes)


def compare(baseline: Snapshot | None, current: Sequence[ContractRecord]) -> ContractComparison:
    """Aktuelle Verträge gegenüber ``baseline``. Ohne gespeicherten Stand gibt es keinen Vergleich."""
    current = tuple(current)
    if baseline is None:
        return ContractComparison(None, current)
    old = keyed(baseline.contracts)
    new = keyed(current)
    added, changed, unchanged = [], [], []
    for key, record in new.items():
        before = old.get(key)
        if before is None:
            added.append(ContractChange(ChangeKind.ADDED, key, None, record))
            continue
        fields = field_changes(before, record)
        if fields:
            changed.append(ContractChange(ChangeKind.CHANGED, key, before, record, fields))
        else:
            unchanged.append(ContractChange(ChangeKind.UNCHANGED, key, before, record))
    removed = [ContractChange(ChangeKind.REMOVED, key, record, None) for key, record in old.items() if key not in new]
    return ContractComparison(baseline, current, tuple(added), tuple(removed), tuple(changed), tuple(unchanged))
