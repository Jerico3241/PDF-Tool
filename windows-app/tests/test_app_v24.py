"""Oberflächentests für Version 2.4: Kundenakte 2.0, Wiedererkennung per E-Mail, Ansicht »Kunden«
und Live-Vorschau – samt Übernahme der Kundenhistorie aus 2.3."""

from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path

import pytest

from conftest import display_available, neustart, pump, schliessen, wait_until, write_excel

pytestmark = pytest.mark.skipif(not display_available(), reason="kein Display verfügbar")


@pytest.fixture
def kunden_app(config_file: Path, monkeypatch):
    """App ohne Animationen; Dialoge antworten mit der Hauptschaltfläche."""
    import appstate

    config_file.write_text(json.dumps({"gesehen": appstate.VERSION, "theme": "light"}), encoding="utf-8")
    monkeypatch.setenv("UE_NO_ANIMATIONS", "1")
    from ui import dialogs

    monkeypatch.setattr(dialogs, "AUTO_ANSWER", "primary")
    import vertragdesk

    instance = vertragdesk.App()
    instance.ctx.anim.enabled = False
    pump(instance, 0.3)
    yield instance
    schliessen(instance)


def liste(tmp_path: Path, name: str, mails, kd="10042", firma="Muster GmbH", rows: int = 3) -> Path:
    """Excel-Liste mit den angegebenen Rechnungsempfängern (reihum auf die Zeilen verteilt)."""
    mails = list(mails) or [""]
    daten = []
    for index in range(max(rows, len(mails))):
        daten.append([f"V-{index + 1}", datetime(2023, 1, 1 + index % 28), "monatlich", 10.0 + index, "Lastschr", f"Modul {index + 1}", mails[index % len(mails)], kd, firma, "Aktiv"])
    return write_excel(tmp_path / name, daten)


def pruefen(app, path: Path) -> None:
    """Excel wählen und die Prüfung abwarten."""
    app.nav.navigate("create", animate=False)
    app.use_excel(str(path))
    assert wait_until(app, lambda: app._analysis is not None and app._analysis_path == str(path), 60)
    pump(app, 0.1)


def aktionen(bar) -> dict:
    return {child.text(): child for child in bar._actions.winfo_children() if hasattr(child, "text")}


def klicken(bar, text: str) -> None:
    aktionen(bar)[text].invoke()


# --- Wiedererkennung ------------------------------------------------------------------------------


def test_unknown_customer_is_normal_and_never_blocks(kunden_app, tmp_path: Path) -> None:
    app = kunden_app
    app.var_ziel.set(str(tmp_path))
    app.var_open.set(False)
    pruefen(app, liste(tmp_path, "neu.xlsx", ["rechnung@unbekannt.de"]))
    assert app._match.kind.value == "no_match"
    assert not app.ui.kunde_match.visible() and app.ui.info_excel.severity == "success"
    # Nichts erfunden: Firma und Kundennummer nur aus den Spalten der Datei, nie aus der Domain
    assert app.var_firma.get() == "Muster GmbH" and app.var_kd.get() == "10042"
    app.start_pdf()
    assert wait_until(app, lambda: not app.busy, 90)
    assert app.ui.pdf_info.severity == "success"
    assert len(app.customers) == 0  # keine Kundenakte ohne bewusste Entscheidung


def test_domain_is_never_turned_into_a_company(kunden_app, tmp_path: Path) -> None:
    app = kunden_app
    pruefen(app, liste(tmp_path, "ohne.xlsx", ["rechnung@mueller-gmbh.de"], kd="", firma=""))
    assert app.var_firma.get() == "" and app.var_kd.get() == ""
    assert "Müller" not in app.ui.kunde_match.message


def test_single_match_offers_the_customer_without_applying(kunden_app, tmp_path: Path) -> None:
    app = kunden_app
    kunde = app.customers.create("Beispiel GmbH", "123456", ["Rechnung@Kunde.de"])
    assert app.var_auto_customer.get() is False  # Standard: aus
    pruefen(app, liste(tmp_path, "a.xlsx", ["  rechnung@KUNDE.de "], kd="", firma=""))
    bar = app.ui.kunde_match
    assert app._match.kind.value == "single_match" and app._match.customer_id == kunde.id
    assert bar.visible() and bar.title == "Bekannter Kunde gefunden" and "Beispiel GmbH · 123456" in bar.message
    assert list(aktionen(bar)) == ["Übernehmen", "Kundenakte", "Ignorieren"]
    assert app.active_customer() is None and app.var_firma.get() == ""
    klicken(bar, "Übernehmen")
    assert app.active_customer() is kunde
    assert app.var_firma.get() == "Beispiel GmbH" and app.var_kd.get() == "123456"
    assert app.ui.kunde_active_title.cget("text") == "Kunde: Beispiel GmbH · 123456"
    assert kunde.last_excel.endswith("a.xlsx") and kunde.last_used_at  # automatische Metadaten


def test_ignore_hides_the_offer_for_this_excel(kunden_app, tmp_path: Path) -> None:
    app = kunden_app
    app.customers.create("Beispiel GmbH", "1", ["r@kunde.de"])
    datei = liste(tmp_path, "a.xlsx", ["r@kunde.de"])
    pruefen(app, datei)
    klicken(app.ui.kunde_match, "Ignorieren")
    assert not app.ui.kunde_match.visible()
    pruefen(app, datei)  # erneute Prüfung derselben Datei (z. B. neue Regel)
    assert not app.ui.kunde_match.visible() and app.active_customer() is None


def test_open_record_from_the_offer(kunden_app, tmp_path: Path) -> None:
    app = kunden_app
    kunde = app.customers.create("Beispiel GmbH", "1", ["r@kunde.de"])
    pruefen(app, liste(tmp_path, "a.xlsx", ["r@kunde.de"]))
    klicken(app.ui.kunde_match, "Kundenakte")
    pump(app, 0.2)
    assert app.nav.current == "customers" and app.customer_page.customer_id == kunde.id


def test_auto_apply_only_when_enabled_and_undoable(kunden_app, tmp_path: Path) -> None:
    app = kunden_app
    kunde = app.customers.create("Beispiel GmbH", "123456", ["r@kunde.de"])
    app.var_auto_customer.set(True)
    pruefen(app, liste(tmp_path, "a.xlsx", ["r@kunde.de"], kd="", firma=""))
    assert app.active_customer() is kunde and app.var_kd.get() == "123456"
    info = app.ui.kunde_info
    assert info.title == "Bekannter Kunde übernommen" and "Rückgängig" in aktionen(info)
    klicken(info, "Rückgängig")
    assert app.active_customer() is None and app.var_kd.get() == "" and app.var_firma.get() == ""
    assert app.ui.kunde_match.visible()  # wieder als Angebot


def test_auto_apply_never_replaces_other_entered_data(kunden_app, tmp_path: Path) -> None:
    app = kunden_app
    app.customers.create("Beispiel GmbH", "123456", ["r@kunde.de"])
    app.var_auto_customer.set(True)
    app.var_kd.set("999")  # bereits eingetragen – ein anderer Kunde?
    pruefen(app, liste(tmp_path, "a.xlsx", ["r@kunde.de"], kd="", firma=""))
    assert app.active_customer() is None and app.var_kd.get() == "999"
    assert app.ui.kunde_match.title == "Bekannter Kunde gefunden"


def test_conflicting_customers_need_a_decision(kunden_app, tmp_path: Path) -> None:
    app = kunden_app
    a = app.customers.create("A GmbH", "1", ["a@a.de"])
    app.customers.create("B GmbH", "2", ["b@b.de"])
    app.var_auto_customer.set(True)
    pruefen(app, liste(tmp_path, "ab.xlsx", ["a@a.de", "b@b.de"], kd="", firma=""))
    bar = app.ui.kunde_match
    assert app._match.kind.value == "conflicting_matches"
    assert bar.severity == "warning"
    assert "Die Excel enthält Rechnungsempfänger, die verschiedenen bekannten Kunden zugeordnet sind." in bar.message
    assert app.active_customer() is None  # keine automatische Entscheidung
    klicken(bar, "Kunden auswählen …")  # Tests: erster Kandidat
    assert app.active_customer() is a


def test_several_emails_of_one_customer_are_one_match(kunden_app, tmp_path: Path) -> None:
    app = kunden_app
    kunde = app.customers.create("A GmbH", "1", ["rechnung@a.de", "buchhaltung@a.de"])
    pruefen(app, liste(tmp_path, "a.xlsx", ["rechnung@a.de", "Buchhaltung@a.de"]))
    assert app._match.kind.value == "single_match" and app._match.customer_id == kunde.id


def test_ambiguous_legacy_mapping_asks(kunden_app, tmp_path: Path) -> None:
    from tools.contract_overview.customers.models import Customer
    from tools.contract_overview.customers.repository import CustomerStore

    app = kunden_app
    app.customers = CustomerStore(app.customers.path, [Customer("x", "X AG", "1", ["r@x.de"]), Customer("y", "X AG Filiale", "2", ["r@x.de"])])
    pruefen(app, liste(tmp_path, "x.xlsx", ["r@x.de"]))
    assert app._match.kind.value == "ambiguous_match"
    assert app.ui.kunde_match.title == "Zuordnung nicht eindeutig" and app.active_customer() is None


# --- Übernehmen und Arbeitskopie ------------------------------------------------------------------


def test_working_copy_never_changes_the_record_silently(kunden_app, tmp_path: Path) -> None:
    app = kunden_app
    logo = tmp_path / "logo.png"
    from PIL import Image

    Image.new("RGB", (40, 20), "red").save(logo)
    ziel = tmp_path / "ausgabe"
    ziel.mkdir()
    kunde = app.customers.create("Beispiel GmbH", "123456", ["r@kunde.de"], logo=str(logo), target_dir=str(ziel))
    app.pick_customer()  # »Bekannten Kunden auswählen« (Tests: erster Treffer)
    assert app.active_customer() is kunde
    assert app.var_logo.get() == str(logo) and app.var_ziel.get() == str(ziel)
    app.var_firma.set("Beispiel GmbH & Co. KG")
    pump(app, 0.2)
    assert app.customers.get(kunde.id).company == "Beispiel GmbH"  # Kundenakte unverändert
    assert "Firmenname" in app.ui.kunde_active_caption.cget("text")
    assert app.ui.btn_kunde_save.text() == "Kundenakte aktualisieren"
    app.update_active_customer()  # Tests: alle gezeigten Änderungen übernehmen
    assert app.customers.get(kunde.id).company == "Beispiel GmbH & Co. KG"
    ident = kunde.id
    zweite = neustart(app)
    try:
        assert zweite.customers.get(ident).company == "Beispiel GmbH & Co. KG"
        assert zweite.active_customer().id == ident  # aktive Kundenakte bleibt nach dem Neustart
    finally:
        schliessen(zweite)


def test_missing_logo_and_folder_fall_back_with_hint(kunden_app, tmp_path: Path) -> None:
    app = kunden_app
    logo_vorher, ziel_vorher = app.var_logo.get(), app.var_ziel.get()
    kunde = app.customers.create("A GmbH", "1", logo=str(tmp_path / "fehlt.png"), target_dir=str(tmp_path / "fehlt"))
    app.apply_customer(kunde.id)
    assert app.var_logo.get() == logo_vorher and app.var_ziel.get() == ziel_vorher
    assert "Gespeichertes Logo wurde nicht gefunden" in app.ui.kunde_info.message
    assert "Zielordner" in app.ui.kunde_info.message


def test_template_follows_the_rule(kunden_app) -> None:
    app = kunden_app
    app.state.save_vorlage({"name": "Vorlage X", "titel": "Titel X", "format": "quer"})
    kunde = app.customers.create("A GmbH", "1", template="Vorlage X")
    app.apply_customer(kunde.id)
    assert app.var_titel.get() != "Titel X"  # ohne »automatisch verwenden« nur angeboten
    assert "Vorlage „Vorlage X“ anwenden" in aktionen(app.ui.kunde_info)
    app.customers.update(kunde.id, template_auto=True)
    app.apply_customer(kunde.id)
    assert app.var_titel.get() == "Titel X" and app.var_format.get() == "quer"


def test_user_edited_texts_are_not_overwritten(kunden_app) -> None:
    from tools.contract_overview.customers.models import TextBlock

    app = kunden_app
    kunde = app.customers.create("A GmbH", "1", footer=TextBlock("Fußzeile A"), header=TextBlock("Kopf A"))
    app.ui.txt_fuss.set("Eigene Fußzeile")  # Benutzer hat die Fußzeile geändert
    pump(app, 0.1)
    app.apply_customer(kunde.id)
    assert app.footer_text() == "Eigene Fußzeile" and app.header_text() != "Kopf A"
    klicken(app.ui.kunde_info, "Texte der Kundenakte verwenden")
    assert app.footer_text() == "Fußzeile A" and app.header_text() == "Kopf A"


def test_standard_footer_never_vanishes(kunden_app) -> None:
    from appstate import DEFAULT_FOOTER
    from tools.contract_overview.customers.migration import customer_from_legacy

    app = kunden_app
    assert app.footer_text() == DEFAULT_FOOTER
    alt = customer_from_legacy({"firmenname": "Alt AG", "kundennummer": "1", "fusszeile": "", "kopfzeile": ""}, "")
    app.customers.restore(alt)
    app.apply_customer(alt.id)
    assert app.footer_text() == DEFAULT_FOOTER
    # auch ein bewusst leerer Fußzeilenwert in der Akte ersetzt die gültige nie
    from tools.contract_overview.customers.models import TextBlock

    alt.footer = TextBlock("   ")
    app.apply_customer(alt.id)
    assert app.footer_text() == DEFAULT_FOOTER


def test_new_overview_leaves_the_customer(kunden_app) -> None:
    from tools.contract_overview.customers.models import TextBlock

    app = kunden_app
    vorher = app.footer_text()
    kunde = app.customers.create("A GmbH", "1", footer=TextBlock("Fußzeile A"))
    app.apply_customer(kunde.id)
    assert app.footer_text() == "Fußzeile A"
    app.new_overview()
    assert app.active_customer() is None and app.var_kd.get() == ""
    assert app.footer_text() == vorher  # Text eines Kunden nie in der Übersicht des nächsten
    klicken(app.ui.kunde_info, "Rückgängig")
    assert app.active_customer() is kunde and app.footer_text() == "Fußzeile A"


def test_detach_keeps_the_entered_data(kunden_app) -> None:
    app = kunden_app
    kunde = app.customers.create("A GmbH", "1")
    app.apply_customer(kunde.id)
    app.detach_customer()
    assert app.active_customer() is None and app.var_firma.get() == "A GmbH"
    assert not app.ui.kunde_active_area.expanded
    klicken(app.ui.kunde_info, "Rückgängig")
    assert app.active_customer() is kunde


# --- Lernen nur nach bewusster Zuordnung ------------------------------------------------------------


def test_save_as_customer_learns_the_email_on_request(kunden_app, tmp_path: Path) -> None:
    app = kunden_app
    app.var_ziel.set(str(tmp_path))
    app.var_open.set(False)
    datei = liste(tmp_path, "neu.xlsx", ["neu@kunde.de"])
    pruefen(app, datei)
    app.start_pdf()
    assert wait_until(app, lambda: not app.busy, 90)
    assert app.ui.kunde_info.title == "Als Kundenakte speichern?" and len(app.customers) == 0
    klicken(app.ui.kunde_info, "Als Kundenakte speichern")  # Dialog: »Zuordnung merken« ist vorbelegt
    kunde = app.active_customer()
    assert kunde is not None and kunde.emails == ["neu@kunde.de"] and kunde.label == "Muster GmbH · 10042"
    app.new_overview()
    pruefen(app, datei)
    assert app._match.kind.value == "single_match" and app._match.customer_id == kunde.id


def test_save_without_remembering_the_email(kunden_app, tmp_path: Path, monkeypatch) -> None:
    from tools.contract_overview import customer_widgets

    app = kunden_app
    monkeypatch.setattr(customer_widgets, "ask_new_customer", lambda *a, **k: (True, False))
    pruefen(app, liste(tmp_path, "neu.xlsx", ["neu@kunde.de"]))
    app.save_as_customer()
    assert app.active_customer().emails == []


def test_new_email_of_a_known_customer_is_offered(kunden_app, tmp_path: Path) -> None:
    app = kunden_app
    kunde = app.customers.create("K GmbH", "5", ["alt@k.de"])
    datei = liste(tmp_path, "k.xlsx", ["neu@k.de"], kd="5", firma="K GmbH")
    pruefen(app, datei)
    assert app._match.kind.value == "no_match"
    app.apply_customer(kunde.id)  # bewusst gewählt
    bar = app.ui.kunde_match
    assert bar.title == "Diese E-Mail künftig diesem Kunden zuordnen?" and "neu@k.de" in bar.message
    assert list(aktionen(bar)) == ["Zuordnung merken", "Nicht zuordnen"]
    klicken(bar, "Zuordnung merken")
    assert app.customers.get(kunde.id).emails == ["alt@k.de", "neu@k.de"]
    pruefen(app, datei)
    assert app._match.kind.value == "single_match"


def test_excel_of_another_customer_is_flagged(kunden_app, tmp_path: Path) -> None:
    app = kunden_app
    kunde = app.customers.create("K GmbH", "5", ["k@k.de"])
    app.apply_customer(kunde.id)
    pruefen(app, liste(tmp_path, "fremd.xlsx", ["andere@firma.de"], kd="999", firma="Andere GmbH"))
    bar = app.ui.kunde_match
    assert bar.severity == "warning" and bar.title == "Excel passt nicht zur aktiven Kundenakte" and "999" in bar.message
    klicken(bar, "Kundenakte lösen")
    assert app.active_customer() is None


def test_declined_email_is_not_offered_again(kunden_app, tmp_path: Path) -> None:
    app = kunden_app
    kunde = app.customers.create("K GmbH", "5")
    pruefen(app, liste(tmp_path, "k.xlsx", ["neu@k.de"], kd="5", firma="K GmbH"))
    app.apply_customer(kunde.id)
    klicken(app.ui.kunde_match, "Nicht zuordnen")
    app.apply_customer(kunde.id)
    assert not app.ui.kunde_match.visible() and app.customers.get(kunde.id).emails == []


@pytest.mark.parametrize(("antwort", "besitzer"), [("primary", "B"), ("secondary", "A"), ("close", "A")])
def test_email_conflict_is_decided_by_the_user(kunden_app, monkeypatch, antwort: str, besitzer: str) -> None:
    from ui import dialogs

    app = kunden_app
    a = app.customers.create("A", "1", ["x@x.de"])
    b = app.customers.create("B", "2")
    monkeypatch.setattr(dialogs, "AUTO_ANSWER", antwort)
    app.assign_emails(b.id, ["X@x.de"])
    owners = [c.company for c in app.customers.owners("x@x.de")]
    assert owners == [besitzer]  # nie still doppelt zugeordnet
    assert (a.emails == ["x@x.de"]) == (besitzer == "A")


# --- Ansicht »Kunden« ----------------------------------------------------------------------------------


def test_empty_state(kunden_app) -> None:
    app = kunden_app
    app.nav.navigate("customers", animate=False)
    pump(app, 0.1)
    page = app.customer_page
    assert page.empty.winfo_manager() and not page.list_card.winfo_manager()
    texte = [w.cget("text") for w in _alle(page.empty) if hasattr(w, "cget") and w.winfo_class() == "Label"]
    assert "Noch keine Kunden gespeichert." in texte
    assert any(t.startswith("PDF Tool kann bekannte Rechnungsempfänger später automatisch wiedererkennen.") for t in texte)
    buttons = [w for w in _alle(page.empty) if hasattr(w, "text") and callable(w.text)]
    assert [b.text() for b in buttons] == ["Zur Vertragsübersicht"]
    buttons[0].invoke()
    assert app.nav.current == "create"


def _alle(widget):
    for child in widget.winfo_children():
        yield child
        yield from _alle(child)


def test_list_search_sort_with_hundreds_of_customers(kunden_app) -> None:
    app = kunden_app
    for number in range(400):
        app.customers.create(f"Firma {number:03d}", str(1000 + number), [f"r{number}@firma{number}.de"])
    app.customers.create("Müller & Söhne GmbH", "77", ["buchhaltung@mueller.de"])
    app.customers_changed()
    app.nav.navigate("customers", animate=False)
    page = app.customer_page
    start = time.perf_counter()
    page.refresh_list()
    pump(app, 0.05)
    assert time.perf_counter() - start < 2.0
    assert "401 Kundenakten" in page.count.cget("text") and "Suche verfeinern" in page.count.cget("text")
    page.var_search.set("müller")
    assert wait_until(app, lambda: len(page.listing.items) == 1, 5)
    assert page.listing.items[0].company == "Müller & Söhne GmbH"
    page.var_search.set("MUELLER.de")  # E-Mail, Groß-/Kleinschreibung egal
    assert wait_until(app, lambda: len(page.listing.items) == 1, 5)
    page.var_search.set("1007")  # Kundennummer
    assert wait_until(app, lambda: [c.number for c in page.listing.items] == ["1007"], 5)
    page.var_search.set("")
    page._sort_picked("Kundennummer")
    pump(app, 0.3)
    assert page.listing.items[0].number == "77" and app.customer_order == "number"
    page._sort_picked("Firma A–Z")
    assert page.listing.items[0].company == "Firma 000"


def test_keyboard_opens_and_leaves_the_detail(kunden_app) -> None:
    app = kunden_app
    kunde = app.customers.create("A GmbH", "1")
    app.customers_changed()
    app.nav.navigate("customers", animate=False)
    page = app.customer_page
    pump(app, 0.1)
    page.listing.focus_force()
    pump(app, 0.1)
    page.listing.event_generate("<KeyPress-Down>")
    page.listing.event_generate("<KeyPress-Return>")
    pump(app, 0.1)
    assert page.customer_id == kunde.id and page.detail_view.winfo_manager()
    page.show_list()
    assert page.customer_id is None and page.list_view.winfo_manager()
    # Strg+F: in »Kunden« die Suche, sonst »Bekannten Kunden auswählen«
    app.find_customer()
    pump(app, 0.1)
    assert app.focus_get() is page.field_search.entry
    app.nav.navigate("create", animate=False)
    app.find_customer()
    assert app.active_customer() is kunde


def test_detail_edit_emails_and_persistence(kunden_app, config_file: Path) -> None:
    app = kunden_app
    kunde = app.customers.create("A GmbH", "1", ["a@a.de"])
    app.customers_changed()
    app.nav.navigate("customers", animate=False)
    page = app.customer_page
    page.show_detail(kunde.id)
    page.var_company.set("A GmbH & Co.")
    page.flush()
    assert kunde.company == "A GmbH & Co."
    page.var_email.set("kein-at-zeichen")
    page.add_email()
    assert app.ui.kunde_mail_info.severity == "warning" and kunde.emails == ["a@a.de"]
    page.var_email.set(" Zweite@A.de ")
    page.add_email()
    assert kunde.emails == ["a@a.de", "zweite@a.de"]
    page.var_email.set("zweite@a.de")
    page.add_email()
    assert app.ui.kunde_mail_info.severity == "info" and kunde.emails == ["a@a.de", "zweite@a.de"]
    page.make_primary("zweite@a.de")
    assert kunde.primary_email == "zweite@a.de"
    page.remove_email("zweite@a.de")
    page.remove_email("a@a.de")
    assert kunde.emails == [] and app.customers.get(kunde.id) is kunde  # Akte bleibt
    klicken(app.ui.kunde_mail_info, "Rückgängig")
    assert kunde.emails == ["a@a.de"]
    data = json.loads((config_file.parent / "kundenakten.json").read_text(encoding="utf-8"))
    assert data["schema_version"] == 2 and data["customers"][0]["company"] == "A GmbH & Co."


def test_delete_removes_record_but_never_files(kunden_app, tmp_path: Path) -> None:
    app = kunden_app
    pdf = tmp_path / "alt.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    excel = liste(tmp_path, "alt.xlsx", ["d@d.de"])
    kunde = app.customers.create("D GmbH", "4", ["d@d.de"])
    app.customers.touch(kunde.id, excel=str(excel), pdf=str(pdf))
    app.apply_customer(kunde.id)
    app.nav.navigate("customers", animate=False)
    app.customer_page.show_detail(kunde.id)
    app.customer_page.delete()  # Bestätigung: Hauptschaltfläche
    assert app.customers.get(kunde.id) is None and app.customers.owner_ids("d@d.de") == []
    assert pdf.is_file() and excel.is_file()
    assert app.active_customer() is None and app.var_firma.get() == "D GmbH"
    klicken(app.ui.kunden_info, "Rückgängig")
    assert app.customers.get(kunde.id) is not None


def test_merge_only_on_request(kunden_app) -> None:
    app = kunden_app
    a = app.customers.create("Beispiel GmbH", "123", ["a@b.de"])
    b = app.customers.create("Beispiel", "123", ["c@b.de"])
    app.customers_changed()
    app.nav.navigate("customers", animate=False)
    page = app.customer_page
    page.show_detail(a.id)
    assert app.ui.kunde_detail_info.visible() and "Mögliche Doppelung" in app.ui.kunde_detail_info.message
    assert len(app.customers) == 2  # Hinweis, keine automatische Zusammenführung
    page.merge()  # Auswahl: erster Kandidat (die Doppelung), dann bestätigen
    assert len(app.customers) == 1 and app.customers.get(b.id) is None
    assert app.customers.get(a.id).emails == ["a@b.de", "c@b.de"]


def test_create_customer_manually(kunden_app, monkeypatch) -> None:
    from tools.contract_overview import customer_widgets

    app = kunden_app
    monkeypatch.setattr(customer_widgets, "ask_customer_fields", lambda parent: ("Neu GmbH", "55", "Info@Neu.de"))
    app.nav.navigate("customers", animate=False)
    app.create_customer_manually()
    kunde = app.customers.all()[0]
    assert kunde.label == "Neu GmbH · 55" and kunde.emails == ["info@neu.de"]
    assert app.customer_page.customer_id == kunde.id
    monkeypatch.setattr(customer_widgets, "ask_customer_fields", lambda parent: ("", "", ""))
    app.create_customer_manually()
    assert len(app.customers) == 1 and app.ui.kunden_info.severity == "warning"


def test_use_last_excel_checks_it_again(kunden_app, tmp_path: Path) -> None:
    app = kunden_app
    excel = liste(tmp_path, "letzte.xlsx", ["l@l.de"])
    kunde = app.customers.create("L GmbH", "8", ["l@l.de"])
    app.customers.touch(kunde.id, excel=str(excel))
    app.nav.navigate("customers", animate=False)
    app.customer_page.show_detail(kunde.id)
    app.customer_page.use_last_excel()
    assert app.nav.current == "create" and app.active_customer() is kunde
    assert app._analysis is None  # nie eine alte Analyse – die Datei wird neu geprüft
    assert wait_until(app, lambda: app._analysis is not None, 60)


# --- Live-Vorschau --------------------------------------------------------------------------------------


def _vorschau_text(app) -> str:
    pypdf = pytest.importorskip("pypdf")
    return "\n".join(page.extract_text() for page in pypdf.PdfReader(str(app._preview_doc.path)).pages)


def _vorschau_fertig(app) -> bool:
    return app._preview_building is None and app._preview_doc is not None and app.ui.preview_view.state == "current" and app.ui.preview_canvas.shown_page == (app._preview_doc.token, app._preview_page)


def test_preview_follows_customer_changes_without_stale_results(kunden_app, tmp_path: Path) -> None:
    app = kunden_app
    a = app.customers.create("Alpha GmbH", "111")
    b = app.customers.create("Beta GmbH", "222")
    pruefen(app, liste(tmp_path, "v.xlsx", ["v@v.de"], kd="", firma=""))
    app.nav.navigate("preview", animate=False)
    assert wait_until(app, lambda: _vorschau_fertig(app), 60)
    assert "Kundennummer: –" in _vorschau_text(app)  # Platzhalter ohne Kundennummer
    laeufe = app.preview_runs
    app.apply_customer(a.id)
    app.refresh_preview()  # Erzeugung für A läuft …
    assert app._preview_building is not None
    app.apply_customer(b.id)  # … und der Kunde wechselt sofort zu B
    assert wait_until(app, lambda: _vorschau_fertig(app) and "Beta GmbH" in json.dumps(app._preview_signature), 90)
    text = _vorschau_text(app)
    assert "Beta GmbH" in text and "222" in text and "Alpha GmbH" not in text
    assert app.preview_runs >= laeufe + 1


def test_preview_pages_and_zoom(kunden_app, tmp_path: Path) -> None:
    app = kunden_app
    app.var_kd.set("1")
    pruefen(app, liste(tmp_path, "lang.xlsx", ["v@v.de"], rows=90))
    app.nav.navigate("preview", animate=False)
    assert wait_until(app, lambda: _vorschau_fertig(app), 60)
    tools = app.ui.preview_tools
    assert app._preview_doc.pages >= 2 and tools.page_text.cget("text") == f"Seite 1 von {app._preview_doc.pages}"
    assert not tools.prev.enabled() and tools.next.enabled()
    app.preview_step(1)
    assert wait_until(app, lambda: _vorschau_fertig(app) and app._preview_page == 1, 30)
    assert tools.prev.enabled()
    breite = app.ui.preview_canvas._size[0]
    app.preview_zoom(1)
    assert wait_until(app, lambda: _vorschau_fertig(app) and app.ui.preview_canvas._size[0] > breite, 30)
    assert tools.zoom_text.cget("text").endswith("%") and tools.fit.enabled()
    app.preview_zoom(0)
    assert tools.zoom_text.cget("text") == "An Breite" and not tools.fit.enabled()
    # Keine Vorschau-Dateien im Zielordner, temporäre Dateien werden beim Beenden gelöscht
    ordner = app._preview_doc.folder
    assert ordner.is_dir() and not list(Path(app.target_folder()).glob("vorschau*.pdf"))
    app._close_preview()
    assert not ordner.exists()


def test_stale_preview_folders_are_removed(tmp_path: Path, monkeypatch) -> None:
    import os
    import tempfile

    from tools.contract_overview import preview

    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(tmp_path))
    alt = tmp_path / (preview.FOLDER_PREFIX + "alt")
    neu = tmp_path / (preview.FOLDER_PREFIX + "neu")
    fremd = tmp_path / "anderer-ordner"
    for folder in (alt, neu, fremd):
        folder.mkdir()
        (folder / "vorschau.pdf").write_bytes(b"%PDF")
    vor_zwei_tagen = time.time() - 2 * 86400
    os.utime(alt, (vor_zwei_tagen, vor_zwei_tagen))
    os.utime(fremd, (vor_zwei_tagen, vor_zwei_tagen))
    assert preview.sweep_stale_folders() == 1
    assert not alt.exists() and neu.exists() and fremd.exists()


def test_preview_explains_what_is_missing(kunden_app) -> None:
    app = kunden_app
    app.var_excel.set("")
    app.nav.navigate("preview", animate=False)
    pump(app, 0.2)
    assert app.ui.preview_view.state == "empty"
    assert app.ui.preview_view.empty_reason.cget("text") == "Excel-Datei fehlt"


# --- Übernahme aus 2.3 und Unabhängigkeit von »PDF reparieren« -------------------------------------------


def test_history_of_23_becomes_customer_records(config_file: Path, monkeypatch) -> None:
    import vertragdesk
    from ui import dialogs

    monkeypatch.setattr(dialogs, "AUTO_ANSWER", "primary")
    monkeypatch.setenv("UE_NO_ANIMATIONS", "1")
    kunden = [
        {"firmenname": "Muster GmbH", "kundennummer": "10042", "rechnungsempfaenger": "rechnung@muster.de", "fusszeile": "Eigene\nFußzeile", "kopfzeile": "", "excel": "C:/x.xlsx", "pdf": ""},
        {"firmenname": "Alt AG", "kundennummer": "1", "rechnungsempfaenger": "", "fusszeile": "", "kopfzeile": ""},
    ]
    config_file.write_text(json.dumps({"gesehen": "2.3.0", "theme": "light", "kunden": kunden, "firmenname": "Muster GmbH"}), encoding="utf-8")
    app = vertragdesk.App()
    try:
        pump(app, 0.8)  # »Neu in Version« erscheint nach 0,5 s und schließt sich im Test selbst
        assert sorted(k.label for k in app.customers.all()) == ["Alt AG · 1", "Muster GmbH · 10042"]
        assert app.ui.kunden_info.severity == "success" and "2 Kunden" in app.ui.kunden_info.message
        assert list((config_file.parent / "sicherungen").glob("gui-config-vor-kundenakte-*.json"))
        assert "kunden" not in json.loads(config_file.read_text(encoding="utf-8"))
        ids = sorted(k.id for k in app.customers.all())
        zweite = neustart(app)
        app = zweite
        assert sorted(k.id for k in app.customers.all()) == ids  # keine zweite Übernahme, stabile IDs
    finally:
        schliessen(app)


def test_failed_migration_keeps_the_history(config_file: Path, monkeypatch) -> None:
    import vertragdesk
    from tools.contract_overview.customers.repository import CustomerStore
    from ui import dialogs

    monkeypatch.setattr(dialogs, "AUTO_ANSWER", "primary")
    monkeypatch.setenv("UE_NO_ANIMATIONS", "1")
    monkeypatch.setattr(CustomerStore, "save", lambda self: False)
    kunden = [{"firmenname": "Muster GmbH", "kundennummer": "10042", "rechnungsempfaenger": "r@m.de"}]
    config_file.write_text(json.dumps({"gesehen": "2.3.0", "theme": "light", "kunden": kunden}), encoding="utf-8")
    app = vertragdesk.App()
    try:
        pump(app, 0.8)
        assert app.ui.kunden_info.severity == "error"
        app.persist()
        assert json.loads(config_file.read_text(encoding="utf-8"))["kunden"] == kunden  # nichts verloren
    finally:
        schliessen(app)


def test_repair_tool_stays_independent(kunden_app) -> None:
    from tools.registry import CONTRACTS, REPAIR

    app = kunden_app
    assert REPAIR.pages == ("repair",) and "customers" in CONTRACTS.pages and "preview" in CONTRACTS.pages
    app.open_tool(REPAIR.key)
    pump(app, 0.2)
    app._find_action()  # Strg+F hat in »PDF reparieren« keine Wirkung
    assert app.nav.current == "repair"
    repair_page = app.nav.pages["repair"]
    texte = " ".join(w.cget("text") for w in _alle(repair_page) if w.winfo_class() == "Label")
    assert "Kunde" not in texte
