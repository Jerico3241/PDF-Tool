"""Vertragsübersichten – Ansicht »Übersicht erstellen«: Kundendaten (mit Kundenakte), Dateien,
Excel-Prüfung, Bereitschaft und PDF-Erstellung."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ui import icons
from ui.components import FactList, FileRow, ResponsiveColumns, SelectorBar, StatusLine, field_label
from ui.inputs import ComboBox, TextField
from ui.navigation import Page
from ui.theme import px
from ui.widgets import Button, Card, Collapsible, Divider, FlowRow, Icon, IconButton, InfoBar, RoundedFrame, Text, ToggleSwitch, frame

from .customer_widgets import PickerBox
from .history_widgets import ComparisonView

if TYPE_CHECKING:
    from vertragdesk import App

TITLE = "Vertragsübersichten"
VIEWS = [("create", "Übersicht erstellen"), ("batch", "Stapel"), ("layout", "Darstellung"), ("preview", "Vorschau"), ("customers", "Kunden")]
EXCEL_EMPTY = "Excel-Datei wählen oder in das Fenster ziehen – sie wird sofort geprüft."
DETAIL_LABEL_WIDTH = 150  # Beschriftungsspalte unter der Excel-Prüfung (»Rechnungsempfänger« passt)


def build(app: "App", host) -> Page:
    ui = app.ui
    page = Page(host, TITLE, "Kundendaten und Excel-Liste – daraus entsteht die PDF.")
    ui.selector_create = SelectorBar(page.content, VIEWS, "create", lambda key: app.nav.navigate(key))
    page.add_section(ui.selector_create, fill="none", anchor="w", pady=(0, px(16)))

    # Zwei Karten nebeneinander oder untereinander – entschieden zentral an den Fenster-Breakpoints.
    columns = ResponsiveColumns(page.content, central=True)
    page.add_section(columns)

    # Kundendaten ----------------------------------------------------------------
    kunde = Card(columns, "Kundendaten", icons.CONTACT)
    columns.add(kunde)
    clear = IconButton(kunde.header_right, icons.CLEAR, app.clear_customer, tooltip="Kundendaten leeren")
    clear.pack(side="right")
    body = kunde.body
    # Aktive Kundenakte: »Kunde: Beispiel GmbH · 123456« (nur sichtbar, wenn eine übernommen wurde)
    ui.kunde_active_area = Collapsible(body)
    ui.kunde_active_area.pack(fill="x")
    box = RoundedFrame(ui.kunde_active_area.content, fill="card_secondary", stroke="card_stroke", radius=4)
    box.pack(fill="x", pady=(0, px(12)))
    inner = frame(box)
    inner.pack(fill="x", padx=px(12), pady=(px(10), px(8)))
    top = frame(inner)
    top.pack(fill="x")
    Icon(top, icons.PEOPLE, color="accent_text").pack(side="left", anchor="n", padx=(0, px(10)), pady=(px(2), 0))
    texts = frame(top)
    texts.pack(side="left", fill="x", expand=True)
    ui.kunde_active_title = Text(texts, "", style="body_strong", wrap=True)
    ui.kunde_active_title.pack(anchor="w", fill="x")
    ui.kunde_active_caption = Text(texts, "", style="caption", color="text2", wrap=True)
    ui.kunde_active_caption.pack(anchor="w", fill="x")
    buttons = FlowRow(inner, gap=4, row_gap=4)
    buttons.pack(fill="x", pady=(px(6), 0))
    buttons.add(Button(buttons, "Kundenakte öffnen", app.open_active_customer, icon=icons.OPEN_IN_WINDOW, kind="subtle", tooltip="Kundenakte in der Ansicht »Kunden« öffnen"))
    buttons.add(Button(buttons, "Lösen", app.detach_customer, icon=icons.CANCEL, kind="subtle", tooltip="Kundenakte für diese Übersicht nicht mehr verwenden – die Angaben bleiben"))
    box.lift_corners()
    # Nur mit eingeschalteter Kundenakte (Einstellungen → Vertragsübersichten)
    ui.kunde_picker_row = frame(body)
    ui.kunde_picker_row.pack(fill="x")
    field_label(ui.kunde_picker_row, "Bekannten Kunden auswählen", first=True)
    ui.kunde_picker = PickerBox(ui.kunde_picker_row, app.pick_customer, placeholder="Firma, Kundennummer oder E-Mail suchen", width=240, tooltip="Kundenakte suchen und übernehmen (Strg+F)")
    ui.kunde_picker.pack(fill="x")
    ui.label_firma = field_label(body, "Firmenname")
    ui.field_firma = TextField(body, app.var_firma, placeholder="z. B. Muster GmbH")
    ui.field_firma.pack(fill="x")
    field_label(body, "Kundennummer")
    ui.field_kd = TextField(body, app.var_kd, placeholder="z. B. 10042", validate=lambda v: bool(v.strip()) or not app.kd_required)
    ui.field_kd.pack(fill="x")
    field_label(body, "Rechnungsempfänger (optional)")
    ui.field_mail = TextField(body, app.var_mail, placeholder="E-Mail-Adresse")
    ui.field_mail.pack(fill="x")
    ui.kunde_info = InfoBar(body)
    ui.kunde_info.pack(fill="x", pady=(px(8), 0))
    ui.kunde_save_row = frame(body)
    ui.kunde_save_row.pack(fill="x", pady=(px(12), 0))
    ui.btn_kunde_save = Button(ui.kunde_save_row, "Als Kundenakte speichern", app.save_or_update_customer, icon=icons.SAVE, tooltip="Kundendaten bewusst als Kundenakte speichern bzw. die aktive Kundenakte aktualisieren")
    ui.btn_kunde_save.pack(side="left")

    # Dateien ---------------------------------------------------------------------
    dateien = Card(columns, "Dateien", icons.FOLDER)
    columns.add(dateien)
    ui.dateien_card = dateien
    body = dateien.body
    ui.row_excel = FileRow(body, icons.BULLETED_LIST, "Excel-Liste")
    ui.row_excel.pack(fill="x")
    Button(ui.row_excel.buttons, "Durchsuchen", app.pick_excel, icon=icons.OPEN_FILE, tooltip="Excel-Datei wählen (Strg+O)").pack(side="right")
    IconButton(ui.row_excel.buttons, icons.COPY, lambda: app.copy_path(app.var_excel.get()), tooltip="Pfad der Excel-Datei kopieren").pack(side="right", padx=(0, px(4)))
    # Status der Prüfung: die einzige Stelle mit den Vertragszahlen (»Excel geprüft · 5 aktive Verträge«)
    ui.info_excel = InfoBar(body, closable=False)
    ui.info_excel.pack(fill="x", pady=(px(8), 0))
    ui.info_excel.show("neutral", EXCEL_EMPTY, animate=False)
    # Darunter nur, was die Statuszeile nicht schon sagt: Rechnungsempfänger, Kunde, Hinweise
    ui.excel_details = Collapsible(body)
    ui.excel_details.pack(fill="x")
    details = frame(ui.excel_details.content)
    details.pack(fill="x", pady=(px(8), 0))
    ui.mail_row = frame(details)
    ui.mail_row.columnconfigure(0, minsize=px(DETAIL_LABEL_WIDTH))
    ui.mail_row.columnconfigure(1, weight=1)
    Text(ui.mail_row, "Rechnungsempfänger", style="caption", color="text2").grid(row=0, column=0, sticky="w", padx=(0, px(12)))
    ui.mail_value = Text(ui.mail_row, "", style="body", width=1)
    ui.mail_value.grid(row=0, column=1, sticky="ew")
    # Mehrere Empfänger: Auswahl direkt daneben (übernimmt die Adresse in die Kundendaten)
    ui.mail_combo = ComboBox(ui.mail_row, placeholder="Empfänger wählen", command=app.on_mail_pick, width=210, tooltip="Übernimmt die Adresse als Rechnungsempfänger")
    ui.mail_combo.grid(row=0, column=2, sticky="e", padx=(px(8), 0))
    ui.mail_combo.grid_remove()
    ui.excel_facts = FactList(details, label_width=DETAIL_LABEL_WIDTH)
    ui.excel_facts.pack(fill="x")
    # Wiedererkennung nach der Excel-Prüfung (Schließen = Ignorieren) – nur mit Kundenakte
    ui.kunde_match = InfoBar(body, on_close=app.ignore_match)
    ui.kunde_match.pack(fill="x", pady=(px(8), 0))
    ui.divider_logo = Divider(body)
    ui.divider_logo.pack(fill="x", pady=px(10))
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

    # Vertragsänderungen (nur mit geprüfter Excel) ------------------------------------------
    ui.comparison_area = Collapsible(page.content)
    page.add_section(ui.comparison_area, pady=(px(12), 0))
    card = Card(ui.comparison_area.content, "Vertragsänderungen", icons.HISTORY, "Vergleich mit einem gespeicherten Vertragsstand dieses Kunden – nur zur Kontrolle, die PDF bleibt unverändert.")
    card.pack(fill="x")
    ui.comparison = ComparisonView(card.body, app.choose_baseline, app.copy_comparison)
    ui.comparison.pack(fill="x")
    card.lift_corners()

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

    app.reload_pdfs()
    app.refresh_files()
    set_customer_parts(app, app.customer_records_enabled())
    app.refresh_customer_line()
    return page


def set_customer_parts(app: "App", enabled: bool) -> None:
    """Kunden-Elemente zeigen bzw. ausblenden (Schalter »Kundenakte verwenden«).

    Nur Ein- und Ausblenden an festen Stellen – nichts wird neu aufgebaut. Ohne Kundenakte
    bleiben Firmenname, Kundennummer und Rechnungsempfänger als normale Eingabefelder.
    """
    ui = app.ui
    row = getattr(ui, "kunde_picker_row", None)
    if row is None:
        return
    if enabled:
        if not row.winfo_manager():
            row.pack(fill="x", before=ui.label_firma)
        ui.label_firma.pack_configure(pady=(px(12), px(4)))
        if not ui.kunde_save_row.winfo_manager():
            ui.kunde_save_row.pack(fill="x", pady=(px(12), 0), after=ui.kunde_info)
        if not ui.kunde_match.winfo_manager():
            ui.kunde_match.pack(fill="x", pady=(px(8), 0), before=ui.divider_logo)
    else:
        row.pack_forget()
        ui.label_firma.pack_configure(pady=(0, px(4)))  # erstes Feld der Karte
        ui.kunde_save_row.pack_forget()
        ui.kunde_match.hide(animate=False)
        ui.kunde_match.pack_forget()
        ui.kunde_active_area.collapse(animate=False)
