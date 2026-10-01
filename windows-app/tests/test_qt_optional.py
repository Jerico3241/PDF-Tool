"""Qt-Oberfläche: optionale Kundenakte und ruhiges Rendering (2.6.1 → 2.7.0).

Ersetzt die Tk-Tests aus test_app_v261:

* Kundenakte optional, Standard aus – auch nach einem Update. Ausgeschaltet: keine Ansichten
  »Kunden« und »Vergleich« (``App.unavailablePages``), kein Abgleich, die Kundenakten werden nicht
  geladen und nichts wird gespeichert. Ein- und Ausschalten wirkt ohne Neustart; gespeicherte Daten
  bleiben immer erhalten, die Ansicht »Kunden« entsteht genau einmal.
* Ruhiges Rendering: Die Vorschau entsteht nicht unnötig neu, ihr Platz steht vor dem ersten Bild,
  Übergänge lassen sich abbrechen, »Reduziert« bewegt nichts, Listen melden nur geänderte Zeilen,
  nach dem Beenden läuft nichts mehr.

Für »Standard aus« schreiben die Tests die Konfiguration selbst, bevor sie die App-Fixture
anfordern (die Fixture schaltet die Kundenakte sonst ein). Nach jedem Test darf die QML-Engine
keine Warnung gemeldet haben.
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

from conftest import neustart, pump, wait_until, write_excel
from qtutil import process_events, qml_type

KUNDE_ID = "6f1c1d2e-0000-4000-8000-000000000024"
FUSS_KUNDE = "Kunde Muster\nZeile 2"
AKTE = {
    "id": KUNDE_ID,
    "company": "Muster GmbH",
    "number": "10042",
    "emails": ["rechnung@muster.de"],
    "note": "Stammkunde",
    "logo": "",
    "target_dir": "",
    "template": "",
    "template_auto": False,
    "header": None,
    "footer": {"text": FUSS_KUNDE},
    "last_excel": "",
    "last_pdf": "",
    "last_used_at": "2026-09-01T10:00:00.000000+02:00",
    "created_at": "2026-08-01T10:00:00.000000+02:00",
    "updated_at": "2026-08-01T10:00:00.000000+02:00",
    "origin": "",
}
KUNDEN_SEITEN = {"customers", "comparison"}
IMMER = ["create", "batch", "layout", "preview", "templates", "rules"]


def seed(config_file: Path, extra: dict | None = None, akten: list[dict] | None = None) -> Path:
    """Benutzerdaten wie nach einem Update von 2.6.0: Einstellungen und (optional) Kundenakten."""
    import appstate

    cfg = {"gesehen": appstate.VERSION, "theme": "light"}
    cfg.update(extra or {})
    config_file.write_text(json.dumps(cfg), encoding="utf-8")
    store = config_file.parent / "kundenakten.json"
    if akten is not None:
        store.write_text(json.dumps({"schema_version": 2, "customers": akten}), encoding="utf-8")
    return store


def start(request):
    """App starten – erst nachdem der Test die Konfiguration geschrieben hat."""
    return request.getfixturevalue("ui_app")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def schalten(h, on: bool) -> None:
    """Schalter »Kundenakte verwenden« in den Einstellungen umlegen (derselbe Slot wie in QML)."""
    h.settings.setCustomerRecords(on)
    pump(0.1)


def excel(path: Path, mail: str = "rechnung@muster.de", number: object = 10042, company: str = "Muster GmbH") -> Path:
    from datetime import datetime

    rows = [
        ["V-1001", datetime(2023, 1, 15), "monatlich", 49.9, "Lastschr", "SW-Pflege Warenwirtschaft", mail, number, company, "Aktiv"],
        ["V-1002", datetime(2022, 6, 1), "jährlich", 120.0, "Überweisung", "Hotline Premium", mail, number, company, "Aktiv"],
    ]
    return write_excel(path, rows)


def pruefen(h, path: Path) -> None:
    h.navigate("create", 0.1)
    h.overview.use_excel(str(path))
    assert wait_until(lambda: h.overview.analysis() is not None and h.overview._analysis_path == str(path), 60)
    pump(0.2)


def exportieren(h, ziel: Path) -> None:
    h.overview.ziel = str(ziel)
    h.overview.pdfOeffnen = False
    h.overview.start_pdf()
    assert wait_until(lambda: not h.overview.busy, 90)
    pump(0.2)
    notice = h.app.notices.get("pdf_info")
    assert notice.severity == "success", notice.message


# QML ---------------------------------------------------------------------------------------------------------------
def alle(root):
    """``root`` und alle Elemente darunter (in der Reihenfolge des Elementbaums)."""
    stack = [root]
    while stack:
        item = stack.pop()
        yield item
        stack.extend(reversed(item.childItems()))


def typ_von(item) -> str:
    """QML-Typ eines Elements (»PInfoBar«, »PCard« …) – siehe ``qtutil.qml_type``."""
    return qml_type(item)


def elemente(root, typ: str) -> list:
    """QML-Elemente eines Typs (z. B. »PInfoBar«) unterhalb von ``root``."""
    return [item for item in alle(root) if typ_von(item) == typ]


def vorfahr(item, typ: str):
    current = item.parentItem()
    while current is not None and typ_von(current) != typ:
        current = current.parentItem()
    return current


def zeiger(item) -> int:
    import shiboken6

    return shiboken6.getCppPointer(item)[0]


def anzahl_elemente(h) -> int:
    return sum(1 for _ in alle(h.window.contentItem()))


def sichtbar(h, name: str) -> bool:
    item = h.item(name)
    assert item is not None, f"QML-Element {name} fehlt"
    return bool(item.property("visible"))


def eintraege(bar) -> list:
    """Einträge einer Ansichtswahl (je Ansicht ein Element mit ``modelData`` und ``available``)."""
    return [item for item in alle(bar) if item.property("modelData") is not None and item.property("available") is not None]


def schluessel(entry) -> str:
    data = entry.property("modelData")
    data = data.toVariant() if hasattr(data, "toVariant") else data
    return data["key"]


def ansichten(h) -> list[list[str]]:
    """Verfügbare Einträge jeder Ansichtswahl (»Übersicht erstellen · Stapel · …«) aller Seiten."""
    return [[schluessel(entry) for entry in eintraege(bar) if entry.property("available")] for bar in elemente(h.window.contentItem(), "ContractViews")]


def infobar(h, page: str, area: str):
    """Die InfoBar einer Seite, die den Hinweisbereich ``area`` zeigt."""
    notice = zeiger(h.app.notices.get(area))
    for bar in elemente(h.item(page), "PInfoBar"):
        shown = bar.property("notice")
        if shown is not None and zeiger(shown) == notice:
            return bar
    raise AssertionError(f"Keine InfoBar für {area} in {page}")


def motion(h):
    """Das QML-Singleton ``Motion`` (Dauern und Bewegungen des Animationsprofils)."""
    return h.engine.singletonInstance("PdfTool.Style", "Motion")


def page_host(h):
    hosts = elemente(h.window.contentItem(), "PageHost")
    assert len(hosts) == 1
    return hosts[0]


# --- Standard: aus ----------------------------------------------------------------------------------------------------


def test_customer_records_are_off_by_default_and_never_loaded(config_file: Path, monkeypatch, request) -> None:
    from qtapp.contracts import customers as customer_module
    from qtapp.contracts.tool import HELP_STEPS_PLAIN
    from tools.contract_overview.customers.repository import CustomerStore

    geladen: list[str] = []
    original_load = CustomerStore.load.__func__

    def open_store(*args, **kwargs):
        geladen.append("open_store")
        raise AssertionError("Kundenakten dürfen ohne Kundenakte nicht geladen werden")

    def load(cls, path):
        geladen.append(str(path))
        return original_load(cls, path)

    monkeypatch.setattr(customer_module, "open_store", open_store)
    monkeypatch.setattr(CustomerStore, "load", classmethod(load))
    seed(config_file)
    h = start(request)
    assert h.customers.enabled is False and h.settings.customerRecords is False
    assert h.customers.customer_records_enabled() is False and h.customers.customers.path is None
    # keine Ansichten »Kunden« und »Vergleich« (nicht nur gesperrt – gar nicht aufgebaut)
    assert set(h.app.unavailablePages) == KUNDEN_SEITEN
    for key in KUNDEN_SEITEN:
        assert h.item(f"page_{key}") is not None and h.item(f"page_{key}").property("item") is None
    assert h.item("customersPage") is None and h.item("comparisonPage") is None
    # kein Eintrag in den Ansichtswahlen
    bars = ansichten(h)
    assert bars and all(keys == IMMER for keys in bars)
    h.navigate("create", 0.3)
    for key in KUNDEN_SEITEN:
        h.navigate(key, 0.1)
        assert h.app.currentPage == "create"
    # »Übersicht erstellen«: keine Kunden-Elemente, die Eingabefelder bleiben
    assert not sichtbar(h, "customerPicker") and not sichtbar(h, "saveCustomer")
    assert not infobar(h, "createPage", "kunde_match").property("visible")
    assert sichtbar(h, "fieldFirma") and sichtbar(h, "fieldKd") and sichtbar(h, "fieldMail")
    assert h.customers.activeId == "" and not h.comparison.visible
    assert "Strg+F" not in h.app.hint
    anfragen = len(h.app.dialogs.history)
    h.app.findAction()  # Strg+F ohne Kundenakte: keine Wirkung
    pump(0.1)
    assert h.app.currentPage == "create" and len(h.app.dialogs.history) == anfragen
    h.app.showHelp()  # Kurzanleitung ohne Kundenakte
    assert h.app.dialogs.history[-1]["data"]["steps"] == list(HELP_STEPS_PLAIN)
    # Einstellungen: Abschnitt »Vertragsübersichten« mit dem Schalter und den Hinweisen
    texts = h.settings.texts
    assert texts["customerTitle"] == "Kundenakte verwenden"
    assert texts["customerText"] == "Speichert Kundendaten lokal und ermöglicht die Wiedererkennung bekannter Rechnungsempfänger."
    assert texts["customerNote"] == "Alle Kundendaten werden ausschließlich lokal auf diesem PC gespeichert."
    h.navigate("settings", 0.3)
    toggle = h.item("customerRecordsToggle")
    assert toggle.property("visible") and toggle.property("checked") is False
    assert geladen == []


def test_update_keeps_customer_data_and_hints_once(config_file: Path, request) -> None:
    from qtapp.contracts.customers import OPTIONAL_HINT

    store = seed(config_file, {"kunde_aktiv": KUNDE_ID, "kunden_sortierung": "company"}, [AKTE])
    vorher = digest(store)
    h = start(request)
    # Update von 2.6.0: Kundenakte aus, Daten unangetastet, einmaliger Hinweis
    assert h.customers.enabled is False and len(h.customers.customers) == 0 and h.customers.active_customer() is None
    notice = h.app.notices.get("kunde_info")
    assert notice.shown and notice.message == OPTIONAL_HINT
    h.navigate("create", 0.3)
    bar = infobar(h, "createPage", "kunde_info")
    assert bar.property("visible") and bar.property("message") == OPTIONAL_HINT
    # sofort gemerkt – auch ohne reguläres Beenden erscheint der Hinweis kein zweites Mal
    assert wait_until(lambda: json.loads(config_file.read_text(encoding="utf-8")).get("kundenakte_hinweis_gezeigt") is True, 5)
    assert digest(store) == vorher
    assert notice.actions == ["Einstellungen öffnen"]
    notice.trigger(0)  # »Einstellungen öffnen«
    pump(0.3)
    assert h.app.currentPage == "settings" and h.customers.enabled is False
    h = neustart(h)
    assert h.app.notices.get("kunde_info").message != OPTIONAL_HINT  # höchstens einmal
    assert h.app.requestClose() is True
    cfg = json.loads(config_file.read_text(encoding="utf-8"))
    assert cfg["kundenakte_verwenden"] is False and cfg["kundenakte_hinweis_gezeigt"] is True
    assert cfg["kunden_sortierung"] == "company"
    assert digest(store) == vorher


def test_no_matching_and_no_saving_without_customer_records(config_file: Path, monkeypatch, request, tmp_path: Path) -> None:
    from tools.contract_overview.customers.repository import CustomerStore

    calls = {"match": 0, "save": 0}
    original_match, original_save = CustomerStore.match, CustomerStore.save

    def match(self, *args, **kwargs):
        calls["match"] += 1
        return original_match(self, *args, **kwargs)

    def save(self, *args, **kwargs):
        calls["save"] += 1
        return original_save(self, *args, **kwargs)

    monkeypatch.setattr(CustomerStore, "match", match)
    monkeypatch.setattr(CustomerStore, "save", save)
    store = seed(config_file, {"kundenakte_hinweis_gezeigt": True}, [AKTE])
    vorher = digest(store)
    h = start(request)
    pruefen(h, excel(tmp_path / "muster.xlsx"))  # Rechnungsempfänger einer vorhandenen Kundenakte
    assert calls["match"] == 0 and h.customers._match is None
    assert not h.app.notices.get("kunde_match").shown and h.customers.active_customer() is None
    assert all(fact["label"] != "Kunde" for fact in h.overview.facts)
    assert not h.comparison.visible  # kein Vertragsvergleich ohne Kundenidentität
    assert h.comparison.single.mode == "none"
    pump(0.3)
    assert not infobar(h, "createPage", "kunde_match").property("visible")
    # Der manuelle Arbeitsablauf bleibt vollständig
    h.overview.firma = "Muster GmbH"
    h.overview.kd = "10042"
    exportieren(h, tmp_path / "out")
    assert list((tmp_path / "out").glob("*.pdf"))
    assert calls["save"] == 0 and calls["match"] == 0 and digest(store) == vorher
    assert not (config_file.parent / "contract-history").exists()
    assert "Kundenakte" not in h.app.notices.get("kunde_info").message  # kein Angebot »Als Kundenakte speichern«


# --- Ein- und Ausschalten ohne Neustart ---------------------------------------------------------------------------


def test_toggle_without_restart_keeps_data_and_builds_the_page_once(config_file: Path, request) -> None:
    from PySide6.QtCore import QMetaObject

    store = seed(config_file, {"kundenakte_hinweis_gezeigt": True}, [AKTE])
    vorher = digest(store)
    h = start(request)
    views = list(h.overview.views)
    assert h.item("page_customers").property("item") is None
    assert all(keys == IMMER for keys in ansichten(h))
    # Schalter in den Einstellungen umlegen (Klick in QML)
    h.navigate("settings", 0.3)
    toggle = h.item("customerRecordsToggle")
    assert QMetaObject.invokeMethod(toggle, "click")
    pump(0.1)
    assert h.customers.enabled and h.settings.customerRecords and toggle.property("checked") is True
    assert h.customers.customer_records_enabled() and len(h.customers.customers) == 1
    assert h.customers.customers.get(KUNDE_ID).company == "Muster GmbH"
    # Die Ansichten erscheinen – »Kunden« entsteht jetzt (im Hintergrund, vor dem ersten Zeigen)
    assert not set(h.app.unavailablePages) & KUNDEN_SEITEN
    # die Einträge blenden ein – auf einem ausgelasteten Rechner nicht zwingend nach 100 ms
    assert wait_until(lambda: all(keys == IMMER + ["comparison", "customers"] for keys in ansichten(h)), 5)
    assert wait_until(lambda: h.item("page_customers").property("item") is not None and h.item("page_comparison").property("item") is not None, 20)
    pump(0.3)
    page = h.item("customersPage")
    h.navigate("customers", 0.3)
    assert h.app.currentPage == "customers" and page.property("visible")
    assert "Strg+F" in h.app.hint
    elemente_vorher = anzahl_elemente(h)
    # AUS → EIN → AUS → EIN: dieselbe Seite, keine doppelten Einträge, nichts wächst
    for on in (False, True, False, True):
        schalten(h, on)
        assert h.customers.enabled is on and toggle.property("checked") is on
        assert (h.app.currentPage == "customers") is False or on
        assert len(h.customers.customers) == (1 if on else 0)
        assert (not set(h.app.unavailablePages) & KUNDEN_SEITEN) is on
        assert all(keys == (IMMER + ["comparison", "customers"] if on else IMMER) for keys in ansichten(h))
        assert ("Strg+F" in h.app.hint) is on
    pump(0.5)
    assert [zeiger(item) for item in h.items("customersPage")] == [zeiger(page)]
    assert len(h.items("page_customers")) == 1 and len(h.items("comparisonPage")) == 1
    assert anzahl_elemente(h) == elemente_vorher
    assert list(h.overview.views) == views
    # Ausschalten in »Vergleich« führt zu »Übersicht erstellen«; das Werkzeug merkt sich keine gesperrte Ansicht
    h.navigate("comparison", 0.3)
    schalten(h, False)
    assert h.app.currentPage == "create"
    schalten(h, True)
    h.navigate("customers", 0.2)
    h.navigate("repair", 0.2)
    schalten(h, False)
    assert h.app.currentPage == "repair"
    h.app.openTool("contracts")
    pump(0.2)
    assert h.app.currentPage == "create"
    schalten(h, True)
    assert digest(store) == vorher  # Schalten schreibt nie in die Kundenakten
    h.app.persist()
    assert json.loads(config_file.read_text(encoding="utf-8"))["kundenakte_verwenden"] is True
    # Ausgeschaltet bleiben die Daten auf dem Datenträger – eingeschaltet sind sie wieder da
    schalten(h, False)
    assert store.is_file() and digest(store) == vorher
    assert json.loads(config_file.read_text(encoding="utf-8"))["kundenakte_verwenden"] is False


def test_toggle_fades_view_entries_without_rebuilding_them(config_file: Path, request) -> None:
    """Die Ansichtswahl blendet »Vergleich« und »Kunden« ein und aus, ohne ihre Einträge neu aufzubauen.

    2.6.1: ``SelectorBar.set_hidden`` blendet »ohne Neuaufbau« aus (keine zusätzlichen Bindungen).
    2.7.0 (PSelectorBar.qml): »Einträge erscheinen und verschwinden weich (Deckkraft + Breite), etwa
    »Kunden« beim Ein- und Ausschalten der Kundenakte« – das setzt voraus, dass die Einträge bestehen bleiben.
    """
    seed(config_file, {"kundenakte_hinweis_gezeigt": True}, [AKTE])
    h = start(request)
    h.navigate("create", 0.3)
    assert h.theme.effectiveProfile == "full"
    bar = elemente(h.item("createPage"), "ContractViews")[0]
    vorher = eintraege(bar)
    assert [schluessel(entry) for entry in vorher] == IMMER + ["comparison", "customers"]
    kunden = vorher[-1]
    assert kunden.property("width") == 0 and not kunden.property("visible")
    h.settings.setCustomerRecords(True)  # Schalter in den Einstellungen
    nachher = eintraege(bar)
    neu_aufgebaut = [zeiger(item) for item in nachher] != [zeiger(item) for item in vorher]
    sofort_voll = nachher[-1].property("opacity") == 1.0 and nachher[-1].property("width") > 1
    assert not neu_aufgebaut and not sofort_voll, (
        f"Ansichtswahl beim Einschalten: Einträge neu aufgebaut: {neu_aufgebaut}, »Kunden« sofort voll sichtbar "
        f"(ohne Überblendung): {sofort_voll}"
    )
    pump(0.5)
    assert kunden.property("visible") and kunden.property("opacity") == 1.0 and kunden.property("width") > 1
    h.settings.setCustomerRecords(False)
    assert [zeiger(item) for item in eintraege(bar)] == [zeiger(item) for item in vorher]
    assert kunden.property("visible")  # blendet noch aus
    pump(0.5)
    assert not kunden.property("visible") and kunden.property("width") == 0


def test_switching_off_keeps_the_standard_footer(config_file: Path, request) -> None:
    from appstate import DEFAULT_FOOTER

    seed(config_file, {"kundenakte_verwenden": True, "kundenakte_hinweis_gezeigt": True}, [AKTE])
    h = start(request)
    assert h.overview.footer_text() == DEFAULT_FOOTER
    h.customers.apply_customer(KUNDE_ID)
    pump(0.1)
    assert h.overview.footer_text() == FUSS_KUNDE and h.customers.active_customer() is not None
    schalten(h, False)
    # Das Formular bleibt als Arbeitskopie – die vorher gültige Fußzeile bleibt gemerkt
    assert h.overview.footer_text() == FUSS_KUNDE and h.customers.active_customer() is None
    h = neustart(h)
    assert h.customers.enabled is False and h.overview.footer_text() == FUSS_KUNDE
    assert json.loads(config_file.read_text(encoding="utf-8"))["kunde_texte_vorher"]["fusszeile"] == DEFAULT_FOOTER
    h.overview.new_overview()
    pump(0.1)
    assert h.overview.footer_text() == DEFAULT_FOOTER  # Standard-Fußzeile für die nächste Übersicht


def test_history_of_23_waits_until_customer_records_are_switched_on(config_file: Path, request) -> None:
    kunden = [{"firmenname": "Muster GmbH", "kundennummer": "10042", "rechnungsempfaenger": "rechnung@muster.de", "fusszeile": "", "kopfzeile": ""}]
    seed(config_file, {"gesehen": "2.3.0", "kunden": kunden})
    h = start(request)
    pump(0.8)  # »Neu in Version« erscheint (nicht blockierend)
    # ausgeschaltet: keine Übernahme, der Kundenverlauf bleibt unverändert in den Einstellungen
    assert not (config_file.parent / "kundenakten.json").exists()
    h.app.persist()
    assert json.loads(config_file.read_text(encoding="utf-8"))["kunden"] == kunden
    schalten(h, True)
    assert [k.label for k in h.customers.customers.all()] == ["Muster GmbH · 10042"]
    assert (config_file.parent / "kundenakten.json").is_file()
    assert list((config_file.parent / "sicherungen").glob("gui-config-vor-kundenakte-*.json"))
    assert "kunden" not in json.loads(config_file.read_text(encoding="utf-8"))


def test_preview_fields_are_identical_with_and_without_customer_records(config_file: Path, request, tmp_path: Path) -> None:
    from tools.contract_overview.preview import signature

    seed(config_file, {"kundenakte_hinweis_gezeigt": True}, [AKTE])
    h = start(request)
    pruefen(h, excel(tmp_path / "liste.xlsx"))
    h.overview.firma = "Muster GmbH"
    h.overview.kd = "10042"
    pump(0.1)
    aus, _grund = h.preview.fields()
    schalten(h, True)
    ein, _grund = h.preview.fields()
    assert aus is not None and signature(aus) == signature(ein)


# --- Stapel ohne Kundenakte ------------------------------------------------------------------------------------------


def test_batch_without_customer_records(config_file: Path, request, tmp_path: Path) -> None:
    from PySide6.QtCore import QMetaObject

    from tools.contract_overview.batch.models import WAITING

    store = seed(config_file, {"kundenakte_hinweis_gezeigt": True}, [AKTE])
    vorher = digest(store)
    h = start(request)
    h.navigate("batch", 0.3)
    h.batch.update_settings(target_dir=str(tmp_path / "out"))
    bekannt = excel(tmp_path / "bekannt.xlsx")  # Rechnungsempfänger einer vorhandenen Kundenakte
    fremd = excel(tmp_path / "fremd.xlsx", mail="info@fremd.de", number=300, company="Fremd GmbH")
    h.batch.add([str(bekannt), str(fremd)])
    assert wait_until(lambda: h.batch.items and all(item.status not in WAITING for item in h.batch.items), 90)
    pump(0.2)
    for item in h.batch.items:
        res = h.batch.resolution(item.id)
        assert item.status.value == "ready" and res.customer is None and res.match is None
        assert h.batch.offer_emails(item.id) == ()
    lines = sorted(row["detail"] for row in h.batch.model.items())
    assert lines == ["Fremd GmbH · 300", "Muster GmbH · 10042"]  # kein »Kunde erkannt«
    assert not h.batch.customerParts
    page = h.item("batchPage")

    def ziel_der_akte_sichtbar() -> bool:
        """»Weitere Einstellungen« des Stapels: »Zielordner der Kundenakte verwenden« nur mit Kundenakte."""
        toggles = {label: [t for t in elemente(page, "PToggle") if t.property("label") == label] for label in ("Unterordner je Kunde", "Zielordner der Kundenakte verwenden")}
        assert all(len(found) == 1 for found in toggles.values())
        assert toggles["Unterordner je Kunde"][0].property("visible")  # der Bereich ist aufgeklappt
        return bool(toggles["Zielordner der Kundenakte verwenden"][0].property("visible"))

    mehr = [button for button in elemente(page, "PButton") if button.property("text") == "Weitere Einstellungen"]
    assert len(mehr) == 1 and QMetaObject.invokeMethod(mehr[0], "clicked")
    pump(0.4)
    assert not ziel_der_akte_sichtbar()
    h.batch.show_detail(h.batch.items[0].id)
    pump(0.3)
    changes_card = vorfahr(elemente(page, "ComparisonHead")[0], "PCard")
    customer_buttons = [button for button in elemente(page, "PButton") if button.property("text") == "Kunden auswählen …"]
    assert not changes_card.property("visible") and customer_buttons and not customer_buttons[0].property("visible")
    fields = [field for field in elemente(page, "PTextField") if field.property("label") in ("Firmenname", "Kundennummer")]
    assert len(fields) == 2 and all(field.property("visible") for field in fields)
    h.batch.show_list()
    h.batch.start_run()
    assert wait_until(lambda: not h.batch.running_now, 180)
    pump(0.2)
    assert [item.status.value for item in h.batch.items] == ["success", "success"]
    assert len(list((tmp_path / "out").glob("*.pdf"))) == 2
    assert digest(store) == vorher and not (config_file.parent / "contract-history").exists()
    assert "Kundenakte" not in h.app.statusText and h.customers._store_warned is False  # keine Warnung zu Kundenakten
    # Eingeschaltet erscheinen die Kunden-Elemente wieder – ohne Neustart
    schalten(h, True)
    h.batch.show_detail(h.batch.items[0].id)
    pump(0.3)
    assert h.batch.customerParts and changes_card.property("visible") and customer_buttons[0].property("visible")
    h.batch.show_list()
    pump(0.4)
    assert ziel_der_akte_sichtbar()


def test_many_customers_are_available_after_switching_on(config_file: Path, request) -> None:
    akten = [dict(AKTE, id=f"00000000-0000-4000-8000-{i:012d}", company=f"Firma {i:03d} GmbH", number=str(20000 + i), emails=[f"rechnung{i}@firma{i}.de"], footer=None) for i in range(500)]
    store = seed(config_file, {"kundenakte_hinweis_gezeigt": True}, akten)
    vorher = digest(store)
    h = start(request)
    assert "customers" in h.app.unavailablePages
    schalten(h, True)
    assert len(h.customers.customers) == 500
    assert wait_until(lambda: h.item("customersPage") is not None, 20)
    h.navigate("customers", 0.3)
    assert h.app.currentPage == "customers"
    listing = elemente(h.item("customersPage"), "PListPage")[0]
    assert listing.property("visible")
    h.customers.search = "Firma 499"
    assert wait_until(lambda: [h.customers.customers.get(key).number for key in h.customers.model.keys()] == ["20499"], 10)
    pump(0.2)
    assert listing.property("count") == 1
    assert digest(store) == vorher


# --- Rendering: vorbereitete Seiten, keine unnötige Arbeit ------------------------------------------------------------


def vorschau_fertig(h) -> bool:
    preview = h.preview
    return preview._doc is not None and preview._building is None and preview._view is None and preview.imageSource != "" and preview.state == "current"


def test_preview_reopen_renders_and_decodes_nothing(config_file: Path, request, tmp_path: Path) -> None:
    seed(config_file)
    h = start(request)
    pruefen(h, excel(tmp_path / "liste.xlsx"))
    h.overview.kd = "10042"
    h.navigate("preview")
    assert wait_until(lambda: vorschau_fertig(h), 60)
    pump(0.2)
    runs, renders = h.preview.runs, h.preview.renders
    status, source = h.preview.stateText, h.preview.imageSource
    for _ in range(3):
        h.navigate("layout", 0.1)
        h.navigate("preview", 0.3)
        # Sichtbarkeit ist keine Änderung: keine neue PDF, kein neues Bild, gleicher Stand
        assert (h.preview.runs, h.preview.renders) == (runs, renders)
        assert h.preview.stateText == status and h.preview.imageSource == source
    # Zoom: nur die Seite wird neu gezeichnet, die PDF nicht neu erzeugt
    h.preview.zoomIn()
    assert wait_until(lambda: vorschau_fertig(h) and h.preview.renders == renders + 1, 30)
    assert h.preview.runs == runs
    # Eine echte Änderung erzeugt die Vorschau neu (entprellt)
    h.overview.titel = "Neuer Titel"
    assert wait_until(lambda: h.preview.runs == runs + 1 and vorschau_fertig(h), 60)


def test_first_preview_reserves_the_page_before_the_image_arrives(config_file: Path, monkeypatch, request, tmp_path: Path) -> None:
    import threading

    from tools.contract_overview import preview as preview_module

    gate = threading.Event()
    original = preview_module.PreviewDocument.render_image

    def langsam(self, index, scale):
        gate.wait(20)
        return original(self, index, scale)

    monkeypatch.setattr(preview_module.PreviewDocument, "render_image", langsam)
    seed(config_file)
    h = start(request)
    try:
        pruefen(h, excel(tmp_path / "liste.xlsx"))
        h.overview.kd = "10042"
        h.navigate("preview")
        assert wait_until(lambda: h.preview._doc is not None and h.preview._view is not None, 60)
        pump(0.3)
        area = h.item("previewArea")
        reserved = area.property("height")
        assert h.preview.imageSource == "" and area.property("visible")
        assert h.preview.pageHeight > 400 and reserved > 400  # Platz der Seite steht, bevor das Bild da ist
        gate.set()
        assert wait_until(lambda: vorschau_fertig(h), 30)
        pump(0.3)
        assert abs(area.property("height") - reserved) <= 2  # kein Layoutsprung beim Eintreffen
    finally:
        gate.set()


def test_first_preview_keeps_page_and_toolbar_in_place_while_the_pdf_is_built(config_file: Path, monkeypatch, request, tmp_path: Path) -> None:
    import threading

    from PySide6.QtCore import QPointF

    from tools.contract_overview import preview as preview_module

    gate = threading.Event()
    original = preview_module.PreviewDocument.build.__func__

    def langsam(cls, fields):
        gate.wait(20)
        return original(cls, fields)

    monkeypatch.setattr(preview_module.PreviewDocument, "build", classmethod(langsam))
    seed(config_file)
    h = start(request)
    try:
        pruefen(h, excel(tmp_path / "liste.xlsx"))
        h.overview.kd = "10042"
        h.navigate("preview", 0.4)
        assert h.preview._doc is None and h.preview._building is not None  # die PDF entsteht noch
        page = h.item("previewPage")
        area = h.item("previewArea")
        reserved = area.property("height")
        assert area.property("visible") and reserved > 600  # A4 an Breite: der Platz steht schon, bevor es die PDF gibt

        def lage() -> dict:
            buttons = [item for item in elemente(page, "PIconButton") + elemente(page, "PButton") if item.property("visible")]
            places = {}
            for item in buttons:
                point = item.mapToScene(QPointF(0, 0))
                places[zeiger(item)] = (round(point.x()), round(point.y()))
            return places

        places = lage()
        top = area.mapToScene(QPointF(0, 0)).y()
        assert places
        gate.set()
        assert wait_until(lambda: vorschau_fertig(h), 60)
        pump(0.3)
        # »Seite 1 von 1« statt »Seite –« und ein anderer Zustandstext verschieben nichts
        height, now_top, now_places = area.property("height"), area.mapToScene(QPointF(0, 0)).y(), lage()
        assert abs(height - reserved) <= 2 and now_top == top and now_places == places, (
            f"Layoutsprung beim Eintreffen der ersten Vorschau: Höhe {reserved:.0f} → {height:.0f} px, "
            f"Oberkante {top:.0f} → {now_top:.0f} px, Werkzeugleiste unverändert: {now_places == places}"
        )
    finally:
        gate.set()


def test_failed_first_preview_leaves_no_empty_page(config_file: Path, monkeypatch, request, tmp_path: Path) -> None:
    from tools.contract_overview import preview as preview_module

    def kaputt(cls, fields):
        raise RuntimeError("Testfehler")

    monkeypatch.setattr(preview_module.PreviewDocument, "build", classmethod(kaputt))
    seed(config_file)
    h = start(request)
    pruefen(h, excel(tmp_path / "liste.xlsx"))
    h.navigate("preview")
    assert wait_until(lambda: h.preview.state == "error", 30)
    pump(0.4)
    notice = h.app.notices.get("preview_info")
    assert notice.shown and notice.severity == "error" and "Testfehler" in notice.message
    # der vorab freigehaltene Platz verschwindet mit der Fehlermeldung – kein leerer Seitenrahmen
    assert h.preview.pageWidth == 0 and h.preview.pageHeight == 0
    assert not sichtbar(h, "previewArea")
    assert infobar(h, "previewPage", "preview_info").property("visible")


def test_fast_navigation_keeps_only_the_latest_transition(config_file: Path, request) -> None:
    seed(config_file)
    h = start(request)
    assert h.theme.effectiveProfile == "full"
    host = page_host(h)
    zwischen = ("layout", "preview", "batch")
    for key in ("create", "layout", "preview", "batch", "create"):
        h.app.navigate(key)  # ohne Pause – nur das letzte Ziel zählt
    gezeigt: set[str] = set()
    end = time.monotonic() + 1.5
    while time.monotonic() < end:
        process_events(2)
        for key in zwischen:
            slot = h.item(f"page_{key}")
            if slot.property("visible"):
                gezeigt.add(key)
        if not host.property("transitioning") and host.property("shownKey") == "create" and time.monotonic() > end - 1.0:
            break
        time.sleep(0.002)
    assert gezeigt == set()  # keine Warteschlange alter Übergänge: Zwischenziele erscheinen nie
    assert wait_until(lambda: not host.property("transitioning"), 5)
    assert h.app.currentPage == "create" and host.property("shownKey") == "create"
    visible = [key for key in h.PAGES if h.item(f"page_{key}") is not None and h.item(f"page_{key}").property("visible")]
    assert visible == ["create"]
    slot = h.item("page_create")
    assert slot.property("opacity") == 1.0
    assert slot.mapToItem(host, 0, 0).y() == 0  # keine Verschiebung bleibt stehen


def test_reduced_motion_switches_pages_without_movement(config_file: Path, request) -> None:
    from PySide6.QtCore import QPointF

    seed(config_file)
    h = start(request)
    host = page_host(h)

    def verschiebung(target: str) -> float:
        """Größte senkrechte Verschiebung der Zielseite während des Seitenwechsels."""
        h.app.navigate(target)
        slot = h.item(f"page_{target}")
        largest = 0.0
        end = time.monotonic() + 0.6
        while time.monotonic() < end:
            process_events(1)
            largest = max(largest, abs(slot.mapToItem(host, QPointF(0, 0)).y()))
            time.sleep(0.002)
        assert wait_until(lambda: not host.property("transitioning"), 5)
        return largest

    # Vollständig: die neue Seite gleitet ein (Gegenprobe für die Messung)
    assert h.theme.effectiveProfile == "full" and motion(h).property("pageShift") > 0
    assert verschiebung("layout") > 0.5
    # Reduziert (Windows: »Animationseffekte« aus bzw. Einstellung »Reduziert«): keine Bewegung
    h.settings.setProfile("reduced")
    pump(0.1)
    assert h.theme.effectiveProfile == "reduced"
    m = motion(h)
    assert m.property("pageShift") == 0 and m.property("moves") is False
    assert m.property("enabled") is True and m.property("fade") > 0  # dezente Überblendungen bleiben
    assert m.property("expand") == 0 and m.property("infoBar") == 0 and m.property("infoBarShift") == 0
    assert verschiebung("create") == 0
    assert h.app.currentPage == "create" and h.item("page_create").property("visible")
    # Aus: Zustände wechseln sofort – kein Übergang, keine Bewegung
    h.settings.setProfile("off")
    pump(0.1)
    assert h.theme.effectiveProfile == "off"
    m = motion(h)
    assert m.property("enabled") is False and m.property("pageShift") == 0 and m.property("pageIn") == 0
    h.app.navigate("layout")
    assert h.item("page_layout").property("visible") and not host.property("transitioning")  # ohne Ereignisschleife: schon gezeigt
    assert not h.item("page_create").property("visible")
    assert verschiebung("create") == 0
    h.settings.setProfile("reduced")
    pump(0.1)
    # Ein-/Ausklappen eines Hinweises ohne Bewegung: die volle Höhe steht sofort
    bar = infobar(h, "createPage", "kunde_info")
    h.app.hide_notice("kunde_info", animate=False)
    pump(0.3)
    h.app.notify("kunde_info", "info", "Test")
    assert bar.property("implicitHeight") == bar.property("barHeight") > 0
    # Gegenprobe »Vollständig«: dieselbe InfoBar klappt mit Höhenanimation auf
    h.settings.setProfile("full")
    h.app.hide_notice("kunde_info", animate=False)
    pump(0.3)
    h.app.notify("kunde_info", "info", "Test 2")
    assert bar.property("implicitHeight") < bar.property("barHeight")
    pump(0.4)
    assert bar.property("implicitHeight") == bar.property("barHeight")


def test_prepare_runs_while_the_page_is_still_hidden(config_file: Path, monkeypatch, request) -> None:
    seed(config_file)
    h = start(request)
    assert h.app.currentPage == "home"
    seen = []
    original = h.contracts.page_prepare

    def prepare(page: str) -> None:
        seen.append((page, h.app.currentPage, bool(h.item(f"page_{page}").property("visible"))))
        original(page)

    monkeypatch.setattr(h.contracts, "page_prepare", prepare)
    h.navigate("layout", 0.4)
    assert seen == [("layout", "home", False)]  # erst verdeckt vorbereitet, dann gezeigt
    assert h.item("page_layout").property("visible")
    h.navigate("preview", 0.4)
    assert seen[-1] == ("preview", "layout", False)
    assert h.item("page_preview").property("visible")


def test_navigation_does_not_repeat_excel_checks(config_file: Path, monkeypatch, request, tmp_path: Path) -> None:
    import engine

    seed(config_file)
    h = start(request)
    pruefen(h, excel(tmp_path / "liste.xlsx"))
    calls = []
    original = engine.pruefe_excel
    monkeypatch.setattr(engine, "pruefe_excel", lambda *a, **k: (calls.append(a), original(*a, **k))[1])
    for key in ("layout", "preview", "batch", "create", "layout", "create"):
        h.navigate(key, 0.1)
    pump(0.3)
    assert calls == []  # derselbe Pfad, dieselbe Datei: die vorhandene Analyse gilt


def test_comparison_is_only_recalculated_after_real_changes(config_file: Path, request, tmp_path: Path) -> None:
    from datetime import datetime

    seed(config_file, {"kundenakte_verwenden": True, "kundenakte_hinweis_gezeigt": True}, [AKTE])
    h = start(request)
    pruefen(h, excel(tmp_path / "stand1.xlsx"))
    h.customers.apply_customer(KUNDE_ID)
    exportieren(h, tmp_path / "out")  # erster Stand
    rows = [[f"V-{2000 + i}", datetime(2024, 1, 1), "jährlich", 10.0 + i, "Lastschr", f"Modul {i}", "rechnung@muster.de", 10042, "Muster GmbH", "Aktiv"] for i in range(300)]
    pruefen(h, write_excel(tmp_path / "stand2.xlsx", rows))  # großer Vertragsbestand
    h.customers.apply_customer(KUNDE_ID)
    assert wait_until(lambda: h.comparison.comparison is not None, 10)
    pump(0.2)
    runs = h.comparison.runs
    resets = h.comparison.single.changeModel.resets
    for _ in range(3):
        h.customers.refresh_line()
        h.navigate("layout", 0.1)
        h.navigate("comparison", 0.1)
        h.navigate("create", 0.1)
    assert h.comparison.runs == runs  # Öffnen, Autosave, Ansichtswechsel: keine neue Berechnung
    assert h.comparison.single.changeModel.resets == resets
    h.overview.firma = "Muster GmbH & Co. KG"  # Eingabe ohne Einfluss auf die Verträge
    pump(1.0)
    assert h.comparison.runs == runs
    h.app.state.regeln.append({"enthaelt": "Modul 1", "zyklus": "monatlich"})
    h.overview.recheck_excel()  # andere Regeln → neue Analyse → neuer Vergleich
    assert wait_until(lambda: h.comparison.runs == runs + 1, 30)


def test_batch_status_update_redraws_only_the_changed_row(config_file: Path, request, tmp_path: Path) -> None:
    import shutil

    from tools.contract_overview.batch.models import WAITING

    seed(config_file)
    h = start(request)
    vorlage = excel(tmp_path / "vorlage.xlsx", mail="info@stapel.de", number=500, company="Stapel GmbH")
    folder = tmp_path / "stapel"
    folder.mkdir()
    files = []
    for i in range(100):
        target = folder / f"liste_{i:03d}.xlsx"
        shutil.copyfile(vorlage, target)
        files.append(str(target))
    h.navigate("batch", 0.2)
    h.batch.add(files)
    assert wait_until(lambda: len(h.batch.items) == 100 and all(item.status not in WAITING for item in h.batch.items), 180)
    pump(0.5)
    model = h.batch.model
    assert model.rowCount() == 100
    resets = model.resets
    changed: list[tuple[int, int, list]] = []
    structure: list[str] = []
    model.dataChanged.connect(lambda top, bottom, roles: changed.append((top.row(), bottom.row(), list(roles))))
    model.modelReset.connect(lambda: structure.append("reset"))
    model.rowsInserted.connect(lambda *_a: structure.append("insert"))
    model.rowsRemoved.connect(lambda *_a: structure.append("remove"))
    model.rowsMoved.connect(lambda *_a: structure.append("move"))
    h.batch.select(h.batch.items[42].id, True)  # Statusänderung eines Eintrags
    pump(0.3)
    names = {int(role): bytes(name).decode() for role, name in model.roleNames().items()}
    assert changed, "keine Zeile aktualisiert"
    assert all(top == bottom == 42 for top, bottom, _roles in changed)  # nur diese Zeile, nicht 100 Zeilen
    assert {names[role] for _top, _bottom, roles in changed for role in roles} == {"selected"}
    assert structure == [] and model.resets == resets
    assert model.get(42)["selected"] is True and h.batch.selection == 1


def test_hidden_spinner_does_not_animate(config_file: Path, monkeypatch, request, tmp_path: Path) -> None:
    """Der Fortschrittsring der Vorschau dreht sich nur, solange er zu sehen ist."""
    import threading

    from tools.contract_overview import preview as preview_module

    gate = threading.Event()
    original = preview_module.PreviewDocument.build.__func__

    def langsam(cls, fields):
        gate.wait(20)
        return original(cls, fields)

    monkeypatch.setattr(preview_module.PreviewDocument, "build", classmethod(langsam))
    seed(config_file)
    h = start(request)
    try:
        rings = elemente(h.item("previewPage"), "PProgressRing")
        assert rings
        assert not any(ring.property("active") for ring in rings)  # abgelegte Seite: nichts dreht sich
        h.navigate("preview", 0.4)
        assert h.preview.state == "empty"
        assert not any(ring.property("active") for ring in rings)  # ohne Vorschau ist die Zustandszeile verborgen
        pruefen(h, excel(tmp_path / "liste.xlsx"))
        h.overview.kd = "10042"
        h.navigate("preview", 0.4)
        assert h.preview.state == "busy"
        assert any(ring.property("active") for ring in rings)  # die Vorschau entsteht: Ring sichtbar und aktiv
        h.navigate("layout", 0.4)
        assert not any(ring.property("active") for ring in rings)  # Seite verlassen: steht wieder
        gate.set()
        h.navigate("preview")
        assert wait_until(lambda: vorschau_fertig(h), 60)
        pump(0.3)
        assert not any(ring.property("active") for ring in rings)
    finally:
        gate.set()


def test_closing_leaves_no_pending_callbacks(config_file: Path, request) -> None:
    seed(config_file)
    h = start(request)
    h.app.schedule_save()
    h.app.timers.later("test:spaeter", 60000, lambda: None)
    assert h.app.timers.count() >= 2
    assert h.app.requestClose() is True
    assert h.app.timers.count() == 0
    assert h.app.worker._closed and not h.app.worker.busy()  # Ergebnisse verfallen, nichts läuft weiter
    assert not h.repair._poll.isActive()
    h.app.timers.later("test:danach", 0, lambda: None)  # nach dem Beenden wird nichts mehr geplant
    assert h.app.timers.count() == 0


def test_toggle_stress_keeps_one_page_and_no_extra_bindings(config_file: Path, monkeypatch, request) -> None:
    from qtapp.contracts import customers as customer_module

    geladen = []
    original = customer_module.open_store

    def open_store(*args, **kwargs):
        geladen.append(True)
        return original(*args, **kwargs)

    monkeypatch.setattr(customer_module, "open_store", open_store)
    seed(config_file, {"kundenakte_hinweis_gezeigt": True}, [AKTE])
    h = start(request)
    schalten(h, True)
    assert wait_until(lambda: h.item("customersPage") is not None and h.item("comparisonPage") is not None, 20)
    pump(0.5)
    page = h.item("customersPage")
    elemente_vorher = anzahl_elemente(h)
    timers = h.app.timers.count()
    for _ in range(10):
        schalten(h, False)
        schalten(h, True)
    pump(0.6)
    assert geladen == [True]  # Kundenakten genau einmal geladen
    assert [zeiger(item) for item in h.items("customersPage")] == [zeiger(page)]  # »Kunden« genau einmal aufgebaut
    assert len(h.items("comparisonPage")) == 1 and len(h.items("page_customers")) == 1
    assert anzahl_elemente(h) == elemente_vorher  # keine wachsenden Elemente
    assert h.app.timers.count() <= timers
    assert len(h.customers.customers) == 1
