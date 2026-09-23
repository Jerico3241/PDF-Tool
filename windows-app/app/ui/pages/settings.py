"""Seite »Einstellungen« im Aufbau der Windows-11-Einstellungen."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .. import icons
from ..components import SettingsCard
from ..context import ctx
from ..inputs import ComboBox
from ..navigation import Page
from ..theme import ACCENTS, SYSTEM_ACCENT, accent_name, px, system_accent
from ..widgets import Button, InfoBar, Swatch, Text, ToggleSwitch, frame

if TYPE_CHECKING:
    from vertragdesk import App

THEME_LABELS = (("system", "Wie Windows"), ("light", "Hell"), ("dark", "Dunkel"))


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
    open_card = SettingsCard(page.content, icons.OPEN_IN_WINDOW, "PDF nach dem Erstellen öffnen", "Öffnet die fertige PDF im Standardprogramm")
    page.add_section(open_card)
    ToggleSwitch(open_card.control, app.var_open, command=app.persist).pack()
    anim_card = SettingsCard(page.content, icons.PLAY, "Animationen", app.animation_description())
    page.add_section(anim_card, pady=(px(4), 0))
    ui.anim_card = anim_card
    ToggleSwitch(anim_card.control, app.var_anim, command=app.apply_animation_setting).pack()

    # Daten ------------------------------------------------------------------------------
    page.section_title("Daten")
    clear_card = SettingsCard(page.content, icons.CONTACT, "Kundendaten leeren", "Leert Firmenname, Kundennummer und Rechnungsempfänger")
    page.add_section(clear_card)
    Button(clear_card.control, "Leeren", app.clear_customer, icon=icons.CLEAR).pack()
    logo_card = SettingsCard(page.content, icons.PICTURE, "Standardlogo", "Setzt das mitgelieferte Logo für die nächste PDF")
    page.add_section(logo_card, pady=(px(4), 0))
    Button(logo_card.control, "Verwenden", app.use_default_logo, icon=icons.REFRESH).pack()
    history_card = SettingsCard(page.content, icons.HISTORY, "Verlauf löschen", "Entfernt zuletzt verwendete Kunden und zuletzt erstellte PDFs aus der Liste. Dateien bleiben erhalten.")
    page.add_section(history_card, pady=(px(4), 0))
    Button(history_card.control, "Löschen", app.clear_history, icon=icons.DELETE).pack()
    ui.settings_info = InfoBar(page.content)
    page.add_section(ui.settings_info, pady=(px(8), 0))

    # App ----------------------------------------------------------------------------------
    page.section_title("Info")
    about_card = SettingsCard(page.content, icons.INFO, app.app_name, f"Version {app.version} · Entwickler und Inhaber: {app.developer}")
    page.add_section(about_card)
    Button(about_card.control, "Über", app.show_about).pack()
    help_card = SettingsCard(page.content, icons.HELP, "Kurzanleitung", "So entsteht eine Vertragsübersicht in fünf Schritten (F1)")
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
