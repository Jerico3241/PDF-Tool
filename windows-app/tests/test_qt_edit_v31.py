"""Qt-Oberfläche 3.1: Text hinzufügen mit Unterstreichen, Durchstreichen und Ausrichtung; Kommentare
nachträglich formatieren (Linienstärke, Füllung, Deckkraft), an den Ecken in der Größe ändern und beantworten.

Bedient wird wie von Hand (Werkzeuge, Maus, Leisten, Seitenleiste). Alle PDFs sind künstlich
(``editorsamples``). Nach jedem Test darf die QML-Engine keine Meldung ausgegeben haben (Fixture ``ui_app``).
"""

from __future__ import annotations

from pathlib import Path

import pikepdf
import pytest
from PySide6.QtCore import QPoint

import editorsamples as samples
from conftest import pump, wait_until
from test_qt_reader import click, drag, open_pdf, page_point, page_text, reader, settle, window_point


@pytest.fixture
def reader_app(ui_app):
    ui_app.app.dialogs.shutdown()
    ui_app.navigate("reader", 0.3)
    return ui_app


def press(h, name: str) -> None:
    item = next((entry for entry in h.items(name) if entry.isVisible()), None)
    assert item is not None, name
    click(h, window_point(item, item.width() / 2, item.height() / 2))


def visual_items(root) -> list:
    found, todo = [], [root]
    while todo:
        item = todo.pop()
        found.append(item)
        todo.extend(item.childItems())
    return found


def choose(h, name: str, label: str) -> None:
    """Eintrag ``label`` einer Auswahlliste (PComboBox) wählen – aufklappen, dann anklicken."""
    press(h, name)
    pump(0.4)
    entries = [item for item in visual_items(h.window.contentItem()) if item.property("itemText") == label and item.isVisible()]
    assert entries, label
    entry = entries[0]
    click(h, window_point(entry, entry.width() / 2, entry.height() / 2))
    settle(h)


def test_added_text_is_underlined_struck_and_centered(reader_app, tmp_path: Path) -> None:
    h = reader_app
    path = samples.standard_text(tmp_path / "text.pdf")
    doc = open_pdf(h, path, whole_page=True)
    doc.setTool("addText")
    pump(0.1)
    click(h, page_point(h, 0, 72, 420))
    for name in ("readerEditorUnderline", "readerEditorStrike", "readerEditorAlign_center"):
        press(h, name)
    editor = h.item("readerTextEditor")
    assert editor.property("underline") is True and editor.property("strike") is True and editor.property("align") == "center"
    h.item("readerEditorInput").setProperty("text", "Wichtig")
    press(h, "readerEditorApply")
    settle(h)
    assert doc.undoText == "Text hinzufügen"
    doc.saveDocument()
    settle(h)
    assert wait_until(lambda: not doc.dirty, 30)
    assert "Wichtig" in page_text(path)
    with pikepdf.open(path) as pdf:  # zwei Linien in der Textfarbe (unter und durch den Text)
        data = b"".join(part.read_bytes() for part in ([pdf.pages[0].Contents] if isinstance(pdf.pages[0].Contents, pikepdf.Stream) else pdf.pages[0].Contents))
    assert data.count(b" l S Q") >= 2


def test_comment_properties_resize_and_reply(reader_app, tmp_path: Path) -> None:
    """Rechteck zeichnen, auswählen: Linienstärke und Deckkraft in der Leiste ändern, an der Ecke vergrößern;
    in der Seitenleiste »Kommentare« antworten – die Antwort steht eingerückt darunter."""
    h = reader_app
    doc = open_pdf(h, samples.standard_text(tmp_path / "kommentare.pdf"), whole_page=True)
    doc.setTool("rect")
    drag(h, page_point(h, 0, 300, 500), page_point(h, 0, 400, 560))
    settle(h)
    shape = next(item for item in doc.annotations if item["subtype"] == "/Square")
    assert shape["ours"] and shape["resizable"] and shape["width"] == pytest.approx(2.0)
    doc.setTool("select")
    pump(0.2)
    click(h, page_point(h, 0, shape["view"][0] + 1, (shape["view"][1] + shape["view"][3]) / 2))
    assert doc.selectedObject.get("key") == shape["key"]
    pump(0.3)
    assert h.item("readerAnnotationWidth").isVisible() and h.item("readerAnnotationOpacity").isVisible()
    choose(h, "readerAnnotationWidth", "5 pt")
    assert wait_until(lambda: any(item["key"] == shape["key"] and item["width"] == pytest.approx(5.0) for item in doc.annotations), 10)
    choose(h, "readerAnnotationOpacity", "50 %")
    assert wait_until(lambda: any(item["key"] == shape["key"] and item["opacity"] == pytest.approx(0.5) for item in doc.annotations), 10)
    # Größe: Ecke rechts unten ziehen (frei, ohne Seitenverhältnis)
    current = next(item for item in doc.annotations if item["key"] == shape["key"])["view"]
    handles = [item for item in h.items("readerAnnotationHandle") if item.isVisible()]
    assert len(handles) == 4
    scale = doc.scale
    corner = page_point(h, 0, current[2], current[3])
    drag(h, corner, QPoint(corner.x() + round(40 * scale), corner.y() + round(10 * scale)))
    settle(h)
    grown = next(item for item in doc.annotations if item["key"] == shape["key"])["view"]
    assert grown[2] - grown[0] == pytest.approx(current[2] - current[0] + 40, abs=2.0)
    assert grown[3] - grown[1] == pytest.approx(current[3] - current[1] + 10, abs=2.0)
    # Antworten in der Seitenleiste
    reader(h).showRightPanel("comments")
    pump(0.4)
    press(h, "readerCommentReply")
    replies = [item for item in h.items("readerCommentReplyText") if item.isVisible()]
    assert replies
    replies[0].setProperty("text", "Bitte so lassen")
    press(h, "readerCommentReplySend")
    settle(h)
    assert wait_until(lambda: any(item.get("replyTo") == shape["key"] and item["contents"] == "Bitte so lassen" for item in doc.annotations), 10)
    assert [entry["depth"] for entry in doc.annotationList.items()] == [0, 1]  # Antwort eingerückt darunter
    # Die Antwort hat kein eigenes Kästchen auf der Seite
    assert all(item.get("replyTo") == "" for item in doc.annotationPages.get("0", []))
