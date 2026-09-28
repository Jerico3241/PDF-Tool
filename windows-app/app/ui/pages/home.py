"""Startseite von PDF Tool: Auswahl der Werkzeuge."""

from __future__ import annotations

from typing import TYPE_CHECKING

from tools.registry import TOOLS

from .. import icons
from ..components import ResponsiveColumns, ToolCard
from ..context import ctx
from ..navigation import Page
from ..theme import px
from ..widgets import Icon, Text, frame

if TYPE_CHECKING:
    from vertragdesk import App

PRIVACY = "Alle Dateien werden lokal auf diesem PC verarbeitet. Es wird nichts hochgeladen."


def build(app: "App", host) -> Page:
    ui = app.ui
    page = Page(host, app.app_name, "Werkzeuge für PDF-Dateien – wählen Sie, was Sie erledigen möchten.")

    columns = ResponsiveColumns(page.content, central=True)
    page.add_section(columns)
    ui.tool_cards = {}
    for tool in TOOLS:
        card = ToolCard(columns, tool.glyph, tool.title, tool.description, lambda key=tool.key: app.open_tool(key), tool.shortcut)
        columns.add(card)
        ui.tool_cards[tool.key] = card

    note = frame(page.content)
    page.add_section(note, pady=(px(20), 0))
    if ctx().icons_available:
        Icon(note, icons.SHIELD, color="text2").pack(side="left", anchor="n", padx=(0, px(8)), pady=(px(1), 0))
    Text(note, PRIVACY, style="caption", color="text2", wrap=True).pack(side="left", fill="x", expand=True)
    return page
