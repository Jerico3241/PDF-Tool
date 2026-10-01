"""Vorlagen und Regelwerk in der PDF-Pipeline (Teil der Tests 41, 42 und 96 der Vorgabe).

* Das Regelwerk wirkt auf die Werte der PDF – nie auf die Excel-Datei.
* Der gespeicherte Vertragsstand hält genau die exportierten Werte fest (kein Vergleich zwischen
  Rohdaten und PDF-Werten).
* Stapel: jeder Eintrag verwendet seine geltende Vorlage samt Regelwerk – oder eine bewusste
  Angabe im Eintrag; ein fehlendes Regelwerk wird nie still ersetzt.
* Vorrang der Vorlagen im Stapel: Eintrag → Kundenakte → Stapel → Standardvorlage → Darstellung.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

import appstate
import engine
from tools.contract_overview.batch import resolver
from tools.contract_overview.batch.models import BatchSettings, Overrides
from tools.contract_overview.customers.repository import FILE_NAME, CustomerStore
from tools.contract_overview.history.models import records_from
from tools.contract_overview.rules.models import Action, Condition, Rule, RuleSet, new_id

from test_batch import analysed, defaults, liste, pdf_text

pypdf = pytest.importorskip("pypdf")


def regelwerk(name: str = "Support", wert: str = "Support") -> RuleSet:
    """Verträge »Vertrag 1« werden zu »Support«, die Zahlungsart erhält einen Zusatz."""
    rule = Rule(
        id=new_id(),
        name="Erster Vertrag",
        conditions=(Condition("beschreibung", "equals", "Vertrag 1"),),
        actions=(Action("set", "art", wert), Action("suffix", "zahlungsart", " (geprüft)")),
    )
    return RuleSet(id=new_id(), name=name, rules=(rule,))


LOGO = appstate.DEFAULT_LOGO


class Templates:
    """Vorlagen per ID (ab 2.8) und per Name (bis 2.7)."""

    def __init__(self, *entries: dict) -> None:
        self.entries = {}
        for entry in entries:
            self.entries[entry["name"]] = entry
            if entry.get("id"):
                self.entries[entry["id"]] = entry

    def __call__(self, ref: str) -> dict | None:
        return self.entries.get(ref)


class RuleSets:
    def __init__(self, *sets: RuleSet) -> None:
        self.sets = {rule_set.id: rule_set for rule_set in sets}

    def __call__(self, ref: str) -> dict | None:
        rule_set = self.sets.get(ref)
        return rule_set.to_dict() if rule_set is not None else None


def test_41_pdf_shows_rule_results_and_the_excel_stays_unchanged(tmp_path: Path) -> None:
    excel = liste(tmp_path / "a.xlsx")
    vorher = hashlib.sha256(excel.read_bytes()).hexdigest()
    ohne = engine.erstelle_pdf(engine.PdfAuftrag(excel=excel, logo=LOGO, kundennummer="1", zielordner=tmp_path / "ohne"))
    auftrag = engine.PdfAuftrag(excel=excel, logo=LOGO, kundennummer="1", zielordner=tmp_path / "mit", regelwerk=regelwerk().to_dict())
    mit = engine.erstelle_pdf(auftrag)
    text_ohne, text_mit = " ".join(pdf_text(ohne).split()), " ".join(pdf_text(mit).split())
    assert "Support" not in text_ohne and "Support" in text_mit
    assert "Sofort (geprüft)" in text_mit and text_mit.count("(geprüft)") == 1  # nur »Vertrag 1«
    assert hashlib.sha256(excel.read_bytes()).hexdigest() == vorher  # die Excel bleibt unverändert
    # Der Vertragsstand hält genau die Werte der PDF fest
    records = records_from(auftrag.vertraege, auftrag.regeln, auftrag.regelwerk)
    first = next(r for r in records if r.description == "Vertrag 1")
    assert (first.contract_type, first.payment_method) == ("Support", "Sofort (geprüft)")
    assert first.raw["zahlungsart"] == "Sofort"  # Rohwert bleibt daneben erhalten
    plain = records_from(auftrag.vertraege, auftrag.regeln)
    assert next(r for r in plain if r.description == "Vertrag 1").contract_type == "Softwarepflegevertrag"


def test_inactive_or_invalid_rule_set_changes_nothing(tmp_path: Path) -> None:
    excel = liste(tmp_path / "a.xlsx")
    rule_set = regelwerk().with_(active=False)
    pdf = engine.erstelle_pdf(engine.PdfAuftrag(excel=excel, logo=LOGO, kundennummer="1", zielordner=tmp_path, regelwerk=rule_set.to_dict()))
    assert "Support" not in pdf_text(pdf)
    assert engine.auswerter({"schema_version": 999}) is None and engine.auswerter(None) is None


def test_rule_values_are_escaped_in_the_pdf(tmp_path: Path) -> None:
    excel = liste(tmp_path / "a.xlsx")
    rule_set = regelwerk(wert="<b>Support & Co</b>")
    pdf = engine.erstelle_pdf(engine.PdfAuftrag(excel=excel, logo=LOGO, kundennummer="1", zielordner=tmp_path, regelwerk=rule_set.to_dict()))
    assert "<b>Support & Co</b>" in " ".join(pdf_text(pdf).split())  # Text, nie Markup


# --- Stapel -------------------------------------------------------------------------------------------


def test_41_batch_item_uses_the_rule_set_of_its_template(tmp_path: Path) -> None:
    rule_set = regelwerk("Energie")
    other = regelwerk("Anderes", "Anders")
    templates = Templates({"id": "t-1", "name": "Mit Regeln", "format": "quer", "regelwerk": rule_set.id}, {"id": "t-2", "name": "Ohne Regeln", "regelwerk": ""}, {"id": "t-3", "name": "Alt"})
    find = RuleSets(rule_set, other)
    settings = BatchSettings(target_dir=str(tmp_path / "out"))
    store = CustomerStore(tmp_path / FILE_NAME)
    item = analysed(liste(tmp_path / "a.xlsx", nummer="1"), overrides=Overrides(company="A", template="Mit Regeln"))

    def run(**default_changes):
        return resolver.resolve(item, store, templates, settings, defaults(**default_changes), find_rule_set=find)

    res = run(regelwerk=other.to_dict(), regelwerk_name="Anderes")
    assert res.fields["regelwerk"]["id"] == rule_set.id and res.rule_set == "Energie" and res.rule_set_source == "Vorlage „Mit Regeln“"
    item.overrides.template = "Ohne Regeln"  # Vorlage legt bewusst kein Regelwerk fest
    res = run(regelwerk=other.to_dict(), regelwerk_name="Anderes")
    assert res.fields["regelwerk"] is None and res.rule_set == ""
    item.overrides.template = "Alt"  # ältere Vorlage ohne Angabe: Regelwerk der Darstellung
    res = run(regelwerk=other.to_dict(), regelwerk_name="Anderes")
    assert res.fields["regelwerk"]["id"] == other.id and res.rule_set_source == resolver.SOURCE_DEFAULT
    item.overrides.rule_set = rule_set.id  # bewusst im Eintrag gewählt
    assert run(regelwerk=other.to_dict()).fields["regelwerk"]["id"] == rule_set.id
    item.overrides.rule_set = ""  # bewusst keines
    assert run(regelwerk=other.to_dict()).fields["regelwerk"] is None


def test_missing_rule_sets_are_never_silently_replaced(tmp_path: Path) -> None:
    settings = BatchSettings(target_dir=str(tmp_path / "out"))
    store = CustomerStore(tmp_path / FILE_NAME)
    templates = Templates({"id": "t-1", "name": "Vorlage", "regelwerk": "gibt-es-nicht"})
    item = analysed(liste(tmp_path / "a.xlsx", nummer="1"), overrides=Overrides(company="A", rule_set="weg"))
    res = resolver.resolve(item, store, templates, settings, defaults(), find_rule_set=RuleSets())
    assert [issue.code for issue in res.issues] == ["rule_set_missing"] and not res.ready
    assert resolver.resolve(item, store, templates, settings, defaults(), for_preview=True, find_rule_set=RuleSets()).fields is None
    item.overrides.rule_set = None
    item.overrides.template = "Vorlage"  # Regelwerk der Vorlage fehlt: Hinweis, keines (wie im Einzelmodus)
    other = regelwerk("Darstellung")
    res = resolver.resolve(item, store, templates, settings, defaults(regelwerk=other.to_dict(), regelwerk_name="Darstellung"), find_rule_set=RuleSets(other))
    assert res.ready and any("Regelwerk der Vorlage" in note for note in res.notes)
    assert res.fields["regelwerk"] is None and res.rule_set == ""


def test_batch_pdf_and_snapshot_values_follow_the_rule_set(tmp_path: Path) -> None:
    from tools.contract_overview.batch import processor

    rule_set = regelwerk()
    settings = BatchSettings(target_dir=str(tmp_path / "out"))
    item = analysed(liste(tmp_path / "a.xlsx", nummer="77"), overrides=Overrides(company="A", rule_set=rule_set.id))
    res = resolver.resolve(item, CustomerStore(tmp_path / FILE_NAME), Templates(), settings, defaults(), find_rule_set=RuleSets(rule_set))
    job = processor.Job(item.id, "A", item.path, item.stamp, processor.identity_of(item.analysis), res.fields, res.folder, settings.conflict, frozenset())
    result = processor.run_job(job, lambda: False)
    assert result.output and "Support" in pdf_text(Path(result.output))
    assert next(r for r in result.contracts if r.description == "Vertrag 1").contract_type == "Support"


def test_default_template_is_the_fourth_level(tmp_path: Path) -> None:
    templates = Templates({"id": "std", "name": "Standard", "format": "quer"}, {"id": "stapel", "name": "Stapel"})
    settings = BatchSettings(target_dir=str(tmp_path / "out"))
    store = CustomerStore(tmp_path / FILE_NAME)
    item = analysed(liste(tmp_path / "a.xlsx", nummer="1"), overrides=Overrides(company="A"))
    res = resolver.resolve(item, store, templates, settings, defaults(vorlage_standard="std"))
    assert (res.template, res.template_source, res.fields["seitenformat"]) == ("Standard", resolver.SOURCE_DEFAULT_TEMPLATE, "quer")
    settings.template = "stapel"  # Vorlage des Stapels hat Vorrang vor der Standardvorlage
    assert resolver.resolve(item, store, templates, settings, defaults(vorlage_standard="std")).template == "Stapel"
    settings.template = ""
    item.overrides.template = ""  # bewusst keine Vorlage: auch keine Standardvorlage
    res = resolver.resolve(item, store, templates, settings, defaults(vorlage_standard="std"))
    assert res.template == "" and res.fields["seitenformat"] == "hoch"
    item.overrides.template = None
    gone = resolver.resolve(item, store, templates, settings, defaults(vorlage_standard="weg"))
    assert gone.template == "" and any("Standardvorlage" in note for note in gone.notes)  # Hinweis, kein Fehler
