"""Datenmodell der Stapelverarbeitung in »Vertragsübersichten«.

Ein ``BatchItem`` ist eine Excel-Datei im Stapel. Es speichert nur, was zu dieser Datei
gehört: Pfad, Ergebnis der Prüfung, die Art der Kundenzuordnung, bewusst im Eintrag
gesetzte Werte (``Overrides``) und das Ergebnis der Erstellung. Welche Werte tatsächlich
verwendet werden (Kundenakte, Vorlage, Logo, Zielordner …), bestimmt ``resolver`` jedes
Mal neu – Änderungen an einer Kundenakte gelten so sofort, bewusst gesetzte Werte bleiben.

Der Status ist ein ``ItemStatus`` – die Oberfläche richtet sich nach ihm, nicht nach Texten.
"""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass, field, fields
from enum import Enum
from pathlib import Path

from ..overview import ExcelAnalysis, Issue


class ItemStatus(str, Enum):
    PENDING = "pending"  # hinzugefügt, Prüfung steht aus
    ANALYZING = "analyzing"  # Excel wird geprüft
    READY = "ready"  # bereit zum Erstellen
    NEEDS_INPUT = "needs_input"  # Angaben erforderlich (Kundennummer, Firma, Empfänger, Kunde …)
    PROCESSING = "processing"  # PDF wird erstellt
    SUCCESS = "success"  # erstellt
    WARNING = "warning"  # erstellt, mit Hinweis (z. B. Name wegen einer vorhandenen PDF geändert)
    FAILED = "failed"  # Datei unbrauchbar oder Erstellung fehlgeschlagen
    SKIPPED = "skipped"  # übersprungen (PDF vorhanden, Einstellung »Überspringen«)


DONE = frozenset({ItemStatus.SUCCESS, ItemStatus.WARNING, ItemStatus.SKIPPED})
CREATED = frozenset({ItemStatus.SUCCESS, ItemStatus.WARNING})
WAITING = frozenset({ItemStatus.PENDING, ItemStatus.ANALYZING})


class ConflictMode(str, Enum):
    """Was geschieht, wenn die PDF schon existiert."""

    NUMBER = "number"  # automatisch nummerieren: …_2.pdf (Standard)
    SKIP = "skip"  # Eintrag überspringen
    OVERWRITE = "overwrite"  # vorhandene PDF ersetzen (nie eine im selben Lauf erstellte)


class CustomerMode(str, Enum):
    AUTO = "auto"  # über die Rechnungsempfänger erkannt – dieselbe Logik wie im Einzelmodus
    MANUAL = "manual"  # bewusst gewählt
    NONE = "none"  # bewusst ohne Kundenakte


@dataclass(frozen=True)
class FileStamp:
    """Größe und Änderungszeit einer Datei – erkennt Änderungen nach der Prüfung."""

    size: int
    mtime_ns: int

    @classmethod
    def of(cls, path) -> "FileStamp | None":
        try:
            stat = Path(path).stat()
        except (OSError, ValueError):
            return None
        return cls(int(stat.st_size), int(stat.st_mtime_ns))


def path_key(path) -> str:
    """Vergleichsschlüssel eines Pfads: absolut, normalisiert, unter Windows ohne Groß-/Kleinschreibung."""
    text = str(path)
    try:
        text = os.path.abspath(os.path.expanduser(text))
    except (OSError, ValueError):
        pass
    return os.path.normcase(os.path.normpath(text))


@dataclass
class Overrides:
    """Im Eintrag bewusst gesetzte Werte. ``None`` heißt: übernehmen (Kundenakte, Excel, Stapel).

    ``template=""`` bedeutet bewusst »keine Vorlage«, ``rule_set=""`` bewusst »kein Regelwerk«.
    Vorlagen und Regelwerke werden ab 2.8 über ihre ID angegeben (Namen aus 2.7 gelten weiter).
    """

    company: str | None = None
    number: str | None = None
    email: str | None = None
    template: str | None = None
    logo: str | None = None
    target_dir: str | None = None
    rule_set: str | None = None

    def to_dict(self) -> dict:
        return {item.name: getattr(self, item.name) for item in fields(self) if getattr(self, item.name) is not None}

    @classmethod
    def from_dict(cls, data) -> "Overrides":
        if not isinstance(data, dict):
            return cls()
        values = {}
        for item in fields(cls):
            value = data.get(item.name)
            if isinstance(value, str):
                values[item.name] = value
        return cls(**values)

    def any(self) -> bool:
        return bool(self.to_dict())


@dataclass
class BatchItem:
    """Eine Excel-Datei im Stapel."""

    path: str
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    status: ItemStatus = ItemStatus.PENDING
    analysis: ExcelAnalysis | None = None
    stamp: FileStamp | None = None  # Stand der Datei bei der Prüfung
    customer_mode: CustomerMode = CustomerMode.AUTO
    customer_id: str | None = None  # nur bei CustomerMode.MANUAL
    overrides: Overrides = field(default_factory=Overrides)
    issues: tuple[Issue, ...] = ()  # was fehlt (bestimmt ``resolver``)
    notes: tuple[str, ...] = ()  # Hinweise, die nicht blockieren
    output: str = ""  # erstellte PDF
    error: str = ""  # verständlicher Fehlertext
    selected: bool = False  # für Massenaktionen

    @property
    def key(self) -> str:
        return path_key(self.path)

    @property
    def name(self) -> str:
        return Path(self.path).name or self.path

    @property
    def done(self) -> bool:
        return self.status in DONE

    def reset_result(self) -> None:
        """Ergebnis einer früheren Erstellung verwerfen (der Eintrag wurde geändert)."""
        self.output = ""
        self.error = ""
        if self.status in DONE or self.status is ItemStatus.FAILED:
            self.status = ItemStatus.PENDING

    def to_dict(self) -> dict:
        """Für die Sicherung des Stapels: nur Pfade, Zuordnung, eigene Angaben und Ergebnis."""
        data: dict = {"path": self.path, "customer_mode": self.customer_mode.value}
        if self.customer_id:
            data["customer_id"] = self.customer_id
        overrides = self.overrides.to_dict()
        if overrides:
            data["overrides"] = overrides
        if self.status in DONE and self.output:
            data["result"] = {"status": self.status.value, "output": self.output, "notes": list(self.notes)}
        return data

    @classmethod
    def from_dict(cls, data) -> "BatchItem | None":
        if not isinstance(data, dict) or not isinstance(data.get("path"), str) or not data["path"].strip():
            return None
        try:
            mode = CustomerMode(data.get("customer_mode", CustomerMode.AUTO.value))
        except ValueError:
            mode = CustomerMode.AUTO
        customer_id = data.get("customer_id") if isinstance(data.get("customer_id"), str) else None
        if mode is CustomerMode.MANUAL and not customer_id:
            mode = CustomerMode.AUTO
        item = cls(path=data["path"], customer_mode=mode, customer_id=customer_id if mode is CustomerMode.MANUAL else None, overrides=Overrides.from_dict(data.get("overrides")))
        result = data.get("result")
        if isinstance(result, dict) and isinstance(result.get("output"), str):
            try:
                status = ItemStatus(result.get("status"))
            except ValueError:
                status = None
            if status in DONE:
                item.status = status
                item.output = result["output"]
                item.notes = tuple(str(note) for note in result.get("notes") or [] if isinstance(note, str))
        return item


@dataclass
class BatchSettings:
    """Gemeinsame Einstellungen des Stapels (gespeichert in den Einstellungen der App)."""

    target_dir: str = ""  # gemeinsamer Standard-Zielordner
    template: str = ""  # Standardvorlage des Stapels ("" = keine)
    logo: str = ""  # Standardlogo des Stapels ("" = das installierte Standardlogo)
    subfolders: bool = False  # Unterordner je Kunde: »123456 Beispiel GmbH«
    customer_target: bool = True  # bevorzugten Zielordner der Kundenakte verwenden
    conflict: ConflictMode = ConflictMode.NUMBER

    PREFIX = "stapel_"

    def to_config(self) -> dict:
        return {
            f"{self.PREFIX}zielordner": self.target_dir,
            f"{self.PREFIX}vorlage": self.template,
            f"{self.PREFIX}logo": self.logo,
            f"{self.PREFIX}unterordner": bool(self.subfolders),
            f"{self.PREFIX}kunden_zielordner": bool(self.customer_target),
            f"{self.PREFIX}konflikt": self.conflict.value,
        }

    @classmethod
    def from_config(cls, cfg: dict, default_target: str = "") -> "BatchSettings":
        def text(key: str, default: str = "") -> str:
            value = cfg.get(cls.PREFIX + key)
            return value.strip() if isinstance(value, str) else default

        try:
            conflict = ConflictMode(cfg.get(cls.PREFIX + "konflikt", ConflictMode.NUMBER.value))
        except ValueError:
            conflict = ConflictMode.NUMBER
        customer_target = cfg.get(cls.PREFIX + "kunden_zielordner")
        return cls(
            target_dir=text("zielordner", default_target),
            template=text("vorlage"),
            logo=text("logo"),
            subfolders=cfg.get(cls.PREFIX + "unterordner") is True,
            customer_target=customer_target if isinstance(customer_target, bool) else True,
            conflict=conflict,
        )


@dataclass
class RunSummary:
    """Ergebnis eines Durchlaufs (»Bereite Übersichten erstellen« bzw. »erneut versuchen«)."""

    total: int = 0  # Einträge, die bearbeitet werden sollten
    created: int = 0
    warnings: int = 0  # davon mit Hinweis erstellt
    skipped: int = 0  # übersprungen (PDF vorhanden) oder inzwischen nicht mehr bereit
    failed: int = 0
    cancelled: int = 0  # wegen »Stapel abbrechen« nicht mehr verarbeitet
    aborted: bool = False  # der Stapel wurde abgebrochen
    folders: list[str] = field(default_factory=list)  # Ausgabeordner (für »Ausgabeordner öffnen«)

    @property
    def processed(self) -> int:
        return self.created + self.skipped + self.failed
