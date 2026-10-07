"""Qt-Oberfläche 3.1: Seiten verwalten – Rahmenauswahl in »Seiten organisieren«, Seiten kopieren, ausschneiden
und einfügen (auch in einem anderen Tab), Seiten aus einer anderen PDF teilweise einfügen, Befehle im
Kontextmenü der Miniaturen und gewählte Seiten drucken.

Bedient wird wie von Hand (Maus, Tastatur, Kontextmenü, Dialoge). Alle PDFs sind künstlich (``editorsamples``).
Nach jedem Test darf die QML-Engine keine Meldung ausgegeben haben (Fixture ``ui_app``).
"""

from __future__ import annotations

from pathlib import Path

import pikepdf
import pytest
from PySide6.QtCore import QObject, QPoint, Qt, QTimer
from PySide6.QtTest import QTest

import editorsamples as samples
from conftest import pump, wait_until
from test_qt_reader import click, key, open_pdf, page_text, prop, reader, right_click, settle, window_point

CTRL = Qt.KeyboardModifier.ControlModifier
NO_MOD = Qt.KeyboardModifier.NoModifier
LEFT = Qt.MouseButton.LeftButton


@pytest.fixture
def reader_app(ui_app):
    ui_app.app.dialogs.shutdown()
    ui_app.navigate("reader", 0.3)
    return ui_app


# --- Hilfen ----------------------------------------------------------------------------------------------------
def organize(h):
    """»Seiten organisieren« im aktuellen Tab einschalten – Raster und Ansicht zurückgeben."""
    reader(h).setOrganize(True)
    pump(0.4)
    grid, view = h.item("readerOrganizeGrid"), h.item("readerOrganizeView")
    assert grid is not None and view is not None
    return grid, view


def cell_point(grid, index: int, dx: float = 0.5, dy: float = 0.5) -> QPoint:
    """Punkt in der Zelle ``index`` (``dx``/``dy``: Anteil der Zellbreite/-höhe)."""
    width, height, columns = grid.property("cellWidth"), grid.property("cellHeight"), grid.property("columns")
    x = (index % columns) * width + width * dx - grid.property("contentX")
    y = (index // columns) * height + height * dy - grid.property("contentY")
    return window_point(grid, x, y)


def below_cells(grid, column: float) -> QPoint:
    """Freie Fläche unter der letzten Zeile des Rasters (Spalte ``column``, auch Bruchteile)."""
    rows = -(-grid.property("count") // grid.property("columns"))
    x = grid.property("cellWidth") * column - grid.property("contentX")
    y = rows * grid.property("cellHeight") + 30 - grid.property("contentY")
    assert y < grid.height(), "keine freie Fläche unter den Seiten"
    return window_point(grid, x, y)


def page_footers(path: Path) -> list[str]:
    """Die Fußzeile »Seite x von y« jeder Seite (``standard_text``) – zeigt, welche Seite wo steht."""
    with pikepdf.open(path) as pdf:
        count = len(pdf.pages)
    found = []
    for page in range(count):
        text = page_text(path, page)
        found.append(next((line.strip() for line in text.splitlines() if line.strip().startswith("Seite ")), ""))
    return found


def answer_dialog(h, kind: str, value: dict, seen: list | None = None, button: str = "primary") -> None:
    """Den echten (blockierenden) Dialog ``kind`` abwarten, seine Anfrage merken und antworten."""
    def respond() -> None:
        service = h.app.dialogs
        if not service.open or service.request.get("kind") != kind:
            QTimer.singleShot(50, respond)
            return
        if seen is not None:
            seen.append(dict(service.request))
        service.answer(service.request["id"], button, value)

    QTimer.singleShot(50, respond)


def menu_entries(owner, name: str) -> dict:
    """Einträge (Text → Eintrag) des Menüs ``name`` unterhalb von ``owner`` (Menüs hängen nicht im Elementbaum)."""
    menus = [obj for obj in owner.findChildren(QObject) if obj.objectName() == name]
    assert len(menus) == 1, name
    return {obj.property("text"): obj for obj in menus[0].findChildren(QObject) if obj.property("text") and obj.property("enabled") is not None and hasattr(obj, "mapToScene")}


def thumbnail(h, index: int):
    """Die Miniatur der Seite ``index`` in der Seitenleiste »Seiten«."""
    thumbs = h.item("readerThumbnails")
    assert thumbs is not None
    todo, found = list(thumbs.childItems()), None
    while todo and found is None:
        item = todo.pop()
        if item.property("thumbW") is not None and item.property("index") == index and item.isVisible():
            found = item
        todo.extend(item.childItems())
    assert found is not None, f"Miniatur {index + 1} fehlt"
    return thumbs, found


# --- Rahmenauswahl, Kopieren und Einfügen über Tabs ---------------------------------------------------------------
def test_marquee_selects_pages_copy_in_one_tab_and_paste_in_another(reader_app, tmp_path: Path) -> None:
    """Rahmen auf freier Fläche wählt Seite 2 und 3; Strg+C in Tab A, Strg+V in Tab B hängt sie in B an.
    A bleibt unverändert; in B lässt sich das Einfügen rückgängig machen; gespeichert stehen die Seiten in B."""
    h = reader_app
    source = open_pdf(h, samples.standard_text(tmp_path / "quelle.pdf", pages=4))
    grid, view = organize(h)
    assert grid.property("count") == 4 and grid.property("columns") >= 4  # eine Zeile
    # Rahmen von der freien Fläche unter Seite 2 bis in die Mitte von Seite 3 ziehen
    start, end = below_cells(grid, 1.15), cell_point(grid, 2, dx=0.85)
    QTest.mousePress(h.window, LEFT, NO_MOD, start)
    for step in range(1, 9):
        QTest.mouseMove(h.window, QPoint(start.x() + (end.x() - start.x()) * step // 8, start.y() + (end.y() - start.y()) * step // 8))
        pump(0.02)
    assert h.item("readerOrganizeMarquee").isVisible()
    QTest.mouseRelease(h.window, LEFT, NO_MOD, end)
    pump(0.2)
    assert prop(view, "selectedPages") == [1, 2]
    assert not h.item("readerOrganizeMarquee").isVisible()
    key(h, Qt.Key.Key_C, CTRL)
    settle(h)
    assert wait_until(lambda: reader(h).pageClip == 2, 10)
    assert not source.dirty and source.pageCount == 4
    # Anderer Tab: Strg+V ohne Auswahl hängt die Seiten am Ende an
    target = samples.standard_text(tmp_path / "ziel.pdf", pages=2, lines=("Zieldokument",))
    second = open_pdf(h, target)
    grid, view = organize(h)
    assert grid.property("count") == 2 and prop(view, "selectedPages") == []
    click(h, below_cells(grid, 0.5))  # Fokus ins Raster, nichts gewählt
    assert h.item("readerOrganizePaste").property("enabled")
    key(h, Qt.Key.Key_V, CTRL)
    settle(h)
    assert wait_until(lambda: second.pageCount == 4, 20)
    assert second.dirty and second.undoText == "Seiten einfügen"
    key(h, Qt.Key.Key_Z, CTRL)
    settle(h)
    assert second.pageCount == 2
    key(h, Qt.Key.Key_Y, CTRL)
    settle(h)
    assert second.pageCount == 4
    second.saveDocument()
    settle(h)
    assert wait_until(lambda: not second.dirty, 30)
    assert page_footers(target) == ["Seite 1 von 2", "Seite 2 von 2", "Seite 2 von 4", "Seite 3 von 4"]
    assert "Zieldokument" in page_text(target, 0)
    assert not source.dirty and source.pageCount == 4  # die Quelle blieb, wie sie war
    reader(h).setOrganize(False)


def test_cut_page_and_paste_it_from_the_thumbnail_menu(reader_app, tmp_path: Path) -> None:
    """Strg+X schneidet Seite 1 aus (erst kopiert, dann entfernt); in der Seitenleiste »Seiten« fügt
    »Einfügen danach« im Kontextmenü der letzten Miniatur sie am Ende wieder ein."""
    h = reader_app
    path = samples.standard_text(tmp_path / "seiten.pdf", pages=4)
    doc = open_pdf(h, path)
    grid, view = organize(h)
    click(h, cell_point(grid, 0))
    assert prop(view, "selectedPages") == [0]
    key(h, Qt.Key.Key_X, CTRL)
    settle(h)
    assert wait_until(lambda: doc.pageCount == 3, 20)
    assert doc.undoText == "Seite ausschneiden" and reader(h).pageClip == 1
    reader(h).setOrganize(False)
    reader(h).showLeftPanel("thumbs")
    pump(0.6)
    thumbs, last = thumbnail(h, 2)
    right_click(h, window_point(last, last.width() / 2, last.height() / 2))
    entries = menu_entries(thumbs, "readerThumbnailMenu")
    assert {"Kopieren", "Einfügen danach", "Drucken …", "Als neue PDF speichern …", "Löschen"} <= set(entries)
    paste = entries["Einfügen danach"]
    assert paste.isVisible()
    click(h, window_point(paste, paste.width() / 2, paste.height() / 2))
    settle(h)
    assert wait_until(lambda: doc.pageCount == 4, 20)
    assert doc.undoText == "Seiten einfügen"
    doc.saveDocument()
    settle(h)
    assert wait_until(lambda: not doc.dirty, 30)
    assert page_footers(path) == ["Seite 2 von 4", "Seite 3 von 4", "Seite 4 von 4", "Seite 1 von 4"]


def test_cut_never_removes_every_page(reader_app, tmp_path: Path) -> None:
    h = reader_app
    doc = open_pdf(h, samples.standard_text(tmp_path / "zwei.pdf", pages=2))
    grid, view = organize(h)
    click(h, cell_point(grid, 0))
    key(h, Qt.Key.Key_A, CTRL)
    assert prop(view, "selectedPages") == [0, 1]
    key(h, Qt.Key.Key_X, CTRL)
    settle(h)
    assert doc.pageCount == 2 and not doc.dirty
    assert h.app.notices.get("reader").title == "Nicht möglich"
    reader(h).setOrganize(False)


# --- Seiten aus einer anderen PDF (alle oder ausgewählte) ----------------------------------------------------------
def test_insert_selected_pages_from_another_pdf(reader_app, tmp_path: Path, monkeypatch) -> None:
    """»Seiten aus PDF danach einfügen …«: der Dialog nennt die Seitenzahl der Quelle; »2, 4-5« fügt genau
    diese Seiten hinter der gewählten ein. Eine ungültige Angabe ändert nichts und sagt, warum."""
    from qtapp import dialogs, files

    monkeypatch.setattr(dialogs, "AUTO_ANSWER", None)  # der echte Dialog – beantwortet von ``answer_dialog``
    h = reader_app
    path = samples.standard_text(tmp_path / "ziel.pdf", pages=2, lines=("Zieldokument",))
    source = samples.standard_text(tmp_path / "quelle.pdf", pages=5, lines=("Quelldokument",))
    doc = open_pdf(h, path)
    grid, view = organize(h)
    click(h, cell_point(grid, 0))
    # Ungültig: Seite 7 gibt es in der Quelle nicht
    files.RESPONSES.append(str(source))
    seen: list = []
    answer_dialog(h, "text_input", {"value": "7"}, seen)
    click(h, window_point(h.item("readerOrganizeInsertFile"), 10, 10))
    settle(h)
    assert seen and "hat 5 Seiten" in seen[0]["message"] and seen[0]["data"]["value"] == "1-5"
    notice = h.app.notices.get("reader")
    assert notice.title == "Seiten einfügen" and "außerhalb der Seiten 1 bis 5" in notice.message
    assert doc.pageCount == 2 and not doc.dirty
    # Gültig: Seiten 2, 4 und 5 hinter Seite 1
    files.RESPONSES.append(str(source))
    answer_dialog(h, "text_input", {"value": "2, 4-5"})
    click(h, cell_point(grid, 0))
    click(h, window_point(h.item("readerOrganizeInsertFile"), 10, 10))
    settle(h)
    assert wait_until(lambda: doc.pageCount == 5, 20)
    assert doc.undoText == "Seiten einfügen"
    doc.saveDocument()
    settle(h)
    assert wait_until(lambda: not doc.dirty, 30)
    assert page_footers(path) == ["Seite 1 von 2", "Seite 2 von 5", "Seite 4 von 5", "Seite 5 von 5", "Seite 2 von 2"]
    assert "Quelldokument" in page_text(path, 1) and "Zieldokument" in page_text(path, 0)
    reader(h).setOrganize(False)


# --- Drucken der Auswahl ------------------------------------------------------------------------------------------
def test_print_selected_pages_preselects_the_selection(reader_app, tmp_path: Path, monkeypatch) -> None:
    """Seite 2 und 4 wählen (Klick, Strg+Klick), »Drucken«: im Druckdialog ist »Auswahl« vorgewählt, gedruckt
    werden genau diese beiden Seiten."""
    from PySide6 import QtPrintSupport
    from PySide6.QtPrintSupport import QPrinter

    from qtapp.reader import printing

    target = tmp_path / "gedruckt.pdf"
    shown: dict = {}

    class Dialog:
        """Druckdialog wie nach »Drucken« mit den Vorgaben – druckt in eine PDF statt auf Papier."""
        DialogCode = QtPrintSupport.QPrintDialog.DialogCode

        def __init__(self, printer) -> None:
            self.printer = printer

        def setWindowTitle(self, title: str) -> None:  # noqa: N802
            shown["title"] = title

        def setOptions(self, options) -> None:  # noqa: N802
            shown["options"] = options

        def exec(self):
            shown["range"] = self.printer.printRange()
            self.printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
            self.printer.setOutputFileName(str(target))
            return self.DialogCode.Accepted

    painted: list = []
    original = printing._paint
    monkeypatch.setattr(QtPrintSupport, "QPrintDialog", Dialog)
    monkeypatch.setattr(printing, "_paint", lambda printer, doc, pages, *args, **kwargs: painted.append(list(pages)) or original(printer, doc, pages, *args, **kwargs))
    h = reader_app
    open_pdf(h, samples.standard_text(tmp_path / "druck.pdf", pages=4))
    grid, view = organize(h)
    click(h, cell_point(grid, 1))
    click(h, cell_point(grid, 3), CTRL)
    assert prop(view, "selectedPages") == [1, 3]
    click(h, window_point(h.item("readerOrganizePrint"), 10, 10))
    settle(h)
    assert shown["title"] == "Drucken" and shown["range"] == QPrinter.PrintRange.Selection
    assert painted == [[1, 3]]
    assert wait_until(lambda: target.is_file(), 20)
    with pikepdf.open(target) as printed:
        assert len(printed.pages) == 2
    reader(h).setOrganize(False)
