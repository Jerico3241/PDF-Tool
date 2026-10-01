"""Werkzeug »Vertragsübersichten«: verbindet die Controller des Werkzeugs miteinander und mit dem
AppController (Tastenkürzel, Drag & Drop, Hilfe, Speichern, Beenden)."""

from __future__ import annotations

from pathlib import Path

from tools.contract_overview.history.models import ContractRecord
from tools.registry import CONTRACTS

from .batch import HINT as BATCH_HINT
from .batch import BatchController
from .comparison import ComparisonController
from .customers import CustomerController
from .overview import HINT, HINT_PLAIN, ContractOverviewController
from .preview import PreviewController

HELP_STEPS = (
    "Die Excel-Datei wählen (Strg+O) oder in das Fenster ziehen – sie wird sofort geprüft.",
    "Ist der Rechnungsempfänger als Kunde bekannt, bietet PDF Tool die Kundenakte an: »Übernehmen«.",
    "Sonst Firmenname und Kundennummer eintragen oder »Bekannten Kunden auswählen« (Strg+F).",
    "Optional Logo, Zielordner sowie Kopf- und Fußzeile in der Ansicht »Darstellung« setzen; die »Vorschau« zeigt das Ergebnis.",
    "Auf »PDF erstellen« klicken oder Strg+Enter drücken.",
)
HELP_NOTES = (
    "Kundenakten entstehen nur bewusst: »Als Kundenakte speichern« – auf Wunsch mit »Zuordnung merken« für die E-Mail-Adresse.",
    "Kundenakten verwalten, bearbeiten, zusammenführen oder löschen: Ansicht »Kunden«. Alle Daten bleiben lokal auf diesem PC.",
    "Stehen mehrere Rechnungsempfänger in der Excel, bitte einen auswählen.",
    "Viele Excel-Listen auf einmal erstellen: Ansicht »Stapel«.",
    "Zyklus-Regeln und Vorlagen stehen in der Ansicht »Darstellung«. Hott-KI wird standardmäßig jährlich ausgegeben.",
    "Hotline-Zeilen werden als Supportvertrag ausgegeben. Nur Netto, kein Brutto.",
)
HELP_STEPS_PLAIN = (
    "Die Excel-Datei wählen (Strg+O) oder in das Fenster ziehen – sie wird sofort geprüft.",
    "Firmenname, Kundennummer und Rechnungsempfänger eintragen (bzw. aus der Excel übernehmen).",
    "Optional Logo, Zielordner sowie Kopf- und Fußzeile in der Ansicht »Darstellung« setzen; die »Vorschau« zeigt das Ergebnis.",
    "Auf »PDF erstellen« klicken oder Strg+Enter drücken.",
)
HELP_NOTES_PLAIN = (
    "Stehen mehrere Rechnungsempfänger in der Excel, bitte einen auswählen.",
    "Viele Excel-Listen auf einmal erstellen: Ansicht »Stapel«.",
    "Zyklus-Regeln und Vorlagen stehen in der Ansicht »Darstellung«. Hott-KI wird standardmäßig jährlich ausgegeben.",
    "Hotline-Zeilen werden als Supportvertrag ausgegeben. Nur Netto, kein Brutto.",
    "Bekannte Kunden wiedererkennen und ihre Angaben übernehmen: »Einstellungen« → »Vertragsübersichten« → »Kundenakte verwenden«. Alle Daten bleiben lokal auf diesem PC.",
)
VIEWS = (
    ("create", "Übersicht erstellen"),
    ("batch", "Stapel"),
    ("layout", "Darstellung"),
    ("preview", "Vorschau"),
    ("comparison", "Vergleich"),
    ("customers", "Kunden"),
)


class ContractsTool:
    """Controller von »Vertragsübersichten« und ihre Verbindungen."""

    key = CONTRACTS.key

    def __init__(self, app, cfg: dict) -> None:
        self.app = app
        self.customers = CustomerController(app, self, cfg, app)
        self.overview = ContractOverviewController(app, self, cfg, app)
        self.preview = PreviewController(app, self, app)
        self.comparison = ComparisonController(app, self, app)
        self.batch = BatchController(app, self, cfg, app)
        for controller in (self.customers, self.preview, self.comparison, self.batch):
            controller.attach(self.overview)
        app.register_tool(self.key, self)

    def start(self) -> None:
        """Nach dem Einrichten aller Controller (vor dem Laden von QML)."""
        self.overview.start()
        self.customers.start()
        self.batch.start()

    # Verbindungen zwischen den Controllern ---------------------------------------------------------
    def preview_dirty(self) -> None:
        self.preview.mark_dirty()

    def refresh_comparison(self) -> None:
        self.comparison.refresh()

    def batch_mark_stale(self) -> None:
        self.batch.mark_stale()

    def batch_customers_changed(self) -> None:
        self.batch.customers_changed()

    def history_after_export(self, customer_id: str | None, label: str, records: tuple[ContractRecord, ...], excel: str, pdf: Path) -> None:
        self.comparison.after_export(customer_id, label, records, excel, pdf)

    def merge_history(self, target_id: str, source_id: str) -> None:
        self.comparison.merge_history(target_id, source_id)

    def views(self) -> list[dict]:
        return [{"key": key, "label": label} for key, label in VIEWS]

    # ToolHooks (AppController) -------------------------------------------------------------------------
    def primary_action(self, page: str) -> None:
        if page == "batch":
            self.batch.start_run()
        else:
            self.overview.start_pdf()

    def open_action(self, page: str) -> None:
        if page == "batch":
            self.batch.pickFiles()
        else:
            self.overview.pick_excel()

    def find_action(self, page: str) -> None:
        if page == "batch":
            if self.batch.detailId:
                self.batch.choose_customer(self.batch.detailId)
        else:
            self.customers.find(page)

    def show_help(self, page: str) -> None:
        if page == "batch":
            self.batch.show_help()
        elif self.customers.enabled:
            self.app.show_steps("Kurzanleitung – Vertragsübersichten", HELP_STEPS, HELP_NOTES)
        else:
            self.app.show_steps("Kurzanleitung – Vertragsübersichten", HELP_STEPS_PLAIN, HELP_NOTES_PLAIN)

    def hint(self, page: str) -> str:
        if page == "batch":
            return BATCH_HINT
        return HINT if self.customers.enabled else HINT_PLAIN

    def accepts(self, files: list[str], page: str) -> bool:
        if page == "batch":
            return self.batch.accepts(files)
        return self.overview.accepts(files)

    def drag_enter(self, accepted: bool, page: str) -> None:
        if page == "batch":
            self.batch.drag_enter(accepted)
        else:
            self.overview.drag_enter(accepted)

    def drag_leave(self) -> None:
        self.batch.drag_leave()
        self.overview.drag_leave()

    def drop(self, files: list[str], page: str) -> None:
        if page == "batch":
            self.batch.drop(files)
        else:
            self.overview.drop(files)

    def page_prepare(self, page: str) -> None:
        if page == "preview":
            self.preview.page_prepare()

    def page_left(self, page: str) -> None:
        if page == "customers":
            self.customers.flush()
        elif page == "batch":
            self.batch.flush()
        elif page == "preview":
            self.preview.page_left()

    def config(self) -> dict:
        return {**self.overview.config(), **self.customers.config(), **self.batch.config()}

    def autosave(self) -> None:
        self.customers.refresh_line()

    def changed(self) -> None:
        self.preview.mark_dirty()
        self.batch.mark_stale()

    def confirm_close(self) -> bool:
        return self.batch.confirm_close()

    def running_work(self) -> str:
        if self.batch.running_now:
            return "Stapel"
        return "PDF-Erstellung" if self.overview.busy else ""

    def close(self) -> None:
        # Kundenakten werden nie automatisch angelegt – nur eine offene Eingabe in »Kunden« sichern.
        self.customers.flush()
        self.batch.close()
        self.preview.close()
