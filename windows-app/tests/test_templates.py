"""Vorlagen 2.0 (Test 95 der Vorgabe): Modell, Ablage, Migration und Vorrang – ohne Oberfläche.

* neue Vorlage, speichern, laden (über die Dateien), umbenennen, duplizieren, löschen
* Kopf-/Fußzeile mit Formatierung, Logo, Darstellung und Regel-Verweis bleiben erhalten
* Vorlagen bis 2.7 werden einmalig übernommen und wirken beim Anwenden exakt wie vorher
* beschädigte oder neuere Dateien betreffen nur sich selbst
* Vorrang: Eintrag → Kundenakte → Stapel → Standardvorlage → keine
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from appstate import DEFAULT_FOOTER, footer_rich_from, header_rich_from
from richtext import FOOTER_ALIGN, FOOTER_STYLE, HEADER_ALIGN, HEADER_STYLE, RichText
from storage import NewerSchema, SchemaError
from tools.contract_overview.overview import template_layout, template_rules
from tools.contract_overview.templates import migration
from tools.contract_overview.templates.models import SCHEMA_VERSION, Template, TemplateLayout, TemplateRichText, TemplateRuleReference
from tools.contract_overview.templates.priority import SOURCE_BATCH, SOURCE_CUSTOMER, SOURCE_DEFAULT, SOURCE_ITEM, Level, choose
from tools.contract_overview.templates.repository import TemplateStore


def formatiert(text: str, kopf: bool) -> RichText:
    """Text, dessen erstes Wort fett und rot ist (Formatierung muss erhalten bleiben)."""
    style, align = (HEADER_STYLE, HEADER_ALIGN) if kopf else (FOOTER_STYLE, FOOTER_ALIGN)
    first = len(text.split(" ")[0])
    styles = [style.with_(bold=True, color="#B51F1F")] * first + [style] * (len(text) - first)
    return RichText(text, styles, None, style, align)


def vollstaendig(store: TemplateStore, name: str = "Standard Energie") -> Template:
    template = store.create(
        name,
        layout=TemplateLayout(format="quer", logo="C:/Logos/energie.png", logo_breite="48", titel="Übersicht", untertitel="Energie", dateiname="VU_{kd}_{datum}.pdf"),
        header=TemplateRichText.of(formatiert("Kunde {kd} · {firma}", True)),
        footer=TemplateRichText.of(formatiert("Stand {datum}\nAlle Preise netto", False)),
        rules=TemplateRuleReference(cycle_rules=(("Hott-KI", "jährlich"),), rule_set_id="7f1c2d3e-0000-4000-8000-000000000001"),
        description="Für Energieberater",
    )
    assert template is not None
    return template


# --- neu, speichern, laden ---------------------------------------------------------------------------


def test_95_new_template_is_saved_as_its_own_file_and_loads_completely(tmp_path):
    store = TemplateStore(tmp_path / "vorlagen")
    template = vollstaendig(store)
    path = tmp_path / "vorlagen" / f"{template.id}.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["schema_version"] == SCHEMA_VERSION and data["id"] == template.id and data["name"] == "Standard Energie"
    assert not [p for p in path.parent.iterdir() if p.suffix == ".tmp"]  # atomar: keine Reste

    loaded = TemplateStore(tmp_path / "vorlagen").load()
    assert loaded.problems == [] and len(loaded) == 1
    again = loaded.get(template.id)
    assert again == template  # alles erhalten: Darstellung, Texte, Regel-Verweis, Metadaten
    assert again.layout.logo == "C:/Logos/energie.png" and again.layout.format == "quer" and again.layout.dateiname == "VU_{kd}_{datum}.pdf"
    assert again.header.rich(True) == formatiert("Kunde {kd} · {firma}", True)  # Rich Text samt Formatierung
    assert again.footer.rich(False) == formatiert("Stand {datum}\nAlle Preise netto", False)
    assert again.rules.rule_set_id == "7f1c2d3e-0000-4000-8000-000000000001"
    assert again.rules.cycle_list() == [{"enthaelt": "Hott-KI", "zyklus": "jährlich"}]
    assert again.meta.description == "Für Energieberater"


def test_95_entry_of_a_template_keeps_the_known_shape(tmp_path):
    template = vollstaendig(TemplateStore(tmp_path))
    entry = template.to_entry()
    assert entry["id"] == template.id and entry["name"] == template.name and entry["regelwerk"] == template.rules.rule_set_id
    assert template_layout(entry) == {"format": "quer", "dateiname": "VU_{kd}_{datum}.pdf", "logo_breite": "48", "titel": "Übersicht", "untertitel": "Energie"}  # Logo-Datei fehlt
    assert header_rich_from(entry) == formatiert("Kunde {kd} · {firma}", True)
    assert footer_rich_from(entry) == formatiert("Stand {datum}\nAlle Preise netto", False)
    assert template_rules(entry) == [{"enthaelt": "Hott-KI", "zyklus": "jährlich"}]
    again = Template.from_entry(entry)  # zurück aus dem Wörterbuch: dieselbe Vorlage (ID, Name, Beschreibung, Inhalt)
    assert again.with_meta(created_at=template.meta.created_at, updated_at=template.meta.updated_at) == template


def test_95_rename_keeps_id_and_file(tmp_path):
    store = TemplateStore(tmp_path)
    template = vollstaendig(store)
    renamed = store.rename(template.id, "  Energie   neu ")
    assert renamed.id == template.id and renamed.name == "Energie neu"
    assert renamed.meta.updated_at >= template.meta.updated_at
    assert sorted(p.name for p in tmp_path.glob("*.json")) == [f"{template.id}.json"]
    assert TemplateStore(tmp_path).load().get(template.id).name == "Energie neu"


def test_95_duplicate_gets_new_id_and_copy_name(tmp_path):
    store = TemplateStore(tmp_path)
    template = vollstaendig(store)
    copy = store.duplicate(template.id)
    second = store.duplicate(template.id)
    assert copy.id != template.id and second.id not in (template.id, copy.id)
    assert copy.name == "Standard Energie – Kopie" and second.name == "Standard Energie – Kopie 2"
    assert copy.layout == template.layout and copy.header == template.header and copy.rules == template.rules
    assert len(TemplateStore(tmp_path).load()) == 3


def test_95_delete_removes_only_this_template(tmp_path):
    store = TemplateStore(tmp_path)
    keep = vollstaendig(store, "Bleibt")
    gone = vollstaendig(store, "Weg")
    assert store.delete(gone.id) and not store.delete(gone.id)
    assert [t.name for t in TemplateStore(tmp_path).load().templates()] == ["Bleibt"] and store.get(keep.id)


def test_95_names_are_unique_without_case(tmp_path):
    store = TemplateStore(tmp_path)
    vollstaendig(store, "Energie")
    assert store.name_taken("energie") and store.name_taken(" ENERGIE ")
    assert store.unique_name("energie") == "energie 2"
    assert store.find("Energie") is store.find("energie") is not None  # Verweis per Name (bis 2.7)
    assert store.find(store.find("Energie").id).name == "Energie"  # Verweis per ID (ab 2.8)


def test_95_recent_order_and_alphabetical_order(tmp_path):
    store = TemplateStore(tmp_path)
    for name in ("B", "a", "C"):
        vollstaendig(store, name)
    assert [t.name for t in store.templates()] == ["a", "B", "C"]
    assert [t.name for t in store.recent()] == ["C", "a", "B"]


# --- Fehler betreffen nur die eine Datei -------------------------------------------------------------------


def test_93_damaged_or_newer_template_does_not_break_the_others(tmp_path):
    store = TemplateStore(tmp_path)
    good = vollstaendig(store, "Gut")
    (tmp_path / "11111111-1111-4111-8111-111111111111.json").write_text("{ kaputt", encoding="utf-8")
    newer = {**good.to_dict(), "id": "22222222-2222-4222-8222-222222222222", "schema_version": SCHEMA_VERSION + 1}
    (tmp_path / "22222222-2222-4222-8222-222222222222.json").write_text(json.dumps(newer), encoding="utf-8")
    (tmp_path / "33333333-3333-4333-8333-333333333333.json").write_text(json.dumps(good.to_dict()), encoding="utf-8")  # falscher Dateiname
    loaded = TemplateStore(tmp_path).load()
    assert [t.name for t in loaded.templates()] == ["Gut"]
    reasons = {problem.file: problem for problem in loaded.problems}
    assert "beschädigt" in reasons["11111111-1111-4111-8111-111111111111.json"].reason
    assert reasons["22222222-2222-4222-8222-222222222222.json"].newer
    assert "Dateiname" in reasons["33333333-3333-4333-8333-333333333333.json"].reason
    assert (tmp_path / "11111111-1111-4111-8111-111111111111.json").read_text(encoding="utf-8") == "{ kaputt"  # nie gelöscht


def test_schema_checks():
    with pytest.raises(NewerSchema):
        Template.from_dict({"schema_version": SCHEMA_VERSION + 1, "id": "a", "name": "x"})
    for data in ({}, {"schema_version": 1, "name": "x"}, {"schema_version": 1, "id": "../x", "name": "x"}, {"schema_version": 1, "id": "a1", "name": "  "}, []):
        with pytest.raises(SchemaError):
            Template.from_dict(data)


def test_write_error_leaves_store_unchanged(tmp_path):
    blocker = tmp_path / "vorlagen"
    blocker.write_text("kein Ordner", encoding="utf-8")
    store = TemplateStore(blocker)
    assert store.create("Neu") is None and len(store) == 0 and "nicht gespeichert" in store.last_error


# --- Übernahme der Vorlagen bis 2.7 -----------------------------------------------------------------------


ALT = [
    {
        "name": "Quer",
        "format": "quer",
        "titel": "Titel Quer",
        "logo_breite": 50,
        "kopfzeile": "Kopf {kd}",
        "kopfzeile_format": formatiert("Kopf {kd}", True).to_dict(),
        "fusszeile": "Fuß eigen",
        "fusszeile_format": formatiert("Fuß eigen", False).to_dict(),
        "fusszeile_explizit": True,
        "regeln": [{"enthaelt": "Hott-KI", "zyklus": "jährlich"}],
    },
    {"name": "Alt ohne Fußzeile", "titel": "Alt"},
    {"name": "Alt leer", "fusszeile": ""},
    {"name": "Alt null", "fusszeile": None, "regeln": "kaputt"},
    {"name": "  "},  # ohne Namen: wird ignoriert (wie bisher)
    "kein Eintrag",
]


def test_95_legacy_templates_are_migrated_once_and_apply_exactly_as_before(tmp_path):
    cfg = {"vorlagen": [dict(e) if isinstance(e, dict) else e for e in ALT]}
    store = TemplateStore(tmp_path)
    assert migration.needs_migration(cfg)
    created, errors = migration.migrate(store, cfg, "2.8.0-beta.1")
    assert (created, errors) == (4, []) and cfg[migration.MIGRATED_KEY] == "2.8.0-beta.1"
    assert cfg["vorlagen"][0]["name"] == "Quer"  # die bisherige Liste bleibt unverändert stehen
    # Reihenfolge wie bisher: zuletzt gespeicherte zuerst
    assert [t.name for t in TemplateStore(tmp_path).load().recent()] == ["Quer", "Alt ohne Fußzeile", "Alt leer", "Alt null"]
    for alt in ALT[:4]:
        template = store.by_name(alt["name"])
        entry = template.to_entry()
        # Anwenden ergibt dasselbe wie mit der Vorlage aus 2.7
        assert template_layout(entry) == template_layout(alt)
        assert header_rich_from(entry) == header_rich_from(alt)
        assert footer_rich_from(entry) == footer_rich_from(alt)
        assert template_rules(entry) == template_rules(alt)
        assert template.rules.rule_set_id is None  # Regelwerk nicht festgelegt: das aktuelle bleibt
    assert footer_rich_from(store.by_name("Alt leer").to_entry()).text == DEFAULT_FOOTER
    # Zweiter Start: nichts doppelt, auch wenn Vorlagen inzwischen gelöscht wurden
    store.delete(store.by_name("Alt null").id)
    assert migration.migrate(store, cfg, "2.8.0") == (0, []) and not migration.needs_migration(cfg)
    assert len(store) == 3


def test_interrupted_migration_continues_without_duplicates(tmp_path):
    cfg = {"vorlagen": [{"name": "A"}, {"name": "B"}]}
    store = TemplateStore(tmp_path)
    store.put(Template.from_entry({"name": "A"}))  # erster Versuch kam bis »A«
    created, errors = migration.migrate(store, cfg, "2.8.0")
    assert (created, errors) == (1, []) and sorted(t.name for t in store.templates()) == ["A", "B"]


def test_failed_migration_is_retried(tmp_path):
    blocker = tmp_path / "vorlagen"
    blocker.write_text("x", encoding="utf-8")
    cfg = {"vorlagen": [{"name": "A"}]}
    created, errors = migration.migrate(TemplateStore(blocker), cfg, "2.8.0")
    assert created == 0 and errors and migration.MIGRATED_KEY not in cfg
    blocker.unlink()
    assert migration.migrate(TemplateStore(blocker), cfg, "2.8.0") == (1, [])


# --- Vorrang ------------------------------------------------------------------------------------------------


def finder(*entries):
    by_ref = {}
    for entry in entries:
        by_ref[entry["id"]] = entry
        by_ref[entry["name"]] = entry
    return by_ref.get


def test_template_priority():
    eintrag, kunde, stapel, standard = ({"id": f"{i}", "name": name} for i, name in enumerate(("Eintrag", "Kunde", "Stapel", "Standard")))
    find = finder(eintrag, kunde, stapel, standard)

    def levels(item=None, customer=None, batch=None, default=None):
        return [Level(item, SOURCE_ITEM, strict=True), Level(customer, SOURCE_CUSTOMER), Level(batch, SOURCE_BATCH), Level(default, SOURCE_DEFAULT)]

    assert choose(levels("0", "1", "2", "3"), find).entry is eintrag  # explizite Auswahl zuerst
    assert choose(levels(None, "1", "2", "3"), find).source == SOURCE_CUSTOMER
    assert choose(levels(None, None, "2", "3"), find).entry is stapel
    assert choose(levels(None, None, None, "3"), find).source == SOURCE_DEFAULT
    nothing = choose(levels(), find)
    assert nothing.entry is None and nothing.source == ""  # globale Standardwerte
    none = choose(levels("", "1", "2", "3"), find)  # bewusst keine Vorlage
    assert none.entry is None and none.source == SOURCE_ITEM and not none.blocked
    gone = choose(levels(None, "weg", None, "Standard"), find)  # Vorlage der Kundenakte gelöscht
    assert gone.entry is standard and gone.missing == [("weg", SOURCE_CUSTOMER)]
    strict = choose(levels("weg", "1"), find)  # bewusst gewählt und fehlt: nie still ersetzen
    assert strict.blocked and strict.entry is None and strict.missing == [("weg", SOURCE_ITEM)]
    assert choose(levels(None, "Kunde"), find).entry is kunde  # Verweis per Name (bis 2.7)


def test_many_templates_load_fast(tmp_path):
    import time

    store = TemplateStore(tmp_path)
    for index in range(100):
        vollstaendig(store, f"Vorlage {index:03d}")
    start = time.perf_counter()
    loaded = TemplateStore(tmp_path).load()
    elapsed = time.perf_counter() - start
    print(f"\n100 Vorlagen laden: {elapsed * 1000:.0f} ms")
    assert len(loaded) == 100 and loaded.problems == [] and elapsed < 2.0
