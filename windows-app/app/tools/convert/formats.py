"""Dateiarten und Ziele des Werkzeugs »Umwandeln«.

Jede Datei gehört zu einer Art (PDF, Text, Tabelle, Präsentation, Bild). Welche Ziele es gibt, hängt von der Art ab;
»Seiten als Bild« gibt es für alle Dokumente (Text, Tabelle und Präsentation über eine PDF dazwischen).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

PDF = "pdf"
TEXT = "text"
SHEET = "sheet"
SLIDES = "slides"
IMAGE = "image"

SUFFIXES = {
    PDF: (".pdf",),
    TEXT: (".docx", ".doc", ".docm", ".odt", ".rtf", ".txt"),
    SHEET: (".xlsx", ".xls", ".xlsm", ".ods", ".csv"),
    SLIDES: (".pptx", ".ppt", ".pptm", ".odp"),
    IMAGE: (".jpg", ".jpeg", ".jpe", ".png", ".bmp", ".gif", ".tif", ".tiff", ".webp", ".heic", ".heif", ".avif"),
}
KIND_LABELS = {PDF: "PDF", TEXT: "Text-Dokument", SHEET: "Tabelle", SLIDES: "Präsentation", IMAGE: "Bild"}


@dataclass(frozen=True)
class Target:
    key: str
    label: str
    suffix: str
    images: bool = False  # je Seite ein Bild


TARGETS = {
    "pdf": Target("pdf", "PDF (.pdf)", ".pdf"),
    "docx": Target("docx", "Word (.docx)", ".docx"),
    "odt": Target("odt", "OpenDocument-Text (.odt)", ".odt"),
    "rtf": Target("rtf", "Rich Text (.rtf)", ".rtf"),
    "txt": Target("txt", "Nur Text (.txt)", ".txt"),
    "html": Target("html", "Webseite (.html)", ".html"),
    "xlsx": Target("xlsx", "Excel (.xlsx)", ".xlsx"),
    "ods": Target("ods", "OpenDocument-Tabelle (.ods)", ".ods"),
    "csv": Target("csv", "CSV (.csv)", ".csv"),
    "pptx": Target("pptx", "PowerPoint (.pptx)", ".pptx"),
    "odp": Target("odp", "OpenDocument-Präsentation (.odp)", ".odp"),
    "png": Target("png", "Bild PNG (.png)", ".png", True),
    "jpg": Target("jpg", "Bild JPEG (.jpg)", ".jpg", True),
    "webp": Target("webp", "Bild WEBP (.webp)", ".webp", True),
    "avif": Target("avif", "Bild AVIF (.avif)", ".avif", True),
    "tiff": Target("tiff", "Bild TIFF (.tif)", ".tif", True),
}
# Ziele je Art in der Reihenfolge der Auswahl
BY_KIND = {
    PDF: ("docx", "xlsx", "pptx", "html", "txt", "png", "jpg", "webp"),
    TEXT: ("pdf", "docx", "odt", "rtf", "txt", "html", "png", "jpg"),
    SHEET: ("pdf", "xlsx", "ods", "csv", "html", "png", "jpg"),
    SLIDES: ("pdf", "pptx", "odp", "png", "jpg"),
    IMAGE: ("pdf", "png", "jpg", "webp", "avif", "tiff"),
}
# Reihenfolge der Ziele in der Auswahl der Seite (alle Arten gemischt)
ORDER = ("pdf", "docx", "xlsx", "pptx", "odt", "ods", "odp", "rtf", "csv", "html", "txt", "png", "jpg", "webp", "avif", "tiff")


def kind_of(path: str | os.PathLike) -> str | None:
    suffix = Path(path).suffix.lower()
    return next((kind for kind, suffixes in SUFFIXES.items() if suffix in suffixes), None)


def supported(path: str | os.PathLike) -> bool:
    return kind_of(path) is not None


def targets_for(kind: str | None) -> tuple[str, ...]:
    return BY_KIND.get(kind or "", ())


def can_convert(path: str | os.PathLike, target: str) -> bool:
    """Lässt sich die Datei in ``target`` umwandeln? Nie in dieselbe Endung (das wäre eine Kopie)."""
    kind = kind_of(path)
    if target not in targets_for(kind):
        return False
    return TARGETS[target].suffix != Path(path).suffix.lower() and not (target == "jpg" and Path(path).suffix.lower() in (".jpeg", ".jpe"))


def why_not(path: str | os.PathLike, target: str) -> str:
    """Satz für »Ausgelassen«, wenn ``can_convert`` nein sagt."""
    kind = kind_of(path)
    if kind is None:
        return "Diese Dateiart kann Novadesk nicht umwandeln."
    if target not in targets_for(kind):
        return f"{KIND_LABELS[kind]} lässt sich nicht in {TARGETS[target].label} umwandeln."
    return "Die Datei hat schon dieses Format."


def dialog_filter() -> str:
    every = " ".join(f"*{suffix}" for suffixes in SUFFIXES.values() for suffix in suffixes)
    parts = [f"Alle unterstützten Dateien ({every})"]
    for kind, suffixes in SUFFIXES.items():
        parts.append(f"{KIND_LABELS[kind]} (" + " ".join(f"*{suffix}" for suffix in suffixes) + ")")
    parts.append("Alle Dateien (*.*)")
    return ";;".join(parts)
