"""Vertragsübersichten – Ansicht »Vorlagen« (in QML: ``Templates``).

Liste und Detail wie in »Kunden«: Vorlagen suchen, ansehen, anwenden, umbenennen, duplizieren,
als Standard festlegen und löschen. Bearbeitet wird eine Vorlage nicht in einem zweiten Editor,
sondern in der »Darstellung«: Vorlage laden → ändern → »Vorlage aktualisieren«.

Gespeichert wird über ``appstate.State.templates`` (``TemplateStore``); Verweise der Kundenakten
und des Stapels behandelt das Werkzeug (``ContractsTool.delete_template``/``rename_template``).
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Property, QObject, Signal, Slot

from appstate import DEFAULT_FOOTER
from tools.contract_overview.templates.models import Template, clean_name

from .. import dialogs as dialog_service
from ..base import Observable, prop
from ..models import KeyedListModel

EMPTY_TITLE = "Noch keine Vorlage gespeichert"
EMPTY_TEXT = (
    "Eine Vorlage hält die vollständige Darstellung einer Vertragsübersicht fest: Seitenformat, Logo, "
    "Titel, Dateiname, Kopf- und Fußzeile mit Formatierung, Zyklus-Regeln und Regelwerk. "
    "Einmal einrichten – danach mit einem Klick wiederverwenden."
)
HINT_EDIT = "Bearbeitet wird eine Vorlage in der »Darstellung«: Vorlage laden, ändern und »Vorlage aktualisieren«."


def first_line(text: str, limit: int = 80) -> str:
    line = next((part.strip() for part in str(text or "").splitlines() if part.strip()), "")
    return line if len(line) <= limit else line[: limit - 1] + "…"


class TemplatesController(Observable):
    """Vorlagen verwalten (Liste ↔ Detail)."""

    searchChanged, search = prop(str, "search", "")
    detailIdChanged, detailId = prop(str, "detailId", "")
    totalChanged, total = prop(int, "total", 0)
    countTextChanged, countText = prop(str, "countText", "")
    problemsTextChanged, problemsText = prop(str, "problemsText", "")
    # Detail
    detailNameChanged, detailName = prop(str, "detailName", "")
    detailDescriptionChanged, detailDescription = prop(str, "detailDescription", "")
    detailFactsChanged, detailFacts = prop(list, "detailFacts", [])
    detailUsesChanged, detailUses = prop(list, "detailUses", [])
    detailDefaultChanged, detailDefault = prop(bool, "detailDefault", False)
    detailLoadedChanged, detailLoaded = prop(bool, "detailLoaded", False)
    detailModifiedChanged, detailModified = prop(bool, "detailModified", False)
    detailCaptionChanged, detailCaption = prop(str, "detailCaption", "")
    focusRequested = Signal(str)  # QML: »search« = Suchfeld der Liste

    def __init__(self, app, tool, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.app = app
        self.tool = tool
        self.state = app.state
        self.model = KeyedListModel(("name", "description", "standard", "loaded", "modified", "updated"), key="id", parent=self)
        self.observe("search", lambda _v: self.app.timers.later("templates:search", 150, self.refresh_list))
        self.renames = 0

    def attach(self, overview) -> None:
        self.c = overview
        for name in ("vorlageId", "templateModified", "defaultTemplate"):
            overview.observe(name, lambda _v: self.app.timers.soon("templates:refresh", self.refresh))

    @property
    def store(self):
        return self.state.templates

    # Liste ------------------------------------------------------------------------------------------------
    def refresh(self) -> None:
        self.refresh_list()
        if self.detailId:
            self.refresh_detail()

    def refresh_list(self) -> None:
        store = self.store
        templates = store.templates() if store is not None else []
        query = self.search.strip().casefold()
        if query:
            templates = [t for t in templates if query in t.name.casefold() or query in t.meta.description.casefold()]
        loaded, modified, default = self.c.vorlageId, self.c.templateModified, self.c.defaultTemplate
        self.model.set_items(
            [
                {
                    "id": t.id,
                    "name": t.name,
                    "description": first_line(t.meta.description) or self._summary(t),
                    "standard": t.id == default,
                    "loaded": t.id == loaded,
                    "modified": t.id == loaded and modified,
                    "updated": _date(t.meta.updated_at),
                }
                for t in templates
            ]
        )
        total = len(store) if store is not None else 0
        self.total = total
        if query:
            self.countText = f"{len(templates)} von {total} Vorlagen" if templates else f"Keine Vorlage passt zu »{self.search.strip()}«."
        else:
            self.countText = "" if total == 0 else (f"{total} Vorlage" if total == 1 else f"{total} Vorlagen")
        problems = store.problems if store is not None else []
        if problems:
            newer = sum(1 for problem in problems if problem.newer)
            text = f"{len(problems)} {'Vorlage konnte' if len(problems) == 1 else 'Vorlagen konnten'} nicht gelesen werden und {'wird' if len(problems) == 1 else 'werden'} nicht angezeigt (Einstellungen → Diagnose)."
            if newer:
                text += " Sie stammen aus einer neueren Version von PDF Tool." if newer == len(problems) else ""
            self.problemsText = text
        else:
            self.problemsText = ""

    @staticmethod
    def _summary(template: Template) -> str:
        parts = []
        if template.layout.format:
            parts.append("Querformat" if template.layout.format == "quer" else "Hochformat")
        if template.layout.titel:
            parts.append(template.layout.titel)
        if template.rules.rule_set_id:
            parts.append("mit Regelwerk")
        return " · ".join(parts)

    # Detail -------------------------------------------------------------------------------------------------
    @Slot(str)
    def showDetail(self, template_id: str) -> None:  # noqa: N802
        if self.store is None or self.store.get(template_id) is None:
            return
        self.detailId = template_id
        self.refresh_detail()

    @Slot()
    def showList(self) -> None:  # noqa: N802
        self.detailId = ""
        self.refresh_list()

    def current(self) -> Template | None:
        return self.store.get(self.detailId) if self.store is not None and self.detailId else None

    def refresh_detail(self) -> None:
        template = self.current()
        if template is None:
            self.detailId = ""
            return
        self.detailName = template.name
        self.detailDescription = template.meta.description
        self.detailDefault = template.id == self.c.defaultTemplate
        self.detailLoaded = template.id == self.c.vorlageId
        self.detailModified = self.detailLoaded and self.c.templateModified
        self.detailCaption = f"Gespeichert am {_date(template.meta.updated_at)}" if template.meta.updated_at else ""
        self.detailFacts = self._facts(template)
        self.detailUses = self._uses(template)

    def _facts(self, template: Template) -> list[dict]:
        layout = template.layout
        facts: list[tuple[str, str, str]] = []
        unset = ("nicht festgelegt – der aktuelle Wert bleibt", "muted")
        facts.append(("Seitenformat", *(("A4 Querformat" if layout.format == "quer" else "A4 Hochformat", "") if layout.format else unset)))
        if layout.logo:
            exists = Path(layout.logo).is_file()
            facts.append(("Logo", Path(layout.logo).name + ("" if exists else " – Datei nicht gefunden"), "" if exists else "caution"))
        else:
            facts.append(("Logo", *unset))
        facts.append(("Logo-Breite", *((f"{layout.logo_breite} mm", "") if layout.logo_breite else unset)))
        facts.append(("Titel", *((layout.titel, "") if layout.titel else unset)))
        facts.append(("Untertitel", *((layout.untertitel, "") if layout.untertitel else unset)))
        facts.append(("Dateiname", *((layout.dateiname, "") if layout.dateiname else unset)))
        header = first_line(template.header.text)
        facts.append(("Kopfzeile", header or "leer", "" if header else "muted"))
        footer = template.footer.text
        facts.append(("Fußzeile", "Standard-Fußzeile" if footer == DEFAULT_FOOTER else (first_line(footer) or "leer"), "" if footer.strip() else "muted"))
        cycles = template.rules.cycle_list()
        facts.append(("Zyklus-Regeln", ", ".join(f"{r['enthaelt']} → {r['zyklus']}" for r in cycles[:3]) + (f" und {len(cycles) - 3} weitere" if len(cycles) > 3 else "") if cycles else "keine", "" if cycles else "muted"))
        ref = template.rules.rule_set_id
        if ref is None:
            facts.append(("Regelwerk", "nicht festgelegt – das aktuelle bleibt", "muted"))
        elif ref == "":
            facts.append(("Regelwerk", "keines", "muted"))
        else:
            rule_set = self.state.rule_sets.get(ref) if self.state.rule_sets is not None else None
            facts.append(("Regelwerk", rule_set.name if rule_set is not None else "gelöscht – es gilt keines", "" if rule_set is not None else "caution"))
        return [{"label": label, "value": value, "tone": tone} for label, value, tone in facts]

    def _uses(self, template: Template) -> list[str]:
        uses = []
        if template.id == self.c.defaultTemplate:
            uses.append("Standardvorlage – wird für jede neue Übersicht geladen")
        if template.id == self.c.vorlageId:
            uses.append("In der Darstellung geladen" + (" (geändert)" if self.c.templateModified else ""))
        customers = len(self.tool.customers.template_refs(template.id, template.name))
        if customers:
            uses.append(f"Bevorzugte Vorlage von {customers} {'Kundenakte' if customers == 1 else 'Kundenakten'}")
        batch = self.tool.batch.template_refs(template.id, template.name)
        if batch:
            uses.append("Im Stapel verwendet")
        return uses

    # Aktionen ----------------------------------------------------------------------------------------------------
    @Slot(str)
    def apply(self, template_id: str) -> None:
        """Vorlage in die Darstellung laden (Hinweis mit »Zur Darstellung«)."""
        if self.store is None or self.store.get(template_id) is None:
            return
        self.c.applyTemplate(template_id)
        self.refresh()
        name = self.store.get(template_id).name
        self.app.notify("vorlagen_verwaltung", "success", f"Vorlage „{name}“ in die Darstellung geladen.", actions=(("Zur Darstellung", lambda: self.app.navigate("layout")),), auto_hide=6000)

    @Slot(str)
    def edit(self, template_id: str) -> None:
        """Vorlage laden und in der Darstellung bearbeiten."""
        if self.store is None or self.store.get(template_id) is None:
            return
        self.c.applyTemplate(template_id)
        self.app.navigate("layout")

    def ask_name(self, title: str, label: str, value: str, primary: str) -> str | None:
        answer, result = self.app.dialogs.ask(
            "text_input",
            title,
            "",
            primary=primary,
            close="Abbrechen",
            data={"label": label, "value": value, "placeholder": "z. B. Standard Energie"},
            width=460,
        )
        if answer != dialog_service.PRIMARY:
            return None
        return clean_name(result.get("value", ""))

    @Slot(str)
    def rename(self, template_id: str) -> None:
        template = self.store.get(template_id) if self.store is not None else None
        if template is None:
            return
        name = self.ask_name("Vorlage umbenennen", "Neuer Name", template.name, "Umbenennen")
        if name is None or name == template.name:
            return
        if not name or self.store.name_taken(name, except_id=template.id):
            self.app.notify("vorlagen_verwaltung", "warning", "Bitte einen Namen eintragen, den noch keine andere Vorlage hat.")
            return
        renamed = self.tool.rename_template(template.id, name)
        if renamed is None:
            self.app.notify("vorlagen_verwaltung", "error", self.store.last_error or "Die Vorlage konnte nicht umbenannt werden.")
            return
        self.renames += 1
        self.refresh()
        self.app.notify("vorlagen_verwaltung", "success", f"Vorlage umbenannt in „{renamed.name}“.", auto_hide=5000)

    @Slot(str)
    def duplicate(self, template_id: str) -> None:
        copy = self.store.duplicate(template_id) if self.store is not None else None
        if copy is None:
            self.app.notify("vorlagen_verwaltung", "error", (self.store.last_error if self.store else "") or "Die Vorlage konnte nicht dupliziert werden.")
            return
        self.c.reload_vorlagen()
        self.tool.templates_changed()
        self.showDetail(copy.id)
        self.app.notify("vorlagen_verwaltung", "success", f"Kopie „{copy.name}“ angelegt.", auto_hide=5000)

    @Slot(str)
    def remove(self, template_id: str) -> None:
        if self.tool.delete_template(template_id, area="vorlagen_verwaltung"):
            self.showList()

    @Slot(str, bool)
    def setDefault(self, template_id: str, value: bool) -> None:  # noqa: N802
        self.c.setDefaultTemplate(template_id if value else "")
        self.refresh()
        if value and self.current() is not None:
            self.app.notify("vorlagen_verwaltung", "success", f"„{self.current().name}“ ist jetzt die Standardvorlage – sie wird für jede neue Übersicht geladen.", auto_hide=6000)

    @Slot(str, str)
    def setDescription(self, template_id: str, text: str) -> None:  # noqa: N802
        """Beschreibung speichern (gesammelt nach kurzer Pause)."""
        self._pending_description = (template_id, text)
        self.app.timers.later("templates:description", 600, self._save_description)

    def _save_description(self) -> None:
        pending = getattr(self, "_pending_description", None)
        self._pending_description = None
        if pending is None or self.store is None:
            return
        template_id, text = pending
        template = self.store.get(template_id)
        if template is None or template.meta.description == text.strip():
            return
        if self.store.describe(template_id, text) is None:
            self.app.notify("vorlagen_verwaltung", "error", self.store.last_error)
        self.refresh_list()

    def flush(self) -> None:
        if getattr(self, "_pending_description", None):
            self.app.timers.cancel("templates:description")
            self._save_description()

    @Slot()
    def createFromCurrent(self) -> None:  # noqa: N802
        """Aktuelle Darstellung als neue Vorlage speichern (Name per Dialog)."""
        name = self.ask_name("Aktuelle Darstellung als Vorlage speichern", "Name der Vorlage", "", "Speichern")
        if name is None:
            return
        if self.c.saveAsTemplate(name):
            self.showDetail(self.c.vorlageId)

    def focus_search(self) -> None:
        """Strg+F: zur Liste und ins Suchfeld."""
        if self.detailId:
            self.showList()
        self.focusRequested.emit("search")

    # Für QML ---------------------------------------------------------------------------------------------------------
    _constant = Signal()

    def _model(self) -> QObject:
        return self.model

    def _texts(self) -> dict:
        return {"emptyTitle": EMPTY_TITLE, "emptyText": EMPTY_TEXT, "editHint": HINT_EDIT}

    listModel = Property(QObject, _model, notify=_constant)
    texts = Property("QVariantMap", _texts, notify=_constant)


def _date(value: str) -> str:
    from datetime import datetime

    try:
        return datetime.fromisoformat(value).astimezone().strftime("%d.%m.%Y, %H:%M")
    except (TypeError, ValueError):
        return ""
