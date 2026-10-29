"""Verzeichnis der Werkzeuge – gelesen von Startseite, Tab-Leiste und Tastenkürzeln.

Ein neues Werkzeug bekommt ein eigenes Paket unter ``tools/`` und einen Eintrag hier.
"""

from __future__ import annotations

from . import ToolInfo

CONTRACTS = ToolInfo(
    key="contracts",
    title="Vertragsübersichten",
    description="Erstellt professionelle Vertragsübersichten aus Excel-Dateien.",
    icon="document",
    pages=("create", "batch", "layout", "preview", "templates", "rules", "comparison", "customers"),
    shortcut="Strg+2",
)
REPAIR = ToolInfo(
    key="repair",
    title="Dateien reparieren",
    description="Analysiert beschädigte PDFs, Office-Dateien und Bilder und stellt lesbare Inhalte wieder her.",
    icon="wrench",
    pages=("repair",),
    shortcut="Strg+3",
)
READER = ToolInfo(
    key="reader",
    title="PDF Reader & Editor",
    description="PDFs öffnen, bearbeiten, organisieren und kommentieren.",
    icon="document_pdf",
    pages=("reader",),
    shortcut="Strg+5",
)
ACTIONS = ToolInfo(
    key="actions",
    title="Stapel-Aktionen",
    description="Viele PDFs auf einmal verkleinern, nummerieren, schützen oder als PDF/A speichern.",
    icon="stack",
    pages=("actions",),
    shortcut="Strg+6",
)
CONVERT = ToolInfo(
    key="convert",
    title="Umwandeln",
    description="Viele Dateien jeder Art umwandeln, zusammenfügen, teilen, drucken oder umbenennen.",
    icon="arrow_swap",
    pages=("convert",),
    shortcut="Strg+7",
)
VERSIONS = ToolInfo(
    key="versions",
    title="Backup-Center",
    description="Automatische Sicherungen und frühere Fassungen Ihrer Dokumente wiederherstellen.",
    icon="history",
    pages=("versions",),
    shortcut="Strg+8",
)
TOOLS: tuple[ToolInfo, ...] = (READER, CONVERT, ACTIONS, CONTRACTS, REPAIR, VERSIONS)


def tool_for_page(page: str) -> ToolInfo | None:
    return next((tool for tool in TOOLS if page in tool.pages), None)
