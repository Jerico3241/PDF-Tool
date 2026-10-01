"""Qt-Oberfläche: Regelwerk 2.0 (Tests 98–101 der Vorgabe).

* Ansicht »Regeln«: Regelwerk anlegen, Regeln WENN … DANN … visuell bearbeiten, Reihenfolge,
  Duplizieren, Entfernen mit »Rückgängig«, Ein-/Ausschalten, automatisch speichern.
* Testmodus »trifft auf 2 von 3 Verträgen zu« und Vorschau vorher → nachher (im Hintergrund).
* Das Regelwerk der Übersicht wirkt auf PDF und gespeicherten Vertragsstand – nie auf die Excel.
* Löschen löst Verweise (Darstellung, Vorlagen, Stapel) kontrolliert.
* Eingaben behalten beim Tippen ihren Fokus (kein Neuaufbau der Bearbeitungszeilen).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from conftest import neustart, pump, wait_until
from test_qt_customers import antworten, hinweis, pruefen


def regelwerk_anlegen(h, monkeypatch, name: str = "Energie") -> str:
    antworten(monkeypatch, "text_input", "primary", {"value": name})
    h.rules.newRuleSet()
    rule_set = h.app.state.rule_sets.by_name(name)
    assert rule_set is not None and h.rules.detailId == rule_set.id
    return rule_set.id


def regel_ausfuellen(h, feld: str = "beschreibung", vergleich: str = "contains", wert: str = "Hott", ziel: str = "art", aktion: str = "set", neu: str = "KI-Vertrag") -> None:
    """Die geöffnete Regel ausfüllen: eine Bedingung, eine Aktion (wie in der Oberfläche)."""
    r = h.rules
    bedingung = r.conditionsModel.get(0)["key"]
    r.setConditionField(bedingung, feld)
    r.setConditionOperator(bedingung, vergleich)
    r.setConditionValue(bedingung, wert)
    schritt = r.actionsModel.get(0)["key"]
    r.setActionField(schritt, ziel)
    r.setActionKind(schritt, aktion)
    r.setActionValue(schritt, neu)


def gespeichert(h, ident: str):
    h.rules.flush()
    return h.app.state.rule_sets.get(ident)


def test_98_build_rule_visually_and_autosave(ui_app, monkeypatch) -> None:
    h = ui_app
    r = h.rules
    h.navigate("rules", 0.3)
    assert r.total == 0
    ident = regelwerk_anlegen(h, monkeypatch)
    pump(0.3)
    # Die erste Regel ist zum Bearbeiten geöffnet und noch unvollständig (wird nie ausgeführt)
    first = r.rulesModel.get(0)
    assert r.editingRule == first["id"] and "Wert fehlt" in first["problems"]
    regel_ausfuellen(h)
    row = r.rulesModel.get(0)
    assert row["problems"] == "" and row["whenText"] == "Beschreibung enthält „Hott“" and row["thenText"] == "Art auf „KI-Vertrag“ setzen"
    # Automatisch gespeichert (gesammelt)
    assert wait_until(lambda: r.saves >= 1, 3)
    rule = h.app.state.rule_sets.get(ident).rules[0]
    assert rule.conditions[0].value == "Hott" and rule.actions[0].value == "KI-Vertrag"
    # Feldtyp wechseln: passender Vergleich, Wert nur bei gleichem Typ
    key = r.conditionsModel.get(0)["key"]
    r.setConditionField(key, "netto")
    cond = r.conditionsModel.get(0)
    assert cond["operator"] == "eq" and cond["value"] == "" and [op["key"] for op in cond["operators"]][:2] == ["eq", "ne"]
    r.setConditionValue(key, "abc")
    assert r.conditionsModel.get(0)["problem"] == "Keine gültige Zahl"
    r.setConditionOperator(key, "gt")
    r.setConditionValue(key, "100")
    assert r.rulesModel.get(0)["whenText"] == "Netto größer als „100“"
    # ODER, zweite Bedingung, zweite Aktion
    r.setMatch("any")
    r.addCondition()
    key2 = r.conditionsModel.get(1)["key"]
    r.setConditionValue(key2, "Hotline")
    r.addAction()
    step2 = r.actionsModel.get(1)["key"]
    r.setActionField(step2, "zahlungsart")
    r.setActionKind(step2, "suffix")
    r.setActionValue(step2, " (geprüft)")
    row = r.rulesModel.get(0)
    assert " oder " in row["whenText"] and "anhängen" in row["thenText"]
    # Nicht änderbare Felder sind kein Ziel
    r.setActionField(step2, "netto")
    assert r.actionsModel.get(1)["field"] == "zahlungsart"
    saved = gespeichert(h, ident)
    assert saved.rules[0].match == "any" and len(saved.rules[0].conditions) == 2 and saved.rules[0].actions[1].value == " (geprüft)"


def test_99_order_duplicate_remove_undo_and_toggle(ui_app, monkeypatch) -> None:
    h = ui_app
    r = h.rules
    h.navigate("rules", 0.2)
    ident = regelwerk_anlegen(h, monkeypatch)
    regel_ausfuellen(h)
    r.setRuleName("Erste")
    r.addRule()
    regel_ausfuellen(h, wert="Hotline", neu="Support")
    r.setRuleName("Zweite")
    names = lambda: [r.rulesModel.get(i)["name"] for i in range(r.rulesModel.count)]  # noqa: E731
    assert names() == ["Erste", "Zweite"]
    second = r.rulesModel.get(1)["id"]
    r.moveRule(second, -1)
    assert names() == ["Zweite", "Erste"] and r.rulesModel.get(0)["first"] is True
    r.duplicateRule(second)
    assert names() == ["Zweite", "Zweite – Kopie", "Erste"]
    copy = r.rulesModel.get(1)["id"]
    assert copy != second and r.editingRule == copy
    r.removeRule(copy)
    assert names() == ["Zweite", "Erste"] and "Rückgängig" in list(hinweis(h, "regeln_verwaltung").actions)
    hinweis(h, "regeln_verwaltung").trigger(list(hinweis(h, "regeln_verwaltung").actions).index("Rückgängig"))
    assert names() == ["Zweite", "Zweite – Kopie", "Erste"]
    r.setRuleActive(second, False)
    assert r.rulesModel.get(0)["active"] is False
    saved = gespeichert(h, ident)
    assert [rule.name for rule in saved.rules] == ["Zweite", "Zweite – Kopie", "Erste"] and saved.rules[0].active is False


def test_100_test_mode_preview_and_pdf_values(ui_app, monkeypatch, excel_file: Path, tmp_path: Path) -> None:
    h = ui_app
    r, o = h.rules, h.overview
    vorher = hashlib.sha256(excel_file.read_bytes()).hexdigest()
    pruefen(h, excel_file)
    h.navigate("rules", 0.2)
    ident = regelwerk_anlegen(h, monkeypatch)
    regel_ausfuellen(h, wert="Hott", neu="KI-Vertrag")
    r.addRule()
    regel_ausfuellen(h, feld="netto", vergleich="ge", wert="100", ziel="zahlungsart", aktion="set", neu="Rechnung")
    # Testmodus (im Hintergrund): 3 aktive Verträge in der Liste
    assert wait_until(lambda: r.testReady and not r.testBusy and r.rulesModel.get(1)["hits"] != "", 10)
    assert r.rulesModel.get(0)["hits"].startswith("Trifft auf 1 von 3 Verträgen zu")
    assert r.rulesModel.get(1)["hits"].startswith("Trifft auf 2 von 3 Verträgen zu")
    assert r.testTitle == "Ändert 2 von 3 Verträgen" and r.changesModel.count == 2
    lines = r.changesModel.get(0)["lines"]
    assert any(line["label"] == "Art" and line["after"] == "KI-Vertrag" for line in r.changesModel.get(0)["lines"] + r.changesModel.get(1)["lines"]) and lines
    # Konflikt: zweite Regel ändert dasselbe Feld wie die erste – die spätere gilt, sichtbar
    r.addRule()
    regel_ausfuellen(h, wert="Hott", ziel="art", neu="Assistent")
    assert wait_until(lambda: "Konflikt" in r.testText, 10)
    alle = [line for i in range(r.changesModel.count) for line in r.changesModel.get(i)["lines"]]
    konflikt = next(line for line in alle if line["conflict"])
    assert konflikt["after"] == "Assistent" and "→" in konflikt["rules"]
    # Ausgeschaltetes Regelwerk: ändert nichts, der Testmodus zeigt trotzdem, was es täte
    r.setActive(False)
    assert wait_until(lambda: r.testTitle.startswith("Ausgeschaltet"), 10)
    r.setActive(True)
    # Für die Übersicht verwenden: Zusammenfassung in »Übersicht erstellen«, PDF und Vertragsstand
    r.useInOverview()
    assert o.ruleSetId == ident
    assert wait_until(lambda: "ändert 2 von 3" in r.activeSummary, 10)
    h.navigate("create", 0.4)
    assert h.item("ruleSetLine").property("expanded") is True
    o.firma, o.kd = "Muster GmbH", "10042"
    o.ziel = str(tmp_path)
    pump(0.1)
    o.startPdf()
    assert wait_until(lambda: not o.busy and h.app.state.pdfs, 60)
    import pypdf

    text = " ".join(" ".join(page.extract_text() for page in pypdf.PdfReader(h.app.state.pdfs[0]).pages).split())
    assert "Assistent" in text and "Rechnung" in text
    assert hashlib.sha256(excel_file.read_bytes()).hexdigest() == vorher  # Excel unverändert


def test_101_delete_rule_set_resolves_references(ui_app, monkeypatch) -> None:
    h = ui_app
    r, o = h.rules, h.overview
    ident = regelwerk_anlegen(h, monkeypatch)
    regel_ausfuellen(h)
    r.useInOverview()
    assert o.saveAsTemplate("Mit Regeln") is True  # die Vorlage hält das Regelwerk fest
    template = h.app.state.templates.by_name("Mit Regeln")
    assert template.rules.rule_set_id == ident
    pump(0.2)
    r.showDetail(ident)
    assert any("Vorlage" in use for use in r.detailUses) and r.detailUsed
    r.remove()
    frage = h.app.dialogs.history[-1]
    assert frage["kind"] == "confirm" and "Darstellung" in frage["message"] and "Vorlage" in frage["message"]
    assert h.app.state.rule_sets.get(ident) is None and r.detailId == ""
    assert o.ruleSetId == "" and h.app.state.templates.get(template.id).rules.rule_set_id == ""
    # Die geladene Vorlage war unverändert – sie bleibt es (Darstellung und Vorlage ohne Regelwerk)
    pump(0.2)
    assert o.vorlageId == template.id and not o.templateModified


def test_rule_set_persists_and_template_applies_it(ui_app, monkeypatch, config_file: Path) -> None:
    h = ui_app
    ident = regelwerk_anlegen(h, monkeypatch)
    regel_ausfuellen(h)
    h.rules.useInOverview()
    assert h.overview.saveAsTemplate("Energie") is True
    h.overview.setRuleSet("")
    assert wait_until(lambda: h.overview.templateModified, 3)
    h.overview.discardTemplateChanges()  # Vorlage legt das Regelwerk wieder fest
    assert h.overview.ruleSetId == ident
    neu = neustart(h)
    pump(0.3)
    assert neu.overview.ruleSetId == ident and neu.app.state.rule_sets.get(ident).rules[0].conditions[0].value == "Hott"
    assert json.loads(config_file.read_text(encoding="utf-8"))["regelwerk"] == ident


def test_typing_keeps_focus_in_rule_editor(ui_app, monkeypatch) -> None:
    """Tippen in einen Wert: das Feld behält den Fokus, die Zeile wird nicht neu aufgebaut, die
    Zusammenfassung der Karte folgt sofort."""
    h = ui_app
    h.navigate("rules", 0.3)
    regelwerk_anlegen(h, monkeypatch)
    pump(0.4)
    feld = h.item("conditionValue")
    assert feld is not None
    feld.forceActiveFocus()
    pump(0.05)
    for zeichen in "Energie":
        QTest.keyClick(h.window, zeichen)
    pump(0.1)
    assert h.item("conditionValue") == feld and feld.property("activeFocus") is True
    assert feld.property("text") == "Energie" and "„Energie“" in h.rules.rulesModel.get(0)["whenText"]


def test_rule_builder_with_many_rules(ui_app, monkeypatch) -> None:
    """Regelwerk mit 120 Regeln: Karten virtualisiert, Testmodus im Hintergrund."""
    import time

    from tools.contract_overview.rules.models import Action, Condition, Rule, new_id

    h = ui_app
    ident = regelwerk_anlegen(h, monkeypatch, "Gross")
    store = h.app.state.rule_sets
    rules = tuple(Rule(new_id(), f"Regel {i}", conditions=(Condition("beschreibung", "contains", f"Modul {i}"),), actions=(Action("set", "art", f"Art {i}"),)) for i in range(120))
    store.update(store.get(ident).with_(rules=rules))
    start = time.perf_counter()
    h.rules.showDetail(ident)
    dauer = time.perf_counter() - start
    h.navigate("rules", 0.4)
    assert h.rules.rulesModel.count == 120 and dauer < 1.0, dauer
    karten = [item for item in h.items("editRule")]
    assert 0 < len(karten) < 120  # nur sichtbare Karten existieren
