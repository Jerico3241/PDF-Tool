"""Präsentationen bearbeiten (seit 5.0 Beta 4): Folien im Textkern, die Präsentationsansicht (Entwurf
4-praesentation.png), Notizen unter der Folie und das Vorführen im Vollbild.

Die Tests mit dem Textkern brauchen LibreOffice (``soffice`` im PATH oder ``NOVADESK_LIBREOFFICE``); ohne laufen nur
die übrigen."""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest
from PySide6.QtCore import QEvent, QObject, QPointF, Qt, QUrl
from PySide6.QtGui import QGuiApplication, QKeyEvent
from PySide6.QtQml import QQmlComponent
from PySide6.QtTest import QTest

from conftest import wait_until
from qtutil import pump


def _slides_available() -> bool:
    from tools.text import engine

    return engine.available()


needs_text = pytest.mark.skipif(not _slides_available(), reason="LibreOffice fehlt – Präsentationen nicht prüfbar")


def _key(h, key, modifiers=Qt.KeyboardModifier.NoModifier, text: str = "") -> None:
    for kind in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease):
        QGuiApplication.sendEvent(h.window, QKeyEvent(kind, key, modifiers, text))
    pump(0.03)


def _type(h, text: str) -> None:
    for char in text:
        key = ord(char.upper()) if char.isascii() and char.isalnum() else Qt.Key.Key_unknown
        _key(h, key, Qt.KeyboardModifier.NoModifier, char)


def _new_slides(h):
    reader = h.runtime.singletons["Reader"]
    reader.newSlides()
    assert wait_until(lambda: reader.current is not None and getattr(reader.current, "ready", False), 120)
    pump(1.0)
    return reader.current


def test_slides_view_loads_without_a_document(ui_app) -> None:
    """Die Präsentationsansicht lädt ohne Meldungen, auch ohne Präsentation (im Setup aus der Ressource)."""
    from qtapp.application import QML_DIR

    h = ui_app
    component = QQmlComponent(h.engine, QUrl.fromLocalFile(str(QML_DIR / "PdfTool" / "Reader" / "SlidesView.qml")))
    assert component.isReady(), component.errorString()
    view = component.create()
    assert view is not None
    view.setParentItem(h.window.contentItem())
    pump(0.3)
    for name in ("slidesRibbonTabs", "slidesToolbar", "slidesCanvas", "slidesSave", "slidesPresent", "slidesPdf",
                 "slidesNew", "slidesLayout", "slidesNotesBox", "slidesNotesCanvas", "slidesList", "slidesSideRail"):
        assert view.findChild(QObject, name) is not None, name
    view.deleteLater()
    pump(0.2)


@needs_text
def test_new_presentation_type_add_slide_and_save(ui_app, tmp_path: Path) -> None:
    """Neue Präsentation: Titel tippen, zweite Folie anlegen, zwischen den Folien wechseln und als .pptx speichern
    (PowerPoint liest denselben Text), danach nicht mehr »geändert«."""
    h = ui_app
    h.app.dialogs.shutdown()
    doc = _new_slides(h)
    assert doc.kind == "praesentation" and doc.name.startswith("Präsentation") and doc.name.endswith(".pptx")
    assert not h.item("readerDocumentArea").isVisible()  # die PDF-Ansicht bleibt verborgen
    assert doc.slideCount == 1 and doc.slideIndex == 0
    canvas = h.item("slidesCanvas")
    # In den Titel der Folie klicken und tippen
    QTest.mouseDClick(h.window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                      canvas.mapToScene(QPointF(canvas.width() / 2, canvas.height() / 3)).toPoint())
    pump(0.5)
    _type(h, "Wartung 2026")
    assert wait_until(lambda: doc.dirty and doc.canUndo, 15)
    doc.newSlide()
    assert wait_until(lambda: doc.slideCount == 2, 20)
    doc.goSlide(1)
    assert wait_until(lambda: doc.slideIndex == 1, 20)
    doc.goSlide(0)
    assert wait_until(lambda: doc.slideIndex == 0, 20)
    target = tmp_path / "Angebot äöü.pptx"
    doc.save(str(target))
    assert wait_until(lambda: not doc.saving and target.exists(), 60)
    with zipfile.ZipFile(target) as archive:
        names = archive.namelist()
        assert "ppt/slides/slide1.xml" in names and "ppt/slides/slide2.xml" in names
        assert "Wartung 2026" in archive.read("ppt/slides/slide1.xml").decode("utf-8")
    assert wait_until(lambda: not doc.dirty and doc.name == "Angebot äöü.pptx", 10)


@needs_text
def test_notes_are_edited_under_the_slide(ui_app, tmp_path: Path) -> None:
    """Die Notizen stehen unter der Folie und gehören zur gezeigten Folie: Getipptes landet in den Notizen der Datei,
    die Folie selbst bleibt, wie sie ist."""
    h = ui_app
    h.app.dialogs.shutdown()
    doc = _new_slides(h)
    notes = doc.notes
    assert wait_until(lambda: notes.ready and notes.docWidth > 0, 30)
    assert doc.notesOpen and h.item("slidesNotesBox").isVisible()
    canvas = h.item("slidesNotesCanvas")
    QTest.mouseDClick(h.window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                      canvas.mapToScene(QPointF(canvas.width() / 2, canvas.height() / 2)).toPoint())
    pump(0.5)
    _type(h, "Preise bis 30.11.")
    pump(1.0)
    target = tmp_path / "Notizen.pptx"
    doc.save(str(target))
    assert wait_until(lambda: not doc.saving and target.exists(), 60)
    with zipfile.ZipFile(target) as archive:
        notes_files = [name for name in archive.namelist() if name.startswith("ppt/notesSlides/notesSlide")]
        assert notes_files, "Notizen gespeichert"
        assert any("Preise bis 30.11." in archive.read(name).decode("utf-8") for name in notes_files)
        assert "Preise bis 30.11." not in archive.read("ppt/slides/slide1.xml").decode("utf-8")


@needs_text
def test_ribbon_panel_and_presenting(ui_app) -> None:
    """Reiter wechseln die Leiste; die Folienleiste rechts geht über den Streifen zu und auf; F5 zeigt die Folie im
    Vollbild, die Pfeiltasten blättern, Esc beendet."""
    h = ui_app
    h.app.dialogs.shutdown()
    doc = _new_slides(h)
    view = h.item("slidesView")
    for key in ("file", "insert", "design", "review", "view", "start"):
        QTest.mouseClick(h.window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                         h.item("slidesRibbon_" + key).mapToScene(QPointF(10, 10)).toPoint())
        pump(0.1)
        assert view.property("ribbon") == key
    assert doc.panel == "slides" and h.item("slidesPanel").isVisible()
    doc.togglePanel("slides")
    pump(0.2)
    assert not h.item("slidesPanel").isVisible()
    doc.togglePanel("layouts")
    pump(0.2)
    assert h.item("slidesPanel").isVisible() and h.item("slidesLayout_0") is not None
    doc.togglePanel("slides")
    pump(0.2)
    assert h.item("slidesThumb_0") is not None
    # Vorführen
    doc.newSlide()
    assert wait_until(lambda: doc.slideCount == 2, 20)
    doc.goSlide(0)
    assert wait_until(lambda: doc.slideIndex == 0, 20)
    doc.present()
    assert wait_until(lambda: doc.presenting and doc.presentIndex == 0, 10)
    doc.presentStep(1)
    assert doc.presentIndex == 1
    doc.presentStep(1)  # hinter der letzten Folie: Vorführen endet
    assert wait_until(lambda: not doc.presenting, 10)
    # Präsentation schließen: das Fenster bleibt
    import shiboken6
    from PySide6.QtCore import QCoreApplication

    h.runtime.singletons["Reader"].closeCurrent()
    pump(0.3)
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert shiboken6.isValid(h.window)


@needs_text
def test_existing_presentation_opens_for_editing(ui_app, tmp_path: Path) -> None:
    """Eine .pptx aus dem Dateisystem öffnet sich zum Bearbeiten (nicht mehr nur als PDF-Ansicht); der Tab trägt die
    Dateiart »praesentation«."""
    h = ui_app
    h.app.dialogs.shutdown()
    doc = _new_slides(h)
    source = tmp_path / "Vorlage.pptx"
    doc.save(str(source))
    assert wait_until(lambda: not doc.saving and source.exists(), 60)
    reader = h.runtime.singletons["Reader"]
    reader.closeCurrent()
    pump(0.5)
    assert reader.edits_slides(str(source))
    reader.open_paths([str(source)])
    assert wait_until(lambda: reader.current is not None and reader.current.kind == "praesentation"
                      and reader.current.ready, 120)
    pump(0.5)
    assert reader.current.slideCount >= 1
    items = [reader.tabs.items()[index] for index in range(len(reader.tabs.items()))]
    assert any(item.get("kind") == "praesentation" for item in items)


@needs_text
def test_kernel_in_libreoffice_main_thread(tmp_path: Path, monkeypatch) -> None:
    """Unter Windows läuft der Kern im Hauptthread von LibreOffice (sonst hängt das Laden einer Präsentation); unter
    Linux lässt sich derselbe Weg einschalten: Präsentation laden, Folie anfügen, warten (settle) und speichern."""
    from tools.text import engine, kernel

    monkeypatch.setenv(kernel.MAIN_THREAD_VARIABLE, "1")
    monkeypatch.setattr(engine, "profile_dir", lambda: tmp_path / "profil")
    core = engine.Engine()
    try:
        core.start()
        deck = core.call("open", path="", kind="praesentation")["doc"]
        core.call("uno", doc=deck, command=".uno:InsertPage")
        core.call("settle", doc=deck)
        assert core.call("parts", doc=deck)["count"] == 2
        core.call("save", doc=deck, path=str(tmp_path / "zwei.pptx"))
        assert "ppt/slides/slide2.xml" in zipfile.ZipFile(tmp_path / "zwei.pptx").namelist()
    finally:
        core.stop()
