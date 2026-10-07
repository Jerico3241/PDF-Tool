"""Qt-Oberfläche: »Objekt bearbeiten« ab 3.1 – gemischte Auswahl (Text, Bild, Vektorgrafik), Eigenschaften
von Grafiken, Deckkraft, Drehen, Größe, Ebenen, Ausrichten/Verteilen und die Zwischenablage für Objekte (über
Tabs hinweg, aus anderen Programmen, Berechtigungen).

Bedient wird wie von Hand (Maus, Tastatur, Kontextmenü, Eigenschaften). Alle PDFs sind künstlich
(``editorsamples``). Nach jedem Test darf die QML-Engine keine Meldung ausgegeben haben (Fixture ``ui_app``).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QColor, QGuiApplication, QImage

import editorsamples as samples
from conftest import pump, wait_until
from test_qt_objects import center, object_menu, objects_tool, reader_app, segment, segments  # noqa: F401 - Fixture
from test_qt_reader import click, drag, key, open_pdf, page_point, page_text, reader, right_click, settle, type_text, window_point

CTRL = Qt.KeyboardModifier.ControlModifier
SHIFT = Qt.KeyboardModifier.ShiftModifier
RED_FRAME = "#E61A1A"


# --- Hilfen ----------------------------------------------------------------------------------------------------
def items(doc, kind: str, page: int = 0) -> list[dict]:
    return doc.objectPages.get(str(page), {}).get(kind, [])


def path_with(doc, page: int = 0, **wanted) -> dict:
    return next(item for item in items(doc, "paths", page) if all(item.get(name) == value for name, value in wanted.items()))


def kinds(doc) -> list[str]:
    return sorted(entry["kind"] for entry in doc.objectSelection)


def analyzed(h, doc, page: int = 0) -> None:
    """Warten, bis die Änderung fertig und die Seite neu analysiert ist."""
    settle(h)
    assert wait_until(lambda: doc.objectPages.get(str(page), {}).get("revision") == doc.revision, 20), "Seite wurde nicht neu analysiert"
    pump(0.1)


def press(h, name: str) -> None:
    button = h.item(name)
    assert button is not None and button.isVisible() and button.property("enabled"), name
    click(h, window_point(button, button.width() / 2, button.height() / 2))


def menu_click(h, entry) -> None:
    click(h, window_point(entry, entry.width() / 2, entry.height() / 2))


def empty_spot(h, doc) -> QPoint:
    """Eine freie Stelle der ersten Seite (unten links) – ein Klick dorthin gibt der Seite den Fokus."""
    return page_point(h, 0, 30, 820)


# --- Gemischte Auswahl ------------------------------------------------------------------------------------------
def test_mixed_selection_moves_text_image_and_graphic_in_one_step(reader_app, tmp_path: Path) -> None:
    """Text, Bild und Rahmen (Vektorgrafik) mit Umschalt- bzw. Strg+Klick wählen, gemeinsam ziehen: alles
    bewegt sich 1:1, ein Rückgängig nimmt alles zurück. Die seitenfüllende Hintergrundfläche ist kein Objekt."""
    h = reader_app
    doc = open_pdf(h, samples.mixed_objects(tmp_path / "gemischt.pdf"), whole_page=True)
    objects_tool(h, doc)
    assert len(items(doc, "paths")) == 3 and len(items(doc, "images")) == 1  # Rahmen, Kreis, Linie; Bild
    text = segment(doc, "Rechnung Nr. 4711")
    frame = path_with(doc, stroke=RED_FRAME)
    image = items(doc, "images")[0]
    assert frame["editable"] and frame["width"] == pytest.approx(2.0, abs=0.01)
    click(h, page_point(h, 0, *center(text["view"])))
    click(h, page_point(h, 0, *center(frame["view"])), SHIFT)
    click(h, page_point(h, 0, *center(image["view"])), CTRL)
    assert kinds(doc) == ["image", "path", "text"]
    assert h.item("readerObjectKind").property("text") == "3 Objekte ausgewählt"
    scale = doc.scale
    start = page_point(h, 0, *center(image["view"]))
    drag(h, start, QPoint(start.x() + round(30 * scale), start.y() + round(20 * scale)))
    analyzed(h, doc)
    du = segment(doc, "Rechnung Nr. 4711")["view"][0] - text["view"][0]
    assert du == pytest.approx(30, abs=1.5)
    assert items(doc, "images")[0]["view"][0] - image["view"][0] == pytest.approx(du, abs=1.0)
    moved_frame = path_with(doc, stroke=RED_FRAME)["view"]
    assert moved_frame[0] - frame["view"][0] == pytest.approx(du, abs=1.0)
    assert moved_frame[1] - frame["view"][1] == pytest.approx(20, abs=1.5)
    assert kinds(doc) == ["image", "path", "text"]  # die Auswahl bleibt an den Objekten
    assert doc.undoText.endswith("Verschieben")
    key(h, Qt.Key.Key_Z, CTRL)
    analyzed(h, doc)
    assert segment(doc, "Rechnung Nr. 4711")["view"] == pytest.approx(text["view"], abs=0.3)
    assert items(doc, "images")[0]["view"] == pytest.approx(image["view"], abs=0.3)
    assert path_with(doc, stroke=RED_FRAME)["view"] == pytest.approx(frame["view"], abs=0.3)


def test_graphic_properties_menu_opacity_rotation_resize_and_layer(reader_app, tmp_path: Path) -> None:
    """Vektorgrafik: eigenes Kontextmenü (Ebene statt Text bearbeiten), Füllfarbe, Deckkraft, Linienstärke,
    Drehen per Knopf, Größe über den Anfasser – jede Änderung nur an der Grafik."""
    h = reader_app
    path = samples.mixed_objects(tmp_path / "grafik.pdf")
    doc = open_pdf(h, path, whole_page=True)
    objects_tool(h, doc)
    circle = path_with(doc, stroke="")
    right_click(h, page_point(h, 0, *center(circle["view"])))
    _page, menu, entries = object_menu(h)
    assert menu.property("opened") and kinds(doc) == ["path"]
    assert entries["In den Vordergrund"].property("visible") and entries["In den Hintergrund"].property("visible")
    assert not entries["Bearbeiten"].property("visible") and not entries["Text bearbeiten (ganzer Absatz)"].property("visible")
    menu.close()
    pump(0.3)
    assert h.item("readerObjectKind").property("text") == "Grafik (Vektorobjekt)"
    assert h.item("readerObjectFill").property("visible") and not h.item("readerObjectFamily").property("visible")
    doc.styleObjects("fill", "#00AA00")
    analyzed(h, doc)
    assert path_with(doc, fill="#00AA00")["view"] == pytest.approx(circle["view"], abs=0.5)
    assert kinds(doc) == ["path"]  # Auswahl bleibt
    opacity = h.item("readerObjectOpacity")
    click(h, window_point(opacity, opacity.width() / 2, opacity.height() / 2))
    key(h, Qt.Key.Key_A, CTRL)
    type_text(h, "40")
    key(h, Qt.Key.Key_Return)
    analyzed(h, doc)
    assert path_with(doc, fill="#00AA00")["opacity"] == pytest.approx(0.4, abs=0.01)
    # Linienstärke des Rahmens über das Feld
    frame = path_with(doc, stroke=RED_FRAME)
    click(h, page_point(h, 0, *center(frame["view"])))
    width = h.item("readerObjectWidth")
    click(h, window_point(width, width.width() / 2, width.height() / 2))
    key(h, Qt.Key.Key_A, CTRL)
    type_text(h, "4")
    key(h, Qt.Key.Key_Return)
    analyzed(h, doc)
    assert path_with(doc, stroke=RED_FRAME)["width"] == pytest.approx(4.0, abs=0.01)
    # Linie per Knopf um 90° drehen: aus waagerecht wird senkrecht (um ihre Mitte)
    line = path_with(doc, stroke="#000000")
    click(h, page_point(h, 0, line["view"][0] + 40, center(line["view"])[1]))
    assert kinds(doc) == ["path"]
    press(h, "readerObjectRotateRight")
    analyzed(h, doc)
    turned = path_with(doc, stroke="#000000")["view"]
    assert turned[3] - turned[1] == pytest.approx(line["view"][2] - line["view"][0], abs=2.0)
    assert turned[2] - turned[0] < 4 and center(turned) == pytest.approx(center(line["view"]), abs=1.0)
    # Größe: Rahmen an der Ecke rechts unten aufziehen (Grafik: frei, ohne Seitenverhältnis)
    frame = path_with(doc, stroke=RED_FRAME)
    click(h, page_point(h, 0, *center(frame["view"])))
    scale = doc.scale
    corner = page_point(h, 0, frame["view"][2], frame["view"][3])
    drag(h, corner, QPoint(corner.x() + round(40 * scale), corner.y() + round(10 * scale)))
    analyzed(h, doc)
    grown = path_with(doc, stroke=RED_FRAME)["view"]
    assert grown[0] == pytest.approx(frame["view"][0], abs=1.0) and grown[1] == pytest.approx(frame["view"][1], abs=1.0)
    assert grown[2] == pytest.approx(frame["view"][2] + 40, abs=2.0) and grown[3] == pytest.approx(frame["view"][3] + 10, abs=2.0)
    # Text der Seite unverändert, Speichern behält alles
    doc.saveDocument()
    settle(h)
    assert wait_until(lambda: not doc.dirty, 30)
    text = page_text(path)
    assert "Hottgenroth Software AG" in text and "Rechnung Nr. 4711" in text


def test_align_distribute_and_rotate_a_mixed_selection(reader_app, tmp_path: Path) -> None:
    h = reader_app
    doc = open_pdf(h, samples.mixed_objects(tmp_path / "ausrichten.pdf"), whole_page=True)
    objects_tool(h, doc)
    click(h, page_point(h, 0, *center(segment(doc, "Hottgenroth Software AG")["view"])))
    click(h, page_point(h, 0, *center(items(doc, "images")[0]["view"])), CTRL)
    click(h, page_point(h, 0, *center(path_with(doc, stroke=RED_FRAME)["view"])), CTRL)
    assert kinds(doc) == ["image", "path", "text"]
    press(h, "readerAlignRight")
    analyzed(h, doc)
    rights = [segment(doc, "Hottgenroth Software AG")["view"][2], items(doc, "images")[0]["view"][2], path_with(doc, stroke=RED_FRAME)["view"][2]]
    assert max(rights) - min(rights) < 1.0
    assert len(doc.objectSelection) == 3  # weiter ausgewählt
    press(h, "readerDistributeV")
    analyzed(h, doc)
    boxes = sorted([segment(doc, "Hottgenroth Software AG")["view"], items(doc, "images")[0]["view"], path_with(doc, stroke=RED_FRAME)["view"]], key=lambda box: (box[1] + box[3]) / 2)
    gaps = [boxes[1][1] - boxes[0][3], boxes[2][1] - boxes[1][3]]
    assert abs(gaps[0] - gaps[1]) < 1.5
    # Bild allein um 90° drehen: Breite und Höhe tauschen, die Mitte bleibt
    image = items(doc, "images")[0]
    click(h, page_point(h, 0, *center(image["view"])))
    assert kinds(doc) == ["image"]
    right_click(h, page_point(h, 0, *center(image["view"])))
    _page, menu, entries = object_menu(h)
    menu_click(h, entries["Drehen (90° im Uhrzeigersinn)"])
    analyzed(h, doc)
    turned = items(doc, "images")[0]["view"]
    assert turned[2] - turned[0] == pytest.approx(image["view"][3] - image["view"][1], abs=1.0)
    assert turned[3] - turned[1] == pytest.approx(image["view"][2] - image["view"][0], abs=1.0)
    assert center(turned) == pytest.approx(center(image["view"]), abs=1.0)


# --- Zwischenablage ------------------------------------------------------------------------------------------------
def test_copy_paste_objects_between_tabs_offset_and_paste_here(reader_app, tmp_path: Path) -> None:
    """Strg+C in einem Tab, Strg+V in einem anderen: Text (nativ) und Rahmen erscheinen an derselben Stelle
    und sind ausgewählt; erneutes Einfügen legt die Kopie versetzt daneben; »Hier einfügen« an der Maus.
    Gespeichert bleibt alles erhalten. Das Original ändert sich durch Kopieren nicht."""
    h = reader_app
    first = open_pdf(h, samples.mixed_objects(tmp_path / "quelle.pdf"), whole_page=True)
    objects_tool(h, first)
    text = segment(first, "Rechnung Nr. 4711")
    frame = path_with(first, stroke=RED_FRAME)
    click(h, page_point(h, 0, *center(text["view"])))
    click(h, page_point(h, 0, *center(frame["view"])), SHIFT)
    key(h, Qt.Key.Key_C, CTRL)
    settle(h)
    assert QGuiApplication.clipboard().text() == "Rechnung Nr. 4711"
    assert reader(h).canPaste and not first.dirty
    target = samples.object_address(tmp_path / "ziel.pdf")
    second = open_pdf(h, target, whole_page=True)
    objects_tool(h, second)
    click(h, empty_spot(h, second))  # Fokus in die Seite, nichts gewählt
    key(h, Qt.Key.Key_V, CTRL)
    analyzed(h, second)
    assert [item["text"] for item in segments(second)].count("Rechnung Nr. 4711") == 1
    assert path_with(second, stroke=RED_FRAME)["view"] == pytest.approx(frame["view"], abs=1.0)
    assert segment(second, "Rechnung Nr. 4711")["view"] == pytest.approx(text["view"], abs=1.0)
    assert segment(second, "Rechnung Nr. 4711")["native"]  # Originalschrift übernommen
    assert kinds(second) == ["path", "text"]  # das Eingefügte ist ausgewählt
    # Noch einmal: versetzt (nicht deckungsgleich)
    key(h, Qt.Key.Key_V, CTRL)
    analyzed(h, second)
    frames = sorted(item["view"] for item in items(second, "paths") if item["stroke"] == RED_FRAME)
    assert len(frames) == 2 and frames[1][0] - frames[0][0] == pytest.approx(12, abs=1.0)
    # Rechtsklick auf eine freie Stelle: »Hier einfügen« (obere linke Ecke an der Maus)
    right_click(h, page_point(h, 0, 60, 600))
    _page, menu, entries = object_menu(h, "readerObjectPageMenu")
    assert {"Einfügen", "Hier einfügen", "Alles auswählen (Seite)"} <= set(entries)
    menu_click(h, entries["Hier einfügen"])
    analyzed(h, second)
    assert len([item for item in items(second, "paths") if item["stroke"] == RED_FRAME]) == 3
    texts = [item["view"] for item in segments(second) if item["text"] == "Rechnung Nr. 4711"]
    assert len(texts) == 3
    # Die obere linke Ecke der Auswahl (hier die des Textes) liegt an der Maus
    assert min(abs(box[0] - 60) + abs(box[1] - 600) for box in texts) < 4
    assert not first.dirty
    second.saveDocument()
    settle(h)
    assert wait_until(lambda: not second.dirty, 30)
    assert page_text(target).count("Rechnung Nr. 4711") == 3


def test_cut_and_paste_puts_objects_back_and_is_undoable(reader_app, tmp_path: Path) -> None:
    h = reader_app
    doc = open_pdf(h, samples.mixed_objects(tmp_path / "ausschneiden.pdf"), whole_page=True)
    objects_tool(h, doc)
    image = items(doc, "images")[0]
    click(h, page_point(h, 0, *center(image["view"])))
    key(h, Qt.Key.Key_X, CTRL)
    analyzed(h, doc)
    assert items(doc, "images") == [] and doc.objectSelection == []
    assert not QGuiApplication.clipboard().image().isNull()  # andere Programme erhalten das Bild
    key(h, Qt.Key.Key_V, CTRL)
    analyzed(h, doc)
    assert len(items(doc, "images")) == 1
    assert items(doc, "images")[0]["view"] == pytest.approx(image["view"], abs=1.0)  # an der alten Stelle
    key(h, Qt.Key.Key_Z, CTRL)
    analyzed(h, doc)
    assert items(doc, "images") == []
    key(h, Qt.Key.Key_Z, CTRL)
    analyzed(h, doc)
    assert items(doc, "images")[0]["view"] == pytest.approx(image["view"], abs=0.3)


def test_copy_permission_blocks_copy_and_cut_never_deletes_without_a_copy(reader_app, tmp_path: Path) -> None:
    h = reader_app
    doc = open_pdf(h, samples.copy_protected(tmp_path / "geschuetzt.pdf"), whole_page=True)
    objects_tool(h, doc)
    text = segment(doc, "Rechnung Nr. 4711")
    click(h, page_point(h, 0, *center(text["view"])))
    QGuiApplication.clipboard().setText("vorher")
    pump(0.1)
    key(h, Qt.Key.Key_X, CTRL)
    settle(h)
    assert h.app.notices.get("reader").title == "Kopieren nicht erlaubt"
    assert QGuiApplication.clipboard().text() == "vorher"
    assert not doc.dirty and segment(doc, "Rechnung Nr. 4711")
    key(h, Qt.Key.Key_C, CTRL)
    settle(h)
    assert QGuiApplication.clipboard().text() == "vorher" and not doc.dirty


def test_paste_image_and_text_from_other_programs(reader_app, tmp_path: Path) -> None:
    """Steht in der Zwischenablage ein Bild bzw. Text aus einem anderen Programm, fügt Strg+V es auf der
    aktuellen Seite ein: das Bild in seiner Größe (96 dpi, höchstens halbe Seite), der Text als neuer Text."""
    h = reader_app
    doc = open_pdf(h, samples.object_address(tmp_path / "einfuegen.pdf"), whole_page=True)
    objects_tool(h, doc)
    picture = QImage(80, 40, QImage.Format.Format_RGB32)
    picture.fill(QColor("#2060C0"))
    QGuiApplication.clipboard().setImage(picture)
    assert wait_until(lambda: reader(h).canPaste, 5)
    click(h, empty_spot(h, doc))
    key(h, Qt.Key.Key_V, CTRL)
    analyzed(h, doc)
    pasted = items(doc, "images")
    assert len(pasted) == 1
    box = pasted[0]["view"]
    assert box[2] - box[0] == pytest.approx(60, abs=1.0) and box[3] - box[1] == pytest.approx(30, abs=1.0)
    QGuiApplication.clipboard().setText("Eingefügter Text")
    pump(0.1)
    key(h, Qt.Key.Key_V, CTRL)
    analyzed(h, doc)
    assert any(item["text"] == "Eingefügter Text" for item in segments(doc))
    assert len(items(doc, "images")) == 1  # das Bild bleibt


def test_closing_keeps_copied_text_for_other_programs(reader_app, tmp_path: Path) -> None:
    """Beim Beenden ersetzt PDF Tool seine Daten in der Zwischenablage durch Qt-eigene: der Text bleibt für
    andere Programme, die interne Kennung entfällt (sonst stürzte der Abbau der Anwendung ab)."""
    from qtapp.reader.controller import CLIP_FORMAT

    h = reader_app
    doc = open_pdf(h, samples.mixed_objects(tmp_path / "beenden.pdf"), whole_page=True)
    objects_tool(h, doc)
    click(h, page_point(h, 0, *center(segment(doc, "Rechnung Nr. 4711")["view"])))
    key(h, Qt.Key.Key_C, CTRL)
    settle(h)
    board = QGuiApplication.clipboard()
    assert board.mimeData().hasFormat(CLIP_FORMAT)
    reader(h)._release_clipboard()  # noqa: SLF001 - wie beim Beenden (close_all)
    assert board.text() == "Rechnung Nr. 4711" and not board.mimeData().hasFormat(CLIP_FORMAT)
