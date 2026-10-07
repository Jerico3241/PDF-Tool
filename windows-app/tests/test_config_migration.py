"""Einstellungen älterer Versionen (2.2.0 … 2.7.2) → aktuelle Version: schnelle Migrationstests.

Datenmigrationstest ≠ Installer-Upgrade-Test: Ob die App die Daten älterer Versionen versteht,
prüft dieser Test direkt am Python-Code – in wenigen Sekunden, ohne ein altes Setup zu
installieren. Als echter (langsamer) Windows-Setup-Test läuft im normalen Workflow nur noch das
Update von der unmittelbar vorherigen veröffentlichten Version (bei einer Beta auch einer Beta); die
vollständige historische Installer-Prüfung gibt es nur noch manuell (Workflow »Deep Compatibility
Test«).

Fixtures (``tests/fixtures``) – so, wie die jeweilige Version ihre Daten geschrieben hat:

* ``config_v22.json`` – Übersichten-Ersteller 2.2.0: formatierte Kopf-/Fußzeile, Textbausteine
  (mit und ohne Formatierung), Vorlagen, Regeln, Kundenverlauf (``kunden``)
* ``config_v23.json`` – PDF Tool 2.3.0: dazu Einstellungen von »PDF reparieren«
* ``config_v24.json`` – 2.4.0: Kundenakte 2.0 (``kundenakten_v24.json``), Fußzeile nie bewusst
  gespeichert (fehlende Metadaten → Standard-Fußzeile)
* ``config_v25.json`` – 2.5.0: dazu Stapel-Einstellungen und eine aktive Kundenakte
* ``config_v26.json`` – 2.6.0: dazu ein Vertragsstand (``vertragsstand_v26.json``), Fensterlage und
  »Animationen aus« der Tk-Oberfläche
* ``config_v261.json`` – 2.6.1: Kundenakte optional (hier eingeschaltet), »Animationen an«
* ``config_v270.json`` – 2.7.0 (Qt-Oberfläche): so, wie 2.7.0 die 2.6.1-Daten gespeichert hat –
  dazu Animationsprofil und Fensterlage; ohne die Namensregel von »PDF reparieren« (neu in 2.7.1)
* ``config_v272.json`` – 2.7.2: dazu die Namensregel von »PDF reparieren« (2.7.1) und die
  Update-Einstellungen (Kanal Beta bestätigt); Vorlagen noch als Liste in den Einstellungen – 2.8
  übernimmt sie einmalig als Vorlagen 2.0 (je Vorlage eine Datei), die Liste bleibt unverändert
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from conftest import _prepare
from qtutil import Harness

from appstate import DEFAULT_FOOTER, baustein_rich, default_footer_rich
from richtext import FOOTER_ALIGN, FOOTER_STYLE, HEADER_ALIGN, HEADER_STYLE, RichText

FIXTURES = Path(__file__).parent / "fixtures"
VERSIONEN = ["v22", "v23", "v24", "v25", "v26", "v261", "v270", "v272"]
MIT_KUNDENAKTEN = {"v24", "v25", "v26", "v261", "v270", "v272"}
MIT_VERTRAGSSTAND = {"v26", "v261", "v270", "v272"}
KUNDENAKTE_AN = {"v261", "v270", "v272"}  # seit 2.6.1 optional; in diesen Daten eingeschaltet
KUNDE = "6f1c1d2e-0000-4000-8000-000000000024"
STAND = "20260901T100000000000-d35c1e20.json"
# Schlüssel, die die aktuelle Version bewusst ergänzt bzw. vereinheitlicht (alle anderen bleiben gleich):
# die Fußzeile wird immer als bewusst gespeichert samt Formatierung geschrieben (fehlte sie: Standard).
ERGAENZT = {"fusszeile", "fusszeile_format", "fusszeile_explizit"}
# Seit 2.8: Vermerk der einmaligen Übernahme der Vorlagen (Vorlagen 2.0)
NEU_28 = {"vorlagen_2"}


def fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def alt(request, qt_application, config_file: Path, monkeypatch):
    """Daten einer älteren Version im Datenordner, dann die aktuelle App starten (ohne Oberfläche)."""
    name = request.param
    daten = fixture(f"config_{name}.json")
    config_file.write_text(json.dumps(daten, ensure_ascii=False), encoding="utf-8")
    ordner = config_file.parent
    if name in MIT_KUNDENAKTEN:
        shutil.copy(FIXTURES / "kundenakten_v24.json", ordner / "kundenakten.json")
    if name in MIT_VERTRAGSSTAND:
        (ordner / "contract-history" / KUNDE).mkdir(parents=True)
        shutil.copy(FIXTURES / "vertragsstand_v26.json", ordner / "contract-history" / KUNDE / STAND)
    _prepare(config_file, monkeypatch, "full")  # Rückfragen automatisch; die Konfiguration bleibt, wie sie ist
    harness = Harness(ui=False)
    holder = {"current": harness}
    yield name, daten, holder
    holder["current"].close()


def alle(ids=VERSIONEN):
    return pytest.mark.parametrize("alt", ids, indirect=True)


@alle()
def test_old_settings_load_into_current_version(alt) -> None:
    name, daten, holder = alt
    h = holder["current"]
    o = h.overview
    # Kopfzeile samt Formatierung (»Kopf« fett, rot, 10 pt)
    kopf = o.header_rich()
    assert kopf == RichText.from_storage(daten["kopfzeile"], daten["kopfzeile_format"], HEADER_STYLE, HEADER_ALIGN)
    assert kopf.text == "Kopf {kd}" and all(s.bold and s.color == "#B51F1F" and s.size == 10 for s in kopf.styles[:4])
    # Fußzeile: bewusst gespeichert → exakt samt Formatierung; nie gespeichert (2.4-Fixture) → Standard
    if "fusszeile" in daten:
        fuss = RichText.from_storage(daten["fusszeile"], daten["fusszeile_format"], FOOTER_STYLE, FOOTER_ALIGN)
        assert o.footer_rich() == fuss and fuss.aligns == ["center", "center", "right"]
        assert fuss.styles[-1].bold and fuss.styles[-1].italic
    else:
        assert o.footer_rich() == default_footer_rich() and o.footer_text() == DEFAULT_FOOTER
    # Textbausteine: mit Formatierung und ohne (älteres Format → Standardformatierung)
    gruss, ohne = (h.app.state.find_baustein(n) for n in ("Gruß", "Alt ohne Format"))
    assert baustein_rich(gruss).styles[5].bold and not baustein_rich(gruss).styles[0].bold
    assert baustein_rich(ohne) == RichText.plain("Alter Baustein\n\nZweiter Absatz", FOOTER_STYLE, FOOTER_ALIGN)
    assert [v["name"] for v in h.app.state.vorlagen] == ["Quer", "Alt ohne Fußzeile"]
    assert h.app.state.regeln == daten["regeln"]
    # Vorlage mit Kopf-/Fußzeile anwenden: Formatierung aus der Vorlage; ältere Vorlage ohne Fußzeile: Standard
    o.pickVorlage("Quer")
    assert (o.format, o.titel, o.dateiname) == ("quer", "Übersicht quer", "Quer_{kd}.pdf")
    assert o.footer_rich().styles[-1].bold and o.header_rich() == kopf
    o.pickVorlage("Alt ohne Fußzeile")
    assert o.footer_rich() == default_footer_rich()
    # Darstellung und Bedienung
    assert (h.theme.mode, h.theme.accentChoice, h.theme.micaEnabled) == ("dark", "#1F5AA6", False)
    assert h.theme.profile == ("off" if daten.get("animationen") is False else "full")
    assert h.app.cfg.get("nav_kompakt") is True  # seit 3.1.0-beta.4 ohne Seitenleiste: unbenutzt, aber erhalten
    if "reparatur_ausgabe" in daten:
        assert (h.repair.outMode, h.repair.out_dir, h.repair.source_dir) == ("ordner", "C:\\Reparatur", "C:\\Quelle")
    # »PDF reparieren«: die Namensregel ist neu in 2.7.1 – fehlt sie, bleibt es bei »<Name>_repariert.pdf«
    assert h.repair.appendSuffix is True and h.repair.suffix == "_repariert"
    if "stapel_zielordner" in daten:
        s = h.batch.settings
        assert (s.target_dir, s.template, s.subfolders, s.customer_target, s.conflict.value) == ("C:\\Stapel", "Quer", True, False, "skip")
    # Kundenakte: seit 2.6.1 optional – nach einem Update zunächst aus, eingeschaltet bleibt eingeschaltet
    assert h.customers.enabled is (name in KUNDENAKTE_AN)
    if name in KUNDENAKTE_AN:
        assert len(h.customers.customers) == 1 and h.customers.customers.get(KUNDE).company == "Muster GmbH"


@alle()
def test_saving_keeps_old_keys_and_writes_current_schema(alt, config_file: Path) -> None:
    name, daten, holder = alt
    h = holder["current"]
    h.app.persist()  # wie beim Beenden
    gespeichert = json.loads(config_file.read_text(encoding="utf-8"))
    for key, value in daten.items():
        if key in ERGAENZT:
            continue
        if key == "kunde_aktiv" and name not in KUNDENAKTE_AN:
            # wie seit 2.6.1: Ausgeschaltet gibt es keine aktive Kundenakte (Formular bleibt Arbeitskopie,
            # die Kundenakte selbst bleibt unverändert – siehe test_customer_records_and_contract_states_stay_unchanged)
            assert gespeichert.get(key) == ""
            continue
        if value is None:
            assert gespeichert.get(key) is None, key  # »null« und »fehlt« bedeuten dasselbe
        else:
            assert gespeichert.get(key) == value, key  # keine Benutzerdaten verändert oder verloren
    # aktuelles Schema: Fußzeile bewusst gespeichert (auch die Standard-Fußzeile), Formatierung daneben
    assert gespeichert["fusszeile_explizit"] is True
    assert gespeichert["fusszeile"] == daten.get("fusszeile", DEFAULT_FOOTER)
    assert RichText.from_storage(gespeichert["fusszeile"], gespeichert["fusszeile_format"], FOOTER_STYLE, FOOTER_ALIGN) == h.overview.footer_rich()
    assert RichText.from_storage(gespeichert["kopfzeile"], gespeichert["kopfzeile_format"], HEADER_STYLE, HEADER_ALIGN) == h.overview.header_rich()
    assert gespeichert["animationsprofil"] == ("off" if daten.get("animationen") is False else "full")
    assert gespeichert["kundenakte_verwenden"] is (name in KUNDENAKTE_AN)
    assert gespeichert["reparatur_anhaengen"] is True and gespeichert["reparatur_zusatz"] == "_repariert"
    # erneut starten und speichern: dasselbe Ergebnis (die Übernahme ist abgeschlossen)
    h.close()
    zweite = Harness(ui=False)
    holder["current"] = zweite
    zweite.app.persist()
    assert json.loads(config_file.read_text(encoding="utf-8")) == gespeichert


@alle(sorted(MIT_KUNDENAKTEN))
def test_customer_records_and_contract_states_stay_unchanged(alt, config_file: Path) -> None:
    from tools.contract_overview.customers.repository import CustomerStore
    from tools.contract_overview.history.repository import FOLDER, HistoryStore

    name, _daten, holder = alt
    h = holder["current"]
    store = config_file.parent / "kundenakten.json"
    stand = config_file.parent / "contract-history" / KUNDE / STAND
    vorher = sha(store), (sha(stand) if stand.exists() else None)
    h.app.persist()
    h.close()
    holder["current"] = Harness(ui=False)
    assert (sha(store), (sha(stand) if stand.exists() else None)) == vorher  # unverändert
    akten = CustomerStore.load(store)
    assert len(akten) == 1 and akten.get(KUNDE).footer.text == "Kunde Muster\nZeile 2"
    if name in MIT_VERTRAGSSTAND:
        staende = HistoryStore(config_file.parent / FOLDER).snapshots(KUNDE)
        assert len(staende) == 1 and staende[0].contracts[0].contract_number == "10001"
        assert len(list((config_file.parent / FOLDER).rglob("*.json"))) == 1  # kein künstlicher neuer Stand


@alle(["v22", "v23"])
def test_customer_history_is_kept_until_customer_records_are_switched_on(alt, config_file: Path) -> None:
    _name, daten, holder = alt
    h = holder["current"]
    ordner = config_file.parent
    h.app.persist()
    assert not (ordner / "kundenakten.json").exists()  # aus: nichts übernommen, nichts gelöscht
    assert json.loads(config_file.read_text(encoding="utf-8"))["kunden"] == daten["kunden"]
    h.settings.setCustomerRecords(True)  # Einstellungen → Kundenakte verwenden
    h.app.persist()
    from tools.contract_overview.customers.repository import CustomerStore

    akten = CustomerStore.load(ordner / "kundenakten.json")
    muster = next(c for c in akten.all() if c.number == "10042")
    assert muster.company == "Muster GmbH" and muster.emails == ["rechnung@muster.de"]
    assert muster.footer.text == "Kunde Muster\nZeile 2" and RichText.from_storage(muster.footer.text, muster.footer.format, FOOTER_STYLE, FOOTER_ALIGN).styles[0].italic
    alt_ag = next(c for c in akten.all() if c.number == "1")
    assert alt_ag.footer is None  # leere Fußzeile aus der Historie wird keine eigene Fußzeile
    assert len(list((ordner / "sicherungen").glob("gui-config-vor-kundenakte-*.json"))) == 1  # Sicherung davor
    assert "kunden" not in json.loads(config_file.read_text(encoding="utf-8"))


@alle(["v270", "v272"])
def test_templates_become_templates_2_once_and_the_old_list_stays(alt, config_file: Path) -> None:
    """Vorlagen bis 2.7 → Vorlagen 2.0: je Vorlage eine Datei (mit ID), einmalig; die bisherige Liste
    in den Einstellungen bleibt unverändert stehen (eine ältere Version findet sie weiterhin)."""
    from tools.contract_overview.templates.repository import FOLDER, TemplateStore

    name, daten, holder = alt
    h = holder["current"]
    store = h.app.state.templates
    assert sorted(t.name for t in store.templates()) == ["Alt ohne Fußzeile", "Quer"]
    quer = store.by_name("Quer")
    assert (quer.layout.format, quer.layout.titel, quer.header.text, quer.rules.cycle_list()) == ("quer", "Übersicht quer", "Kopf {kd}", [{"enthaelt": "Hott-KI", "zyklus": "jährlich"}])
    assert quer.rules.rule_set_id is None  # ältere Vorlage: legt kein Regelwerk fest
    h.app.persist()
    gespeichert = json.loads(config_file.read_text(encoding="utf-8"))
    assert gespeichert["vorlagen"] == daten["vorlagen"] and gespeichert["vorlagen_2"]
    dateien = sorted((config_file.parent / FOLDER).glob("*.json"))
    assert len(dateien) == 2
    # Zweiter Start: keine zweite Übernahme, gleiche IDs
    h.close()
    zweite = Harness(ui=False)
    holder["current"] = zweite
    assert sorted((config_file.parent / FOLDER).glob("*.json")) == dateien
    assert zweite.app.state.templates.by_name("Quer").id == quer.id
    if name == "v272":
        assert zweite.updates.channel == "beta"  # der Beta-Kanal bleibt nach dem Update gewählt
    assert TemplateStore(config_file.parent / FOLDER).load().problems == []
