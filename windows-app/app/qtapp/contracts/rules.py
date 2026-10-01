"""Vertragsübersichten – Ansicht »Regeln« (in QML: ``Rules``).

Regelwerke verwalten (Liste ↔ Detail wie in »Kunden«) und ihre Regeln visuell bearbeiten: je Regel
eine Karte »WENN … DANN …«. Zum Bearbeiten ist immer genau eine Regel geöffnet; ihre Bedingungen
und Aktionen sind eigene Listen mit festen Schlüsseln – Eingaben behalten beim Tippen ihren Fokus,
nichts wird sichtbar neu aufgebaut.

Gespeichert wird automatisch (gesammelt nach einer kurzen Pause, spätestens beim Verlassen der
Ansicht und beim Beenden). Unvollständige Regeln bleiben gespeichert, werden aber nie ausgeführt –
die Karte nennt den Grund.

Testmodus und Vorschau: Mit der geprüften Excel aus »Übersicht erstellen« zeigt jede Regel, auf wie
viele Verträge sie zutrifft, und die Vorschau, was sich ändert (vorher → nachher, mit Konflikten).
Gerechnet wird im Hintergrund; ein veraltetes Ergebnis wird verworfen. Die Excel bleibt unberührt.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from itertools import count
from pathlib import Path

from PySide6.QtCore import Property, QObject, Signal, Slot

from tools.contract_overview.rules import evaluate
from tools.contract_overview.rules.models import (
    ACTION,
    ACTIONS,
    FIELD,
    FIELDS,
    MATCH_ALL,
    MATCH_ANY,
    OPERATORS,
    Action,
    Condition,
    FieldType,
    Rule,
    RuleSet,
    clean_name,
    new_id,
    new_rule,
    operator_def,
)

from .. import dialogs as dialog_service
from ..base import Observable, prop
from ..models import KeyedListModel

AREA = "regeln_verwaltung"
SAVE_DELAY = 500  # ms – Eingaben gesammelt speichern
TEST_DELAY = 250  # ms – Testmodus nach einer kurzen Pause neu rechnen
PREVIEW_LIMIT = 200  # so viele geänderte Verträge zeigt die Vorschau höchstens

EMPTY_TITLE = "Noch kein Regelwerk"
EMPTY_TEXT = (
    "Ein Regelwerk ändert Werte der Vertragsübersicht nach festen Regeln – etwa »WENN die Beschreibung "
    "„Energie“ enthält, DANN die Art auf „Energievertrag“ setzen«. Die Excel-Datei bleibt dabei immer unverändert."
)
NO_EXCEL = "Für Testmodus und Vorschau in »Übersicht erstellen« eine Excel-Datei wählen – sie wird dabei nur gelesen."
ORDER_HINT = "Die Regeln laufen von oben nach unten. Ändern zwei Regeln dasselbe Feld, gilt die spätere."
PLACEHOLDERS = {FieldType.TEXT: "Text", FieldType.NUMBER: "z. B. 100,00", FieldType.DATE: "TT.MM.JJJJ"}
MATCH_CHOICES = (
    {"key": MATCH_ALL, "label": "alle Bedingungen erfüllt sind"},
    {"key": MATCH_ANY, "label": "mindestens eine Bedingung erfüllt ist"},
)


def first_line(text: str, limit: int = 80) -> str:
    line = next((part.strip() for part in str(text or "").splitlines() if part.strip()), "")
    return line if len(line) <= limit else line[: limit - 1] + "…"


def contracts_text(number: int) -> str:
    return "1 Vertrag" if number == 1 else f"{number} Verträge"


def rules_text(number: int) -> str:
    return "Keine Regeln" if number == 0 else ("1 Regel" if number == 1 else f"{number} Regeln")


def _quote(text: str) -> str:
    return f"„{text}“" if str(text).strip() else "…"


def condition_text(condition: Condition) -> str:
    definition = FIELD.get(condition.field)
    op = operator_def(condition.field, condition.operator)
    if definition is None or op is None:
        return "ungültige Bedingung"
    if not op.needs_value:
        return f"{definition.label} {op.label}"
    return f"{definition.label} {op.label} {_quote(condition.value.strip())}"


def action_text(action: Action) -> str:
    target = FIELD.get(action.field)
    if target is None or action.kind not in ACTION:
        return "ungültige Aktion"
    label = target.label
    if action.kind == "set":
        return f"{label} auf {_quote(action.value.strip())} setzen"
    if action.kind == "replace":
        if not action.value:
            return f"in {label} {_quote(action.find.strip())} entfernen"
        return f"in {label} {_quote(action.find.strip())} durch {_quote(action.value)} ersetzen"
    if action.kind == "prefix":
        return f"{label}: {_quote(action.value)} voranstellen"
    if action.kind == "suffix":
        return f"{label}: {_quote(action.value)} anhängen"
    return f"{label} leeren"


def when_text(rule: Rule) -> str:
    if not rule.conditions:
        return "für alle Verträge"
    joiner = " und " if rule.match == MATCH_ALL else " oder "
    return joiner.join(condition_text(condition) for condition in rule.conditions)


def then_text(rule: Rule) -> str:
    return " · ".join(action_text(action) for action in rule.actions) if rule.actions else "keine Aktion"


def _contracts_key(vertraege) -> int:
    """Kurzer Schlüssel des Inhalts einer Vertragsliste (wurde die Excel neu geprüft?)."""
    return hash(tuple((v.zeile, v.nummer, v.bemerkung, str(v.netto), v.zyklus, v.zahlungsart, v.beginn_roh) for v in vertraege))


def _date(value: str) -> str:
    try:
        return datetime.fromisoformat(value).astimezone().strftime("%d.%m.%Y, %H:%M")
    except (TypeError, ValueError):
        return ""


class RulesController(Observable):
    """Regelwerke verwalten und ihre Regeln bearbeiten (Liste ↔ Detail)."""

    searchChanged, search = prop(str, "search", "")
    detailIdChanged, detailId = prop(str, "detailId", "")
    totalChanged, total = prop(int, "total", 0)
    countTextChanged, countText = prop(str, "countText", "")
    problemsTextChanged, problemsText = prop(str, "problemsText", "")
    # Detail
    detailNameChanged, detailName = prop(str, "detailName", "")
    detailDescriptionChanged, detailDescription = prop(str, "detailDescription", "")
    detailActiveChanged, detailActive = prop(bool, "detailActive", True)
    detailUsedChanged, detailUsed = prop(bool, "detailUsed", False)
    detailCaptionChanged, detailCaption = prop(str, "detailCaption", "")
    detailUsesChanged, detailUses = prop(list, "detailUses", [])
    ruleCountChanged, ruleCount = prop(int, "ruleCount", 0)
    # Geöffnete Regel
    editingRuleChanged, editingRule = prop(str, "editingRule", "")
    editNameChanged, editName = prop(str, "editName", "")
    editMatchChanged, editMatch = prop(str, "editMatch", MATCH_ALL)
    # Testmodus und Vorschau (geprüfte Excel aus »Übersicht erstellen«)
    testReadyChanged, testReady = prop(bool, "testReady", False)
    testBusyChanged, testBusy = prop(bool, "testBusy", False)
    testSourceChanged, testSource = prop(str, "testSource", "")
    testTitleChanged, testTitle = prop(str, "testTitle", "")
    testTextChanged, testText = prop(str, "testText", NO_EXCEL)
    previewMoreChanged, previewMore = prop(str, "previewMore", "")
    # Regelwerk der Übersicht (»Darstellung«, »Übersicht erstellen«): was es an der Excel ändert
    activeSummaryChanged, activeSummary = prop(str, "activeSummary", "")
    activeToneChanged, activeTone = prop(str, "activeTone", "info")

    revealRule = Signal(str)  # QML: diese Regelkarte in den sichtbaren Bereich holen
    focusRequested = Signal(str)  # QML: »search« = Suchfeld der Liste

    def __init__(self, app, tool, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.app = app
        self.tool = tool
        self.state = app.state
        self.model = KeyedListModel(("name", "description", "rules", "active", "used"), key="id", parent=self)
        self.ruleModel = KeyedListModel(("number", "name", "active", "whenText", "thenText", "problems", "hits", "first", "last"), key="id", parent=self)
        self.conditionModel = KeyedListModel(("field", "operator", "value", "needsValue", "operators", "placeholder", "problem"), key="key", parent=self)
        self.actionModel = KeyedListModel(("kind", "field", "value", "find", "needsValue", "needsFind", "placeholder", "problem"), key="key", parent=self)
        self.previewModel = KeyedListModel(("title", "lines"), key="key", parent=self)
        self._draft: RuleSet | None = None
        self._dirty = False
        self._keys = count(1)
        self._condition_keys: list[str] = []
        self._action_keys: list[str] = []
        self._removed: tuple[str, int, Rule] | None = None
        self._test_serial = 0
        self._test: evaluate.RulePreview | None = None
        self._summary_serial = 0
        self._summary_key: tuple | None = None
        self.saves = 0  # Tests, Diagnose
        self.observe("search", lambda _v: self.app.timers.later("rules:search", 150, self.refresh_list))

    def attach(self, overview) -> None:
        self.c = overview
        overview.observe("ruleSetId", lambda _v: self._overview_changed())

    def start(self) -> None:
        self.refresh_list()
        self.summary_soon()

    @property
    def store(self):
        return self.state.rule_sets

    # Liste ------------------------------------------------------------------------------------------------
    def refresh_list(self) -> None:
        store = self.store
        sets = store.rule_sets() if store is not None else []
        query = self.search.strip().casefold()
        if query:
            sets = [s for s in sets if query in s.name.casefold() or query in s.description.casefold()]
        used = self.c.ruleSetId
        self.model.set_items(
            [
                {
                    "id": s.id,
                    "name": s.name,
                    "description": first_line(s.description) or self._summary(s),
                    "rules": rules_text(len(s.rules)),
                    "active": s.active,
                    "used": s.id == used,
                }
                for s in sets
            ]
        )
        total = len(store) if store is not None else 0
        self.total = total
        if query:
            self.countText = f"{len(sets)} von {total} Regelwerken" if sets else f"Kein Regelwerk passt zu »{self.search.strip()}«."
        else:
            self.countText = "" if total == 0 else (f"{total} Regelwerk" if total == 1 else f"{total} Regelwerke")
        problems = store.problems if store is not None else []
        if problems:
            one = len(problems) == 1
            text = f"{len(problems)} {'Regelwerk konnte' if one else 'Regelwerke konnten'} nicht gelesen werden und {'wird' if one else 'werden'} nicht angezeigt (Einstellungen → Diagnose)."
            if all(problem.newer for problem in problems):
                text += " Sie stammen aus einer neueren Version von PDF Tool."
            self.problemsText = text
        else:
            self.problemsText = ""

    @staticmethod
    def _summary(rule_set: RuleSet) -> str:
        """Besonderheiten für die Liste (die Zahl der Regeln steht daneben)."""
        parts = []
        inactive = sum(1 for rule in rule_set.rules if not rule.active)
        if inactive:
            parts.append(f"{inactive} ausgeschaltet")
        incomplete = sum(1 for rule in rule_set.rules if rule.problems())
        if incomplete:
            parts.append(f"{incomplete} unvollständig")
        return " · ".join(parts)

    # Detail ------------------------------------------------------------------------------------------------
    @Slot(str)
    def showDetail(self, rule_set_id: str) -> None:  # noqa: N802
        self.flush()
        rule_set = self.store.get(rule_set_id) if self.store is not None else None
        if rule_set is None:
            return
        if rule_set_id != self.detailId:
            self._removed = None
            self._close_editor()
        self._draft = rule_set
        self.detailId = rule_set.id
        self.refresh_detail()
        self.refresh_rules()
        self.test_soon(0)

    @Slot()
    def showList(self) -> None:  # noqa: N802
        self.flush()
        self.detailId = ""
        self.refresh_list()

    def current(self) -> RuleSet | None:
        return self._draft if self.detailId else None

    def refresh_detail(self) -> None:
        rule_set = self._draft
        if rule_set is None:
            return
        self.detailName = rule_set.name
        if not self.app.timers.pending("rules:save") or self.detailDescription.strip() == rule_set.description:
            self.detailDescription = rule_set.description
        self.detailActive = rule_set.active
        self.detailUsed = rule_set.id == self.c.ruleSetId
        self.ruleCount = len(rule_set.rules)
        self.detailCaption = f"Gespeichert am {_date(rule_set.updated_at)}" if rule_set.updated_at else ""
        self.detailUses = self._uses(rule_set)

    def _uses(self, rule_set: RuleSet) -> list[str]:
        uses = []
        if rule_set.id == self.c.ruleSetId:
            uses.append("In der »Darstellung« gewählt – gilt für die nächste Übersicht")
        templates = self.state.templates.using_rule_set(rule_set.id) if self.state.templates is not None else []
        if templates:
            names = ", ".join(f"„{t.name}“" for t in templates[:3]) + (f" und {len(templates) - 3} weitere" if len(templates) > 3 else "")
            uses.append(f"Festgelegt in {'der Vorlage' if len(templates) == 1 else f'{len(templates)} Vorlagen:'} {names}")
        batch = self.tool.batch.rule_set_refs(rule_set.id)
        if batch:
            uses.append(f"Im Stapel für {batch} {'Eintrag' if batch == 1 else 'Einträge'} gewählt")
        return uses

    def refresh_rules(self) -> None:
        rules = self._draft.rules if self._draft is not None else ()
        self.ruleModel.set_items([self._rule_row(rule, index, len(rules)) for index, rule in enumerate(rules)])
        self.ruleCount = len(rules)

    def _rule_row(self, rule: Rule, index: int, total: int) -> dict:
        problems = rule.problems()
        return {
            "id": rule.id,
            "number": index + 1,
            "name": rule.name or f"Regel {index + 1}",
            "active": rule.active,
            "whenText": when_text(rule),
            "thenText": then_text(rule),
            "problems": ("Wird nicht ausgeführt – " + "; ".join(problems) + ".") if problems else "",
            "hits": self._hits_text(rule),
            "first": index == 0,
            "last": index == total - 1,
        }

    def _update_rule_row(self, rule: Rule) -> None:
        rules = self._draft.rules
        index = next((i for i, r in enumerate(rules) if r.id == rule.id), -1)
        if index >= 0:
            self.ruleModel.update_item(rule.id, **self._rule_row(rule, index, len(rules)))

    def _hits_text(self, rule: Rule) -> str:
        result = self._test
        if result is None or not result.total or rule.problems():
            return ""
        of = f"von {result.total} {'Vertrag' if result.total == 1 else 'Verträgen'}"
        if not rule.active:
            return f"Ausgeschaltet – träfe auf {result.probes.get(rule.id, 0)} {of} zu"
        hits = result.hits.get(rule.id, 0)
        text = f"Trifft auf {hits} {of} zu"
        changed = result.changed.get(rule.id, 0)
        if hits and changed < hits:
            text += f", ändert {changed}"
        return text

    # Speichern -----------------------------------------------------------------------------------------------
    def _set_draft(self, rule_set: RuleSet) -> None:
        self._draft = rule_set
        self._dirty = True
        self.app.timers.later("rules:save", SAVE_DELAY, self.save)
        self.test_soon()

    def save(self) -> bool:
        """Entwurf speichern (atomar); danach folgen Liste, Darstellung, Vorschau und Stapel."""
        self.app.timers.cancel("rules:save")
        if not self._dirty or self._draft is None or self.store is None:
            return True
        saved = self.store.update(self._draft)
        if saved is None:
            self.app.notify(AREA, "error", self.store.last_error or "Das Regelwerk konnte nicht gespeichert werden.")
            return False
        self._dirty = False
        self.saves += 1
        if self._draft.id == saved.id:
            self._draft = saved
        self.detailCaption = f"Gespeichert am {_date(saved.updated_at)}"
        self.after_change(saved.id)
        return True

    def after_change(self, rule_set_id: str = "") -> None:
        """Ein Regelwerk wurde gespeichert, umbenannt oder gelöscht."""
        self.refresh_list()
        self.c.reload_rule_sets()
        if rule_set_id and rule_set_id == self.c.ruleSetId:
            self.c.rule_set_changed()  # Vorschau, Vergleich, Stapel, Zusammenfassung
        else:
            self.tool.rules_changed()

    def flush(self) -> None:
        if self.app.timers.pending("rules:save") or self._dirty:
            self.save()

    # Regelwerk ----------------------------------------------------------------------------------------------
    def ask_name(self, title: str, value: str, primary: str) -> str | None:
        answer, result = self.app.dialogs.ask(
            "text_input",
            title,
            "",
            primary=primary,
            close="Abbrechen",
            data={"label": "Name des Regelwerks", "value": value, "placeholder": "z. B. Energieverträge"},
            width=460,
        )
        if answer != dialog_service.PRIMARY:
            return None
        return clean_name(result.get("value", ""))

    @Slot()
    def newRuleSet(self) -> None:  # noqa: N802
        """Neues Regelwerk (Name per Dialog) mit einer ersten, noch leeren Regel – gleich zum Bearbeiten geöffnet."""
        if self.store is None:
            return
        name = self.ask_name("Neues Regelwerk", self.store.unique_name("Neues Regelwerk"), "Anlegen")
        if name is None:
            return
        if not name or self.store.name_taken(name):
            self.app.notify(AREA, "warning", "Bitte einen Namen eintragen, den noch kein anderes Regelwerk hat.")
            return
        first = new_rule()
        created = self.store.create(name, rules=(first,))
        if created is None:
            self.app.notify(AREA, "error", self.store.last_error or "Das Regelwerk konnte nicht angelegt werden.")
            return
        self.after_change()
        self.showDetail(created.id)
        self.editRule(first.id)
        self.app.notify(AREA, "success", f"Regelwerk „{created.name}“ angelegt – jetzt die erste Regel ausfüllen.", auto_hide=6000)

    @Slot()
    def rename(self) -> None:
        rule_set = self.current()
        if rule_set is None:
            return
        name = self.ask_name("Regelwerk umbenennen", rule_set.name, "Umbenennen")
        if name is None or name == rule_set.name:
            return
        if not name or self.store.name_taken(name, except_id=rule_set.id):
            self.app.notify(AREA, "warning", "Bitte einen Namen eintragen, den noch kein anderes Regelwerk hat.")
            return
        self._set_draft(rule_set.with_(name=name))
        if self.save():
            self.refresh_detail()
            self.app.notify(AREA, "success", f"Regelwerk umbenannt in „{name}“.", auto_hide=5000)

    @Slot(str)
    def setDescription(self, text: str) -> None:  # noqa: N802
        rule_set = self.current()
        if rule_set is None or rule_set.description == text.strip():
            return
        self.detailDescription = text
        self._set_draft(rule_set.with_(description=text.strip()))

    @Slot(bool)
    def setActive(self, value: bool) -> None:  # noqa: N802
        """Regelwerk ein- oder ausschalten (ausgeschaltet ändert es nichts – auch nicht im Stapel)."""
        rule_set = self.current()
        if rule_set is None or rule_set.active == bool(value):
            return
        self._set_draft(rule_set.with_(active=bool(value)))
        self.detailActive = bool(value)
        self.save()

    @Slot()
    def duplicate(self) -> None:
        rule_set = self.current()
        if rule_set is None:
            return
        self.flush()
        copy = self.store.duplicate(rule_set.id)
        if copy is None:
            self.app.notify(AREA, "error", self.store.last_error or "Das Regelwerk konnte nicht dupliziert werden.")
            return
        self.after_change()
        self.showDetail(copy.id)
        self.app.notify(AREA, "success", f"Kopie „{copy.name}“ angelegt.", auto_hide=5000)

    @Slot()
    def remove(self) -> None:
        """Regelwerk löschen (mit Rückfrage). Verweise werden kontrolliert gelöst – nie still ersetzt."""
        rule_set = self.current()
        if rule_set is None:
            return
        uses = []
        used_here = rule_set.id == self.c.ruleSetId
        if used_here:
            uses.append("ist in der »Darstellung« gewählt")
        templates = self.state.templates.using_rule_set(rule_set.id) if self.state.templates is not None else []
        if templates:
            uses.append(f"ist in {'einer Vorlage' if len(templates) == 1 else f'{len(templates)} Vorlagen'} festgelegt")
        batch = self.tool.batch.rule_set_refs(rule_set.id)
        if batch:
            uses.append(f"ist im Stapel für {batch} {'Eintrag' if batch == 1 else 'Einträge'} gewählt")
        message = f"Das Regelwerk „{rule_set.name}“ mit {rules_text(len(rule_set.rules))} wird dauerhaft entfernt. Excel-Dateien und erstellte PDFs bleiben unverändert."
        if uses:
            message += " Es " + " und ".join(uses) + " – diese Stellen verwenden danach kein Regelwerk mehr (der Stapel: »Automatisch«)."
        if not self.app.dialogs.confirm("Regelwerk löschen?", message, "Löschen"):
            return
        self.app.timers.cancel("rules:save")
        self._dirty = False
        if not self.store.delete(rule_set.id):
            self.app.notify(AREA, "error", self.store.last_error or "Das Regelwerk konnte nicht gelöscht werden.")
            return
        self.tool.rule_set_deleted(rule_set.id)
        self._draft = None
        self._close_editor()
        self.detailId = ""
        self.after_change()
        self.app.notify(AREA, "success", f"Regelwerk „{rule_set.name}“ gelöscht.", auto_hide=5000)

    @Slot()
    def useInOverview(self) -> None:  # noqa: N802
        """Dieses Regelwerk für die Übersicht verwenden (»Darstellung«)."""
        rule_set = self.current()
        if rule_set is None:
            return
        self.flush()
        self.c.setRuleSet(rule_set.id)
        self.refresh_detail()
        self.app.notify(
            AREA,
            "success",
            f"Regelwerk „{rule_set.name}“ gilt jetzt für die Übersicht." + ("" if rule_set.active else " Es ist ausgeschaltet und ändert erst nach dem Einschalten etwas."),
            actions=(("Zur Darstellung", lambda: self.app.navigate("layout")),),
            auto_hide=6000,
        )

    @Slot()
    def stopUsing(self) -> None:  # noqa: N802
        if self.current() is not None and self.c.ruleSetId == self.current().id:
            self.c.setRuleSet("")
            self.refresh_detail()

    @Slot(str)
    def open(self, rule_set_id: str) -> None:
        """Regelwerk in der Ansicht »Regeln« zeigen (aus »Darstellung« oder »Übersicht erstellen«)."""
        if self.store is None or self.store.get(rule_set_id) is None:
            return
        self.showDetail(rule_set_id)
        self.app.navigate("rules")

    @Slot()
    def openActive(self) -> None:  # noqa: N802
        if self.c.ruleSetId:
            self.open(self.c.ruleSetId)
        else:
            self.showList()
            self.app.navigate("rules")

    # Regeln ----------------------------------------------------------------------------------------------------
    def _replace_rule(self, rule: Rule) -> None:
        rule_set = self._draft
        self._set_draft(rule_set.with_(rules=tuple(rule if r.id == rule.id else r for r in rule_set.rules)))
        self._update_rule_row(rule)

    @Slot()
    def addRule(self) -> None:  # noqa: N802
        rule_set = self.current()
        if rule_set is None:
            return
        rule = new_rule()
        self._set_draft(rule_set.with_(rules=rule_set.rules + (rule,)))
        self.refresh_rules()
        self.editRule(rule.id)
        self.revealRule.emit(rule.id)

    @Slot(str)
    def editRule(self, rule_id: str) -> None:  # noqa: N802
        """Regel zum Bearbeiten öffnen (eine erneute Wahl schließt sie wieder)."""
        rule = self._draft.rule(rule_id) if self._draft is not None else None
        if rule is None or rule_id == self.editingRule:
            self._close_editor()
            return
        self._condition_keys = [self._key() for _ in rule.conditions]
        self._action_keys = [self._key() for _ in rule.actions]
        self.editName = rule.name
        self.editMatch = rule.match
        self.conditionModel.set_items([self._condition_row(key, c) for key, c in zip(self._condition_keys, rule.conditions)])
        self.actionModel.set_items([self._action_row(key, a) for key, a in zip(self._action_keys, rule.actions)])
        self.editingRule = rule.id

    @Slot()
    def closeEditor(self) -> None:  # noqa: N802
        self._close_editor()

    def _close_editor(self) -> None:
        self.editingRule = ""

    def _key(self) -> str:
        return f"k{next(self._keys)}"

    def _editing(self) -> Rule | None:
        return self._draft.rule(self.editingRule) if self._draft is not None and self.editingRule else None

    @Slot(str, int)
    def moveRule(self, rule_id: str, delta: int) -> None:  # noqa: N802
        """Regel nach oben (−1) oder unten (+1) – die Reihenfolge bestimmt, welche Regel zuletzt gilt."""
        rule_set = self.current()
        if rule_set is None:
            return
        rules = list(rule_set.rules)
        index = next((i for i, r in enumerate(rules) if r.id == rule_id), -1)
        target = index + int(delta)
        if index < 0 or not 0 <= target < len(rules):
            return
        rules[index], rules[target] = rules[target], rules[index]
        self._set_draft(rule_set.with_(rules=tuple(rules)))
        self.refresh_rules()
        self.revealRule.emit(rule_id)

    @Slot(str)
    def duplicateRule(self, rule_id: str) -> None:  # noqa: N802
        rule_set = self.current()
        rule = rule_set.rule(rule_id) if rule_set is not None else None
        if rule is None:
            return
        rules = list(rule_set.rules)
        index = rules.index(rule)
        copy = replace(rule, id=new_id(), name=clean_name((rule.name or f"Regel {index + 1}") + " – Kopie"))
        rules.insert(index + 1, copy)
        self._set_draft(rule_set.with_(rules=tuple(rules)))
        self.refresh_rules()
        self.editRule(copy.id)
        self.revealRule.emit(copy.id)

    @Slot(str)
    def removeRule(self, rule_id: str) -> None:  # noqa: N802
        """Regel entfernen – mit »Rückgängig« im Hinweis."""
        rule_set = self.current()
        rule = rule_set.rule(rule_id) if rule_set is not None else None
        if rule is None:
            return
        index = rule_set.rules.index(rule)
        if self.editingRule == rule_id:
            self._close_editor()
        self._set_draft(rule_set.with_(rules=tuple(r for r in rule_set.rules if r.id != rule_id)))
        self._removed = (rule_set.id, index, rule)
        self.refresh_rules()
        self.refresh_detail()
        name = rule.name or f"Regel {index + 1}"
        self.app.notify(AREA, "info", f"„{name}“ entfernt.", actions=(("Rückgängig", self._undo_remove),), auto_hide=10000)

    def _undo_remove(self) -> None:
        removed, self._removed = self._removed, None
        rule_set = self.current()
        if removed is None or rule_set is None or removed[0] != rule_set.id or rule_set.rule(removed[2].id) is not None:
            return
        _ident, index, rule = removed
        rules = list(rule_set.rules)
        rules.insert(min(index, len(rules)), rule)
        self._set_draft(rule_set.with_(rules=tuple(rules)))
        self.refresh_rules()
        self.refresh_detail()
        self.app.hide_notice(AREA)
        self.revealRule.emit(rule.id)

    @Slot(str, bool)
    def setRuleActive(self, rule_id: str, value: bool) -> None:  # noqa: N802
        rule = self._draft.rule(rule_id) if self.current() is not None else None
        if rule is None or rule.active == bool(value):
            return
        self._replace_rule(replace(rule, active=bool(value)))

    @Slot(str)
    def setRuleName(self, text: str) -> None:  # noqa: N802
        rule = self._editing()
        if rule is None:
            return
        self.editName = text
        self._replace_rule(replace(rule, name=clean_name(text)))

    @Slot(str)
    def setMatch(self, value: str) -> None:  # noqa: N802
        rule = self._editing()
        if rule is None or value not in (MATCH_ALL, MATCH_ANY) or rule.match == value:
            return
        self.editMatch = value
        self._replace_rule(replace(rule, match=value))

    # Bedingungen der geöffneten Regel ------------------------------------------------------------------------------
    def _condition_row(self, key: str, condition: Condition) -> dict:
        definition = FIELD.get(condition.field)
        op = operator_def(condition.field, condition.operator)
        return {
            "key": key,
            "field": condition.field,
            "operator": condition.operator,
            "value": condition.value,
            "needsValue": op is None or op.needs_value,
            "operators": [{"key": o.key, "label": o.label} for o in OPERATORS[definition.type]] if definition else [],
            "placeholder": PLACEHOLDERS[definition.type] if definition else "",
            "problem": condition.problem(),
        }

    def _set_condition(self, key: str, change) -> None:
        rule = self._editing()
        if rule is None or key not in self._condition_keys:
            return
        index = self._condition_keys.index(key)
        conditions = list(rule.conditions)
        new = change(conditions[index])
        if new == conditions[index]:
            return
        conditions[index] = new
        self._replace_rule(replace(rule, conditions=tuple(conditions)))
        self.conditionModel.update_item(key, **self._condition_row(key, new))

    @Slot()
    def addCondition(self) -> None:  # noqa: N802
        rule = self._editing()
        if rule is None:
            return
        condition = Condition()
        self._condition_keys.append(self._key())
        self._replace_rule(replace(rule, conditions=rule.conditions + (condition,)))
        self.conditionModel.set_items([*self.conditionModel.items(), self._condition_row(self._condition_keys[-1], condition)])

    @Slot(str)
    def removeCondition(self, key: str) -> None:  # noqa: N802
        rule = self._editing()
        if rule is None or key not in self._condition_keys:
            return
        index = self._condition_keys.index(key)
        del self._condition_keys[index]
        self._replace_rule(replace(rule, conditions=tuple(c for i, c in enumerate(rule.conditions) if i != index)))
        self.conditionModel.set_items([item for item in self.conditionModel.items() if item["key"] != key])

    @Slot(str, str)
    def setConditionField(self, key: str, field: str) -> None:  # noqa: N802
        """Anderes Feld: passender Vergleich; der Wert bleibt nur bei gleichem Feldtyp."""
        if field not in FIELD:
            return

        def change(old: Condition) -> Condition:
            same = old.field in FIELD and FIELD[old.field].type is FIELD[field].type
            operator = old.operator if operator_def(field, old.operator) is not None else OPERATORS[FIELD[field].type][0].key
            return Condition(field, operator, old.value if same else "")

        self._set_condition(key, change)

    @Slot(str, str)
    def setConditionOperator(self, key: str, operator: str) -> None:  # noqa: N802
        self._set_condition(key, lambda old: Condition(old.field, operator, old.value) if operator_def(old.field, operator) is not None else old)

    @Slot(str, str)
    def setConditionValue(self, key: str, value: str) -> None:  # noqa: N802
        self._set_condition(key, lambda old: Condition(old.field, old.operator, value))

    # Aktionen der geöffneten Regel ----------------------------------------------------------------------------------
    def _action_row(self, key: str, action: Action) -> dict:
        definition = ACTION.get(action.kind)
        return {
            "key": key,
            "kind": action.kind,
            "field": action.field,
            "value": action.value,
            "find": action.find,
            "needsValue": definition is None or definition.needs_value,
            "needsFind": action.kind == "replace",
            "placeholder": "ersetzen durch (leer = entfernen)" if action.kind == "replace" else ("Text, auch mit Leerzeichen" if action.kind in ("prefix", "suffix") else "neuer Wert"),
            "problem": action.problem(),
        }

    def _set_action(self, key: str, change) -> None:
        rule = self._editing()
        if rule is None or key not in self._action_keys:
            return
        index = self._action_keys.index(key)
        actions = list(rule.actions)
        new = change(actions[index])
        if new == actions[index]:
            return
        actions[index] = new
        self._replace_rule(replace(rule, actions=tuple(actions)))
        self.actionModel.update_item(key, **self._action_row(key, new))

    @Slot()
    def addAction(self) -> None:  # noqa: N802
        rule = self._editing()
        if rule is None:
            return
        action = Action()
        self._action_keys.append(self._key())
        self._replace_rule(replace(rule, actions=rule.actions + (action,)))
        self.actionModel.set_items([*self.actionModel.items(), self._action_row(self._action_keys[-1], action)])

    @Slot(str)
    def removeAction(self, key: str) -> None:  # noqa: N802
        rule = self._editing()
        if rule is None or key not in self._action_keys:
            return
        index = self._action_keys.index(key)
        del self._action_keys[index]
        self._replace_rule(replace(rule, actions=tuple(a for i, a in enumerate(rule.actions) if i != index)))
        self.actionModel.set_items([item for item in self.actionModel.items() if item["key"] != key])

    @Slot(str, str)
    def setActionKind(self, key: str, kind: str) -> None:  # noqa: N802
        if kind not in ACTION:
            return
        self._set_action(key, lambda old: Action(kind, old.field, "" if kind == "clear" else old.value, old.find if kind == "replace" else ""))

    @Slot(str, str)
    def setActionField(self, key: str, field: str) -> None:  # noqa: N802
        if field not in FIELD or not FIELD[field].editable:
            return
        self._set_action(key, lambda old: Action(old.kind, field, old.value, old.find))

    @Slot(str, str)
    def setActionValue(self, key: str, value: str) -> None:  # noqa: N802
        self._set_action(key, lambda old: Action(old.kind, old.field, value, old.find))

    @Slot(str, str)
    def setActionFind(self, key: str, value: str) -> None:  # noqa: N802
        self._set_action(key, lambda old: Action(old.kind, old.field, old.value, value))

    # Testmodus und Vorschau -------------------------------------------------------------------------------------------
    def test_soon(self, delay: int = TEST_DELAY) -> None:
        if self.detailId:
            self.app.timers.later("rules:test", delay, self.run_test)

    def analysis_changed(self) -> None:
        """Excel geprüft, Zyklus-Regeln geändert …: Testmodus und Zusammenfassung neu rechnen."""
        self.test_soon()
        self.summary_soon()

    def _contracts(self) -> tuple[tuple, str] | None:
        result = self.c.analysis_for_current()
        if not result or not result.get("ok"):
            return None
        return tuple(result.get("vertraege") or ()), Path(self.c.excel.strip()).name

    def run_test(self) -> None:
        """Entwurf gegen die geprüfte Excel rechnen (im Hintergrund – die Oberfläche bleibt bedienbar)."""
        rule_set = self.current()
        if rule_set is None:
            return
        source = self._contracts()
        self._test_serial += 1
        serial = self._test_serial
        if source is None:
            self._test = None
            self.testReady = False
            self.testBusy = False
            self.testSource = ""
            self.testTitle = ""
            self.testText = NO_EXCEL
            self.previewModel.clear()
            self.previewMore = ""
            self.refresh_rules()
            return
        vertraege, name = source
        regeln = [dict(regel) for regel in self.state.regeln]
        # Ausgeschaltet: zeigen, was es eingeschaltet täte (Testmodus vor dem Einschalten)
        probe = rule_set if rule_set.active else rule_set.with_(active=True)
        self.testBusy = True

        def work() -> evaluate.RulePreview:
            return evaluate.preview(probe, evaluate.contract_inputs(vertraege, regeln), probe_inactive=True)

        def done(result: evaluate.RulePreview) -> None:
            if serial == self._test_serial:
                self._show_test(result, name, rule_set.active)

        def failed(_exc, _text) -> None:
            if serial == self._test_serial:
                self.testBusy = False
                self.testReady = False
                self.testText = "Die Vorschau konnte nicht berechnet werden."

        self.app.worker.run(work, done, failed)

    def _show_test(self, result: evaluate.RulePreview, name: str, active: bool) -> None:
        self._test = result
        self.testBusy = False
        self.testReady = True
        self.testSource = f"{name} · {contracts_text(result.total)}"
        if result.total == 0:
            title = "Die Excel enthält keine Verträge"
        elif result.affected:
            title = f"Ändert {result.affected} von {result.total} {'Vertrag' if result.total == 1 else 'Verträgen'}"
        else:
            title = "Ändert keinen Vertrag"
        self.testTitle = title if active else f"Ausgeschaltet – eingeschaltet: {title[0].lower()}{title[1:]}"
        parts = [f"{definition.label} bei {contracts_text(result.fields[definition.key])}" for definition in FIELDS if result.fields.get(definition.key)]
        if result.conflicts:
            parts.append(f"{result.conflicts} {'Konflikt' if result.conflicts == 1 else 'Konflikte'}: mehrere Regeln ändern dasselbe Feld – die spätere gilt")
        self.testText = " · ".join(parts) if parts else ("Keine Regel trifft zu bzw. ändert einen Wert." if result.total else "")
        rows = []
        for contract in result.contracts[:PREVIEW_LIMIT]:
            title = f"Vertrag {contract.nummer}" if contract.nummer and contract.nummer != "–" else f"Vertrag in Zeile {contract.index + 1} der Liste"
            lines = [
                {
                    "label": change.label,
                    "before": change.before if change.before.strip() not in evaluate.EMPTY_VALUES else "leer",
                    "after": change.after if change.after.strip() not in evaluate.EMPTY_VALUES else "leer",
                    "rules": " → ".join(f"„{rule}“" for rule in change.rules),
                    "conflict": change.conflict,
                }
                for change in contract.fields
            ]
            rows.append({"key": str(contract.index), "title": title, "lines": lines})
        self.previewModel.set_items(rows)
        more = result.affected - PREVIEW_LIMIT
        self.previewMore = f"… und {more} weitere geänderte Verträge" if more > 0 else ""
        self.refresh_rules()

    # Zusammenfassung für »Darstellung« und »Übersicht erstellen« -------------------------------------------------------
    def summary_soon(self) -> None:
        self.app.timers.later("rules:summary", 150, self.refresh_summary)

    def _overview_changed(self) -> None:
        self.refresh_list()
        if self.detailId:
            self.refresh_detail()
        self.summary_soon()

    def refresh_summary(self) -> None:
        """Was das Regelwerk der Übersicht an der geprüften Excel ändert – nie eine stille Änderung."""
        rule_set = self.c.rule_set()
        if rule_set is None:
            self._summary_key = None
            self._summary_serial += 1
            self.activeSummary = ""
            return
        name = f"Regelwerk „{rule_set.name}“"
        if not rule_set.active:
            self._set_summary(f"{name} ist ausgeschaltet – es ändert nichts.", "caution")
            return
        if not rule_set.runnable_rules():
            self._set_summary(f"{name} enthält keine vollständige, eingeschaltete Regel – es ändert nichts.", "caution")
            return
        source = self._contracts()
        if source is None:
            self._set_summary(f"{name} ist gewählt und wird auf die Excel angewendet.", "info")
            return
        vertraege, excel = source
        regeln = [dict(regel) for regel in self.state.regeln]
        key = (rule_set.id, rule_set.fingerprint(), excel, _contracts_key(vertraege), repr(regeln))
        if key == self._summary_key:
            return
        self._summary_key = key
        self._summary_serial += 1
        serial = self._summary_serial

        def work() -> evaluate.RulePreview:
            return evaluate.preview(rule_set, evaluate.contract_inputs(vertraege, regeln))

        def done(result: evaluate.RulePreview) -> None:
            if serial != self._summary_serial:
                return
            if result.affected:
                of = f"von {result.total} {'Vertrag' if result.total == 1 else 'Verträgen'}"
                self._set_summary(f"{name} ändert {result.affected} {of} der Excel – vorher → nachher in »Regeln«.", "info", computed=True)
            else:
                self._set_summary(f"{name} ist gewählt, ändert an dieser Excel aber nichts.", "info", computed=True)

        def failed(_exc, _text) -> None:
            if serial == self._summary_serial:
                self._set_summary(f"{name} ist gewählt und wird auf die Excel angewendet.", "info")

        self.app.worker.run(work, done, failed)

    def _set_summary(self, text: str, tone: str, computed: bool = False) -> None:
        if not computed:
            self._summary_key = None
            self._summary_serial += 1  # laufende Berechnung verwerfen
        self.activeTone = tone
        self.activeSummary = text

    def focus_search(self) -> None:
        """Strg+F: zur Liste und ins Suchfeld."""
        if self.detailId:
            self.showList()
        self.focusRequested.emit("search")

    # Für QML -----------------------------------------------------------------------------------------------------
    _constant = Signal()

    def _list_model(self) -> QObject:
        return self.model

    def _rule_model(self) -> QObject:
        return self.ruleModel

    def _condition_model(self) -> QObject:
        return self.conditionModel

    def _action_model(self) -> QObject:
        return self.actionModel

    def _preview_model(self) -> QObject:
        return self.previewModel

    def _texts(self) -> dict:
        return {"emptyTitle": EMPTY_TITLE, "emptyText": EMPTY_TEXT, "orderHint": ORDER_HINT, "noExcel": NO_EXCEL}

    def _fields(self) -> list:
        return [{"key": d.key, "label": d.label} for d in FIELDS]

    def _editable(self) -> list:
        return [{"key": d.key, "label": d.label} for d in FIELDS if d.editable]

    def _actions(self) -> list:
        return [{"key": a.key, "label": a.label} for a in ACTIONS]

    def _matches(self) -> list:
        return [dict(choice) for choice in MATCH_CHOICES]

    listModel = Property(QObject, _list_model, notify=_constant)
    rulesModel = Property(QObject, _rule_model, notify=_constant)
    conditionsModel = Property(QObject, _condition_model, notify=_constant)
    actionsModel = Property(QObject, _action_model, notify=_constant)
    changesModel = Property(QObject, _preview_model, notify=_constant)
    texts = Property("QVariantMap", _texts, notify=_constant)
    fieldChoices = Property(list, _fields, notify=_constant)
    targetChoices = Property(list, _editable, notify=_constant)
    actionChoices = Property(list, _actions, notify=_constant)
    matchChoices = Property(list, _matches, notify=_constant)
