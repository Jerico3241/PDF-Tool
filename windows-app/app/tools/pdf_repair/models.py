"""Analyse- und Ergebnismodelle des Werkzeugs »PDF reparieren«.

Nur Standardbibliothek: Die Modelle werden zwischen Arbeitsprozess und
Oberfläche ausgetauscht. Oberfläche und Logik entscheiden anhand der
Statusklassen, nie anhand von Texten.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Condition(str, Enum):
    """Zustand einer PDF nach der Analyse."""

    HEALTHY = "healthy"  # keine strukturellen Fehler gefunden
    REPAIRABLE = "repairable"  # beschädigte Strukturen, die sich voraussichtlich reparieren lassen
    DAMAGED = "damaged"  # schwer beschädigt: Teile der Datei sind nicht lesbar
    # Keine Engine öffnet die Datei, aber die Rohanalyse findet noch Objekte, Datenströme und
    # Seiten – die Dokumentstruktur lässt sich möglicherweise neu aufbauen
    RAW_RECOVERABLE = "raw_recoverable"
    UNREADABLE = "unreadable"  # auch die Rohanalyse findet keine verwertbare Struktur
    ENCRYPTED = "encrypted"  # verschlüsselt, Passwort fehlt oder ist falsch


class RepairStatus(str, Enum):
    """Ergebnis eines Reparaturvorgangs."""

    HEALTHY = "healthy"  # keine Reparatur nötig
    REPAIRED = "repaired"
    PARTIALLY_RECOVERED = "partially_recovered"
    FAILED = "failed"
    ENCRYPTED = "encrypted"  # Passwort fehlt oder ist falsch
    CANCELLED = "cancelled"


class RepairMode(str, Enum):
    """Wie repariert wird."""

    AUTO = "auto"  # Stufe 2, bei Bedarf Stufe 3
    REBUILD = "rebuild"  # unbeschädigte PDF trotzdem neu aufbauen (Stufe 2)
    RASTER = "raster"  # Rettungsmodus: lesbare Seiten als Bilder (nur nach Bestätigung)


class Method(str, Enum):
    """Stufe, aus der die ausgegebene Datei stammt."""

    REWRITE = "rewrite"  # Stufe 2: Struktur mit qpdf neu geschrieben
    PAGES = "pages"  # Stufe 3: lesbare Seiten einzeln übertragen (qpdf)
    PDFIUM = "pdfium"  # Stufe 3: Seiten über die zweite Engine (PDFium) übertragen
    LENIENT = "lenient"  # Stufe 4: dritte, tolerante Engine (pypdf)
    RAW_REBUILD = "raw_rebuild"  # Stufe 5: Objekte aus den Rohdaten, neue xref, neuer Trailer
    PAGE_TREE_REBUILD = "page_tree_rebuild"  # Stufe 5 mit neu aufgebautem Seitenbaum
    RASTER = "raster"  # Rettungsmodus: Seiten als Bilder


@dataclass
class Check:
    """Eine Zeile der Diagnose. ``ok`` ist ``None``, wenn nicht geprüft werden konnte."""

    key: str
    label: str
    ok: bool | None
    detail: str = ""


@dataclass
class RawStructure:
    """Ergebnis der Rohanalyse – was in den Bytes der Datei noch an PDF-Struktur steckt."""

    candidates: int = 0  # gefundene Objektköpfe »N G obj«
    objects: int = 0  # gültige Objekte (je Nummer die neueste vollständige Definition)
    rejected: int = 0  # verworfene Kandidaten (z. B. zufällige Bytes in Datenströmen)
    superseded: int = 0  # ältere Fassungen (inkrementelle Updates)
    streams: int = 0
    object_streams: int = 0
    catalog: bool = False
    pages: int = 0  # Seitenobjekte (/Type /Page)
    page_nodes: int = 0  # Seitenbaum-Knoten (/Type /Pages)
    xref_table: bool = False
    xref_stream: bool = False
    trailer: bool = False
    startxref: bool = False
    startxref_valid: bool = False
    eof: bool = False
    encrypted: bool = False
    signatures: int = 0

    @property
    def recoverable(self) -> bool:
        """Lohnt der Neuaufbau? Unverschlüsselt, Objekte vorhanden und ein Katalog oder Seiten."""
        return not self.encrypted and self.objects >= 2 and (self.catalog or self.pages > 0)


@dataclass
class PdfAnalysis:
    path: str
    size: int = 0
    sha256: str = ""
    mtime: float = 0.0
    condition: Condition = Condition.UNREADABLE
    engine: str = ""
    looks_like_pdf: bool = False
    pdf_version: str | None = None
    page_count: int | None = None  # Seiten laut qpdf
    pages_expected: int | None = None  # größte Seitenzahl, die eine Engine erkennt
    pdfium_pages: int | None = None
    readable_pages: int | None = None  # Seiten, deren Inhalt fehlerfrei gelesen wurde
    incomplete_pages: list[int] = field(default_factory=list)  # Seitennummern (ab 1) mit beschädigtem Inhalt
    encrypted: bool = False
    password_required: bool = False
    password_rejected: bool = False
    signatures: int = 0  # unterschriebene Signaturfelder
    forms: bool = False
    form_fields: int = 0
    attachments: int = 0
    outlines: bool = False
    metadata_ok: bool | None = None
    structural_errors: list[str] = field(default_factory=list)  # verständliche Befunde
    warnings: list[str] = field(default_factory=list)  # Hinweise für den Benutzer
    checks: list[Check] = field(default_factory=list)
    technical: list[str] = field(default_factory=list)  # Meldungen der Engines (Protokoll)
    repairable: bool = False
    rasterizable_pages: int = 0  # Seiten, die sich für den Rettungsmodus darstellen lassen
    raw: RawStructure | None = None  # Rohanalyse (nur bei beschädigten Dateien)
    data_before: int = 0  # fremde Daten vor dem PDF-Anfang (Byte), z. B. ein E-Mail- oder HTTP-Kopf
    data_after: int = 0  # fremde Daten nach dem letzten %%EOF (Byte)
    error: str | None = None

    @property
    def needs_password(self) -> bool:
        return self.condition is Condition.ENCRYPTED


@dataclass
class PdfRepairResult:
    status: RepairStatus
    input_path: str
    output_path: str | None = None
    method: Method | None = None
    size_before: int = 0
    size_after: int | None = None
    pages_before: int | None = None
    pages_after: int | None = None
    incomplete_pages: list[int] = field(default_factory=list)  # Seitennummern (ab 1) der Ausgabe mit beschädigtem Inhalt
    data_removed: int = 0  # entfernte fremde Daten vor bzw. nach der PDF (Byte)
    streams_rescued: int = 0  # Datenströme, von denen nur der lesbare Teil übernommen wurde
    warnings: list[str] = field(default_factory=list)
    repair_actions: list[str] = field(default_factory=list)
    error: str | None = None
    technical: list[str] = field(default_factory=list)

    @property
    def usable(self) -> bool:
        """Es gibt eine geprüfte Ausgabedatei."""
        return self.status in (RepairStatus.REPAIRED, RepairStatus.PARTIALLY_RECOVERED) and bool(self.output_path)


# Fortschrittsmeldungen der Engine (Schlüssel → Text für die Oberfläche)
STAGES = {
    "hash": "PDF wird geprüft …",
    "open": "Dokumentstruktur wird analysiert …",
    "streams": "Datenströme werden geprüft …",
    "second": "Zweite Engine prüft die Datei …",
    "trim": "Fremde Daten vor bzw. nach der PDF werden entfernt …",
    "rewrite": "Objekte werden rekonstruiert …",
    "write": "PDF wird neu geschrieben …",
    "pages": "Lesbare Seiten werden übertragen …",
    "lenient": "Alternative PDF-Struktur wird geprüft …",
    "raw_scan": "PDF-Objekte werden gesucht …",
    "xref_rebuild": "Querverweistabelle wird rekonstruiert …",
    "trailer_rebuild": "Trailer wird neu aufgebaut …",
    "page_tree_rebuild": "Seitenstruktur wird neu aufgebaut …",
    "normalize": "PDF wird normalisiert …",
    "raster": "Seiten werden als Bilder gerettet …",
    "streams_rescue": "Beschädigte Datenströme werden gerettet …",
    "validate": "Reparierte Datei wird geprüft …",
    "finish": "Ausgabe wird gespeichert …",
}
