"""Seite »Erstellen«: Kundendaten, Dateien, Excel-Prüfung, Bereitschaft und PDF-Erstellung."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .. import icons
from ..components import FactList, FileRow, ResponsiveColumns, StatusLine, field_label
from ..inputs import ComboBox, TextField
from ..navigation import Page
from ..theme import px
from ..widgets import Button, Card, Collapsible, Divider, FlowRow, IconButton, InfoBar, Text, ToggleSwitch, frame

if TYPE_CHECKING:
    from vertragdesk import App

EXCEL_EMPTY = "Excel-Datei wählen oder in das Fenster ziehen – sie wird sofort geprüft."


def build(app: "App", host) -> Page:
    ui = app.ui
    page = Page(host, "Vertragsübersicht", "Vertragsübersichten aus Excel erstellen")

    # Zwei Karten nebeneinander oder untereinander – entschieden zentral an den Fenster-Breakpoints.
    columns = ResponsiveColumns(page.content, central=True)
    page.add_section(columns)

    # Kundendaten ----------------------------------------------------------------
    kunde = Card(columns, "Kundendaten", icons.CONTACT)
    columns.add(kunde)
    clear = IconButton(kunde.header_right, icons.CLEAR, app.clear_customer, tooltip="Kundendaten leeren")
    clear.pack(side="right")
    body = kunde.body
    field_label(body, "Zuletzt verwendet", first=True)
    ui.recent_combo = ComboBox(body, placeholder="Kunden aus dem Verlauf wählen", command=app.on_recent_pick, width=240, tooltip="Übernimmt Kundendaten, Excel, Logo und Kopf-/Fußzeile")
    ui.recent_combo.pack(fill="x")
    field_label(body, "Firmenname")
    ui.field_firma = TextField(body, app.var_firma, placeholder="z. B. Muster GmbH")
    ui.field_firma.pack(fill="x")
    field_label(body, "Kundennummer")
    ui.field_kd = TextField(body, app.var_kd, placeholder="z. B. 10042", validate=lambda v: bool(v.strip()) or not app.kd_required)
    ui.field_kd.pack(fill="x")
    field_label(body, "Rechnungsempfänger (optional)")
    ui.field_mail = TextField(body, app.var_mail, placeholder="E-Mail-Adresse")
    ui.field_mail.pack(fill="x")
    ui.mail_area = Collapsible(body)
    ui.mail_area.pack(fill="x")
    mail_inner = ui.mail_area.content
    field_label(mail_inner, "Mehrere Rechnungsempfänger in der Excel")
    ui.mail_combo = ComboBox(mail_inner, placeholder="Empfänger wählen", command=app.on_mail_pick, width=240, tooltip="Übernimmt die Adresse als Rechnungsempfänger")
    ui.mail_combo.pack(fill="x")
    ui.kunde_info = InfoBar(body)
    ui.kunde_info.pack(fill="x", pady=(px(8), 0))

    # Dateien ---------------------------------------------------------------------
    dateien = Card(columns, "Dateien", icons.FOLDER)
    columns.add(dateien)
    ui.dateien_card = dateien
    body = dateien.body
    ui.row_excel = FileRow(body, icons.BULLETED_LIST, "Excel-Liste")
    ui.row_excel.pack(fill="x")
    Button(ui.row_excel.buttons, "Durchsuchen", app.pick_excel, icon=icons.OPEN_FILE, tooltip="Excel-Datei wählen (Strg+O)").pack(side="right")
    IconButton(ui.row_excel.buttons, icons.COPY, lambda: app.copy_path(app.var_excel.get()), tooltip="Pfad der Excel-Datei kopieren").pack(side="right", padx=(0, px(4)))
    ui.info_excel = InfoBar(body, closable=False)
    ui.info_excel.pack(fill="x", pady=(px(8), px(4)))
    ui.info_excel.show("neutral", EXCEL_EMPTY, animate=False)
    # Ergebnis der Excel-Prüfung im Detail (nur was tatsächlich in der Datei steht)
    ui.excel_details = Collapsible(body)
    ui.excel_details.pack(fill="x")
    ui.excel_facts = FactList(ui.excel_details.content)
    ui.excel_facts.pack(fill="x", pady=(px(4), px(2)))
    Divider(body).pack(fill="x", pady=px(10))
    ui.row_logo = FileRow(body, icons.PICTURE, "Logo")
    ui.row_logo.pack(fill="x")
    Button(ui.row_logo.buttons, "Durchsuchen", app.pick_logo, icon=icons.OPEN_FILE, tooltip="Logo-Datei wählen").pack(side="right")
    IconButton(ui.row_logo.buttons, icons.REFRESH, app.use_default_logo, tooltip="Standardlogo verwenden").pack(side="right", padx=(0, px(4)))
    IconButton(ui.row_logo.buttons, icons.COPY, lambda: app.copy_path(app.var_logo.get()), tooltip="Pfad des Logos kopieren").pack(side="right", padx=(0, px(4)))
    Divider(body).pack(fill="x", pady=px(10))
    ui.row_ziel = FileRow(body, icons.FOLDER, "Zielordner")
    ui.row_ziel.pack(fill="x")
    Button(ui.row_ziel.buttons, "Durchsuchen", app.pick_ziel, icon=icons.FOLDER_OPEN, tooltip="Ordner für die PDF wählen").pack(side="right")
    IconButton(ui.row_ziel.buttons, icons.COPY, lambda: app.copy_path(app.target_folder()), tooltip="Pfad des Zielordners kopieren").pack(side="right", padx=(0, px(4)))
    ui.dateien_info = InfoBar(body)
    ui.dateien_info.pack(fill="x", pady=(px(8), 0))

    # Aktionen ----------------------------------------------------------------------
    action = Card(page.content)
    page.add_section(action, pady=(px(12), 0))
    body = action.body
    # Bereitschaft: zeigt vor dem Erstellen, was noch fehlt (Klick springt zum Feld).
    ui.ready = StatusLine(body, command=app.fix_readiness)
    ui.ready.pack(fill="x", pady=(0, px(12)))
    row = FlowRow(body, gap=8, row_gap=8)
    row.pack(fill="x")
    ui.btn_pdf = Button(row, "PDF erstellen", app.start_pdf, icon=icons.DOCUMENT, kind="accent", height=40, min_width=180, font="body_strong", tooltip="PDF erstellen (Strg+Enter)")
    row.add(ui.btn_pdf)
    row.add(Button(row, "Ordner öffnen", app.open_folder, icon=icons.FOLDER_OPEN, height=40, tooltip="Zielordner im Explorer öffnen"))
    toggle_box = frame(row)
    Text(toggle_box, "PDF nach dem Erstellen öffnen", style="body").pack(side="left", padx=(px(16), px(8)))
    ToggleSwitch(toggle_box, app.var_open, command=app.persist, show_text=False).pack(side="left")
    row.add(toggle_box)
    ui.pdf_info = InfoBar(body)
    ui.pdf_info.pack(fill="x", pady=(px(8), 0))
    Divider(body).pack(fill="x", pady=(px(14), px(12)))
    recent = frame(body)
    recent.pack(fill="x")
    Text(recent, "Zuletzt erstellt", style="body").pack(side="left", padx=(0, px(12)))
    open_btn = Button(recent, "Öffnen", app.open_recent_pdf, icon=icons.OPEN_IN_WINDOW, tooltip="Ausgewählte PDF öffnen")
    open_btn.pack(side="right")
    ui.pdf_combo = ComboBox(recent, placeholder="Noch keine PDF erstellt", width=200, tooltip="Zuletzt erstellte PDFs – mit »Öffnen« anzeigen")
    ui.pdf_combo.pack(side="left", fill="x", expand=True, padx=(0, px(8)))

    app.reload_recent()
    app.reload_pdfs()
    app.refresh_files()
    return page
