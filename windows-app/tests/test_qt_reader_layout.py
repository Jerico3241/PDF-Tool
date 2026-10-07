"""Qt-Oberfläche: Aufbau des PDF Readers – Tab-Leiste, Seitenleisten und Dokumentfläche.

Drei Ebenen: die Tab-Leiste oben (jedes PDF ein Tab neben ⌂ Start, seit 3.1.0-beta.4), die Seitenleisten links
und rechts mit festen Breiten und ihren Umschaltern im eigenen Kopf (geschlossen: ein schmaler Streifen mit ihren
Symbolen), in der Mitte die Dokumentfläche. Bedient wird wie von Hand (Klicks auf Tabs, Reiter, Streifen und
Schließen, Mausrad). Nach jedem Test darf die QML-Engine keine Meldung ausgegeben haben (Fixtures ``ui_app`` bzw.
``app``).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QGuiApplication, QWheelEvent

import editorsamples as samples
from conftest import neustart, pump, wait_until
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


# --- Tab-Leiste oben: Dokumente als Tabs neben ⌂ Start (Adobe-Prinzip) ------------------------------------------
def test_documents_are_tabs_next_to_start(reader_app, tmp_path: Path) -> None:
    """Jedes PDF ist ein Tab in der Leiste oben neben ⌂ Start – eine Seitenleiste der App gibt es nicht, das Dokument
    hat die ganze Breite. ⌂ führt zur Startseite, ein Klick auf ein PDF zurück in den Reader mit diesem Dokument;
    nach dem letzten geschlossenen PDF geht es zur Startseite."""
    h = reader_app
    a, r = h.app, reader(h)
    eins = open_pdf(h, samples.standard_text(tmp_path / "eins.pdf"))
    zwei = open_pdf(h, samples.standard_text(tmp_path / "zwei.pdf"))
    assert h.item("navigationPane") is None
    assert h.item("readerToolbar").mapToScene(QPointF(0, 0)).x() == 0  # Befehlsleiste ab dem linken Fensterrand
    tab = [h.item("readerTab_0"), h.item("readerTab_1")]
    assert tab[1].property("active") and not tab[0].property("active") and not h.item("tabHome").property("active")
    press(h, "tabHome")
    assert a.currentPage == "home" and h.item("tabHome").property("active") and not tab[1].property("active")
    press(h, "readerTab_0")
    assert a.currentPage == "reader" and r.currentKey == eins.docId and tab[0].property("active")
    r.closeTab(eins.docId)
    pump(0.4)
    assert a.currentPage == "reader" and r.currentKey == zwei.docId
    r.closeTab(zwei.docId)
    pump(0.4)
    assert a.currentPage == "home" and not r.hasDocument


def test_open_from_start_shows_the_reader_once_the_document_is_there(ui_app, tmp_path: Path) -> None:
    """Von der Startseite aus erscheint der Reader erst mit dem geöffneten Dokument – nie leer. Lässt sich eine Datei
    nicht öffnen, bleibt die Startseite und zeigt den Hinweis."""
    h = ui_app
    h.app.dialogs.shutdown()
    h.navigate("home", 0.3)
    r = reader(h)
    kaputt = tmp_path / "kein.pdf"
    kaputt.write_text("kein PDF", encoding="utf-8")
    r.open_paths([str(kaputt)])
    assert h.app.currentPage == "home"
    assert wait_until(lambda: r.opening == 0, 30)
    settle(h)
    assert h.app.currentPage == "home" and h.item("homeReaderInfo").property("shown") is True
    r.open_paths([str(samples.standard_text(tmp_path / "gut.pdf"))])
    assert h.app.currentPage == "home"  # noch nicht geöffnet
    assert wait_until(lambda: r.tabs.count == 1 and h.app.currentPage == "reader", 30)


def test_many_tabs_show_whole_tabs_with_arrows_and_move_by_one_tab(reader_app, tmp_path: Path) -> None:
    """Viele Tabs im schmalen Fenster: Die Werkzeug-Tabs werden schmaler, damit die PDF-Tabs mindestens 200 px haben;
    reicht der Platz nicht für alle PDF-Tabs (je mindestens 144 px), zeigt die Leiste nur ganze, gleich breite Tabs
    und ‹ › zum Blättern – nie einen halb abgeschnittenen Tab. Pfeile und Mausrad verschieben um genau einen Tab,
    nie über das Ende hinaus; der aktive Tab bleibt ganz zu sehen. Im Tab steht der Name ohne ».pdf«."""
    h = reader_app
    a, r = h.app, reader(h)
    for page in ("repair", "create", "settings"):
        a.navigate(page)
        pump(0.2)
    for nummer in range(6):
        open_pdf(h, samples.standard_text(tmp_path / f"Dokument mit einem recht langen Namen {nummer}.pdf"))
    h.window.resize(760, 560)
    pump(0.6)
    leiste, docs = h.item("appTabs"), h.item("readerTabs")
    zurueck, weiter = h.item("readerTabsBack"), h.item("readerTabsForward")
    assert leiste.width() == 760 and right_x(h.item("appSettingsButton")) <= 760
    assert leiste.property("docsOverflow") and zurueck.isVisible() and weiter.isVisible()
    takt = leiste.property("docPitch")
    assert takt == 146 and docs.width() == leiste.property("docsShown") * takt - 2 and docs.width() >= 144

    def ganz_zu_sehen(tab) -> bool:
        return left_x(docs) - 0.5 <= left_x(tab) and right_x(tab) <= right_x(docs) + 0.5

    def nur_ganze_tabs() -> bool:
        for nummer in range(6):
            tab = h.item(f"readerTab_{nummer}")  # die Liste legt nur Tabs in der Nähe des Sichtbaren an
            if tab is None:
                continue
            assert tab.width() == 144
            draussen = right_x(tab) <= left_x(docs) + 0.5 or left_x(tab) >= right_x(docs) - 0.5
            if not (draussen or ganz_zu_sehen(tab)):
                return False
        return True

    assert ganz_zu_sehen(h.item("readerTab_5")) and nur_ganze_tabs()  # zuletzt geöffnet = aktiv
    r.activate(r.tabs.keys()[0])
    pump(0.5)
    assert ganz_zu_sehen(h.item("readerTab_0")) and docs.property("contentX") == 0
    assert not zurueck.property("enabled") and weiter.property("enabled")
    assert h.item("readerTab_0").property("title") == "Dokument mit einem recht langen Namen 0"
    mitte = docs.mapToScene(QPointF(docs.width() / 2, docs.height() / 2))

    def rad(schritte: int) -> None:
        for _ in range(abs(schritte)):
            ereignis = QWheelEvent(mitte, QPointF(h.window.mapToGlobal(mitte.toPoint())), QPoint(0, 0), QPoint(0, -120 if schritte > 0 else 120),
                                   Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
            QGuiApplication.sendEvent(h.window, ereignis)
            pump(0.3)

    rad(1)
    assert docs.property("contentX") == pytest.approx(takt) and nur_ganze_tabs() and zurueck.property("enabled")
    press(h, "readerTabsForward")
    assert docs.property("contentX") == pytest.approx(2 * takt) and nur_ganze_tabs()
    rad(20)  # nie über das Ende hinaus
    ende = docs.property("contentWidth") - docs.width()
    assert docs.property("contentX") == pytest.approx(ende) and ende % takt == pytest.approx(0) and nur_ganze_tabs()
    assert not weiter.property("enabled")
    press(h, "readerTabsBack")
    assert docs.property("contentX") == pytest.approx(ende - takt)
    rad(-30)
    assert docs.property("contentX") == pytest.approx(0)
    # Breites Fenster: alle Tabs haben Platz – keine Pfeile, kein Bildlauf
    h.window.resize(1920, 1080)
    pump(0.6)
    assert not leiste.property("docsOverflow") and not zurueck.isVisible() and not weiter.isVisible()
    assert docs.property("contentX") == 0 and docs.width() == docs.property("contentWidth")


def test_closing_with_many_tabs_leaves_no_qml_messages(reader_app, tmp_path: Path, capfd) -> None:
    """Beenden mit Werkzeug-Tabs und vielen PDFs: Beim Schließen der PDFs laufen keine Übergänge der Tab-Leiste
    mehr, und zum Löschen vorgemerkte Tabs enden vor der QML-Engine – sonst meldete Qt beim Abbau »Cannot find
    member data« für halb abgebaute Tabs."""
    h = reader_app
    a, r = h.app, reader(h)
    for page in ("repair", "create", "settings"):
        a.navigate(page)
        pump(0.2)
    for nummer in range(6):
        open_pdf(h, samples.standard_text(tmp_path / f"Dokument mit einem recht langen Namen {nummer}.pdf"))
    h.window.resize(760, 560)
    pump(0.6)
    r.activate(r.tabs.keys()[0])
    pump(0.5)
    capfd.readouterr()
    neu = neustart(h)  # beendet wie beim Schließen des Fensters und startet neu
    ausgabe = capfd.readouterr().err
    assert not [zeile for zeile in ausgabe.splitlines() if "QML" in zeile], ausgabe[-3000:]
    assert neu.app.currentPage == "home" and reader(neu).tabs.count == 0


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
