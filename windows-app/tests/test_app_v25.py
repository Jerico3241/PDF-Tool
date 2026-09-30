"""Oberflächentests für Version 2.5: kompakte Excel-Karte und Stapelverarbeitung in »Vertragsübersichten«."""

from __future__ import annotations

import json
import os
import time
from datetime import datetime
from pathlib import Path

import pytest

from conftest import display_available, neustart, pump, schliessen, wait_until, write_excel
from test_batch import liste as stapel_liste

pytestmark = pytest.mark.skipif(not display_available(), reason="kein Display verfügbar")
pypdf = pytest.importorskip("pypdf")


@pytest.fixture
def stapel_app(config_file: Path, monkeypatch):
    """App ohne Animationen; Dialoge antworten mit der Hauptschaltfläche."""
    import appstate

    config_file.write_text(json.dumps({"gesehen": appstate.VERSION, "theme": "light", "kundenakte_verwenden": True}), encoding="utf-8")
    monkeypatch.setenv("UE_NO_ANIMATIONS", "1")
    from ui import dialogs

    monkeypatch.setattr(dialogs, "AUTO_ANSWER", "primary")
    import vertragdesk

    instance = vertragdesk.App()
    instance.ctx.anim.enabled = False
    pump(instance, 0.3)
    yield instance
    schliessen(instance)


def excel(pfad: Path, aktiv: int = 5, inaktiv: int = 0, mails=("rechnung@kunde-a.de",), spalten=None) -> Path:
    """Excel wie die echten Listen (ohne Kundennummer und Firma) – Empfänger reihum."""
    zeilen = []
    for index in range(aktiv + inaktiv):
        mail = mails[index % len(mails)] if mails else ""
        zeilen.append([f"V-{index + 1}", datetime(2022, 1, 1 + index % 28), "jährlich", 10.0 + index, "Sofort", f"Modul {index + 1}", mail, "Aktiv" if index < aktiv else "Inaktiv"])
    spalten = spalten or ["Vertrag-Nr.", "Beginnt am", "Abrechnungszyklus", "Netto [€]", "Zahlungsart", "Bemerkung", "Rechnungsempfänger Email", "Anwenderstatus"]
    if "Rechnungsempfänger Email" not in spalten:
        zeilen = [zeile[:6] + zeile[7:] for zeile in zeilen]
    return write_excel(pfad, zeilen, spalten)


def einzeln_pruefen(app, path: Path) -> None:
    app.nav.navigate("create", animate=False)
    app.use_excel(str(path))
    assert wait_until(app, lambda: app._analysis is not None and app._analysis_path == str(path), 60)
    pump(app, 0.2)


def fakten(app) -> dict[str, str]:
    return {label: wert for label, wert, _ton in app.ui.excel_facts.facts()}


def stapel(app, target: Path | None = None):
    app.nav.navigate("batch", animate=False)
    pump(app, 0.2)
    if target is not None:
        app.batch_update_settings(target_dir=str(target))
    return app.batch_page


def geprueft(app, timeout: float = 90) -> None:
    from tools.contract_overview.batch.models import WAITING

    assert wait_until(app, lambda: app.batch_items and all(item.status not in WAITING for item in app.batch_items), timeout), [(i.name, i.status) for i in app.batch_items]
    pump(app, 0.2)


def erstellen(app, timeout: float = 180) -> None:
    app.batch_start()
    assert wait_until(app, lambda: not app.batch_running, timeout)
    pump(app, 0.2)


def eintrag(app, name: str):
    return next(item for item in app.batch_items if item.name == name)


def status(app) -> dict[str, str]:
    return {item.name: item.status.value for item in app.batch_items}


def pdf_text(pfad) -> str:
    return " ".join(" ".join(page.extract_text() or "" for page in pypdf.PdfReader(str(pfad)).pages).split())


# --- Teil A: kompakte Excel-Karte ------------------------------------------------------------------------


def test_excel_card_shows_contract_counts_only_once(stapel_app, tmp_path: Path) -> None:
    app = stapel_app
    einzeln_pruefen(app, excel(tmp_path / "liste.xlsx", aktiv=5, inaktiv=3, mails=("p.zimmermann@ipb-zimmermann.de",)))
    bar = app.ui.info_excel
    assert (bar.severity, bar.title, bar.message) == ("success", "Excel geprüft", "5 aktive Verträge · 3 inaktiv ausgeblendet")
    labels = fakten(app)
    assert "Aktive Verträge" not in labels and "Ausgeblendet (inaktiv)" not in labels  # keine Doppelung
    assert not any("aktiv" in wert for wert in labels.values())
    assert app.ui.mail_row.winfo_manager() and app.ui.mail_value.cget("text") == "p.zimmermann@ipb-zimmermann.de"
    assert not app.ui.mail_combo.winfo_ismapped()
    assert app.ui.excel_details.expanded


def test_status_line_without_inactive_and_in_singular(stapel_app, tmp_path: Path) -> None:
    app = stapel_app
    einzeln_pruefen(app, excel(tmp_path / "fuenf.xlsx", aktiv=5))
    assert app.ui.info_excel.message == "5 aktive Verträge"  # kein »0 inaktiv ausgeblendet«
    einzeln_pruefen(app, excel(tmp_path / "eins.xlsx", aktiv=1))
    assert app.ui.info_excel.message == "1 aktiver Vertrag"
    einzeln_pruefen(app, excel(tmp_path / "eins_inaktiv.xlsx", aktiv=1, inaktiv=1))
    assert app.ui.info_excel.message == "1 aktiver Vertrag · 1 inaktiv ausgeblendet"


def test_several_recipients_show_a_count_and_the_choice(stapel_app, tmp_path: Path) -> None:
    app = stapel_app
    app.var_mail.set("")
    einzeln_pruefen(app, excel(tmp_path / "drei.xlsx", aktiv=6, mails=("a@x.de", "b@x.de", "c@x.de")))
    assert app.ui.mail_value.cget("text") == "3 erkannt"
    assert app.ui.mail_combo.winfo_ismapped() and app.ui.mail_combo.values() == ["a@x.de", "b@x.de", "c@x.de"]
    assert "a@x.de" not in json.dumps(fakten(app))  # keine lange Liste in der Karte
    assert app.ui.ready.text.endswith("Bitte Rechnungsempfänger auswählen")
    app.ui.mail_combo.select_index(1)
    pump(app, 0.1)
    assert app.var_mail.get() == "b@x.de"


def test_no_recipient_means_no_empty_row(stapel_app, tmp_path: Path) -> None:
    app = stapel_app
    spalten = ["Vertrag-Nr.", "Beginnt am", "Abrechnungszyklus", "Netto [€]", "Zahlungsart", "Bemerkung", "Anwenderstatus"]
    einzeln_pruefen(app, excel(tmp_path / "ohne.xlsx", aktiv=2, spalten=spalten))
    assert app.ui.info_excel.severity == "success"
    assert not app.ui.mail_row.winfo_manager()
    assert not any("Rechnungsempfänger" in wert for wert in fakten(app).values())


def test_known_customer_appears_once(stapel_app, tmp_path: Path) -> None:
    app = stapel_app
    kunde = app.customers.create("IPB Zimmermann", "123456", ["p.zimmermann@ipb-zimmermann.de"])
    app.customers_changed()
    einzeln_pruefen(app, excel(tmp_path / "ipb.xlsx", mails=("p.zimmermann@ipb-zimmermann.de",)))
    bar = app.ui.kunde_match
    assert bar.visible() and bar.title == "Bekannter Kunde gefunden" and "IPB Zimmermann · 123456" in bar.message
    assert "p.zimmermann@" not in bar.message  # steht schon als Rechnungsempfänger darüber
    assert "Kunde" not in fakten(app)
    assert bar.winfo_toplevel() is app and str(bar).startswith(str(app.ui.dateien_card))  # in der Dateikarte
    app.apply_customer(kunde.id)
    pump(app, 0.2)
    assert not bar.visible() and "Kunde" not in fakten(app)
    assert app.ui.kunde_active_title.cget("text") == "Kunde: IPB Zimmermann · 123456"
    assert app.ui.kunde_picker.get() == ""  # das Auswahlfeld wiederholt die aktive Kundenakte nicht
    app.detach_customer()
    einzeln_pruefen(app, excel(tmp_path / "neu.xlsx", mails=("info@unbekannt.de",)))
    assert fakten(app).get("Kunde") == "Nicht zugeordnet"


# --- Teil B: Stapel anlegen ----------------------------------------------------------------------------------


def test_empty_batch_offers_files_and_folder(stapel_app) -> None:
    app = stapel_app
    page = stapel(app)
    assert page.empty.winfo_manager() and not page.list_area.winfo_manager() and not page.run_card.winfo_manager()
    texts = [child.cget("text") for child in page.empty.winfo_children()[0].winfo_children() if hasattr(child, "cget") and child.winfo_class() == "Label"]
    assert "Noch keine Excel-Dateien hinzugefügt." in texts
    assert "Füge mehrere Excel-Dateien hinzu, um Vertragsübersichten gesammelt zu erstellen." in texts
    assert not page.tools.winfo_manager()  # dieselben Aktionen stehen im leeren Zustand


def test_help_follows_the_open_view(stapel_app, monkeypatch) -> None:
    app = stapel_app
    shown = []
    monkeypatch.setattr(app, "show_steps", lambda title, steps, notes=(): shown.append((title, steps, notes)))
    stapel(app)
    app.show_help()
    app.nav.navigate("create", animate=False)
    app.show_help()
    (batch_title, batch_steps, _notes), (single_title, _steps, single_notes) = shown
    assert batch_title == "Kurzanleitung – Stapel" and any("Bereite Übersichten erstellen" in step for step in batch_steps)
    assert single_title == "Kurzanleitung – Vertragsübersichten" and any("»Stapel«" in note for note in single_notes)


def test_files_folders_and_duplicates(stapel_app, tmp_path: Path) -> None:
    app = stapel_app
    stapel(app, tmp_path / "out")
    ordner = tmp_path / "ordner"
    ordner.mkdir()
    a = excel(ordner / "a.xlsx")
    excel(ordner / "b.xlsx", mails=("x@y.de",))
    (ordner / "notiz.txt").write_text("keine Excel", encoding="utf-8")
    (ordner / "~$a.xlsx").write_bytes(b"Sperrdatei von Excel")
    unter = ordner / "unter"
    unter.mkdir()
    excel(unter / "tief.xlsx")  # nicht rekursiv
    assert app.batch_add([str(a)]) == (1, 0, 0)
    # a.xlsx kommt zweimal (über den Ordner und direkt) und steht schon im Stapel: 2 Doppelte, 1 neu (b.xlsx)
    assert app.batch_add([str(ordner), str(a).upper() if os.name == "nt" else str(a), str(tmp_path / "bild.png")]) == (1, 2, 1)
    assert sorted(item.name for item in app.batch_items) == ["a.xlsx", "b.xlsx"]
    assert app.ui.batch_info.severity == "warning" and "keine Excel" in app.ui.batch_info.message
    geprueft(app)
    assert set(status(app).values()) <= {"ready", "needs_input"}


def test_drop_adds_several_files_only_on_the_batch_page(stapel_app, tmp_path: Path) -> None:
    app = stapel_app
    a, b = excel(tmp_path / "a.xlsx"), excel(tmp_path / "b.xlsx")
    stapel(app)
    app._on_drop([str(a), str(b), str(tmp_path / "bild.png")])
    pump(app, 0.2)
    assert [item.name for item in app.batch_items] == ["a.xlsx", "b.xlsx"]
    assert app.var_excel.get() != str(a)  # der Einzelmodus bleibt unberührt
    # Im Einzelmodus: weiterhin genau eine Excel in den aktuellen Arbeitsablauf
    app.nav.navigate("create", animate=False)
    pump(app, 0.2)
    app._on_drop([str(b)])
    assert wait_until(app, lambda: app._analysis_path == str(b) and app._analysis is not None, 60)
    assert len(app.batch_items) == 2


# --- Teil B: Status, Kunden, Verarbeitung --------------------------------------------------------------------------


def test_single_file_batch(stapel_app, tmp_path: Path) -> None:
    app = stapel_app
    app.customers.create("Beispiel GmbH", "123456", ["rechnung@kunde-a.de"])
    stapel(app, tmp_path / "out")
    app.batch_add([str(excel(tmp_path / "vertrag_a.xlsx"))])
    geprueft(app)
    item = app.batch_items[0]
    assert item.status.value == "ready"
    row = app.ui.batch_list.rows[0]
    assert (row.title, row.facts, row.detail, row.status) == ("vertrag_a.xlsx", "5 aktive · rechnung@kunde-a.de", "Kunde erkannt: Beispiel GmbH · 123456", "Bereit")
    erstellen(app)
    assert item.status.value == "success" and Path(item.output) == tmp_path / "out" / "Vertragsuebersicht_Kd123456.pdf"
    page = app.batch_page
    assert page.result.visible() and page.result.title == "Stapel abgeschlossen" and page.result.text() == "1 Übersicht erstellt"
    assert "Beispiel GmbH" in pdf_text(item.output)


def test_twenty_files_are_analysed_while_the_ui_stays_responsive(stapel_app, tmp_path: Path) -> None:
    app = stapel_app
    stapel(app, tmp_path / "out")
    files = [str(stapel_liste(tmp_path / f"liste_{i:02d}.xlsx", mail=f"kunde{i}@beispiel.de", aktiv=40)) for i in range(20)]
    app.batch_add(files)
    longest = 0.0
    last = time.perf_counter()
    end = last + 120
    from tools.contract_overview.batch.models import WAITING

    while any(item.status in WAITING for item in app.batch_items) and time.perf_counter() < end:
        app.update()
        now = time.perf_counter()
        longest = max(longest, now - last)
        last = now
        time.sleep(0.01)
    assert all(item.analysis is not None and item.analysis.active == 40 for item in app.batch_items)
    assert longest < 0.75, f"Oberfläche blockiert ({longest:.2f} s)"
    assert len(app.ui.batch_list.rows) == 20


def test_fifty_files_stay_fluid(stapel_app, tmp_path: Path) -> None:
    from tools.contract_overview.batch.models import WAITING

    app = stapel_app
    stapel(app, tmp_path / "out")
    files = [str(stapel_liste(tmp_path / f"liste_{i:02d}.xlsx", mail=f"kunde{i}@beispiel.de", aktiv=10)) for i in range(50)]
    start = time.perf_counter()
    assert app.batch_add(files) == (50, 0, 0)
    # aufgenommen, ohne auf die Prüfung zu warten: Ergebnisse kommen erst über die Ereignisschleife
    assert all(item.status in WAITING for item in app.batch_items)
    app.update()
    added = time.perf_counter() - start
    assert len(app.ui.batch_list.rows) == 50
    assert added < 3.0, f"Hinzufügen dauerte {added:.2f} s"
    longest, last = 0.0, time.perf_counter()
    end = last + 180
    while any(item.status in WAITING for item in app.batch_items) and time.perf_counter() < end:
        app.update()
        now = time.perf_counter()
        longest, last = max(longest, now - last), now
        time.sleep(0.01)
    assert app.batch_counts()["needs_input"] == 50
    assert longest < 0.75, f"Oberfläche blockiert ({longest:.2f} s)"
    for key in ("needs_input", "all"):
        start = time.perf_counter()
        app.set_batch_filter(key)
        app.update()
        assert time.perf_counter() - start < 1.0, key
    start = time.perf_counter()
    app.batch_refresh_all()  # z. B. nach einer Änderung an Kundenakten
    app.update()
    assert time.perf_counter() - start < 1.5
    for item in app.batch_items:
        app.batch_edit(item.id, company="Firma", number=item.name[6:8])
    pump(app, 0.3)
    assert app.batch_counts()["ready"] == 50


def test_mixed_customers_get_the_right_status(stapel_app, tmp_path: Path) -> None:
    app = stapel_app
    app.customers.create("Beispiel GmbH", "100", ["rechnung@kunde-a.de"])
    app.customers.create("Muster AG", "200", ["buchhaltung@kunde-b.de"])
    stapel(app, tmp_path / "out")
    app.batch_add([str(excel(tmp_path / "bekannt.xlsx")), str(excel(tmp_path / "unbekannt.xlsx", mails=("info@neu.de",))), str(excel(tmp_path / "konflikt.xlsx", mails=("rechnung@kunde-a.de", "buchhaltung@kunde-b.de")))])
    geprueft(app)
    assert status(app) == {"bekannt.xlsx": "ready", "unbekannt.xlsx": "needs_input", "konflikt.xlsx": "needs_input"}
    konflikt = app.batch_resolution(eintrag(app, "konflikt.xlsx").id)
    assert konflikt.customer is None and konflikt.company == "" and konflikt.number == ""  # nie automatisch entscheiden
    assert app.batch_counts() == {"all": 3, "ready": 1, "needs_input": 2, "failed": 0, "done": 0}
    assert app.ui.batch_summary.text == "3 Dateien · 1 bereit · 2 Angaben erforderlich"
    # Konflikt bewusst lösen: Kunden wählen (Dialog wählt im Test den ersten Kandidaten)
    item = eintrag(app, "konflikt.xlsx")
    app.batch_page.show_detail(item.id)
    app.batch_choose_customer(item.id)
    pump(app, 0.2)
    res = app.batch_resolution(item.id)
    assert res.customer is not None and res.customer_source == "gewählt" and res.customer.company == "Beispiel GmbH"
    # Von den beiden Empfängern gehört genau einer zur gewählten Kundenakte – wie im Einzelmodus
    assert item.status.value == "ready" and res.email == "rechnung@kunde-a.de" and res.email_source == "Kundenakte"
    app.batch_page._mail_picked("buchhaltung@kunde-b.de")  # bewusst anders gewählt
    pump(app, 0.2)
    assert app.batch_resolution(item.id).email == "buchhaltung@kunde-b.de" and item.status.value == "ready"


def test_missing_number_does_not_hold_back_the_others(stapel_app, tmp_path: Path) -> None:
    app = stapel_app
    app.customers.create("Beispiel GmbH", "100", ["rechnung@kunde-a.de"])
    stapel(app, tmp_path / "out")
    app.batch_add([str(excel(tmp_path / "bekannt.xlsx")), str(excel(tmp_path / "ohne_nummer.xlsx", mails=("info@neu.de",)))])
    geprueft(app)
    offen = eintrag(app, "ohne_nummer.xlsx")
    app.batch_edit(offen.id, company="Neu GmbH")  # nur die Firma – Kundennummer fehlt weiterhin
    pump(app, 0.2)
    assert offen.status.value == "needs_input" and [i.code for i in offen.issues] == ["number_missing"]
    erstellen(app)
    assert eintrag(app, "bekannt.xlsx").status.value == "success"
    assert offen.status.value == "needs_input"  # bleibt »Angaben erforderlich«, schlägt nicht fehl
    assert app.batch_summary.created == 1 and app.batch_summary.skipped == 1 and app.batch_summary.failed == 0
    # nachträglich ergänzen und separat verarbeiten
    app.batch_edit(offen.id, number="777")
    pump(app, 0.2)
    assert offen.status.value == "ready"
    erstellen(app)
    assert offen.status.value == "success" and (tmp_path / "out" / "Vertragsuebersicht_Kd777.pdf").is_file()


def test_broken_or_empty_files_fail_alone(stapel_app, tmp_path: Path) -> None:
    app = stapel_app
    stapel(app, tmp_path / "out")
    kaputt = tmp_path / "kaputt.xlsx"
    kaputt.write_bytes(b"keine Excel-Datei")
    gut = excel(tmp_path / "gut.xlsx")
    leer = excel(tmp_path / "leer.xlsx", aktiv=0, inaktiv=2)
    app.batch_add([str(kaputt), str(gut), str(leer)])
    geprueft(app)
    app.batch_edit(eintrag(app, "gut.xlsx").id, company="Gut GmbH", number="1")
    pump(app, 0.2)
    assert status(app) == {"kaputt.xlsx": "failed", "gut.xlsx": "ready", "leer.xlsx": "failed"}
    rows = {row.title: row for row in app.ui.batch_list.rows}
    assert rows["leer.xlsx"].status == "Keine aktiven Verträge" and "0 aktive" not in rows["leer.xlsx"].facts
    assert rows["kaputt.xlsx"].status == "Excel nicht lesbar" and "(" not in rows["kaputt.xlsx"].detail
    erstellen(app)
    assert status(app) == {"kaputt.xlsx": "failed", "gut.xlsx": "success", "leer.xlsx": "failed"}
    assert sorted(p.name for p in (tmp_path / "out").iterdir()) == ["Vertragsuebersicht_Kd1.pdf"]
    assert app.batch_summary.failed == 2 and app.batch_summary.created == 1


def test_file_deleted_before_processing_fails_only_this_entry(stapel_app, tmp_path: Path, monkeypatch) -> None:
    app = stapel_app
    stapel(app, tmp_path / "out")
    files = [excel(tmp_path / f"liste_{i}.xlsx") for i in range(3)]
    app.batch_add([str(f) for f in files])
    geprueft(app)
    for index, item in enumerate(app.batch_items):
        app.batch_edit(item.id, company=f"Firma {index}", number=str(index + 10))
    pump(app, 0.2)
    from tools.contract_overview.batch import processor

    original = processor.run_job

    def run(job, cancelled):
        if job.excel == str(files[0]):
            files[1].unlink()  # während der Verarbeitung von Datei 1 wird Datei 2 gelöscht
        return original(job, cancelled)

    monkeypatch.setattr(processor, "run_job", run)
    erstellen(app)
    assert status(app) == {"liste_0.xlsx": "success", "liste_1.xlsx": "failed", "liste_2.xlsx": "success"}
    geloescht = eintrag(app, "liste_1.xlsx")
    assert geloescht.issues[0].code == "file_missing"
    assert {row.title: row.status for row in app.ui.batch_list.rows}["liste_1.xlsx"] == "Datei nicht gefunden"
    assert (app.batch_summary.created, app.batch_summary.failed, app.batch_summary.skipped) == (2, 1, 0)
    assert app.batch_page.result.text() == "2 Übersichten erstellt · 1 fehlgeschlagen"


def test_existing_pdf_is_never_overwritten_by_default(stapel_app, tmp_path: Path) -> None:
    app = stapel_app
    out = tmp_path / "out"
    out.mkdir()
    vorhanden = out / "Vertragsuebersicht_Kd42.pdf"
    vorhanden.write_bytes(b"%PDF-1.4 alte Datei")
    stapel(app, out)
    app.batch_add([str(excel(tmp_path / "a.xlsx"))])
    geprueft(app)
    item = app.batch_items[0]
    app.batch_edit(item.id, company="A", number="42")
    pump(app, 0.2)
    erstellen(app)
    assert vorhanden.read_bytes() == b"%PDF-1.4 alte Datei"
    assert item.status.value == "warning" and Path(item.output).name == "Vertragsuebersicht_Kd42_2.pdf"
    assert "gespeichert als »Vertragsuebersicht_Kd42_2.pdf«" in item.notes[0]
    assert not any(p.name.endswith(".tmp") for p in out.iterdir())


def test_customer_template_and_item_override(stapel_app, tmp_path: Path) -> None:
    app = stapel_app
    app.state.save_vorlage({"name": "Quer", "format": "quer"})
    app.state.save_vorlage({"name": "Hoch", "format": "hoch", "titel": "Hochformat"})
    app.customers.create("Beispiel GmbH", "100", ["rechnung@kunde-a.de"], template="Quer")
    app.customers.create("Muster AG", "200", ["buchhaltung@kunde-b.de"], template="Quer")
    stapel(app, tmp_path / "out")
    app.batch_add([str(excel(tmp_path / "a.xlsx")), str(excel(tmp_path / "b.xlsx", mails=("buchhaltung@kunde-b.de",)))])
    geprueft(app)
    b = eintrag(app, "b.xlsx")
    app.batch_apply_template("Hoch", [b.id])  # im Eintrag gesetzt: hat Vorrang vor der Kundenvorlage
    pump(app, 0.2)
    assert app.batch_resolution(b.id).template_source == "Eintrag"
    erstellen(app)
    breite, hoehe = pypdf.PdfReader(str(tmp_path / "out" / "Vertragsuebersicht_Kd100.pdf")).pages[0].mediabox.upper_right
    assert breite > hoehe  # Kundenvorlage »Quer«
    breite, hoehe = pypdf.PdfReader(str(tmp_path / "out" / "Vertragsuebersicht_Kd200.pdf")).pages[0].mediabox.upper_right
    assert breite < hoehe and "Hochformat" in pdf_text(tmp_path / "out" / "Vertragsuebersicht_Kd200.pdf")


def test_rich_text_and_standard_footer_per_customer(stapel_app, tmp_path: Path) -> None:
    import appstate
    from tools.contract_overview.customers.models import TextBlock

    app = stapel_app
    app.customers.create("Beispiel GmbH", "100", ["rechnung@kunde-a.de"], footer=TextBlock("Fußzeile für {firma}", None), header=TextBlock("Kopf Beispiel", None))
    app.customers.create("Muster AG", "200", ["buchhaltung@kunde-b.de"], footer=TextBlock("Sonderpreise Muster", None))
    app.customers.create("Leer GmbH", "300", ["info@leer.de"], footer=TextBlock("", None))  # alter leerer Wert
    stapel(app, tmp_path / "out")
    app.batch_add([str(excel(tmp_path / "a.xlsx")), str(excel(tmp_path / "b.xlsx", mails=("buchhaltung@kunde-b.de",))), str(excel(tmp_path / "c.xlsx", mails=("info@leer.de",)))])
    geprueft(app)
    erstellen(app)
    a = pdf_text(tmp_path / "out" / "Vertragsuebersicht_Kd100.pdf")
    b = pdf_text(tmp_path / "out" / "Vertragsuebersicht_Kd200.pdf")
    c = pdf_text(tmp_path / "out" / "Vertragsuebersicht_Kd300.pdf")
    assert "Fußzeile für Beispiel GmbH" in a and "Kopf Beispiel" in a and "Sonderpreise Muster" not in a
    assert "Sonderpreise Muster" in b and "Kopf Beispiel" not in b
    standard = " ".join(appstate.DEFAULT_FOOTER.split())
    assert standard[:60] in c  # die Standard-Fußzeile verschwindet nie


def test_preview_of_a_batch_entry_uses_the_same_pipeline(stapel_app, tmp_path: Path) -> None:
    app = stapel_app
    app.customers.create("Beispiel GmbH", "123456", ["rechnung@kunde-a.de"])
    stapel(app, tmp_path / "out")
    app.batch_add([str(excel(tmp_path / "a.xlsx"))])
    geprueft(app)
    item = app.batch_items[0]
    runs = app.preview_runs
    app.batch_preview(item.id)
    assert wait_until(app, lambda: app.preview_runs > runs and app.ui.preview_view.state == "current", 60)
    assert app.nav.current == "preview" and app.ui.preview_source.visible() and "a.xlsx" in app.ui.preview_source.message
    assert "Beispiel GmbH" in pdf_text(app._preview_doc.path) and "123456" in pdf_text(app._preview_doc.path)
    assert not (tmp_path / "out").exists() or not any((tmp_path / "out").iterdir())  # nichts im Zielordner
    app.nav.navigate("create", animate=False)
    pump(app, 0.2)
    assert app._preview_item is None  # beim nächsten Öffnen wieder die Einzelübersicht


def test_failed_job_does_not_stop_the_batch(stapel_app, tmp_path: Path) -> None:
    app = stapel_app
    stapel(app, tmp_path / "out")
    files = [str(excel(tmp_path / f"liste_{i:02d}.xlsx")) for i in range(10)]
    app.batch_add(files)
    geprueft(app)
    kaputt = tmp_path / "kaputt.png"
    kaputt.write_bytes(b"kein Bild")
    for index, item in enumerate(app.batch_items):
        app.batch_edit(item.id, company=f"Firma {index}", number=str(1000 + index), logo=str(kaputt) if index == 3 else None)
    pump(app, 0.2)
    erstellen(app)
    stati = [item.status.value for item in app.batch_items]
    assert stati[3] == "failed" and stati.count("success") == 9
    assert app.batch_items[3].error == "Das Logo ist keine lesbare Bilddatei."
    assert len(list((tmp_path / "out").iterdir())) == 9
    log = app.batch_log.path.read_text(encoding="utf-8")
    assert "liste_03.xlsx" in log and str(tmp_path) not in log  # keine vollständigen Pfade


def test_cancel_keeps_finished_pdfs_and_leaves_no_partial_files(stapel_app, tmp_path: Path, monkeypatch) -> None:
    app = stapel_app
    stapel(app, tmp_path / "out")
    app.batch_add([str(stapel_liste(tmp_path / f"liste_{i}.xlsx", aktiv=20)) for i in range(5)])
    geprueft(app)
    for index, item in enumerate(app.batch_items):
        app.batch_edit(item.id, company=f"Firma {index}", number=str(index + 1))
    pump(app, 0.2)
    from tools.contract_overview.batch import processor

    original = processor.run_job

    def slow(job, cancelled):
        result = original(job, cancelled)
        time.sleep(0.3)
        return result

    monkeypatch.setattr(processor, "run_job", slow)
    app.batch_start()
    assert wait_until(app, lambda: sum(item.status.value == "success" for item in app.batch_items) >= 2, 60)
    app.batch_page.btn_cancel.invoke()
    assert wait_until(app, lambda: not app.batch_running, 60)
    pump(app, 0.2)
    created = [item for item in app.batch_items if item.status.value == "success"]
    assert 2 <= len(created) < 5 and app.batch_summary.aborted
    assert [item.status.value for item in app.batch_items if item.status.value != "success"] == ["ready"] * (5 - len(created))
    names = sorted(p.name for p in (tmp_path / "out").iterdir())
    assert len(names) == len(created) and not any(name.endswith(".tmp") for name in names)
    for name in names:
        assert pypdf.PdfReader(str(tmp_path / "out" / name)).pages
    assert app.batch_page.result.title == "Stapel abgebrochen"


def test_cancel_during_a_running_pdf_counts_it_as_not_processed(stapel_app, tmp_path: Path, monkeypatch) -> None:
    app = stapel_app
    stapel(app, tmp_path / "out")
    app.batch_add([str(stapel_liste(tmp_path / f"liste_{i}.xlsx", aktiv=5)) for i in range(5)])
    geprueft(app)
    for index, item in enumerate(app.batch_items):
        app.batch_edit(item.id, company=f"Firma {index}", number=str(index + 1))
    pump(app, 0.2)
    from tools.contract_overview.batch import processor

    original = processor.run_job

    def run(job, cancelled):
        if job.label == "Firma 2":  # die dritte PDF läuft, als abgebrochen wird
            deadline = time.monotonic() + 30
            while not cancelled() and time.monotonic() < deadline:
                time.sleep(0.02)
        return original(job, cancelled)

    monkeypatch.setattr(processor, "run_job", run)
    app.batch_start()
    assert wait_until(app, lambda: app.batch_items[2].status.value == "processing", 60)
    app.batch_page.btn_cancel.invoke()
    assert wait_until(app, lambda: not app.batch_running, 60)
    pump(app, 0.2)
    assert [item.status.value for item in app.batch_items] == ["success", "success", "ready", "ready", "ready"]
    summary = app.batch_summary
    assert (summary.created, summary.skipped, summary.failed, summary.cancelled, summary.aborted) == (2, 0, 0, 3, True)
    assert app.batch_page.result.text() == "2 Übersichten erstellt · 3 nicht verarbeitet"
    names = sorted(p.name for p in (tmp_path / "out").iterdir())
    assert names == ["Vertragsuebersicht_Kd1.pdf", "Vertragsuebersicht_Kd2.pdf"]  # keine halbe dritte PDF


def test_retry_processes_only_failed_entries(stapel_app, tmp_path: Path) -> None:
    from PIL import Image

    app = stapel_app
    stapel(app, tmp_path / "out")
    app.batch_add([str(excel(tmp_path / "ok.xlsx")), str(excel(tmp_path / "logo.xlsx"))])
    geprueft(app)
    ok, logo_item = eintrag(app, "ok.xlsx"), eintrag(app, "logo.xlsx")
    kaputt = tmp_path / "logo.png"
    kaputt.write_bytes(b"kein Bild")
    app.batch_edit(ok.id, company="A", number="1")
    app.batch_edit(logo_item.id, company="B", number="2", logo=str(kaputt))
    pump(app, 0.2)
    erstellen(app)
    assert (ok.status.value, logo_item.status.value) == ("success", "failed")
    first = Path(ok.output).stat().st_mtime_ns
    Image.new("RGB", (40, 20), "blue").save(kaputt)  # Fehler behoben
    app.batch_page.btn_retry.invoke()
    assert wait_until(app, lambda: not app.batch_running and logo_item.status.value == "success", 60)
    assert Path(ok.output).stat().st_mtime_ns == first  # der erfolgreiche Eintrag wurde nicht erneut erstellt
    assert sorted(p.name for p in (tmp_path / "out").iterdir()) == ["Vertragsuebersicht_Kd1.pdf", "Vertragsuebersicht_Kd2.pdf"]


def test_customer_record_gets_only_activity_metadata(stapel_app, tmp_path: Path) -> None:
    app = stapel_app
    kunde = app.customers.create("Beispiel GmbH", "100", ["rechnung@kunde-a.de"], template="", logo="", target_dir="")
    before = kunde.to_dict()
    stapel(app, tmp_path / "out")
    app.batch_add([str(excel(tmp_path / "a.xlsx"))])
    geprueft(app)
    item = app.batch_items[0]
    app.batch_apply_template("", [item.id])  # nur für den Eintrag
    app.batch_edit(item.id, target_dir=str(tmp_path / "eigen"))
    pump(app, 0.2)
    erstellen(app)
    after = app.customers.get(kunde.id).to_dict()
    assert after["last_excel"] == item.path and after["last_pdf"] == item.output and after["last_used_at"] > (before["last_used_at"] or "")
    for key in ("company", "number", "emails", "logo", "target_dir", "template", "header", "footer"):
        assert after[key] == before[key], key  # keine Darstellungswerte ungefragt gespeichert
    saved = json.loads((Path(app.customers.path)).read_text(encoding="utf-8"))
    assert any(entry.get("last_pdf") == item.output for entry in saved["customers"])


def test_new_email_is_only_learned_after_remember(stapel_app, tmp_path: Path) -> None:
    app = stapel_app
    kunde = app.customers.create("Beispiel GmbH", "100", ["rechnung@kunde-a.de"])
    stapel(app, tmp_path / "out")
    app.batch_add([str(excel(tmp_path / "neu.xlsx", mails=("neu@kunde-a.de",))), str(excel(tmp_path / "noch.xlsx", mails=("neu@kunde-a.de",)))])
    geprueft(app)
    neu, noch = eintrag(app, "neu.xlsx"), eintrag(app, "noch.xlsx")
    app.batch_page.show_detail(neu.id)
    app.batch_choose_customer(neu.id)  # manuell gewählt (Dialog: erster Kunde)
    pump(app, 0.2)
    assert app.customers.get(kunde.id).emails == ["rechnung@kunde-a.de"]  # nicht automatisch gelernt
    bar = app.ui.batch_mail_info
    assert bar.visible() and bar.title == "Diese E-Mail künftig diesem Kunden zuordnen?"
    assert noch.status.value == "needs_input"
    app.batch_remember_emails(neu.id)
    pump(app, 0.2)
    assert "neu@kunde-a.de" in app.customers.get(kunde.id).emails
    assert app.batch_resolution(noch.id).customer_source == "erkannt" and noch.status.value == "ready"  # jetzt wiedererkannt


def test_customer_changes_apply_but_item_values_stay(stapel_app, tmp_path: Path) -> None:
    app = stapel_app
    kunde = app.customers.create("Beispiel GmbH", "100", ["rechnung@kunde-a.de"])
    stapel(app, tmp_path / "out")
    app.batch_add([str(excel(tmp_path / "a.xlsx"))])
    geprueft(app)
    item = app.batch_items[0]
    app.batch_edit(item.id, number="555")  # bewusst im Eintrag
    app.customers.update(kunde.id, company="Beispiel GmbH & Co. KG", number="101")
    app.customers_changed()
    pump(app, 0.2)
    res = app.batch_resolution(item.id)
    assert res.company == "Beispiel GmbH & Co. KG" and res.number == "555"
    app.customers.delete(kunde.id)
    app.customers_changed()
    pump(app, 0.2)
    assert app.batch_resolution(item.id).customer is None and item.status.value == "needs_input"


def test_changed_excel_is_checked_again_before_processing(stapel_app, tmp_path: Path) -> None:
    app = stapel_app
    app.customers.create("Beispiel GmbH", "100", ["rechnung@kunde-a.de"])
    app.customers.create("Muster AG", "200", ["buchhaltung@kunde-b.de"])
    stapel(app, tmp_path / "out")
    pfad = excel(tmp_path / "a.xlsx")
    app.batch_add([str(pfad)])
    geprueft(app)
    item = app.batch_items[0]
    assert app.batch_resolution(item.id).customer.company == "Beispiel GmbH"
    excel(pfad, mails=("buchhaltung@kunde-b.de",))  # jetzt die Liste eines anderen Kunden
    os.utime(pfad, ns=(item.stamp.mtime_ns + 5_000_000_000,) * 2)
    erstellen(app)
    assert not (tmp_path / "out" / "Vertragsuebersicht_Kd100.pdf").exists()  # nie mit der alten Zuordnung
    assert item.status.value == "ready" and app.batch_resolution(item.id).customer.company == "Muster AG"
    assert any("geändert" in note for note in item.notes)
    erstellen(app)
    assert (tmp_path / "out" / "Vertragsuebersicht_Kd200.pdf").is_file()


def test_filters_and_bulk_actions(stapel_app, tmp_path: Path) -> None:
    app = stapel_app
    app.state.save_vorlage({"name": "Quer", "format": "quer"})
    app.customers.create("Beispiel GmbH", "100", ["rechnung@kunde-a.de"])
    stapel(app, tmp_path / "out")
    app.batch_add([str(excel(tmp_path / "a.xlsx")), str(excel(tmp_path / "b.xlsx", mails=("x@y.de",))), str(excel(tmp_path / "c.xlsx", mails=("z@y.de",)))])
    geprueft(app)
    app.ui.batch_filters._activate("needs_input")
    pump(app, 0.2)
    assert [row.title for row in app.ui.batch_list.rows] == ["b.xlsx", "c.xlsx"]
    app.batch_page.check_all.activate()  # »Alle auswählen«
    pump(app, 0.2)
    assert [item.name for item in app.batch_selected()] == ["b.xlsx", "c.xlsx"]  # nur die sichtbaren
    app.batch_page.apply_template()
    pump(app, 0.2)
    assert [item.overrides.template for item in app.batch_items] == [None, "Quer", "Quer"]
    app.batch_page.btn_remove.invoke()
    pump(app, 0.2)
    assert [item.name for item in app.batch_items] == ["a.xlsx"]
    from test_app_v24 import klicken

    klicken(app.ui.batch_info, "Rückgängig")
    pump(app, 0.2)
    assert [item.name for item in app.batch_items] == ["a.xlsx", "b.xlsx", "c.xlsx"]
    app.ui.batch_filters._activate("all")
    pump(app, 0.2)
    assert len(app.ui.batch_list.rows) == 3


def test_queue_is_restored_after_a_restart(stapel_app, tmp_path: Path, config_file: Path) -> None:
    app = stapel_app
    stapel(app, tmp_path / "out")
    app.batch_add([str(excel(tmp_path / "a.xlsx")), str(excel(tmp_path / "b.xlsx", mails=("x@y.de",)))])
    geprueft(app)
    a, b = app.batch_items
    app.batch_edit(a.id, company="A", number="1")
    app.batch_edit(b.id, company="B GmbH")
    pump(app, 0.2)
    erstellen(app)
    assert a.status.value == "success"
    neu = neustart(app)
    try:
        assert [item.name for item in neu.batch_items] == ["a.xlsx", "b.xlsx"]
        assert neu.batch_items[0].status.value == "success" and neu.batch_items[0].output == a.output
        geprueft(neu)
        assert neu.batch_items[1].overrides.company == "B GmbH" and neu.batch_items[1].status.value == "needs_input"
        assert neu.batch_settings.target_dir == str(tmp_path / "out")
        saved = json.loads((config_file.parent / "stapel.json").read_text(encoding="utf-8"))
        assert "analysis" not in json.dumps(saved) and "Modul" not in json.dumps(saved)  # nur Pfade und Angaben
    finally:
        schliessen(neu)


def test_new_batch_keeps_customers_templates_and_settings(stapel_app, tmp_path: Path) -> None:
    app = stapel_app
    app.state.save_vorlage({"name": "Quer", "format": "quer"})
    kunde = app.customers.create("Beispiel GmbH", "100", ["rechnung@kunde-a.de"])
    stapel(app, tmp_path / "out")
    app.batch_update_settings(template="Quer", subfolders=True)
    pfad = excel(tmp_path / "a.xlsx")
    app.batch_add([str(pfad)])
    geprueft(app)
    app.batch_new()  # Dialog bestätigt im Test
    pump(app, 0.2)
    assert app.batch_items == [] and app.batch_page.empty.winfo_manager()
    assert app.customers.get(kunde.id) is not None and app.state.find_vorlage("Quer") is not None
    assert app.batch_settings.template == "Quer" and app.batch_settings.subfolders
    assert pfad.is_file()


def test_edit_single_takes_the_entry_into_the_single_workflow(stapel_app, tmp_path: Path) -> None:
    app = stapel_app
    kunde = app.customers.create("Beispiel GmbH", "100", ["rechnung@kunde-a.de"])
    stapel(app, tmp_path / "out")
    pfad = excel(tmp_path / "a.xlsx")
    app.batch_add([str(pfad)])
    geprueft(app)
    app.var_firma.set("Vorher AG")
    app.batch_edit_single(app.batch_items[0].id)
    assert wait_until(app, lambda: app._analysis_path == str(pfad) and app._analysis is not None, 60)
    pump(app, 0.3)
    assert app.nav.current == "create" and app.var_excel.get() == str(pfad)
    assert app.active_customer() is not None and app.active_customer().id == kunde.id
    assert (app.var_firma.get(), app.var_kd.get()) == ("Beispiel GmbH", "100")
    assert len(app.batch_items) == 1  # der Stapel-Eintrag bleibt
    app._undo_new_overview()
    pump(app, 0.2)
    assert app.var_firma.get() == "Vorher AG"


def test_single_mode_and_repair_still_work_after_a_batch(stapel_app, tmp_path: Path, excel_file: Path) -> None:
    import pdfsamples as samples

    app = stapel_app
    stapel(app, tmp_path / "out")
    app.batch_add([str(excel(tmp_path / "a.xlsx"))])
    geprueft(app)
    app.batch_edit(app.batch_items[0].id, company="A", number="1")
    pump(app, 0.2)
    erstellen(app)
    # Einzelmodus unverändert
    app.nav.navigate("create", animate=False)
    app.var_ziel.set(str(tmp_path / "einzel"))
    app.var_open.set(False)
    app.use_excel(str(excel_file))
    assert wait_until(app, lambda: app.ui.ready.kind == "success", 60)
    app.start_pdf()
    assert wait_until(app, lambda: not app.busy, 90)
    assert app.ui.pdf_info.severity == "success" and (tmp_path / "einzel" / "Vertragsuebersicht_Kd10042.pdf").is_file()
    # PDF reparieren: unabhängig vom Stapel
    app.open_tool("repair")
    pdf = samples.xref_offset(tmp_path / "defekt.pdf")
    app.repair.use(str(pdf))
    assert wait_until(app, lambda: not app.repair.busy and app.repair.analysis is not None, 90)
    assert app.repair.analysis.condition.value == "repairable"
    assert len(app.batch_items) == 1 and app.batch_items[0].status.value == "success"


def test_close_during_a_batch_cancels_cleanly(stapel_app, tmp_path: Path, monkeypatch) -> None:
    app = stapel_app
    stapel(app, tmp_path / "out")
    app.batch_add([str(stapel_liste(tmp_path / f"liste_{i}.xlsx", aktiv=20)) for i in range(4)])
    geprueft(app)
    for index, item in enumerate(app.batch_items):
        app.batch_edit(item.id, company=f"F{index}", number=str(index + 1))
    pump(app, 0.2)
    from tools.contract_overview.batch import processor

    original = processor.run_job
    monkeypatch.setattr(processor, "run_job", lambda job, cancelled: (time.sleep(0.4), original(job, cancelled))[1])
    app.batch_start()
    assert wait_until(app, lambda: app.batch_runner is not None and app.batch_runner.current is not None, 30)
    app._on_close()  # Rückfrage bestätigt der Test
    out = tmp_path / "out"
    names = [p.name for p in out.iterdir()] if out.exists() else []
    assert not any(name.endswith(".tmp") for name in names)
    for name in names:
        assert pypdf.PdfReader(str(out / name)).pages
