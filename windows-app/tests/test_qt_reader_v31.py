"""Qt-Oberfläche: PDF Reader – Erweiterungen seit 3.1 (Vollbild, Anhänge, Seitenleisten und Lage je Tab,
Zoom mit eigenem Wert, erste/letzte Seite, Tastenkürzel, Druckbereiche).

Bedient wird wie in ``test_qt_reader`` über Maus, Tastatur und die Controller. Alle PDFs sind künstlich
(``editorsamples``). Nach jedem Test darf die QML-Engine keine Meldung ausgegeben haben (``ui_app``).
"""

from __future__ import annotations

from pathlib import Path

import pikepdf
import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QWindow
from PySide6.QtTest import QTest

import editorsamples as samples
from conftest import pump, wait_until
from test_qt_reader import click, key, open_pdf, page_point, reader, settle, window_point

NO_MOD = Qt.KeyboardModifier.NoModifier
CTRL = Qt.KeyboardModifier.ControlModifier


@pytest.fixture
def reader_app(ui_app):
    ui_app.app.dialogs.shutdown()  # »Neu in Version« (nicht blockierend) schließen
    ui_app.navigate("reader", 0.3)
    assert ui_app.app.currentPage == "reader"
    return ui_app


def center(item):
    return window_point(item, item.width() / 2, item.height() / 2)


# --- Vollbild ------------------------------------------------------------------------------------------------
def test_full_screen_shows_only_the_document_and_esc_returns(reader_app, tmp_path: Path) -> None:
    h = reader_app
    doc = open_pdf(h, samples.standard_text(tmp_path / "Voll.pdf", pages=3))
    r = reader(h)
    before = h.window.visibility()
    nav, tabs, toolbar = h.item("navigationPane"), h.item("readerTabs"), h.item("readerToolbar")
    assert nav.isVisible() and tabs.isVisible() and toolbar.isVisible()
    key(h, Qt.Key.Key_F11)
    assert r.fullScreen is True
    assert wait_until(lambda: h.window.visibility() == QWindow.Visibility.FullScreen, 5)
    pump(0.3)
    assert not nav.isVisible() and not tabs.isVisible() and not toolbar.isVisible()
    assert not h.item("readerLeftRail").isVisible() and not h.item("readerRightRail").isVisible()
    controls = h.item("readerViewControls")
    assert controls.isVisible()  # Seite, Zoom und »Vollbild beenden« bleiben erreichbar
    # Esc in der Seite: zuerst Auswahl bzw. Werkzeug, dann das Vollbild
    doc.setTool("highlight")
    view = h.item("readerView")
    view.forceActiveFocus()
    key(h, Qt.Key.Key_Escape)
    assert doc.tool == "select" and r.fullScreen is True
    key(h, Qt.Key.Key_Escape)
    assert r.fullScreen is False
    assert wait_until(lambda: h.window.visibility() == before, 5)
    pump(0.3)
    assert nav.isVisible() and tabs.isVisible() and toolbar.isVisible()
    # Schaltfläche in der schwebenden Leiste; Verlassen des Readers beendet das Vollbild
    click(h, center(h.item("readerFullScreen")))
    assert r.fullScreen is True
    h.navigate("home")
    assert r.fullScreen is False
    assert wait_until(lambda: h.window.visibility() == before, 5)


def test_full_screen_ends_with_the_last_document(reader_app, tmp_path: Path) -> None:
    h = reader_app
    doc = open_pdf(h, samples.standard_text(tmp_path / "Allein.pdf"))
    r = reader(h)
    r.toggleFullScreen()
    assert r.fullScreen
    r.closeTab(doc.ident)
    settle(h)
    assert not r.fullScreen and not r.hasDocument


# --- Anhänge -----------------------------------------------------------------------------------------------
def test_attachments_panel_save_open_add_remove(reader_app, tmp_path: Path, monkeypatch) -> None:
    from qtapp import dialogs, files

    h = reader_app
    path = samples.structured(tmp_path / "Anhang.pdf")
    with pikepdf.open(path, allow_overwriting_input=True) as pdf:
        pdf.attachments["setup.exe"] = pikepdf.AttachedFileSpec(pdf, b"MZ", filename="setup.exe")
        pdf.save(path, fix_metadata_version=False)  # XMP unverändert (ohne lxml, wie die App)
    doc = open_pdf(h, path)
    r = reader(h)
    r.showLeftPanel("attachments")
    pump(0.4)
    assert h.item("readerAttachmentsPanel") is not None and h.item("readerAttachmentsPanel").isVisible()
    assert doc.attachmentCount == 2
    names = [item["name"] for item in doc.attachmentList.items()]
    assert names == ["notiz.txt", "setup.exe"]
    keys = {item["name"]: item["key"] for item in doc.attachmentList.items()}
    # Speichern unter
    monkeypatch.setattr(files, "RESPONSES", [str(tmp_path / "gespeichert.txt")])
    doc.saveAttachment(keys["notiz.txt"])
    settle(h)
    assert (tmp_path / "gespeichert.txt").read_bytes() == b"Anhang zum Test"
    # Öffnen: Text nach Rückfrage mit dem zugeordneten Programm, ein Programm nie
    opened = []
    monkeypatch.setattr(files, "open_path", lambda target: opened.append(Path(target)))
    monkeypatch.setattr(dialogs, "AUTO_ANSWER", "primary")
    doc.openAttachment(keys["notiz.txt"])
    settle(h)
    assert len(opened) == 1 and opened[0].name == "notiz.txt" and opened[0].read_bytes() == b"Anhang zum Test"
    doc.openAttachment(keys["setup.exe"])
    settle(h)
    assert len(opened) == 1
    assert h.app.notices.get("reader").title == "Anhang nicht geöffnet"
    # Hinzufügen und Entfernen – mit Rückgängig
    extra = tmp_path / "Beleg.csv"
    extra.write_text("a;b\n1;2\n", encoding="utf-8")
    monkeypatch.setattr(files, "RESPONSES", [str(extra)])
    doc.addAttachment()
    settle(h)
    assert [item["name"] for item in doc.attachmentList.items()] == ["Beleg.csv", "notiz.txt", "setup.exe"]
    assert doc.dirty
    doc.removeAttachment(keys["setup.exe"])
    settle(h)
    assert [item["name"] for item in doc.attachmentList.items()] == ["Beleg.csv", "notiz.txt"]
    doc.undo()
    settle(h)
    assert [item["name"] for item in doc.attachmentList.items()] == ["Beleg.csv", "notiz.txt", "setup.exe"]
    # Speichern und neu öffnen: Anhänge in der Datei
    doc.saveDocument()
    settle(h)
    with pikepdf.open(path) as pdf:
        assert sorted(pdf.attachments) == ["Beleg.csv", "notiz.txt", "setup.exe"]
    # Geöffnete Anhänge liegen in einem eigenen Ordner, der beim Beenden entfernt wird
    folder = Path(r.attachment_dir())
    assert folder.is_dir()
    r._remove_attachment_dir()  # noqa: SLF001
    assert not folder.exists()


def test_attachments_empty_state(reader_app, tmp_path: Path) -> None:
    h = reader_app
    doc = open_pdf(h, samples.standard_text(tmp_path / "Ohne.pdf"))
    reader(h).showLeftPanel("attachments")
    pump(0.4)
    assert doc.attachmentCount == 0
    assert h.item("readerAttachmentsEmpty").isVisible()


# --- Je Tab: Seitenleisten, Suche, Lage ------------------------------------------------------------------------
def test_side_panels_search_options_and_position_are_per_tab(reader_app, tmp_path: Path) -> None:
    h = reader_app
    r = reader(h)
    a = open_pdf(h, samples.standard_text(tmp_path / "A.pdf", pages=8))
    r.showLeftPanel("search")
    a.search("Zeile", True, False)
    settle(h)
    r.showRightPanel("comments")
    view = h.item("readerView")
    view.setProperty("contentY", view.property("contentHeight") * 0.55)
    pump(0.3)
    page_a = a.currentPage
    y_a = view.property("contentY")
    assert page_a > 2
    b = open_pdf(h, samples.standard_text(tmp_path / "B.pdf", pages=2))
    # Neuer Tab übernimmt die Leisten des bisherigen; danach eigene Wahl
    r.showLeftPanel("outline")
    r.setRightPanel("comments")
    assert (r.leftPanel, r.rightPanel) == ("outline", "")
    r.activate(a.ident)
    pump(0.4)
    assert (r.leftPanel, r.rightPanel) == ("search", "comments")
    assert a.currentPage == page_a and abs(view.property("contentY") - y_a) < 4
    case_box = h.item("readerSearchCase")
    assert case_box.property("checked") is True and a.searchCase is True
    r.activate(b.ident)
    pump(0.4)
    assert (r.leftPanel, r.rightPanel) == ("outline", "")
    r.showLeftPanel("search")
    pump(0.3)
    assert h.item("readerSearchCase").property("checked") is False


# --- Navigation und Zoom ----------------------------------------------------------------------------------------
def test_first_last_page_buttons_and_go_to_shortcut(reader_app, tmp_path: Path) -> None:
    h = reader_app
    doc = open_pdf(h, samples.standard_text(tmp_path / "Blättern.pdf", pages=6))
    click(h, center(h.item("readerLastPage")))
    pump(0.2)
    assert doc.currentPage == 5
    click(h, center(h.item("readerFirstPage")))
    pump(0.2)
    assert doc.currentPage == 0
    key(h, Qt.Key.Key_G, CTRL)
    field = h.item("readerPageField")
    assert field.hasActiveFocus()
    for char in "4":
        QTest.keyClick(h.window, char)
    key(h, Qt.Key.Key_Return)
    pump(0.2)
    assert doc.currentPage == 3


def test_custom_zoom_value(reader_app, tmp_path: Path) -> None:
    h = reader_app
    doc = open_pdf(h, samples.standard_text(tmp_path / "Zoom.pdf"))
    field = h.item("readerZoomField")
    click(h, center(field))
    assert field.hasActiveFocus()
    QTest.keyClick(h.window, Qt.Key.Key_A, CTRL)
    for char in "137":
        QTest.keyClick(h.window, char)
    key(h, Qt.Key.Key_Return)
    pump(0.4)
    assert abs(doc.zoom - 137) < 0.01 and doc.fit == ""
    assert field.property("text") == "137 %"
    # Werte außerhalb von 10–800 % werden begrenzt
    click(h, center(field))
    QTest.keyClick(h.window, Qt.Key.Key_A, CTRL)
    for char in "999":
        QTest.keyClick(h.window, char)
    key(h, Qt.Key.Key_Return)
    pump(0.4)
    assert doc.zoom == 800


def test_ctrl_a_selects_the_text_of_the_current_page(reader_app, tmp_path: Path) -> None:
    h = reader_app
    doc = open_pdf(h, samples.standard_text(tmp_path / "Alles.pdf", pages=2), whole_page=True)
    click(h, page_point(h, 0, 20, 20))
    key(h, Qt.Key.Key_A, CTRL)
    assert wait_until(lambda: doc.selectionPage == 0 and len(doc.selectionRects) > 0, 5)


# --- Drucken: Bereiche und Kopien --------------------------------------------------------------------------------
def test_print_ranges_selection_and_copies() -> None:
    from PySide6.QtGui import QPageRanges
    from PySide6.QtPrintSupport import QPrinter

    from qtapp.reader.printing import chosen_pages, copies

    printer = QPrinter()
    printer.setPrintRange(QPrinter.PrintRange.PageRange)
    ranges = QPageRanges()
    ranges.addRange(1, 2)
    ranges.addPage(4)
    printer.setPageRanges(ranges)
    assert chosen_pages(printer, 10, 0, []) == [0, 1, 3]
    printer.setPrintRange(QPrinter.PrintRange.Selection)
    assert chosen_pages(printer, 10, 0, [2, 5]) == [2, 5]
    printer.setPrintRange(QPrinter.PrintRange.CurrentPage)
    assert chosen_pages(printer, 10, 7, []) == [7]
    printer.setPrintRange(QPrinter.PrintRange.AllPages)
    assert chosen_pages(printer, 3, 0, []) == [0, 1, 2]

    class Driver:
        def __init__(self, count: int, multiple: bool, collate: bool) -> None:
            self.values = (count, multiple, collate)

        def copyCount(self) -> int:  # noqa: N802
            return self.values[0]

        def supportsMultipleCopies(self) -> bool:  # noqa: N802
            return self.values[1]

        def collateCopies(self) -> bool:  # noqa: N802
            return self.values[2]

    assert copies([0, 1], Driver(2, True, True)) == [0, 1]  # der Treiber druckt die Kopien
    assert copies([0, 1], Driver(2, False, True)) == [0, 1, 0, 1]
    assert copies([0, 1], Driver(2, False, False)) == [0, 0, 1, 1]
