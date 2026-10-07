"""Qt-Oberfläche: Komfortfunktionen ab 3.2 – Dokument-Tabs (Kontextmenü, »Geschlossenen Tab wieder öffnen«,
Umordnen per Ziehen), PDFs der letzten Sitzung, Nachtmodus, Schnellwerkzeuge der Startseite und »Per E-Mail senden«
(Reader und Vertragsübersichten).

Bedient wird wie von Hand (Rechtsklick, Ziehen mit der Maus, Tastenkürzel, Klick auf Kacheln) oder über die
Controller. Ein E-Mail-Programm wird nie gestartet: Simple MAPI, ``mailto:`` und der Explorer sind Attrappen. Nach
jedem Test darf die QML-Engine keine Meldung ausgegeben haben.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QMetaObject, QPoint, QSize, Qt
from PySide6.QtGui import QColor
from PySide6.QtQuick import QQuickItem
from PySide6.QtTest import QTest

import editorsamples as samples
from conftest import neustart, pump, wait_until
from test_qt_reader import click, open_pdf, reader, settle, window_point

NO_MOD = Qt.KeyboardModifier.NoModifier
LEFT = Qt.MouseButton.LeftButton
CTRL_SHIFT = Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier


@pytest.fixture
def reader_app(ui_app):
    ui_app.app.dialogs.shutdown()  # »Neu in Version« (nicht blockierend) schließen
    ui_app.navigate("reader", 0.3)
    return ui_app


@pytest.fixture
def mailer(monkeypatch):
    """Kein echtes E-Mail-Programm: Simple MAPI fehlt (bzw. liefert ``code``), ``mailto:`` und Explorer werden nur
    protokolliert."""
    from qtapp import mail

    calls: dict = {"mapi": [], "urls": [], "shown": [], "code": None, "url_ok": True}

    def mapi(path, subject, to, body):
        calls["mapi"].append({"path": path, "subject": subject, "to": to})
        return calls["code"]

    monkeypatch.setattr(mail, "_mapi_send", mapi)
    monkeypatch.setattr(mail, "open_url", lambda url: calls["urls"].append(url) or calls["url_ok"])
    monkeypatch.setattr(mail, "show_in_folder", lambda path: calls["shown"].append(path) or True)
    return calls


def names(h) -> list[str]:
    return [item["name"] for item in reader(h).tabs.items()]


def center(item) -> QPoint:
    return window_point(item, item.width() / 2, item.height() / 2)


def open_many(h, tmp_path: Path, *stems: str, pages: int = 1) -> list:
    return [open_pdf(h, samples.standard_text(tmp_path / f"{stem}.pdf", pages=pages)) for stem in stems]


def switch(h, toggle) -> None:
    """Umschalter mit der Tastatur betätigen (Fokus, Leertaste) – auch außerhalb des sichtbaren Bereichs der Seite."""
    toggle.forceActiveFocus()
    QTest.keyClick(h.window, Qt.Key.Key_Space)
    pump(0.2)


# --- Kontextmenü der Dokument-Tabs -------------------------------------------------------------------------------
def test_tab_context_menu_closes_tabs_to_the_right_and_the_others(reader_app, tmp_path: Path, monkeypatch) -> None:
    """Rechtsklick auf einen Dokument-Tab: Schließen, andere bzw. rechts schließen, Pfad kopieren, im Ordner anzeigen
    und »Geschlossenen Tab wieder öffnen« (aus, solange nichts geschlossen wurde). Ungespeicherte Dokumente fragen wie
    beim Schließen eines Tabs nach – »Abbrechen« hört auf, die übrigen Tabs bleiben."""
    from PySide6.QtCore import QObject

    from qtapp import dialogs, files

    h = reader_app
    r = reader(h)
    a, b, c, d = open_many(h, tmp_path, "a", "b", "c", "d")
    menu = h.window.findChild(QObject, "readerTabMenu")
    assert menu is not None and not menu.property("visible")
    QTest.mouseClick(h.window, Qt.MouseButton.RightButton, NO_MOD, center(h.item("readerTab_1")))
    assert wait_until(lambda: menu.property("visible") and menu.property("opacity") == 1, 3)
    entries = {name: h.window.findChild(QObject, name) for name in ("tabMenuClose", "tabMenuCloseOthers", "tabMenuCloseRight", "tabMenuCopyPath", "tabMenuShowFolder", "tabMenuReopen")}
    assert [entries[name].property("text") for name in entries] == ["Schließen", "Andere Tabs schließen", "Tabs rechts schließen", "Pfad kopieren", "Im Ordner anzeigen", "Geschlossenen Tab wieder öffnen"]
    assert [entries[name].property("enabled") for name in entries] == [True, True, True, True, True, False]
    assert menu.property("key") == b.docId and menu.property("path") == b.path
    # »Pfad kopieren« und »Im Ordner anzeigen« (nach dem Ausblenden des Menüs)
    click(h, center(entries["tabMenuCopyPath"]))
    pump(0.3)
    assert h.app.statusText == f"Pfad kopiert: {b.path}"
    QTest.mouseClick(h.window, Qt.MouseButton.RightButton, NO_MOD, center(h.item("readerTab_1")))
    assert wait_until(lambda: menu.property("visible") and menu.property("opacity") == 1, 3)
    click(h, center(entries["tabMenuShowFolder"]))
    assert wait_until(lambda: str(Path(b.path).parent) in files.OPENED, 3)
    # »Tabs rechts schließen« (mit der Maus im Menü)
    QTest.mouseClick(h.window, Qt.MouseButton.RightButton, NO_MOD, center(h.item("readerTab_1")))
    assert wait_until(lambda: menu.property("visible") and menu.property("opacity") == 1, 3)
    click(h, center(entries["tabMenuCloseRight"]))
    assert wait_until(lambda: names(h) == ["a.pdf", "b.pdf"], 5)
    settle(h)
    assert r.canReopen and entries["tabMenuReopen"].property("enabled")
    # »Andere Tabs schließen« mit einem ungespeicherten Dokument: »Abbrechen« hört auf
    c, d = open_many(h, tmp_path, "c", "d")
    b.rotatePages([0], 90)
    settle(h)
    assert b.dirty
    monkeypatch.setattr(dialogs, "AUTO_ANSWER", "close")
    r.closeOtherTabs(d.docId)
    settle(h)
    assert names(h) == ["b.pdf", "c.pdf", "d.pdf"]  # a geschlossen, bei b abgebrochen – c bleibt
    asked = [entry for entry in h.app.dialogs.history if entry["title"] == "Änderungen an »b.pdf« speichern?"]
    assert asked and asked[-1]["primary"] == "Speichern" and asked[-1]["secondary"] == "Nicht speichern"
    # »Nicht speichern«: alle anderen zu, der gewählte Tab ist aktiv
    monkeypatch.setattr(dialogs, "AUTO_ANSWER", "secondary")
    r.closeOtherTabs(d.docId)
    settle(h)
    assert names(h) == ["d.pdf"] and r.current is d and h.app.currentPage == "reader"
    # Ein einzelner Tab: »Andere« und »rechts« sind aus
    QTest.mouseClick(h.window, Qt.MouseButton.RightButton, NO_MOD, center(h.item("readerTab_0")))
    assert wait_until(lambda: menu.property("visible") and menu.property("opacity") == 1, 3)
    assert not entries["tabMenuCloseOthers"].property("enabled") and not entries["tabMenuCloseRight"].property("enabled")
    QTest.keyClick(h.window, Qt.Key.Key_Escape)
    assert wait_until(lambda: not menu.property("visible"), 3)


def test_close_others_keeps_closing_after_save(reader_app, tmp_path: Path, monkeypatch) -> None:
    """»Speichern« in der Rückfrage ist kein Abbruch: das Dokument schließt nach dem Speichern, die übrigen auch."""
    from qtapp import dialogs

    h = reader_app
    r = reader(h)
    a, b, c = open_many(h, tmp_path, "a", "b", "c")
    a.rotatePages([0], 90)
    settle(h)
    monkeypatch.setattr(dialogs, "AUTO_ANSWER", "primary")
    r.closeOtherTabs(c.docId)
    assert wait_until(lambda: names(h) == ["c.pdf"], 30)
    settle(h)
    assert r.current is c


# --- Geschlossenen Tab wieder öffnen ----------------------------------------------------------------------------
def test_reopen_closed_tab_with_shortcut_on_the_remembered_page(reader_app, tmp_path: Path) -> None:
    """Strg+Umschalt+T öffnet das zuletzt geschlossene Dokument wieder – auf der Seite, die zu sehen war; auch von der
    Startseite aus. Der Stapel hält höchstens 10 Dokumente, nur solche mit Pfad; eine inzwischen gelöschte Datei
    meldet sich, statt still zu fehlen."""
    from qtapp.reader import controller as reader_module

    h = reader_app
    r = reader(h)
    long_doc, other = open_many(h, tmp_path, "lang", "anders", pages=4)
    long_doc.goTo(2)
    pump(0.2)
    assert not r.canReopen
    r.closeTab(long_doc.docId)
    settle(h)
    assert r.canReopen and names(h) == ["anders.pdf"]
    h.navigate("home", 0.3)
    QTest.keyClick(h.window, Qt.Key.Key_T, CTRL_SHIFT)
    assert wait_until(lambda: r.tabs.count == 2 and r.current is not None and r.current.name == "lang.pdf", 30)
    settle(h)
    assert r.current.currentPage == 2 and h.app.currentPage == "reader"
    assert not r.canReopen
    # Zweimal schließen, zweimal wieder öffnen: das zuletzt geschlossene zuerst
    r.closeTab(r.current.ident)
    settle(h)
    r.closeTab(other.docId)
    settle(h)
    r.reopenClosed()
    assert wait_until(lambda: r.tabs.count == 1 and r.current.name == "anders.pdf", 30)
    r.reopenClosed()
    assert wait_until(lambda: r.tabs.count == 2 and r.current.name == "lang.pdf", 30)
    settle(h)
    # Gelöschte Datei: Hinweis, kein Tab
    gone = open_pdf(h, samples.standard_text(tmp_path / "weg.pdf"))
    path = Path(gone.path)
    r.closeTab(gone.docId)
    settle(h)
    path.unlink()
    QTest.keyClick(h.window, Qt.Key.Key_T, CTRL_SHIFT)
    pump(0.3)
    notice = h.app.notices.get("reader")
    assert notice.shown and notice.message == "Die Datei »weg.pdf« gibt es nicht mehr." and r.tabs.count == 2
    # Höchstens 10, je Pfad einmal; ohne Pfad (nie gespeichert) nichts
    for number in range(12):
        r._remember_closed(SimpleNamespace(path=str(tmp_path / f"x{number}.pdf"), currentPage=number))  # noqa: SLF001
    r._remember_closed(SimpleNamespace(path=str(tmp_path / "x5.pdf"), currentPage=7))  # noqa: SLF001
    r._remember_closed(SimpleNamespace(path="", currentPage=0))  # noqa: SLF001
    stack = r._closed  # noqa: SLF001
    assert len(stack) == reader_module.CLOSED_LIMIT == 10
    assert stack[-1] == {"path": str(tmp_path / "x5.pdf"), "page": 7} and [entry["path"] for entry in stack].count(str(tmp_path / "x5.pdf")) == 1
    assert str(tmp_path / "x0.pdf") not in [entry["path"] for entry in stack]


def test_quitting_does_not_fill_the_reopen_stack(reader_app, tmp_path: Path) -> None:
    h = reader_app
    r = reader(h)
    open_many(h, tmp_path, "eins", "zwei")
    h.app.shutdown()  # wie beim Beenden: alle PDFs schließen
    assert r.tabs.count == 0 and not r.canReopen and r._closed == []  # noqa: SLF001


# --- Tabs umordnen --------------------------------------------------------------------------------------------------
def test_drag_a_document_tab_to_a_new_place(app, tmp_path: Path) -> None:
    """Ziehen mit der Maus: der Tab folgt dem Zeiger, tauscht mit dem Nachbarn die Stelle, sobald er dessen Mitte
    überschreitet, und gleitet beim Loslassen an seinen Platz (»Aus«: sofort). Ein einfacher Klick wechselt weiter nur
    den Tab. Strg+Umschalt+→ verschiebt den fokussierten Tab, ``moveTab`` ordnet direkt um."""
    h = app
    h.app.dialogs.shutdown()
    r = reader(h)
    open_many(h, tmp_path, "eins", "zwei", "drei")
    pump(0.4)
    first, second = h.item("readerTab_0"), h.item("readerTab_1")
    start = center(first)
    target = window_point(second, second.width() * 0.75, second.height() / 2)
    QTest.mousePress(h.window, LEFT, NO_MOD, start)
    for step in range(1, 13):
        QTest.mouseMove(h.window, QPoint(start.x() + (target.x() - start.x()) * step // 12, start.y()))
        pump(0.02)
    pump(0.1)
    assert names(h) == ["zwei.pdf", "eins.pdf", "drei.pdf"]  # schon beim Ziehen getauscht
    dragged = [item for item in h.items("readerTab_1") if item.property("title") == "eins"][0]
    assert dragged.property("dragged") is True
    QTest.mouseRelease(h.window, LEFT, NO_MOD, target)
    assert wait_until(lambda: dragged.property("dragged") is False and abs(dragged.property("x")) < 0.01, 3)
    assert r.current.name == "drei.pdf"  # Ziehen ist kein Klick: der aktive Tab bleibt
    # Tastatur: fokussierter Tab, Strg+Umschalt+→
    tab = h.item("readerTab_0")
    tab.forceActiveFocus()
    QTest.keyClick(h.window, Qt.Key.Key_Right, CTRL_SHIFT)
    pump(0.4)
    assert names(h) == ["eins.pdf", "zwei.pdf", "drei.pdf"]
    # Direkt: an das Ende, ungültige Stellen ändern nichts
    r.moveTab(0, 9)
    pump(0.4)
    assert names(h) == ["zwei.pdf", "drei.pdf", "eins.pdf"]
    r.moveTab(5, 0)
    r.moveTab(1, 1)
    assert names(h) == ["zwei.pdf", "drei.pdf", "eins.pdf"]
    # Strg+Tab folgt der neuen Reihenfolge
    r.activate(r.tabs.keys()[0])
    r.activateIndex(1)
    assert r.current.name == "drei.pdf"
    # Klick ohne Bewegung wechselt den Tab (wie bisher)
    click(h, center(h.item("readerTab_2")))
    pump(0.3)
    assert r.current.name == "eins.pdf"


# --- Letzte Sitzung -------------------------------------------------------------------------------------------------
def test_session_restore_off_by_default_and_on_after_enabling(ui_app, tmp_path: Path, config_file: Path) -> None:
    """Standard: aus – nach einem Neustart sind keine PDFs offen, die Einstellungen enthalten keine Liste. Eingeschaltet
    merkt sich das Beenden die geöffneten PDFs (Pfad, Seite, das aktive); der nächste Start öffnet sie im Hintergrund
    wieder, zeigt das zuletzt aktive auf seiner Seite und übergeht Dateien, die es nicht mehr gibt. Ausgeschaltet
    verschwindet die Liste aus den Einstellungen."""
    h = ui_app
    h.app.dialogs.shutdown()
    assert h.settings.readerRestoreSession is False
    open_many(h, tmp_path, "eins", "zwei")
    h = neustart(h)
    data = json.loads(config_file.read_text(encoding="utf-8"))
    assert "reader_sitzung" not in data and data["reader_sitzung_wiederherstellen"] is False
    pump(1.0)
    assert reader(h).tabs.count == 0 and h.app.currentPage == "home"
    # Einschalten (Einstellungen → PDF Reader)
    h.navigate("settings", 0.3)
    toggle = h.item("readerSessionToggle")
    assert h.item("readerSessionCard").property("title") == "PDFs der letzten Sitzung beim Start wieder öffnen" and not toggle.property("checked")
    switch(h, toggle)
    assert h.settings.readerRestoreSession is True and toggle.property("checked")
    a, b, c = open_many(h, tmp_path, "a", "b", "c", pages=3)
    a.goTo(2)
    reader(h).activate(b.docId)
    pump(0.2)
    paths = [doc.path for doc in (a, b, c)]  # die Controller enden mit dem Neustart
    h = neustart(h)
    data = json.loads(config_file.read_text(encoding="utf-8"))
    assert data["reader_sitzung"] == {"dokumente": [{"pfad": paths[0], "seite": 2}, {"pfad": paths[1], "seite": 0}, {"pfad": paths[2], "seite": 0}], "aktiv": paths[1]}
    r = reader(h)
    assert wait_until(lambda: r.tabs.count == 3 and r.opening == 0 and r.current is not None and r.current.name == "b.pdf", 30)
    settle(h)
    assert names(h) == ["a.pdf", "b.pdf", "c.pdf"] and h.app.currentPage == "reader"
    assert [doc.currentPage for doc in (r._docs[key] for key in r.tabs.keys())] == [2, 0, 0]  # noqa: SLF001
    assert wait_until(lambda: h.app.statusText == "Letzte Sitzung: 3 PDFs wieder geöffnet.", 5), h.app.statusText
    # Eine Datei fehlt beim nächsten Start: übergangen, gemeldet
    r.closeTab(r.current.ident)
    settle(h)
    Path(paths[2]).unlink()
    h = neustart(h)
    r = reader(h)
    assert wait_until(lambda: r.tabs.count == 1 and r.opening == 0 and r.current is not None, 30)
    settle(h)
    assert names(h) == ["a.pdf"] and r.current.currentPage == 2
    assert wait_until(lambda: h.app.statusText == "Letzte Sitzung: 1 PDF wieder geöffnet – 1 nicht (nicht mehr vorhanden oder nicht lesbar).", 5), h.app.statusText
    # Ausschalten: die Liste verschwindet aus den Einstellungen, der nächste Start öffnet nichts
    h.settings.setReaderRestoreSession(False)
    data = json.loads(config_file.read_text(encoding="utf-8"))
    assert "reader_sitzung" not in data and data["reader_sitzung_wiederherstellen"] is False
    h = neustart(h)
    pump(1.0)
    assert reader(h).tabs.count == 0


def test_session_restore_keeps_a_document_opened_with_the_app_active(ui_app, tmp_path: Path, monkeypatch) -> None:
    """»Öffnen mit« beim Start: die PDFs der letzten Sitzung kommen als weitere Tabs dazu – aktiv bleibt die PDF, mit
    der PDF Tool gestartet wurde. Schon offene Dateien öffnen sich nicht zweimal."""
    from qtapp.reader import controller as reader_module
    from qtutil import Harness

    h = ui_app
    h.app.dialogs.shutdown()
    h.settings.setReaderRestoreSession(True)
    a, _b = open_many(h, tmp_path, "a", "b")
    first = a.path
    started = samples.standard_text(tmp_path / "gestartet.pdf")
    h.close()  # speichert wie beim Beenden
    original = reader_module.ReaderController.__init__

    def init(self, app, cfg, parent=None):
        original(self, app, cfg, parent)
        self.open_external([str(started), first])  # wie »Öffnen mit« vor dem ersten Bild

    monkeypatch.setattr(reader_module.ReaderController, "__init__", init)
    neu = Harness(ui=True)
    monkeypatch.setattr(reader_module.ReaderController, "__init__", original)
    h.holder["current"] = neu
    neu.holder = h.holder
    r = reader(neu)
    assert wait_until(lambda: r.tabs.count == 3 and r.opening == 0, 30)
    settle(neu)
    assert sorted(names(neu)) == ["a.pdf", "b.pdf", "gestartet.pdf"] and names(neu).count("a.pdf") == 1
    assert r.current.name == "a.pdf"  # die zuletzt mit dem Start geöffnete


def test_session_remembers_the_active_tab_from_before_the_quit_prompts(ui_app, tmp_path: Path, config_file: Path, monkeypatch) -> None:
    """Beim Beenden zeigen die Rückfragen das jeweilige ungespeicherte Dokument – gemerkt wird trotzdem der Tab, der
    vorher aktiv war. Ein nie gespeichertes Dokument (ohne Pfad) gehört nicht zur Sitzung."""
    from qtapp import dialogs

    h = ui_app
    h.app.dialogs.shutdown()
    h.settings.setReaderRestoreSession(True)
    first, second = open_many(h, tmp_path, "erstes", "zweites")
    second.rotatePages([0], 90)
    settle(h)
    reader(h).activate(first.docId)
    paths = [first.path, second.path]
    monkeypatch.setattr(dialogs, "AUTO_ANSWER", "secondary")  # »Nicht speichern«
    assert h.app.requestClose() is True
    data = json.loads(config_file.read_text(encoding="utf-8"))
    assert data["reader_sitzung"] == {"dokumente": [{"pfad": paths[0], "seite": 0}, {"pfad": paths[1], "seite": 0}], "aktiv": paths[0]}


def test_saved_session_is_read_robustly() -> None:
    from qtapp.reader.controller import _session_from

    assert _session_from(None) is None and _session_from([]) is None and _session_from({"dokumente": 5}) is None
    assert _session_from({"dokumente": [], "aktiv": "x"}) is None
    session = _session_from({"dokumente": [{"pfad": "C:/a.pdf", "seite": 3}, {"pfad": ""}, {"seite": 1}, "kaputt", {"pfad": "b.pdf", "seite": -2}, {"pfad": "c.pdf", "seite": True}], "aktiv": 7})
    assert session == {"dokumente": [{"pfad": "C:/a.pdf", "seite": 3}, {"pfad": "b.pdf", "seite": 0}, {"pfad": "c.pdf", "seite": 0}], "aktiv": ""}


# --- Nachtmodus -----------------------------------------------------------------------------------------------------
def test_night_image_softens_inverted_colors(qt_application) -> None:
    from PySide6.QtGui import QImage

    from qtapp.reader.engine import night_image

    image = QImage(3, 1, QImage.Format.Format_RGB32)
    for x, color in enumerate(("#FFFFFF", "#000000", "#808080")):
        image.setPixelColor(x, 0, QColor(color))
    night_image(image)
    assert [image.pixelColor(x, 0).name() for x in range(3)] == ["#1e1e1e", "#e0e0e0", "#7f7f7f"]
    assert night_image(QImage()).isNull()


def request(provider, ident: str):
    response = provider.requestImageResponse(ident, QSize())
    assert wait_until(lambda: not response._image.isNull() or response._error != "", 30)  # noqa: SLF001
    return response


def test_night_mode_darkens_only_the_page_images(reader_app, tmp_path: Path, config_file: Path) -> None:
    """Nachtmodus: ``Reader.imageTag`` hängt »~n« an die Kennung der Seitenbilder (Miniaturen, Seiten organisieren);
    das Bild ist dunkelgrau mit heller Schrift und liegt getrennt im Zwischenspeicher. Drucken bleibt unverändert. Der
    Schalter in den Einstellungen folgt dem Zustand, gespeichert wird er in den Einstellungen."""
    h = reader_app
    r = reader(h)
    doc = open_pdf(h, samples.standard_text(tmp_path / "nacht.pdf", pages=2))
    assert r.imageTag == "" and r.nightMode is False
    provider = r.provider()
    day = request(provider, f"{doc.docId}/0/200/{doc.revision}")
    night = request(provider, f"{doc.docId}~n/0/200/{doc.revision}")
    assert day._image.pixelColor(2, 2).name() == "#ffffff"  # noqa: SLF001
    assert night._image.pixelColor(2, 2).name() == "#1e1e1e"  # noqa: SLF001
    assert r.cache.get((doc.docId, 0, 200, doc.revision, "page", (), True)) is not None
    assert r.cache.get((doc.docId, 0, 200, doc.revision, "page", (), False)) is not None
    # Ungültige Kennung bleibt ungültig, ein unbekanntes Dokument auch mit »~n«
    assert request(provider, "~n/0/200/0")._error == "Ungültige Bildadresse"  # noqa: SLF001
    assert request(provider, "d999~n/0/200/0")._error == "Dokument nicht geöffnet"  # noqa: SLF001
    # Einschalten: Miniaturen fragen die Bilder für den Nachtmodus an
    r.showLeftPanel("thumbs")
    r.setNightMode(True)
    assert r.imageTag == "~n" and h.app.statusText.startswith("Nachtmodus ein")
    thumbs = h.item("readerThumbnails")

    def sources() -> list[str]:
        found = []
        for row in thumbs.property("contentItem").childItems():
            found += [item.property("source").toString() for item in row.findChildren(QQuickItem) if item.property("asynchronous") is True]
        return [url for url in found if url]

    assert wait_until(lambda: sources() and all(f"/{doc.docId}~n/" in url for url in sources()), 10)
    # Drucken: unverändert hell
    task = r.engine.submit(lambda: doc.session.print_image(0, 72), label="drucken")
    printed = r.engine.wait(task, timeout=60)
    assert printed.pixelColor(2, 2).name() == "#ffffff"
    # Einstellungen: Schalter folgt dem Zustand und schaltet aus
    h.app.persist()
    assert json.loads(config_file.read_text(encoding="utf-8"))["reader_nachtmodus"] is True
    h.navigate("settings", 0.3)
    toggle = h.item("readerNightToggle")
    assert toggle.property("checked") is True
    switch(h, toggle)
    assert r.nightMode is False and r.imageTag == "" and toggle.property("checked") is False
    h.app.persist()
    assert json.loads(config_file.read_text(encoding="utf-8"))["reader_nachtmodus"] is False


def test_night_mode_survives_a_restart(ui_app) -> None:
    h = ui_app
    reader(h).setNightMode(True)
    h = neustart(h)
    assert reader(h).nightMode is True and reader(h).imageTag == "~n"


# --- Schnellwerkzeuge der Startseite --------------------------------------------------------------------------------
def test_quick_tools_open_a_pdf_and_start_the_tool(ui_app, tmp_path: Path, monkeypatch) -> None:
    """Startseite → Schnellwerkzeuge: acht Kacheln; ein Klick wählt eine PDF, öffnet sie im Tab und startet das
    Werkzeug, sobald das Dokument geöffnet und aktiv ist (``runAction``). »Zusammenführen« hängt weitere PDFs an.
    Abgebrochene Auswahl: nichts geschieht; ein schon offenes Dokument wird aktiv und das Werkzeug startet dort."""
    from qtapp import files
    from qtapp.reader.document import DocumentController

    h = ui_app
    h.app.dialogs.shutdown()
    r = reader(h)
    calls: list = []
    monkeypatch.setattr(DocumentController, "runAction", lambda self, name: calls.append((self.ident, name, r.current is self)), raising=False)
    monkeypatch.setattr(DocumentController, "mergeFiles", lambda self: calls.append((self.ident, "merge", r.current is self)))
    tiles = {entry["action"]: entry for entry in r.quickTools}
    assert [entry["title"] for entry in r.quickTools] == ["PDF verkleinern", "Schwärzen", "Kennwortschutz", "Wasserzeichen", "Seitenzahlen", "Dokument bereinigen", "Unterschreiben", "Zusammenführen"]
    assert list(tiles) == ["optimize", "redact", "protect", "watermark", "headerFooter", "clean", "sign", "merge"]
    h.navigate("home", 0.3)
    for action in tiles:
        tile = h.item(f"quickTool_{action}")
        assert tile is not None and tile.isVisible() and tile.property("title") == tiles[action]["title"]
    grid = h.item("homeQuickGrid")
    assert grid.property("columns") in (1, 2, 4)
    # Abgebrochen: nichts
    click(h, center(h.item("quickTool_optimize")))
    pump(0.3)
    assert r.tabs.count == 0 and calls == [] and h.app.currentPage == "home"
    # Gewählt: öffnen, dann das Werkzeug
    pdf = samples.standard_text(tmp_path / "gross.pdf", pages=2)
    files.RESPONSES.append(str(pdf))
    click(h, center(h.item("quickTool_optimize")))
    assert wait_until(lambda: len(calls) == 1, 30)
    settle(h)
    assert calls == [(r.current.ident, "optimize", True)] and r.current.name == "gross.pdf" and h.app.currentPage == "reader"
    # Schon offen: aktiv, das Werkzeug startet dort (kein zweiter Tab)
    other = open_pdf(h, samples.standard_text(tmp_path / "anderes.pdf"))
    files.RESPONSES.append(str(pdf))
    r.quickTool("protect")
    assert wait_until(lambda: len(calls) == 2, 10)
    assert r.tabs.count == 2 and calls[-1][1:] == ("protect", True) and r.current.name == "gross.pdf"
    # Zusammenführen: PDF wählen, danach die anzuhängenden (mergeFiles)
    files.RESPONSES.append(str(other.path))
    r.quickTool("merge")
    assert wait_until(lambda: len(calls) == 3, 10)
    assert calls[-1] == (other.ident, "merge", True)
    # Unbekannte Aktion: nichts
    r.quickTool("gibtsnicht")
    pump(0.2)
    assert len(calls) == 3


def test_quick_tool_runs_nothing_when_the_document_does_not_open(ui_app, tmp_path: Path, monkeypatch) -> None:
    from qtapp import files
    from qtapp.reader.document import DocumentController

    h = ui_app
    h.app.dialogs.shutdown()
    r = reader(h)
    calls: list = []
    monkeypatch.setattr(DocumentController, "runAction", lambda self, name: calls.append(name), raising=False)
    broken = tmp_path / "kaputt.pdf"
    broken.write_text("kein PDF", encoding="utf-8")
    files.RESPONSES.append(str(broken))
    r.quickTool("clean")
    assert wait_until(lambda: r.opening == 0 and h.app.notices.get("reader").shown, 30)
    pump(0.3)
    assert calls == [] and r.tabs.count == 0


# --- Per E-Mail senden: Reader --------------------------------------------------------------------------------------
def test_send_by_mail_falls_back_to_mailto_and_explorer(reader_app, tmp_path: Path, mailer) -> None:
    """Ohne Simple MAPI: neue Nachricht über ``mailto:`` (Betreff = Dateiname), die Datei im Explorer markiert und ein
    Hinweis, sie selbst anzuhängen. Mit MAPI: übergeben bzw. abgebrochen – nie ein Ersatzweg nach »Abbrechen«."""
    h = reader_app
    doc = open_pdf(h, samples.standard_text(tmp_path / "Angebot 2026.pdf"))
    reader(h).sendByMail()
    notice = h.app.notices.get("reader")
    assert wait_until(lambda: notice.shown and notice.title == "Bitte Anhang hinzufügen", 10)
    assert mailer["urls"] == ["mailto:?subject=Angebot%202026.pdf"] and mailer["shown"] == [doc.path]
    assert "»Angebot 2026.pdf« im Explorer markiert" in notice.message and notice.actions == ["Pfad kopieren"]
    if mailer["mapi"]:
        assert mailer["mapi"][-1]["subject"] == "Angebot 2026.pdf" and mailer["mapi"][-1]["to"] == ""
    # Kein Programm für mailto:
    h.app.hide_notice("reader")
    mailer["url_ok"] = False
    reader(h).sendByMail()
    assert wait_until(lambda: notice.shown and notice.title == "Kein E-Mail-Programm gefunden", 10)


def test_send_by_mail_with_mapi_result(reader_app, tmp_path: Path, mailer, monkeypatch) -> None:
    from qtapp import mail

    h = reader_app
    monkeypatch.setattr(mail, "IS_WINDOWS", True)  # MAPI-Weg (die Attrappe antwortet)
    open_pdf(h, samples.standard_text(tmp_path / "brief.pdf"))
    mailer["code"] = mail.SUCCESS_SUCCESS
    reader(h).sendByMail()
    assert wait_until(lambda: h.app.statusText == "»brief.pdf« wurde an Ihr E-Mail-Programm übergeben.", 10)
    mailer["code"] = mail.MAPI_USER_ABORT
    reader(h).sendByMail()
    assert wait_until(lambda: h.app.statusText == "Senden per E-Mail abgebrochen.", 10)
    assert mailer["urls"] == [] and mailer["shown"] == [] and len(mailer["mapi"]) == 2


def test_send_by_mail_saves_changes_first_or_sends_the_saved_file(reader_app, tmp_path: Path, mailer, monkeypatch) -> None:
    """Ungespeicherte Änderungen: »Speichern und senden« speichert zuerst (der übliche Weg), »Ohne Änderungen senden«
    sendet die gespeicherte Datei, »Abbrechen« nichts."""
    from qtapp import dialogs

    h = reader_app
    r = reader(h)
    doc = open_pdf(h, samples.standard_text(tmp_path / "entwurf.pdf"))
    doc.rotatePages([0], 90)
    settle(h)
    assert doc.dirty
    monkeypatch.setattr(dialogs, "AUTO_ANSWER", "close")
    r.sendByMail()
    pump(0.3)
    assert mailer["urls"] == [] and doc.dirty
    asked = h.app.dialogs.history[-1]
    assert asked["title"] == "Änderungen an »entwurf.pdf« vor dem Senden speichern?" and asked["primary"] == "Speichern und senden" and asked["secondary"] == "Ohne Änderungen senden"
    monkeypatch.setattr(dialogs, "AUTO_ANSWER", "secondary")
    r.sendByMail()
    assert wait_until(lambda: len(mailer["urls"]) == 1, 10)
    assert doc.dirty  # ohne Speichern gesendet
    monkeypatch.setattr(dialogs, "AUTO_ANSWER", "primary")
    r.sendByMail()
    assert wait_until(lambda: len(mailer["urls"]) == 2, 30)
    settle(h)
    assert not doc.dirty and mailer["shown"][-1] == doc.path


def test_send_by_mail_asks_for_a_location_for_a_new_document(reader_app, tmp_path: Path, mailer, monkeypatch) -> None:
    """Ein nie gespeichertes Dokument (wiederhergestellt nach einem Absturz, ohne Original) wird vor dem Senden
    gespeichert – zuerst fragt »Speichern unter« nach dem Ort."""
    from qtapp import dialogs, files
    from tools.pdf_editor import recovery

    h = reader_app
    r = reader(h)
    source = samples.standard_text(tmp_path / "vorlage.pdf")
    script = (
        "import sys; sys.path.insert(0, sys.argv[1]);"
        "from tools.pdf_editor import recovery;"
        "s = recovery.RecoverySession('Neu.pdf', None, False);"
        "s.write(open(sys.argv[2], 'rb').read()); import os; os._exit(0)"
    )
    subprocess.run([sys.executable, "-c", script, str(Path(__file__).resolve().parents[1] / "app"), str(source)], check=True)
    assert len(recovery.orphaned_sessions()) == 1
    monkeypatch.setattr(dialogs, "AUTO_ANSWER", "primary")
    r.offer_recovery()
    assert wait_until(lambda: r.tabs.count == 1 and r.current is not None, 30)
    settle(h)
    doc = r.current
    assert doc.path == ""
    files.RESPONSES.append("")  # »Speichern unter« abgebrochen: nichts
    r.sendByMail()
    pump(0.3)
    assert mailer["urls"] == [] and doc.path == ""
    target = tmp_path / "Gesendet.pdf"
    files.RESPONSES.append(str(target))
    r.sendByMail()
    assert wait_until(lambda: len(mailer["urls"]) == 1, 30)
    settle(h)
    assert target.is_file() and doc.path == str(target) and mailer["urls"] == ["mailto:?subject=Gesendet.pdf"]


# --- Per E-Mail senden: Vertragsübersichten --------------------------------------------------------------------------
def test_contract_pdf_can_be_sent_to_the_invoice_recipient(ui_app, excel_file: Path, tmp_path: Path, monkeypatch) -> None:
    """Nach »PDF erstellen« erscheint »Per E-Mail senden«: neue Nachricht mit der PDF als Anhang, an den
    Rechnungsempfänger – eingetragen oder (wie in der PDF) die einzige Adresse der Excel. »Neue Übersicht« blendet die
    Schaltfläche wieder aus."""
    from qtapp import mail

    h = ui_app
    o = h.overview
    sent: list = []
    monkeypatch.setattr(mail, "send_file", lambda path, subject="", to="", body="": sent.append((path, subject, to)) or mail.OK)
    h.navigate("create", 0.3)
    button = h.item("createMailPdf")
    assert button is not None and not button.isVisible()
    o.ziel = str(tmp_path)
    o.pdfOeffnen = False
    o.mail = ""
    o.use_excel(str(excel_file))
    assert wait_until(lambda: o.readyKind == "success", 60)
    o.start_pdf()
    assert wait_until(lambda: not o.busy and o.lastPdf != "", 90)
    pump(0.3)
    assert button.isVisible() and button.property("text") == "Per E-Mail senden"
    assert "rechnung@muster.de" in button.property("tip")
    assert QMetaObject.invokeMethod(button, "clicked")  # wie ein Klick (die Karte kann außerhalb des Fensters liegen)
    assert wait_until(lambda: len(sent) == 1, 10)
    path = Path(o.lastPdf)
    assert sent == [(str(path), path.name, "rechnung@muster.de")]
    assert wait_until(lambda: h.app.statusText == f"»{path.name}« wurde an Ihr E-Mail-Programm übergeben.", 5)
    # Eingetragener Empfänger hat Vorrang; kein gültiger Empfänger: leer
    o.mail = "buchhaltung@kunde.de"
    o.start_pdf()
    assert wait_until(lambda: not o.busy, 90)
    o.sendPdfByMail()
    assert wait_until(lambda: len(sent) == 2, 10)
    assert sent[-1][2] == "buchhaltung@kunde.de"
    o.mail = "Frau Muster"
    o.start_pdf()
    assert wait_until(lambda: not o.busy, 90)
    o.sendPdfByMail()
    assert wait_until(lambda: len(sent) == 3, 10)
    assert sent[-1][2] == "" and o.lastPdfMailTip.startswith("Neue E-Mail mit der erstellten PDF")
    # Gelöschte PDF: Hinweis, kein Versuch
    Path(o.lastPdf).unlink()
    o.sendPdfByMail()
    pump(0.2)
    assert len(sent) == 3 and h.app.notices.get("pdf_mail_info").shown and not button.isVisible()
    # Neue Übersicht: ausgeblendet
    o.start_pdf()
    assert wait_until(lambda: not o.busy and o.lastPdf != "", 90)
    o.new_overview()
    pump(0.2)
    assert o.lastPdf == "" and not button.isVisible()


def test_batch_detail_offers_mail_for_a_created_pdf(ui_app) -> None:
    """Stapel: die Detailansicht hat »Per E-Mail senden« neben »PDF öffnen« – sichtbar nur mit erstellter PDF."""
    h = ui_app
    button = h.item("batchMailPdf")
    assert button is not None and button.property("text") == "Per E-Mail senden" and not button.isVisible()
    h.batch.mailPdf()  # ohne gewählten Eintrag: nichts
    pump(0.1)
    assert not h.app.notices.get("batch_detail_info").shown
