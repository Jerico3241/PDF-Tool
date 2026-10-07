"""Qt-Oberfläche: Aufbau des PDF Readers – App-Navigation, Seitenleisten und Dokumentfläche.

Drei Ebenen: die App-Navigation (bei geöffnetem Dokument eingeklappt), die Seitenleisten links und rechts
mit festen Breiten und ihren Umschaltern im eigenen Kopf (geschlossen: ein schmaler Streifen mit ihren
Symbolen), in der Mitte die Dokumentfläche. Bedient wird wie von Hand (Klicks auf Reiter, Streifen,
Schließen und Menüschaltfläche). Nach jedem Test darf die QML-Engine keine Meldung ausgegeben haben
(Fixtures ``ui_app`` bzw. ``app``).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import QPointF

import editorsamples as samples
from conftest import pump, wait_until
from test_qt_reader import click, open_pdf, reader, settle, window_point

LEFT_WIDTH, RIGHT_WIDTH, RAIL = 300, 280, 44  # Metrics.readerLeftPanelWidth / readerRightPanelWidth / readerRailWidth


@pytest.fixture
def reader_app(ui_app):
    ui_app.app.dialogs.shutdown()  # »Neu in Version« (nicht blockierend) schließen
    ui_app.navigate("reader", 0.3)
    assert ui_app.app.currentPage == "reader"
    return ui_app


@pytest.fixture
def reader_profiles(app):
    """Reader mit Animationsprofil »Vollständig« bzw. »Aus« (Fixture ``app``)."""
    app.app.dialogs.shutdown()
    app.navigate("reader", 0.3)
    return app


def press(h, name: str) -> None:
    item = h.item(name)
    assert item is not None and item.isVisible(), f"{name} nicht sichtbar"
    click(h, window_point(item, item.width() / 2, item.height() / 2))
    pump(0.4)


def left_x(item) -> float:
    return item.mapToScene(QPointF(0, 0)).x()


def titles(h) -> list[str]:
    return sorted(item.property("text") for item in h.items("readerPanelTitle") if item.isVisible())


def right_x(item) -> float:
    return left_x(item) + item.width()


# --- Seitenleisten: feste Breiten, Umschalter im eigenen Kopf ---------------------------------------------------
def test_left_panel_keeps_its_width_and_the_document_does_not_move(reader_app, tmp_path: Path) -> None:
    """Seiten, Lesezeichen, Suchen: dieselbe Breite; die Dokumentfläche bleibt beim Umschalten stehen."""
    h = reader_app
    open_pdf(h, samples.standard_text(tmp_path / "breite.pdf", pages=3))
    panel, view = h.item("readerLeftPanel"), h.item("readerView")
    assert reader(h).leftPanel == "thumbs"
    widths, positions, sizes = set(), set(), set()
    for name in ("readerTabOutline", "readerTabSearch", "readerTabThumbs"):
        press(h, name)
        widths.add(round(panel.width()))
        positions.add(round(left_x(view)))
        sizes.add(round(view.width()))
    assert widths == {LEFT_WIDTH}
    assert positions == {round(right_x(panel))}  # die Dokumentfläche beginnt an der Leiste
    assert len(sizes) == 1


def test_tabs_in_the_header_switch_and_the_strip_reopens(reader_app, tmp_path: Path) -> None:
    h = reader_app
    open_pdf(h, samples.standard_text(tmp_path / "leisten.pdf"))
    r = reader(h)
    # Links: im Kopf wechseln; ein Klick auf den gewählten Reiter ändert nichts
    press(h, "readerTabOutline")
    assert r.leftPanel == "outline" and "Lesezeichen" in titles(h)
    press(h, "readerTabOutline")
    assert r.leftPanel == "outline"
    assert not h.item("readerRailOutline").isVisible()  # offen: keine doppelten Umschalter im Streifen
    # Schließen über den Kopf: übrig bleibt der Streifen mit den Symbolen, die Dokumentfläche rückt nach
    closer = min((item for item in h.items("readerPanelClose") if item.isVisible()), key=left_x)
    click(h, window_point(closer, closer.width() / 2, closer.height() / 2))
    pump(0.4)
    assert r.leftPanel == ""
    assert wait_until(lambda: not h.item("readerLeftPanel").isVisible(), 3)
    rail, view = h.item("readerLeftRail"), h.item("readerView")
    assert round(rail.width()) == RAIL and round(left_x(view)) == round(right_x(rail))
    # Wieder öffnen über den Streifen – gleich mit dem gewünschten Inhalt
    press(h, "readerRailOutline")
    assert r.leftPanel == "outline" and "Lesezeichen" in titles(h)
    assert wait_until(lambda: round(left_x(h.item("readerLeftPanel"))) == round(left_x(rail)), 3)
    # Rechts: geschlossen nur der Streifen; Kommentare ↔ Eigenschaften im Kopf; Schließen
    assert r.rightPanel == "" and h.item("readerRailComments").isVisible()
    press(h, "readerRailComments")
    assert r.rightPanel == "comments" and "Kommentare" in titles(h)
    assert round(h.item("readerRightPanel").width()) == RIGHT_WIDTH
    press(h, "readerTabProperties")
    assert r.rightPanel == "properties" and "Eigenschaften" in titles(h)
    closer = max((item for item in h.items("readerPanelClose") if item.isVisible()), key=left_x)
    click(h, window_point(closer, closer.width() / 2, closer.height() / 2))
    pump(0.4)
    assert r.rightPanel == "" and r.leftPanel == "outline"
    assert wait_until(lambda: h.item("readerRailProperties").isVisible(), 3)


def test_headers_are_uniform_and_titles_fit(reader_app, tmp_path: Path) -> None:
    """Alle Köpfe gleich hoch; jeder Titel passt neben die Umschalter (nicht gekürzt)."""
    h = reader_app
    open_pdf(h, samples.standard_text(tmp_path / "koepfe.pdf"))
    press(h, "readerRailComments")
    seen = {}
    for name in ("readerTabThumbs", "readerTabOutline", "readerTabSearch", "readerTabComments", "readerTabProperties"):
        press(h, name)
        for title in h.items("readerPanelTitle"):
            if title.isVisible():
                seen[title.property("text")] = (round(title.parentItem().parentItem().height()), title.property("truncated"))
    assert set(seen) == {"Seiten", "Lesezeichen", "Suchen", "Kommentare", "Eigenschaften"}
    assert {height for height, _ in seen.values()} == {44}  # Metrics.readerPanelHeaderHeight
    assert not any(truncated for _, truncated in seen.values()), seen


def test_toolbar_no_longer_holds_panel_toggles(reader_app, tmp_path: Path) -> None:
    h = reader_app
    open_pdf(h, samples.standard_text(tmp_path / "leiste.pdf"))
    toolbar = h.item("readerToolbar")
    names = []
    todo = [toolbar]
    while todo:
        item = todo.pop()
        names.append(item.objectName())
        todo.extend(item.childItems())
    assert "readerComments" not in names and "readerSearch" not in names
    for name in ("readerTabThumbs", "readerTabOutline", "readerTabSearch", "readerTabComments", "readerTabProperties",
                 "readerRailThumbs", "readerRailOutline", "readerRailSearch", "readerRailComments", "readerRailProperties"):
        assert h.item(name) is not None, name


def test_empty_states_are_calm_and_explain_what_to_do(reader_app, tmp_path: Path) -> None:
    h = reader_app
    doc = open_pdf(h, samples.standard_text(tmp_path / "leer.pdf"))
    press(h, "readerTabOutline")
    empty = h.item("readerOutlineEmpty")
    assert empty.isVisible() and empty.property("title") == "Keine Lesezeichen"
    press(h, "readerRailComments")
    assert h.item("readerCommentsEmpty").isVisible()
    doc.setTool("objects")
    settle(h)
    press(h, "readerTabProperties")
    empty = h.item("readerObjectPanelEmpty")
    assert empty.isVisible() and empty.property("title") == "Kein Objekt ausgewählt"


# --- App-Navigation: im Dokument eingeklappt --------------------------------------------------------------------
def test_navigation_collapses_for_documents_and_expands_elsewhere(reader_app, tmp_path: Path) -> None:
    h = reader_app
    pane = h.item("navigationPane")
    expanded = pane.width()
    assert expanded > 100  # breites Fenster, Reader ohne Dokument: ausgeklappt
    open_pdf(h, samples.standard_text(tmp_path / "eins.pdf"))
    assert wait_until(lambda: pane.width() < 60, 3)  # kompakt: nur Symbole
    assert h.item("readerView").property("contentY") == 0  # die erste Seite beginnt oben
    # Menüschaltfläche: vorübergehend ausklappen – die gespeicherte Wahl bleibt
    stored = h.app.navCompact
    press(h, "navigationToggle")
    assert wait_until(lambda: pane.width() > 100, 3) and h.app.navCompact == stored
    # Nächstes Dokument: wieder kompakt
    open_pdf(h, samples.standard_text(tmp_path / "zwei.pdf"))
    assert wait_until(lambda: pane.width() < 60, 3)
    # Startseite: normale Navigation
    h.navigate("home", 0.5)
    assert wait_until(lambda: pane.width() > 100, 3)
    h.navigate("reader", 0.5)
    assert wait_until(lambda: pane.width() < 60, 3)


# --- Bewegung: kurz, ohne Umbauen in jedem Bild; »Aus« sofort --------------------------------------------------
def test_panel_opens_without_relayouting_the_document_every_frame(reader_profiles, tmp_path: Path) -> None:
    h = reader_profiles
    open_pdf(h, samples.standard_text(tmp_path / "bewegung.pdf"))
    r = reader(h)
    view, panel = h.item("readerView"), h.item("readerRightPanel")
    widths: list[float] = []
    view.widthChanged.connect(lambda: widths.append(view.width()))
    edge = right_x(h.item("readerRightRail"))  # rechter Rand der Arbeitsfläche
    r.setRightPanel("comments")
    pump(0.02)
    if h.runtime.theme.effectiveProfile == "off":  # »Aus«: sofort an ihrem Platz
        assert panel.isVisible() and round(right_x(panel)) == round(edge)
    pump(0.4)
    assert panel.isVisible() and round(right_x(panel)) == round(edge)
    assert round(right_x(view)) == round(left_x(panel))  # die Dokumentfläche endet an der Leiste
    assert len(set(round(width) for width in widths)) == 1  # die Dokumentfläche nimmt ihre Breite einmal an
    r.setRightPanel("comments")  # schließen
    pump(0.5)
    assert not panel.isVisible() and r.rightPanel == ""
