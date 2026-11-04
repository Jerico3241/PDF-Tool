"""Tastenkürzel wie in Word, Excel und PowerPoint (seit 5.0 Beta 10).

In Texten, Tabellen und Präsentationen gehören Strg+1 … Strg+8 und Strg+Eingabe dem Dokument (Zeilenabstand,
Seitenumbruch, Durchgestrichen …) – vorher sprangen sie zur Startseite, zu den Vertragsübersichten oder zum PDF Reader.
Die Tests brauchen LibreOffice (``soffice`` im PATH); ohne werden sie übersprungen."""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest
from PySide6.QtCore import QEvent, QObject, QPointF, Qt
from PySide6.QtGui import QGuiApplication, QKeyEvent
from PySide6.QtTest import QTest

from conftest import wait_until
from qtutil import pump

CTRL = Qt.KeyboardModifier.ControlModifier
SHIFT = Qt.KeyboardModifier.ShiftModifier


def _office_available() -> bool:
    from tools.text import engine

    return engine.available()


needs_office = pytest.mark.skipif(not _office_available(), reason="LibreOffice fehlt – Office-Kürzel nicht prüfbar")


def _key(h, key, modifiers=Qt.KeyboardModifier.NoModifier, text: str = "") -> None:
    for kind in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease):
        QGuiApplication.sendEvent(h.window, QKeyEvent(kind, key, modifiers, text))
    pump(0.05)


def _type(h, text: str) -> None:
    for char in text:
        key = ord(char.upper()) if char.isascii() and char.isalnum() else Qt.Key.Key_unknown
        _key(h, key, Qt.KeyboardModifier.NoModifier, char)


def _open(h, make: str, kind: str):
    reader = h.runtime.singletons["Reader"]
    getattr(reader, make)()
    assert wait_until(lambda: reader.current is not None and reader.current.kind == kind and getattr(reader.current, "ready", False), 180)
    pump(1.0)
    return reader.current


def _click(h, name: str, x: float = 300, y: float = 120) -> None:
    item = h.item(name)
    QTest.mouseClick(h.window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, item.mapToScene(QPointF(x, y)).toPoint())
    pump(0.3)
    assert item.hasActiveFocus()


def test_office_keys_table() -> None:
    """Die Zuordnung ohne LibreOffice: Strg+1/2/5 nur im Text (in Präsentationen tun sie nichts Fremdes)."""
    from qtapp.text.canvas import office_command

    assert office_command("text", Qt.Key.Key_2, False) == ".uno:SpacePara2"
    assert office_command("text", Qt.Key.Key_5, False) == ".uno:SpacePara15"
    assert office_command("praesentation", Qt.Key.Key_2, False) == ""
    assert office_command("praesentation", Qt.Key.Key_F, True) == ".uno:Bold"
    assert office_command("text", Qt.Key.Key_M, False) == ".uno:IncrementIndent"
    assert office_command("praesentation", Qt.Key.Key_M, False) == ""  # PowerPoint: neue Folie


@needs_office
def test_text_keys_like_word(ui_app, tmp_path: Path) -> None:
    """Text: Strg+1/2 bleiben im Dokument und stellen den Zeilenabstand ein, Strg+Eingabe macht einen Seitenumbruch,
    Strg+Umschalt+F macht fett, Strg+H öffnet Suchen und Ersetzen."""
    h = ui_app
    h.app.dialogs.shutdown()
    doc = _open(h, "newText", "text")
    _click(h, "textCanvas")
    _type(h, "Zeile")
    _key(h, Qt.Key.Key_1, CTRL, "1")
    _key(h, Qt.Key.Key_2, CTRL, "2")
    pump(0.5)
    assert h.app.currentPage == "reader" and h.runtime.singletons["Reader"].current is doc, "Strg+1/2 verlassen das Dokument nicht"
    _key(h, Qt.Key.Key_Return, CTRL)
    assert wait_until(lambda: doc.pageCount == 2, 20), "Strg+Eingabe: Seitenumbruch"
    _key(h, Qt.Key.Key_F, CTRL | SHIFT, "F")
    _type(h, "Fett")
    assert wait_until(lambda: doc.bold, 10)
    _key(h, Qt.Key.Key_H, CTRL, "h")
    bar = h.item("textFindBar")
    assert wait_until(lambda: bar.isVisible() and bar.property("replacing"), 5)
    target = tmp_path / "Abstand.docx"
    doc.save(str(target))
    assert wait_until(lambda: not doc.saving and target.exists(), 30)
    xml = zipfile.ZipFile(target).read("word/document.xml").decode("utf-8")
    assert 'w:line="480"' in xml, "Strg+2: doppelter Zeilenabstand"
    assert "w:br" in xml and 'w:type="page"' in xml or "pageBreakBefore" in xml


@needs_office
def test_slides_keys_like_powerpoint(ui_app) -> None:
    """Präsentation: Strg+M neue Folie, Strg+D Folie duplizieren, Strg+1 verlässt die Präsentation nicht."""
    h = ui_app
    h.app.dialogs.shutdown()
    doc = _open(h, "newSlides", "praesentation")
    canvas = h.item("slidesCanvas")
    canvas.forceActiveFocus()
    pump(0.2)
    _key(h, Qt.Key.Key_M, CTRL, "m")
    assert wait_until(lambda: doc.slideCount == 2, 20)
    canvas.forceActiveFocus()
    _key(h, Qt.Key.Key_D, CTRL, "d")
    assert wait_until(lambda: doc.slideCount == 3, 20)
    _key(h, Qt.Key.Key_1, CTRL, "1")
    pump(0.3)
    assert h.app.currentPage == "reader"


@needs_office
def test_sheet_keys_like_excel(ui_app) -> None:
    """Tabelle: Strg+Umschalt+4 Währung, Strg+5 durchgestrichen, Strg++ fügt eine Zeile ein, Strg+N macht in der Tabelle
    eine neue Tabelle, Strg+1 bleibt in der Tabelle."""
    h = ui_app
    h.app.dialogs.shutdown()
    sheet = _open(h, "newSheet", "tabelle")
    assert [entry["name"] for entry in sheet.sheets] == ["Tabelle1"], "Blattname wie in Excel"
    grid = h.item("sheetGrid")
    grid.forceActiveFocus()
    pump(0.2)
    _type(h, "5")
    _key(h, Qt.Key.Key_Return)
    _key(h, Qt.Key.Key_Up)
    assert wait_until(lambda: sheet.cellName == "A1", 10)
    _key(h, Qt.Key.Key_Dollar, CTRL | SHIFT, "$")
    assert wait_until(lambda: sheet.formatKind == "currency", 10)
    _key(h, Qt.Key.Key_5, CTRL, "5")
    assert wait_until(lambda: bool(sheet.cellStyle.get("strike")), 10)
    assert wait_until(lambda: sheet.cellInput == "5", 10)
    _key(h, Qt.Key.Key_Plus, CTRL, "+")
    assert wait_until(lambda: sheet.cellInput == "", 10), "Strg++: neue leere Zeile über der 5"
    _key(h, Qt.Key.Key_Down)
    assert wait_until(lambda: sheet.cellName == "A2" and sheet.cellInput == "5", 10)
    _key(h, Qt.Key.Key_1, CTRL, "1")
    pump(0.3)
    assert h.app.currentPage == "reader" and h.runtime.singletons["Reader"].current is sheet
