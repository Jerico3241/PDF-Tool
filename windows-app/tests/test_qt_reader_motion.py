"""Qt-Oberfläche: Bewegung im PDF Reader – mit allen drei Animationsprofilen.

»Vollständig«: Seitenleisten gleiten, Markierungen wandern, Seiten rücken beim Organisieren weich.
»Reduziert«: nur kurze Überblendungen, nichts bewegt sich. »Aus«: jeder Zustand sofort am Ziel.
Geprüft wird außerdem, dass nach schnellen Wiederholungen kein Zustand verloren geht und dass Scrollen
und Strg+Mausrad direkt bleiben. Bedient wird wie von Hand; nach jedem Test darf die QML-Engine keine
Meldung ausgegeben haben.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from PySide6.QtCore import QObject, QPoint, QPointF, Qt
from PySide6.QtTest import QTest

import editorsamples as samples
from conftest import _prepare, pump, wait_until
from test_qt_reader import click, ctrl_wheel, open_pdf, page_item, prop, reader, settle, window_point

LEFT = Qt.MouseButton.LeftButton
NO_MOD = Qt.KeyboardModifier.NoModifier


@pytest.fixture(params=["full", "reduced", "off"], ids=["vollstaendig", "reduziert", "aus"])
def motion_app(request, qt_application, config_file: Path, monkeypatch):
    from qtutil import Harness

    _prepare(config_file, monkeypatch, request.param)
    harness = Harness(ui=True)
    holder = {"current": harness}
    harness.holder = holder
    harness.app.dialogs.shutdown()  # »Neu in Version« (nicht blockierend) schließen
    harness.navigate("reader", 0.3)
    yield harness
    current = holder["current"]
    messages = current.messages()
    current.close()
    assert not messages, "QML-Meldungen:\n" + "\n".join(messages)


def profile(h) -> str:
    """Wirksames Profil (unter Windows kann »Vollständig« systembedingt »Reduziert« sein)."""
    return h.runtime.theme.effectiveProfile


def scene_x(item) -> float:
    return item.mapToScene(QPointF(0, 0)).x()


def trace(read, duration: float = 0.6) -> list:
    """Werte während einer Animation sammeln (in jedem Durchlauf der Ereignisschleife) – unabhängig davon,
    wie schnell der Rechner ist: Zwischenwerte gibt es genau dann, wenn sich etwas bewegt bzw. blendet."""
    values = [read()]
    end = time.monotonic() + duration
    while time.monotonic() < end:
        pump(0.004)
        values.append(read())
    return values


def between(values, low: float, high: float, margin: float = 0.5) -> bool:
    """Kommt ein Wert echt zwischen ``low`` und ``high`` vor (Zwischenstand einer Animation)?"""
    lo, hi = min(low, high), max(low, high)
    return any(lo + margin < value < hi - margin for value in values)


def center_x(item) -> float:
    return item.mapToScene(QPointF(item.width() / 2, 0)).x()


# --- Seitenleisten ------------------------------------------------------------------------------------------------
def test_side_panels_slide_fade_or_switch_and_keep_their_state_after_rapid_toggling(motion_app, tmp_path: Path) -> None:
    h = motion_app
    open_pdf(h, samples.standard_text(tmp_path / "leisten.pdf"))
    r = reader(h)
    panel, rail = h.item("readerRightPanel"), h.item("readerRightRail")
    edge = scene_x(rail) + rail.width()
    r.setRightPanel("comments")
    seen = trace(lambda: (scene_x(panel) + panel.width(), panel.property("opacity")) if panel.isVisible() else (edge, 1.0))
    xs, opacities = [x for x, _ in seen], [o for _, o in seen]
    assert between(xs, edge, edge + panel.width()) == (profile(h) == "full")  # gleitet nur bei »Vollständig«
    assert between(opacities, 0, 1, 0.01) == (profile(h) == "reduced")  # »Reduziert«: blendet, ohne Weg
    assert round(scene_x(panel) + panel.width()) == round(edge) and panel.property("opacity") == 1
    # Schnell hintereinander öffnen, wechseln, schließen: am Ende gilt genau der letzte Zustand
    for key in ("properties", "comments", "comments", "properties", "properties"):
        r.setRightPanel(key)
        pump(0.01)
    for key in ("outline", "search", "outline", "thumbs", "thumbs"):
        r.setLeftPanel(key)
        pump(0.01)
    pump(0.5)
    assert r.rightPanel == "" and r.leftPanel == ""
    assert not panel.isVisible() and not h.item("readerLeftPanel").isVisible()
    assert h.item("readerRailComments").isVisible() and h.item("readerRailThumbs").isVisible()


def test_panel_tabs_crossfade_and_the_selection_slides(motion_app, tmp_path: Path) -> None:
    h = motion_app
    open_pdf(h, samples.standard_text(tmp_path / "reiter.pdf"))
    selection = [item for item in h.items("readerPanelTabSelection") if item.isVisible()][0]
    start, target = selection.property("x"), h.item("readerTabSearch").property("x")
    QTest.mouseClick(h.window, LEFT, NO_MOD, window_point(h.item("readerTabSearch"), 14, 14))
    xs = trace(lambda: selection.property("x"))
    assert between(xs, start, target) == (profile(h) == "full")  # gleitet nur bei »Vollständig«
    assert selection.property("x") == target and reader(h).leftPanel == "search"


# --- Dokument-Tabs ---------------------------------------------------------------------------------------------
def test_document_tabs_indicator_and_dirty_dot(motion_app, tmp_path: Path) -> None:
    h = motion_app
    r = reader(h)
    docs = [open_pdf(h, samples.standard_text(tmp_path / f"tab{i}.pdf")) for i in range(3)]
    indicator = h.item("readerTabIndicator")

    def tab(i: int):
        return h.item(f"readerTab_{i}")

    pump(0.5)
    assert abs(center_x(indicator) - center_x(tab(2))) < 1.5  # der neue Tab ist aktiv
    # Schnell wechseln: die Markierung landet beim zuletzt gewählten Tab
    for key in (docs[0].docId, docs[1].docId, docs[0].docId):
        r.activate(key)
        pump(0.01)
    pump(0.5)
    assert r.currentKey == docs[0].docId and abs(center_x(indicator) - center_x(tab(0))) < 1.5
    # Ungespeichert: der Punkt blendet ein, nach dem Speichern wieder aus; der Tab wird dabei nicht breiter
    width = tab(0).width()
    dot = [item for item in h.items("readerTabDirty") if item.parentItem().parentItem().objectName() == "readerTab_0"][0]
    assert dot.property("opacity") == 0
    docs[0].rotatePages([0], 90)
    settle(h)
    assert wait_until(lambda: dot.property("opacity") == 1, 2) and tab(0).width() == width
    docs[0].saveDocument()
    settle(h)
    assert wait_until(lambda: dot.property("opacity") == 0, 2) and not docs[0].dirty
    # Schließen: die übrigen Tabs rücken nach, die Markierung folgt dem aktiven Tab
    r.closeTab(docs[1].docId)
    pump(0.6)
    assert r.tabs.count == 2 and abs(center_x(indicator) - center_x(tab(0))) < 1.5


# --- Kontextmenü und Werkzeuge ---------------------------------------------------------------------------------
def test_context_menu_fades_and_grows_and_the_tool_marker_follows(motion_app, tmp_path: Path) -> None:
    h = motion_app
    doc = open_pdf(h, samples.standard_text(tmp_path / "menue.pdf"), whole_page=True)
    item = page_item(h, 0)
    menus = [obj for obj in item.findChildren(QObject) if obj.objectName() == "readerContextMenu"]
    assert len(menus) == 1
    menu = menus[0]
    QTest.mouseClick(h.window, Qt.MouseButton.RightButton, NO_MOD, window_point(item, 120, 200))
    seen = trace(lambda: (menu.property("scale"), menu.property("opacity")), 0.4)
    scales, opacities = [sc for sc, _ in seen], [o for _, o in seen]
    assert menu.property("visible")
    assert any(sc < 0.999 for sc in scales) == (profile(h) == "full")  # wächst nur bei »Vollständig«
    assert between(opacities, 0, 1, 0.01) == (profile(h) != "off")  # blendet, außer bei »Aus«
    assert menu.property("scale") == 1 and menu.property("opacity") == 1
    QTest.keyClick(h.window, Qt.Key.Key_Escape)
    pump(0.3)
    # Werkzeug wechseln: die Markierung sitzt danach unter dem neuen Werkzeug
    marker = h.item("readerToolIndicator")
    assert abs(center_x(marker) - center_x(h.item("readerToolSelect"))) < 1.5
    click(h, window_point(h.item("readerToolImage"), 10, 10))
    pump(0.5)
    assert doc.tool == "image" and abs(center_x(marker) - center_x(h.item("readerToolImage"))) < 1.5


# --- Seiten organisieren ---------------------------------------------------------------------------------------
def test_organize_drag_previews_the_new_order_and_the_pages_settle(motion_app, tmp_path: Path) -> None:
    h = motion_app
    doc = open_pdf(h, samples.standard_text(tmp_path / "ordnen.pdf", pages=4))
    reader(h).setOrganize(True)
    pump(0.4)
    grid = h.item("readerOrganizeGrid")

    def cell_point(index: int) -> QPoint:
        width, height = grid.property("cellWidth"), grid.property("cellHeight")
        columns = max(1, int((grid.width() - 16) // width))
        x = (index % columns) * width + width / 2 - grid.property("contentX")
        y = (index // columns) * height + height / 2 - grid.property("contentY")
        return window_point(grid, x, y)

    def cells() -> dict[int, object]:
        return {child.property("index"): child for child in grid.property("contentItem").childItems() if child.property("isCell")}

    click(h, cell_point(3))
    start, end = cell_point(3), QPoint(cell_point(0).x() - 60, cell_point(0).y())
    QTest.mousePress(h.window, LEFT, NO_MOD, start)
    for step in range(1, 11):
        QTest.mouseMove(h.window, QPoint(start.x() + (end.x() - start.x()) * step // 10, start.y() + (end.y() - start.y()) * step // 10))
        pump(0.01)
    pump(0.4)
    ghost = h.item("readerOrganizeGhost")
    shown = {index: cell.property("shownAt") for index, cell in cells().items()}
    if profile(h) == "full":
        assert shown == {0: 1, 1: 2, 2: 3, 3: 0}  # Vorschau der neuen Reihenfolge
        assert ghost.isVisible()
    else:
        assert shown == {0: 0, 1: 1, 2: 2, 3: 3}  # nichts bewegt sich; die Einfügemarke zeigt die Stelle
        assert ghost.isVisible() == (profile(h) == "reduced")
    QTest.mouseRelease(h.window, LEFT, NO_MOD, end)
    settle(h)
    pump(0.6)
    assert doc.undoText == "Seite verschieben"
    assert all(cell.property("offsetX") == 0 and cell.property("offsetY") == 0 for cell in cells().values())
    assert {index: cell.property("shownAt") for index, cell in cells().items()} == {0: 0, 1: 1, 2: 2, 3: 3}
    assert prop(h.item("readerOrganizeView"), "selectedPages") == [0]  # die abgelegte Seite bleibt gewählt
    assert not ghost.isVisible()
    # Löschen: danach drei Seiten, alle an ihrem Platz und sichtbar
    click(h, cell_point(1))
    click(h, window_point(h.item("readerOrganizeDelete"), 10, 10))
    settle(h)
    pump(0.6)
    assert doc.pageCount == 3
    assert all(cell.property("offsetX") == 0 and cell.property("opacity") == 1 for cell in cells().values())


# --- Ansicht: Zoom, Seitenbilder, Suche, Ablegen ------------------------------------------------------------------
def test_zoom_buttons_glide_but_wheel_scrolling_and_pages_stay_direct(motion_app, tmp_path: Path) -> None:
    h = motion_app
    doc = open_pdf(h, samples.standard_text(tmp_path / "zoom.pdf", pages=3))
    view = h.item("readerView")
    before = doc.zoom
    QTest.mouseClick(h.window, LEFT, NO_MOD, window_point(h.item("readerZoomIn"), 10, 10))
    assert doc.zoom > before  # der Zoom gilt sofort, nur die Darstellung gleitet
    glides = trace(lambda: view.property("glide"), 0.4)
    assert any(glide < 0.999 for glide in glides) == (profile(h) == "full")
    assert view.property("glide") == 1
    # Strg+Mausrad: immer direkt
    ctrl_wheel(h, window_point(view, view.width() / 2, view.height() / 2), 1)
    assert all(glide == 1 for glide in trace(lambda: view.property("glide"), 0.3))
    # Scrollen: Seiten folgen sofort (keine Bewegung, keine Skalierung)
    page = page_item(h, 0)
    y = page.mapToScene(QPointF(0, 0)).y()
    view.setProperty("contentY", view.property("contentY") + 120)
    assert abs(page.mapToScene(QPointF(0, 0)).y() - (y - 120)) < 0.5 and page.property("scale") == 1
    # Seitenbild: nach dem Laden voll deckend
    images = [child for child in page.childItems() if child.property("ready") is not None and child.property("asynchronous")]
    assert images and wait_until(lambda: images[0].property("opacity") == 1, 2)


def test_search_hits_and_drop_overlay(motion_app, tmp_path: Path) -> None:
    h = motion_app
    doc = open_pdf(h, samples.standard_text(tmp_path / "suche.pdf", pages=2))
    doc.search("Rechnung", False, False)
    assert wait_until(lambda: not doc.searchRunning, 30) and doc.searchCount > 0
    settle(h)
    pump(0.4)
    layers = [item for item in h.items("readerHitLayer") if item.isVisible() and item.property("rects")]
    assert layers and all(layer.property("opacity") == 1 for layer in layers)
    doc.nextHit()
    pump(0.5)
    current = [item for item in h.items("readerCurrentHit") if item.isVisible()]
    assert current and all(item.property("grow") == 0 and item.property("opacity") == 1 for item in current)
    # Datei über die Ansicht gezogen: Ablagefläche nur, solange gezogen wird
    overlay = h.item("readerDropOverlay")
    reader(h).dropHighlight = True
    pump(0.02 if profile(h) == "off" else 0.4)
    assert overlay.isVisible() and overlay.property("opacity") == 1
    reader(h).dropHighlight = False
    pump(0.02 if profile(h) == "off" else 0.4)
    assert not overlay.isVisible()
