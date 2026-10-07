"""Qt-Oberfläche: Texterkennung (OCR) im PDF Reader & Editor – Hinweis bei gescannten Seiten, Dialog (Seiten,
Sprachen), Erkennung im Hintergrund mit Fortschritt und Abbrechen, danach durchsuchbar und ein Schritt für
Rückgängig. Läuft nur mit Tesseract auf diesem Rechner (sonst übersprungen – das gebündelte Tesseract prüft
der Laufzeit-Test des Setups). Alle PDFs sind künstlich (``editorsamples``)."""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import QTimer

import editorsamples as samples
from conftest import pump, wait_until
from test_qt_reader import click, open_pdf, page_text, reader, settle, window_point
from tools.pdf_editor import ocr

ENGINE = ocr.find_engine()
pytestmark = pytest.mark.skipif(ENGINE is None or "deu" not in ENGINE.languages, reason="Tesseract mit deutschen Sprachdaten fehlt")


@pytest.fixture
def reader_app(ui_app, monkeypatch):
    from qtapp import dialogs

    monkeypatch.setattr(dialogs, "AUTO_ANSWER", None)  # der echte Dialog – beantwortet von ``answer_ocr``
    ui_app.app.dialogs.shutdown()
    ui_app.navigate("reader", 0.3)
    return ui_app


def answer_ocr(h, *, scope: str = "all", languages=("deu",), redo: bool = False, seen: list | None = None, button: str = "primary") -> None:
    """Den echten Dialog abwarten (er blockiert, bis er beantwortet ist), seinen Inhalt prüfen und antworten."""
    def respond() -> None:
        service = h.app.dialogs
        if not service.open or service.request.get("kind") != "ocr":
            QTimer.singleShot(50, respond)
            return
        if seen is not None:
            pump(0.2)
            seen.append({
                "data": dict(service.request["data"]),
                "all": h.item("ocrScopeAll").isVisible(),
                "selected": h.item("ocrScopeSelected").isVisible(),
                "deu": h.item("ocrLanguage_deu").property("checked") if h.item("ocrLanguage_deu") is not None else None,
            })
        service.answer(service.request["id"], button, {"scope": scope, "languages": list(languages), "redo": redo})

    QTimer.singleShot(50, respond)


def press_action(h, bar, text: str) -> None:
    """Schaltfläche ``text`` in einem Hinweis anklicken (wie mit der Maus)."""
    todo, found = list(bar.childItems()), None
    while todo and found is None:
        item = todo.pop()
        if item.property("text") == text and item.isVisible():
            found = item
        todo.extend(item.childItems())
    assert found is not None, text
    click(h, window_point(found, found.width() / 2, found.height() / 2))


def wait_for_ocr(h, doc, timeout: float = 120) -> None:
    assert wait_until(lambda: not doc.ocrRunning, timeout), "Texterkennung wurde nicht fertig"
    settle(h)


def test_scanned_pdf_offers_ocr_and_makes_the_page_searchable(reader_app, tmp_path: Path) -> None:
    """Gescanntes PDF: Hinweis mit »Text erkennen …«; der Dialog bietet Seiten und Sprachen an. Danach ist
    der Text such- und kopierbar, das Aussehen unverändert, ein Rückgängig nimmt alles zurück; Speichern
    behält die Textebene."""
    h = reader_app
    path = samples.scanned(tmp_path / "scan.pdf")
    doc = open_pdf(h, path, whole_page=True)
    assert wait_until(lambda: doc.scanHint, 20), "Hinweis auf gescannte Seiten fehlt"
    notice = h.item("readerScanNotice")
    assert wait_until(lambda: notice.property("shown") is True, 5)
    assert wait_until(lambda: reader(h).ocrState == "bereit", 30)
    seen: list = []
    answer_ocr(h, seen=seen)
    press_action(h, notice, "Text erkennen …")
    assert seen and seen[0]["all"] and not seen[0]["selected"] and seen[0]["deu"] is True
    assert seen[0]["data"]["pageCount"] == 1
    assert wait_until(lambda: doc.ocrRunning or doc.undoText, 10)
    wait_for_ocr(h, doc)
    assert doc.undoText.endswith("Text erkennen (OCR)")
    assert not doc.scanHint and notice.property("shown") is False
    assert h.app.notices.get("reader").title == "Text erkannt"
    # Suchen findet den erkannten Text
    doc.search("Rechnung", False, False)
    assert wait_until(lambda: doc.searchCount >= 1, 20)
    # Rückgängig: wieder ohne Text; Wiederholen: wieder mit
    doc.undo()
    settle(h)
    assert doc.undoText == "" and not doc.dirty
    doc.redo()
    settle(h)
    doc.saveDocument()
    settle(h)
    assert wait_until(lambda: not doc.dirty, 30)
    assert "Rechnung" in page_text(path)


def test_cancel_stops_the_recognition_and_changes_nothing(reader_app, tmp_path: Path, monkeypatch) -> None:
    h = reader_app
    path = samples.scanned(tmp_path / "abbrechen.pdf")
    doc = open_pdf(h, path, whole_page=True)
    assert wait_until(lambda: reader(h).ocrState == "bereit", 30)
    started = []
    original = ocr.recognize

    def slow(*args, **kwargs):  # erst nach dem Abbrechen weiterlaufen lassen
        started.append(True)
        assert kwargs["cancel"].wait(30)
        return original(*args, **kwargs)

    monkeypatch.setattr(ocr, "recognize", slow)
    answer_ocr(h, scope="current")
    doc.recognizeText([])
    assert wait_until(lambda: started, 20)
    card = h.item("readerOcrProgress")
    assert doc.ocrRunning and card.isVisible()
    assert doc.ocrTotal == 1 and "wird erkannt" in doc.ocrStatus
    # Während der Erkennung bleibt das Dokument unverändert: Bearbeiten wartet
    doc.addText(0, 100, 100, "Neu", {})
    assert h.app.notices.get("reader").title == "Texterkennung läuft"
    doc.cancelOcr()
    wait_for_ocr(h, doc)
    assert h.app.notices.get("reader").title == "Abgebrochen"
    assert doc.undoText == "" and not doc.dirty
    assert wait_until(lambda: not card.isVisible(), 3)  # blendet aus


def test_pages_with_text_are_skipped_and_selected_pages_are_offered(reader_app, tmp_path: Path) -> None:
    """Gemischtes PDF (Seite 1 mit echtem Text, Seite 2 gescannt): »Ausgewählte Seiten« erscheint mit einer
    Auswahl; die Textseite wird nie erkannt (sonst stünde ihr Text doppelt im Dokument)."""
    h = reader_app
    doc = open_pdf(h, samples.scanned(tmp_path / "gemischt.pdf", text_page=True), whole_page=True)
    assert wait_until(lambda: reader(h).ocrState == "bereit", 30)
    seen: list = []
    answer_ocr(h, scope="selected", seen=seen)
    doc.recognizeText([0])
    assert seen and seen[0]["selected"] and seen[0]["data"]["selected"] == [0]
    wait_for_ocr(h, doc)
    assert doc.undoText == ""  # nichts geändert
    assert "bereits Text" in h.app.notices.get("reader").message
    answer_ocr(h, scope="all")
    doc.recognizeText([])
    wait_for_ocr(h, doc)
    assert doc.undoText.endswith("Text erkennen (OCR)")
    assert "1 Seite durchsuchbar gemacht" in h.app.notices.get("reader").message
