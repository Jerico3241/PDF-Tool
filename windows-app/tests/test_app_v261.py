"""Oberflächentests für Version 2.6.1: optionale Kundenakte (Standard aus – auch nach einem Update,
Ein- und Ausschalten ohne Neustart, kein Abgleich und kein Speichern ohne Kundenakte, gespeicherte
Daten bleiben immer erhalten) und ruhiges Rendering (Seiten entstehen einmal, die Vorschau wird
nicht unnötig neu erzeugt, Übergänge lassen sich abbrechen)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from conftest import display_available, neustart, pump, schliessen, wait_until, write_excel

pytestmark = pytest.mark.skipif(not display_available(), reason="kein Display verfügbar")

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


def start(monkeypatch):
    monkeypatch.setenv("UE_NO_ANIMATIONS", "1")
    from ui import dialogs

    monkeypatch.setattr(dialogs, "AUTO_ANSWER", "primary")
    import vertragdesk

    app = vertragdesk.App()
    app.ctx.anim.enabled = False
    pump(app, 0.3)
    return app


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def schalten(app, on: bool) -> None:
    """Schalter »Kundenakte verwenden« in den Einstellungen umlegen."""
    app.var_customer_records.set(on)
    app.apply_customer_records_setting()
    pump(app, 0.1)


def excel(path: Path, mail: str = "rechnung@muster.de", number: object = 10042, company: str = "Muster GmbH") -> Path:
    from datetime import datetime

    rows = [
        ["V-1001", datetime(2023, 1, 15), "monatlich", 49.9, "Lastschr", "SW-Pflege Warenwirtschaft", mail, number, company, "Aktiv"],
        ["V-1002", datetime(2022, 6, 1), "jährlich", 120.0, "Überweisung", "Hotline Premium", mail, number, company, "Aktiv"],
    ]
    return write_excel(path, rows)


def pruefen(app, path: Path) -> None:
    app.nav.navigate("create", animate=False)
    app.use_excel(str(path))
    assert wait_until(app, lambda: app._analysis is not None and app._analysis_path == str(path), 60)
    pump(app, 0.2)


def exportieren(app, ziel: Path) -> None:
    app.var_ziel.set(str(ziel))
    app.var_open.set(False)
    app.start_pdf()
    assert wait_until(app, lambda: not app.busy, 90)
    pump(app, 0.2)
    assert app.ui.pdf_info.severity == "success", app.ui.pdf_info.message


# --- Standard: aus ----------------------------------------------------------------------------------------------------


def test_customer_records_are_off_by_default_and_never_loaded(config_file: Path, monkeypatch) -> None:
    from tools.contract_overview import customer_flow
    from ui.pages import settings

    def verboten(*_args, **_kwargs):
        raise AssertionError("Kundenakten dürfen ohne Kundenakte nicht geladen werden")

    monkeypatch.setattr(customer_flow, "open_store", verboten)
    seed(config_file)
    app = start(monkeypatch)
    try:
        assert app.customer_records_enabled() is False and app.var_customer_records.get() is False
        # keine Ansicht »Kunden« (nicht nur gesperrt – gar nicht aufgebaut), kein Eintrag in den Auswahlleisten
        assert "customers" not in app.nav.pages and app.customer_page is None
        for view in ("create", "batch", "layout", "preview"):
            assert getattr(app.ui, f"selector_{view}").hidden == {"customers"}
        app.nav.navigate("create", animate=False)
        app.nav.navigate("customers", animate=False)
        assert app.nav.current == "create"
        # »Übersicht erstellen«: keine Kunden-Elemente, die Eingabefelder bleiben
        assert not app.ui.kunde_picker_row.winfo_manager() and not app.ui.kunde_save_row.winfo_manager()
        assert not app.ui.kunde_match.winfo_manager() and not app.ui.kunde_active_area.expanded
        assert app.ui.field_firma.winfo_manager() and app.ui.field_kd.winfo_manager() and app.ui.field_mail.winfo_manager()
        assert "Strg+F" not in app.nav.status.hint_text
        app._find_action()  # Strg+F ohne Kundenakte: keine Wirkung
        pump(app, 0.1)
        assert app.nav.current == "create"
        # Einstellungen: Abschnitt »Vertragsübersichten« mit dem Schalter und den Hinweisen
        card = app.ui.customer_records_card
        assert card.title.cget("text") == "Kundenakte verwenden" == settings.CUSTOMER_RECORDS_TITLE
        assert card.description.cget("text") == "Speichert Kundendaten lokal und ermöglicht die Wiedererkennung bekannter Rechnungsempfänger."
        assert settings.CUSTOMER_RECORDS_NOTE == "Alle Kundendaten werden ausschließlich lokal auf diesem PC gespeichert."
        assert app.ui.customer_records_toggle.var is app.var_customer_records
    finally:
        schliessen(app)


def test_update_keeps_customer_data_and_hints_once(config_file: Path, monkeypatch) -> None:
    from tools.contract_overview.customer_flow import OPTIONAL_HINT

    store = seed(config_file, {"kunde_aktiv": KUNDE_ID, "kunden_sortierung": "company"}, [AKTE])
    vorher = digest(store)
    app = start(monkeypatch)
    try:
        # Update von 2.6.0: Kundenakte aus, Daten unangetastet, einmaliger Hinweis
        assert app.customer_records_enabled() is False and len(app.customers) == 0 and app.active_customer() is None
        assert app.ui.kunde_info.message == OPTIONAL_HINT
        app = neustart(app)
        assert app.ui.kunde_info.message != OPTIONAL_HINT  # höchstens einmal
        app._on_close()
        cfg = json.loads(config_file.read_text(encoding="utf-8"))
        assert cfg["kundenakte_verwenden"] is False and cfg["kundenakte_hinweis_gezeigt"] is True
        assert cfg["kunden_sortierung"] == "company"
        assert digest(store) == vorher
    finally:
        schliessen(app)


def test_no_matching_and_no_saving_without_customer_records(config_file: Path, monkeypatch, tmp_path: Path) -> None:
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
    app = start(monkeypatch)
    try:
        pruefen(app, excel(tmp_path / "muster.xlsx"))  # Rechnungsempfänger einer vorhandenen Kundenakte
        assert calls["match"] == 0 and app._match is None
        assert not app.ui.kunde_match.winfo_manager() and app.active_customer() is None
        assert all(label != "Kunde" for label, _v, _t in app._excel_facts())
        assert not app.ui.comparison_area.expanded  # kein Vertragsvergleich ohne Kundenidentität
        # Der manuelle Arbeitsablauf bleibt vollständig
        app.var_firma.set("Muster GmbH")
        app.var_kd.set("10042")
        exportieren(app, tmp_path / "out")
        assert list((tmp_path / "out").glob("*.pdf"))
        assert calls["save"] == 0 and calls["match"] == 0 and digest(store) == vorher
        assert not (config_file.parent / "contract-history").exists()
        assert "Kundenakte" not in app.ui.kunde_info.message  # kein Angebot »Als Kundenakte speichern«
    finally:
        schliessen(app)


# --- Ein- und Ausschalten ohne Neustart ---------------------------------------------------------------------------


def test_toggle_without_restart_keeps_data_and_builds_the_page_once(config_file: Path, monkeypatch) -> None:
    store = seed(config_file, {"kundenakte_hinweis_gezeigt": True}, [AKTE])
    vorher = digest(store)
    app = start(monkeypatch)
    try:
        bindings = {sequence: app.bind_all(sequence) for sequence in ("<Control-f>", "<Control-o>", "<Control-Return>")}
        nav_items = len(app.nav.items)
        views = list(app.ui.selector_create.items)
        schalten(app, True)
        page = app.nav.pages["customers"]
        customer_page = app.customer_page
        assert app.customer_records_enabled() and len(app.customers) == 1 and app.customers.get(KUNDE_ID).company == "Muster GmbH"
        app.nav.navigate("customers", animate=False)
        pump(app, 0.1)
        assert app.nav.current == "customers" and app.ui.selector_create.hidden == frozenset()
        assert "Strg+F" in app.nav.status.hint_text
        # AUS → EIN → AUS → EIN: dieselbe Seite, keine doppelten Einträge, keine zusätzlichen Bindungen
        for on in (False, True, False, True):
            schalten(app, on)
            assert app.customer_records_enabled() is on
            assert (app.nav.current == "customers") is False or on
            assert len(app.customers) == (1 if on else 0)
        assert app.nav.pages["customers"] is page and app.customer_page is customer_page
        assert list(app.nav.pages).count("customers") == 1 and len(app.nav.items) == nav_items
        assert list(app.ui.selector_create.items) == views
        assert {sequence: app.bind_all(sequence) for sequence in bindings} == bindings
        assert digest(store) == vorher  # Schalten schreibt nie in die Kundenakten
        app.persist()
        assert json.loads(config_file.read_text(encoding="utf-8"))["kundenakte_verwenden"] is True
        # Ausgeschaltet bleiben die Daten auf dem Datenträger – eingeschaltet sind sie wieder da
        schalten(app, False)
        assert store.is_file() and digest(store) == vorher
    finally:
        schliessen(app)


def test_switching_off_keeps_the_standard_footer(config_file: Path, monkeypatch) -> None:
    from appstate import DEFAULT_FOOTER

    seed(config_file, {"kundenakte_verwenden": True, "kundenakte_hinweis_gezeigt": True}, [AKTE])
    app = start(monkeypatch)
    try:
        assert app.ui.txt_fuss.get() == DEFAULT_FOOTER
        app.apply_customer(KUNDE_ID)
        pump(app, 0.1)
        assert app.ui.txt_fuss.get() == FUSS_KUNDE and app.active_customer() is not None
        schalten(app, False)
        # Das Formular bleibt als Arbeitskopie – die vorher gültige Fußzeile bleibt gemerkt
        assert app.ui.txt_fuss.get() == FUSS_KUNDE and app.active_customer() is None
        app = neustart(app)
        assert app.customer_records_enabled() is False and app.ui.txt_fuss.get() == FUSS_KUNDE
        assert json.loads(config_file.read_text(encoding="utf-8"))["kunde_texte_vorher"]["fusszeile"] == DEFAULT_FOOTER
        app.new_overview()
        pump(app, 0.1)
        assert app.ui.txt_fuss.get() == DEFAULT_FOOTER  # Standard-Fußzeile für die nächste Übersicht
    finally:
        schliessen(app)


def test_history_of_23_waits_until_customer_records_are_switched_on(config_file: Path, monkeypatch) -> None:
    kunden = [{"firmenname": "Muster GmbH", "kundennummer": "10042", "rechnungsempfaenger": "rechnung@muster.de", "fusszeile": "", "kopfzeile": ""}]
    seed(config_file, {"gesehen": "2.3.0", "kunden": kunden})
    app = start(monkeypatch)
    try:
        pump(app, 0.8)  # »Neu in Version« schließt sich im Test selbst
        # ausgeschaltet: keine Übernahme, der Kundenverlauf bleibt unverändert in den Einstellungen
        assert not (config_file.parent / "kundenakten.json").exists()
        app.persist()
        assert json.loads(config_file.read_text(encoding="utf-8"))["kunden"] == kunden
        schalten(app, True)
        assert [k.label for k in app.customers.all()] == ["Muster GmbH · 10042"]
        assert (config_file.parent / "kundenakten.json").is_file()
        assert list((config_file.parent / "sicherungen").glob("gui-config-vor-kundenakte-*.json"))
        assert "kunden" not in json.loads(config_file.read_text(encoding="utf-8"))
    finally:
        schliessen(app)


def test_preview_fields_are_identical_with_and_without_customer_records(config_file: Path, monkeypatch, tmp_path: Path) -> None:
    from tools.contract_overview.preview import signature

    seed(config_file, {"kundenakte_hinweis_gezeigt": True}, [AKTE])
    app = start(monkeypatch)
    try:
        pruefen(app, excel(tmp_path / "liste.xlsx"))
        app.var_firma.set("Muster GmbH")
        app.var_kd.set("10042")
        pump(app, 0.1)
        aus, _grund = app._preview_fields()
        schalten(app, True)
        ein, _grund = app._preview_fields()
        assert aus is not None and signature(aus) == signature(ein)
    finally:
        schliessen(app)


# --- Stapel ohne Kundenakte ------------------------------------------------------------------------------------------


def test_batch_without_customer_records(config_file: Path, monkeypatch, tmp_path: Path) -> None:
    from tools.contract_overview.batch.models import WAITING

    store = seed(config_file, {"kundenakte_hinweis_gezeigt": True}, [AKTE])
    vorher = digest(store)
    app = start(monkeypatch)
    try:
        app.nav.navigate("batch", animate=False)
        pump(app, 0.2)
        app.batch_update_settings(target_dir=str(tmp_path / "out"))
        bekannt = excel(tmp_path / "bekannt.xlsx")  # Rechnungsempfänger einer vorhandenen Kundenakte
        fremd = excel(tmp_path / "fremd.xlsx", mail="info@fremd.de", number=300, company="Fremd GmbH")
        app.batch_add([str(bekannt), str(fremd)])
        assert wait_until(app, lambda: app.batch_items and all(item.status not in WAITING for item in app.batch_items), 90)
        pump(app, 0.2)
        for item in app.batch_items:
            res = app.batch_resolution(item.id)
            assert item.status.value == "ready" and res.customer is None and res.match is None
            assert app.batch_offer_emails(item.id) == ()
        lines = sorted(row.detail for row in app.ui.batch_list.rows)
        assert lines == ["Fremd GmbH · 300", "Muster GmbH · 10042"]  # kein »Kunde erkannt«
        page = app.batch_page
        page.show_detail(app.batch_items[0].id)
        pump(app, 0.2)
        assert not page.d_customer_part.winfo_manager() and not page.d_changes_card.winfo_manager()
        assert page.field_company.winfo_manager() and page.field_number.winfo_manager()
        assert not page.setting_rows["customer_target"].winfo_manager()
        page.show_list()
        app.batch_start()
        assert wait_until(app, lambda: not app.batch_running, 180)
        pump(app, 0.2)
        assert [item.status.value for item in app.batch_items] == ["success", "success"]
        assert len(list((tmp_path / "out").glob("*.pdf"))) == 2
        assert digest(store) == vorher and not (config_file.parent / "contract-history").exists()
        assert "Kundenakte" not in app.nav.status.text and app._store_warned is False  # keine Warnung zu Kundenakten
        # Eingeschaltet erscheinen die Kunden-Elemente wieder – ohne Neustart
        schalten(app, True)
        page.show_detail(app.batch_items[0].id)
        pump(app, 0.2)
        assert page.d_customer_part.winfo_manager() and page.d_changes_card.winfo_manager()
    finally:
        schliessen(app)


def test_many_customers_are_available_after_switching_on(config_file: Path, monkeypatch) -> None:
    akten = [dict(AKTE, id=f"00000000-0000-4000-8000-{i:012d}", company=f"Firma {i:03d} GmbH", number=str(20000 + i), emails=[f"rechnung{i}@firma{i}.de"], footer=None) for i in range(500)]
    store = seed(config_file, {"kundenakte_hinweis_gezeigt": True}, akten)
    vorher = digest(store)
    app = start(monkeypatch)
    try:
        assert "customers" not in app.nav.pages
        schalten(app, True)
        assert len(app.customers) == 500
        app.nav.navigate("customers", animate=False)
        pump(app, 0.3)
        assert app.nav.current == "customers"
        app.customer_page.var_search.set("Firma 499")
        assert wait_until(app, lambda: [c.number for c in app.customer_page.listing.items] == ["20499"], 10)
        assert digest(store) == vorher
    finally:
        schliessen(app)
