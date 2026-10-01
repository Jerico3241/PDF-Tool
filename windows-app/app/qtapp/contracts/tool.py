"""Werkzeug »Vertragsübersichten«: verbindet die Controller des Werkzeugs miteinander und mit dem
AppController (Tastenkürzel, Drag & Drop, Hilfe, Speichern, Beenden)."""

from __future__ import annotations

from pathlib import Path

from appstate import VERSION
from storage import data_root
from tools.contract_overview.history.models import ContractRecord
from tools.contract_overview.rules.repository import FOLDER as RULE_SET_FOLDER
from tools.contract_overview.rules.repository import RuleSetStore
from tools.contract_overview.templates import migration as template_migration
from tools.contract_overview.templates.repository import FOLDER as TEMPLATE_FOLDER
from tools.contract_overview.templates.repository import TemplateStore
from tools.registry import CONTRACTS

from .batch import HINT as BATCH_HINT
from .batch import BatchController
from .comparison import ComparisonController
from .customers import CustomerController
from .overview import HINT, HINT_PLAIN, ContractOverviewController
from .preview import PreviewController
from .rules import RulesController
from .templates import TemplatesController

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
    "Zyklus-Regeln und die geladene Vorlage stehen in der Ansicht »Darstellung«; Vorlagen verwalten: »Vorlagen«. Hott-KI wird standardmäßig jährlich ausgegeben.",
    "Werte der Übersicht nach eigenen Regeln anpassen (WENN … DANN …): Ansicht »Regeln«. Die Excel bleibt dabei unverändert.",
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
    "Zyklus-Regeln und die geladene Vorlage stehen in der Ansicht »Darstellung«; Vorlagen verwalten: »Vorlagen«. Hott-KI wird standardmäßig jährlich ausgegeben.",
    "Werte der Übersicht nach eigenen Regeln anpassen (WENN … DANN …): Ansicht »Regeln«. Die Excel bleibt dabei unverändert.",
    "Hotline-Zeilen werden als Supportvertrag ausgegeben. Nur Netto, kein Brutto.",
    "Bekannte Kunden wiedererkennen und ihre Angaben übernehmen: »Einstellungen« → »Vertragsübersichten« → »Kundenakte verwenden«. Alle Daten bleiben lokal auf diesem PC.",
)
VIEWS = (
    ("create", "Übersicht erstellen"),
    ("batch", "Stapel"),
    ("layout", "Darstellung"),
    ("preview", "Vorschau"),
    ("templates", "Vorlagen"),
    ("rules", "Regeln"),
    ("comparison", "Vergleich"),
    ("customers", "Kunden"),
)


class ContractsTool:
    """Controller von »Vertragsübersichten« und ihre Verbindungen."""

    key = CONTRACTS.key

    def __init__(self, app, cfg: dict) -> None:
        self.app = app
        # Vorlagen 2.0 und Regelwerke: je Datensatz eine Datei im Datenordner. Vorlagen bis 2.7
        # werden beim ersten Start einmalig übernommen (die alte Liste bleibt unverändert stehen).
        root = data_root()
        templates = TemplateStore(root / TEMPLATE_FOLDER).load()
        self.template_migration: tuple[int, list[str]] = (0, [])
        if template_migration.needs_migration(cfg):
            self.template_migration = template_migration.migrate(templates, cfg, VERSION)
        app.state.attach_stores(templates, RuleSetStore(root / RULE_SET_FOLDER).load())
        self.customers = CustomerController(app, self, cfg, app)
        self.overview = ContractOverviewController(app, self, cfg, app)
        self.preview = PreviewController(app, self, app)
        self.comparison = ComparisonController(app, self, app)
        self.batch = BatchController(app, self, cfg, app)
        self.templates = TemplatesController(app, self, app)
        self.rules = RulesController(app, self, app)
        for controller in (self.customers, self.preview, self.comparison, self.batch, self.templates, self.rules):
            controller.attach(self.overview)
        app.register_tool(self.key, self)

    def start(self) -> None:
        """Nach dem Einrichten aller Controller (vor dem Laden von QML)."""
        self.overview.start()
        self.customers.start()
        self.batch.start()
        self.templates.refresh_list()
        self.rules.start()
        if self.template_migration[0]:
            self.app.schedule_save()  # Markierung der Übernahme speichern

    # Verbindungen zwischen den Controllern ---------------------------------------------------------
    def preview_dirty(self) -> None:
        self.preview.mark_dirty()

    def refresh_comparison(self) -> None:
        """Nach der Excel-Prüfung, einem Kundenwechsel oder geänderten Regeln."""
        self.comparison.refresh()
        self.rules.analysis_changed()

    def batch_mark_stale(self) -> None:
        self.batch.mark_stale()

    def batch_customers_changed(self) -> None:
        self.batch.customers_changed()

    def templates_changed(self) -> None:
        """Vorlage gespeichert, umbenannt, gelöscht oder Standard geändert."""
        self.batch.templates_changed()
        self.customers.refresh()
        self.app.timers.soon("templates:refresh", self.templates.refresh)

    def rules_changed(self) -> None:
        """Regelwerk gewählt, bearbeitet, umbenannt oder gelöscht."""
        self.batch.mark_stale()
        self.rules.summary_soon()
        self.app.timers.soon("templates:refresh", self.templates.refresh)

    def rule_set_deleted(self, rule_set_id: str) -> None:
        """Gelöschtes Regelwerk: Verweise kontrolliert lösen – Vorlagen und »Darstellung« verwenden keines,
        Stapel-Einträge wieder »Automatisch«. Eine unverändert geladene Vorlage bleibt unverändert."""
        overview = self.overview
        clean = bool(overview.vorlageId) and not overview.templateModified
        if self.app.state.templates is not None:
            self.app.state.templates.detach_rule_set(rule_set_id)
        if overview.ruleSetId == rule_set_id:
            overview.setRuleSet("")
        self.batch.retarget_rule_set(rule_set_id)
        overview.reload_vorlagen()
        if clean and overview.template_entry() is not None:
            overview._mark_template(overview.vorlageId)  # Vorlage und Darstellung sind wieder gleich
        self.templates_changed()

    def delete_template(self, template_id: str, area: str = "vorlagen_info") -> bool:
        """Vorlage löschen (mit Rückfrage). Verweise der Kundenakten und des Stapels werden kontrolliert
        auf »keine Vorlage« bzw. »automatisch« gesetzt – nie bleibt ein Verweis ins Leere."""
        store = self.app.state.templates
        template = store.get(template_id) if store is not None else None
        if template is None:
            return False
        customers = len(self.customers.template_refs(template.id, template.name))
        batch = self.batch.template_refs(template.id, template.name)
        uses = []
        if template.id == self.overview.defaultTemplate:
            uses.append("ist die Standardvorlage")
        if customers:
            uses.append(f"wird von {customers} {'Kundenakte' if customers == 1 else 'Kundenakten'} verwendet")
        if batch:
            uses.append("wird im Stapel verwendet")
        message = f"Die Vorlage „{template.name}“ wird dauerhaft entfernt. Die aktuelle Darstellung bleibt unverändert."
        if uses:
            message += " Sie " + " und ".join(uses) + " – diese Stellen verwenden danach keine Vorlage mehr."
        if not self.app.dialogs.confirm("Vorlage löschen?", message, "Löschen"):
            return False
        if not store.delete(template.id):
            self.app.notify(area, "error", store.last_error or "Die Vorlage konnte nicht gelöscht werden.")
            return False
        self.customers.retarget_template(template.id, template.name, "")
        self.batch.retarget_template(template.id, template.name, None)
        self.overview.template_deleted(template.id, template.name)
        self.templates_changed()
        self.app.notify(area, "success", f"Vorlage „{template.name}“ gelöscht.", auto_hide=5000)
        return True

    def rename_template(self, template_id: str, name: str):
        """Vorlage umbenennen; Verweise per Name (aus 2.7) werden dabei auf die ID umgestellt."""
        store = self.app.state.templates
        template = store.get(template_id) if store is not None else None
        if template is None:
            return None
        self.customers.retarget_template(template.id, template.name, template.id)
        self.batch.retarget_template(template.id, template.name, template.id)
        renamed = store.rename(template.id, name)
        if renamed is not None:
            self.overview.reload_vorlagen()
            self.templates_changed()
        return renamed

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
        elif page == "templates":
            self.templates.focus_search()
        elif page == "rules":
            self.rules.focus_search()
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
        elif page == "templates":
            self.templates.flush()
        elif page == "rules":
            self.rules.flush()

    def config(self) -> dict:
        return {**self.overview.config(), **self.customers.config(), **self.batch.config()}

    def autosave(self) -> None:
        self.customers.refresh_line()

    def changed(self) -> None:
        self.preview.mark_dirty()
        self.batch.mark_stale()
        self.overview.template_state_soon()

    def confirm_close(self) -> bool:
        return self.batch.confirm_close()

    def running_work(self) -> str:
        if self.batch.running_now:
            return "Stapel"
        return "PDF-Erstellung" if self.overview.busy else ""

    def close(self) -> None:
        # Kundenakten werden nie automatisch angelegt – nur eine offene Eingabe in »Kunden« sichern.
        self.customers.flush()
        self.templates.flush()
        self.rules.flush()
        self.batch.close()
        self.preview.close()
