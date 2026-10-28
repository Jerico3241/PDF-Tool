"""Tabellen: Daten-Werkzeuge (seit 5.0 Beta 5) – bedingte Formatierung und Datenbalken, Datenüberprüfung mit
Auswahlliste, Pivot-Tabelle, Duplikate entfernen, Text in Spalten, Blitzvorschau, Blätter teilen und zusammenführen,
Blatt- und Mappenschutz, Kennwort und Lese-Kreuz.

Die Formulare (``sheet_form``) beantworten die Tests über ``SheetController._form``; ohne LibreOffice laufen nur die
Tests ohne Rechenkern."""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import QObject, QUrl
from PySide6.QtQml import QQmlComponent

from conftest import wait_until
from qtutil import pump


def _calc_available() -> bool:
    from tools.sheet import engine

    return engine.available()


needs_calc = pytest.mark.skipif(not _calc_available(), reason="LibreOffice fehlt – Rechenkern nicht prüfbar")


def _workbook(path: Path) -> Path:
    import openpyxl

    book = openpyxl.Workbook()
    sheet = book.active
    sheet.title = "Verträge"
    sheet.append(["Kunde", "Ort", "Betrag", "Status", "Ansprechpartner", "Vorname"])
    for row in (("Müller", "Köln", 480, "aktiv", "Max Müller", "Max"), ("Schmidt", "Bonn", 1250, "aktiv", "Anna Schmidt", None),
                ("Weber", "Köln", 190, "läuft aus", "Jo Weber", None), ("Müller", "Köln", 480, "aktiv", "Max Müller", None),
                ("Fischer", "Bonn", 300, "aktiv", "Eva Fischer", None)):
        sheet.append(list(row))
    book.create_sheet("Kunden").append(["Kunde", "Ort"])
    book["Kunden"].append(["Neu", "Aachen"])
    book.save(path)
    return path


def _open(h, path: Path):
    reader = h.runtime.singletons["Reader"]
    reader.open_paths([str(path)])
    assert wait_until(lambda: reader.current is not None and getattr(reader.current, "ready", False), 120)
    pump(0.5)
    return reader.current


def _answer(monkeypatch, sheet, *answers: dict) -> list:
    """Formulare der Reihe nach mit diesen Werten beantworten (übrige Felder: Anfangswert); gibt die Felder zurück."""
    asked: list = []
    queue = list(answers)

    def form(title, fields, primary, **_kwargs):
        asked.append((title, fields))
        values = {field["key"]: field.get("value") for field in fields if field.get("key")}
        values.update(queue.pop(0) if queue else {})
        return values.pop("_answer", "primary"), values

    monkeypatch.setattr(sheet, "_form", form)
    return asked


def _cell(sheet, row: int, col: int):
    """(Text, Format) einer geladenen Zelle – wartet, bis sie (neu) geladen ist."""
    assert wait_until(lambda: sheet.sheet_cells().get(row, col) is not None and not sheet.busy, 20)
    pump(0.2)
    value = sheet.sheet_cells().get(row, col)
    return value[0], sheet.style(value[2])


def test_sheet_form_content_loads(ui_app) -> None:
    from qtapp.application import QML_DIR

    component = QQmlComponent(ui_app.engine, QUrl.fromLocalFile(str(QML_DIR / "PdfTool" / "Dialogs" / "SheetFormContent.qml")))
    assert component.isReady(), component.errorString()
    item = component.create()
    item.setProperty("request", {"id": 1, "data": {"fields": [
        {"key": "kind", "type": "choice", "label": "Zulassen", "value": "list", "options": [{"key": "list", "label": "Liste"}]},
        {"key": "items", "type": "text", "label": "Einträge", "value": "", "required": True, "show": {"key": "kind", "is": ["list"]}},
        {"key": "pw", "type": "password", "label": "Kennwort", "value": "a"},
        {"key": "pw2", "type": "password", "label": "Wiederholen", "value": "b", "confirm": "pw"},
        {"key": "cols", "type": "checks", "label": "Spalten", "value": ["0"], "options": [{"key": "0", "label": "A"}]},
        {"key": "preview", "type": "preview", "samples": ["a;b", "c;d"], "source": "kind", "custom": "x"},
    ]}})
    pump(0.1)
    assert item.property("acceptable") is False  # Einträge fehlen, Kennwörter verschieden
    values = item.property("values").toVariant()
    assert values["kind"] == "list" and values["cols"] == ["0"]
    values.update({"items": "Ja; Nein", "pw2": "a"})
    item.setProperty("values", values)
    assert item.property("acceptable") is True
    item.deleteLater()


@needs_calc
def test_conditional_formatting_and_data_bars(ui_app, tmp_path: Path, monkeypatch) -> None:
    """»Größer als« färbt passende Zellen hellrot, Datenbalken zeigen den Anteil; Regeln der Auswahl löschen."""
    h = ui_app
    h.app.dialogs.shutdown()
    sheet = _open(h, _workbook(tmp_path / "Bedingt.xlsx"))
    _answer(monkeypatch, sheet, {"value1": "400", "style": "red"})
    sheet.selectRange(1, 2, 5, 2)
    sheet.conditional("greater")
    assert wait_until(lambda: not sheet.busy and sheet.dirty, 20)
    assert _cell(sheet, 2, 2)[1].get("background", "").lower() == "#ffc7ce"  # 1250 > 400
    assert _cell(sheet, 3, 2)[1].get("background") in (None, "")  # 190
    sheet.selectRange(1, 2, 5, 2)
    sheet.clearConditional("selection")
    assert wait_until(lambda: not sheet.busy, 20)
    sheet.conditional("bar_blue")
    assert wait_until(lambda: not sheet.busy and _cell(sheet, 2, 2)[1].get("bar") is not None, 20)
    assert _cell(sheet, 2, 2)[1]["bar"][1] == pytest.approx(1.0)  # größter Wert: ganzer Balken
    assert 0 < _cell(sheet, 1, 2)[1]["bar"][1] < 1
    pump(0.3)
    assert h.item("sheetGrid").grabToImage is not None  # Raster malt Balken ohne Fehler


@needs_calc
def test_validation_list_rejects_and_offers_items(ui_app, tmp_path: Path, monkeypatch) -> None:
    """Datenüberprüfung »Liste«: falsche Eingaben lehnt der Kern ab (die Zelle bleibt, die Mappe gilt danach nicht als
    geändert), der Pfeil an der Zelle bietet die Einträge an."""
    h = ui_app
    h.app.dialogs.shutdown()
    sheet = _open(h, _workbook(tmp_path / "Liste.xlsx"))
    _answer(monkeypatch, sheet, {"kind": "list", "items": "aktiv; läuft aus; gekündigt", "strict": True})
    sheet.selectRange(1, 3, 5, 3)
    sheet.validationDialog()
    sheet.select(1, 3, False)
    assert wait_until(lambda: sheet.validation.get("kind") == "list", 20)
    assert sheet.validation["items"] == ["aktiv", "läuft aus", "gekündigt"]
    assert wait_until(lambda: h.item("sheetListButton").isVisible(), 10)
    assert sheet.save_and_wait() and wait_until(lambda: not sheet.dirty, 10)
    sheet.commit("Paris", 0, 0)
    assert wait_until(lambda: not sheet.busy, 20)
    assert wait_until(lambda: not sheet.dirty, 10)  # abgelehnt: wieder »gespeichert«
    assert _cell(sheet, 1, 3)[0] == "aktiv"
    sheet.chooseListItem("gekündigt")
    assert wait_until(lambda: not sheet.busy and _cell(sheet, 1, 3)[0] == "gekündigt", 20)


@needs_calc
def test_pivot_duplicates_text_to_columns_and_flash_fill(ui_app, tmp_path: Path, monkeypatch) -> None:
    h = ui_app
    h.app.dialogs.shutdown()
    sheet = _open(h, _workbook(tmp_path / "Daten.xlsx"))
    # Blitzvorschau: Vornamen aus »Ansprechpartner« nach dem Beispiel in F2
    sheet.select(2, 5, False)
    sheet.flashFill()
    assert wait_until(lambda: not sheet.busy and _cell(sheet, 2, 5)[0] == "Anna", 20)
    assert _cell(sheet, 5, 5)[0] == "Eva" and sheet.undoText == "Blitzvorschau"
    # Duplikate: die zweite »Müller, Köln, 480, aktiv« fällt weg (verglichen ohne Vorname/Ansprechpartner)
    asked = _answer(monkeypatch, sheet, {"columns": ["0", "1", "2", "3"]},
                    {"rows": "1", "data": "2", "function": "sum"}, {"separator": " "})
    sheet.select(1, 0, False)
    sheet.removeDuplicates()
    assert wait_until(lambda: not sheet.busy and _cell(sheet, 4, 0)[0] == "Fischer", 20)
    assert asked[0][0] == "Duplikate entfernen"
    # Pivot: Summe der Beträge je Ort auf einem neuen Blatt
    sheet.select(1, 0, False)
    sheet.pivotDialog()
    assert wait_until(lambda: [s["name"] for s in sheet.sheets][:2] == ["Verträge", "Pivot"] and sheet.activeSheet == 1, 30)
    texts = {}
    for row in range(0, 4):
        texts[_cell(sheet, row, 0)[0]] = _cell(sheet, row, 1)[0]
    assert texts.get("Bonn") == "1550" and texts.get("Köln") == "670"
    # Text in Spalten: »Max Müller« → »Max« | »Müller« (überschreibt nach Rückfrage die Spalte daneben)
    sheet.activateSheet(0)
    assert wait_until(lambda: sheet.activeSheet == 0 and sheet.layout().loaded, 20)
    sheet.selectRange(1, 4, 4, 4)
    sheet.textToColumns()
    assert wait_until(lambda: not sheet.busy and _cell(sheet, 1, 5)[0] == "Müller", 20)
    assert _cell(sheet, 1, 4)[0] == "Max"


@needs_calc
def test_split_merge_and_protection(ui_app, tmp_path: Path, monkeypatch) -> None:
    """Teilen nach Ort, wieder zusammenführen; Blatt- und Mappenschutz lehnen Änderungen ab; Kennwort beim Speichern;
    Lese-Kreuz."""
    h = ui_app
    h.app.dialogs.shutdown()
    sheet = _open(h, _workbook(tmp_path / "Teilen.xlsx"))
    _answer(monkeypatch, sheet, {"col": "1"}, {"sheets": ["2", "3"], "header": True}, {"password": "geheim", "repeat": "geheim"},
            {"password": "falsch"}, {"password": "geheim"}, {}, {"password": "x", "repeat": "x"})
    sheet.select(1, 0, False)
    sheet.splitSheet()
    assert wait_until(lambda: [s["name"] for s in sheet.sheets] == ["Verträge", "Kunden", "Köln", "Bonn"], 30)
    sheet.mergeSheets()
    assert wait_until(lambda: len(sheet.sheets) == 5 and sheet.sheets[4]["name"] == "Zusammengeführt" and sheet.activeSheet == 4, 30)
    assert wait_until(lambda: sheet.layout().loaded, 20)
    assert _cell(sheet, 0, 0)[0] == "Kunde" and _cell(sheet, 5, 0)[0] == "Fischer"
    # Blattschutz mit Kennwort: Eingaben abgelehnt, falsches Kennwort hebt ihn nicht auf
    sheet.activateSheet(0)
    assert wait_until(lambda: sheet.activeSheet == 0 and sheet.layout().loaded, 20)
    sheet.protectSheet()
    assert wait_until(lambda: sheet.sheetProtected, 20)
    sheet.select(1, 0, False)
    sheet.commit("Geändert", 0, 0)
    assert wait_until(lambda: not sheet.busy and _cell(sheet, 1, 0)[0] == "Müller", 20)
    sheet.protectSheet()
    pump(1.0)
    assert sheet.sheetProtected
    sheet.protectSheet()
    assert wait_until(lambda: not sheet.sheetProtected, 20)
    # Mappenschutz (ohne Kennwort): kein neues Blatt
    sheet.protectBook()
    assert wait_until(lambda: sheet.bookProtected, 20)
    count = len(sheet.sheets)
    sheet.addSheet()
    pump(1.5)
    assert len(sheet.sheets) == count
    # Kennwort zum Öffnen
    sheet.encrypt()
    assert wait_until(lambda: sheet.encrypted, 20)
    assert sheet.save_and_wait() and wait_until(lambda: not sheet.dirty, 10)
    # verschlüsselte Excel-Dateien sind ein OLE-Container (kein ZIP mehr)
    assert Path(sheet.path).read_bytes()[:4] == bytes.fromhex("D0CF11E0")
    sheet.toggleCrosshair()
    pump(0.3)
    assert sheet.crosshair
