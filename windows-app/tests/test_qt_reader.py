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
