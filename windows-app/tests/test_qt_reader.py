"""Qt-Oberfläche: Werkzeug »PDF Reader & Editor« (seit 3.0.0).

Die App läuft mit QML im Fenster (offscreen). Bedient wird wie von Hand – Maus (Ziehen,
Klicken, Strg+Mausrad) und Tastatur – oder über die Controller (``Reader``, ``Reader.current``).
Alle PDFs sind künstlich (``editorsamples``). Nach jedem Test darf die QML-Engine keine Meldung
ausgegeben haben (Fixture ``ui_app``).
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pikepdf
import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QGuiApplication, QWheelEvent
from PySide6.QtTest import QTest

import editorsamples as samples
from conftest import pump, wait_until

NO_MOD = Qt.KeyboardModifier.NoModifier
LEFT = Qt.MouseButton.LeftButton


# --- Hilfen ----------------------------------------------------------------------------------------------------
def reader(h):
    return h.runtime.reader.controller


def settle(h, timeout: float = 60.0) -> None:
    """Warten, bis der Arbeitsthread fertig ist und die Oberfläche alles übernommen hat."""
    r = reader(h)
    assert wait_until(lambda: r.engine.idle() and r.opening == 0 and (r.current is None or not r.current.busy), timeout), "Arbeitsthread wurde nicht fertig"
    pump(0.15)


def open_pdf(h, path: Path, whole_page: bool = False):
    """PDF öffnen und warten, bis die erste Seite gezeichnet ist; ``whole_page``: »Ganze Seite«,
    damit jede Stelle der ersten Seite im Fenster liegt (Maus-Tests)."""
    r = reader(h)
    before = r.tabs.count
    r.open_paths([str(path)])
    assert wait_until(lambda: r.tabs.count == before + 1 and r.current is not None and r.current.path and Path(r.current.path) == Path(path), 30), f"{path.name} wurde nicht geöffnet"
    settle(h)
    if whole_page:
        r.current.fitPage()
        pump(0.3)
    assert wait_until(lambda: r.cache.bytes > 0, 20), "Seitenbild wurde nicht gerendert"
    pump(0.2)
    return r.current


def page_item(h, page: int):
    for item in h.items(f"readerPage_{page}"):
        if item.isVisible():
            return item
    return None


def window_point(item, x: float, y: float) -> QPoint:
    scene = item.mapToScene(QPointF(x, y))
    return QPoint(round(scene.x()), round(scene.y()))


def page_point(h, page: int, u: float, v: float) -> QPoint:
    """Anzeige-Punkt (u, v) einer Seite → Fensterpunkt."""
    item = page_item(h, page)
    assert item is not None, f"Seite {page + 1} ist nicht sichtbar"
    scale = reader(h).current.scale
    return window_point(item, u * scale, v * scale)


def drag(h, start: QPoint, end: QPoint, steps: int = 8, modifiers=NO_MOD) -> None:
    QTest.mousePress(h.window, LEFT, modifiers, start)
    for step in range(1, steps + 1):
        QTest.mouseMove(h.window, QPoint(start.x() + (end.x() - start.x()) * step // steps, start.y() + (end.y() - start.y()) * step // steps))
        pump(0.01)
    QTest.mouseRelease(h.window, LEFT, modifiers, end)
    pump(0.1)


def click(h, point: QPoint, modifiers=NO_MOD) -> None:
    QTest.mouseClick(h.window, LEFT, modifiers, point)
    pump(0.1)


def key(h, key_code, modifiers=NO_MOD) -> None:
    QTest.keyClick(h.window, key_code, modifiers)
    pump(0.1)


def ctrl_wheel(h, point: QPoint, steps: int) -> None:
    pos = QPointF(point)
    event = QWheelEvent(pos, QPointF(h.window.mapToGlobal(point)), QPoint(0, 0), QPoint(0, 120 * steps), Qt.MouseButton.NoButton, Qt.KeyboardModifier.ControlModifier, Qt.ScrollPhase.NoScrollPhase, False)
    QGuiApplication.sendEvent(h.window, event)
    pump(0.1)


def page_text(path: Path, page: int = 0) -> str:
    import pypdfium2

    document = pypdfium2.PdfDocument(str(path))
    try:
        return document[page].get_textpage().get_text_range()
    finally:
        document.close()


def prop(item, name: str):
    """Property eines QML-Elements als Python-Wert (JavaScript-Arrays kommen als QJSValue)."""
    value = item.property(name)
    return value.toVariant() if hasattr(value, "toVariant") else value


def type_text(h, text: str) -> None:
    for char in text:
        QTest.keyClick(h.window, char)
    pump(0.05)


def digest(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


@pytest.fixture
def reader_app(ui_app):
    ui_app.app.dialogs.shutdown()  # »Neu in Version« (nicht blockierend) schließen
    ui_app.navigate("reader", 0.3)
    assert ui_app.app.currentPage == "reader"
    return ui_app


# --- Öffnen, Tabs, Zuletzt geöffnet ---------------------------------------------------------------------------
def test_start_card_shortcut_and_empty_state(ui_app) -> None:
    from tools.registry import READER

    assert READER.title == "PDF Reader & Editor"
    assert READER.description == "PDFs öffnen, bearbeiten, organisieren und kommentieren."
    ui_app.app.openShortcut(5)
    pump(0.3)
    assert ui_app.app.currentPage == "reader"
    assert ui_app.item("readerStart").isVisible()
    assert ui_app.item("readerOpenButton") is not None
    assert not reader(ui_app).hasDocument


def test_open_dialog_tabs_dirty_marker_and_close_prompt(reader_app, tmp_path: Path, monkeypatch) -> None:
    from qtapp import dialogs, files

    h = reader_app
    a = samples.standard_text(tmp_path / "Rechnung A.pdf", pages=2)
    b = samples.standard_text(tmp_path / "Rechnung B.pdf")
    original = digest(a)
    files.RESPONSES.append([str(a), str(b)])
    reader(h).openDialog()
    assert wait_until(lambda: reader(h).tabs.count == 2, 30)
    settle(h)
    assert [item["name"] for item in reader(h).tabs.items()] == ["Rechnung A.pdf", "Rechnung B.pdf"]
    assert reader(h).current.name == "Rechnung B.pdf"
    # Strg+Tab wechselt den Tab
    key(h, Qt.Key.Key_Tab, Qt.KeyboardModifier.ControlModifier)
    assert reader(h).current.name == "Rechnung A.pdf"
    doc = reader(h).current
    doc.addNote(0, 300, 300, "Bitte prüfen")
    settle(h)
    assert doc.dirty and reader(h).tabs.items()[0]["dirty"] is True
    # Schließen → »Abbrechen«: bleibt offen
    monkeypatch.setattr(dialogs, "AUTO_ANSWER", "close")
    assert reader(h).closeTab(doc.ident) is False
    assert reader(h).tabs.count == 2
    # »Nicht speichern«: geschlossen, Datei unverändert
    monkeypatch.setattr(dialogs, "AUTO_ANSWER", "secondary")
    assert reader(h).closeTab(doc.ident) is True
    settle(h)
    assert reader(h).tabs.count == 1 and reader(h).current.name == "Rechnung B.pdf"
    assert digest(a) == original
    # Zuletzt geöffnet: nur Pfade, lässt sich leeren
    paths = [entry["path"] for entry in reader(h).recent]
    assert str(a) in paths and str(b) in paths
    reader(h).clearRecent()
    assert reader(h).recent == []
    assert "reader_zuletzt" in reader(h).config() and reader(h).config()["reader_zuletzt"] == []


def test_drop_on_home_opens_reader_and_same_file_only_once(ui_app, tmp_path: Path) -> None:
    from PySide6.QtCore import QUrl

    h = ui_app
    h.app.dialogs.shutdown()
    pdf = samples.standard_text(tmp_path / "Abgelegt.pdf")
    h.navigate("home")
    assert h.app.dragEnter([QUrl.fromLocalFile(str(pdf))]) is True
    h.app.drop([QUrl.fromLocalFile(str(pdf))])
    assert wait_until(lambda: reader(h).tabs.count == 1, 30)
    settle(h)
    assert h.app.currentPage == "reader"
    reader(h).open_paths([str(pdf)])  # schon offen: nur aktivieren
    settle(h)
    assert reader(h).tabs.count == 1


# --- Ansicht: Zoom, Modi, Navigation, große Dokumente -----------------------------------------------------------
def test_zoom_fit_and_ctrl_wheel_keeps_point_under_cursor(reader_app, tmp_path: Path) -> None:
    h = reader_app
    doc = open_pdf(h, samples.standard_text(tmp_path / "zoom.pdf", pages=3))
    view = h.item("readerView")
    assert doc.fit == "width"
    width_zoom = doc.zoom
    doc.fitPage()
    pump(0.2)
    assert doc.fit == "page" and doc.zoom < width_zoom
    doc.setZoom(150)
    pump(0.3)
    assert doc.fit == "" and abs(doc.zoom - 150) < 0.01
    doc.zoomIn()
    assert doc.zoom == 200
    doc.zoomOut()
    doc.zoomOut()
    assert doc.zoom == 125
    # Strg+Mausrad: die Stelle unter dem Mauszeiger bleibt stehen
    target = page_point(h, 0, 200, 300)
    ctrl_wheel(h, target, 2)
    assert doc.zoom > 125
    # Punkt unter dem Zeiger: gleicher Anzeige-Punkt der Seite (±1 pt)
    item = page_item(h, 0)
    at = item.mapFromScene(QPointF(target))
    assert abs(at.x() / doc.scale - 200) < 1.5 and abs(at.y() / doc.scale - 300) < 1.5, (at.x() / doc.scale, at.y() / doc.scale)
    assert view is not None
    # Grenzen 10–800 %, Originalgröße
    doc.setZoom(5000)
    assert doc.zoom == 800
    doc.actualSize()
    assert doc.zoom == 100


def test_view_modes_navigation_and_keys(reader_app, tmp_path: Path) -> None:
    h = reader_app
    doc = open_pdf(h, samples.standard_text(tmp_path / "modi.pdf", pages=6))
    doc.goTo(4)
    pump(0.3)
    assert doc.currentPage == 4 and page_item(h, 4) is not None
    for mode in ("single", "two", "continuousTwo", "continuous"):
        doc.setViewMode(mode)
        pump(0.3)
        assert doc.viewMode == mode
        assert page_item(h, doc.currentPage) is not None, mode
    doc.setViewMode("single")
    pump(0.2)
    doc.goTo(0)
    pump(0.2)
    h.item("readerView").forceActiveFocus()
    key(h, Qt.Key.Key_End)
    assert doc.currentPage == 5
    key(h, Qt.Key.Key_Home)
    assert doc.currentPage == 0
    doc.step(1)
    pump(0.2)
    assert doc.currentPage == 1 and page_item(h, 1) is not None and page_item(h, 0) is None
    doc.setViewMode("two")
    pump(0.2)
    assert page_item(h, 0) is not None and page_item(h, 1) is not None
    doc.step(1)
    pump(0.2)
    assert doc.currentPage == 2


def test_large_document_stays_virtualized(reader_app, tmp_path: Path) -> None:
    h = reader_app
    doc = open_pdf(h, samples.big(tmp_path / "gross.pdf", pages=600))
    assert doc.pageCount == 600
    view = h.item("readerView")
    slots = len(prop(view, "slotPages"))
    assert slots < 20, f"zu viele Seitenelemente: {slots}"
    doc.goTo(599)
    pump(0.5)
    assert doc.currentPage == 599 and page_item(h, 599) is not None
    view.setProperty("contentY", view.property("contentHeight") / 2)
    pump(0.4)
    assert 250 < doc.currentPage < 350
    assert len(prop(view, "slotPages")) < 20
    settle(h)
    assert reader(h).cache.bytes <= reader(h).cache.limit


def test_render_cache_keeps_no_images_of_closed_documents() -> None:
    """Ein Seitenbild, das beim Schließen noch in Arbeit war und erst danach fertig wird, bleibt nicht im Speicher."""
    from PySide6.QtGui import QImage
    from qtapp.reader.engine import RenderCache

    cache = RenderCache(limit=8 * 1024 * 1024)
    image = QImage(200, 300, QImage.Format.Format_RGB32)
    cache.put(("d1", 0, 200, 0, "page", ()), image)
    cache.put(("d2", 0, 200, 0, "page", ()), image)
    cache.drop("d1")
    cache.put(("d1", 1, 200, 0, "page", ()), image)  # verspätet fertig
    assert len(cache) == 1 and cache.bytes == image.sizeInBytes()
    assert cache.get(("d2", 0, 200, 0, "page", ())) is not None and cache.get(("d1", 1, 200, 0, "page", ())) is None


# --- Text: Auswahl, Kopieren, Suche --------------------------------------------------------------------------------
def test_text_selection_by_mouse_and_copy(reader_app, tmp_path: Path) -> None:
    h = reader_app
    doc = open_pdf(h, samples.standard_text(tmp_path / "auswahl.pdf"))
    doc.loadText(0)
    settle(h)
    drag(h, page_point(h, 0, 70, 77), page_point(h, 0, 300, 77))
    settle(h)
    assert doc.selectionPage == 0 and len(doc.selectionRects) == 1
    QGuiApplication.clipboard().setText("")
    key(h, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier)
    settle(h)
    assert "Rechnung Nr. 4711" in QGuiApplication.clipboard().text()
    # Doppelklick wählt ein Wort
    QTest.mouseDClick(h.window, LEFT, NO_MOD, page_point(h, 0, 100, 77))
    pump(0.2)
    assert doc.selectionPage == 0
    key(h, Qt.Key.Key_Escape)
    assert doc.selectionPage == -1


def context_menu(h, page: int = 0):
    """Kontextmenü der Seite mit seinen Einträgen (Text → Eintrag). Seite und Menü mit zurückgeben:
    PySide verwirft die Python-Objekte der Kinder, sobald das des Elternobjekts freigegeben ist."""
    from PySide6.QtCore import QObject

    item = page_item(h, page)
    menus = [obj for obj in item.findChildren(QObject) if obj.objectName() == "readerContextMenu"]
    assert len(menus) == 1
    entries = {obj.property("text"): obj for obj in menus[0].findChildren(QObject) if obj.property("text") and obj.property("enabled") is not None and hasattr(obj, "mapToScene")}
    return item, menus[0], entries


def right_click(h, point: QPoint) -> None:
    QTest.mouseClick(h.window, Qt.MouseButton.RightButton, NO_MOD, point)
    pump(0.3)


def test_text_selection_shows_no_extra_bar_and_actions_stay_in_the_context_menu(reader_app, tmp_path: Path) -> None:
    """Desktop: Eine Textauswahl blendet keine Aktionsleiste ein. Rechtsklick auf die Auswahl öffnet das
    Kontextmenü – Kopieren, Alles auswählen, Markieren, Unterstreichen, Durchstreichen, Notiz –, die
    Auswahl bleibt dabei bestehen; Strg+C kopiert wie bisher."""
    h = reader_app
    doc = open_pdf(h, samples.standard_text(tmp_path / "kontextmenue.pdf"))
    doc.loadText(0)
    settle(h)
    options = h.item("readerToolOptions")
    drag(h, page_point(h, 0, 70, 77), page_point(h, 0, 300, 77))
    settle(h)
    assert doc.tool == "select" and doc.selectionPage == 0
    assert not options.isVisible() and options.height() == 0  # keine Leiste für die Auswahl
    # Rechtsklick auf den ausgewählten Text: Kontextmenü, Auswahl bleibt
    right_click(h, page_point(h, 0, 150, 77))
    _page, menu, entries = context_menu(h)
    assert menu.property("opened") and doc.selectionPage == 0 and not options.isVisible()
    assert {"Kopieren", "Alles auswählen (Seite)", "Markieren", "Unterstreichen", "Durchstreichen", "Notiz hier hinzufügen"} <= set(entries)
    assert all(entries[name].property("enabled") for name in ("Kopieren", "Markieren", "Unterstreichen", "Durchstreichen"))
    QGuiApplication.clipboard().setText("")
    copy = entries["Kopieren"]
    click(h, window_point(copy, copy.width() / 2, copy.height() / 2))
    settle(h)
    assert "Rechnung Nr. 4711" in QGuiApplication.clipboard().text() and not menu.property("opened")
    # »Unterstreichen« aus dem Kontextmenü: Anmerkung über der Auswahl, Auswahl danach aufgehoben
    right_click(h, page_point(h, 0, 150, 77))
    _page, menu, entries = context_menu(h)
    underline = entries["Unterstreichen"]
    click(h, window_point(underline, underline.width() / 2, underline.height() / 2))
    settle(h)
    assert [item["subtype"] for item in doc.annotations] == ["/Underline"]
    assert doc.selectionPage == -1 and not options.isVisible()
    # Ohne Auswahl: Textaktionen im Menü ausgegraut, »Alles auswählen« und »Notiz« bleiben
    right_click(h, page_point(h, 0, 150, 300))
    _page, menu, entries = context_menu(h)
    assert not any(entries[name].property("enabled") for name in ("Kopieren", "Markieren", "Unterstreichen", "Durchstreichen"))
    assert entries["Alles auswählen (Seite)"].property("enabled") and entries["Notiz hier hinzufügen"].property("enabled")
    key(h, Qt.Key.Key_Escape)
    pump(0.2)
    # Strg+C kopiert weiterhin eine Auswahl – auch »Alles auswählen«, ohne dass eine Leiste erscheint
    doc.selectAll(0)
    settle(h)
    assert doc.selectionPage == 0 and not options.isVisible()
    QGuiApplication.clipboard().setText("")
    key(h, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier)
    settle(h)
    assert "Rechnung Nr. 4711" in QGuiApplication.clipboard().text()


def test_search_hits_navigation_and_options(reader_app, tmp_path: Path) -> None:
    h = reader_app
    doc = open_pdf(h, samples.standard_text(tmp_path / "suche.pdf", pages=4))
    key(h, Qt.Key.Key_F, Qt.KeyboardModifier.ControlModifier)
    assert reader(h).leftPanel == "search"
    field = h.item("readerSearchField")
    assert field is not None and field.hasActiveFocus()
    doc.search("seite", False, False)
    assert wait_until(lambda: not doc.searchRunning, 30)
    pump(0.2)
    assert doc.searchCount == 4 and doc.searchIndex == 0
    key(h, Qt.Key.Key_F3)
    assert doc.searchIndex == 1 and doc.currentPage == doc.currentHit["page"]
    key(h, Qt.Key.Key_F3, Qt.KeyboardModifier.ShiftModifier)
    assert doc.searchIndex == 0
    doc.search("seite", True, False)  # Groß-/Kleinschreibung: »Seite« ≠ »seite«
    assert wait_until(lambda: not doc.searchRunning, 30)
    assert doc.searchCount == 0 and "Keine Treffer" in doc.searchSummary
    doc.search("Seit", False, True)  # ganzes Wort
    assert wait_until(lambda: not doc.searchRunning, 30)
    assert doc.searchCount == 0


# --- Bearbeiten: Text ----------------------------------------------------------------------------------------------------
def test_edit_text_block_natively_with_the_editor_and_save(reader_app, tmp_path: Path) -> None:
    h = reader_app
    path = samples.standard_text(tmp_path / "Text ändern.pdf")
    doc = open_pdf(h, path, whole_page=True)
    doc.setTool("editText")
    settle(h)
    assert doc.blocksPage == 0 and len(doc.blocks) >= 3
    block = next(b for b in doc.blocks if "4711" in b["text"])
    click(h, page_point(h, 0, (block["view"][0] + block["view"][2]) / 2, (block["view"][1] + block["view"][3]) / 2))
    editor = h.item("readerTextEditor")
    assert editor.property("open") is True
    area = h.item("readerEditorInput")
    assert area.property("text") == block["text"]
    area.setProperty("text", "Rechnung Nr. 4712 vom 01.10.2026")
    key(h, Qt.Key.Key_Return, Qt.KeyboardModifier.ControlModifier)  # Strg+Eingabe übernimmt (speichert nicht)
    settle(h)
    assert editor.property("open") is False
    assert doc.dirty and doc.lastMode == "Direkt im PDF geändert (Originalschrift)"
    assert doc.undoText != ""
    before = digest(path)
    key(h, Qt.Key.Key_S, Qt.KeyboardModifier.ControlModifier)
    settle(h)
    assert not doc.dirty and digest(path) != before
    text = page_text(path)
    assert "4712" in text and "4711" not in text
    with pikepdf.open(path) as saved:
        assert len(saved.pages) == 1
    # Sicherung des vorherigen Stands liegt im (Test-)Ordner des Editors
    from tools.pdf_editor import recovery

    assert any(recovery.backups_dir().rglob("*.pdf"))


def test_add_text_note_ink_shapes_and_undo_redo(reader_app, tmp_path: Path) -> None:
    h = reader_app
    doc = open_pdf(h, samples.standard_text(tmp_path / "kommentare.pdf"), whole_page=True)
    # Text hinzufügen (Klick, schreiben, Übernehmen)
    doc.setTool("addText")
    pump(0.1)
    click(h, page_point(h, 0, 72, 400))
    h.item("readerEditorInput").setProperty("text", "Neuer Hinweis")
    click(h, window_point(h.item("readerEditorApply"), 10, 10))
    settle(h)
    assert doc.dirty and doc.undoText == "Text hinzufügen"
    # Notiz, Freihand, Rechteck, Pfeil
    doc.setTool("note")
    click(h, page_point(h, 0, 450, 450))
    h.item("readerEditorInput").setProperty("text", "Rückfrage")
    key(h, Qt.Key.Key_Return, Qt.KeyboardModifier.ControlModifier)
    settle(h)
    doc.setTool("ink")
    drag(h, page_point(h, 0, 100, 500), page_point(h, 0, 200, 560), steps=12)
    settle(h)
    doc.setTool("rect")
    drag(h, page_point(h, 0, 300, 500), page_point(h, 0, 400, 560))
    settle(h)
    doc.setTool("arrow")
    drag(h, page_point(h, 0, 300, 600), page_point(h, 0, 400, 650))
    settle(h)
    kinds = sorted(item["subtype"] for item in doc.annotations)
    assert kinds == ["/Ink", "/Line", "/Square", "/Text"], kinds
    # Markieren über den Text
    doc.setTool("highlight")
    doc.loadText(0)
    settle(h)
    drag(h, page_point(h, 0, 70, 77), page_point(h, 0, 250, 77))
    settle(h)
    assert any(item["subtype"] == "/Highlight" for item in doc.annotations)
    count = len(doc.annotations)
    key(h, Qt.Key.Key_Escape)  # Werkzeug → Auswählen
    assert doc.tool == "select"
    key(h, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
    settle(h)
    assert len(doc.annotations) == count - 1
    key(h, Qt.Key.Key_Y, Qt.KeyboardModifier.ControlModifier)
    settle(h)
    assert len(doc.annotations) == count
    # Kommentar auswählen, verschieben, löschen (Entf)
    note = next(item for item in doc.annotations if item["subtype"] == "/Text")
    center = page_point(h, 0, (note["view"][0] + note["view"][2]) / 2, (note["view"][1] + note["view"][3]) / 2)
    drag(h, center, QPoint(center.x() + 30, center.y() + 20))
    settle(h)
    moved = next(item for item in doc.annotations if item["key"] == note["key"])
    assert moved["view"][0] > note["view"][0] + 10
    assert doc.selectedObject.get("key") == note["key"]
    key(h, Qt.Key.Key_Delete)
    settle(h)
    assert all(item["key"] != note["key"] for item in doc.annotations)


# --- Bearbeiten: Bilder ------------------------------------------------------------------------------------------------
def test_image_insert_move_resize_and_delete(reader_app, tmp_path: Path) -> None:
    from qtapp import files

    h = reader_app
    doc = open_pdf(h, samples.standard_text(tmp_path / "bilder.pdf"), whole_page=True)
    png = samples.two_tone_png(tmp_path / "logo.png", alpha=True)
    doc.setTool("image")
    settle(h)
    assert doc.images == []
    files.RESPONSES.append(str(png))
    click(h, window_point(h.item("readerInsertImage"), 10, 10))
    settle(h)
    assert len(doc.images) == 1
    image = doc.images[0]
    assert image["ours"] and image["editable"]
    # verschieben
    center = page_point(h, 0, (image["view"][0] + image["view"][2]) / 2, (image["view"][1] + image["view"][3]) / 2)
    drag(h, center, QPoint(center.x() + 40, center.y() + 30))
    settle(h)
    moved = doc.images[0]["view"]
    assert moved[0] > image["view"][0] + 20
    # Größe an der Ecke rechts unten (Seitenverhältnis bleibt)
    corner = page_point(h, 0, moved[2], moved[3])
    drag(h, corner, QPoint(corner.x() + 40, corner.y() + 40))
    settle(h)
    resized = doc.images[0]["view"]
    assert resized[2] - resized[0] > moved[2] - moved[0] + 10
    ratio_before = (moved[2] - moved[0]) / (moved[3] - moved[1])
    ratio_after = (resized[2] - resized[0]) / (resized[3] - resized[1])
    assert abs(ratio_before - ratio_after) < 0.05
    # drehen, löschen
    selected = doc.selectedObject
    doc.rotateImage(selected["page"], selected["index"], True)
    settle(h)
    key(h, Qt.Key.Key_Delete)
    settle(h)
    assert doc.images == []


# --- Formulare -------------------------------------------------------------------------------------------------------------
def test_fill_form_fields(reader_app, tmp_path: Path) -> None:
    h = reader_app
    doc = open_pdf(h, samples.form(tmp_path / "formular.pdf"), whole_page=True)
    doc.setTool("form")
    settle(h)
    widgets = doc.fieldPages["0"]
    name = next(w for w in widgets if w["name"] == "name")
    click(h, page_point(h, 0, (name["view"][0] + name["view"][2]) / 2, (name["view"][1] + name["view"][3]) / 2))
    type_text(h, "Erika Muster")
    key(h, Qt.Key.Key_Return)
    settle(h)
    checkbox = next(w for w in doc.fieldPages["0"] if w["name"] == "ok")
    click(h, page_point(h, 0, (checkbox["view"][0] + checkbox["view"][2]) / 2, (checkbox["view"][1] + checkbox["view"][3]) / 2))
    settle(h)
    radio = next(w for w in doc.fieldPages["0"] if w["name"] == "versand" and w["onValue"] != w["value"])
    click(h, page_point(h, 0, (radio["view"][0] + radio["view"][2]) / 2, (radio["view"][1] + radio["view"][3]) / 2))
    settle(h)
    values = {field["name"]: field["value"] for field in doc.fields}
    assert values["name"] == "Erika Muster"
    assert values["ok"] is True
    assert values["versand"] == radio["onValue"]


# --- Seiten organisieren ----------------------------------------------------------------------------------------------------
def test_organize_pages_select_move_rotate_delete(reader_app, tmp_path: Path) -> None:
    h = reader_app
    doc = open_pdf(h, samples.standard_text(tmp_path / "seiten.pdf", pages=4))
    reader(h).setOrganize(True)
    pump(0.4)
    grid = h.item("readerOrganizeGrid")
    assert grid is not None and grid.property("count") == 4
    organize = h.item("readerOrganizeView")

    def cell_point(index: int) -> QPoint:
        width, height = grid.property("cellWidth"), grid.property("cellHeight")
        columns = max(1, int((grid.width() - 16) // width))
        x = (index % columns) * width + width / 2 - grid.property("contentX")
        y = (index // columns) * height + height / 2 - grid.property("contentY")
        return window_point(grid, x, y)

    click(h, cell_point(3))
    assert prop(organize, "selectedPages") == [3]
    # Seite 4 vor Seite 1 ziehen
    drag(h, cell_point(3), QPoint(cell_point(0).x() - 60, cell_point(0).y()), steps=10)
    settle(h)
    assert doc.dirty and doc.undoText == "Seite verschieben"
    # Strg+A, drehen, dann eine Seite löschen
    grid.forceActiveFocus()
    key(h, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
    assert len(prop(organize, "selectedPages")) == 4
    click(h, window_point(h.item("readerOrganizeRotate"), 10, 10))
    settle(h)
    assert all(size[0] > size[1] for size in doc.pageSizes)
    click(h, cell_point(1))
    click(h, window_point(h.item("readerOrganizeDelete"), 10, 10))
    settle(h)
    assert doc.pageCount == 3
    key(h, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
    settle(h)
    assert doc.pageCount == 4
    target = tmp_path / "neu geordnet.pdf"
    doc.save(str(target))
    settle(h)
    with pikepdf.open(target) as saved:
        assert len(saved.pages) == 4
        assert int(saved.pages[0].get("/Rotate", 0)) == 90
    assert "Seite 4 von 4" in page_text(target, 0)
    reader(h).setOrganize(False)


# --- Speichern, Sicherheit, Dateien ------------------------------------------------------------------------------------------
def test_password_protected_pdf_asks_for_password(reader_app, tmp_path: Path, monkeypatch) -> None:
    h = reader_app
    path = samples.encrypted(tmp_path / "geschuetzt.pdf", user="geheim")
    answers = iter(["falsch", "geheim"])
    asked: list[dict] = []

    def ask(kind, title, message="", **kwargs):
        asked.append({"kind": kind, "message": message})
        return "primary", {"value": next(answers)}

    monkeypatch.setattr(h.app.dialogs, "ask", ask)
    reader(h).open_paths([str(path)])
    assert wait_until(lambda: reader(h).tabs.count == 1, 30)
    settle(h)
    assert [entry["kind"] for entry in asked] == ["password", "password"]
    assert "falsch" in asked[1]["message"] and "geheim" not in asked[1]["message"]  # Hinweis »falsch«, nie das Passwort
    assert reader(h).current.pageCount == 1
    assert "geheim" not in str(reader(h).config())


def test_damaged_pdf_offers_repair_without_repairing(reader_app, tmp_path: Path) -> None:
    h = reader_app
    path = samples.damaged(tmp_path / "kaputt.pdf")
    before = digest(path)
    reader(h).open_paths([str(path)])
    assert wait_until(lambda: h.app.currentPage == "repair", 30), h.app.currentPage
    settle(h)
    asked = [entry for entry in h.app.dialogs.history if entry["title"] == "Dieses Dokument scheint beschädigt zu sein."]
    assert asked, "Reparatur wurde nicht angeboten"
    assert reader(h).tabs.count == 0
    assert digest(path) == before
    assert wait_until(lambda: any(item.path == path for item in h.repair.batch.items), 30)


def test_signed_pdf_warns_and_asks_before_first_edit(reader_app, tmp_path: Path, monkeypatch) -> None:
    from qtapp import dialogs

    h = reader_app
    doc = open_pdf(h, samples.signed(tmp_path / "signiert.pdf"))
    assert doc.signed and "digital signiert" in doc.notice and doc.noticeKind == "warning"
    assert h.item("readerDocumentNotice").property("shown") is True
    monkeypatch.setattr(dialogs, "AUTO_ANSWER", "close")
    doc.addNote(0, 300, 300, "Test")
    settle(h)
    assert not doc.dirty and all(item["subtype"] != "/Text" for item in doc.annotations)
    assert any(entry["title"] == "Signiertes Dokument bearbeiten?" for entry in h.app.dialogs.history)
    monkeypatch.setattr(dialogs, "AUTO_ANSWER", "primary")
    doc.addNote(0, 300, 300, "Test")
    settle(h)
    assert doc.dirty


def test_external_change_is_detected_before_overwrite(reader_app, tmp_path: Path, monkeypatch) -> None:
    from qtapp import dialogs

    h = reader_app
    path = samples.standard_text(tmp_path / "extern.pdf")
    doc = open_pdf(h, path)
    doc.addNote(0, 100, 100, "x")
    settle(h)
    samples.standard_text(path, lines=("Von außen geändert",))  # anderes Programm schreibt die Datei
    changed = digest(path)
    monkeypatch.setattr(dialogs, "AUTO_ANSWER", "close")
    doc.saveDocument()
    settle(h)
    assert digest(path) == changed and doc.dirty
    assert any(entry["title"] == "Datei wurde von außen geändert" for entry in h.app.dialogs.history)


def test_properties_dialog_changes_metadata(reader_app, tmp_path: Path, monkeypatch) -> None:
    h = reader_app
    path = samples.standard_text(tmp_path / "eigenschaften.pdf")
    doc = open_pdf(h, path)
    seen: dict = {}

    def ask(kind, title, message="", **kwargs):
        seen["kind"], seen["data"] = kind, kwargs.get("data")
        return "primary", {"title": "Neuer Titel", "author": "Erika Muster", "subject": "", "keywords": "Test"}

    monkeypatch.setattr(h.app.dialogs, "ask", ask)
    doc.showProperties()
    settle(h)
    assert seen["kind"] == "reader_properties"
    facts = {fact["label"]: fact["value"] for fact in seen["data"]["props"]["facts"]}
    assert facts["Seiten"] == "1" and facts["Verschlüsselung"] == "keine" and "A4" in facts["Seitengröße"]
    assert doc.dirty
    doc.saveDocument()
    settle(h)
    with pikepdf.open(path) as saved:
        assert str(saved.docinfo["/Title"]) == "Neuer Titel" and str(saved.docinfo["/Author"]) == "Erika Muster"


def test_print_renders_every_page(reader_app, tmp_path: Path) -> None:
    from PySide6.QtCore import QRectF
    from PySide6.QtPrintSupport import QPrinter

    from qtapp.reader import printing

    h = reader_app
    doc = open_pdf(h, samples.standard_text(tmp_path / "druck.pdf", pages=3))
    printer = QPrinter(QPrinter.PrinterMode.HighResolution)
    printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
    target = tmp_path / "gedruckt.pdf"
    printer.setOutputFileName(str(target))
    printing._paint(printer, doc, [0, 1, 2], QRectF)
    settle(h)
    with pikepdf.open(target) as printed:
        assert len(printed.pages) == 3


def test_open_with_forwards_paths_to_the_running_app(reader_app, tmp_path: Path) -> None:
    """Zweiter Start mit einer PDF (eigener Prozess, wie »Öffnen mit« im Explorer): die laufende App
    öffnet sie als Tab, nicht vorhandene Pfade werden verworfen; der zweite Prozess endet mit 0."""
    import subprocess
    import sys

    from qtapp import instance

    h = reader_app
    pdf = samples.standard_text(tmp_path / "Explorer.pdf")
    received: list = []
    name = instance.PREFIX + "test-" + hashlib.sha1(str(tmp_path).encode()).hexdigest()[:8]
    server = instance.InstanceServer(lambda paths: (received.extend(paths), reader(h).open_external(paths)), name=name)
    assert server.listening
    script = (
        "import sys; sys.path.insert(0, sys.argv[1]);"
        "from PySide6.QtCore import QCoreApplication; app = QCoreApplication([]);"
        "from qtapp import instance;"
        "sys.exit(0 if instance.forward(sys.argv[3:], name=sys.argv[2]) else 3)"
    )
    second = subprocess.Popen([sys.executable, "-c", script, str(Path(__file__).resolve().parents[1] / "app"), name, str(pdf), str(tmp_path / "fehlt.pdf")])
    assert wait_until(lambda: second.poll() is not None, 30)
    assert second.returncode == 0
    assert wait_until(lambda: reader(h).tabs.count == 1, 30)
    settle(h)
    assert received == [str(pdf)]  # nicht vorhandene Datei verworfen
    server.close()
    # ohne laufende App: nicht angenommen (der Start öffnet die PDF dann selbst)
    assert instance.forward([str(pdf)], name=name + "-keiner") is False
    assert instance.pdf_arguments(["-OO", str(pdf), "notiz.txt"]) == [str(pdf.resolve())]


def test_crash_recovery_offers_unsaved_session(reader_app, tmp_path: Path, monkeypatch) -> None:
    import subprocess
    import sys

    from tools.pdf_editor import recovery

    h = reader_app
    path = samples.standard_text(tmp_path / "absturz.pdf")
    # Ein anderer Prozess sichert einen ungespeicherten Stand und endet ohne Aufräumen (wie ein Absturz)
    script = (
        "import sys; sys.path.insert(0, sys.argv[1]);"
        "from tools.pdf_editor import recovery;"
        "s = recovery.RecoverySession('absturz.pdf', __import__('pathlib').Path(sys.argv[2]), False);"
        "s.write(open(sys.argv[2], 'rb').read()); import os; os._exit(0)"
    )
    subprocess.run([sys.executable, "-c", script, str(Path(__file__).resolve().parents[1] / "app"), str(path)], check=True, env={**__import__("os").environ})
    assert len(recovery.orphaned_sessions()) == 1
    reader(h).offer_recovery()
    assert wait_until(lambda: reader(h).tabs.count == 1, 30)
    settle(h)
    asked = [entry for entry in h.app.dialogs.history if entry["title"] == "Eine nicht gespeicherte Bearbeitung wurde gefunden."]
    assert asked and asked[-1]["primary"] == "Wiederherstellen" and asked[-1]["secondary"] == "Verwerfen"
    assert reader(h).current.dirty  # wiederhergestellt = ungespeichert, Original unverändert
    # Die wiederhergestellte Sitzung gehört jetzt diesem Prozess – ein weiterer Start bietet sie nicht erneut an
    assert wait_until(lambda: recovery.orphaned_sessions() == [], 15)
    assert len(list((recovery.root_dir() / recovery.SESSIONS).iterdir())) == 1


def test_no_document_text_in_settings_or_logs(reader_app, tmp_path: Path, config_file: Path) -> None:
    import os

    h = reader_app
    doc = open_pdf(h, samples.standard_text(tmp_path / "privat.pdf"))
    doc.search("Gesamtbetrag", False, False)
    assert wait_until(lambda: not doc.searchRunning, 30)
    doc.loadText(0)
    settle(h)
    doc.selectAll(0)
    doc.copySelection()
    settle(h)
    h.app.persist()
    pump(0.3)
    assert "privat.pdf" in config_file.read_text(encoding="utf-8")  # nur der Pfad (»Zuletzt geöffnet«)
    files = [config_file, *(file for file in Path(os.environ["UE_DATA_DIR"]).rglob("*") if file.is_file())]
    for file in files:
        if file.stat().st_size < 5_000_000:
            assert b"Gesamtbetrag" not in file.read_bytes(), f"Dokumenttext in {file}"


# --- Speichern (Release-Blocker in 3.0.0-beta.1) ----------------------------------------------------------------
# Wie im installierten Programm ohne lxml: pikepdf hätte beim Schreiben die XMP-Metadaten mit lxml
# angepasst – jedes PDF mit XMP ließ sich nicht speichern (»Das Dokument konnte nicht geschrieben werden.«).
@pytest.fixture
def no_lxml(monkeypatch):
    import sys

    monkeypatch.setitem(sys.modules, "lxml", None)
    monkeypatch.setitem(sys.modules, "lxml.etree", None)


def edit_invoice(h, doc, new: str = "4712", old: str = "4711") -> None:
    """Rechnungsnummer auf Seite 1 direkt im PDF ändern (Werkzeug »Text bearbeiten«)."""
    doc.setTool("editText")
    settle(h)
    block = next(b for b in doc.blocks if old in b["text"])
    doc.editBlock(0, block["id"], block["text"].replace(old, new), {})
    settle(h)
    doc.setTool("select")
    settle(h)
    assert doc.dirty


def save_error(h):
    notice = h.app.notices.get("reader")
    return notice if notice.shown and notice.severity == "error" else None


def assert_saved(h, doc, path: Path, before: str, pages: int = 1) -> None:
    """Gespeichert und gültig: nicht mehr geändert, Datei neu, öffnet in pikepdf und PDFium, rendert."""
    import pypdfium2

    assert not doc.dirty and digest(path) != before and save_error(h) is None
    with pikepdf.open(path) as saved:
        assert len(saved.pages) == pages
    view = pypdfium2.PdfDocument(str(path))
    try:
        assert len(view) == pages and view[0].render(scale=0.3).to_pil().getextrema() != ((255, 255), (255, 255), (255, 255))
    finally:
        view.close()
    assert not [p.name for p in path.parent.iterdir() if p.name.endswith(".tmp")]


def test_a_ctrl_s_saves_keeps_the_view_and_undo(reader_app, tmp_path: Path, no_lxml) -> None:
    h = reader_app
    path = samples.with_xmp(tmp_path / "Rechnung.pdf", pages=3)
    doc = open_pdf(h, path)
    edit_invoice(h, doc)
    doc.setViewMode("single")
    doc.setZoom(150)
    doc.goTo(1)
    reader(h).leftPanel = "outline"
    settle(h)
    view = (doc.currentPage, doc.zoom, doc.viewMode, reader(h).leftPanel, reader(h).currentKey, reader(h).tabs.count)
    before = digest(path)
    key(h, Qt.Key.Key_S, Qt.KeyboardModifier.ControlModifier)
    settle(h)
    assert_saved(h, doc, path, before, pages=3)
    assert "4712" in page_text(path) and "4711" not in page_text(path)
    # Kein Zurück zur Startseite, Ansicht und Seitenleiste wie vorher; »Gespeichert« ohne Dialog
    assert (doc.currentPage, doc.zoom, doc.viewMode, reader(h).leftPanel, reader(h).currentKey, reader(h).tabs.count) == view
    assert h.app.currentPage == "reader" and doc.saveState == "saved"
    assert h.item("readerSaveState").property("text") == "Gespeichert"
    assert reader(h).tabs.items()[0]["dirty"] is False
    assert wait_until(lambda: doc.saveState == "", 5)
    # Rückgängig bleibt möglich – danach wieder ungespeichert
    assert doc.undoText
    doc.undo()
    settle(h)
    assert doc.dirty


def test_b_toolbar_save_button(reader_app, tmp_path: Path, no_lxml) -> None:
    h = reader_app
    path = samples.with_xmp(tmp_path / "Toolbar.pdf")
    doc = open_pdf(h, path)
    edit_invoice(h, doc)
    button = h.item("readerSave")
    assert button.property("enabled") is True
    before = digest(path)
    click(h, window_point(button, button.width() / 2, button.height() / 2))
    settle(h)
    assert_saved(h, doc, path, before)
    assert button.property("enabled") is False  # nichts mehr zu speichern


def test_c_saved_change_is_there_after_closing_and_reopening(reader_app, tmp_path: Path, no_lxml) -> None:
    h = reader_app
    path = samples.with_xmp(tmp_path / "Wieder öffnen.pdf", pages=2)
    doc = open_pdf(h, path)
    edit_invoice(h, doc)
    doc.saveDocument()
    settle(h)
    assert not doc.dirty
    assert reader(h).closeTab(doc.ident) is True
    settle(h)
    again = open_pdf(h, path)
    assert again.pageCount == 2 and not again.dirty
    again.setTool("editText")
    settle(h)
    assert any("4712" in block["text"] for block in again.blocks) and not any("4711" in block["text"] for block in again.blocks)


def test_d_failed_save_keeps_original_unsaved_state_and_undo(reader_app, tmp_path: Path, monkeypatch, no_lxml) -> None:
    from tools.pdf_editor import save as save_engine

    h = reader_app
    path = samples.with_xmp(tmp_path / "Fehler.pdf")
    doc = open_pdf(h, path)
    edit_invoice(h, doc)
    before, undo = digest(path), doc.undoText

    def broken(*_args, **_kwargs):
        raise OSError(5, "Ein-/Ausgabefehler")

    monkeypatch.setattr(save_engine, "_replace", broken)
    key(h, Qt.Key.Key_S, Qt.KeyboardModifier.ControlModifier)
    settle(h)
    error = save_error(h)
    assert error is not None and error.title == "Speichern nicht möglich" and "unverändert" in error.message
    assert error.actions == ["Speichern unter …"]
    assert digest(path) == before and doc.dirty and doc.undoText == undo and doc.saveState == ""
    assert reader(h).tabs.items()[0]["dirty"] is True
    monkeypatch.undo()
    key(h, Qt.Key.Key_S, Qt.KeyboardModifier.ControlModifier)  # Ursache behoben: jetzt klappt es
    settle(h)
    assert not doc.dirty and "4712" in page_text(path)


def test_e_read_only_file_offers_save_as(reader_app, tmp_path: Path, no_lxml) -> None:
    import os
    import stat

    from qtapp import files

    h = reader_app
    path = samples.with_xmp(tmp_path / "Nur lesen.pdf")
    os.chmod(path, stat.S_IREAD)
    try:
        doc = open_pdf(h, path)
        edit_invoice(h, doc)
        before = digest(path)
        key(h, Qt.Key.Key_S, Qt.KeyboardModifier.ControlModifier)
        settle(h)
        error = save_error(h)
        assert error is not None and error.message == "Die Datei ist schreibgeschützt. Verwenden Sie »Speichern unter«, um eine bearbeitete Kopie zu erstellen."
        assert doc.dirty and digest(path) == before
        copy = tmp_path / "Bearbeitete Kopie.pdf"
        files.RESPONSES.append(str(copy))
        error.trigger(0)  # »Speichern unter …« direkt aus der Meldung
        settle(h)
        assert not doc.dirty and Path(doc.path) == copy and doc.name == copy.name and "4712" in page_text(copy)
        assert digest(path) == before
    finally:
        os.chmod(path, stat.S_IREAD | stat.S_IWRITE)


def test_f_folder_without_write_permission(reader_app, tmp_path: Path, monkeypatch, no_lxml) -> None:
    import errno

    from tools.pdf_editor import save as save_engine

    h = reader_app
    path = samples.with_xmp(tmp_path / "Ordner ohne Rechte.pdf")
    doc = open_pdf(h, path)
    edit_invoice(h, doc)
    before = digest(path)

    def denied(file, mode="r", *args, **kwargs):
        if str(file).endswith(".tmp") and "x" in mode:
            raise PermissionError(errno.EACCES, "Zugriff verweigert")
        return open(file, mode, *args, **kwargs)

    monkeypatch.setattr(save_engine, "open", denied, raising=False)
    key(h, Qt.Key.Key_S, Qt.KeyboardModifier.ControlModifier)
    settle(h)
    error = save_error(h)
    assert error is not None and error.message.startswith("PDF Tool hat keine Schreibberechtigung für diesen Speicherort.")
    assert error.actions == ["Speichern unter …"] and doc.dirty and digest(path) == before


def test_g_file_locked_by_another_program(reader_app, tmp_path: Path, monkeypatch, no_lxml) -> None:
    import errno
    import sys

    from tools.pdf_editor import save as save_engine

    h = reader_app
    path = samples.with_xmp(tmp_path / "Gesperrt.pdf")
    doc = open_pdf(h, path)
    edit_invoice(h, doc)
    before = digest(path)
    other = None
    if sys.platform == "win32":
        other = open(path, "rb")  # echtes anderes Handle ohne Freigabe zum Löschen
    else:
        def locked(*_args, **_kwargs):
            exc = PermissionError(errno.EACCES, "Der Prozess kann nicht auf die Datei zugreifen")
            exc.winerror = 32  # ERROR_SHARING_VIOLATION wie unter Windows
            raise exc

        monkeypatch.setattr(save_engine, "_replace", locked)
    try:
        key(h, Qt.Key.Key_S, Qt.KeyboardModifier.ControlModifier)
        settle(h)
        error = save_error(h)
        assert error is not None and error.message.startswith("Die Datei wird möglicherweise von einem anderen Programm verwendet.")
        assert "Schreibberechtigung" not in error.message and doc.dirty
    finally:
        if other is not None:
            other.close()
    assert digest(path) == before


def test_h_i_save_while_pages_and_thumbnails_render(reader_app, tmp_path: Path, no_lxml) -> None:
    h = reader_app
    path = samples.with_xmp(tmp_path / "Viele Seiten.pdf", pages=40)
    doc = open_pdf(h, path)
    edit_invoice(h, doc)
    reader(h).leftPanel = "thumbs"  # Miniaturen werden im Hintergrund gezeichnet
    doc.setZoom(400)  # neue Seitenbilder in hoher Auflösung
    before = digest(path)
    key(h, Qt.Key.Key_S, Qt.KeyboardModifier.ControlModifier)  # sofort – während gezeichnet wird
    settle(h)
    assert_saved(h, doc, path, before, pages=40)


def test_j_save_while_search_runs(reader_app, tmp_path: Path, monkeypatch, no_lxml) -> None:
    from qtapp.reader.session import Session

    h = reader_app
    path = samples.big(tmp_path / "Suche.pdf", pages=400)
    doc = open_pdf(h, path)
    doc.addNote(0, 100, 100, "Prüfen")
    settle(h)
    assert doc.dirty
    searched: list[int] = []
    at_save: list[int] = []
    search_page, save_session = Session.search_page, Session.save
    monkeypatch.setattr(Session, "search_page", lambda self, page, *args: searched.append(page) or search_page(self, page, *args))
    monkeypatch.setattr(Session, "save", lambda self, *args, **kwargs: at_save.append(len(searched)) or save_session(self, *args, **kwargs))
    before = digest(path)
    doc.search("SuchwortTreffer", False, False)
    assert wait_until(lambda: len(searched) >= 3, 30) and doc.searchRunning
    doc.saveDocument()
    assert wait_until(lambda: not doc.dirty and not doc.saving, 60)
    assert wait_until(lambda: not doc.searchRunning, 120)
    settle(h)
    # Gespeichert, als die Suche erst einen Teil der Seiten hatte: sie gibt Vorrang und läuft danach weiter
    assert at_save and at_save[0] < 400 and len(searched) == 400
    assert doc.searchCount == 8  # Seiten 8, 58, 108 … 358
    assert save_error(h) is None and digest(path) != before


def test_k_repeated_ctrl_s_saves_once_without_races(reader_app, tmp_path: Path, monkeypatch, no_lxml) -> None:
    from qtapp import dialogs
    from tools.pdf_editor import save as save_engine

    h = reader_app
    path = samples.with_xmp(tmp_path / "Schnell.pdf", pages=5)
    doc = open_pdf(h, path)
    edit_invoice(h, doc)
    calls = []
    real = save_engine.save

    def counted(*args, **kwargs):
        calls.append(1)
        return real(*args, **kwargs)

    monkeypatch.setattr(save_engine, "save", counted)
    before = digest(path)
    for _ in range(5):
        QTest.keyClick(h.window, Qt.Key.Key_S, Qt.KeyboardModifier.ControlModifier)
    settle(h)
    assert len(calls) == 1  # ein Schreibvorgang; die übrigen Anfragen fanden nichts mehr zu speichern
    assert_saved(h, doc, path, before, pages=5)
    # »Speichern« beim Schließen, während noch gespeichert wird: wartet und schließt danach
    edit_invoice(h, doc, new="4713", old="4712")
    monkeypatch.setattr(dialogs, "AUTO_ANSWER", "primary")
    doc.saveDocument()
    assert doc.saving
    reader(h).closeTab(doc.ident)
    settle(h)
    assert reader(h).tabs.count == 0 and len(calls) == 2 and "4713" in page_text(path)


def test_l_saving_one_tab_leaves_the_other_alone(reader_app, tmp_path: Path, no_lxml) -> None:
    h = reader_app
    a_path = samples.with_xmp(tmp_path / "A.pdf")
    b_path = samples.with_xmp(tmp_path / "B.pdf", pages=2)
    a = open_pdf(h, a_path)
    edit_invoice(h, a)
    b = open_pdf(h, b_path)
    edit_invoice(h, b, new="4799")
    reader(h).activate(a.ident)
    settle(h)
    a_before, b_before = digest(a_path), digest(b_path)
    b_view = (b.currentPage, b.zoom, b.viewMode, b.undoText)
    key(h, Qt.Key.Key_S, Qt.KeyboardModifier.ControlModifier)
    settle(h)
    assert_saved(h, a, a_path, a_before)
    assert b.dirty and digest(b_path) == b_before and (b.currentPage, b.zoom, b.viewMode, b.undoText) == b_view
    assert {item["key"]: item["dirty"] for item in reader(h).tabs.items()} == {a.ident: False, b.ident: True}
    reader(h).activate(b.ident)
    settle(h)
    key(h, Qt.Key.Key_S, Qt.KeyboardModifier.ControlModifier)
    settle(h)
    assert_saved(h, b, b_path, b_before, pages=2)
    assert "4799" in page_text(b_path) and "4712" in page_text(a_path)


def test_m_save_as_writes_a_new_file_and_switches_to_it(reader_app, tmp_path: Path, no_lxml) -> None:
    from qtapp import files

    h = reader_app
    path = samples.with_xmp(tmp_path / "Original.pdf", pages=2)
    doc = open_pdf(h, path)
    edit_invoice(h, doc)
    before = digest(path)
    copy = tmp_path / "Kopie" / "Neu gespeichert.pdf"
    copy.parent.mkdir()
    files.RESPONSES.append(str(copy))
    doc.saveDocumentAs()
    settle(h)
    assert not doc.dirty and Path(doc.path) == copy and doc.name == "Neu gespeichert.pdf"
    assert reader(h).tabs.items()[0]["name"] == "Neu gespeichert.pdf"
    assert digest(path) == before and "4711" in page_text(path)  # Original unverändert
    assert "4712" in page_text(copy)
    with pikepdf.open(copy) as saved:
        assert len(saved.pages) == 2


# --- Einstellungen »PDF Reader«: Ansicht neu geöffneter Dokumente -----------------------------------------------
def view_of(h, doc) -> tuple:
    return (doc.fit, doc.zoom, doc.viewMode, reader(h).leftPanel)


def test_open_settings_default_keeps_todays_behaviour(reader_app, tmp_path: Path, config_file: Path) -> None:
    """Standard »Zuletzt verwendet« (Zoom und Seitenleiste): ein neues Dokument öffnet genau wie ohne
    die Einstellungen; die neuen Schlüssel stehen mit ihrem Standard in den Einstellungen."""
    import json

    h = reader_app
    s, r = h.settings, reader(h)
    assert (s.readerZoom, s.readerPanel) == ("last", "last")
    zuletzt = {"fit": "", "zoom": 150.0, "mode": "single"}
    assert s.reader_start_view(zuletzt) == zuletzt and s.reader_start_panel("outline") == "outline" and s.reader_start_panel("") == ""
    first = open_pdf(h, samples.standard_text(tmp_path / "erstes.pdf", pages=2))

    def open_after_last_view(name: str):
        first.setViewMode("single")  # zuletzt verwendet: eine Seite, ganze Seite, Lesezeichen
        first.fitPage()
        r.showLeftPanel("outline")
        pump(0.2)
        return view_of(h, open_pdf(h, samples.standard_text(tmp_path / name, pages=2)))

    with_settings = open_after_last_view("mit.pdf")
    h.app.settings = None  # wie vor den Einstellungen: nur die zuletzt verwendete Ansicht
    try:
        without_settings = open_after_last_view("ohne.pdf")
    finally:
        h.app.settings = s
    assert with_settings == without_settings and with_settings[3] == "outline"
    h.app.persist()
    data = json.loads(config_file.read_text(encoding="utf-8"))
    assert data["reader_zoom_beim_oeffnen"] == "last" and data["reader_leiste_beim_oeffnen"] == "last"


@pytest.mark.parametrize("choice,fit", [("width", "width"), ("page", "page"), ("100", "")])
def test_open_settings_zoom_applies_to_new_documents(reader_app, tmp_path: Path, choice: str, fit: str) -> None:
    h = reader_app
    first = open_pdf(h, samples.standard_text(tmp_path / "erstes.pdf", pages=2))
    first.setZoom(150)  # zuletzt verwendet: freier Zoom
    pump(0.2)
    h.settings.setReaderZoom(choice)
    assert h.app.statusText.startswith("Standardzoom beim Öffnen: ")
    doc = open_pdf(h, samples.standard_text(tmp_path / "neu.pdf", pages=2))
    assert doc.fit == fit and first.fit == "" and abs(first.zoom - 150) < 0.01  # das offene Dokument bleibt, wie es ist
    if choice == "100":
        assert doc.zoom == 100
    else:
        zoom = doc.zoom
        assert abs(zoom - 150) > 1  # nicht der zuletzt verwendete Zoom …
        (doc.fitWidth if choice == "width" else doc.fitPage)()
        pump(0.2)
        assert abs(doc.zoom - zoom) < 0.01  # … sondern Seitenbreite bzw. ganze Seite
    # Ein weiteres Dokument öffnet wieder mit der Vorgabe – auch nach anderer Ansicht dazwischen
    doc.setZoom(230)
    pump(0.2)
    again = open_pdf(h, samples.standard_text(tmp_path / "noch.pdf", pages=1))
    assert again.fit == fit and (choice != "100" or again.zoom == 100)


@pytest.mark.parametrize("choice,panel", [("thumbs", "thumbs"), ("outline", "outline"), ("none", "")])
def test_open_settings_left_panel_applies_to_new_documents(reader_app, tmp_path: Path, choice: str, panel: str) -> None:
    h = reader_app
    r = reader(h)
    r.leftPanel = "search"  # zuletzt verwendet: eine andere Seitenleiste
    h.settings.setReaderPanel(choice)
    open_pdf(h, samples.structured(tmp_path / "neu.pdf"))
    pump(0.5)
    assert r.leftPanel == panel
    assert h.item("readerLeftPanel").property("panel") == panel
    assert h.item("readerLeftRail").property("collapsed") is (panel == "")
    # beim Lesen umgeschaltet: gilt für dieses Dokument, das nächste öffnet wieder mit der Vorgabe
    r.showLeftPanel("search")
    open_pdf(h, samples.standard_text(tmp_path / "weiter.pdf"))
    assert r.leftPanel == panel


def test_open_settings_in_the_settings_page_persist(reader_app, config_file: Path) -> None:
    """Einstellungen → »PDF Reader«: zwei Auswahllisten, mit der Tastatur bedienbar, gespeichert
    und nach einem Neustart wieder da. »Animationen« bleibt in ihrer Karte."""
    import json

    from conftest import neustart

    h = reader_app
    h.navigate("settings", 0.3)
    assert [entry["label"] for entry in h.settings.readerZooms] == ["Zuletzt verwendet", "Seitenbreite", "Ganze Seite", "100 %"]
    assert [entry["label"] for entry in h.settings.readerPanels] == ["Zuletzt verwendet", "Seiten", "Lesezeichen", "Keine"]
    zoom, panel = h.item("readerZoomCombo"), h.item("readerPanelCombo")
    assert zoom.property("currentText") == panel.property("currentText") == "Zuletzt verwendet"
    assert h.item("readerZoomCard").property("title") == "Standardzoom beim Öffnen"
    assert h.item("readerPanelCard").property("title") == "Seitenleiste beim Öffnen"
    assert h.item("profileCombo") is not None  # Animationen: unverändert in ihrer Karte
    zoom.forceActiveFocus()
    key(h, Qt.Key.Key_Down)
    key(h, Qt.Key.Key_Down)
    panel.forceActiveFocus()
    for _ in range(3):
        key(h, Qt.Key.Key_Down)
    pump(0.3)
    assert (h.settings.readerZoom, h.settings.readerPanel) == ("page", "none")
    assert zoom.property("currentText") == "Ganze Seite" and panel.property("currentText") == "Keine"
    data = json.loads(config_file.read_text(encoding="utf-8"))
    assert data["reader_zoom_beim_oeffnen"] == "page" and data["reader_leiste_beim_oeffnen"] == "none"
    h = neustart(h)
    assert (h.settings.readerZoom, h.settings.readerPanel) == ("page", "none")
    h.navigate("settings", 0.3)
    assert h.item("readerZoomCombo").property("currentText") == "Ganze Seite"
