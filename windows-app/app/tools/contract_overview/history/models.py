"""Vertragsstände (Snapshots) und das Ergebnis eines Vergleichs.

Ein Vertrag wird mit den Werten gespeichert, die tatsächlich in der Vertragsübersicht
stehen (``effective``: bereinigte Bemerkung, angewendeter Zyklus, Zahlungsart,
Vertragsart) – dazu die Rohwerte der Excel. Verglichen werden nur die normalisierten
Vertragsdaten: keine Formatierung (Fettschrift, Schrift, Farbe), keine Pfade, keine Zeiten.

Normalisierung
--------------
* Vertragsnummer: immer Text (»001234« bleibt »001234«)
* Datum: ISO »JJJJ-MM-TT«
* Betrag: ``Decimal`` auf zwei Nachkommastellen, gespeichert als Text (»250.00«)
* Text: einheitliche Zeilenenden, äußere Leerzeichen entfernt – sonst unverändert
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass, field
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from enum import Enum

SCHEMA_VERSION = 1
CENT = Decimal("0.01")


class ChangeKind(str, Enum):
    ADDED = "added"
    REMOVED = "removed"
    CHANGED = "changed"
    UNCHANGED = "unchanged"


# Vergleichsrelevante Felder – in der Reihenfolge der Anzeige
FIELDS = ("contract_type", "description", "start_date", "billing_cycle", "net_amount", "payment_method")


# --- Normalisierung ------------------------------------------------------------------------------


def clean_text(value) -> str:
    """Zeilenenden vereinheitlichen, äußere Leerzeichen entfernen – keine weiteren Eingriffe."""
    if value is None:
        return ""
    return str(value).replace("\r\n", "\n").replace("\r", "\n").strip()


def amount(value) -> Decimal | None:
    """Betrag als ``Decimal`` (zwei Nachkommastellen) – nie über ``float`` gerundet gespeichert.

    Texte werden gelesen wie in der PDF: »1.234,50 €« und »49.90« ergeben 1234.50 bzw. 49.90.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        number = Decimal(value)
    elif isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return None
        number = Decimal(repr(value))
    elif isinstance(value, Decimal):
        number = value
    else:
        text = re.sub(r"[^\d,.\-]", "", str(value))
        if not re.search(r"\d", text):
            return None
        if "," in text:
            text = text.replace(".", "").replace(",", ".")
        try:
            number = Decimal(text)
        except InvalidOperation:
            return None
    if not number.is_finite():
        return None
    return number.quantize(CENT, rounding=ROUND_HALF_UP)


def iso_date(value) -> str | None:
    """»2026-01-01« aus ISO-Text, ``date``/``datetime`` – sonst ``None``."""
    if value is None:
        return None
    if hasattr(value, "strftime"):
        return value.strftime("%Y-%m-%d")
    text = str(value).strip()
    match = re.match(r"^(\d{4})-(\d{2})-(\d{2})", text)
    if not match:
        return None
    try:
        return datetime(int(match.group(1)), int(match.group(2)), int(match.group(3))).strftime("%Y-%m-%d")
    except ValueError:
        return None


# --- Vertrag ------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class ContractRecord:
    """Ein Vertrag eines Vertragsstands. Identität ist allein die Vertragsnummer."""

    contract_number: str
    contract_type: str = ""
    description: str = ""
    start_date: str | None = None  # ISO
    billing_cycle: str = ""
    net_amount: str | None = None  # Decimal als Text, z. B. »250.00«; None: kein lesbarer Betrag
    net_text: str = ""  # Anzeige in der PDF, z. B. »250,00« (auch für nicht lesbare Beträge)
    payment_method: str = ""
    raw: dict = field(default_factory=dict, compare=False, hash=False)
    source_row: int | None = field(default=None, compare=False)

    def value(self, name: str) -> str | None:
        """Normalisierter Vergleichswert eines Felds."""
        if name == "net_amount":
            return self.net_amount if self.net_amount is not None else (self.net_text or None)
        return getattr(self, name)

    def comparable(self) -> list:
        return [self.contract_number, *(self.value(name) for name in FIELDS)]

    def to_dict(self) -> dict:
        return {
            "contract_number": self.contract_number,
            "effective": {
                "contract_type": self.contract_type,
                "description": self.description,
                "start_date": self.start_date,
                "billing_cycle": self.billing_cycle,
                "net_amount": self.net_amount,
                "net_text": self.net_text,
                "payment_method": self.payment_method,
            },
            "raw": dict(self.raw),
            "source_row": self.source_row,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ContractRecord":
        effective = data.get("effective") or {}
        net = effective.get("net_amount")
        parsed = amount(net) if net is not None else None
        row = data.get("source_row")
        return cls(
            contract_number=str(data.get("contract_number") or ""),
            contract_type=clean_text(effective.get("contract_type")),
            description=clean_text(effective.get("description")),
            start_date=iso_date(effective.get("start_date")),
            billing_cycle=clean_text(effective.get("billing_cycle")),
            net_amount=None if parsed is None else str(parsed),
            net_text=clean_text(effective.get("net_text")),
            payment_method=clean_text(effective.get("payment_method")),
            raw={str(k): (None if v is None else str(v)) for k, v in (data.get("raw") or {}).items()},
            source_row=int(row) if isinstance(row, int) else None,
        )


def _evaluator(regelwerk):
    """Regelwerk als ``Evaluator`` (aus ``RuleSet``, gespeichertem Wörterbuch oder bereits übersetzt)."""
    if regelwerk is None or hasattr(regelwerk, "apply_contract"):
        return regelwerk
    from ..rules.evaluate import evaluator_for

    return evaluator_for(regelwerk)


def record_from(vertrag, regeln=None, regelwerk=None) -> ContractRecord:
    """Vertrag aus ``engine.Vertragsdaten`` – mit denselben Regeln wie in der PDF.

    ``regelwerk``: Regelwerk 2.0 der PDF – der Vertragsstand hält genau die exportierten Werte fest.
    """
    shown = vertrag.ausgabe(regeln, _evaluator(regelwerk))
    total = amount(vertrag.netto)
    return ContractRecord(
        contract_number=clean_text(vertrag.nummer),
        contract_type=clean_text(shown["art"]),
        description=clean_text(shown["beschreibung"]),
        start_date=vertrag.beginn,
        billing_cycle=clean_text(shown["zyklus"]),
        net_amount=None if total is None else str(total),
        net_text=clean_text(shown["netto"]),
        payment_method=clean_text(shown["zahlungsart"]),
        raw={
            "bemerkung": vertrag.bemerkung,
            "beginn": vertrag.beginn_roh or None,
            "zyklus": vertrag.zyklus,
            "netto": None if vertrag.netto is None else str(vertrag.netto),
            "zahlungsart": vertrag.zahlungsart,
        },
        source_row=vertrag.zeile,
    )


def records_from(vertraege, regeln=None, regelwerk=None) -> tuple[ContractRecord, ...]:
    evaluator = _evaluator(regelwerk)
    return tuple(record_from(vertrag, regeln, evaluator) for vertrag in vertraege)


def content_hash(records) -> str:
    """Deterministisch aus den normalisierten Vertragsdaten – ohne Pfade, Zeiten oder Einstellungen.

    Unabhängig von der Reihenfolge: Derselbe Vertragsstand ergibt immer denselben Wert.
    """
    items = sorted((record.comparable() for record in records), key=lambda item: json.dumps(item, ensure_ascii=False))
    payload = json.dumps({"schema": SCHEMA_VERSION, "contracts": items}, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# --- Vertragsstand -----------------------------------------------------------------------------------------


@dataclass(frozen=True)
class SnapshotSource:
    """Woher der Stand stammt. Die Dateien selbst werden für den Vergleich nicht gebraucht."""

    excel_path: str = ""
    excel_sha256: str = ""
    pdf_path: str = ""

    def to_dict(self) -> dict:
        return {"excel_path": self.excel_path, "excel_sha256": self.excel_sha256, "pdf_path": self.pdf_path}

    @classmethod
    def from_dict(cls, data: dict | None) -> "SnapshotSource":
        data = data or {}
        return cls(str(data.get("excel_path") or ""), str(data.get("excel_sha256") or ""), str(data.get("pdf_path") or ""))


@dataclass(frozen=True)
class Snapshot:
    id: str
    customer_id: str
    created_at: str  # ISO 8601 mit Zeitzone
    contracts: tuple[ContractRecord, ...]
    content_hash: str
    source: SnapshotSource = SnapshotSource()
    customer_label: str = ""  # »Beispiel GmbH · 123456« zum Zeitpunkt des Exports (nur Anzeige)
    last_exported_at: str = ""  # letzter Export mit genau diesem Stand
    export_count: int = 1
    schema_version: int = SCHEMA_VERSION

    @property
    def created(self) -> datetime:
        return parse_time(self.created_at)

    @property
    def exported(self) -> datetime:
        return parse_time(self.last_exported_at or self.created_at)

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "id": self.id,
            "customer_id": self.customer_id,
            "created_at": self.created_at,
            "last_exported_at": self.last_exported_at or self.created_at,
            "export_count": self.export_count,
            "content_hash": self.content_hash,
            "customer_label": self.customer_label,
            "source": self.source.to_dict(),
            "contracts": [record.to_dict() for record in self.contracts],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Snapshot":
        version = int(data.get("schema_version") or 1)
        if version > SCHEMA_VERSION:
            raise ValueError(f"Vertragsstand im neueren Format {version}")
        contracts = tuple(ContractRecord.from_dict(item) for item in data.get("contracts") or [] if isinstance(item, dict))
        created = str(data.get("created_at") or "")
        parse_time(created)  # ungültige Zeitangabe: Datei gilt als beschädigt
        return cls(
            id=str(data.get("id") or ""),
            customer_id=str(data.get("customer_id") or ""),
            created_at=created,
            contracts=contracts,
            content_hash=str(data.get("content_hash") or content_hash(contracts)),
            source=SnapshotSource.from_dict(data.get("source")),
            customer_label=str(data.get("customer_label") or ""),
            last_exported_at=str(data.get("last_exported_at") or created),
            export_count=max(1, int(data.get("export_count") or 1)),
            schema_version=SCHEMA_VERSION,
        )


def parse_time(text: str) -> datetime:
    value = datetime.fromisoformat(str(text))
    return value if value.tzinfo is not None else value.astimezone()


# --- Vergleich -------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class FieldChange:
    field: str
    old_value: str | None
    new_value: str | None


@dataclass(frozen=True)
class ContractChange:
    kind: ChangeKind
    key: str  # Vertragsnummer, bei mehrfach vorkommender Nummer »10001#2«
    old: ContractRecord | None = None
    new: ContractRecord | None = None
    fields: tuple[FieldChange, ...] = ()

    @property
    def record(self) -> ContractRecord:
        return self.new if self.new is not None else self.old  # type: ignore[return-value]

    @property
    def contract_number(self) -> str:
        return self.record.contract_number


@dataclass(frozen=True)
class ContractComparison:
    """Aktueller Stand gegenüber einem gespeicherten Stand (``baseline``)."""

    baseline: Snapshot | None
    current: tuple[ContractRecord, ...]
    added: tuple[ContractChange, ...] = ()
    removed: tuple[ContractChange, ...] = ()
    changed: tuple[ContractChange, ...] = ()
    unchanged: tuple[ContractChange, ...] = ()

    @property
    def has_baseline(self) -> bool:
        return self.baseline is not None

    @property
    def has_changes(self) -> bool:
        return bool(self.added or self.removed or self.changed)

    def counts(self) -> dict[ChangeKind, int]:
        return {
            ChangeKind.ADDED: len(self.added),
            ChangeKind.REMOVED: len(self.removed),
            ChangeKind.CHANGED: len(self.changed),
            ChangeKind.UNCHANGED: len(self.unchanged),
        }

    def changes(self, include_unchanged: bool = False) -> list[ContractChange]:
        """Neu, entfernt, geändert – optional danach die unveränderten."""
        items = [*self.added, *self.removed, *self.changed]
        if include_unchanged:
            items += list(self.unchanged)
        return items
