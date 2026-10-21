"""Reader 4.0: Präsentation, geteilte Ansicht und Vergleichen."""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QWindow

import editorsamples as samples
from conftest import pump, wait_until
from test_qt_reader import key, open_pdf, reader


@pytest.fixture
def reader_app(ui_app):
    ui_app.app.dialogs.shutdown()
    ui_app.navigate("reader", 0.3)
    return ui_app


# --- Präsentation ------------------------------------------------------------------------------------------------
def test_presentation_shows_whole_pages_on_black_and_esc_restores_the_view(reader_app, tmp_path: Path) -> None:
    h = reader_app
    r = reader(h)
    doc = open_pdf(h, samples.standard_text(tmp_path / "Vortrag.pdf", pages=3))
    doc.fitWidth()
    doc.setTool("highlight")
    pump(0.2)
    key(h, Qt.Key.Key_F5)
    assert r.presenting and r.fullScreen
    assert wait_until(lambda: h.window.visibility() == QWindow.Visibility.FullScreen, 5)
    assert doc.viewMode == "single" and doc.fit == "page" and doc.tool == "select"
    pump(0.3)
    assert not h.item("readerViewControls").isVisible() and not h.item("readerToolbar").isVisible()
    view = h.item("readerView")
    view.forceActiveFocus()
    for pressed, page in ((Qt.Key.Key_Right, 1), (Qt.Key.Key_Space, 2), (Qt.Key.Key_Down, 2), (Qt.Key.Key_Left, 1), (Qt.Key.Key_PageUp, 0)):
        key(h, pressed)
        pump(0.1)
        assert doc.currentPage == page, pressed
    key(h, Qt.Key.Key_Escape)
    assert not r.presenting and not r.fullScreen
    assert doc.viewMode == "continuous" and doc.fit == "width" and doc.tool == "highlight"
    assert wait_until(lambda: h.window.visibility() != QWindow.Visibility.FullScreen, 5)
    assert h.item("readerViewControls").isVisible()


# --- Geteilte Ansicht --------------------------------------------------------------------------------------------
def test_split_view_shows_a_second_pdf_beside_and_tabs_swap(reader_app, tmp_path: Path) -> None:
    h = reader_app
    r = reader(h)
    eins = open_pdf(h, samples.standard_text(tmp_path / "eins.pdf"))
    zwei = open_pdf(h, samples.standard_text(tmp_path / "zwei.pdf", pages=2))
    assert r.currentKey == zwei.docId
    r.toggleSplit()
    pump(0.4)
    assert r.splitKey == eins.docId and r.splitDoc is eins
    left, right = h.item("readerView"), h.item("readerSplitView")
    assert right is not None and right.isVisible()
    assert abs(left.width() - right.width()) < 3  # halb und halb
    assert left.mapToScene(left.boundingRect().topRight()).x() <= right.mapToScene(right.boundingRect().topLeft()).x() + 1
    # Klick auf den Tab des rechten PDFs: die beiden tauschen
    r.activate(eins.docId)
    pump(0.3)
    assert r.currentKey == eins.docId and r.splitKey == zwei.docId
    r.swapSplit()
    assert r.currentKey == zwei.docId and r.splitKey == eins.docId
    # Schließen des rechten PDFs beendet die geteilte Ansicht
    r.closeTab(eins.docId)
    pump(0.4)
    assert r.splitKey == "" and h.item("readerSplitView") is None


# --- Vergleichen -------------------------------------------------------------------------------------------------
def test_compare_marks_differences_in_both_versions_and_lists_them(reader_app, tmp_path: Path) -> None:
    h = reader_app
    r = reader(h)
    old_path = samples.standard_text(tmp_path / "Angebot alt.pdf", pages=2)
    new_path = samples.standard_text(tmp_path / "Angebot neu.pdf", pages=2, lines=("Rechnung Nr. 4711 vom 01.10.2026", "Gesamtbetrag: 1.334,56 EUR", "Zahlbar innerhalb von 14 Tagen."))
    newer = open_pdf(h, new_path)
    r.compare_paths(newer, str(old_path))
    assert wait_until(lambda: r.compareActive and not r.compareRunning and r.compareItems, 20), r.compareSummary
    older = r.current
    assert older.path.endswith("Angebot alt.pdf") and r.splitDoc is newer  # alt links, neu rechts
    assert r.compareSummary == "2 Unterschiede: 2 geändert."
    assert [(item["before"], item["after"], item["newPage"]) for item in r.compareItems] == [("1.234,56", "1.334,56", 0), ("1.234,56", "1.334,56", 1)]
    assert set(older.compareRects) == {"0", "1"} and set(newer.compareRects) == {"0", "1"}
    assert r.rightPanel == "compare"
    pump(0.4)
    assert h.item("readerComparePanel").isVisible()
    assert r.compareIndex == 0 and newer.currentCompare["page"] == 0 and older.currentCompare["page"] == 0
    r.nextCompare()
    assert r.compareIndex == 1 and newer.currentPage == 1 and older.currentPage == 1
    r.endCompare()
    assert not r.compareActive and older.compareRects == {} and newer.compareRects == {} and r.rightPanel == ""


def _open_damaged_and_add_tab(h, tmp_path: Path, start) -> tuple:
    r = reader(h)
    first = open_pdf(h, samples.standard_text(tmp_path / "A.pdf"))
    start(r, first, str(samples.damaged(tmp_path / "kaputt.pdf")))
    assert wait_until(lambda: r.opening == 0 and r.engine.idle(), 20)
    pump(0.3)
    h.app.dialogs.shutdown()  # Angebot »PDF reparieren« schließen
    second = open_pdf(h, samples.standard_text(tmp_path / "B.pdf", pages=2))
    pump(0.3)
    return r, first, second


def test_failed_open_of_the_older_version_does_not_compare_a_later_tab(reader_app, tmp_path: Path) -> None:
    """Die ältere Fassung lässt sich nicht öffnen: ein danach geöffnetes PDF startet keinen Vergleich."""
    r, first, second = _open_damaged_and_add_tab(reader_app, tmp_path, lambda r, doc, path: r.compare_paths(doc, path))
    assert not r._compare_pending  # noqa: SLF001
    assert r.current is second and r.splitKey == "" and not r.compareActive and first.ident in r.tabs.keys()


def test_failed_open_beside_does_not_split_a_later_tab(reader_app, tmp_path: Path) -> None:
    """Das PDF für die geteilte Ansicht lässt sich nicht öffnen: ein danach geöffnetes PDF erscheint allein."""
    r, _first, second = _open_damaged_and_add_tab(reader_app, tmp_path, lambda r, _doc, path: r.open_beside(path))
    assert not r._split_pending  # noqa: SLF001
    assert r.current is second and r.splitKey == ""


# --- Hinweise zum Dokument gehen von selbst --------------------------------------------------------------------------
def test_document_notice_hides_itself_after_five_seconds(reader_app, tmp_path: Path) -> None:
    h = reader_app
    doc = open_pdf(h, samples.signed(tmp_path / "signiert.pdf"))
    notice = h.item("readerDocumentNotice")
    assert doc.notice != "" and wait_until(lambda: notice.property("shown") is True, 3)
    pump(3.0)
    assert notice.property("shown") is True  # noch zu lesen
    assert wait_until(lambda: notice.property("shown") is False, 5)
    assert doc.notice != ""  # nur ausgeblendet, der Hinweis gehört weiter zum Dokument
