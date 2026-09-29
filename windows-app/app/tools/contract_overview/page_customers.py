"""Vertragsübersichten – Ansicht »Kunden«: Kundenakten suchen, ansehen, bearbeiten, zusammenführen.

Die Seite gehört zum Werkzeug »Vertragsübersichten« (kein globales Kundenmanagement).
Änderungen in der Detailansicht werden sofort bzw. kurz nach der Eingabe gespeichert –
wie überall in der App. Die Arbeitskopie in »Übersicht erstellen« bleibt davon unberührt.
"""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog
from typing import TYPE_CHECKING

from appstate import ICON_FILE, desktop_dir
from ui import dialogs, icons
from ui.components import FactList, FileRow, SelectorBar, SettingsCard, field_label, path_caption
from ui.context import ctx
from ui.inputs import ComboBox, TextArea, TextField
from ui.navigation import Page
from ui.theme import px
from ui.widgets import Button, Card, Divider, FlowRow, Icon, IconButton, InfoBar, RoundedFrame, Text, ToggleSwitch, frame

from .customer_widgets import MAX_ROWS, CustomerList, ask_email_conflict, choose_customer, format_when
from .customers.matching import is_valid_email, normalize_email
from .customers.models import TextBlock
from .customers.repository import ORDER_COMPANY, ORDER_NUMBER, ORDER_RECENT, ORDERS, EmailConflict
from .page_create import TITLE, VIEWS

if TYPE_CHECKING:
    from vertragdesk import App

SORT_LABELS = {ORDER_RECENT: "Zuletzt verwendet", ORDER_COMPANY: "Firma A–Z", ORDER_NUMBER: "Kundennummer"}
PRIVACY = "Kundendaten und E-Mail-Zuordnungen werden ausschließlich lokal auf diesem PC gespeichert."
EMPTY_TITLE = "Noch keine Kunden gespeichert."
EMPTY_TEXT = "PDF Tool kann bekannte Rechnungsempfänger später automatisch wiedererkennen. Kundenakten entstehen, wenn Sie Kundendaten bewusst speichern – nach dem Erstellen einer Übersicht oder mit »Als Kundenakte speichern«."
NO_TEMPLATE = "Keine Vorlage"
SEARCH_DELAY = 200
SAVE_DELAY = 600
REASONS = {"number": "gleiche Kundennummer", "company": "gleicher Firmenname", "email": "gleiche E-Mail"}


def _first_line(text: str, limit: int = 80) -> str:
    line = next((part.strip() for part in text.splitlines() if part.strip()), "")
    return line if len(line) <= limit else line[: limit - 1] + "…"


def _show_buttons(buttons, visible: bool) -> None:
    """Schaltflächen einer Dateizeile zeigen oder ausblenden (Reihenfolge von rechts)."""
    for index, button in enumerate(buttons):
        if visible and not button.winfo_manager():
            button.pack(side="right", padx=(0, px(4)) if index else 0)
        elif not visible and button.winfo_manager():
            button.pack_forget()


class CustomerPage:
    """Liste und Detailansicht der Kundenakten."""

    def __init__(self, app: "App", page: Page) -> None:
        self.app = app
        self.page = page
        self.customer_id: str | None = None
        self._loading = False
        self._search_job = None
        self._save_job = None
        self.var_search = tk.StringVar(app, "")
        self.var_company = tk.StringVar(app, "")
        self.var_number = tk.StringVar(app, "")
        self.var_email = tk.StringVar(app, "")
        self.var_template_auto = tk.BooleanVar(app, False)
        self._build_list()
        self._build_detail()
        self.var_search.trace_add("write", lambda *_a: self._schedule_search())
        for var in (self.var_company, self.var_number):
            var.trace_add("write", lambda *_a: self._schedule_save())
        self.show_list()

    # Aufbau: Liste ------------------------------------------------------------------------
    def _build_list(self) -> None:
        app, content = self.app, self.page.content
        self.list_view = frame(content)
        tools = FlowRow(self.list_view, gap=8, row_gap=8)
        tools.pack(fill="x")
        search_box = frame(tools)
        if ctx().icons_available:
            Icon(search_box, icons.SEARCH, color="text2").pack(side="left", padx=(0, px(8)))
        self.field_search = TextField(search_box, self.var_search, placeholder="Firma, Kundennummer oder E-Mail suchen", width=300)
        self.field_search.pack(side="left")
        tools.add(search_box)
        sort_box = frame(tools)
        Text(sort_box, "Sortierung", style="body").pack(side="left", padx=(px(8), px(8)))
        self.sort_combo = ComboBox(sort_box, [SORT_LABELS[o] for o in ORDERS], command=self._sort_picked, width=170, tooltip="Reihenfolge der Kundenliste")
        self.sort_combo.set(SORT_LABELS.get(app.customer_order, SORT_LABELS[ORDER_RECENT]))
        self.sort_combo.pack(side="left")
        tools.add(sort_box)
        tools.add(Button(tools, "Neue Kundenakte", self.new_customer, icon=icons.ADD_FRIEND, tooltip="Kundenakte manuell anlegen"))

        note = frame(self.list_view)
        note.pack(fill="x", pady=(px(12), 0))
        if ctx().icons_available:
            Icon(note, icons.SHIELD, color="text2").pack(side="left", anchor="n", padx=(0, px(8)), pady=(px(1), 0))
        Text(note, PRIVACY, style="caption", color="text2", wrap=True).pack(side="left", fill="x", expand=True)
        app.ui.kunden_info = InfoBar(self.list_view)
        app.ui.kunden_info.pack(fill="x", pady=(px(8), 0))

        self.list_card = Card(self.list_view, padding=8)
        self.list_card.pack(fill="x", pady=(px(12), 0))
        self.listing = CustomerList(self.list_card.body, on_open=self.show_detail)
        self.listing.pack(fill="x")
        self.count = Text(self.list_view, "", style="caption", color="text2")
        self.count.pack(anchor="w", pady=(px(6), 0))

        self.empty = RoundedFrame(self.list_view, fill="card", stroke="card_stroke")
        inner = frame(self.empty)
        inner.pack(fill="x", padx=px(24), pady=px(28))
        if ctx().icons_available:
            Icon(inner, icons.PEOPLE, color="text2", size="icon_large").pack(anchor="w")
        Text(inner, EMPTY_TITLE, style="body_strong").pack(anchor="w", pady=(px(10), px(4)))
        Text(inner, EMPTY_TEXT, style="body", color="text2", wrap=True).pack(anchor="w", fill="x")
        Button(inner, "Zur Vertragsübersicht", lambda: app.nav.navigate("create"), icon=icons.DOCUMENT, kind="accent").pack(anchor="w", pady=(px(14), 0))

        self.auto_card = SettingsCard(self.list_view, icons.SYNC, "Bekannte Kunden automatisch übernehmen", "Erkennt PDF Tool nach der Excel-Prüfung genau einen bekannten Kunden und sind noch keine Kundendaten eingetragen, werden sie ohne Nachfrage übernommen (rückgängig machbar). Standard: aus.")
        self.auto_card.pack(fill="x", pady=(px(16), 0))
        ToggleSwitch(self.auto_card.control, app.var_auto_customer, command=app.persist).pack()

    # Aufbau: Detail ------------------------------------------------------------------------
    def _build_detail(self) -> None:
        app = self.app
        self.detail_view = frame(self.page.content)
        top = frame(self.detail_view)
        top.pack(fill="x")
        self.btn_back = Button(top, "Alle Kunden", self.show_list, icon=icons.BACK, kind="subtle", tooltip="Zurück zur Kundenliste")
        self.btn_back.pack(side="left")
        self.title = Text(self.detail_view, "", style="subtitle", wrap=True)
        self.title.pack(anchor="w", fill="x", pady=(px(12), 0))
        self.caption = Text(self.detail_view, "", style="caption", color="text2", wrap=True)
        self.caption.pack(anchor="w", fill="x", pady=(px(2), 0))
        app.ui.kunde_detail_info = InfoBar(self.detail_view)
        app.ui.kunde_detail_info.pack(fill="x", pady=(px(8), 0))

        # Stammdaten
        card = Card(self.detail_view, "Stammdaten", icons.CONTACT)
        card.pack(fill="x", pady=(px(12), 0))
        body = card.body
        field_label(body, "Firmenname", first=True)
        self.field_company = TextField(body, self.var_company, placeholder="z. B. Muster GmbH")
        self.field_company.pack(fill="x")
        field_label(body, "Kundennummer")
        self.field_number = TextField(body, self.var_number, placeholder="z. B. 10042")
        self.field_number.pack(fill="x")
        field_label(body, "Notiz (optional)")
        self.note = TextArea(body, lines=3, on_change=self._schedule_save)
        self.note.pack(fill="x")

        # Rechnungsempfänger
        card = Card(self.detail_view, "Rechnungsempfänger", icons.MAIL, "Adressen, an denen PDF Tool diesen Kunden in einer Excel-Liste wiedererkennt.")
        card.pack(fill="x", pady=(px(12), 0))
        self.mail_rows = frame(card.body)
        self.mail_rows.pack(fill="x")
        add = frame(card.body)
        add.pack(fill="x", pady=(px(10), 0))
        self.field_email = TextField(add, self.var_email, placeholder="weitere E-Mail-Adresse", width=260, on_submit=self.add_email)
        self.field_email.pack(side="left", fill="x", expand=True)
        Button(add, "E-Mail hinzufügen", self.add_email, icon=icons.ADD).pack(side="left", padx=(px(8), 0))
        app.ui.kunde_mail_info = InfoBar(card.body)
        app.ui.kunde_mail_info.pack(fill="x", pady=(px(8), 0))

        # Einstellungen
        card = Card(self.detail_view, "Einstellungen für Vertragsübersichten", icons.SETTINGS, "Werden beim Übernehmen des Kunden verwendet – fehlt eine Datei, bleibt der aktuelle Wert.")
        card.pack(fill="x", pady=(px(12), 0))
        body = card.body
        self.row_logo = FileRow(body, icons.PICTURE, "Bevorzugtes Logo")
        self.row_logo.pack(fill="x")
        Button(self.row_logo.buttons, "Durchsuchen", self.pick_logo, icon=icons.OPEN_FILE).pack(side="right")
        IconButton(self.row_logo.buttons, icons.CLEAR, lambda: self._update(logo=""), tooltip="Kein bevorzugtes Logo").pack(side="right", padx=(0, px(4)))
        Divider(body).pack(fill="x", pady=px(10))
        self.row_target = FileRow(body, icons.FOLDER, "Bevorzugter Zielordner")
        self.row_target.pack(fill="x")
        Button(self.row_target.buttons, "Durchsuchen", self.pick_target, icon=icons.FOLDER_OPEN).pack(side="right")
        IconButton(self.row_target.buttons, icons.CLEAR, lambda: self._update(target_dir=""), tooltip="Kein bevorzugter Zielordner").pack(side="right", padx=(0, px(4)))
        Divider(body).pack(fill="x", pady=px(10))
        field_label(body, "Bevorzugte Vorlage", first=True)
        row = frame(body)
        row.pack(fill="x")
        self.template_combo = ComboBox(row, command=self._template_picked, placeholder=NO_TEMPLATE, width=220, tooltip="Vorlage aus »Darstellung«")
        self.template_combo.pack(side="left")
        auto = frame(row)
        auto.pack(side="left", padx=(px(16), 0))
        ToggleSwitch(auto, self.var_template_auto, command=lambda: self._update(template_auto=bool(self.var_template_auto.get())), show_text=False).pack(side="left")
        Text(auto, "Vorlage automatisch verwenden", style="body").pack(side="left", padx=(px(8), 0))

        # Dokumentdarstellung
        card = Card(self.detail_view, "Dokumentdarstellung", icons.DOCUMENT, "Eigene Kopf- und Fußzeile dieses Kunden (mit Formatierung). Ohne eigene Fußzeile bleibt die gültige – nie eine leere.")
        card.pack(fill="x", pady=(px(12), 0))
        self.texts = FactList(card.body, label_width=110)
        self.texts.pack(fill="x")
        actions = FlowRow(card.body, gap=8, row_gap=8)
        actions.pack(fill="x", pady=(px(10), 0))
        actions.add(Button(actions, "Aktuelle Kopf- und Fußzeile übernehmen", self.take_texts, icon=icons.SAVE, tooltip="Kopf- und Fußzeile aus »Darstellung« in dieser Kundenakte speichern"))
        actions.add(Button(actions, "Eigene entfernen", lambda: self._update(header=None, footer=None, message="Die Kundenakte verwendet keine eigene Kopf- und Fußzeile mehr."), icon=icons.CLEAR))

        # Letzte Aktivität
        card = Card(self.detail_view, "Letzte Aktivität", icons.HISTORY)
        card.pack(fill="x", pady=(px(12), 0))
        body = card.body
        self.row_excel = FileRow(body, icons.BULLETED_LIST, "Letzte Excel-Liste")
        self.row_excel.pack(fill="x")
        self.btn_excel_use = Button(self.row_excel.buttons, "Als Quelle verwenden", self.use_last_excel, icon=icons.OPEN_FILE, tooltip="Kunden übernehmen und diese Excel neu prüfen")
        self.btn_excel_use.pack(side="right")
        self.btn_excel_open = IconButton(self.row_excel.buttons, icons.OPEN_IN_WINDOW, self.open_last_excel, tooltip="Excel öffnen")
        self.btn_excel_open.pack(side="right", padx=(0, px(4)))
        Divider(body).pack(fill="x", pady=px(10))
        self.row_pdf = FileRow(body, icons.DOCUMENT, "Zuletzt erstellte Übersicht")
        self.row_pdf.pack(fill="x")
        self.btn_pdf_folder = Button(self.row_pdf.buttons, "Ordner öffnen", self.open_last_pdf_folder, icon=icons.FOLDER_OPEN)
        self.btn_pdf_folder.pack(side="right")
        self.btn_pdf_open = IconButton(self.row_pdf.buttons, icons.OPEN_IN_WINDOW, self.open_last_pdf, tooltip="PDF öffnen")
        self.btn_pdf_open.pack(side="right", padx=(0, px(4)))
        self.activity = FactList(body, label_width=150)
        self.activity.pack(fill="x", pady=(px(12), 0))

        # Aktionen
        actions = FlowRow(self.detail_view, gap=8, row_gap=8)
        actions.pack(fill="x", pady=(px(16), 0))
        actions.add(Button(actions, "In Vertragsübersicht übernehmen", self.apply, icon=icons.ACCEPT, kind="accent", tooltip="Kundendaten in »Übersicht erstellen« übernehmen"))
        actions.add(Button(actions, "Zusammenführen …", self.merge, icon=icons.SWITCH, tooltip="Eine doppelte Kundenakte in diese übernehmen"))
        actions.add(Button(actions, "Kundenakte löschen", self.delete, icon=icons.DELETE, tooltip="Löscht nur die Kundenakte – keine PDF- oder Excel-Dateien"))

    # Ansichten ---------------------------------------------------------------------------------
    def show_list(self) -> None:
        self._flush_save()
        self.customer_id = None
        self.detail_view.pack_forget()
        if not self.list_view.winfo_manager():
            self.list_view.pack(fill="x")
        self.refresh()
        try:
            self.page.scroll.to_top()
        except tk.TclError:
            pass

    def show_detail(self, customer_id: str) -> None:
        customer = self.app.customers.get(customer_id)
        if customer is None:
            self.show_list()
            return
        self._flush_save()
        self.customer_id = customer_id
        self.list_view.pack_forget()
        if not self.detail_view.winfo_manager():
            self.detail_view.pack(fill="x")
        self.app.hide_notice("kunde_detail_info")
        self.app.hide_notice("kunde_mail_info")
        self._fill_detail(reset_fields=True)
        try:
            self.page.scroll.to_top()
            self.field_company.focus()
        except tk.TclError:
            pass

    def focus_search(self) -> None:
        if self.customer_id is not None:
            self.show_list()
        self.field_search.focus()

    # Liste ------------------------------------------------------------------------------------------
    def _schedule_search(self) -> None:
        if self._search_job is not None:
            try:
                self.app.after_cancel(self._search_job)
            except tk.TclError:
                pass
        self._search_job = self.app.after(SEARCH_DELAY, self._search_now)

    def _search_now(self) -> None:
        self._search_job = None
        self.refresh_list()

    def _sort_picked(self, label: str) -> None:
        order = next((key for key, text in SORT_LABELS.items() if text == label), ORDER_RECENT)
        self.app.customer_order = order
        self.app.schedule_save()
        self.refresh_list()

    def refresh(self) -> None:
        """Nach Änderungen an den Kundenakten: Liste und ggf. Detailansicht aktualisieren."""
        if self.customer_id is not None:
            if self.app.customers.get(self.customer_id) is None:
                self.show_list()
                return
            self._fill_detail(reset_fields=False)
        self.refresh_list()

    def refresh_list(self) -> None:
        store = self.app.customers
        total = len(store)
        if total == 0:
            self.list_card.pack_forget()
            self.count.configure(text="")
            if not self.empty.winfo_manager():
                self.empty.pack(fill="x", pady=(px(12), 0), before=self.auto_card)
            self.listing.set_items([])
            return
        self.empty.pack_forget()
        if not self.list_card.winfo_manager():
            self.list_card.pack(fill="x", pady=(px(12), 0), before=self.count)
        query = self.var_search.get().strip()
        items = store.search(query, store.ordered(self.app.customer_order))
        self.listing.set_items(items)
        if not items:
            self.list_card.pack_forget()
            self.count.configure(text=f"Keine Kundenakte passt zu „{query}“.")
            return
        shown = min(len(items), MAX_ROWS)
        if query:
            text = f"{len(items)} von {total} Kundenakten"
        else:
            text = "1 Kundenakte" if total == 1 else f"{total} Kundenakten"
        if shown < len(items):
            text += f" – {shown} angezeigt, bitte Suche verfeinern"
        ambiguous = store.ambiguous_emails()
        if ambiguous:
            text += f" · {len(ambiguous)} E-Mail-Adresse(n) sind mehreren Kundenakten zugeordnet – bitte zusammenführen oder Zuordnung verschieben"
        self.count.configure(text=text)

    # Detail --------------------------------------------------------------------------------------------
    def current(self):
        return self.app.customers.get(self.customer_id)

    def _fill_detail(self, reset_fields: bool) -> None:
        customer = self.current()
        if customer is None:
            return
        self._loading = True
        try:
            if reset_fields:
                self.var_company.set(customer.company)
                self.var_number.set(customer.number)
                self.note.set(customer.note)
                self.var_email.set("")
            self.var_template_auto.set(customer.template_auto)
        finally:
            self._loading = False
        self.title.configure(text=customer.company or "Ohne Namen")
        active = self.app._active_customer_id == customer.id
        caption = f"Kundennummer {customer.number or '–'} · angelegt {format_when(customer.created_at)}"
        if customer.origin == "kundenhistorie":
            caption += " · aus der bisherigen Kundenhistorie übernommen"
        if active:
            caption += " · aktiv in »Übersicht erstellen«"
        self.caption.configure(text=caption)
        self._render_emails(customer)
        # Einstellungen
        if customer.logo:
            name, full = path_caption(customer.logo, "")
            self.row_logo.set_value(name + ("" if Path(customer.logo).is_file() else " – nicht gefunden"), full)
        else:
            self.row_logo.set_value("Keines – das aktuelle Logo wird verwendet")
        if customer.target_dir:
            available = Path(customer.target_dir).is_dir()
            self.row_target.set_value((Path(customer.target_dir).name or customer.target_dir) + ("" if available else " – nicht verfügbar"), customer.target_dir)
        else:
            self.row_target.set_value("Keiner – der aktuelle Zielordner wird verwendet")
        templates = [str(entry.get("name", "")) for entry in self.app.state.vorlagen]
        values = [NO_TEMPLATE] + templates
        if customer.template and customer.template not in templates:
            values.append(customer.template)
        self.template_combo.set_values(values, keep=False)
        self.template_combo.set(customer.template or NO_TEMPLATE)
        # Kopf- und Fußzeile
        texts = []
        if customer.header is None:
            texts.append(("Kopfzeile", "keine eigene – die gültige bleibt", "muted"))
        else:
            texts.append(("Kopfzeile", _first_line(customer.header.text) or "eigene, leer (keine Kopfzeile)", ""))
        if customer.footer is None:
            texts.append(("Fußzeile", "keine eigene – die gültige bleibt", "muted"))
        else:
            texts.append(("Fußzeile", _first_line(customer.footer.text), ""))
        self.texts.set(texts)
        # Aktivität
        excel_ok = bool(customer.last_excel) and Path(customer.last_excel).is_file()
        pdf_ok = bool(customer.last_pdf) and Path(customer.last_pdf).is_file()
        if customer.last_excel:
            name, full = path_caption(customer.last_excel, "")
            self.row_excel.set_value(name if excel_ok else f"{name} – nicht verfügbar", full)
        else:
            self.row_excel.set_value("Noch keine")
        if customer.last_pdf:
            name, full = path_caption(customer.last_pdf, "")
            self.row_pdf.set_value(name if pdf_ok else f"{name} – nicht verfügbar", full)
        else:
            self.row_pdf.set_value("Noch keine")
        # Aktionen nur, wenn die Datei noch vorhanden ist
        _show_buttons((self.btn_excel_use, self.btn_excel_open), excel_ok)
        _show_buttons((self.btn_pdf_folder, self.btn_pdf_open), pdf_ok)
        self.activity.set(
            [
                ("Zuletzt verwendet", format_when(customer.last_used_at, "noch nicht"), ""),
                ("Angelegt", format_when(customer.created_at), "muted"),
                ("Zuletzt geändert", format_when(customer.updated_at), "muted"),
            ]
        )
        self._show_duplicates(customer)

    def _render_emails(self, customer) -> None:
        for child in self.mail_rows.winfo_children():
            child.destroy()
        if not customer.emails:
            Text(self.mail_rows, "Keine E-Mail zugeordnet. Die Kundenakte kann weiterhin manuell ausgewählt werden.", style="body", color="text2", wrap=True).pack(anchor="w", fill="x")
            return
        ambiguous = self.app.customers.ambiguous_emails()
        for index, email in enumerate(customer.emails):
            row = RoundedFrame(self.mail_rows, fill="card_secondary", stroke=None, radius=4)
            row.pack(fill="x", pady=(0 if index == 0 else px(4), 0))
            inner = frame(row)
            inner.pack(fill="x", padx=(px(12), px(4)), pady=px(2))
            Text(inner, email, style="body").pack(side="left")
            if index == 0:
                Text(inner, "primär", style="caption", color="accent_text").pack(side="left", padx=(px(10), 0))
            if email in ambiguous:
                Text(inner, "auch anderen Kundenakten zugeordnet", style="caption", color="caution").pack(side="left", padx=(px(10), 0))
            IconButton(inner, icons.DELETE, lambda e=email: self.remove_email(e), tooltip=f"{email} entfernen").pack(side="right")
            if index > 0:
                IconButton(inner, icons.CHEVRON_UP, lambda e=email: self.make_primary(e), tooltip="Als primäre Adresse festlegen").pack(side="right")
            row.lift_corners()

    def _show_duplicates(self, customer) -> None:
        hints = self.app.customers.duplicates(company=customer.company, number=customer.number, emails=customer.emails, exclude=customer.id)
        if not hints:
            self.app.hide_notice("kunde_detail_info")
            return
        other, reasons = hints[0]
        text = f"„{other.label}“ ({', '.join(REASONS[r] for r in reasons)})"
        if len(hints) > 1:
            text += f" und {len(hints) - 1} weitere"
        self.app.notify(
            "kunde_detail_info",
            "warning",
            f"Mögliche Doppelung: {text}. Gleiche Firma oder Nummer bedeutet nicht zwingend denselben Kunden.",
            title="Hinweis",
            actions=(("Zusammenführen …", self.merge),),
            status=False,
        )

    # Speichern ------------------------------------------------------------------------------------------
    def _schedule_save(self) -> None:
        if self._loading or self.customer_id is None:
            return
        if self._save_job is not None:
            try:
                self.app.after_cancel(self._save_job)
            except tk.TclError:
                pass
        self._save_job = self.app.after(SAVE_DELAY, self._save_fields)

    def flush(self) -> None:
        """Offene Eingaben der Detailansicht sofort speichern (z. B. beim Beenden)."""
        self._flush_save()

    def _flush_save(self) -> None:
        if self._save_job is not None:
            try:
                self.app.after_cancel(self._save_job)
            except tk.TclError:
                pass
            self._save_job = None
            self._save_fields()

    def _save_fields(self) -> None:
        self._save_job = None
        customer = self.current()
        if customer is None:
            return
        company, number, note = self.var_company.get().strip(), self.var_number.get().strip(), self.note.get()
        if not company and not number:
            self.field_company.set_error(True)
            self.app.notify("kunde_detail_info", "warning", "Bitte Firmenname oder Kundennummer eintragen – leere Angaben werden nicht gespeichert.", status=False)
            return
        self.field_company.set_error(False)
        if (company, number, note) == (customer.company, customer.number, customer.note):
            return
        self.app.customers.update(customer.id, company=company, number=number, note=note)
        self.app.customers_changed(detail=False)
        self.title.configure(text=company or "Ohne Namen")
        self._show_duplicates(customer)

    def _update(self, message: str = "", **fields) -> None:
        customer = self.current()
        if customer is None:
            return
        self.app.customers.update(customer.id, **fields)
        self.app.customers_changed()
        if message:
            self.app.notify("kunde_detail_info", "success", message, auto_hide=5000, status=False)

    # Aktionen --------------------------------------------------------------------------------------------
    def add_email(self) -> None:
        customer = self.current()
        if customer is None:
            return
        raw = self.var_email.get()
        email = normalize_email(raw)
        if not email:
            self.field_email.set_error(True)
            self.app.notify("kunde_mail_info", "warning", "Bitte eine E-Mail-Adresse eintragen.", status=False)
            return
        if not is_valid_email(email):
            self.field_email.set_error(True)
            self.app.notify("kunde_mail_info", "warning", f"„{raw.strip()}“ ist keine gültige E-Mail-Adresse.", status=False)
            return
        self.field_email.set_error(False)
        if email in customer.emails:
            self.app.notify("kunde_mail_info", "info", f"{email} ist dieser Kundenakte bereits zugeordnet.", auto_hide=5000, status=False)
            return
        try:
            self.app.customers.add_email(customer.id, email)
        except EmailConflict as conflict:
            answer = ask_email_conflict(self.app, email, conflict.owners, customer.label)
            if answer != "move":
                self.app.notify("kunde_mail_info", "info", f"{email} bleibt bei {', '.join(o.label for o in conflict.owners)}.", auto_hide=6000, status=False)
                return
            self.app.customers.add_email(customer.id, email, move=True)
        self.var_email.set("")
        self.app.customers_changed()
        self.app.notify("kunde_mail_info", "success", f"{email} wird künftig als Rechnungsempfänger dieses Kunden erkannt.", auto_hide=6000, status=False)

    def remove_email(self, email: str) -> None:
        customer = self.current()
        if customer is None or not self.app.customers.remove_email(customer.id, email):
            return
        self.app.customers_changed()
        self.app.notify("kunde_mail_info", "info", f"{email} entfernt.", actions=(("Rückgängig", lambda: self._restore_email(customer.id, email)),), auto_hide=8000, status=False)

    def _restore_email(self, customer_id: str, email: str) -> None:
        try:
            self.app.customers.add_email(customer_id, email)
        except (EmailConflict, KeyError, ValueError):
            return
        self.app.customers_changed()
        self.app.hide_notice("kunde_mail_info")

    def make_primary(self, email: str) -> None:
        customer = self.current()
        if customer is not None:
            self.app.customers.make_primary(customer.id, email)
            self.app.customers_changed()

    def pick_logo(self) -> None:
        customer = self.current()
        if customer is None:
            return
        start = str(Path(customer.logo).parent) if customer.logo else self.app._initial_dir("logo", self.app.var_logo.get().strip())
        path = filedialog.askopenfilename(parent=self.app, title="Bevorzugtes Logo wählen", initialdir=start, filetypes=[("Bilder", "*.png *.jpg *.jpeg *.webp"), ("Alle Dateien", "*.*")])
        if path:
            self._update(logo=path, message="Bevorzugtes Logo gespeichert.")

    def pick_target(self) -> None:
        customer = self.current()
        if customer is None:
            return
        start = customer.target_dir if customer.target_dir and Path(customer.target_dir).is_dir() else str(desktop_dir())
        path = filedialog.askdirectory(parent=self.app, title="Bevorzugter Zielordner", initialdir=start)
        if path:
            self._update(target_dir=path, message="Bevorzugter Zielordner gespeichert.")

    def _template_picked(self, label: str) -> None:
        self._update(template="" if label == NO_TEMPLATE else label)

    def take_texts(self) -> None:
        kopf, fuss = self.app.header_rich(), self.app.footer_rich()
        footer = TextBlock(fuss.text, fuss.to_dict()) if fuss.text.strip() else None
        self._update(header=TextBlock(kopf.text, kopf.to_dict()), footer=footer, message="Kopf- und Fußzeile (mit Formatierung) in der Kundenakte gespeichert.")

    def apply(self) -> None:
        customer = self.current()
        if customer is None:
            return
        self._flush_save()
        self.app.apply_customer(customer.id)
        self.app.nav.navigate("create")

    def use_last_excel(self) -> None:
        customer = self.current()
        if customer is None or not customer.last_excel or not Path(customer.last_excel).is_file():
            return
        self._flush_save()
        self.app.apply_customer(customer.id)
        self.app.nav.navigate("create")
        self.app.use_excel(customer.last_excel)  # neu prüfen – nie eine alte Analyse verwenden

    def open_last_excel(self) -> None:
        customer = self.current()
        if customer is not None and customer.last_excel:
            self.app.open_file(customer.last_excel, "kunde_detail_info")

    def open_last_pdf(self) -> None:
        customer = self.current()
        if customer is not None and customer.last_pdf:
            self.app.open_file(customer.last_pdf, "kunde_detail_info")

    def open_last_pdf_folder(self) -> None:
        customer = self.current()
        if customer is not None and customer.last_pdf:
            self.app.open_folder_of(customer.last_pdf, "kunde_detail_info")

    def merge(self) -> None:
        customer = self.current()
        if customer is None:
            return
        self._flush_save()
        duplicates = [other.id for other, _reasons in self.app.customers.duplicates(company=customer.company, number=customer.number, emails=customer.emails, exclude=customer.id)]
        others = duplicates + [c.id for c in self.app.customers.ordered(ORDER_RECENT) if c.id != customer.id and c.id not in duplicates]
        if not others:
            self.app.notify("kunde_detail_info", "info", "Es gibt keine weitere Kundenakte zum Zusammenführen.", auto_hide=5000, status=False)
            return
        chosen = choose_customer(
            self.app,
            self.app.customers,
            candidates=others,
            title="Kundenakten zusammenführen",
            message=f"Welche Kundenakte soll in „{customer.label}“ aufgehen? E-Mail-Adressen werden vereint, neuere Einstellungen bevorzugt. PDF- und Excel-Dateien bleiben unberührt.",
        )
        other = self.app.customers.get(chosen)
        if other is None:
            return
        if not dialogs.confirm(
            self.app,
            "Kundenakten zusammenführen?",
            f"„{other.label}“ wird in „{customer.label}“ übernommen und danach entfernt. Firmenname und Kundennummer von „{customer.label}“ bleiben.",
            "Zusammenführen",
            danger=False,
            icon=ICON_FILE,
        ):
            return
        self.app.merge_customers(customer.id, other.id)

    def delete(self) -> None:
        customer = self.current()
        if customer is None:
            return
        if not dialogs.confirm(
            self.app,
            "Kundenakte löschen?",
            f"„{customer.label}“ und die E-Mail-Zuordnungen werden entfernt. Erstellte PDF-Dateien und Excel-Listen bleiben unverändert erhalten.",
            "Löschen",
            icon=ICON_FILE,
        ):
            return
        self.app.delete_customer(customer.id)

    def new_customer(self) -> None:
        self.app.create_customer_manually()


def build(app: "App", host) -> Page:
    ui = app.ui
    page = Page(host, TITLE, "Kundenakten: bekannte Kunden verwalten und in Übersichten wiederverwenden.")
    ui.selector_customers = SelectorBar(page.content, VIEWS, "customers", lambda key: app.nav.navigate(key))
    page.add_section(ui.selector_customers, fill="none", anchor="w", pady=(0, px(16)))
    app.customer_page = CustomerPage(app, page)
    ui.customer_page = app.customer_page
    return page
