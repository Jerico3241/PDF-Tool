"""Qt-Oberfläche: Vertragsvergleich in »Vertragsübersichten« – Einzelmodus und Stapel (2.7.0).

Ersetzt die Tk-Tests des Vertragsvergleichs aus test_app_v26. Ein Vertragsstand entsteht nur
nach einer erfolgreich erstellten PDF mit Kundenakte; der Vergleich ist eine reine Anzeige
(``ComparisonController`` – in QML ``Comparison`` – mit ``ComparisonView`` und ihrem Listenmodell).
In »Übersicht erstellen« steht die Kurzfassung (``ComparisonSummary``), die Einzelheiten zeigt die
Ansicht »Vergleich« (``comparisonPage``, nur mit Kundenakte). Die Kundenakte ist eingeschaltet
(Konfiguration der Fixture ``ui_app``). Nach jedem Test darf die QML-Engine keine Warnung
gemeldet haben.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from conftest import pump, wait_until, write_excel

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
AENDERUNGEN = "2 neu · 1 entfernt · 1 geändert · 3 unverändert"


def liste(pfad: Path, vertraege, mail: str = "rechnung@kunde.de") -> Path:
    return write_excel(pfad, [[nummer, beginn, zyklus, netto, zahlung, text, mail, "Aktiv"] for nummer, beginn, zyklus, netto, zahlung, text in vertraege], SPALTEN)


def kunde_anlegen(h, company: str, number: str, emails: list[str]):
    """Kundenakte wie in der Ansicht »Kunden« angelegt (mit E-Mail-Zuordnung)."""
    kunde = h.customers.customers.create(company, number, emails)
    h.customers.customers_changed()
    return kunde


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


def staende(config_file: Path, kunde) -> list[dict]:
    folder = config_file.parent / "contract-history" / kunde.id
    return [json.loads(path.read_text(encoding="utf-8")) for path in sorted(folder.glob("*.json"))] if folder.is_dir() else []


def ansicht(h):
    return h.comparison.single


def zaehler(view) -> str:
    """»2 neu · 1 entfernt · …« wie in der Zählleiste."""
    return " · ".join(item["text"] for item in view.counts)


def zeilen(view) -> list[str]:
    """Sichtbare Zeilen der Änderungsliste (aufgeklappte mit ihren Einzelheiten)."""
    lines = []
    for row in view.changeModel.items():
        lines.append(f"{row['kindLabel']}: {row['title']}" + (f" – {row['summary']}" if row["summary"] else ""))
        if row["expanded"]:
            lines += [f"  {detail['field']}: {detail['change']}" for detail in row["details"]]
    return lines


def gewaehlt(view) -> str:
    """Beschriftung des gewählten Stands in »Vergleichen mit«."""
    return next(choice["label"] for choice in view.choices if choice["value"] == view.baseline)


def typ_von(item) -> str:
    """QML-Typ eines Elements (»ComparisonSummary«, »PCard« …) aus seiner JavaScript-Darstellung.

    Bewusst nicht über ``metaObject()``: PySide hängt dessen Rückgabe an den Wrapper des Elements.
    Überlebt der Wrapper die QML-Engine (z. B. im Traceback eines fehlgeschlagenen Tests), liefert
    PySide später für ein neues Element an derselben Adresse dieses veraltete QMetaObject.
    """
    from PySide6.QtQml import QQmlEngine

    context = QQmlEngine.contextForObject(item)
    if context is None or context.engine() is None:
        return ""  # nicht aus QML (z. B. die Inhaltsebene des Fensters)
    return context.engine().toScriptValue(item).toString().split("(", 1)[0].split("_QML", 1)[0]


def elemente(root, typ: str) -> list:
    """QML-Elemente eines Typs (z. B. »ComparisonSummary«) unterhalb von ``root``."""
    found = []
    stack = [root]
    while stack:
        item = stack.pop()
        if typ_von(item) == typ:
            found.append(item)
        stack.extend(reversed(item.childItems()))
    return found


def vorfahr(item, typ: str):
    current = item.parentItem()
    while current is not None and typ_von(current) != typ:
        current = current.parentItem()
    return current


def zeiger(items) -> set[int]:
    import shiboken6

    return {shiboken6.getCppPointer(item)[0] for item in items}


def kurzfassung(h):
    """Die Karte »Vertragsänderungen« in »Übersicht erstellen«."""
    found = elemente(h.item("createPage"), "ComparisonSummary")
    assert len(found) == 1
    return found[0]


def zwischenablage() -> str:
    from PySide6.QtGui import QGuiApplication

    return QGuiApplication.clipboard().text()


# --- Einzelmodus ---------------------------------------------------------------------------------------------------


def test_comparison_needs_a_customer_record(ui_app, tmp_path: Path, config_file: Path) -> None:
    from qtapp.contracts.comparison import NO_CUSTOMER

    h = ui_app
    h.navigate("create", 0.3)
    summary = kurzfassung(h)
    assert not h.comparison.visible and not summary.property("visible")  # ohne geprüfte Excel keine Karte
    pruefen(h, liste(tmp_path / "ohne.xlsx", STAND_1, mail="info@unbekannt.de"))
    pump(0.3)
    assert h.comparison.visible and summary.property("visible")
    view = ansicht(h)
    assert view.mode == "message" and view.noteText == NO_CUSTOMER and view.rowCount == 0
    assert h.comparison.comparison is None and zaehler(view) == ""
    # Auch die Ansicht »Vergleich« zeigt nur den Hinweis
    h.navigate("comparison", 0.3)
    assert h.item("comparisonPage").property("visible") and h.item("comparisonPage").property("count") == 0
    h.overview.kd = "99"
    h.overview.firma = "Ohne Akte GmbH"
    h.navigate("create", 0.1)
    exportieren(h, tmp_path / "out")
    assert list((tmp_path / "out").glob("*.pdf"))
    assert not (config_file.parent / "contract-history").exists()  # ohne Kundenakte kein Stand


def test_first_export_saves_the_first_state_and_nothing_before(ui_app, tmp_path: Path, config_file: Path) -> None:
    from qtapp.contracts.comparison import FIRST_SAVED
    from tools.contract_overview.history.report import NO_HISTORY

    h = ui_app
    kunde = kunde_anlegen(h, "Kunde GmbH", "4711", ["rechnung@kunde.de"])
    pruefen(h, liste(tmp_path / "stand1.xlsx", STAND_1))
    h.customers.apply_customer(kunde.id)
    pump(0.2)
    view = ansicht(h)
    assert view.mode == "message" and view.noteText.startswith(NO_HISTORY)
    # Vorschau und Excel-Prüfung speichern keinen Stand
    h.navigate("preview")
    assert wait_until(lambda: h.preview._building is None and h.preview._doc is not None, 60)
    assert h.preview.runs >= 1
    h.navigate("create")
    assert staende(config_file, kunde) == []
    exportieren(h, tmp_path / "out")
    saved = staende(config_file, kunde)
    assert len(saved) == 1 and saved[0]["schema_version"] == 1 and saved[0]["customer_id"] == kunde.id
    # Reihenfolge wie in der PDF (nach Vertragsbeginn), Werte wie gedruckt, normalisiert
    assert [c["contract_number"] for c in saved[0]["contracts"]] == ["10005", "10004", "10003", "10002", "10001"]
    first = saved[0]["contracts"][-1]["effective"]
    assert first["net_amount"] == "250.00" and first["start_date"] == "2024-01-01" and first["billing_cycle"] == "jährlich"
    assert (view.noteTitle, view.noteText) == ("Vertragsstand gespeichert", FIRST_SAVED)
    assert view.noteSeverity == "success"
    # Gleiche Verträge noch einmal erstellt: kein zweiter Stand, nur gezählt
    exportieren(h, tmp_path / "out2")
    saved = staende(config_file, kunde)
    assert len(saved) == 1 and saved[0]["export_count"] == 2


def test_changes_since_the_last_state(ui_app, tmp_path: Path, config_file: Path) -> None:
    h = ui_app
    kunde = kunde_anlegen(h, "Kunde GmbH", "4711", ["rechnung@kunde.de"])
    pruefen(h, liste(tmp_path / "stand1.xlsx", STAND_1))
    h.customers.apply_customer(kunde.id)
    exportieren(h, tmp_path / "out")
    pruefen(h, liste(tmp_path / "stand2.xlsx", STAND_2))
    active = h.customers.active_customer()
    assert active is not None and active.id == kunde.id  # Kundenakte bleibt aktiv (gleiche E-Mail)
    view = ansicht(h)
    assert view.mode == "comparison" and view.noteText == ""
    assert view.headline == f"Seit {datetime.now().strftime('%d.%m.%Y')}"
    assert zaehler(view) == AENDERUNGEN
    assert zeilen(view) == [
        "Neu: 10006 Cloud-Speicher – 19,00 €",
        "Neu: 10007 KI-Assistent – 99,00 €",
        "Entfernt: 10003 Alte Schnittstelle – nicht mehr in der Excel",
        "Geändert: 10001 GetSolar – Netto 250,00 € → 270,00 €",
    ]
    assert gewaehlt(view).startswith("Letzter Stand (")
    # Kurzfassung in »Übersicht erstellen«, Einzelheiten in der Ansicht »Vergleich«
    pump(0.3)
    assert kurzfassung(h).property("visible")
    h.navigate("comparison", 0.4)
    page = h.item("comparisonPage")
    assert page.property("visible") and page.property("count") == 4
    # Einzelheiten aufklappen, unveränderte nur auf Wunsch
    view.toggle("10001")
    assert "  Netto: 250,00 € → 270,00 €" in zeilen(view)
    assert view.unchangedLabel == "3 unveränderte anzeigen"
    view.toggleUnchanged()
    pump(0.1)
    assert sum(line.startswith("Unverändert:") for line in zeilen(view)) == 3
    assert view.unchangedLabel == "Unveränderte ausblenden"
    assert page.property("count") == 7
    assert "  Netto: 250,00 € → 270,00 €" in zeilen(view)  # aufgeklappt bleibt aufgeklappt
    # Kopieren und Wechsel des Vergleichs lösen keine neue Vorschau aus
    runs = h.preview.runs
    view.copy()
    text = zwischenablage()
    assert text.startswith("Vertragsänderungen – Kunde GmbH") and "Netto: 250,00 € → 270,00 €" in text and "10006 Cloud-Speicher" in text
    pump(0.3)
    assert h.preview.runs == runs
    # Nach dem Erstellen bleibt der Vergleich sichtbar; der neue Stand ist wählbar
    h.navigate("create", 0.1)
    exportieren(h, tmp_path / "out")
    assert len(staende(config_file, kunde)) == 2
    labels = [choice["label"] for choice in view.choices]
    assert labels[0].startswith("Gerade gespeichert (") and labels[1].startswith("Letzter Stand (")
    assert zaehler(view) == AENDERUNGEN
    view.chooseBaseline(view.choices[0]["value"])
    pump(0.1)
    assert view.headline.startswith("Keine Änderungen seit") and zaehler(view) == "6 unverändert"
    assert not view.canCopy
    assert h.preview.runs == runs


def test_states_of_different_customers_never_mix(ui_app, tmp_path: Path, config_file: Path) -> None:
    from tools.contract_overview.history.report import NO_HISTORY

    h = ui_app
    a = kunde_anlegen(h, "Alpha GmbH", "1", ["rechnung@kunde.de"])
    b = kunde_anlegen(h, "Alpha GmbH", "2", ["einkauf@alpha.de"])  # gleicher Firmenname, andere Kundenakte
    pruefen(h, liste(tmp_path / "a.xlsx", STAND_1))
    h.customers.apply_customer(a.id)
    exportieren(h, tmp_path / "out")
    pruefen(h, liste(tmp_path / "b.xlsx", STAND_2, mail="einkauf@alpha.de"))
    h.customers.apply_customer(b.id)
    pump(0.2)
    active = h.customers.active_customer()
    assert active is not None and active.id == b.id
    assert ansicht(h).noteText.startswith(NO_HISTORY) and h.comparison.comparison is None
    assert ansicht(h).rowCount == 0
    assert len(staende(config_file, a)) == 1 and staende(config_file, b) == []


def test_failed_export_saves_no_state(ui_app, tmp_path: Path, config_file: Path, monkeypatch) -> None:
    import engine

    h = ui_app
    kunde = kunde_anlegen(h, "Kunde GmbH", "4711", ["rechnung@kunde.de"])
    pruefen(h, liste(tmp_path / "stand1.xlsx", STAND_1))
    h.customers.apply_customer(kunde.id)

    def kaputt(job):
        raise OSError("Datenträger voll")

    monkeypatch.setattr(engine, "erstelle_pdf", kaputt)
    h.overview.ziel = str(tmp_path / "out")
    h.overview.pdfOeffnen = False
    h.overview.start_pdf()
    assert wait_until(lambda: not h.overview.busy, 60)
    pump(0.2)
    notice = h.app.notices.get("pdf_info")
    assert notice.severity == "error" and "Datenträger voll" in notice.message
    assert staende(config_file, kunde) == []
    assert not (config_file.parent / "contract-history").exists()


def test_old_files_are_not_needed_for_the_comparison(ui_app, tmp_path: Path, config_file: Path) -> None:
    h = ui_app
    kunde = kunde_anlegen(h, "Kunde GmbH", "4711", ["rechnung@kunde.de"])
    erste = liste(tmp_path / "stand1.xlsx", STAND_1)
    pruefen(h, erste)
    h.customers.apply_customer(kunde.id)
    exportieren(h, tmp_path / "out")
    for pdf in (tmp_path / "out").glob("*.pdf"):
        pdf.unlink()
    erste.unlink()
    pruefen(h, liste(tmp_path / "stand2.xlsx", STAND_2))
    view = ansicht(h)
    assert zaehler(view) == AENDERUNGEN
    meta = {fact["label"]: fact["value"] for fact in view.meta}
    assert meta["Excel"] == "stand1.xlsx (nicht mehr vorhanden)" and meta["PDF"].endswith("(nicht mehr vorhanden)")


def test_comparison_card_follows_theme_and_width(ui_app, tmp_path: Path) -> None:
    """Die Liste ist ein Modell: kein Neuaufbau von Zeilen bei Breite oder Farbschema, keine QML-Meldung."""
    from PySide6.QtGui import QColor

    h = ui_app
    kunde = kunde_anlegen(h, "Kunde GmbH", "4711", ["rechnung@kunde.de"])
    pruefen(h, liste(tmp_path / "stand1.xlsx", STAND_1))
    h.customers.apply_customer(kunde.id)
    exportieren(h, tmp_path / "out")
    pruefen(h, liste(tmp_path / "stand2.xlsx", STAND_2))
    view = ansicht(h)
    assert zaehler(view) == AENDERUNGEN
    pump(0.3)
    summary = kurzfassung(h)
    assert summary.property("visible")
    summary_card = vorfahr(summary, "PCard")
    h.navigate("comparison", 0.4)
    page = h.item("comparisonPage")
    assert page.property("visible") and page.property("count") == view.rowCount == 4
    cards = [card for card in elemente(page, "PCard") if card.property("visible")]
    assert cards
    rows = zeiger(elemente(page, "ChangeRow"))
    assert len(rows) >= 4
    resets = view.changeModel.resets
    for size in ((760, 560), (1500, 950), (1100, 800)):
        h.window.resize(*size)
        pump(0.4)
        assert page.property("count") == 4 and view.changeModel.resets == resets
        assert zeiger(elemente(page, "ChangeRow")) == rows  # keine Zeile neu aufgebaut
        assert not h.messages(), h.messages()
    h.settings.setTheme("dark")
    pump(0.5)
    assert h.theme.dark
    surface = QColor(h.theme.colors["card"])
    for card in [summary_card, *cards]:
        assert QColor(card.property("color")) == surface  # Karten folgen dem Farbschema
    assert page.property("count") == 4 and view.changeModel.resets == resets
    assert zeiger(elemente(page, "ChangeRow")) == rows
    h.settings.setTheme("light")
    pump(0.4)
    assert not h.theme.dark and QColor(summary_card.property("color")) == QColor(h.theme.colors["card"])
    assert zeiger(elemente(page, "ChangeRow")) == rows and view.changeModel.resets == resets
    assert zaehler(view) == AENDERUNGEN
    assert not h.messages(), h.messages()


# --- Stapel -----------------------------------------------------------------------------------------------------------


def stapel(h, target: Path) -> None:
    h.navigate("batch", 0.2)
    h.batch.update_settings(target_dir=str(target))


def geprueft(h, timeout: float = 90) -> None:
    from tools.contract_overview.batch.models import WAITING

    assert wait_until(lambda: h.batch.items and all(item.status not in WAITING for item in h.batch.items), timeout)
    pump(0.2)


def erstellen(h, timeout: float = 180) -> None:
    h.batch.start_run()
    assert wait_until(lambda: not h.batch.running_now, timeout)
    pump(0.2)


def test_batch_saves_one_state_per_created_item(ui_app, tmp_path: Path, config_file: Path) -> None:
    from tools.contract_overview.batch.models import ConflictMode

    h = ui_app
    a = kunde_anlegen(h, "Alpha GmbH", "100", ["rechnung@alpha.de"])
    b = kunde_anlegen(h, "Beta AG", "200", ["rechnung@beta.de"])
    stapel(h, tmp_path / "out")
    leer = write_excel(tmp_path / "leer.xlsx", [["20001", datetime(2024, 1, 1), "jährlich", 10.0, "Sofort", "Alt", "rechnung@beta.de", "Inaktiv"]], SPALTEN)
    h.batch.add([str(liste(tmp_path / "alpha.xlsx", STAND_1, "rechnung@alpha.de")), str(liste(tmp_path / "beta.xlsx", STAND_1[:2], "rechnung@beta.de")), str(leer), str(liste(tmp_path / "fremd.xlsx", STAND_1, "info@fremd.de"))])
    geprueft(h)
    h.batch.edit(next(i for i in h.batch.items if i.name == "fremd.xlsx").id, company="Fremd GmbH", number="300")
    pump(0.2)
    erstellen(h)
    status = {item.name: item.status.value for item in h.batch.items}
    assert status["alpha.xlsx"] == status["beta.xlsx"] == status["fremd.xlsx"] == "success"
    assert status["leer.xlsx"] != "success"
    # je erfolgreich erstelltem Eintrag mit Kundenakte ein Stand – nie für übersprungene oder fehlgeschlagene
    assert len(staende(config_file, a)) == 1 and len(staende(config_file, b)) == 1
    assert sorted(p.name for p in (config_file.parent / "contract-history").iterdir()) == sorted([a.id, b.id])
    assert [c["contract_number"] for c in staende(config_file, b)[0]["contracts"]] == ["10002", "10001"]  # wie in der PDF
    # übersprungen (PDF vorhanden): kein Stand, obwohl sich die Verträge geändert haben
    h.batch.update_settings(conflict=ConflictMode.SKIP)
    h.batch.newBatch()
    pump(0.2)
    assert h.batch.items == []
    h.batch.add([str(liste(tmp_path / "beta2.xlsx", STAND_2, "rechnung@beta.de"))])
    geprueft(h)
    erstellen(h)
    assert h.batch.items[0].status.value == "skipped" and len(staende(config_file, b)) == 1
    h.batch.update_settings(conflict=ConflictMode.NUMBER)
    # nächster Stapel: kompakte Angaben in der Liste, Einzelheiten in der Detailansicht
    h.batch.newBatch()
    pump(0.2)
    h.batch.add([str(liste(tmp_path / "alpha2.xlsx", STAND_2, "rechnung@alpha.de"))])
    geprueft(h)
    row = h.batch.model.get(0)
    assert row["facts"].endswith("+2 neu · ~1 geändert · −1 entfernt"), row["facts"]
    item = h.batch.items[0]
    h.batch.show_detail(item.id)
    pump(0.3)
    detail = h.batch.detail
    assert detail.mode == "comparison" and zaehler(detail) == AENDERUNGEN
    assert gewaehlt(detail).startswith("Letzter Stand (")
    # QML: die Karte »Vertragsänderungen« der Detailansicht zeigt den Vergleich
    heads = [head for head in elemente(h.item("batchPage"), "ComparisonHead") if head.property("visible")]
    assert heads and heads[0].property("view") is not None
    erstellen(h)
    assert len(staende(config_file, a)) == 2
    pump(0.2)
    # Der Vergleich bleibt nach dem Erstellen sichtbar (gegen den vorherigen Stand)
    assert zaehler(h.batch.detail) == AENDERUNGEN
    assert gewaehlt(h.batch.detail).startswith("Letzter Stand (")
