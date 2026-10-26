"""Texte bearbeiten (seit 5.0 Beta 3): Textkern in LibreOffice (LibreOfficeKit), Text-Ansicht (Entwurf 2-text.png) und
das gemeinsame Menüband für PDFs, Texte und Tabellen.

Die Tests mit dem Textkern brauchen LibreOffice (``soffice`` im PATH oder ``NOVADESK_LIBREOFFICE``); ohne laufen nur
die übrigen. Im Setup prüft ``build.py probe_text`` den Textkern im mitgelieferten LibreOffice."""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest
from PySide6.QtCore import QEvent, QObject, QPointF, Qt, QUrl
from PySide6.QtGui import QGuiApplication, QKeyEvent
from PySide6.QtQml import QQmlComponent
from PySide6.QtTest import QTest

import editorsamples as samples
from conftest import wait_until
from qtutil import pump


def _text_available() -> bool:
    from tools.text import engine

    return engine.available()


needs_text = pytest.mark.skipif(not _text_available(), reason="LibreOffice fehlt – Textkern nicht prüfbar")


def _key(h, key, modifiers=Qt.KeyboardModifier.NoModifier, text: str = "") -> None:
    for kind in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease):
        QGuiApplication.sendEvent(h.window, QKeyEvent(kind, key, modifiers, text))
    pump(0.03)


def _type(h, text: str) -> None:
    for char in text:
        key = ord(char.upper()) if char.isascii() and char.isalnum() else Qt.Key.Key_unknown
        _key(h, key, Qt.KeyboardModifier.NoModifier, char)


def _new_text(h):
    reader = h.runtime.singletons["Reader"]
    reader.newText()
    assert wait_until(lambda: reader.current is not None and getattr(reader.current, "ready", False), 120)
    pump(1.0)
    return reader.current


def test_text_view_loads_without_a_document(ui_app) -> None:
    """Die Text-Ansicht lädt ohne Meldungen, auch ohne Text (im Setup aus der Ressource wie alle Seiten)."""
    from qtapp.application import QML_DIR

    h = ui_app
    component = QQmlComponent(h.engine, QUrl.fromLocalFile(str(QML_DIR / "PdfTool" / "Reader" / "TextView.qml")))
    assert component.isReady(), component.errorString()
    view = component.create()
    assert view is not None
    view.setParentItem(h.window.contentItem())
    pump(0.3)
    for name in ("textRibbonTabs", "textToolbar", "textCanvas", "textSave", "textPdf", "textFont", "textStyle"):
        assert view.findChild(QObject, name) is not None, name
    view.deleteLater()
    pump(0.2)


@needs_text
def test_type_format_copy_paste_and_save(ui_app, tmp_path: Path) -> None:
    """Neuer Text: tippen (mit Umlauten), Strg+B, Auswahl kopieren und einfügen, Statuszeile mit Wörtern, Speichern als
    .docx (Word liest denselben Text), danach nicht mehr »geändert«."""
    h = ui_app
    h.app.dialogs.shutdown()
    doc = _new_text(h)
    assert doc.kind == "text" and doc.name.startswith("Dokument") and doc.name.endswith(".docx")
    assert not h.item("readerDocumentArea").isVisible()  # die PDF-Ansicht bleibt verborgen
    assert doc.cursor, "Schreibmarke nach dem Laden bekannt"
    canvas = h.item("textCanvas")
    QTest.mouseClick(h.window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, canvas.mapToScene(QPointF(300, 120)).toPoint())
    pump(0.3)
    assert canvas.hasActiveFocus()
    _type(h, "Hallo Welt, äöü!")
    _key(h, Qt.Key.Key_Return)
    _key(h, Qt.Key.Key_B, Qt.KeyboardModifier.ControlModifier)
    _type(h, "Fett")
    assert wait_until(lambda: doc.bold and doc.dirty and doc.canUndo, 10)
    assert wait_until(lambda: doc.wordText == "4 Wörter", 10)
    # Erste Zeile wählen und kopieren: Windows-Zwischenablage hat den Text
    _key(h, Qt.Key.Key_Home, Qt.KeyboardModifier.ControlModifier)
    _key(h, Qt.Key.Key_End, Qt.KeyboardModifier.ShiftModifier)
    assert wait_until(lambda: doc.canCopy and doc.selection, 10)
    doc.copy()
    assert wait_until(lambda: QGuiApplication.clipboard().text() == "Hallo Welt, äöü!", 10)
    _key(h, Qt.Key.Key_End, Qt.KeyboardModifier.ControlModifier)
    _key(h, Qt.Key.Key_Return)
    doc.paste()
    pump(0.5)
    target = tmp_path / "Test äöü.docx"
    assert doc.save(str(target)) is not False
    assert wait_until(lambda: not doc.saving and target.exists(), 30)
    xml = zipfile.ZipFile(target).read("word/document.xml").decode("utf-8")
    assert xml.count("Hallo Welt, äöü!") == 2 and "Fett" in xml
    assert wait_until(lambda: not doc.dirty and doc.name == "Test äöü.docx", 10)


@needs_text
def test_text_ribbon_tabs_and_sidebar(ui_app) -> None:
    """Reiter wechseln die Leiste; die Formatvorlagen rechts gehen über den Kopf zu und über das Menüband wieder auf."""
    h = ui_app
    h.app.dialogs.shutdown()
    doc = _new_text(h)
    view = h.item("textView")
    for key in ("file", "insert", "page", "review", "view", "start"):
        QTest.mouseClick(h.window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                         h.item("textRibbon_" + key).mapToScene(QPointF(10, 10)).toPoint())
        pump(0.1)
        assert view.property("ribbon") == key
    assert doc.sidebar and h.item("textSidebar").isVisible()
    doc.toggleSidebar()
    pump(0.2)
    assert not h.item("textSidebar").isVisible()
    doc.toggleSidebar()
    pump(0.2)
    assert h.item("textSidebar").isVisible()
    # Text schließen: das Fenster bleibt (der Zeichenbereich hing es früher an sich und löschte es mit)
    import shiboken6
    from PySide6.QtCore import QCoreApplication

    h.runtime.singletons["Reader"].closeCurrent()
    pump(0.3)
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert shiboken6.isValid(h.window)


def test_pdf_uses_the_same_ribbon(ui_app, tmp_path: Path) -> None:
    """PDFs haben dasselbe Menüband wie Texte und Tabellen (Reiter mit Unterstrich in der Farbe der Dateiart, Speichern,
    Drucken, Rückgängig rechts); Werkzeuge wählt man dort, ohne Schnellwerkzeuge und Randstreifen daneben."""
    h = ui_app
    h.app.dialogs.shutdown()
    reader = h.runtime.singletons["Reader"]
    reader.open_paths([str(samples.standard_text(tmp_path / "Vertrag.pdf", pages=2))])
    assert wait_until(lambda: reader.current is not None and h.item("readerRibbon_start") is not None, 30)
    pump(0.5)
    doc = reader.current
    ribbon = h.item("readerToolbar")
    for key in ("file", "comment", "edit", "pages", "view", "start"):
        QTest.mouseClick(h.window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                         h.item("readerRibbon_" + key).mapToScene(QPointF(10, 10)).toPoint())
        pump(0.1)
        assert ribbon.property("ribbon") == key
    for name in ("readerSave", "readerPrint", "readerUndo", "readerRedo", "readerAllTools", "readerPageField", "readerSidebarToggle"):
        assert h.item(name) is not None, name
    assert h.item("readerQuickTools") is None and h.item("readerLeftRail") is None
    button = h.item("readerToolAddText")
    QTest.mouseClick(h.window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, button.mapToScene(QPointF(8, 8)).toPoint())
    pump(0.2)
    assert doc.tool == "addText" and button.property("checked")
    # Seitenleiste über das Menüband zu und wieder auf
    reader.showLeftPanel("thumbs")
    toggle = h.item("readerSidebarToggle")
    QTest.mouseClick(h.window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, toggle.mapToScene(QPointF(8, 8)).toPoint())
    pump(0.2)
    assert reader.leftPanel == ""
    QTest.mouseClick(h.window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, toggle.mapToScene(QPointF(8, 8)).toPoint())
    pump(0.2)
    assert reader.leftPanel == "thumbs"
