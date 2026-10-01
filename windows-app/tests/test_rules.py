"""Regelwerk 2.0 (Tests 96 und 97 der Vorgabe): Bedingungen, Aktionen, Reihenfolge, Konflikte,
Vorschau vorher → nachher, Determinismus, Ablage – ohne Oberfläche.
"""

from __future__ import annotations

import json
import time
from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest

from engine import Vertragsdaten
from storage import NewerSchema, SchemaError
from tools.contract_overview.rules.evaluate import Evaluator, Typed, contract_inputs, evaluator_for, preview
from tools.contract_overview.rules.models import (
    FIELDS,
    MATCH_ANY,
    OPERATORS,
    SCHEMA_VERSION,
    Action,
    Condition,
    FieldType,
    Rule,
    RuleSet,
    new_id,
    new_rule,
    parse_date,
    parse_number,
)
from tools.contract_overview.rules.repository import RuleSetStore

VERTRAEGE = [
    Vertragsdaten("V-1001", "x SW-Pflege Warenwirtschaft Energieberater", "2023-01-15", "15.01.2023", "jeden Monat", 49.9, "Lastschr", 2),
    Vertragsdaten("V-1002", "Hott-KI Assistent", "2022-06-01", "01.06.2022", "monatlich", 120.0, "Überweisung", 3),
    Vertragsdaten("V-1003", "Hotline Premium", "2021-03-01", "01.03.2021", "jährlich", 300.0, "Sofort", 4),
    Vertragsdaten("ABC-77", "SW-Pflege Energieberater Plus", None, "", "12", "199,00", None, 5),
]


def regel(*conditions, actions=(), match="all", name="", active=True) -> Rule:
    return Rule(id=new_id(), name=name, active=active, match=match, conditions=tuple(conditions), actions=tuple(actions))


def werk(*rules, active=True) -> RuleSet:
    return RuleSet(id=new_id(), name="Test", active=active, rules=tuple(rules))


def ergebnisse(rule_set, vertraege=VERTRAEGE, regeln=None):
    evaluator = Evaluator(rule_set)
    return [evaluator.apply_contract(vertrag, vertrag.anzeige(regeln)) for vertrag in vertraege]


def C(field, operator, value=""):
    return Condition(field, operator, value)


def A(kind, field, value="", find=""):
    return Action(kind, field, value, find)


# --- Beispiele der Vorgabe ---------------------------------------------------------------------------


def test_96_examples_from_the_specification():
    rules = werk(
        regel(C("beschreibung", "contains", "Hotline"), actions=[A("set", "art", "Support")], name="Hotline"),
        regel(C("zyklus", "equals", "12"), actions=[A("set", "zyklus", "jährlich")], name="Zyklus 12"),
        regel(C("art", "equals", "Softwarepflegevertrag"), C("beschreibung", "contains", "Energieberater"), actions=[A("set", "art", "Energieberater Softwarepflege")], name="Energieberater"),
        regel(C("nummer", "starts_with", "ABC-"), actions=[A("set", "zahlungsart", "Rechnung")], name="Präfix"),
    )
    out = ergebnisse(rules)
    assert out[2].values["art"] == "Support"  # Hotline Premium
    assert out[3].values["zyklus"] == "jährlich"  # Zahlungszyklus 12
    assert out[0].values["art"] == "Energieberater Softwarepflege" and out[3].values["art"] == "Energieberater Softwarepflege"
    assert out[1].values["art"] == "Softwarepflegevertrag"  # keine Bedingung erfüllt
    assert out[3].values["zahlungsart"] == "Rechnung" and out[0].values["zahlungsart"] == "Lastschrift"


# --- Bedingungen ----------------------------------------------------------------------------------------


def test_96_single_condition_and_all_text_operators():
    base = {"nummer": "V-1", "art": "Softwarepflegevertrag", "beschreibung": "Hotline Basic Energie", "beginn": "01.01.2024", "zyklus": "–", "netto": "10,00", "zahlungsart": "Lastschrift"}
    expect = {
        ("equals", "hotline basic energie"): True,
        ("equals", "Hotline"): False,
        ("not_equals", "Hotline"): True,
        ("contains", "BASIC"): True,
        ("not_contains", "basic"): False,
        ("starts_with", "  hotline "): True,
        ("ends_with", "energie"): True,
        ("ends_with", "hotline"): False,
        ("empty", ""): False,
        ("not_empty", ""): True,
    }
    for (operator, value), hit in expect.items():
        result = Evaluator(werk(regel(C("beschreibung", operator, value), actions=[A("set", "art", "X")]))).apply(base)
        assert (result.values["art"] == "X") is hit, (operator, value)
    # »–« steht in der PDF für einen fehlenden Wert und gilt als leer
    assert Evaluator(werk(regel(C("zyklus", "empty"), actions=[A("set", "zyklus", "monatlich")]))).apply(base).values["zyklus"] == "monatlich"


def test_96_number_operators_use_the_excel_amount():
    typed = Typed(netto=Decimal("120.00"))
    base = {"netto": "120,00", "art": "a"}
    for operator, value, hit in [("eq", "120", True), ("eq", "120,01", False), ("ne", "1", True), ("gt", "99,99", True), ("gt", "120", False), ("lt", "1.234,50", True), ("ge", "120.00", True), ("le", "119", False), ("empty", "", False), ("not_empty", "", True)]:
        result = Evaluator(werk(regel(C("netto", operator, value), actions=[A("set", "art", "X")]))).apply(base, typed)
        assert (result.values["art"] == "X") is hit, (operator, value)
    assert Evaluator(werk(regel(C("netto", "empty"), actions=[A("set", "art", "X")]))).apply(base, Typed()).values["art"] == "X"
    assert parse_number("1.234,50") == Decimal("1234.50") and parse_number("49.90") == Decimal("49.90") and parse_number("abc") is None


def test_96_date_operators():
    typed = Typed(beginn=date(2023, 1, 15))
    for operator, value, hit in [("before", "01.02.2023", True), ("before", "15.01.2023", False), ("after", "2022-12-31", True), ("on", "15.1.2023", True), ("empty", "", False), ("not_empty", "", True)]:
        result = Evaluator(werk(regel(C("beginn", operator, value), actions=[A("set", "art", "X")]))).apply({"art": "a"}, typed)
        assert (result.values["art"] == "X") is hit, (operator, value)
    assert Evaluator(werk(regel(C("beginn", "empty"), actions=[A("set", "art", "X")]))).apply({"art": "a"}, Typed()).values["art"] == "X"
    assert parse_date("31.02.2024") is None and parse_date("2024-02-29") == date(2024, 2, 29)


def test_96_several_conditions_and_or():
    und = werk(regel(C("beschreibung", "contains", "Energieberater"), C("netto", "gt", "100"), actions=[A("set", "art", "Groß")]))
    oder = werk(regel(C("beschreibung", "contains", "Hotline"), C("nummer", "starts_with", "ABC"), match=MATCH_ANY, actions=[A("set", "art", "Treffer")]))
    assert [o.values["art"] for o in ergebnisse(und)] == ["Softwarepflegevertrag", "Softwarepflegevertrag", "Supportvertrag", "Groß"]
    assert [o.values["art"] == "Treffer" for o in ergebnisse(oder)] == [False, False, True, True]


def test_rule_without_conditions_applies_to_all_contracts():
    out = ergebnisse(werk(regel(actions=[A("suffix", "beschreibung", " (geprüft)")])))
    assert all(o.values["beschreibung"].endswith(" (geprüft)") for o in out)


# --- Aktionen -----------------------------------------------------------------------------------------------


def test_96_several_actions_and_all_action_types():
    rule = regel(
        C("nummer", "equals", "V-1003"),
        actions=[
            A("set", "art", "Support"),
            A("replace", "beschreibung", "Basis", find="premium"),  # ohne Groß-/Kleinschreibung
            A("prefix", "zahlungsart", "per "),
            A("suffix", "zyklus", " (Vorauszahlung)"),
            A("clear", "beschreibung"),
            A("set", "beschreibung", "Hotline"),
        ],
    )
    out = Evaluator(werk(rule)).apply_contract(VERTRAEGE[2], VERTRAEGE[2].anzeige())
    assert out.values["art"] == "Support" and out.values["zahlungsart"] == "per Sofort" and out.values["zyklus"] == "jährlich (Vorauszahlung)"
    assert out.values["beschreibung"] == "Hotline"
    assert [(c.field, c.before, c.after) for c in out.changes][:2] == [("art", "Supportvertrag", "Support"), ("beschreibung", "Hotline Premium", "Hotline Basis")]


def test_prefix_and_suffix_on_an_empty_value_give_just_the_text():
    out = Evaluator(werk(regel(actions=[A("prefix", "zahlungsart", "Rechnung "), A("suffix", "zyklus", " jährlich")]))).apply({"zahlungsart": "–", "zyklus": ""})
    assert out.values["zahlungsart"] == "Rechnung" and out.values["zyklus"] == "jährlich"


def test_actions_never_change_identity_amount_or_date():
    for field in ("nummer", "netto", "beginn"):
        rule = regel(actions=[A("set", field, "X")])
        assert any("kann nicht geändert werden" in p for p in rule.problems())
        assert not Evaluator(werk(rule)).active  # unvollständige Regel wird nie ausgeführt


# --- Reihenfolge, Konflikte, Aktiv/Inaktiv -------------------------------------------------------------------------


def test_96_rule_order_later_rule_wins_and_sees_earlier_results():
    erste = regel(C("beschreibung", "contains", "Hotline"), actions=[A("set", "art", "Support")], name="Erste")
    zweite = regel(C("art", "equals", "Support"), actions=[A("set", "art", "Hotline-Support")], name="Zweite")
    assert ergebnisse(werk(erste, zweite))[2].values["art"] == "Hotline-Support"  # sieht das Ergebnis der ersten
    assert ergebnisse(werk(zweite, erste))[2].values["art"] == "Support"  # andere Reihenfolge, anderes Ergebnis


def test_96_conflict_of_two_rules_is_visible_in_the_preview():
    a = regel(C("beschreibung", "contains", "Hotline"), actions=[A("set", "art", "Support")], name="A")
    b = regel(C("netto", "ge", "300"), actions=[A("set", "art", "Premium")], name="B")
    result = preview(werk(a, b), contract_inputs(VERTRAEGE))
    hotline = next(c for c in result.contracts if c.nummer == "V-1003")
    change = hotline.fields[0]
    assert (change.field, change.before, change.after, change.rules, change.conflict) == ("art", "Supportvertrag", "Premium", ("A", "B"), True)
    assert result.conflicts == 1


def test_96_inactive_rule_and_inactive_rule_set():
    rule = regel(actions=[A("set", "art", "X")])
    assert ergebnisse(werk(replace(rule, active=False)))[0].values["art"] == "Softwarepflegevertrag"
    assert ergebnisse(werk(rule, active=False))[0].values["art"] == "Softwarepflegevertrag"
    assert not Evaluator(werk(rule, active=False)).active and not Evaluator(None).active
    assert ergebnisse(werk(rule))[0].values["art"] == "X"


def test_incomplete_rules_are_reported_and_skipped():
    assert regel(C("netto", "gt", "abc"), actions=[A("set", "art", "X")]).problems() == ["Bedingung 1: Keine gültige Zahl"]
    assert regel(C("beginn", "on", "morgen"), actions=[A("set", "art", "X")]).problems() == ["Bedingung 1: Kein gültiges Datum (TT.MM.JJJJ)"]
    assert regel(C("beschreibung", "gt", "x"), actions=[A("set", "art", "X")]).problems() == ["Bedingung 1: Dieser Vergleich passt nicht zum Feld"]
    assert regel(C("beschreibung", "contains", " "), actions=[A("set", "art", "X")]).problems() == ["Bedingung 1: Wert fehlt"]
    assert regel(C("ende", "contains", "x"), actions=[A("set", "art", "X")]).problems() == ["Bedingung 1: Unbekanntes Feld"]
    assert regel(C("beschreibung", "contains", "x")).problems() == ["Keine Aktion"]
    assert regel(actions=[A("replace", "art", "Y")]).problems() == ["Aktion 1: Zu ersetzender Text fehlt"]
    assert regel(actions=[A("set", "art", "  ")]).problems() == ["Aktion 1: Wert fehlt"]
    assert regel(actions=[A("loeschen", "art")]).problems() == ["Aktion 1: Unbekannte Aktion"]
    assert new_rule("Neu").problems() == ["Bedingung 1: Wert fehlt", "Aktion 1: Wert fehlt"]


# --- Vorschau ---------------------------------------------------------------------------------------------------


def test_96_preview_before_after_only_changed_fields():
    rules = werk(
        regel(C("beschreibung", "contains", "Hotline"), actions=[A("set", "art", "Support")], name="Hotline"),
        regel(C("beschreibung", "contains", "Hott-KI"), actions=[A("set", "beschreibung", "Hott-KI Assistent")], name="Unverändert"),  # setzt denselben Wert
    )
    result = preview(rules, contract_inputs(VERTRAEGE))
    assert (result.total, result.affected) == (4, 1)
    only = result.contracts[0]
    assert only.nummer == "V-1003" and [(f.label, f.before, f.after) for f in only.fields] == [("Art", "Supportvertrag", "Support")]
    ids = [rule.id for rule in rules.rules]
    assert result.hits == {ids[0]: 1, ids[1]: 1} and result.changed == {ids[0]: 1}  # »trifft auf 1 von 4 zu«
    assert result.fields == {"art": 1}


def test_preview_uses_cycle_rules_as_starting_point():
    zyklus = [{"enthaelt": "Hott-KI", "zyklus": "jährlich"}]
    rules = werk(regel(C("zyklus", "equals", "jährlich"), actions=[A("suffix", "zyklus", " (Regel)")]))
    result = preview(rules, contract_inputs(VERTRAEGE, zyklus))
    assert {c.nummer for c in result.contracts} == {"V-1002", "V-1003"}  # V-1002: »monatlich« durch die Zyklus-Regel


# --- Determinismus --------------------------------------------------------------------------------------------------


def test_97_same_input_same_rules_same_result():
    rules = werk(
        regel(C("beschreibung", "contains", "Energieberater"), actions=[A("set", "art", "EB")]),
        regel(C("art", "equals", "EB"), C("netto", "gt", "100"), actions=[A("suffix", "art", " groß")]),
        regel(C("zyklus", "not_empty"), match=MATCH_ANY, actions=[A("replace", "zyklus", "Jahr", find="jährlich")]),
    )
    first = [(o.values, [(c.rule_id, c.field, c.before, c.after) for c in o.changes]) for o in ergebnisse(rules)]
    for _ in range(5):
        again = [(o.values, [(c.rule_id, c.field, c.before, c.after) for c in o.changes]) for o in ergebnisse(rules)]
        assert again == first
    # Reihenfolge der Verträge ändert nichts am Ergebnis je Vertrag
    backwards = ergebnisse(rules, list(reversed(VERTRAEGE)))
    assert [o.values for o in reversed(backwards)] == [values for values, _ in first]
    # Regelwerk aus dem gespeicherten Stand (PDF-Auftrag) wirkt identisch
    restored = evaluator_for(json.loads(json.dumps(rules.to_dict())))
    assert [restored.apply_contract(v, v.anzeige()).values for v in VERTRAEGE] == [values for values, _ in first]
    assert rules.fingerprint() == RuleSet.from_dict(rules.to_dict()).fingerprint()


# --- Speichern ------------------------------------------------------------------------------------------------------


def test_rule_set_roundtrip_and_store(tmp_path):
    store = RuleSetStore(tmp_path / "regelwerke")
    created = store.create("Energie", "Für Energieberater", rules=(regel(C("beschreibung", "contains", "x"), actions=[A("set", "art", "Y")], name="R1"),))
    assert created is not None
    loaded = RuleSetStore(tmp_path / "regelwerke").load()
    assert loaded.problems == [] and loaded.get(created.id) == created
    copy = store.duplicate(created.id)
    assert copy.name == "Energie – Kopie" and copy.id != created.id and copy.rules[0].id != created.rules[0].id
    assert copy.rules[0].conditions == created.rules[0].conditions
    renamed = store.rename(created.id, "Energie 2026")
    assert renamed.id == created.id and store.by_name("energie 2026") is not None
    assert store.update(renamed.with_(active=False)).active is False
    assert store.delete(copy.id) and [r.name for r in RuleSetStore(tmp_path / "regelwerke").load().rule_sets()] == ["Energie 2026"]
    # unvollständige Regeln bleiben gespeichert (der Benutzer sieht sie und kann sie korrigieren)
    broken = store.update(renamed.with_(rules=(regel(C("netto", "gt", "abc"), actions=[A("set", "art", "X")]),)))
    assert RuleSetStore(tmp_path / "regelwerke").load().get(broken.id).rules[0].conditions[0].value == "abc"


def test_rule_set_schema():
    data = werk(regel(actions=[A("set", "art", "X")])).to_dict()
    assert data["schema_version"] == SCHEMA_VERSION and data["rules"][0]["actions"][0] == {"type": "set", "field": "art", "value": "X"}
    with pytest.raises(NewerSchema):
        RuleSet.from_dict({**data, "schema_version": SCHEMA_VERSION + 1})
    for bad in ({**data, "id": "../x"}, {**data, "name": ""}, {**data, "rules": [{"id": "x y"}]}, {**data, "rules": [data["rules"][0], data["rules"][0]]}):
        with pytest.raises(SchemaError):
            RuleSet.from_dict(bad)
    assert not evaluator_for({"schema_version": 99}).active  # ungültiger Auftrag: kein Regelwerk


def test_every_field_has_operators_and_texts():
    for definition in FIELDS:
        assert OPERATORS[definition.type]
    assert {d.key for d in FIELDS} == {"nummer", "art", "beschreibung", "beginn", "zyklus", "netto", "zahlungsart"}
    assert FieldType("number") is FieldType.NUMBER


# --- Leistung -------------------------------------------------------------------------------------------------------


def test_103_many_rules_and_contracts_are_fast():
    contracts = [Vertragsdaten(f"V-{i:04d}", f"SW-Pflege Modul {i % 37} Energieberater" if i % 3 else f"Hotline {i}", "2023-01-15", "", "jeden Monat", 10.0 + i, "Lastschr", i) for i in range(500)]
    rules = werk(*(regel(C("beschreibung", "contains", f"Modul {n}"), C("netto", "gt", str(n)), actions=[A("set", "art", f"Gruppe {n}"), A("suffix", "beschreibung", f" [{n}]")]) for n in range(100)))
    inputs = contract_inputs(contracts)
    start = time.perf_counter()
    result = preview(rules, inputs)
    elapsed = time.perf_counter() - start
    print(f"\n500 Verträge × 100 Regeln: {elapsed * 1000:.0f} ms, {result.affected} Verträge geändert")
    assert result.affected > 0 and elapsed < 3.0
