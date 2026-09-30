"""Oberflächentests für Version 2.6: Vertragsvergleich (Einzelmodus und Stapel) und erweiterte
PDF-Wiederherstellung in »PDF reparieren«."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

import pdfsamples as samples
from conftest import display_available, pump, schliessen, wait_until, write_excel

pytestmark = pytest.mark.skipif(not display_available(), reason="kein Display verfügbar")

SPALTEN = ["Vertrag-Nr.", "Beginnt am", "Abrechnungszyklus", "Netto [€]", "Zahlungsart", "Bemerkung", "Rechnungsempfänger Email", "Anwenderstatus"]
STAND_1 = [
    ("10001", datetime(2024, 1, 1), "jährlich", 250.0, "Lastschrift", "GetSolar"),
    ("10002", datetime(2023, 5, 1), "monatlich", 49.9, "Lastschrift", "Hotline Premium"),
    ("10003", datetime(2022, 3, 1), "jährlich", 120.0, "Überweisung", "Alte Schnittstelle"),
    ("10004", datetime(2021, 7, 1), "jährlich", 300.0, "Lastschrift", "Warenwirtschaft"),
    ("10005", datetime(2020, 2, 1), "vierteljährlich", 75.5, "Lastschrift", "Datensicherung"),
]
# 10001 teurer, 10003 entfernt, 10006 und 10007 neu, 10002/10004/10005 unverändert
STAND_2 = [
    ("10001", datetime(2024, 1, 1), "jährlich", 270.0, "Lastschrift", "GetSolar"),
    *STAND_1[1:2],
    *STAND_1[3:],
    ("10006", datetime(2026, 8, 1), "monatlich", 19.0, "Lastschrift", "Cloud-Speicher"),
    ("10007", datetime(2026, 8, 1), "jährlich", 99.0, "Lastschrift", "KI-Assistent"),
]


@pytest.fixture
def app26(config_file: Path, monkeypatch):
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


def liste(pfad: Path, vertraege, mail: str = "rechnung@kunde.de") -> Path:
    return write_excel(pfad, [[nummer, beginn, zyklus, netto, zahlung, text, mail, "Aktiv"] for nummer, beginn, zyklus, netto, zahlung, text in vertraege], SPALTEN)


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


def staende(config_file: Path, kunde) -> list[dict]:
    folder = config_file.parent / "contract-history" / kunde.id
    return [json.loads(path.read_text(encoding="utf-8")) for path in sorted(folder.glob("*.json"))] if folder.is_dir() else []


def ansicht(app):
    return app.ui.comparison


# --- Einzelmodus ---------------------------------------------------------------------------------------------------


def test_comparison_needs_a_customer_record(app26, tmp_path: Path, config_file: Path) -> None:
    from tools.contract_overview.history_flow import NO_CUSTOMER

    app = app26
    assert not app.ui.comparison_area.expanded  # ohne geprüfte Excel keine Karte
    pruefen(app, liste(tmp_path / "ohne.xlsx", STAND_1, mail="info@unbekannt.de"))
    assert app.ui.comparison_area.expanded
    view = ansicht(app)
    assert view.info.message == NO_CUSTOMER and not view.body.winfo_manager()
    app.var_kd.set("99")
    app.var_firma.set("Ohne Akte GmbH")
    exportieren(app, tmp_path / "out")
    assert not (config_file.parent / "contract-history").exists()  # ohne Kundenakte kein Stand


def test_first_export_saves_the_first_state_and_nothing_before(app26, tmp_path: Path, config_file: Path) -> None:
    from tools.contract_overview.history.report import NO_HISTORY
    from tools.contract_overview.history_flow import FIRST_SAVED

    app = app26
    kunde = app.customers.create("Kunde GmbH", "4711", ["rechnung@kunde.de"])
    pruefen(app, liste(tmp_path / "stand1.xlsx", STAND_1))
    app.apply_customer(kunde.id)
    pump(app, 0.2)
    view = ansicht(app)
    assert view.info.message.startswith(NO_HISTORY)
    # Vorschau und Excel-Prüfung speichern keinen Stand
    app.nav.navigate("preview", animate=False)
    assert wait_until(app, lambda: app._preview_building is None and app._preview_doc is not None, 60)
    app.nav.navigate("create", animate=False)
    assert staende(config_file, kunde) == []
    exportieren(app, tmp_path / "out")
    saved = staende(config_file, kunde)
    assert len(saved) == 1 and saved[0]["schema_version"] == 1 and saved[0]["customer_id"] == kunde.id
    # Reihenfolge wie in der PDF (nach Vertragsbeginn), Werte wie gedruckt, normalisiert
    assert [c["contract_number"] for c in saved[0]["contracts"]] == ["10005", "10004", "10003", "10002", "10001"]
    first = saved[0]["contracts"][-1]["effective"]
    assert first["net_amount"] == "250.00" and first["start_date"] == "2024-01-01" and first["billing_cycle"] == "jährlich"
    assert (view.info.title, view.info.message) == ("Vertragsstand gespeichert", FIRST_SAVED)
    # Gleiche Verträge noch einmal erstellt: kein zweiter Stand, nur gezählt
    exportieren(app, tmp_path / "out2")
    saved = staende(config_file, kunde)
    assert len(saved) == 1 and saved[0]["export_count"] == 2


def test_changes_since_the_last_state(app26, tmp_path: Path, config_file: Path) -> None:
    app = app26
    kunde = app.customers.create("Kunde GmbH", "4711", ["rechnung@kunde.de"])
    pruefen(app, liste(tmp_path / "stand1.xlsx", STAND_1))
    app.apply_customer(kunde.id)
    exportieren(app, tmp_path / "out")
    pruefen(app, liste(tmp_path / "stand2.xlsx", STAND_2))
    assert app.active_customer() is kunde  # Kundenakte bleibt aktiv (gleiche E-Mail)
    view = ansicht(app)
    assert view.body.winfo_manager() and not view.info.visible()
    assert view.headline.cget("text") == f"Seit {datetime.now().strftime('%d.%m.%Y')}"
    assert view.counts.text() == "2 neu · 1 entfernt · 1 geändert · 3 unverändert"
    assert view.changes.visible_text() == [
        "Neu: 10006 Cloud-Speicher – 19,00 €",
        "Neu: 10007 KI-Assistent – 99,00 €",
        "Entfernt: 10003 Alte Schnittstelle – nicht mehr in der Excel",
        "Geändert: 10001 GetSolar – Netto 250,00 € → 270,00 €",
    ]
    assert view.selected_label().startswith("Letzter Stand (")
    # Einzelheiten aufklappen, unveränderte nur auf Wunsch
    view.changes.toggle("10001")
    assert "  Netto: 250,00 € → 270,00 €" in view.changes.visible_text()
    assert view.btn_unchanged.text() == "3 unveränderte anzeigen"
    view.btn_unchanged.invoke()
    pump(app, 0.1)
    assert sum(line.startswith("Unverändert:") for line in view.changes.visible_text()) == 3
    assert view.btn_unchanged.text() == "Unveränderte ausblenden"
    # Kopieren und Wechsel des Vergleichs lösen keine neue Vorschau aus
    runs = app.preview_runs
    view.btn_copy.invoke()
    text = app.clipboard_get()
    assert text.startswith("Vertragsänderungen – Kunde GmbH") and "Netto: 250,00 € → 270,00 €" in text and "10006 Cloud-Speicher" in text
    pump(app, 0.3)
    assert app.preview_runs == runs
    # Nach dem Erstellen bleibt der Vergleich sichtbar; der neue Stand ist wählbar
    exportieren(app, tmp_path / "out")
    assert len(staende(config_file, kunde)) == 2
    labels = view.baseline.values()
    assert labels[0].startswith("Gerade gespeichert (") and labels[1].startswith("Letzter Stand (")
    assert view.counts.text() == "2 neu · 1 entfernt · 1 geändert · 3 unverändert"
    view._picked(labels[0])
    pump(app, 0.1)
    assert view.headline.cget("text").startswith("Keine Änderungen seit") and view.counts.text() == "6 unverändert"
    assert app.preview_runs == runs


def test_states_of_different_customers_never_mix(app26, tmp_path: Path, config_file: Path) -> None:
    from tools.contract_overview.history.report import NO_HISTORY

    app = app26
    a = app.customers.create("Alpha GmbH", "1", ["rechnung@kunde.de"])
    b = app.customers.create("Alpha GmbH", "2", ["einkauf@alpha.de"])  # gleicher Firmenname, andere Kundenakte
    pruefen(app, liste(tmp_path / "a.xlsx", STAND_1))
    app.apply_customer(a.id)
    exportieren(app, tmp_path / "out")
    pruefen(app, liste(tmp_path / "b.xlsx", STAND_2, mail="einkauf@alpha.de"))
    app.apply_customer(b.id)
    pump(app, 0.2)
    assert app.active_customer() is b
    assert ansicht(app).info.message.startswith(NO_HISTORY) and app.comparison is None
    assert len(staende(config_file, a)) == 1 and staende(config_file, b) == []


def test_failed_export_saves_no_state(app26, tmp_path: Path, config_file: Path, monkeypatch) -> None:
    import engine

    app = app26
    kunde = app.customers.create("Kunde GmbH", "4711", ["rechnung@kunde.de"])
    pruefen(app, liste(tmp_path / "stand1.xlsx", STAND_1))
    app.apply_customer(kunde.id)

    def kaputt(job):
        raise OSError("Datenträger voll")

    monkeypatch.setattr(engine, "erstelle_pdf", kaputt)
    app.var_ziel.set(str(tmp_path / "out"))
    app.var_open.set(False)
    app.start_pdf()
    assert wait_until(app, lambda: not app.busy, 60)
    pump(app, 0.2)
    assert app.ui.pdf_info.severity == "error"
    assert staende(config_file, kunde) == []


def test_old_files_are_not_needed_for_the_comparison(app26, tmp_path: Path, config_file: Path) -> None:
    app = app26
    kunde = app.customers.create("Kunde GmbH", "4711", ["rechnung@kunde.de"])
    erste = liste(tmp_path / "stand1.xlsx", STAND_1)
    pruefen(app, erste)
    app.apply_customer(kunde.id)
    exportieren(app, tmp_path / "out")
    for pdf in (tmp_path / "out").glob("*.pdf"):
        pdf.unlink()
    erste.unlink()
    pruefen(app, liste(tmp_path / "stand2.xlsx", STAND_2))
    view = ansicht(app)
    assert view.counts.text() == "2 neu · 1 entfernt · 1 geändert · 3 unverändert"
    meta = {label: value for label, value, _tone in view.meta.facts()}
    assert meta["Excel"] == "stand1.xlsx (nicht mehr vorhanden)" and meta["PDF"].endswith("(nicht mehr vorhanden)")


def test_comparison_card_follows_theme_and_width(app26, tmp_path: Path, monkeypatch) -> None:
    """Die Liste ist gezeichnet: kein Auf- und Abbau von Widgets bei Breite oder Farbschema."""
    from ui.context import surface_color

    app = app26
    errors: list = []
    monkeypatch.setattr(app, "report_callback_exception", lambda exc, val, tb: errors.append(val))
    kunde = app.customers.create("Kunde GmbH", "4711", ["rechnung@kunde.de"])
    pruefen(app, liste(tmp_path / "stand1.xlsx", STAND_1))
    app.apply_customer(kunde.id)
    exportieren(app, tmp_path / "out")
    pruefen(app, liste(tmp_path / "stand2.xlsx", STAND_2))
    view = ansicht(app)
    height = view.changes.winfo_height()
    children = len(view.changes.winfo_children())
    for size in ("760x560", "1500x950", "1100x800"):
        app.geometry(size)
        pump(app, 0.4)
        assert view.changes.winfo_height() == height
    app.set_theme("dark")
    pump(app, 0.4)
    assert view.changes.cget("bg") == surface_color(view.changes.master) and view.counts.cget("bg") == surface_color(view.counts.master)
    app.set_theme("light")
    pump(app, 0.3)
    assert len(view.changes.winfo_children()) == children == 0 and errors == []


# --- Stapel -----------------------------------------------------------------------------------------------------------


def stapel(app, target: Path):
    app.nav.navigate("batch", animate=False)
    pump(app, 0.2)
    app.batch_update_settings(target_dir=str(target))
    return app.batch_page


def geprueft(app, timeout: float = 90) -> None:
    from tools.contract_overview.batch.models import WAITING

    assert wait_until(app, lambda: app.batch_items and all(item.status not in WAITING for item in app.batch_items), timeout)
    pump(app, 0.2)


def erstellen(app, timeout: float = 180) -> None:
    app.batch_start()
    assert wait_until(app, lambda: not app.batch_running, timeout)
    pump(app, 0.2)


def test_batch_saves_one_state_per_created_item(app26, tmp_path: Path, config_file: Path) -> None:
    app = app26
    a = app.customers.create("Alpha GmbH", "100", ["rechnung@alpha.de"])
    b = app.customers.create("Beta AG", "200", ["rechnung@beta.de"])
    stapel(app, tmp_path / "out")
    leer = write_excel(tmp_path / "leer.xlsx", [["20001", datetime(2024, 1, 1), "jährlich", 10.0, "Sofort", "Alt", "rechnung@beta.de", "Inaktiv"]], SPALTEN)
    app.batch_add([str(liste(tmp_path / "alpha.xlsx", STAND_1, "rechnung@alpha.de")), str(liste(tmp_path / "beta.xlsx", STAND_1[:2], "rechnung@beta.de")), str(leer), str(liste(tmp_path / "fremd.xlsx", STAND_1, "info@fremd.de"))])
    geprueft(app)
    app.batch_edit(next(i for i in app.batch_items if i.name == "fremd.xlsx").id, company="Fremd GmbH", number="300")
    pump(app, 0.2)
    erstellen(app)
    status = {item.name: item.status.value for item in app.batch_items}
    assert status["alpha.xlsx"] == status["beta.xlsx"] == status["fremd.xlsx"] == "success"
    assert status["leer.xlsx"] != "success"
    # je erfolgreich erstelltem Eintrag mit Kundenakte ein Stand – nie für übersprungene oder fehlgeschlagene
    assert len(staende(config_file, a)) == 1 and len(staende(config_file, b)) == 1
    assert sorted(p.name for p in (config_file.parent / "contract-history").iterdir()) == sorted([a.id, b.id])
    assert [c["contract_number"] for c in staende(config_file, b)[0]["contracts"]] == ["10002", "10001"]  # wie in der PDF
    # übersprungen (PDF vorhanden): kein Stand, obwohl sich die Verträge geändert haben
    from tools.contract_overview.batch.models import ConflictMode

    app.batch_update_settings(conflict=ConflictMode.SKIP)
    app.batch_new()
    pump(app, 0.2)
    app.batch_add([str(liste(tmp_path / "beta2.xlsx", STAND_2, "rechnung@beta.de"))])
    geprueft(app)
    erstellen(app)
    assert app.batch_items[0].status.value == "skipped" and len(staende(config_file, b)) == 1
    app.batch_update_settings(conflict=ConflictMode.NUMBER)
    # nächster Stapel: kompakte Angaben in der Liste, Einzelheiten in der Detailansicht
    app.batch_new()
    pump(app, 0.2)
    app.batch_add([str(liste(tmp_path / "alpha2.xlsx", STAND_2, "rechnung@alpha.de"))])
    geprueft(app)
    row = app.ui.batch_list.rows[0]
    assert row.facts.endswith("+2 neu · ~1 geändert · −1 entfernt"), row.facts
    item = app.batch_items[0]
    app.batch_page.show_detail(item.id)
    pump(app, 0.2)
    detail = app.batch_page.d_changes
    assert detail.counts.text() == "2 neu · 1 entfernt · 1 geändert · 3 unverändert"
    assert detail.selected_label().startswith("Letzter Stand (")
    erstellen(app)
    assert len(staende(config_file, a)) == 2
    pump(app, 0.2)
    # Der Vergleich bleibt nach dem Erstellen sichtbar (gegen den vorherigen Stand)
    assert app.batch_page.d_changes.counts.text() == "2 neu · 1 entfernt · 1 geändert · 3 unverändert"


# --- PDF reparieren: erweiterte Wiederherstellung -----------------------------------------------------------------------


def test_raw_recoverable_file_offers_the_structure_rebuild(app26, tmp_path: Path) -> None:
    app = app26
    pdf = samples.real_case(tmp_path / "Vertrag März.pdf")
    before = pdf.read_bytes()
    app.open_tool("repair")
    app.repair.use(str(pdf))
    assert wait_until(app, lambda: not app.repair.busy and app.repair.analysis is not None, 90)
    pump(app, 0.2)
    ui = app.repair.ui
    analysis = app.repair.analysis
    assert analysis.condition.value == "raw_recoverable"
    assert ui.analysis_info.severity == "warning" and ui.analysis_info.title == "Erweiterte Wiederherstellung möglich"
    assert "PDF Tool versucht, die noch vorhandenen Inhalte wiederherzustellen." in ui.analysis_info.message
    assert "Datenströme" in ui.analysis_info.message
    assert ui.btn_repair.text() == "PDF-Struktur rekonstruieren" and ui.btn_repair.enabled()
    facts = {label: value for label, value, _tone in ui.analysis_facts.facts()}
    assert facts["Seiten"] == "3 gefunden" and "Objektkandidaten" not in facts  # Technik nur in den Details
    details = {label: value for label, value, _tone in ui.details_facts.facts()}
    assert details["Objektkandidaten"].startswith("9 gefunden") and details["Seitenobjekte (/Page)"] == "3"
    assert details["Trailer-Wörterbuch"] == "fehlt" and details["%%EOF"] == "fehlt"
    app.repair.start_repair()
    assert wait_until(app, lambda: not app.repair.busy and app.repair.result is not None, 120)
    pump(app, 0.2)
    result = app.repair.result
    assert result.status.value == "repaired" and result.method.value == "page_tree_rebuild"
    assert ui.result_info.severity == "success" and ui.result_info.title == "PDF-Struktur wurde rekonstruiert."
    assert app.repair.output == tmp_path / "Vertrag März_repariert.pdf" and app.repair.output.is_file()
    assert pdf.read_bytes() == before
