"""Verzeichnis der Werkzeuge – gelesen von Startseite, Navigation und Tastenkürzeln.

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
    title="PDF reparieren",
    description="Analysiert beschädigte PDF-Dateien und versucht, lesbare Inhalte wiederherzustellen.",
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
TOOLS: tuple[ToolInfo, ...] = (READER, CONTRACTS, REPAIR)


def tool_for_page(page: str) -> ToolInfo | None:
    return next((tool for tool in TOOLS if page in tool.pages), None)
