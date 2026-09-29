"""Vertragsübersichten – Ansicht »Stapel«: mehrere Excel-Listen prüfen und gesammelt als PDF erstellen.

Aufbau: Oben »Stapel« (Zusammenfassung, Fortschritt, Erstellen) neben »Ausgabe und Standards«,
darunter Filter, Massenaktionen und die Liste. Ein Eintrag öffnet sich zum Bearbeiten in einer
eigenen Ansicht (wie eine Kundenakte in »Kunden«). Alles entsteht einmal und bleibt bestehen;
Änderungen werden gesammelt je Leerlauf übernommen.
"""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog
from typing import TYPE_CHECKING

from appstate import ICON_FILE
from ui import dialogs, icons
from ui.components import FactList, FileRow, ResponsiveColumns, SelectorBar, StatusLine, field_label, path_caption
from ui.context import ctx
from ui.inputs import ComboBox, TextField
from ui.navigation import Page
from ui.theme import px
from ui.widgets import Button, Card, CheckBox, Collapsible, Divider, FlowRow, Icon, IconButton, InfoBar, ProgressBar, ProgressRing, RoundedFrame, Text, ToggleSwitch, frame

from ..overview import contract_summary
from ..page_create import DETAIL_LABEL_WIDTH, TITLE, VIEWS
from . import resolver
from .flow import FILTERS
from .models import CREATED, DONE, ConflictMode, CustomerMode, ItemStatus
from .widgets import BatchList, RowData

if TYPE_CHECKING:
    from vertragdesk import App

SUBTITLE = "Mehrere Excel-Listen prüfen und gesammelt als PDF erstellen."
EMPTY_TITLE = "Noch keine Excel-Dateien hinzugefügt."
EMPTY_TEXT = "Füge mehrere Excel-Dateien hinzu, um Vertragsübersichten gesammelt zu erstellen."
EMPTY_HINT = "Excel-Dateien oder einen Ordner auch einfach in das Fenster ziehen. Jede Datei wird sofort geprüft; bekannte Kunden werden an der Rechnungsempfänger-E-Mail erkannt."
PRIVACY = "Alles geschieht lokal auf diesem PC – keine Cloud, keine Uploads."
RUN_TEXT = "Bereite Übersichten erstellen"
FILTER_LABELS = {"all": "Alle", "ready": "Bereit", "needs_input": "Angaben erforderlich", "failed": "Fehler", "done": "Fertig"}
FILTER_EMPTY = {
    "ready": "Kein Eintrag ist bereit.",
    "needs_input": "Kein Eintrag braucht weitere Angaben.",
    "failed": "Keine Fehler.",
    "done": "Noch nichts erstellt.",
}
CONFLICT_LABELS = {ConflictMode.NUMBER: "Automatisch nummerieren", ConflictMode.SKIP: "Überspringen", ConflictMode.OVERWRITE: "Überschreiben"}
TEMPLATE_AUTO = "Automatisch"
TEMPLATE_NONE = "Keine Vorlage"
STATUS = {
    ItemStatus.PENDING: ("Wartet auf Prüfung", "neutral"),
    ItemStatus.ANALYZING: ("Wird geprüft …", "neutral"),
    ItemStatus.READY: ("Bereit", "success"),
    ItemStatus.NEEDS_INPUT: ("Angaben erforderlich", "caution"),
    ItemStatus.PROCESSING: ("Wird erstellt …", "accent"),
    ItemStatus.SUCCESS: ("Erstellt", "success"),
    ItemStatus.WARNING: ("Erstellt mit Hinweis", "caution"),
    ItemStatus.FAILED: ("Fehler", "critical"),
    ItemStatus.SKIPPED: ("Übersprungen", "neutral"),
}
FAILED_LABELS = {"file_missing": "Datei nicht gefunden", "no_active": "Keine aktiven Verträge", "unreadable": "Excel nicht lesbar", "columns_missing": "Spalten fehlen"}
SOURCE_TEXT = {
    resolver.SOURCE_ITEM: "eigene Angabe",
    resolver.SOURCE_CUSTOMER: "aus der Kundenakte",
    resolver.SOURCE_EXCEL: "aus der Excel",
    resolver.SOURCE_BATCH: "Stapel-Einstellung",
    resolver.SOURCE_DEFAULT: "Standard",
}
EDIT_DELAY = 450


def status_label(item) -> tuple[str, str]:
    label, tone = STATUS[item.status]
    if item.status is ItemStatus.FAILED and not item.error:
        code = next((issue.code for issue in item.issues if issue.code in FAILED_LABELS), "")
        label = FAILED_LABELS.get(code, label)
    return label, tone


def facts_line(item) -> str:
    """Kompakt und ohne Doppelungen: »5 aktive · 3 inaktiv ausgeblendet · rechnung@kunde.de«."""
    analysis = item.analysis
    if analysis is None or not analysis.ok:
        return ""
    if analysis.active:
        parts = [contract_summary(analysis.active, analysis.inactive, short=True)]
    else:
        parts = [f"{analysis.inactive} inaktiv ausgeblendet"] if analysis.inactive else []  # »Keine aktiven Verträge« steht als Status
    if len(analysis.emails) == 1:
        parts.append(analysis.emails[0])
    elif len(analysis.emails) > 1:
        parts.append(f"{len(analysis.emails)} Rechnungsempfänger")
    return " · ".join(parts)


def short_error(text: str) -> str:
    """Für die Liste: ohne technische Einzelheiten in Klammern (vollständig im Eintrag)."""
    head = text.split(" (", 1)[0].strip()
    return head if head.endswith(".") or not head else head + "."


def detail_line(item, res) -> tuple[str, str]:
    status = item.status
    if status is ItemStatus.PROCESSING:
        return "Wird erstellt …", "accent"
    if status in CREATED:
        text = f"Erstellt: {Path(item.output).name}"
        if status is ItemStatus.WARNING and item.notes:
            return f"{text} · {item.notes[0]}", "caution"
        return text, "success"
    if status is ItemStatus.SKIPPED:
        return (item.notes[0] if item.notes else "Übersprungen"), "text2"
    if status is ItemStatus.FAILED:
        if item.error:
            return item.error, "critical"
        code = next((issue.code for issue in item.issues if issue.code in FAILED_LABELS), "")
        if code in ("no_active", "file_missing"):
            return "", "text2"  # steht schon als Status (»Keine aktiven Verträge«, »Datei nicht gefunden«)
        if item.analysis is not None and not item.analysis.ok and item.analysis.error:
            return short_error(item.analysis.error), "critical"
        return (item.issues[0].text if item.issues else "Fehler"), "critical"
    if res is None or status in (ItemStatus.PENDING, ItemStatus.ANALYZING):
        return "", "text2"
    if status is ItemStatus.NEEDS_INPUT:
        missing = [issue.text for issue in res.issues if issue.area != "kunde"]
        return " · ".join([res.customer_line, *missing]), "caution"
    note = f" · {item.notes[0]}" if item.notes else ""
    return res.customer_line + note, "text2"


class BatchPage:
    """Liste und Detailansicht des Stapels."""

    def __init__(self, app: "App", page: Page) -> None:
        self.app = app
        self.page = page
        self.item_id: str | None = None
        self._job = None
        self._edit_job = None
        self._loading = False
        self.var_company = tk.StringVar(app, "")
        self.var_number = tk.StringVar(app, "")
        self.var_email = tk.StringVar(app, "")
        self.var_subfolders = tk.BooleanVar(app, app.batch_settings.subfolders)
        self.var_customer_target = tk.BooleanVar(app, app.batch_settings.customer_target)
        self._build_list()
        self._build_detail()
        for var in (self.var_company, self.var_number, self.var_email):
            var.trace_add("write", lambda *_a: self._schedule_edit())
        self.show_list()

    # Aufbau: Liste --------------------------------------------------------------------------------
    def _build_list(self) -> None:
        app, content = self.app, self.page.content
        ui = app.ui
        self.list_view = frame(content)
        tools = FlowRow(self.list_view, gap=8, row_gap=8)
        tools.pack(fill="x")
        tools.add(Button(tools, "Excel-Dateien hinzufügen", app.pick_batch_files, icon=icons.ADD, tooltip="Mehrere Excel-Dateien wählen (Strg+O)"))
        tools.add(Button(tools, "Ordner hinzufügen", app.pick_batch_folder, icon=icons.FOLDER_OPEN, tooltip="Alle Excel-Dateien eines Ordners hinzufügen (ohne Unterordner)"))
        self.btn_new = Button(tools, "Neuer Stapel", app.batch_new, icon=icons.REFRESH, kind="subtle", tooltip="Liste leeren – Dateien, Kundenakten, Vorlagen und Einstellungen bleiben")
        tools.add(self.btn_new)
        self.tools = tools
        ui.batch_info = InfoBar(self.list_view)
        ui.batch_info.pack(fill="x", pady=(px(8), 0))

        top = ResponsiveColumns(self.list_view, central=True)
        top.pack(fill="x", pady=(px(12), 0))
        # Links: Stapel (Zusammenfassung, Fortschritt, Erstellen) bzw. der leere Zustand
        self.left = frame(top)
        top.add(self.left)
        self._build_empty(self.left)
        self._build_run(self.left)
        # Rechts: Ausgabe und Standards
        self._build_settings(top)

        self.list_area = frame(self.list_view)
        filters = frame(self.list_area)
        filters.pack(fill="x", pady=(px(16), 0))
        self.filters = SelectorBar(filters, [(key, FILTER_LABELS[key]) for key in FILTERS], app.batch_filter, app.set_batch_filter)
        self.filters.pack(side="left")
        ui.batch_filters = self.filters
        bulk = FlowRow(self.list_area, gap=8, row_gap=8)
        bulk.pack(fill="x", pady=(px(8), 0))
        self.check_all = CheckBox(bulk, "Alle auswählen", self._toggle_all)
        bulk.add(self.check_all)
        self.selected_text = Text(bulk, "", style="caption", color="text2")
        bulk.add(self.selected_text)
        self.btn_template = Button(bulk, "Vorlage anwenden …", self.apply_template, icon=icons.PAGE, tooltip="Dieselbe Vorlage für alle ausgewählten Einträge setzen")
        bulk.add(self.btn_template)
        self.btn_remove = Button(bulk, "Auswahl entfernen", app.batch_remove_selected, icon=icons.DELETE, tooltip="Ausgewählte Einträge aus dem Stapel nehmen (die Dateien bleiben)")
        bulk.add(self.btn_remove)
        self.list_card = Card(self.list_area, padding=6)
        self.list_card.pack(fill="x", pady=(px(8), 0))
        self.listing = BatchList(self.list_card.body, on_open=self.show_detail, on_toggle=app.batch_select)
        self.listing.pack(fill="x")
        ui.batch_list = self.listing
        self.filter_empty = Text(self.list_area, "", style="body", color="text2")

    def _build_empty(self, master) -> None:
        app = self.app
        self.empty = RoundedFrame(master, fill="card", stroke="card_stroke")
        inner = frame(self.empty)
        inner.pack(fill="x", padx=px(24), pady=px(28))
        if ctx().icons_available:
            Icon(inner, icons.LIBRARY, color="text2", size="icon_large").pack(anchor="w")
        Text(inner, EMPTY_TITLE, style="body_strong", wrap=True).pack(anchor="w", fill="x", pady=(px(10), px(4)))
        Text(inner, EMPTY_TEXT, style="body", color="text2", wrap=True).pack(anchor="w", fill="x")
        buttons = FlowRow(inner, gap=8, row_gap=8)
        buttons.pack(fill="x", pady=(px(14), 0))
        buttons.add(Button(buttons, "Dateien hinzufügen", app.pick_batch_files, icon=icons.ADD, kind="accent"))
        buttons.add(Button(buttons, "Ordner hinzufügen", app.pick_batch_folder, icon=icons.FOLDER_OPEN))
        Text(inner, EMPTY_HINT, style="caption", color="text2", wrap=True).pack(anchor="w", fill="x", pady=(px(12), 0))
        self.empty.lift_corners()

    def _build_run(self, master) -> None:
        app = self.app
        ui = app.ui
        self.run_card = Card(master, "Stapel", icons.LIBRARY)
        body = self.run_card.body
        self.summary = StatusLine(body)
        self.summary.pack(fill="x")
        ui.batch_summary = self.summary
        # Fortschritt (nur während der Erstellung)
        self.progress_area = Collapsible(body)
        self.progress_area.pack(fill="x")
        inner = self.progress_area.content
        self.progress = ProgressBar(inner)
        self.progress.pack(fill="x", pady=(px(10), px(2)))
        ui.batch_progress = self.progress
        self.progress_text = Text(inner, "", style="body")
        self.progress_text.pack(anchor="w")
        current = frame(inner)
        current.pack(fill="x", pady=(px(2), 0))
        self.ring = ProgressRing(current, size=16)
        self.ring.pack(side="left", padx=(0, px(8)))
        self.current_text = Text(current, "", style="caption", color="text2", width=1)
        self.current_text.pack(side="left", fill="x", expand=True)
        # Ergebnis des letzten Durchlaufs (Aktionen brechen bei schmalem Fenster um)
        self.result = ResultPanel(body, app)
        self.result.holder.pack(fill="x", pady=(px(10), 0))
        ui.batch_result = self.result
        self.actions = FlowRow(body, gap=8, row_gap=8)
        self.actions.pack(fill="x", pady=(px(12), 0))
        self.btn_run = Button(self.actions, RUN_TEXT, app.batch_start, icon=icons.DOCUMENT, kind="accent", height=40, font="body_strong", tooltip="Alle bereiten Einträge nacheinander erstellen (Strg+Enter)")
        self.actions.add(self.btn_run)
        ui.btn_batch_run = self.btn_run
        self.btn_cancel = Button(self.actions, "Stapel abbrechen", app.batch_cancel, icon=icons.STOP, height=40, tooltip="Nach der laufenden PDF anhalten – fertige PDFs bleiben erhalten")
        self.actions.add(self.btn_cancel)
        self.btn_retry = Button(self.actions, "Fehlgeschlagene erneut versuchen", app.batch_retry_failed, icon=icons.REFRESH, height=40, tooltip="Nur fehlgeschlagene Einträge erneut prüfen und erstellen")
        self.actions.add(self.btn_retry)
        self.run_card.lift_corners()

    def _build_settings(self, columns) -> None:
        app = self.app
        settings = app.batch_settings
        card = Card(columns, "Ausgabe und Standards", icons.SETTINGS, "Gilt für alle Einträge. Angaben einer Kundenakte oder eines Eintrags haben Vorrang.")
        columns.add(card)
        body = card.body
        self.row_target = FileRow(body, icons.FOLDER, "Zielordner")
        self.row_target.pack(fill="x")
        Button(self.row_target.buttons, "Durchsuchen", app.pick_batch_target, icon=icons.FOLDER_OPEN, tooltip="Gemeinsamen Zielordner wählen").pack(side="right")
        Divider(body).pack(fill="x", pady=px(8))
        grid = frame(body)
        grid.pack(fill="x")
        grid.columnconfigure(1, weight=1)
        Text(grid, "Standardvorlage", style="body").grid(row=0, column=0, sticky="w", padx=(0, px(12)))
        self.template_combo = ComboBox(grid, command=self._batch_template_picked, placeholder=TEMPLATE_NONE, width=230, tooltip="Vorlage für Einträge ohne eigene Vorlage und ohne Vorlage der Kundenakte")
        self.template_combo.grid(row=0, column=1, sticky="w")
        Text(grid, "Vorhandene PDF", style="body").grid(row=1, column=0, sticky="w", padx=(0, px(12)), pady=(px(6), 0))
        self.conflict_combo = ComboBox(grid, [CONFLICT_LABELS[mode] for mode in ConflictMode], command=self._conflict_picked, width=230, tooltip="Was geschieht, wenn es die PDF schon gibt (Standard: automatisch nummerieren)")
        self.conflict_combo.set(CONFLICT_LABELS[settings.conflict])
        self.conflict_combo.grid(row=1, column=1, sticky="w", pady=(px(6), 0))
        # Seltener gebraucht: hinter »Weitere Einstellungen«
        self.btn_more = Button(body, "Weitere Einstellungen", self.toggle_more, icon=icons.CHEVRON_DOWN, kind="subtle", tooltip="Standardlogo, Unterordner je Kunde, Zielordner der Kundenakte")
        self.btn_more.pack(anchor="w", pady=(px(8), 0))
        self.more = Collapsible(body)
        self.more.pack(fill="x")
        more = self.more.content
        self.row_logo = FileRow(more, icons.PICTURE, "Standardlogo")
        self.row_logo.pack(fill="x", pady=(px(6), 0))
        Button(self.row_logo.buttons, "Durchsuchen", app.pick_batch_logo, icon=icons.OPEN_FILE, tooltip="Logo für Einträge ohne eigenes Logo").pack(side="right")
        IconButton(self.row_logo.buttons, icons.REFRESH, lambda: app.batch_update_settings(logo=""), tooltip="Installiertes Standardlogo verwenden").pack(side="right", padx=(0, px(4)))
        toggles = frame(more)
        toggles.pack(fill="x", pady=(px(8), 0))
        for var, text, key in (
            (self.var_subfolders, "Unterordner je Kunde (»123456 Beispiel GmbH«)", "subfolders"),
            (self.var_customer_target, "Zielordner der Kundenakte verwenden", "customer_target"),
        ):
            row = frame(toggles)
            row.pack(fill="x", pady=(px(2), 0))
            ToggleSwitch(row, var, command=lambda v=var, k=key: app.batch_update_settings(**{k: bool(v.get())}), show_text=False).pack(side="left")
            Text(row, text, style="body", wrap=True).pack(side="left", fill="x", expand=True, padx=(px(8), 0))
        note = frame(body)
        note.pack(fill="x", pady=(px(10), 0))
        if ctx().icons_available:
            Icon(note, icons.SHIELD, color="text2").pack(side="left", anchor="n", padx=(0, px(8)), pady=(px(1), 0))
        Text(note, PRIVACY, style="caption", color="text2", wrap=True).pack(side="left", fill="x", expand=True)
        card.lift_corners()

    def toggle_more(self) -> None:
        if self.more.expanded:
            self.more.collapse()
            self.btn_more.set_text("Weitere Einstellungen")
        else:
            self.more.expand()
            self.btn_more.set_text("Weniger Einstellungen")

    # Aufbau: Detail ---------------------------------------------------------------------------------
    def _build_detail(self) -> None:
        app = self.app
        ui = app.ui
        self.detail_view = frame(self.page.content)
        top = frame(self.detail_view)
        top.pack(fill="x")
        Button(top, "Alle Einträge", self.show_list, icon=icons.BACK, kind="subtle", tooltip="Zurück zur Liste").pack(side="left")
        nav = frame(top)
        nav.pack(side="right")
        self.btn_prev = IconButton(nav, icons.CHEVRON_LEFT, lambda: self.step(-1), tooltip="Vorheriger Eintrag")
        self.btn_prev.pack(side="left")
        self.position = Text(nav, "", style="caption", color="text2")
        self.position.pack(side="left", padx=px(8))
        self.btn_next = IconButton(nav, icons.CHEVRON_RIGHT, lambda: self.step(1), tooltip="Nächster Eintrag")
        self.btn_next.pack(side="left")
        self.d_title = Text(self.detail_view, "", style="subtitle", wrap=True)
        self.d_title.pack(anchor="w", fill="x", pady=(px(12), 0))
        self.d_path = Text(self.detail_view, "", style="caption", color="text2", wrap=True)
        self.d_path.pack(anchor="w", fill="x", pady=(px(2), 0))
        self.d_status = StatusLine(self.detail_view)
        self.d_status.pack(fill="x", pady=(px(10), 0))
        ui.batch_detail_status = self.d_status
        ui.batch_detail_info = InfoBar(self.detail_view)
        ui.batch_detail_info.pack(fill="x", pady=(px(8), 0))

        columns = ResponsiveColumns(self.detail_view, central=True)
        columns.pack(fill="x", pady=(px(12), 0))
        # Excel-Prüfung: Statuszeile und nur zusätzliche Angaben (wie im Einzelmodus)
        excel = Card(columns, "Excel-Prüfung", icons.BULLETED_LIST)
        columns.add(excel)
        self.d_summary = InfoBar(excel.body, closable=False)
        self.d_summary.pack(fill="x")
        self.d_mail_row = frame(excel.body)
        self.d_mail_row.pack(fill="x", pady=(px(8), 0))
        self.d_mail_row.columnconfigure(0, minsize=px(DETAIL_LABEL_WIDTH))
        self.d_mail_row.columnconfigure(1, weight=1)
        Text(self.d_mail_row, "Rechnungsempfänger", style="caption", color="text2").grid(row=0, column=0, sticky="w", padx=(0, px(12)))
        self.d_mail_value = Text(self.d_mail_row, "", style="body", width=1)
        self.d_mail_value.grid(row=0, column=1, sticky="ew")
        self.d_mail_combo = ComboBox(self.d_mail_row, placeholder="Empfänger wählen", command=self._mail_picked, width=210, tooltip="Rechnungsempfänger für diese Übersicht")
        self.d_mail_combo.grid(row=0, column=2, sticky="e", padx=(px(8), 0))
        self.d_mail_field = TextField(self.d_mail_row, self.var_email, placeholder="E-Mail-Adresse (optional)", width=210)
        self.d_mail_field.grid(row=0, column=2, sticky="e", padx=(px(8), 0))
        ui.batch_mail_combo = self.d_mail_combo
        self.d_facts = FactList(excel.body, label_width=DETAIL_LABEL_WIDTH)
        self.d_facts.pack(fill="x", pady=(px(4), 0))
        excel.lift_corners()
        # Kunde
        kunde = Card(columns, "Kunde", icons.CONTACT)
        columns.add(kunde)
        body = kunde.body
        self.d_customer = Text(body, "", style="body_strong", wrap=True)
        self.d_customer.pack(anchor="w", fill="x")
        self.d_customer_note = Text(body, "", style="caption", color="text2", wrap=True)
        self.d_customer_note.pack(anchor="w", fill="x")
        row = FlowRow(body, gap=6, row_gap=6)
        row.pack(fill="x", pady=(px(8), 0))
        self.btn_pick = Button(row, "Kunden auswählen …", lambda: app.batch_choose_customer(self.item_id), icon=icons.PEOPLE, tooltip="Bekannten Kunden für diesen Eintrag wählen")
        row.add(self.btn_pick)
        self.btn_no_customer = Button(row, "Ohne Kundenakte", lambda: app.batch_set_customer(self.item_id, CustomerMode.NONE), kind="subtle", tooltip="Diesen Eintrag ohne Kundenakte erstellen – Angaben selbst eintragen")
        row.add(self.btn_no_customer)
        self.btn_auto_customer = Button(row, "Automatisch erkennen", lambda: app.batch_set_customer(self.item_id, CustomerMode.AUTO), kind="subtle", tooltip="Kunden wieder über die Rechnungsempfänger erkennen")
        row.add(self.btn_auto_customer)
        self.customer_buttons = row
        field_label(body, "Firmenname")
        self.field_company = TextField(body, self.var_company, placeholder="z. B. Muster GmbH")
        self.field_company.pack(fill="x")
        field_label(body, "Kundennummer")
        self.field_number = TextField(body, self.var_number, placeholder="z. B. 10042")
        self.field_number.pack(fill="x")
        self.d_value_source = Text(body, "", style="caption", color="text2", wrap=True)
        self.d_value_source.pack(anchor="w", fill="x", pady=(px(4), 0))
        ui.batch_mail_info = InfoBar(body)
        ui.batch_mail_info.pack(fill="x", pady=(px(8), 0))
        kunde.lift_corners()

        # Darstellung und Ausgabe
        output = Card(self.detail_view, "Darstellung und Ausgabe", icons.DOCUMENT, "Eigene Angaben gelten nur für diesen Eintrag; »Zurücksetzen« übernimmt wieder Kundenakte bzw. Stapel.")
        output.pack(fill="x", pady=(px(12), 0))
        body = output.body
        row = frame(body)
        row.pack(fill="x")
        Text(row, "Vorlage", style="body").pack(side="left", padx=(0, px(12)))
        self.d_template = ComboBox(row, command=self._template_picked, width=220, tooltip="»Automatisch«: Vorlage der Kundenakte, sonst Standardvorlage des Stapels")
        self.d_template.pack(side="left")
        self.d_template_note = Text(body, "", style="caption", color="text2", wrap=True)
        self.d_template_note.pack(anchor="w", fill="x", pady=(px(4), 0))
        Divider(body).pack(fill="x", pady=px(8))
        self.d_logo = FileRow(body, icons.PICTURE, "Logo")
        self.d_logo.pack(fill="x")
        Button(self.d_logo.buttons, "Durchsuchen", self.pick_logo, icon=icons.OPEN_FILE).pack(side="right")
        self.btn_logo_reset = IconButton(self.d_logo.buttons, icons.UNDO, lambda: app.batch_edit(self.item_id, logo=None), tooltip="Zurücksetzen (Kundenakte bzw. Stapel)")
        self.btn_logo_reset.pack(side="right", padx=(0, px(4)))
        Divider(body).pack(fill="x", pady=px(8))
        self.d_target = FileRow(body, icons.FOLDER, "Zielordner")
        self.d_target.pack(fill="x")
        Button(self.d_target.buttons, "Durchsuchen", self.pick_target, icon=icons.FOLDER_OPEN).pack(side="right")
        self.btn_target_reset = IconButton(self.d_target.buttons, icons.UNDO, lambda: app.batch_edit(self.item_id, target_dir=None), tooltip="Zurücksetzen (Kundenakte bzw. Stapel)")
        self.btn_target_reset.pack(side="right", padx=(0, px(4)))
        self.d_output = Text(body, "", style="caption", color="text2", wrap=True)
        self.d_output.pack(anchor="w", fill="x", pady=(px(8), 0))
        output.lift_corners()

        actions = FlowRow(self.detail_view, gap=8, row_gap=8)
        actions.pack(fill="x", pady=(px(16), 0))
        self.btn_preview = Button(actions, "Vorschau", lambda: app.batch_preview(self.item_id), icon=icons.VIEW, kind="accent", tooltip="Diesen Eintrag in der Vorschau ansehen – dieselbe Vorschau wie im Einzelmodus")
        actions.add(self.btn_preview)
        self.btn_single = Button(actions, "Einzeln bearbeiten", lambda: app.batch_edit_single(self.item_id), icon=icons.EDIT, tooltip="Eintrag in »Übersicht erstellen« übernehmen")
        actions.add(self.btn_single)
        self.btn_open_pdf = Button(actions, "PDF öffnen", self.open_pdf, icon=icons.OPEN_IN_WINDOW)
        actions.add(self.btn_open_pdf)
        self.btn_open_folder = Button(actions, "Ordner öffnen", self.open_folder, icon=icons.FOLDER_OPEN)
        actions.add(self.btn_open_folder)
        actions.add(Button(actions, "Aus Stapel entfernen", lambda: self.remove_current(), icon=icons.DELETE, tooltip="Eintrag aus dem Stapel nehmen – die Datei bleibt"))
        self.detail_actions = actions

    # Ansichten ------------------------------------------------------------------------------------------
    def show_list(self) -> None:
        self._flush_edit()
        self.item_id = None
        self.detail_view.pack_forget()
        if not self.list_view.winfo_manager():
            self.list_view.pack(fill="x")
        self.refresh()
        try:
            self.page.scroll.to_top()
        except tk.TclError:
            pass

    def show_detail(self, item_id: str) -> None:
        if item_id not in self.app.batch_by_id:
            self.show_list()
            return
        self._flush_edit()
        self.item_id = item_id
        self.list_view.pack_forget()
        if not self.detail_view.winfo_manager():
            self.detail_view.pack(fill="x")
        self.app.hide_notice("batch_detail_info")
        self.refresh_detail(load_fields=True)
        try:
            self.page.scroll.to_top()
        except tk.TclError:
            pass

    def step(self, delta: int) -> None:
        order = [item.id for item in self.app.batch_visible()] or [item.id for item in self.app.batch_items]
        if self.item_id not in order:
            order = [item.id for item in self.app.batch_items]
        if self.item_id not in order:
            return
        index = order.index(self.item_id) + delta
        if 0 <= index < len(order):
            self.show_detail(order[index])

    # Aktualisieren (gesammelt) -----------------------------------------------------------------------------
    def invalidate(self, item_ids=None, structure: bool = False) -> None:
        if self._job is None:
            try:
                self._job = self.app.after_idle(self._flush)
            except tk.TclError:
                self._job = None

    def _flush(self) -> None:
        self._job = None
        self.refresh()

    def refresh(self) -> None:
        app = self.app
        if self.item_id is not None:
            if self.item_id not in app.batch_by_id:
                self.show_list()
                return
            self.refresh_detail(load_fields=False)
            return
        items = app.batch_items
        has_items = bool(items)
        # leerer Zustand bzw. Stapel
        if has_items:
            if self.empty.winfo_manager():
                self.empty.pack_forget()
            if not self.run_card.winfo_manager():
                self.run_card.pack(fill="both", expand=True)
            if not self.list_area.winfo_manager():
                self.list_area.pack(fill="x")
        else:
            if self.run_card.winfo_manager():
                self.run_card.pack_forget()
            if not self.empty.winfo_manager():
                self.empty.pack(fill="both", expand=True)
            if self.list_area.winfo_manager():
                self.list_area.pack_forget()
        # Leer: Die Karte »Noch keine Excel-Dateien« bietet dieselben Aktionen – oben keine Doppelung.
        if has_items and not self.tools.winfo_manager():
            self.tools.pack(fill="x", before=self.app.ui.batch_info)
        elif not has_items and self.tools.winfo_manager():
            self.tools.pack_forget()
        self._refresh_settings()
        if not has_items:
            self.listing.set_rows([])
            return
        counts = app.batch_counts()
        # Die Anzahlen stehen in der Zusammenfassung oben – die Filter wiederholen sie nicht.
        self.filters.select(app.batch_filter)
        self._refresh_summary(counts)
        visible = app.batch_visible()
        rows = []
        for item in visible:
            res = app.batch_resolutions.get(item.id)
            label, tone = status_label(item)
            detail, detail_tone = detail_line(item, res)
            rows.append(RowData(item.id, item.name, facts_line(item), detail, detail_tone, label, tone, item.selected))
        self.listing.set_rows(rows)
        if rows:
            if self.filter_empty.winfo_manager():
                self.filter_empty.pack_forget()
            if not self.list_card.winfo_manager():
                self.list_card.pack(fill="x", pady=(px(8), 0))
        else:
            self.list_card.pack_forget()
            self.filter_empty.configure(text=FILTER_EMPTY.get(app.batch_filter, "Keine Einträge."))
            if not self.filter_empty.winfo_manager():
                self.filter_empty.pack(anchor="w", pady=(px(12), 0))
        selected = [item for item in visible if item.selected]
        self.check_all.set_state(True if visible and len(selected) == len(visible) else (None if selected else False))
        total_selected = len(app.batch_selected())
        self.selected_text.configure(text=f"{total_selected} ausgewählt" if total_selected else "")
        busy = app.batch_running
        self.btn_template.set_enabled(bool(total_selected) and not busy)
        self.btn_remove.set_enabled(bool(total_selected) and not busy)
        self.check_all.set_enabled(bool(visible))

    def _refresh_summary(self, counts: dict[str, int]) -> None:
        app = self.app
        running = app.batch_running
        total = counts["all"]
        waiting = sum(1 for item in app.batch_items if item.status in (ItemStatus.PENDING, ItemStatus.ANALYZING))
        parts = ["1 Datei" if total == 1 else f"{total} Dateien", f"{counts['ready']} bereit"]
        if counts["needs_input"]:
            parts.append(f"{counts['needs_input']} Angaben erforderlich")
        if counts["failed"]:
            parts.append("1 Fehler" if counts["failed"] == 1 else f"{counts['failed']} Fehler")
        if counts["done"]:
            parts.append(f"{counts['done']} fertig")
        if waiting:
            parts.append(f"{waiting} {'wird' if waiting == 1 else 'werden'} geprüft")
        text = " · ".join(parts)
        if running or waiting:
            kind = "busy"
        elif counts["failed"] or counts["needs_input"]:
            kind = "caution"  # einzelne Einträge – der Stapel selbst ist nicht fehlerhaft
        elif counts["ready"] or counts["done"]:
            kind = "success"
        else:
            kind = "neutral"
        self.summary.set(kind, text)
        runner = app.batch_runner
        if running and runner is not None:
            summary = runner.summary
            processed = summary.processed + summary.cancelled
            self.progress.set(processed / max(1, summary.total), error=bool(summary.failed))
            done_text = f"{summary.created} von {summary.total} {'Übersicht' if summary.total == 1 else 'Übersichten'} erstellt"
            extra = [f"{summary.failed} fehlgeschlagen"] if summary.failed else []
            if summary.skipped:
                extra.append(f"{summary.skipped} übersprungen")
            self.progress_text.configure(text=" · ".join([done_text, *extra]))
            job = runner.current_job
            if runner.cancel_requested:
                current = "Wird abgebrochen – die laufende PDF wird sauber beendet …"
            elif job is not None:
                current = f"{job.label} wird verarbeitet …"
            else:
                current = ""
            self.current_text.configure(text=current)
            if not self.progress_area.expanded:
                self.progress_area.expand(animate=False)
                self.ring.start()
        elif self.progress_area.expanded:
            self.progress_area.collapse(animate=False)
            self.ring.stop()
        # Aktionen
        self.btn_run.set_enabled(bool(counts["ready"]) and not running)
        self.actions.set_visible(self.btn_cancel, running)
        self.btn_cancel.set_enabled(running and not (runner is not None and runner.cancel_requested))
        self.actions.set_visible(self.btn_retry, bool(counts["failed"]) and not running)
        # Ergebnis – solange es sichtbar ist, nennt es die Anzahlen (die Zusammenfassung tritt zurück)
        result = app.batch_summary
        if result is not None and not running:
            self.result.show(result, app.batch_summary_text(result).split(": ", 1)[1], bool(app.batch_output_folders()), bool(counts["failed"]))
            if self.summary.winfo_manager():
                self.summary.pack_forget()
        else:
            self.result.hide()
            if not self.summary.winfo_manager():
                self.summary.pack(fill="x", before=self.progress_area)
        # »Neuer Stapel« steht im Ergebnis – oben nur, solange es kein Ergebnis gibt
        self.tools.set_visible(self.btn_new, bool(app.batch_items) and not running and not self.result.visible())

    def _refresh_settings(self) -> None:
        app = self.app
        settings = app.batch_settings
        text, full = (Path(settings.target_dir).name or settings.target_dir, settings.target_dir) if settings.target_dir else ("Kein Zielordner gewählt", "")
        self.row_target.set_value(text, full)
        if settings.logo:
            name, full = path_caption(settings.logo, "")
            self.row_logo.set_value(name + ("" if Path(settings.logo).is_file() else " – nicht gefunden"), full)
        else:
            self.row_logo.set_value("Installiertes Standardlogo", "")
        names = app.batch_template_names()
        if self.template_combo.values() != [TEMPLATE_NONE, *names]:
            self.template_combo.set_values([TEMPLATE_NONE, *names], keep=False)
        self.template_combo.set(settings.template if settings.template in names else TEMPLATE_NONE)
        self.conflict_combo.set(CONFLICT_LABELS[settings.conflict])
        if bool(self.var_subfolders.get()) != settings.subfolders:
            self.var_subfolders.set(settings.subfolders)
        if bool(self.var_customer_target.get()) != settings.customer_target:
            self.var_customer_target.set(settings.customer_target)

    # Detail ------------------------------------------------------------------------------------------------------
    def current(self):
        return self.app.batch_by_id.get(self.item_id) if self.item_id else None

    def refresh_detail(self, load_fields: bool = False) -> None:
        app = self.app
        item = self.current()
        if item is None:
            return
        res = app.batch_resolution(item.id)
        order = [entry.id for entry in app.batch_visible()]
        if item.id not in order:
            order = [entry.id for entry in app.batch_items]
        index = order.index(item.id)
        self.position.configure(text=f"{index + 1} von {len(order)}")
        self.btn_prev.set_enabled(index > 0)
        self.btn_next.set_enabled(index < len(order) - 1)
        self.d_title.configure(text=item.name)
        self.d_path.configure(text=str(Path(item.path).parent))
        label, _tone = status_label(item)
        kind = {"success": "success", "caution": "caution", "critical": "critical", "accent": "busy", "neutral": "neutral"}[STATUS[item.status][1]]
        if item.status in (ItemStatus.ANALYZING, ItemStatus.PENDING):
            kind = "busy"
        if item.status is ItemStatus.NEEDS_INPUT and res is not None:
            detail = " · ".join(issue.text for issue in res.issues)
        elif item.status is ItemStatus.FAILED:
            detail = item.error or (item.analysis.error if item.analysis is not None and not item.analysis.ok else "") or " · ".join(issue.text for issue in item.issues[:1])
        else:
            detail = ""
        self.d_status.set(kind, label + (f": {detail}" if detail and detail != label else ""))
        # Hinweise (nicht blockierend) und Ergebnis
        notes = [note for note in item.notes if note]
        if item.status in CREATED and item.output:
            app.notify("batch_detail_info", "success" if item.status is ItemStatus.SUCCESS else "warning", " ".join(notes) or Path(item.output).name, title="Erstellt", status=False, animate=False)
        elif notes and item.status not in DONE:
            app.notify("batch_detail_info", "info", " ".join(notes), status=False, animate=False)
        else:
            app.hide_notice("batch_detail_info")
        self._refresh_excel(item, res)
        self._refresh_customer(item, res, load_fields)
        self._refresh_output(item, res)
        running = item.status is ItemStatus.PROCESSING
        for button in (self.btn_pick, self.btn_no_customer, self.btn_auto_customer):
            button.set_enabled(not running)
        self.customer_buttons.set_visible(self.btn_no_customer, item.customer_mode is not CustomerMode.NONE)
        self.customer_buttons.set_visible(self.btn_auto_customer, item.customer_mode is not CustomerMode.AUTO)
        has_output = item.status in CREATED and bool(item.output) and Path(item.output).is_file()
        self.detail_actions.set_visible(self.btn_open_pdf, has_output)
        self.detail_actions.set_visible(self.btn_open_folder, has_output)
        preview_ok, _problem = (True, "") if res is None else (not any(issue.code in resolver.PREVIEW_BLOCKING for issue in res.issues), "")
        self.btn_preview.set_enabled(preview_ok and item.analysis is not None and item.analysis.ok)

    def _refresh_excel(self, item, res) -> None:
        analysis = item.analysis
        bar = self.d_summary
        if analysis is None:
            bar.show("info", "Excel wird geprüft …", animate=False)
            facts: list[tuple[str, str, str]] = []
        elif not analysis.ok:
            bar.show("error", analysis.error or "Die Datei konnte nicht gelesen werden.", "Excel-Prüfung fehlgeschlagen", animate=False)
            facts = []
        elif analysis.missing:
            spalten = ", ".join(f"»{name}«" for name in analysis.missing)
            bar.show("error", f"Für die PDF fehlt {'die Spalte' if len(analysis.missing) == 1 else 'die Spalten'} {spalten}.", "Spalten fehlen", animate=False)
            facts = []
        elif not analysis.active:
            bar.show("warning", "In der Datei steht kein aktiver Vertrag." + (f" {analysis.inactive} inaktive wurden ausgeblendet." if analysis.inactive else ""), "Keine aktiven Verträge", animate=False)
            facts = []
        else:
            bar.show("success", contract_summary(analysis.active, analysis.inactive), "Excel geprüft", animate=False)
            facts = []
            if len(analysis.numbers) > 1:
                facts.append(("Kundennummer", f"{len(analysis.numbers)} verschiedene in der Datei: " + ", ".join(analysis.numbers), "caution"))
            if len(analysis.companies) > 1:
                facts.append(("Firmenname", f"{len(analysis.companies)} verschiedene in der Datei: " + ", ".join(analysis.companies), "caution"))
            if analysis.bold:
                facts.append(("Fettschrift", f"{analysis.bold} {'Zelle' if analysis.bold == 1 else 'Zellen'} in der PDF fett", "muted"))
            for hint in analysis.hints:
                if "Rechnungsempfänger" not in hint:
                    facts.append(("Hinweis", hint, "muted"))
        self.d_facts.set(facts)
        emails = list(analysis.emails) if analysis is not None and analysis.ok else []
        if len(emails) > 1:
            self.d_mail_value.configure(text=f"{len(emails)} erkannt")
            self.d_mail_combo.set_values(emails, keep=False)
            self.d_mail_combo.set(res.email if res is not None and res.email in emails else None)
            self.d_mail_combo.grid()
            self.d_mail_field.grid_remove()
        elif len(emails) == 1:
            self.d_mail_value.configure(text=emails[0])
            self.d_mail_combo.grid_remove()
            self.d_mail_field.grid_remove()
        elif analysis is not None and analysis.ok:
            self.d_mail_value.configure(text="keine in der Excel")
            self.d_mail_combo.grid_remove()
            self.d_mail_field.grid()
        else:
            self.d_mail_value.configure(text="–")
            self.d_mail_combo.grid_remove()
            self.d_mail_field.grid_remove()

    def _refresh_customer(self, item, res, load_fields: bool) -> None:
        app = self.app
        if res is None:
            return
        if res.customer is not None:
            self.d_customer.configure(text=res.customer.label)
            via = ", ".join(res.match.emails_of(res.customer.id)) if res.match is not None else ""
            note = f"Erkannt an {via}" if res.customer_source == "erkannt" and via else ("Bewusst gewählt" if res.customer_source == "gewählt" else "")
            self.d_customer_note.configure(text=note + (" · Kundenakte bleibt unverändert – Angaben hier gelten nur für diesen Eintrag." if note else ""))
        elif item.customer_mode is CustomerMode.NONE:
            self.d_customer.configure(text="Ohne Kundenakte")
            self.d_customer_note.configure(text="Firmenname und Kundennummer bitte selbst eintragen (oder aus der Excel).")
        else:
            conflict = [issue for issue in res.issues if issue.area == "kunde"]
            if conflict and conflict[0].code == "customer_conflict":
                names = ", ".join(f"„{c.label}“" for c in (app.customers.get(i) for i in (res.match.customer_ids if res.match else ())) if c is not None)
                self.d_customer.configure(text="Mehrere bekannte Kunden")
                self.d_customer_note.configure(text=f"Die Excel enthält Rechnungsempfänger, die verschiedenen bekannten Kunden zugeordnet sind: {names}. Bitte den passenden Kunden auswählen.")
            elif conflict:
                self.d_customer.configure(text="Kunde bitte prüfen")
                self.d_customer_note.configure(text=conflict[0].text)
            elif res.company and res.number:
                self.d_customer.configure(text="Keine Kundenakte zugeordnet")
                self.d_customer_note.configure(text="Die Angaben gelten nur für diesen Eintrag.")
            else:
                self.d_customer.configure(text="Kunde nicht zugeordnet")
                self.d_customer_note.configure(text="Kein bekannter Rechnungsempfänger. Kunden auswählen oder Firmenname und Kundennummer eintragen.")
        if load_fields or not self._fields_focused():
            self._loading = True
            try:
                if self.var_company.get() != res.company:
                    self.var_company.set(res.company)
                if self.var_number.get() != res.number:
                    self.var_number.set(res.number)
                email = item.overrides.email or (res.email if res.email_source == resolver.SOURCE_CUSTOMER else "")
                if not res.emails and self.var_email.get() != email:
                    self.var_email.set(email)
            finally:
                self._loading = False
        sources = []
        if res.company:
            sources.append(f"Firmenname: {SOURCE_TEXT.get(res.company_source, res.company_source)}")
        if res.number:
            sources.append(f"Kundennummer: {SOURCE_TEXT.get(res.number_source, res.number_source)}")
        self.d_value_source.configure(text=" · ".join(sources))
        for field, code in ((self.field_company, "company_missing"), (self.field_number, "number_missing")):
            field.set_error(any(issue.code == code for issue in res.issues))
        offer = app.batch_offer_emails(item.id)
        if res.customer is not None and offer:
            single = len(offer) == 1
            app.notify(
                "batch_mail_info",
                "info",
                f"{', '.join(offer)} → „{res.customer.label}“. PDF Tool erkennt den Kunden dann in der nächsten Excel-Liste wieder.",
                title="Diese E-Mail künftig diesem Kunden zuordnen?" if single else "Diese E-Mail-Adressen künftig diesem Kunden zuordnen?",
                actions=(("Zuordnung merken", lambda: app.batch_remember_emails(item.id)), ("Nicht zuordnen", lambda: app.batch_decline_emails(item.id))),
                status=False,
                animate=False,
            )
        else:
            app.hide_notice("batch_mail_info")

    def _refresh_output(self, item, res) -> None:
        app = self.app
        names = app.batch_template_names()
        values = [TEMPLATE_AUTO, TEMPLATE_NONE, *names]
        if self.d_template.values() != values:
            self.d_template.set_values(values, keep=False)
        chosen = item.overrides.template
        self.d_template.set(TEMPLATE_AUTO if chosen is None else (TEMPLATE_NONE if chosen == "" else chosen))
        if res is None:
            return
        if res.template:
            self.d_template_note.configure(text=f"Verwendet: Vorlage „{res.template}“ ({SOURCE_TEXT.get(res.template_source, res.template_source)}) · Kopf- und Fußzeile: {res.header_source}")
        else:
            self.d_template_note.configure(text=f"Keine Vorlage – es gilt die »Darstellung« · Kopf- und Fußzeile: {res.header_source}")
        logo_name, logo_full = path_caption(res.logo, "Kein Logo")
        self.d_logo.set_value(f"{logo_name}  ·  {SOURCE_TEXT.get(res.logo_source, res.logo_source)}" if res.logo else logo_name, logo_full)
        self.btn_logo_reset.set_enabled(item.overrides.logo is not None)
        folder = res.folder or "Kein Zielordner"
        self.d_target.set_value(f"{Path(folder).name or folder}  ·  {SOURCE_TEXT.get(res.folder_source, res.folder_source)}" if res.folder else folder, res.folder)
        self.btn_target_reset.set_enabled(item.overrides.target_dir is not None)
        if item.status in CREATED and item.output:
            self.d_output.configure(text=f"Erstellt: {item.output}")
        elif res.fields is not None or res.number:
            try:
                from engine import dateiname_fuer

                layout_name = (res.fields or {}).get("dateiname") or app.var_name.get()
                name = dateiname_fuer(layout_name, res.number or "…", res.company)
                self.d_output.configure(text=f"Wird gespeichert als »{name}« in {res.folder or '–'}")
            except (KeyError, ValueError, IndexError):
                self.d_output.configure(text="")
        else:
            self.d_output.configure(text="")

    def _fields_focused(self) -> bool:
        try:
            focus = self.app.focus_get()
        except (tk.TclError, KeyError):
            return False
        return focus in (self.field_company.entry, self.field_number.entry, self.d_mail_field.entry)

    # Eingaben ----------------------------------------------------------------------------------------------------
    def _schedule_edit(self) -> None:
        if self._loading or self.item_id is None:
            return
        if self._edit_job is not None:
            try:
                self.app.after_cancel(self._edit_job)
            except tk.TclError:
                pass
        self._edit_job = self.app.after(EDIT_DELAY, self._flush_edit)

    def _flush_edit(self) -> None:
        if self._edit_job is not None:
            try:
                self.app.after_cancel(self._edit_job)
            except tk.TclError:
                pass
            self._edit_job = None
        item = self.current()
        if item is None or self._loading:
            return
        values = {}
        inherited = self.app.batch_inherited(item.id)
        for key, var in (("company", self.var_company), ("number", self.var_number)):
            value = var.get().strip()
            values[key] = None if value == inherited.get(key, "") else value
        email = self.var_email.get().strip()
        if not (item.analysis is not None and item.analysis.emails):
            values["email"] = None if email == inherited.get("email", "") else email
        self.app.batch_edit(item.id, **values)

    def _mail_picked(self, mail: str) -> None:
        if self.item_id and mail:
            self.app.batch_edit(self.item_id, email=mail)

    def _template_picked(self, label: str) -> None:
        if not self.item_id:
            return
        value = None if label == TEMPLATE_AUTO else ("" if label == TEMPLATE_NONE else label)
        self.app.batch_apply_template(value, [self.item_id])

    def _batch_template_picked(self, label: str) -> None:
        self.app.batch_update_settings(template="" if label == TEMPLATE_NONE else label)

    def _conflict_picked(self, label: str) -> None:
        mode = next((mode for mode, text in CONFLICT_LABELS.items() if text == label), ConflictMode.NUMBER)
        self.app.batch_update_settings(conflict=mode)

    def pick_logo(self) -> None:
        item = self.current()
        if item is None:
            return
        path = filedialog.askopenfilename(parent=self.app, title="Logo für diesen Eintrag", initialdir=self.app._initial_dir("logo", item.overrides.logo or ""), filetypes=[("Bilder", "*.png *.jpg *.jpeg *.webp"), ("Alle Dateien", "*.*")])
        if path:
            self.app._remember_dir("logo", path)
            self.app.batch_edit(item.id, logo=path)

    def pick_target(self) -> None:
        item = self.current()
        if item is None:
            return
        path = filedialog.askdirectory(parent=self.app, title="Zielordner für diesen Eintrag", initialdir=self.app._initial_dir("ziel", item.overrides.target_dir or self.app.batch_settings.target_dir))
        if path:
            self.app.batch_edit(item.id, target_dir=path)

    def open_pdf(self) -> None:
        item = self.current()
        if item is not None and item.output:
            self.app.open_file(item.output, "batch_detail_info")

    def open_folder(self) -> None:
        item = self.current()
        if item is not None and item.output:
            self.app.open_folder_of(item.output, "batch_detail_info")

    def remove_current(self) -> None:
        item = self.current()
        if item is None:
            return
        self.show_list()
        self.app.batch_remove([item.id])

    # Massenaktionen ---------------------------------------------------------------------------------------------------
    def _toggle_all(self) -> None:
        visible = self.app.batch_visible()
        self.app.batch_select_all(not (visible and all(item.selected for item in visible)))

    def apply_template(self) -> None:
        selected = self.app.batch_selected()
        if not selected:
            return
        choice = ask_template(self.app, self.app.batch_template_names(), len(selected))
        if choice is False:
            return
        count = self.app.batch_apply_template(choice)
        label = "automatisch (Kundenakte bzw. Stapel)" if choice is None else ("keine Vorlage" if choice == "" else f"„{choice}“")
        self.app.notify("batch_info", "success", f"Vorlage {label} für {count} {'Eintrag' if count == 1 else 'Einträge'} gesetzt.", auto_hide=6000)

    def flush(self) -> None:
        self._flush_edit()


class ResultPanel(RoundedFrame):
    """Ergebnis des letzten Durchlaufs: »Stapel abgeschlossen« mit Anzahlen und Aktionen.

    Wie eine InfoBar, aber die Aktionen brechen bei wenig Platz in neue Zeilen um.
    """

    def __init__(self, master, app: "App") -> None:
        self.holder = Collapsible(master)
        # Neutrale Fläche – die Stufe (Erfolg bzw. Hinweis) zeigt das Symbol.
        super().__init__(self.holder.content, fill="card_secondary", stroke="card_stroke", radius=4)
        self.app = app
        self.pack(fill="x")
        inner = frame(self)
        inner.pack(fill="x", padx=px(14), pady=px(10))
        top = frame(inner)
        top.pack(fill="x")
        self.icon = StatusLine(top)
        self.icon.pack(fill="x")
        self.message = Text(inner, "", style="body", wrap=True, width=1)
        self.message.pack(anchor="w", fill="x", padx=(px(30), 0))
        self.buttons = FlowRow(inner, gap=8, row_gap=8)
        self.buttons.pack(fill="x", padx=(px(30), 0), pady=(px(8), 0))
        self.btn_folder = Button(self.buttons, "Ausgabeordner öffnen", app.batch_open_output, icon=icons.FOLDER_OPEN)
        self.buttons.add(self.btn_folder)
        self.btn_errors = Button(self.buttons, "Fehler anzeigen", app.batch_show_errors, icon=icons.WARNING)
        self.buttons.add(self.btn_errors)
        self.btn_new = Button(self.buttons, "Neuer Stapel", app.batch_new, icon=icons.REFRESH)
        self.buttons.add(self.btn_new)
        self.title = ""
        self.severity = ""
        self.lift_corners()

    def show(self, summary, message: str, has_output: bool, has_errors: bool) -> None:
        severity = "warning" if (summary.failed or summary.aborted) else "success"
        title = "Stapel abgebrochen" if summary.aborted else "Stapel abgeschlossen"
        self.title, self.severity = title, severity
        self.icon.set("caution" if severity == "warning" else "success", title)
        self.message.configure(text=message)
        self.buttons.set_visible(self.btn_folder, has_output)
        self.buttons.set_visible(self.btn_errors, has_errors)
        if not self.holder.expanded:
            self.holder.expand(animate=False)

    def hide(self) -> None:
        if self.holder.expanded:
            self.holder.collapse(animate=False)

    def visible(self) -> bool:
        return self.holder.expanded

    def text(self) -> str:
        return self.message.cget("text")


def ask_template(parent, names: list[str], count: int):
    """Vorlage für mehrere Einträge wählen. Rückgabe: Name, ``""`` (keine), ``None`` (automatisch) oder False."""
    options = [TEMPLATE_AUTO, TEMPLATE_NONE, *names]
    state = {"value": names[0] if names else TEMPLATE_AUTO}

    def build(holder) -> None:
        combo = ComboBox(holder, options, command=lambda value: state.update(value=value), width=320)
        combo.set(state["value"])
        combo.pack(fill="x")
        Text(holder, "»Automatisch«: bevorzugte Vorlage der Kundenakte, sonst die Standardvorlage des Stapels. Eine hier gewählte Vorlage hat Vorrang vor beiden.", style="caption", color="text2", wrap=True).pack(anchor="w", fill="x", pady=(px(10), 0))

    title = "Vorlage anwenden"
    message = f"Vorlage für {count} ausgewählte {'Eintrag' if count == 1 else 'Einträge'}:"
    dialog = dialogs.ContentDialog(parent, title, message, primary="Anwenden", close="Abbrechen", build=build, icon=ICON_FILE, width=460)
    if dialog.show() != dialogs.PRIMARY:
        return False
    value = state["value"]
    return None if value == TEMPLATE_AUTO else ("" if value == TEMPLATE_NONE else value)


def build(app: "App", host) -> Page:
    ui = app.ui
    page = Page(host, TITLE, SUBTITLE)
    ui.selector_batch = SelectorBar(page.content, VIEWS, "batch", lambda key: app.nav.navigate(key))
    page.add_section(ui.selector_batch, fill="none", anchor="w", pady=(0, px(16)))
    view = BatchPage(app, page)
    app.batch_page = view
    ui.batch_view = view
    ui.batch_page_frame = page
    view.refresh()
    return page
