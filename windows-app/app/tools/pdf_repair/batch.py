"""Mehrere PDFs reparieren: Dateiliste, Status je Datei, Ausgabenamen, Reihenfolge.

Die Reparatur selbst bleibt die Engine aus 2.7.0 – je Datei genau wie im Einzelmodus:
``engine.analyze`` und ``engine.repair`` in einem eigenen Arbeitsprozess (``process.Job``),
Übernahme der geprüften Ausgabe mit ``process.deliver``. Es gibt keine zweite »Batch-Engine«:
Dieses Modul entscheidet nur, *welche* Datei als Nächstes analysiert oder repariert wird, und
bestimmt die Ausgabenamen.

Ausgabenamen
------------
* Automatisch (``NameMode.AUTO``): Originalname, mit eingeschaltetem Schalter »„repariert“
  anhängen« plus Zusatz (Standard ``_repariert`` – wie bis 2.7.0: ``Rechnung_repariert.pdf``).
* Vom Benutzer festgelegt (``NameMode.MANUAL``): bleibt, auch wenn sich die Regel ändert –
  bis »Automatischen Namen wiederherstellen«.
* Immer eindeutig: Gibt es den Namen schon im Zielordner (ohne Rücksicht auf Groß-/Klein-
  schreibung, wie unter Windows), ist er das Original oder plant ihn bereits eine andere Datei
  der Liste, wird nummeriert: ``Rechnung_repariert (1).pdf``, ``(2)`` … Beim Start eines
  Durchlaufs werden die Namen aller beteiligten Dateien festgelegt (reserviert); gespeichert
  wird exklusiv – eine vorhandene Datei, insbesondere das Original, wird nie überschrieben.

Nur Standardbibliothek; Entscheidungen fallen anhand der Statusklassen, nie anhand von Texten.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import Enum
from itertools import count
from pathlib import Path
from typing import Callable, Iterable

from .models import Condition, PdfAnalysis, PdfRepairResult, RepairMode, RepairStatus

DEFAULT_SUFFIX = "_repariert"
FORBIDDEN_CHARS = '<>:"/\\|?*'
RESERVED_NAMES = {"CON", "PRN", "AUX", "NUL", *(f"COM{n}" for n in range(1, 10)), *(f"LPT{n}" for n in range(1, 10))}
MAX_BASE = 150  # Zeichen ohne ».pdf« – lässt Platz für Ordnerpfad und Nummer (Windows: 260 Zeichen)


class ItemState(str, Enum):
    """Zustand einer Datei der Liste."""

    PENDING = "pending"  # wartet auf die Analyse
    ANALYZING = "analyzing"
    READY = "ready"  # analysiert, kann repariert (bzw. neu aufgebaut) werden
    ENCRYPTED = "encrypted"  # Passwort fehlt oder ist falsch
    UNREADABLE = "unreadable"  # keine Reparatur möglich (ggf. Rettungsmodus)
    REPAIRING = "repairing"
    REPAIRED = "repaired"
    PARTIALLY_RECOVERED = "partially_recovered"
    FAILED = "failed"  # Analyse oder Reparatur fehlgeschlagen
    CANCELLED = "cancelled"  # abgebrochen (Analyse oder Reparatur)
    SKIPPED = "skipped"  # im Durchlauf übersprungen (z. B. keine Reparatur nötig, Passwort fehlt)


class NameMode(str, Enum):
    AUTO = "auto"  # Namensregel (Schalter, Zusatz) bestimmt den Namen
    MANUAL = "manual"  # vom Benutzer festgelegt


class Phase(str, Enum):
    """Fortschritt je Datei, in vier Schritten."""

    ANALYSIS = "analysis"
    REPAIR = "repair"
    VALIDATION = "validation"
    DONE = "done"


# Fortschrittsmeldungen der Engine (``models.STAGES``) → Schritt
_REPAIR_STAGES = {"trim", "rewrite", "write", "pages", "lenient", "raw_scan", "xref_rebuild", "trailer_rebuild", "page_tree_rebuild", "normalize", "raster", "streams_rescue"}


def phase_of(kind: str, stage: str) -> Phase:
    """Schritt einer Fortschrittsmeldung: Analyse, Reparatur, Validierung oder Fertig."""
    if kind == "analyze":
        return Phase.ANALYSIS
    if stage in _REPAIR_STAGES:
        return Phase.REPAIR
    if stage == "validate":
        return Phase.VALIDATION
    if stage == "finish":
        return Phase.DONE
    return Phase.ANALYSIS  # »hash«, »open«: Datei wird vor der Reparatur noch einmal geprüft


FINISHED = (ItemState.REPAIRED, ItemState.PARTIALLY_RECOVERED)
WORKING = (ItemState.ANALYZING, ItemState.REPAIRING)
REPAIRABLE_CONDITIONS = (Condition.REPAIRABLE, Condition.DAMAGED, Condition.RAW_RECOVERABLE)


# --- Dateinamen ---------------------------------------------------------------------------


def strip_pdf(text: str) -> str:
    """Eingabe des Benutzers → Name ohne Endung (».pdf« wird immer selbst ergänzt)."""
    value = str(text or "").strip()
    while value.lower().endswith(".pdf"):
        value = value[:-4].rstrip()
    return value


def name_error(base: str) -> str:
    """Fehlermeldung für einen Dateinamen ohne Endung – leer, wenn er unter Windows gültig ist."""
    if not base:
        return "Bitte einen Dateinamen eingeben."
    bad = sorted({char for char in base if char in FORBIDDEN_CHARS or ord(char) < 32})
    if bad:
        shown = " ".join(char if ord(char) >= 32 else "Steuerzeichen" for char in bad)
        return f"Nicht erlaubt in Dateinamen: {shown}"
    if base.endswith((".", " ")):
        return "Der Name darf nicht mit Punkt oder Leerzeichen enden."
    if base.split(".")[0].strip().upper() in RESERVED_NAMES:
        return f"»{base}« ist unter Windows ein reservierter Name."
    if len(base) > MAX_BASE:
        return f"Der Name ist zu lang (höchstens {MAX_BASE} Zeichen)."
    return ""


def suffix_error(suffix: str) -> str:
    """Fehlermeldung für den Zusatz (z. B. »_repariert«) – leer, wenn gültig."""
    if not suffix:
        return "Bitte einen Zusatz eingeben (z. B. »_repariert«)."
    error = name_error("x" + suffix)
    return error.replace("Der Name", "Der Zusatz") if error else ""


def auto_base(source: Path, append: bool, suffix: str = DEFAULT_SUFFIX) -> str:
    """Name nach der Regel: Originalname, mit Schalter plus Zusatz (»Rechnung_repariert«)."""
    return f"{source.stem}{suffix}" if append else source.stem


def numbered(base: str, number: int) -> str:
    """``0`` → »Name.pdf«, ``1`` → »Name (1).pdf«, ``2`` → »Name (2).pdf« …"""
    return f"{base}.pdf" if number <= 0 else f"{base} ({number}).pdf"


def folder_key(folder: Path) -> str:
    """Ordner vergleichbar machen – ohne Rücksicht auf Groß-/Kleinschreibung (wie unter Windows)."""
    return os.path.normcase(os.path.abspath(str(folder))).casefold()


def names_in(folder: Path) -> set[str]:
    """Vorhandene Namen im Ordner (in Kleinschreibung für den Vergleich); fehlt er: keine."""
    try:
        return {entry.name.casefold() for entry in Path(folder).iterdir()}
    except OSError:
        return set()


def path_key(path: str | Path) -> str:
    """Schlüssel für »dieselbe Datei« (doppelt hinzugefügt) – absolut, ohne Groß-/Kleinschreibung."""
    try:
        resolved = Path(path).resolve()
    except OSError:
        resolved = Path(os.path.abspath(str(path)))
    return os.path.normcase(str(resolved)).casefold()


# --- Einträge ---------------------------------------------------------------------------------

_IDS = count(1)


@dataclass
class BatchItem:
    """Eine PDF der Liste. Das Passwort steht nur im Arbeitsspeicher (nie im Protokoll)."""

    path: Path
    size: int | None = None
    key: str = field(default_factory=lambda: f"pdf{next(_IDS)}")
    state: ItemState = ItemState.PENDING
    analysis: PdfAnalysis | None = None
    result: PdfRepairResult | None = None
    output: Path | None = None  # gespeicherte Ausgabe
    name_mode: NameMode = NameMode.AUTO
    manual_base: str = ""
    name_input: str | None = None  # ungültige Eingabe des Benutzers (wird angezeigt, nicht verwendet)
    planned: Path | None = None  # geplanter (bzw. reservierter) Ausgabepfad
    planned_base: str = ""  # … aus diesem Namen ohne Endung
    planned_number: int = 0  # … und dieser Nummer (0: ohne Nummer)
    reserved: bool = False  # Name für den laufenden Durchlauf festgelegt
    phase: Phase | None = None
    stage: str = ""
    fraction: float | None = None
    message: str = ""  # Hinweis oder Fehler (verständlich, ohne vollständige Pfade)
    rescue: bool = False  # Rettungsmodus (Seiten als Bilder) kann angeboten werden
    password: str | None = field(default=None, repr=False)

    @property
    def name(self) -> str:
        return self.path.name

    @property
    def condition(self) -> Condition | None:
        return self.analysis.condition if self.analysis is not None else None

    @property
    def busy(self) -> bool:
        return self.state in WORKING

    @property
    def done(self) -> bool:
        return self.state in FINISHED

    @property
    def signatures(self) -> int:
        return self.analysis.signatures if self.analysis is not None else 0

    @property
    def name_error(self) -> str:
        return name_error(strip_pdf(self.name_input)) if self.name_input is not None else ""

    def base(self, append: bool, suffix: str) -> str:
        return self.manual_base if self.name_mode is NameMode.MANUAL else auto_base(self.path, append, suffix)

    def can_repair(self) -> bool:
        """Mit »Nur diese Datei reparieren« (bzw. im Einzelmodus) reparierbar – auch eine gesunde PDF
        (»Trotzdem neu aufbauen«), nicht verschlüsselt und nicht unlesbar."""
        return (
            self.analysis is not None
            and not self.busy
            and self.analysis.condition not in (Condition.ENCRYPTED, Condition.UNREADABLE)
        )

    def needs_repair(self) -> bool:
        """Gehört zu »Alle reparieren«: beschädigt und noch nicht erfolgreich repariert."""
        return self.can_repair() and self.analysis.condition in REPAIRABLE_CONDITIONS and not self.done

    def repair_mode(self) -> RepairMode:
        return RepairMode.REBUILD if self.condition is Condition.HEALTHY else RepairMode.AUTO


@dataclass
class AddResult:
    added: list[BatchItem] = field(default_factory=list)
    duplicates: list[str] = field(default_factory=list)  # bereits in der Liste
    rejected: list[str] = field(default_factory=list)  # keine PDF
    missing: list[str] = field(default_factory=list)  # nicht vorhanden


class RepairBatch:
    """Die Dateiliste: Hinzufügen (ohne Doppelte), Entfernen, Namensplanung, Zählung."""

    def __init__(self) -> None:
        self.items: list[BatchItem] = []
        self._keys: dict[str, BatchItem] = {}  # Pfadschlüssel → Eintrag

    # Liste ----------------------------------------------------------------------------------
    def add(self, paths: Iterable[str | Path], is_file: Callable[[Path], bool] = Path.is_file) -> AddResult:
        result = AddResult()
        for raw in paths:
            path = Path(raw)
            if not str(raw).lower().endswith(".pdf"):
                result.rejected.append(path.name or str(raw))
                continue
            key = path_key(path)
            if key in self._keys:
                result.duplicates.append(path.name)
                continue
            if not is_file(path):
                result.missing.append(path.name)
                continue
            try:
                size = path.stat().st_size
            except OSError:
                size = None
            item = BatchItem(path=path, size=size)
            self.items.append(item)
            self._keys[key] = item
            result.added.append(item)
        return result

    def get(self, key: str) -> BatchItem | None:
        return next((item for item in self.items if item.key == key), None)

    def remove(self, key: str) -> BatchItem | None:
        item = self.get(key)
        if item is None:
            return None
        self.items.remove(item)
        self._keys.pop(path_key(item.path), None)
        item.password = None
        return item

    def clear(self) -> list[BatchItem]:
        removed, self.items = self.items, []
        self._keys.clear()
        for item in removed:
            item.password = None
        return removed

    def __len__(self) -> int:
        return len(self.items)

    # Reihenfolge ------------------------------------------------------------------------------
    def next_to_analyze(self) -> BatchItem | None:
        return next((item for item in self.items if item.state is ItemState.PENDING), None)

    def to_repair(self) -> list[BatchItem]:
        """Für »Alle reparieren«: beschädigte, noch nicht reparierte Dateien in Listenreihenfolge."""
        return [item for item in self.items if item.needs_repair() and item.state not in (ItemState.FAILED,)]

    def failed(self) -> list[BatchItem]:
        """Für »Fehlgeschlagene erneut versuchen«: Reparatur gescheitert, Analyse vorhanden."""
        return [item for item in self.items if item.state is ItemState.FAILED and item.can_repair()]

    # Namen -------------------------------------------------------------------------------------
    def plan(self, folder_of: Callable[[BatchItem], Path], append: bool, suffix: str, listing: Callable[[Path], set[str]] = names_in) -> None:
        """Ausgabenamen aller Einträge festlegen – in Listenreihenfolge, eindeutig je Zielordner.

        Gespeicherte Ausgaben und reservierte Namen bleiben, wie sie sind; alle anderen bekommen den
        ersten freien Namen: nicht vorhanden (ohne Rücksicht auf Groß-/Kleinschreibung), nicht das
        Original, nicht schon von einer anderen Datei der Liste geplant.
        """
        existing: dict[str, set[str]] = {}
        taken: dict[str, set[str]] = {}
        # Erst festliegende Namen (gespeichert oder reserviert), dann die übrigen
        for item in self.items:
            fixed = item.output if item.output is not None else (item.planned if item.reserved else None)
            if fixed is not None:
                taken.setdefault(folder_key(fixed.parent), set()).add(fixed.name.casefold())
        for item in self.items:
            if item.output is not None or item.reserved:
                continue
            folder = Path(folder_of(item))
            fkey = folder_key(folder)
            if fkey not in existing:
                existing[fkey] = listing(folder)
            used = taken.setdefault(fkey, set())
            base = item.base(append, suffix)
            source = item.path.name.casefold() if folder_key(item.path.parent) == fkey else None
            number = 0
            while True:
                name = numbered(base, number)
                folded = name.casefold()
                if folded not in used and folded not in existing[fkey] and folded != source:
                    break
                number += 1
            item.planned, item.planned_base, item.planned_number = folder / name, base, number
            used.add(folded)

    def reserve(self, items: Iterable[BatchItem], folder_of: Callable[[BatchItem], Path], append: bool, suffix: str, listing: Callable[[Path], set[str]] = names_in) -> None:
        """Namen für einen Durchlauf festlegen: mit frischem Blick auf die Zielordner neu planen und
        für die beteiligten Dateien reservieren (kein Wettlauf zwischen ihnen)."""
        chosen = list(items)
        for item in chosen:
            item.reserved = False
        self.plan(folder_of, append, suffix, listing)
        for item in chosen:
            item.reserved = True

    def release(self) -> None:
        for item in self.items:
            item.reserved = False

    def reserved_names(self, folder: Path, except_item: BatchItem | None = None) -> set[str]:
        """Für andere Dateien reservierte Namen in ``folder`` (dürfen beim Speichern nicht belegt werden)."""
        fkey = folder_key(folder)
        return {
            item.planned.name.casefold()
            for item in self.items
            if item is not except_item and item.reserved and item.output is None and item.planned is not None and folder_key(item.planned.parent) == fkey
        }

    # Zählung -------------------------------------------------------------------------------------
    def counts(self) -> dict[ItemState, int]:
        found: dict[ItemState, int] = {}
        for item in self.items:
            found[item.state] = found.get(item.state, 0) + 1
        return found


def result_state(result: PdfRepairResult, delivered: bool) -> ItemState:
    """Zustand nach einer Reparatur (``delivered``: Ausgabe gespeichert)."""
    if result.status is RepairStatus.CANCELLED:
        return ItemState.CANCELLED
    if result.status is RepairStatus.ENCRYPTED:
        return ItemState.ENCRYPTED
    if delivered and result.status is RepairStatus.REPAIRED:
        return ItemState.REPAIRED
    if delivered and result.status is RepairStatus.PARTIALLY_RECOVERED:
        return ItemState.PARTIALLY_RECOVERED
    return ItemState.FAILED


def analysis_state(analysis: PdfAnalysis) -> ItemState:
    """Zustand nach der Analyse."""
    if analysis.condition is Condition.ENCRYPTED:
        return ItemState.ENCRYPTED
    if analysis.condition is Condition.UNREADABLE:
        return ItemState.UNREADABLE
    return ItemState.READY
