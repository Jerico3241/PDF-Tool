"""Qt-Oberfläche: Modus »Objekt bearbeiten« im PDF Reader & Editor.

Bedient wird wie von Hand – Werkzeugleiste, Maus (Zeigen, Klicken, Doppelklick, Ziehen, Strg+Klick,
Auswahlrechteck, Rechtsklick) und Tastatur. Alle PDFs sind künstlich (``editorsamples``). Geprüft wird
jeweils auch das Ergebnis in der Datei: nur das gewählte Segment ändert sich, alles andere bleibt.
Nach jedem Test darf die QML-Engine keine Meldung ausgegeben haben (Fixture ``ui_app``).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import QObject, QPoint, Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtTest import QTest

import editorsamples as samples
from conftest import pump, wait_until
from test_qt_reader import LEFT, NO_MOD, click, digest, drag, key, open_pdf, page_item, page_point, page_text, reader, right_click, settle, type_text, window_point

ADDRESS = ["Firma", "Hottgenroth Software AG", "Von-Hünefeld-Str. 3", "50829 Köln"]


@pytest.fixture
def reader_app(ui_app):
    ui_app.app.dialogs.shutdown()  # »Neu in Version« (nicht blockierend) schließen
    ui_app.navigate("reader", 0.3)
    assert ui_app.app.currentPage == "reader"
    return ui_app


# --- Hilfen ----------------------------------------------------------------------------------------------------
def objects_tool(h, doc) -> None:
    """Werkzeug über die Leiste wählen und warten, bis die Seite analysiert ist."""
    button = h.item("readerToolObjects")
    click(h, window_point(button, button.width() / 2, button.height() / 2))
    settle(h)
    assert doc.tool == "objects"
    assert wait_until(lambda: str(doc.currentPage) in doc.objectPages, 20), "Seite wurde nicht analysiert"


def segments(doc, page: int = 0) -> list[dict]:
    return doc.objectPages[str(page)]["segments"]


def segment(doc, text: str, page: int = 0) -> dict:
    return next(item for item in segments(doc, page) if item["text"] == text)


def center(view) -> tuple[float, float]:
    return (view[0] + view[2]) / 2, (view[1] + view[3]) / 2


def chosen(doc) -> list[str]:
    return [entry["text"] for entry in doc.objectSelection]


def children(h, page: int, name: str) -> tuple:
    """Sichtbare Elemente einer Seite mit diesem Namen (auch die eines Repeaters, die nur über die
    Elementhierarchie erreichbar sind) – die Seite mit zurückgeben: PySide verwirft die
    Python-Objekte der Kinder, sobald das des Elternobjekts freigegeben ist."""
    item = page_item(h, page)
    found, todo = [], list(item.childItems())
    while todo:
        child = todo.pop()
        if child.objectName() == name:
            found.append(child)
        todo.extend(child.childItems())
    return item, found


def lines(path: Path, page: int = 0) -> list[str]:
    return [line.strip() for line in page_text(path, page).replace("\r", "").split("\n") if line.strip()]


def object_menu(h, name: str = "readerObjectMenu", page: int = 0):
    item = page_item(h, page)
    menus = [obj for obj in item.findChildren(QObject) if obj.objectName() == name]
    assert len(menus) == 1
    entries = {obj.property("text"): obj for obj in menus[0].findChildren(QObject) if obj.property("text") and obj.property("enabled") is not None and hasattr(obj, "mapToScene")}
    return item, menus[0], entries


def double_click(h, point: QPoint) -> None:
    QTest.mouseDClick(h.window, LEFT, NO_MOD, point)
    pump(0.3)


# --- Auswahl und Bearbeiten eines Segments ---------------------------------------------------------------------
def test_hottgenroth_line_is_selected_alone_and_only_it_changes(reader_app, tmp_path: Path) -> None:
    """Adresse in einem einzigen Textobjekt: Zeigen hebt nur die Zeile hervor, ein Klick wählt nur sie,
    ein Doppelklick öffnet genau diese Zeile im Editor. Nach dem Ändern ist nur diese Zeile anders –
    auch nach Speichern, Schließen und erneutem Öffnen."""
    h = reader_app
    path = samples.object_address(tmp_path / "adresse.pdf")
    doc = open_pdf(h, path, whole_page=True)
    tip = h.item("readerToolObjects").property("tip")
    assert "Text und andere PDF-Inhalte einzeln auswählen und bearbeiten." in tip
    objects_tool(h, doc)
    assert [item["text"] for item in segments(doc)] == ADDRESS
    line = segment(doc, "Hottgenroth Software AG")
    assert [word["text"] for word in line["words"]] == ["Hottgenroth", "Software", "AG"]
    assert line["native"] and line["reason"] == ""
    # Zeigen: dezenter Rahmen um genau diese Zeile – noch keine Auswahl
    QTest.mouseMove(h.window, page_point(h, 0, *center(line["view"])))
    pump(0.2)
    _page, hover = children(h, 0, "readerObjectHover")
    assert [item.isVisible() for item in hover] == [True] and doc.objectSelection == []
    # Klick: nur diese Zeile, mit Rahmen; die Eigenschaften öffnen sich
    click(h, page_point(h, 0, *center(line["view"])))
    pump(0.2)
    assert chosen(doc) == ["Hottgenroth Software AG"]
    _page, boxes = children(h, 0, "readerObjectSelection")
    assert len(boxes) == 1 and boxes[0].isVisible()
    assert reader(h).rightPanel == "properties"
    assert h.item("readerObjectPanel").isVisible()
    # Doppelklick: Editor mit genau dieser Zeile, Cursor an der Klickstelle (hinter »AG«)
    ag = line["words"][2]["view"]
    double_click(h, page_point(h, 0, ag[2] - 1, (ag[1] + ag[3]) / 2))
    editor = h.item("readerTextEditor")
    area = h.item("readerEditorInput")
    assert editor.property("open") is True
    assert area.property("text") == "Hottgenroth Software AG"
    assert area.property("cursorPosition") >= len("Hottgenroth Software A")
    area.setProperty("text", "Hottgenroth Software GmbH")
    key(h, Qt.Key.Key_Return)  # einzeilig: Eingabe übernimmt
    settle(h)
    assert editor.property("open") is False
    assert doc.dirty and doc.lastMode == "Direkt im PDF geändert (Originalschrift)"
    assert wait_until(lambda: [item["text"] for item in doc.objectPages.get("0", {}).get("segments", [])] == ["Firma", "Hottgenroth Software GmbH", "Von-Hünefeld-Str. 3", "50829 Köln"], 20)
    assert chosen(doc) == ["Hottgenroth Software GmbH"]  # Auswahl bleibt an der geänderten Zeile
    # Speichern, schließen, neu öffnen: nur die eine Zeile ist anders, Position unverändert
    before = digest(path)
    key(h, Qt.Key.Key_S, Qt.KeyboardModifier.ControlModifier)
    settle(h)
    assert not doc.dirty and digest(path) != before
    assert lines(path) == ["Firma", "Hottgenroth Software GmbH", "Von-Hünefeld-Str. 3", "50829 Köln"]
    assert reader(h).closeTab(doc.ident) is True
    settle(h)
    doc = open_pdf(h, path, whole_page=True)
    objects_tool(h, doc)
    again = segments(doc)
    assert [item["text"] for item in again] == ["Firma", "Hottgenroth Software GmbH", "Von-Hünefeld-Str. 3", "50829 Köln"]
    assert abs(again[1]["view"][0] - line["view"][0]) < 0.2 and abs(again[1]["view"][1] - line["view"][1]) < 0.5


def test_second_click_selects_a_word_and_double_click_edits_only_that_word(reader_app, tmp_path: Path) -> None:
    """Granularität: der erste Klick wählt die Zeile, ein weiterer Klick ein Wort darin. Ein Doppelklick
    auf das gewählte Wort ändert nur das Wort; der Rest der Zeile rückt passend nach."""
    h = reader_app
    path = samples.object_address(tmp_path / "wort.pdf")
    doc = open_pdf(h, path, whole_page=True)
    objects_tool(h, doc)
    line = segment(doc, "Hottgenroth Software AG")
    software = line["words"][1]["view"]
    point = page_point(h, 0, *center(software))
    click(h, point)
    assert chosen(doc) == ["Hottgenroth Software AG"]
    pump(0.6)  # kein Doppelklick
    click(h, point)
    assert chosen(doc) == ["Software"] and doc.objectSelection[0]["kind"] == "word"
    pump(0.6)
    double_click(h, point)
    area = h.item("readerEditorInput")
    assert area.property("text") == "Software"
    area.setProperty("text", "Systemhaus")
    key(h, Qt.Key.Key_Return)
    settle(h)
    assert wait_until(lambda: any(item["text"] == "Hottgenroth Systemhaus AG" for item in doc.objectPages.get("0", {}).get("segments", [])), 20)
    changed = segment(doc, "Hottgenroth Systemhaus AG")
    assert [word["text"] for word in changed["words"]] == ["Hottgenroth", "Systemhaus", "AG"]
    # »AG« folgt dem längeren Wort mit gleichem Abstand – keine Überlappung, keine Lücke
    gap_before = line["words"][2]["view"][0] - line["words"][1]["view"][2]
    gap_after = changed["words"][2]["view"][0] - changed["words"][1]["view"][2]
    assert abs(gap_before - gap_after) < 0.6
    assert [item["text"] for item in segments(doc)] == ["Firma", "Hottgenroth Systemhaus AG", "Von-Hünefeld-Str. 3", "50829 Köln"]


def test_double_click_on_a_selected_line_edits_the_line_not_the_word(reader_app, tmp_path: Path) -> None:
    h = reader_app
    doc = open_pdf(h, samples.object_address(tmp_path / "zeile.pdf"), whole_page=True)
    objects_tool(h, doc)
    line = segment(doc, "Von-Hünefeld-Str. 3")
    point = page_point(h, 0, *center(line["words"][0]["view"]))
    click(h, point)
    pump(0.6)
    double_click(h, point)
    assert h.item("readerEditorInput").property("text") == "Von-Hünefeld-Str. 3"
    assert chosen(doc) == ["Von-Hünefeld-Str. 3"]
    key(h, Qt.Key.Key_Escape)  # Abbrechen: nichts geändert
    settle(h)
    assert not doc.dirty and h.item("readerTextEditor").property("open") is False


# --- Mehrfachauswahl, Auswahlrechteck, Löschen, Verschieben ------------------------------------------------------
def test_table_cells_ctrl_click_marquee_and_delete_only_the_selection(reader_app, tmp_path: Path) -> None:
    """Tabelle: jede Zelle ist ein eigenes Objekt. Strg+Klick wählt mehrere, ein Auswahlrechteck alle
    darin; Entf löscht nur die gewählten Zellen."""
    h = reader_app
    path = samples.object_table(tmp_path / "tabelle.pdf")
    doc = open_pdf(h, path, whole_page=True)
    objects_tool(h, doc)
    assert [item["text"] for item in segments(doc)] == ["Pos.", "Anz.", "Leistung", "Stückpreis", "Gesamtpreis", "1", "2", "Wartung Software", "120,00", "240,00"]
    # Strg+Klick: hinzufügen und wieder entfernen
    click(h, page_point(h, 0, *center(segment(doc, "Stückpreis")["view"])))
    click(h, page_point(h, 0, *center(segment(doc, "120,00")["view"])), Qt.KeyboardModifier.ControlModifier)
    click(h, page_point(h, 0, *center(segment(doc, "Gesamtpreis")["view"])), Qt.KeyboardModifier.ControlModifier)
    assert chosen(doc) == ["Stückpreis", "120,00", "Gesamtpreis"]
    click(h, page_point(h, 0, *center(segment(doc, "Gesamtpreis")["view"])), Qt.KeyboardModifier.ControlModifier)
    assert chosen(doc) == ["Stückpreis", "120,00"]
    # Klick ins Leere hebt die Auswahl auf; Rechteck über die Kopfzeile wählt genau ihre fünf Zellen
    click(h, page_point(h, 0, 300, 400))
    assert doc.objectSelection == []
    drag(h, page_point(h, 0, 60, 66), page_point(h, 0, 500, 86))
    pump(0.2)
    assert chosen(doc) == ["Pos.", "Anz.", "Leistung", "Stückpreis", "Gesamtpreis"]
    # Nur zwei Zellen behalten und löschen
    others = {text: segment(doc, text)["view"] for text in ("Gesamtpreis", "Wartung Software")}
    click(h, page_point(h, 0, *center(segment(doc, "Stückpreis")["view"])))
    click(h, page_point(h, 0, *center(segment(doc, "120,00")["view"])), Qt.KeyboardModifier.ControlModifier)
    key(h, Qt.Key.Key_Delete)
    settle(h)
    assert wait_until(lambda: len(doc.objectPages.get("0", {}).get("segments", [])) == 8, 20)
    assert [item["text"] for item in segments(doc)] == ["Pos.", "Anz.", "Leistung", "Gesamtpreis", "1", "2", "Wartung Software", "240,00"]
    assert doc.objectSelection == []
    # Die anderen Zellen stehen unverändert an ihrem Platz
    for text, view in others.items():
        assert segment(doc, text)["view"] == pytest.approx(view, abs=0.05), text
    # Rückgängig bringt beide zurück
    key(h, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
    settle(h)
    assert wait_until(lambda: len(doc.objectPages.get("0", {}).get("segments", [])) == 10, 20)


def test_drag_moves_only_the_selection_one_to_one_and_undo_restores(reader_app, tmp_path: Path) -> None:
    h = reader_app
    path = samples.object_address(tmp_path / "ziehen.pdf")
    doc = open_pdf(h, path, whole_page=True)
    objects_tool(h, doc)
    line = segment(doc, "50829 Köln")
    firma = segment(doc, "Firma")["view"]  # Lage hängt von den Schriftmaßen ab (PDFium je System) – vorher messen
    start = page_point(h, 0, *center(line["view"]))
    click(h, start)
    scale = doc.scale
    drag(h, start, QPoint(start.x() + round(60 * scale), start.y() + round(30 * scale)), steps=10)
    settle(h)
    assert wait_until(lambda: any(item["text"] == "50829 Köln" and item["view"][0] > line["view"][0] + 50 for item in doc.objectPages.get("0", {}).get("segments", [])), 20)
    moved = segment(doc, "50829 Köln")
    assert moved["view"][0] - line["view"][0] == pytest.approx(60, abs=1.5)
    assert moved["view"][1] - line["view"][1] == pytest.approx(30, abs=1.5)
    # Die übrigen Zeilen bleiben, wo sie waren
    assert segment(doc, "Firma")["view"] == pytest.approx(firma, abs=0.05)
    assert chosen(doc) == ["50829 Köln"] and doc.undoText != ""
    key(h, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
    settle(h)
    assert wait_until(lambda: any(item["text"] == "50829 Köln" and abs(item["view"][0] - line["view"][0]) < 0.3 for item in doc.objectPages.get("0", {}).get("segments", [])), 20)


def test_keyboard_tab_arrows_escape_enter_and_one_undo_step_for_nudging(reader_app, tmp_path: Path) -> None:
    h = reader_app
    doc = open_pdf(h, samples.object_address(tmp_path / "tastatur.pdf"), whole_page=True)
    objects_tool(h, doc)
    click(h, page_point(h, 0, 300, 500))  # Klick ins Leere: Fokus in der Seite, keine Auswahl
    assert doc.objectSelection == []
    key(h, Qt.Key.Key_Tab)
    assert chosen(doc) == ["Firma"]
    key(h, Qt.Key.Key_Tab)
    assert chosen(doc) == ["Hottgenroth Software AG"]
    key(h, Qt.Key.Key_Backtab, Qt.KeyboardModifier.ShiftModifier)
    assert chosen(doc) == ["Firma"]
    original = segment(doc, "Firma")["view"]
    # Pfeiltasten: Auswahl folgt sofort, gespeichert wird ein Schritt
    for _ in range(3):
        key(h, Qt.Key.Key_Right)
    key(h, Qt.Key.Key_Down, Qt.KeyboardModifier.ShiftModifier)
    assert doc.objectSelection[0]["view"][0] == pytest.approx(original[0] + 3, abs=0.01)
    settle(h)
    assert wait_until(lambda: any(item["text"] == "Firma" and abs(item["view"][1] - original[1] - 10) < 0.6 for item in doc.objectPages.get("0", {}).get("segments", [])), 20)
    assert segment(doc, "Firma")["view"][0] == pytest.approx(original[0] + 3, abs=0.6)
    assert doc.undoText != ""
    key(h, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
    settle(h)
    assert wait_until(lambda: any(item["text"] == "Firma" and abs(item["view"][0] - original[0]) < 0.3 for item in doc.objectPages.get("0", {}).get("segments", [])), 20)
    # Eingabe öffnet den Editor für das gewählte Segment, Esc bricht ab, Esc hebt die Auswahl auf
    click(h, page_point(h, 0, *center(segment(doc, "50829 Köln")["view"])))
    key(h, Qt.Key.Key_Return)
    assert h.item("readerEditorInput").property("text") == "50829 Köln"
    key(h, Qt.Key.Key_Escape)
    assert h.item("readerTextEditor").property("open") is False and chosen(doc) == ["50829 Köln"]
    key(h, Qt.Key.Key_Escape)
    assert doc.objectSelection == []


# --- Kontextmenü, Eigenschaften, Moduswechsel ----------------------------------------------------------------------
def test_context_menu_and_properties_panel(reader_app, tmp_path: Path) -> None:
    h = reader_app
    path = samples.object_address(tmp_path / "menue.pdf")
    doc = open_pdf(h, path, whole_page=True)
    objects_tool(h, doc)
    line = segment(doc, "Firma")
    right_click(h, page_point(h, 0, *center(line["view"])))
    _page, menu, entries = object_menu(h)
    assert menu.property("opened") and chosen(doc) == ["Firma"]
    assert {"Bearbeiten", "Text bearbeiten (ganzer Absatz)", "Kopieren", "Ausschneiden", "Duplizieren", "Löschen", "Eigenschaften"} <= set(entries)
    QGuiApplication.clipboard().setText("")
    copy = entries["Kopieren"]
    click(h, window_point(copy, copy.width() / 2, copy.height() / 2))
    settle(h)
    assert QGuiApplication.clipboard().text() == "Firma" and not menu.property("opened")
    # Duplizieren über das Menü: Kopie versetzt daneben, das Original bleibt
    right_click(h, page_point(h, 0, *center(line["view"])))
    _page, menu, entries = object_menu(h)
    duplicate = entries["Duplizieren"]
    click(h, window_point(duplicate, duplicate.width() / 2, duplicate.height() / 2))
    settle(h)
    assert wait_until(lambda: [item["text"] for item in doc.objectPages.get("0", {}).get("segments", [])].count("Firma") == 2, 20)
    # Eigenschaften: Größe ändern – nur das gewählte Objekt
    panel = h.item("readerObjectPanel")
    assert panel.isVisible()
    copy_of = chosen(doc)
    assert copy_of == ["Firma"]
    size = h.item("readerObjectSize")
    assert size.property("text") == "11,0"
    click(h, window_point(size, size.width() / 2, size.height() / 2))
    key(h, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
    type_text(h, "14")
    key(h, Qt.Key.Key_Return)  # Eingabe im Feld übernimmt – öffnet nicht den Editor der Seite
    settle(h)
    assert h.item("readerTextEditor").property("open") is False
    assert wait_until(lambda: sorted(item["size"] for item in doc.objectPages.get("0", {}).get("segments", []) if item["text"] == "Firma") == [11.0, 14.0], 20)
    assert all(item["size"] == 11.0 for item in segments(doc) if item["text"] != "Firma")
    # Modus verlassen: Auswahl weg, die für den Modus geöffneten Eigenschaften schließen sich
    doc.setTool("select")
    settle(h)
    assert doc.objectSelection == [] and reader(h).rightPanel == ""


def test_text_without_editable_structure_and_scanned_pages_are_named_honestly(reader_app, tmp_path: Path) -> None:
    h = reader_app
    doc = open_pdf(h, samples.scanned_with_ocr(tmp_path / "scan.pdf"), whole_page=True)
    objects_tool(h, doc)
    notice = h.item("readerObjectNotice")
    assert wait_until(lambda: notice.property("shown") is True, 10)
    assert notice.property("message") == "Auf dieser Seite wurde kein bearbeitbarer PDF-Text erkannt."
    assert segments(doc) == [] and len(doc.objectPages["0"]["images"]) == 1
    # Text in einem Formular-Objekt: wählbar, als nicht direkt änderbar gekennzeichnet
    doc2 = open_pdf(h, samples.form_xobject_text(tmp_path / "formular.pdf"), whole_page=True)
    objects_tool(h, doc2)
    assert notice.property("shown") is False
    items = segments(doc2)
    assert items and not items[0]["native"] and "Formular-Objekt" in items[0]["reason"]


def test_context_menu_edit_delete_and_whole_paragraph(reader_app, tmp_path: Path) -> None:
    """»Bearbeiten« öffnet nur das Segment, »Löschen« entfernt nur das Segment, »Text bearbeiten (ganzer
    Absatz)« wechselt ins Werkzeug »Text bearbeiten« und öffnet dort den Absatz."""
    h = reader_app
    doc = open_pdf(h, samples.object_address(tmp_path / "menue2.pdf"), whole_page=True)
    objects_tool(h, doc)
    street = segment(doc, "Von-Hünefeld-Str. 3")
    city = segment(doc, "50829 Köln")["view"]  # Lage hängt von den Schriftmaßen ab (PDFium je System) – vorher messen
    right_click(h, page_point(h, 0, *center(street["view"])))
    _page, menu, entries = object_menu(h)
    edit = entries["Bearbeiten"]
    click(h, window_point(edit, edit.width() / 2, edit.height() / 2))
    area = h.item("readerEditorInput")
    assert wait_until(lambda: area.property("text") == "Von-Hünefeld-Str. 3", 5)
    # Der Editor hat den Tastaturfokus – auch nachdem sich das Menü ausgeblendet hat
    pump(0.4)
    assert area.property("activeFocus") is True
    key(h, Qt.Key.Key_Escape)  # bricht nur den Editor ab
    assert h.item("readerTextEditor").property("open") is False and doc.tool == "objects"
    right_click(h, page_point(h, 0, *center(street["view"])))
    _page, menu, entries = object_menu(h)
    delete = entries["Löschen"]
    click(h, window_point(delete, delete.width() / 2, delete.height() / 2))
    settle(h)
    assert wait_until(lambda: [item["text"] for item in doc.objectPages.get("0", {}).get("segments", [])] == ["Firma", "Hottgenroth Software AG", "50829 Köln"], 20)
    assert segment(doc, "50829 Köln")["view"] == pytest.approx(city, abs=0.05)  # der Ort rückt nicht nach
    # Wiederholen nach Rückgängig
    key(h, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
    settle(h)
    assert wait_until(lambda: len(doc.objectPages.get("0", {}).get("segments", [])) == 4, 20)
    key(h, Qt.Key.Key_Y, Qt.KeyboardModifier.ControlModifier)
    settle(h)
    assert wait_until(lambda: len(doc.objectPages.get("0", {}).get("segments", [])) == 3, 20)
    # Ganzer Absatz: Werkzeug »Text bearbeiten« mit dem Block, der die Zeile enthält
    firm = segment(doc, "Firma")
    right_click(h, page_point(h, 0, *center(firm["view"])))
    _page, menu, entries = object_menu(h)
    paragraph = entries["Text bearbeiten (ganzer Absatz)"]
    click(h, window_point(paragraph, paragraph.width() / 2, paragraph.height() / 2))
    settle(h)
    assert doc.tool == "editText" and doc.objectSelection == []
    assert wait_until(lambda: h.item("readerTextEditor").property("open") is True, 10)
    assert "Firma" in h.item("readerEditorInput").property("text")
    key(h, Qt.Key.Key_Escape)


def test_image_object_select_move_resize_and_delete(reader_app, tmp_path: Path) -> None:
    """Bilder im Objektmodus: anklicken (Rahmen mit Anfassern, Eigenschaften »Bild«), ziehen, an der Ecke
    skalieren, löschen. Der Text über dem Bild bleibt."""
    h = reader_app
    doc = open_pdf(h, samples.object_text_on_image(tmp_path / "bild.pdf"), whole_page=True)
    objects_tool(h, doc)
    image = doc.objectPages["0"]["images"][0]
    assert image["editable"] and image["kind"] == "image"
    spot = (image["view"][0] + (image["view"][2] - image["view"][0]) * 0.75, image["view"][3] - 6)  # aufs Bild, neben den Text, fern der Ecken
    click(h, page_point(h, 0, *spot))
    assert [entry["kind"] for entry in doc.objectSelection] == ["image"]
    assert h.item("readerObjectX").property("enabled") is True
    start = page_point(h, 0, *spot)
    scale = doc.scale
    drag(h, start, QPoint(start.x() + round(30 * scale), start.y() + round(20 * scale)))
    settle(h)
    assert wait_until(lambda: doc.objectPages.get("0", {}).get("images") and doc.objectPages["0"]["images"][0]["view"][0] > image["view"][0] + 25, 20)
    moved = doc.objectPages["0"]["images"][0]["view"]
    assert [entry["kind"] for entry in doc.objectSelection] == ["image"]  # Auswahl bleibt am Bild
    corner = page_point(h, 0, moved[2], moved[3])
    drag(h, corner, QPoint(corner.x() + round(30 * scale), corner.y() + round(6 * scale)))
    settle(h)
    assert wait_until(lambda: doc.objectPages.get("0", {}).get("images") and doc.objectPages["0"]["images"][0]["view"][2] - doc.objectPages["0"]["images"][0]["view"][0] > moved[2] - moved[0] + 20, 20)
    resized = doc.objectPages["0"]["images"][0]["view"]
    ratio = (moved[2] - moved[0]) / (moved[3] - moved[1])
    assert (resized[2] - resized[0]) / (resized[3] - resized[1]) == pytest.approx(ratio, rel=0.05)  # Seitenverhältnis bleibt
    key(h, Qt.Key.Key_Delete)
    settle(h)
    assert wait_until(lambda: doc.objectPages.get("0", {}).get("images") == [], 20)
    assert [item["text"] for item in segments(doc)] == ["Text auf Bild"]


# --- Zoom, gedrehte Seiten, Tabs -------------------------------------------------------------------------------------
@pytest.mark.parametrize("zoom", [50, 133, 200, 400])
def test_hit_testing_is_exact_at_low_and_high_zoom(reader_app, tmp_path: Path, zoom: int) -> None:
    h = reader_app
    doc = open_pdf(h, samples.object_address(tmp_path / f"zoom{zoom}.pdf"))
    objects_tool(h, doc)
    doc.setZoom(zoom)
    settle(h)
    line = segment(doc, "Von-Hünefeld-Str. 3")
    doc.reveal(0, *center(line["view"]))
    pump(0.5)
    click(h, page_point(h, 0, *center(line["view"])))
    assert chosen(doc) == ["Von-Hünefeld-Str. 3"]
    # Knapp über der Zeile liegt die vorige, knapp darunter die nächste
    click(h, page_point(h, 0, line["view"][0] + 5, line["view"][1] - 3))
    assert chosen(doc) == ["Hottgenroth Software AG"]
    click(h, page_point(h, 0, line["view"][0] + 5, line["view"][3] + 3))
    assert chosen(doc) == ["50829 Köln"]


def test_rotated_pages_and_cropbox_select_and_edit_the_right_line(reader_app, tmp_path: Path) -> None:
    h = reader_app
    path = samples.object_rotated(tmp_path / "gedreht.pdf")
    doc = open_pdf(h, path)
    doc.setViewMode("single")
    doc.fitPage()
    objects_tool(h, doc)
    for page in range(5):
        doc.goTo(page)  # seitenweise mit »Ganze Seite«: jede Seite wird eingepasst
        settle(h)
        pump(0.4)
        assert wait_until(lambda page=page: str(page) in doc.objectPages, 20)
        line = segment(doc, "Hottgenroth Software AG", page)
        click(h, page_point(h, page, *center(line["view"])))
        assert chosen(doc) == ["Hottgenroth Software AG"], page
        doc.editObject(page, line["id"], "Hottgenroth Software GmbH")
        settle(h)
        assert wait_until(lambda page=page: any(item["text"] == "Hottgenroth Software GmbH" for item in doc.objectPages.get(str(page), {}).get("segments", [])), 20)
        others = sorted(item["text"] for item in segments(doc, page))
        assert others == sorted(["Firma", "Hottgenroth Software GmbH", "Von-Hünefeld-Str. 3", "50829 Köln"]), page
    key(h, Qt.Key.Key_S, Qt.KeyboardModifier.ControlModifier)
    settle(h)
    for page in range(5):
        assert "Hottgenroth Software GmbH" in page_text(path, page) and "Software AG" not in page_text(path, page)


def test_selection_belongs_to_its_tab(reader_app, tmp_path: Path) -> None:
    h = reader_app
    first = open_pdf(h, samples.object_address(tmp_path / "eins.pdf"), whole_page=True)
    objects_tool(h, first)
    click(h, page_point(h, 0, *center(segment(first, "Firma")["view"])))
    assert chosen(first) == ["Firma"]
    second = open_pdf(h, samples.object_table(tmp_path / "zwei.pdf"), whole_page=True)
    assert second.objectSelection == [] and second.tool == "select"
    objects_tool(h, second)
    click(h, page_point(h, 0, *center(segment(second, "Leistung")["view"])))
    assert chosen(second) == ["Leistung"] and chosen(first) == ["Firma"]
    key(h, Qt.Key.Key_Delete)
    settle(h)
    assert not first.dirty and second.dirty


@pytest.fixture
def reader_profiles(app):
    """Reader mit Animationsprofil »Vollständig« bzw. »Aus« (Fixture ``app``)."""
    app.app.dialogs.shutdown()
    app.navigate("reader", 0.3)
    return app


def test_selection_appears_quickly_and_dragging_follows_the_pointer_one_to_one(reader_profiles, tmp_path: Path) -> None:
    """Auswahlrahmen: kurz eingeblendet (Vollständig) bzw. sofort (Aus); beim Ziehen folgt der Inhalt
    dem Zeiger ohne Verzögerung – in jedem Profil."""
    h = reader_profiles
    doc = open_pdf(h, samples.object_address(tmp_path / "animation.pdf"), whole_page=True)
    objects_tool(h, doc)
    line = segment(doc, "Hottgenroth Software AG")
    start = page_point(h, 0, *center(line["view"]))
    QTest.mouseClick(h.window, LEFT, NO_MOD, start)
    pump(0.15)  # länger als jede Einblendung (höchstens 120 ms)
    _page, boxes = children(h, 0, "readerObjectSelection")
    assert len(boxes) == 1 and boxes[0].property("opacity") == pytest.approx(1.0)
    x0 = boxes[0].property("x")
    QTest.mousePress(h.window, LEFT, NO_MOD, start)
    for step in range(1, 5):
        QTest.mouseMove(h.window, QPoint(start.x() + 10 * step, start.y()))
        pump(0.01)
        assert boxes[0].property("x") == pytest.approx(x0 + 10 * step, abs=1.0)  # 1:1, ohne Nachlaufen
    QTest.mouseRelease(h.window, LEFT, NO_MOD, QPoint(start.x() + 40, start.y()))
    settle(h)
    assert wait_until(lambda: any(item["text"] == "Hottgenroth Software AG" and item["view"][0] > line["view"][0] + 20 for item in doc.objectPages.get("0", {}).get("segments", [])), 20)
