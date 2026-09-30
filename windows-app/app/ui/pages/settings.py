"""Seite »Einstellungen«: globale Einstellungen von PDF Tool (Design, Akzentfarbe, Mica, Animationen)
und die optionale Kundenakte der Vertragsübersichten.

Weitere Einstellungen einzelner Werkzeuge stehen im jeweiligen Werkzeug."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .. import icons
from ..components import SettingsCard
from ..context import ctx
from ..inputs import ComboBox
from ..navigation import Page
from ..theme import ACCENTS, SYSTEM_ACCENT, accent_name, px, system_accent
from ..widgets import Button, Icon, Swatch, Text, ToggleSwitch, frame

if TYPE_CHECKING:
    from vertragdesk import App

THEME_LABELS = (("system", "Wie Windows"), ("light", "Hell"), ("dark", "Dunkel"))
CUSTOMER_RECORDS_TITLE = "Kundenakte verwenden"
CUSTOMER_RECORDS_TEXT = "Speichert Kundendaten lokal und ermöglicht die Wiedererkennung bekannter Rechnungsempfänger."
CUSTOMER_RECORDS_NOTE = "Alle Kundendaten werden ausschließlich lokal auf diesem PC gespeichert."


def build(app: "App", host) -> Page:
    ui = app.ui
    c = ctx()
    page = Page(host, "Einstellungen", None)

    # Darstellung -------------------------------------------------------------------
    page.section_title("Darstellung")
    theme_card = SettingsCard(page.content, icons.PERSONALIZE, "App-Design", "Hell, Dunkel oder automatisch wie der Windows-App-Modus")
    page.add_section(theme_card)
    labels = [label for _key, label in THEME_LABELS]
    ui.theme_combo = ComboBox(theme_card.control, labels, command=lambda label: app.set_theme(next(k for k, v in THEME_LABELS if v == label)), width=180)
    ui.theme_combo.pack()
    ui.theme_combo.set(dict(THEME_LABELS).get(app.theme.mode, "Wie Windows"))

    accent_card = SettingsCard(page.content, icons.COLOR, "Akzentfarbe", "Für Schaltflächen, Auswahl, Hinweise und die Navigation")
    page.add_section(accent_card, pady=(px(4), 0))
    ui.accent_label = Text(accent_card.control, accent_name(app.theme.accent_choice), style="body", color="text2")
    ui.accent_label.pack()
    extra = accent_card.show_extra()
    swatches = frame(extra)
    swatches.pack(anchor="w")
    ui.swatches = []

    def add_swatch(value: str, name: str, color_fn, glyph=None) -> None:
        swatch = Swatch(
            swatches,
            color_fn,
            lambda v=value: app.set_accent(v),
            tooltip=name,
            selected_fn=lambda v=value: app.theme.accent_choice.lower() == v.lower(),
            glyph=glyph,
        )
        swatch.pack(side="left", padx=(0, px(2)))
        ui.swatches.append(swatch)

    add_swatch(SYSTEM_ACCENT, "Windows-Akzentfarbe", lambda: system_accent().dark_fill if c.pal.dark else system_accent().light_fill, glyph=icons.SYSTEM)
    for name, value in ACCENTS:
        add_swatch(value, name, lambda v=value: _preview(v))

    mica_card = SettingsCard(page.content, icons.LIGHTBULB, "Mica-Material", app.mica_description())
    page.add_section(mica_card, pady=(px(4), 0))
    ui.mica_card = mica_card
    if app.mica_possible():
        ui.mica_toggle = ToggleSwitch(mica_card.control, app.var_mica, command=app.apply_mica_setting)
    else:
        import tkinter as tk

        ui.mica_toggle = ToggleSwitch(mica_card.control, tk.BooleanVar(mica_card, False))
        ui.mica_toggle.set_enabled(False)
    ui.mica_toggle.pack()

    # Verhalten -----------------------------------------------------------------------
    page.section_title("Verhalten")
    anim_card = SettingsCard(page.content, icons.PLAY, "Animationen", app.animation_description())
    page.add_section(anim_card)
    ui.anim_card = anim_card
    ToggleSwitch(anim_card.control, app.var_anim, command=app.apply_animation_setting).pack()

    # Vertragsübersichten ----------------------------------------------------------------
    page.section_title("Vertragsübersichten")
    records_card = SettingsCard(page.content, icons.PEOPLE, CUSTOMER_RECORDS_TITLE, CUSTOMER_RECORDS_TEXT)
    page.add_section(records_card)
    ui.customer_records_card = records_card
    ui.customer_records_toggle = ToggleSwitch(records_card.control, app.var_customer_records, command=app.apply_customer_records_setting)
    ui.customer_records_toggle.pack()
    extra = records_card.show_extra()
    note_row = frame(extra)
    note_row.pack(fill="x")
    if c.icons_available:
        Icon(note_row, icons.SHIELD, color="text2").pack(side="left", anchor="n", padx=(0, px(8)), pady=(px(1), 0))
    Text(note_row, CUSTOMER_RECORDS_NOTE, style="caption", color="text2", wrap=True).pack(side="left", fill="x", expand=True)
    note = Text(page.content, "Einstellungen der einzelnen Werkzeuge stehen im jeweiligen Werkzeug – z. B. Vorlagen und Verlauf unter »Vertragsübersichten · Darstellung«.", style="caption", color="text2", wrap=True)
    page.add_section(note, pady=(px(8), 0))

    # App ----------------------------------------------------------------------------------
    page.section_title("Info")
    about_card = SettingsCard(page.content, icons.INFO, app.app_name, f"Version {app.version} · Entwickler und Inhaber: {app.developer}")
    page.add_section(about_card)
    Button(about_card.control, "Über", app.show_about).pack()
    help_card = SettingsCard(page.content, icons.HELP, "Kurzanleitung", "So arbeiten Sie mit den Werkzeugen von PDF Tool (F1)")
    page.add_section(help_card, pady=(px(4), 0))
    Button(help_card.control, "Öffnen", app.show_help).pack()
    news_card = SettingsCard(page.content, icons.MEGAPHONE, "Neuerungen", f"Was ist neu in Version {app.version}")
    page.add_section(news_card, pady=(px(4), 0))
    Button(news_card.control, "Anzeigen", app.show_changelog).pack()
    return page


def _preview(value: str) -> str:
    from ..theme import derive_accent

    accent = derive_accent(value)
    return accent.dark_fill if ctx().pal.dark else accent.light_fill


def refresh(app: "App") -> None:
    ui = app.ui
    if getattr(ui, "accent_label", None) is not None:
        ui.accent_label.configure(text=accent_name(app.theme.accent_choice))
    for swatch in getattr(ui, "swatches", []):
        swatch.redraw()
    if getattr(ui, "theme_combo", None) is not None:
        ui.theme_combo.set(dict(THEME_LABELS).get(app.theme.mode, "Wie Windows"))
    if getattr(ui, "mica_card", None) is not None:
        ui.mica_card.set_description(app.mica_description())
    if getattr(ui, "anim_card", None) is not None:
        ui.anim_card.set_description(app.animation_description())
