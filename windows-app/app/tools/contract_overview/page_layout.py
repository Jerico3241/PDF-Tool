"""Vertragsübersichten – Ansicht »Darstellung«: Vorlagen, PDF-Einstellungen, Kopf- und
Fußzeile, Zyklus-Regeln und Verlauf."""

from __future__ import annotations

import tkinter as tk
from typing import TYPE_CHECKING

from richtext import FOOTER_ALIGN, FOOTER_STYLE, HEADER_ALIGN, HEADER_STYLE

from ui import icons
from ui.components import ResponsiveColumns, SelectorBar, SettingsCard, field_label
from ui.context import ctx
from ui.inputs import ComboBox, TextField
from ui.navigation import Page
from ui.richtext import RichTextEditor
from ui.theme import px
from ui.widgets import Button, Card, FlowRow, IconButton, InfoBar, RadioGroup, RoundedFrame, Text, frame

if TYPE_CHECKING:
    from vertragdesk import App

PLACEHOLDERS = "Platzhalter: {kd}  {kunde}  {firma}  {datum}  {datumkurz} – auch formatiert"


def _number(value: str) -> bool:
    try:
        return float(value.replace(",", ".")) > 0
    except ValueError:
        return False


def build(app: "App", host) -> Page:
    from .page_create import TITLE, VIEWS

    ui = app.ui
    page = Page(host, TITLE, "Vorlagen, Layout der PDF sowie Kopf- und Fußzeile.")
    ui.selector_layout = SelectorBar(page.content, VIEWS, "layout", lambda key: app.nav.navigate(key))
    page.add_section(ui.selector_layout, fill="none", anchor="w", pady=(0, px(16)))

    # Vorlagen ------------------------------------------------------------------
    vorlagen = Card(page.content, "Vorlagen", icons.LIBRARY, "Speichert Logo, Format, Dateiname, Kopfzeile, Fußzeile und Zyklus-Regeln unter einem Namen.")
    page.add_section(vorlagen)
    body = vorlagen.body
    cols = ResponsiveColumns(body, breakpoint=560)
    cols.pack(fill="x")
    left = frame(cols)
    field_label(left, "Gespeicherte Vorlage", first=True)
    ui.vorlage_combo = ComboBox(left, placeholder="Vorlage wählen", command=app.on_vorlage_pick, width=200)
    ui.vorlage_combo.pack(fill="x")
    cols.add(left)
    right = frame(cols)
    field_label(right, "Name", first=True)
    ui.field_vorlage = TextField(right, app.var_vorlage, placeholder="Name der Vorlage", on_submit=app.save_vorlage)
    ui.field_vorlage.pack(fill="x")
    cols.add(right)
    buttons = FlowRow(body)
    buttons.pack(fill="x", pady=(px(12), 0))
    buttons.add(Button(buttons, "Vorlage speichern", app.save_vorlage, icon=icons.SAVE, kind="accent"))
    buttons.add(Button(buttons, "Vorlage löschen", app.delete_vorlage, icon=icons.DELETE))
    ui.vorlagen_info = InfoBar(body)
    ui.vorlagen_info.pack(fill="x", pady=(px(8), 0))

    # PDF-Einstellungen -----------------------------------------------------------
    pdf = Card(page.content, "PDF-Einstellungen", icons.PAGE, "Titel, Dateiname, Logo und Seitenformat der erstellten PDF.")
    page.add_section(pdf, pady=(px(12), 0))
    reset = IconButton(pdf.header_right, icons.UNDO, app.reset_pdf_settings, tooltip="Standardwerte wiederherstellen")
    reset.pack(side="right")
    body = pdf.body
    grid = ResponsiveColumns(body, breakpoint=560)
    grid.pack(fill="x")
    col_a, col_b = frame(grid), frame(grid)
    field_label(col_a, "Titel", first=True)
    TextField(col_a, app.var_titel, placeholder="Vertragsübersicht").pack(fill="x")
    field_label(col_a, "Dateiname")
    TextField(col_a, app.var_name, placeholder="Vertragsuebersicht_Kd{kd}.pdf").pack(fill="x")
    Text(col_a, "Platzhalter: {kd}  {kunde}  {datum}  {datumkurz}", style="caption", color="text2").pack(anchor="w", pady=(px(4), 0))
    field_label(col_b, "Untertitel", first=True)
    TextField(col_b, app.var_untertitel, placeholder="Wartungs- und Nutzungsverträge").pack(fill="x")
    field_label(col_b, "Logo-Breite (mm)")
    ui.field_breite = TextField(col_b, app.var_breite, placeholder="62", validate=_number, width=120)
    ui.field_breite.pack(fill="x")
    grid.add(col_a)
    grid.add(col_b)
    field_label(body, "Seitenformat")
    RadioGroup(body, app.var_format, (("hoch", "Hochformat A4"), ("quer", "Querformat A4")), command=app.persist).pack(anchor="w")
    ui.pdf_settings_info = InfoBar(body)
    ui.pdf_settings_info.pack(fill="x", pady=(px(8), 0))

    # Kopfzeile ---------------------------------------------------------------------
    kopf = Card(page.content, "Kopfzeile", icons.ALIGN_LEFT, "Optional. Erscheint oben auf jeder Seite. Leer lassen, wenn keine Kopfzeile gewünscht ist.")
    page.add_section(kopf, pady=(px(12), 0))
    body = kopf.body
    txt_kopf = RichTextEditor(body, HEADER_STYLE, HEADER_ALIGN, lines=3, on_change=app.schedule_text_save)
    txt_kopf.pack(fill="x")
    # Mit dem geladenen Wert füllen, *bevor* das Feld unter app.ui bekannt ist: header_rich()
    # liefert sonst bereits den (noch leeren) Inhalt des neuen Felds.
    txt_kopf.set_rich(app.header_rich())
    ui.txt_kopf = txt_kopf
    row = FlowRow(body)
    row.pack(fill="x", pady=(px(10), 0))
    row.add(Button(row, "Kopfzeile speichern", app.save_header, icon=icons.SAVE, kind="accent"))
    row.add(Text(row, PLACEHOLDERS, style="caption", color="text2"))
    ui.kopf_info = InfoBar(body)
    ui.kopf_info.pack(fill="x", pady=(px(8), 0))

    # Fußzeile -------------------------------------------------------------------------
    fuss = Card(page.content, "Fußzeile", icons.ALIGN_CENTER, "Erscheint unten auf jeder Seite. Die Seitenzahl wird automatisch ergänzt.")
    page.add_section(fuss, pady=(px(12), 0))
    body = fuss.body
    cols = ResponsiveColumns(body, breakpoint=560)
    cols.pack(fill="x")
    left, right = frame(cols), frame(cols)
    field_label(left, "Textbaustein", first=True)
    ui.baustein_combo = ComboBox(left, placeholder="Textbaustein wählen", command=app.on_baustein_pick, width=200)
    ui.baustein_combo.pack(fill="x")
    field_label(right, "Name des Textbausteins (optional)", first=True)
    TextField(right, app.var_baustein, placeholder="Zum Speichern als Textbaustein").pack(fill="x")
    cols.add(left)
    cols.add(right)
    field_label(body, "Text")
    txt_fuss = RichTextEditor(body, FOOTER_STYLE, FOOTER_ALIGN, lines=5, on_change=app.schedule_text_save)
    txt_fuss.pack(fill="x")
    txt_fuss.set_rich(app.footer_rich())  # geladene bzw. Standard-Fußzeile (siehe Kopfzeile)
    ui.txt_fuss = txt_fuss
    row = FlowRow(body)
    row.pack(fill="x", pady=(px(10), 0))
    row.add(Button(row, "Fußzeile speichern", app.save_footer, icon=icons.SAVE, kind="accent"))
    row.add(Button(row, "Standard wiederherstellen", app.restore_default_footer, icon=icons.UNDO, tooltip="Setzt Text und Formatierung der Fußzeile auf den Standard der App zurück"))
    row.add(Button(row, "Textbaustein löschen", app.delete_baustein, icon=icons.DELETE))
    row.add(Text(row, PLACEHOLDERS, style="caption", color="text2"))
    ui.fuss_info = InfoBar(body)
    ui.fuss_info.pack(fill="x", pady=(px(8), 0))

    # Zyklus-Regeln ---------------------------------------------------------------------
    regeln = Card(page.content, "Zyklus-Regeln", icons.REPEAT_ALL, "Enthält die Beschreibung den Begriff, wird der Abrechnungszyklus in der PDF ersetzt. Das Datum bleibt stehen.")
    page.add_section(regeln, pady=(px(12), 0))
    body = regeln.body
    ui.regeln_list = frame(body)
    ui.regeln_list.pack(fill="x")
    form = frame(body)
    form.pack(fill="x", pady=(px(12), 0))
    cols = ResponsiveColumns(form, breakpoint=520)
    cols.pack(fill="x")
    a, b = frame(cols), frame(cols)
    field_label(a, "Begriff", first=True)
    ui.field_regel_such = TextField(a, app.var_regel_such, placeholder="z. B. Hott-KI", on_submit=app.add_regel)
    ui.field_regel_such.pack(fill="x")
    field_label(b, "Zyklus", first=True)
    ui.field_regel_zyk = TextField(b, app.var_regel_zyk, placeholder="z. B. jährlich", on_submit=app.add_regel)
    ui.field_regel_zyk.pack(fill="x")
    cols.add(a)
    cols.add(b)
    actions = FlowRow(body)
    actions.pack(fill="x", pady=(px(12), 0))
    actions.add(Button(actions, "Regel speichern", app.add_regel, icon=icons.ADD, kind="accent"))
    ui.regeln_info = InfoBar(body)
    ui.regeln_info.pack(fill="x", pady=(px(8), 0))

    # Verlauf (bis 2.2 unter »Einstellungen«) ------------------------------------------
    history = SettingsCard(page.content, icons.HISTORY, "Verlauf löschen", "Entfernt zuletzt verwendete Kunden und zuletzt erstellte PDFs aus den Listen. Dateien bleiben erhalten.")
    page.add_section(history, pady=(px(12), 0))
    Button(history.control, "Löschen", app.clear_history, icon=icons.DELETE).pack()
    ui.daten_info = InfoBar(page.content)
    page.add_section(ui.daten_info, pady=(px(8), 0))

    app.reload_vorlagen()
    app.reload_bausteine()
    app.reload_regeln()
    return page


def render_rules(app: "App") -> None:
    """Regelliste als Zeilen mit Bearbeiten- und Löschen-Schaltfläche."""
    container = getattr(app.ui, "regeln_list", None)
    if container is None:
        return
    for child in container.winfo_children():
        child.destroy()
    c = ctx()
    if not app.state.regeln:
        empty = RoundedFrame(container, fill="card_secondary", stroke=None, radius=4)
        empty.pack(fill="x")
        Text(empty, "Keine Regeln. Neue Regel unten eintragen.", style="body", color="text2").pack(anchor="w", padx=px(12), pady=px(10))
        return
    for index, regel in enumerate(app.state.regeln):
        row = RoundedFrame(container, fill="card_secondary", stroke=None, radius=4)
        row.pack(fill="x", pady=(0 if index == 0 else px(4), 0))
        inner = frame(row)
        inner.pack(fill="x", padx=(px(12), px(4)), pady=px(2))
        Text(inner, regel["enthaelt"], style="body_strong").pack(side="left")
        arrow = "" if c.icons_available else "→"
        arrow_label = tk.Label(inner, text=arrow, font=c.fonts.icon_small if c.icons_available else c.fonts.body, bd=0)
        c.theme.style(arrow_label, bg="card_secondary", fg="text2")
        arrow_label.pack(side="left", padx=px(10))
        Text(inner, regel["zyklus"], style="body").pack(side="left")
        IconButton(inner, icons.DELETE, lambda i=index: app.delete_regel(i), tooltip=f"Regel „{regel['enthaelt']}“ löschen").pack(side="right")
        IconButton(inner, icons.EDIT, lambda r=regel: app.edit_regel(r), tooltip="In das Formular übernehmen").pack(side="right")
        row.lift_corners()
