"""Darstellung eines Vergleichs: Feldnamen, Werte und »Änderungen als Text kopieren«.

Die Einordnung (neu, entfernt, geändert, unverändert) steht im Modell; hier werden
nur Texte für Anzeige und Zwischenablage gebildet.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation

from .models import ChangeKind, ContractChange, ContractComparison, ContractRecord, FieldChange, Snapshot

FIELD_LABELS = {
    "contract_type": "Art",
    "description": "Beschreibung",
    "start_date": "Beginn",
    "billing_cycle": "Abrechnungszyklus",
    "net_amount": "Netto",
    "payment_method": "Zahlungsart",
}
KIND_LABELS = {
    ChangeKind.ADDED: "Neu",
    ChangeKind.REMOVED: "Entfernt",
    ChangeKind.CHANGED: "Geändert",
    ChangeKind.UNCHANGED: "Unverändert",
}
NO_HISTORY = "Noch kein früherer Vertragsstand vorhanden."


def euro(value: str | None) -> str:
    """»1234.50« → »1.234,50 €« (anderer Text bleibt, wie er ist)."""
    if value in (None, ""):
        return "–"
    try:
        number = Decimal(str(value))
    except InvalidOperation:
        return str(value)
    return f"{number:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") + " €"


def format_value(field: str, value: str | None) -> str:
    if value in (None, ""):
        return "–"
    if field == "start_date":
        try:
            return datetime.strptime(str(value), "%Y-%m-%d").strftime("%d.%m.%Y")
        except ValueError:
            return str(value)
    if field == "net_amount":
        return euro(value)
    return str(value)


def change_text(change: FieldChange) -> str:
    """»Netto: 250,00 € → 270,00 €«"""
    return f"{FIELD_LABELS.get(change.field, change.field)}: {format_value(change.field, change.old_value)} → {format_value(change.field, change.new_value)}"


def contract_title(record: ContractRecord) -> str:
    """»10001 GetSolar« – Vertragsnummer und Beschreibung."""
    description = " ".join(record.description.split())
    return f"{record.contract_number} {description}".strip()


def stand_label(snapshot: Snapshot, with_time: bool = True) -> str:
    """»12.08.2026, 14:03« – Zeitpunkt, zu dem der Stand gespeichert wurde."""
    created = snapshot.created.astimezone()
    return created.strftime("%d.%m.%Y, %H:%M") if with_time else created.strftime("%d.%m.%Y")


def plural(count: int, one: str, many: str) -> str:
    return f"{count} {one if count == 1 else many}"


def counts_text(comparison: ContractComparison) -> str:
    """»2 neu · 1 entfernt · 3 geändert · 4 unverändert« (nur vorhandene Kategorien)."""
    counts = comparison.counts()
    parts = []
    for kind, label in ((ChangeKind.ADDED, "neu"), (ChangeKind.REMOVED, "entfernt"), (ChangeKind.CHANGED, "geändert"), (ChangeKind.UNCHANGED, "unverändert")):
        if counts[kind]:
            parts.append(f"{counts[kind]} {label}")
    return " · ".join(parts) if parts else "keine Verträge"


def badges(comparison: ContractComparison | None) -> str:
    """Kompakt für Listen, z. B. »+2 neu · ~1 geändert · −1 entfernt« – leer ohne Änderungen."""
    if comparison is None or not comparison.has_baseline:
        return ""
    counts = comparison.counts()
    parts = []
    if counts[ChangeKind.ADDED]:
        parts.append(f"+{counts[ChangeKind.ADDED]} neu")
    if counts[ChangeKind.CHANGED]:
        parts.append(f"~{counts[ChangeKind.CHANGED]} geändert")
    if counts[ChangeKind.REMOVED]:
        parts.append(f"−{counts[ChangeKind.REMOVED]} entfernt")
    return " · ".join(parts)


def _block(title: str, changes: list[ContractChange], details: bool) -> list[str]:
    lines = [f"{title} ({len(changes)})"]
    for change in changes:
        lines.append(f"  {contract_title(change.record)}")
        if details:
            lines += [f"    {change_text(field)}" for field in change.fields]
    return lines


def comparison_text(comparison: ContractComparison, customer: str = "") -> str:
    """Änderungen als Text für die Zwischenablage (nur Vertragsdaten, keine Pfade)."""
    title = "Vertragsänderungen" + (f" – {customer}" if customer else "")
    if comparison.baseline is None:
        return f"{title}\n{NO_HISTORY}\n"
    lines = [title, f"Verglichen mit dem Stand vom {stand_label(comparison.baseline)}", ""]
    if not comparison.has_changes:
        lines.append(f"Keine Änderungen – {plural(len(comparison.unchanged), 'Vertrag', 'Verträge')} unverändert.")
        return "\n".join(lines) + "\n"
    for label, changes, details in (("Neu", list(comparison.added), False), ("Entfernt", list(comparison.removed), False), ("Geändert", list(comparison.changed), True)):
        if changes:
            lines += _block(label, changes, details)
            lines.append("")
    lines.append(f"Unverändert: {plural(len(comparison.unchanged), 'Vertrag', 'Verträge')}")
    return "\n".join(lines) + "\n"
