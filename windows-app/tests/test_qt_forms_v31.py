"""Qt-Oberfläche 3.1: »Formular gestalten« – Felder anlegen (Rahmen aufziehen, klicken, Rechtsklick »… hier«),
Option hinzufügen, verschieben, Größe ändern, duplizieren, löschen und rückgängig machen, Eigenschaften im Dialog;
danach mit »Formular ausfüllen« ausfüllen, speichern und erneut öffnen.

Bedient wird wie von Hand (Werkzeugleiste, Maus, Tastatur, Kontextmenü, Dialog). Alle PDFs sind künstlich
(``editorsamples``). Nach jedem Test darf die QML-Engine keine Meldung ausgegeben haben (Fixture ``ui_app``).
"""

from __future__ import annotations

from pathlib import Path

import pikepdf
import pytest
from PySide6.QtCore import QObject, QPoint, Qt, QTimer
from PySide6.QtTest import QTest

import editorsamples as samples
from conftest import pump, wait_until
from test_qt_reader import click, drag, key, open_pdf, page_item, page_point, right_click, settle, type_text, window_point
from tools.pdf_editor import forms
from tools.pdf_editor.document import EditorDocument

CTRL = Qt.KeyboardModifier.ControlModifier
LEFT = Qt.MouseButton.LeftButton
NO_MOD = Qt.KeyboardModifier.NoModifier


@pytest.fixture
def reader_app(ui_app):
    ui_app.app.dialogs.shutdown()
    ui_app.navigate("reader", 0.3)
    return ui_app


# --- Hilfen ----------------------------------------------------------------------------------------------------
def press(h, name: str) -> None:
    item = next((entry for entry in h.items(name) if entry.isVisible()), None)
    assert item is not None, name
    assert item.property("enabled"), name
    click(h, window_point(item, item.width() / 2, item.height() / 2))


def widgets(doc, name: str | None = None) -> list[dict]:
    found = [item for items in doc.designPages.values() for item in items]
    return found if name is None else [item for item in found if item["name"] == name]


def one(doc, name: str) -> dict:
    found = widgets(doc, name)
    assert len(found) == 1, (name, [item["name"] for item in widgets(doc)])
    return found[0]


def center(view) -> tuple[float, float]:
    return (view[0] + view[2]) / 2, (view[1] + view[3]) / 2


def changed(h, doc, check, timeout: float = 20) -> None:
    """Warten, bis die Änderung fertig und das Formular neu gelesen ist."""
    settle(h)
    assert wait_until(lambda: check(), timeout), "Formular nicht wie erwartet"
    pump(0.1)


def design_mode(h, doc) -> None:
    """Werkzeug »Formular gestalten« über die Werkzeugleiste (Pfeil neben »Formular«)."""
    press(h, "readerFormMenu")
    pump(0.3)
    press(h, "readerToolFormDesign")
    pump(0.3)
    assert doc.tool == "formDesign"
    assert wait_until(lambda: h.item("readerFormKind_text") is not None and h.item("readerFormKind_text").isVisible(), 5)


def menu_entries(owner, name: str):
    """(Menü, Einträge Text → Eintrag). Menü und ``owner`` beim Aufrufer behalten: PySide verwirft die
    Python-Objekte der Kinder, sobald das des Elternobjekts freigegeben ist."""
    menus = [obj for obj in owner.findChildren(QObject) if obj.objectName() == name]
    assert len(menus) == 1, name
    return menus[0], {obj.property("text"): obj for obj in menus[0].findChildren(QObject) if obj.property("text") and obj.property("enabled") is not None and hasattr(obj, "mapToScene")}


def answer_dialog(h, kind: str, value: dict, seen: list | None = None, button: str = "primary") -> None:
    """Den echten (blockierenden) Dialog ``kind`` abwarten, seine Anfrage merken und antworten."""
    def respond() -> None:
        service = h.app.dialogs
        if not service.open or service.request.get("kind") != kind:
            QTimer.singleShot(50, respond)
            return
        pump(0.2)
        if seen is not None:
            seen.append({"request": dict(service.request), "name": h.item("fieldName").property("text") if h.item("fieldName") else None,
                         "options": h.item("fieldOptions").isVisible() if h.item("fieldOptions") else None,
                         "export": h.item("fieldExport").isVisible() if h.item("fieldExport") else None})
        service.answer(service.request["id"], button, value)

    QTimer.singleShot(50, respond)


# --- Anlegen, verschieben, Größe, duplizieren, löschen ----------------------------------------------------------------
def test_create_move_resize_duplicate_delete_and_undo(reader_app, tmp_path: Path) -> None:
    """Textfeld per Rahmen, Kontrollkästchen per Klick, Optionsgruppe mit zweiter Option, Dropdown per
    Rechtsklick »Dropdown hier«; Ziehen verschiebt, die Ecke ändert die Größe, Strg+D dupliziert, Entf löscht,
    Strg+Z holt es zurück."""
    h = reader_app
    doc = open_pdf(h, samples.standard_text(tmp_path / "leer.pdf"), whole_page=True)
    design_mode(h, doc)
    # Textfeld: Feldart wählen, Rahmen aufziehen
    press(h, "readerFormKind_text")
    assert doc.formKind == "text"
    drag(h, page_point(h, 0, 72, 200), page_point(h, 0, 272, 222))
    changed(h, doc, lambda: len(widgets(doc, "Textfeld 1")) == 1)
    text = one(doc, "Textfeld 1")
    assert text["view"] == pytest.approx([72, 200, 272, 222], abs=1.5) and text["kind"] == "text"
    assert doc.fieldSelection.get("key") == text["key"] and doc.formKind == ""  # gewählt, danach wieder »Auswählen«
    assert doc.undoText == "Textfeld hinzufügen"
    # Kontrollkästchen: Klick legt es in Standardgröße an
    press(h, "readerFormKind_checkbox")
    click(h, page_point(h, 0, 72, 260))
    changed(h, doc, lambda: len(widgets(doc, "Kontrollkästchen 1")) == 1)
    box = one(doc, "Kontrollkästchen 1")
    assert box["view"][2] - box["view"][0] == pytest.approx(14, abs=1) and box["view"][3] - box["view"][1] == pytest.approx(14, abs=1)
    # Optionsgruppe mit einer zweiten Option (Leiste »Option hinzufügen«)
    press(h, "readerFormKind_radio")
    click(h, page_point(h, 0, 72, 300))
    changed(h, doc, lambda: len(widgets(doc, "Optionsgruppe 1")) == 1)
    press(h, "readerFieldAddOption")
    changed(h, doc, lambda: len(widgets(doc, "Optionsgruppe 1")) == 2)
    assert sorted(item["export"] for item in widgets(doc, "Optionsgruppe 1")) == ["Option 1", "Option 2"]
    # Dropdown über das Kontextmenü einer freien Stelle
    right_click(h, page_point(h, 0, 320, 200))
    item = page_item(h, 0)
    _menu, entries = menu_entries(item, "readerFieldPageMenu")
    assert {"Textfeld hier", "Kontrollkästchen hier", "Optionsfeld hier", "Dropdown hier", "Liste hier"} <= set(entries)
    entry = entries["Dropdown hier"]
    click(h, window_point(entry, entry.width() / 2, entry.height() / 2))
    changed(h, doc, lambda: len(widgets(doc, "Auswahl 1")) == 1)
    assert one(doc, "Auswahl 1")["view"][0] == pytest.approx(320, abs=1.5)
    # Verschieben: Textfeld ziehen
    text = one(doc, "Textfeld 1")
    u, v = center(text["view"])
    drag(h, page_point(h, 0, u, v), page_point(h, 0, u + 20, v + 30), steps=10)
    changed(h, doc, lambda: one(doc, "Textfeld 1")["view"][0] == pytest.approx(text["view"][0] + 20, abs=1.5))
    moved = one(doc, "Textfeld 1")["view"]
    assert moved[1] == pytest.approx(text["view"][1] + 30, abs=1.5) and doc.undoText == "Feld verschieben"
    # Größe: rechte untere Ecke ziehen (frei)
    handles = [item for item in h.items("readerDesignHandle") if item.isVisible()]
    assert len(handles) == 4
    drag(h, page_point(h, 0, moved[2], moved[3]), page_point(h, 0, moved[2] + 50, moved[3] + 10), steps=10)
    changed(h, doc, lambda: one(doc, "Textfeld 1")["view"][2] == pytest.approx(moved[2] + 50, abs=1.5))
    assert one(doc, "Textfeld 1")["view"][3] == pytest.approx(moved[3] + 10, abs=1.5) and doc.undoText == "Feldgröße ändern"
    # Duplizieren (Strg+D) und Löschen (Entf), dann Rückgängig
    box = one(doc, "Kontrollkästchen 1")
    click(h, page_point(h, 0, *center(box["view"])))
    assert doc.fieldSelection.get("key") == box["key"]
    key(h, Qt.Key.Key_D, CTRL)
    changed(h, doc, lambda: len(widgets(doc, "Kontrollkästchen 2")) == 1)
    copy = one(doc, "Kontrollkästchen 2")
    assert doc.fieldSelection.get("key") == copy["key"] and copy["view"][1] > box["view"][3]  # darunter, gewählt
    key(h, Qt.Key.Key_Delete)
    changed(h, doc, lambda: not widgets(doc, "Kontrollkästchen 2"))
    assert doc.undoText == "Feld löschen" and doc.fieldSelection == {}
    key(h, Qt.Key.Key_Z, CTRL)
    changed(h, doc, lambda: len(widgets(doc, "Kontrollkästchen 2")) == 1)
    # Pfeiltasten: ein Schritt für mehrere Tastendrücke
    click(h, page_point(h, 0, *center(one(doc, "Kontrollkästchen 2")["view"])))
    before = one(doc, "Kontrollkästchen 2")["view"]
    for _ in range(3):
        key(h, Qt.Key.Key_Right)
    changed(h, doc, lambda: one(doc, "Kontrollkästchen 2")["view"][0] == pytest.approx(before[0] + 3, abs=0.6), timeout=10)
    assert doc.undoText == "Feld verschieben"
    # Esc: erst die Auswahl, dann das Werkzeug
    key(h, Qt.Key.Key_Escape)
    assert doc.fieldSelection == {} and doc.tool == "formDesign"
    key(h, Qt.Key.Key_Escape)
    assert doc.tool == "select"


# --- Eigenschaften, ausfüllen, speichern ---------------------------------------------------------------------------
def test_properties_dialog_then_fill_save_and_reopen(reader_app, tmp_path: Path, monkeypatch) -> None:
    """Doppelklick öffnet »Feldeigenschaften« (Name, Pflichtfeld, Schriftgröße; beim Dropdown die Optionen);
    danach lassen sich die neuen Felder ausfüllen – gespeichert und neu geöffnet sind Werte und Namen da."""
    from qtapp import dialogs

    monkeypatch.setattr(dialogs, "AUTO_ANSWER", None)  # der echte Dialog – beantwortet von ``answer_dialog``
    h = reader_app
    path = samples.standard_text(tmp_path / "formular.pdf")
    doc = open_pdf(h, path, whole_page=True)
    design_mode(h, doc)
    press(h, "readerFormKind_text")
    drag(h, page_point(h, 0, 72, 200), page_point(h, 0, 272, 222))
    changed(h, doc, lambda: len(widgets(doc, "Textfeld 1")) == 1)
    press(h, "readerFormKind_combo")
    drag(h, page_point(h, 0, 72, 260), page_point(h, 0, 222, 282))
    changed(h, doc, lambda: len(widgets(doc, "Auswahl 1")) == 1)
    press(h, "readerFormKind_checkbox")
    click(h, page_point(h, 0, 72, 320))
    changed(h, doc, lambda: len(widgets(doc, "Kontrollkästchen 1")) == 1)
    # Textfeld: Doppelklick → Eigenschaften
    seen: list = []
    answer_dialog(h, "form_field", {"name": "Vorname", "tooltip": "Vorname laut Ausweis", "required": True, "readOnly": False, "multiline": False, "maxLength": 40,
                                    "fontSize": 12, "align": "left", "options": [], "export": "", "border": True, "background": True}, seen)
    u, v = center(one(doc, "Textfeld 1")["view"])
    QTest.mouseDClick(h.window, LEFT, NO_MOD, page_point(h, 0, u, v))
    changed(h, doc, lambda: len(widgets(doc, "Vorname")) == 1)
    assert seen and seen[0]["name"] == "Textfeld 1" and seen[0]["options"] is False and seen[0]["export"] is False
    field = one(doc, "Vorname")
    assert field["required"] and field["tooltip"] == "Vorname laut Ausweis" and field["maxLength"] == 40 and field["fontSize"] == 12
    assert doc.undoText == "Feldeigenschaften ändern"
    # Dropdown: Optionen über die Leiste »Eigenschaften …«
    click(h, page_point(h, 0, *center(one(doc, "Auswahl 1")["view"])))
    seen.clear()
    answer_dialog(h, "form_field", {"name": "Farbe", "tooltip": "", "required": False, "readOnly": False, "fontSize": 0, "align": "left",
                                    "options": ["Rot", "Grün", "Blau"], "export": "", "border": True, "background": True}, seen)
    press(h, "readerFieldProperties")
    changed(h, doc, lambda: widgets(doc, "Farbe") and one(doc, "Farbe")["options"] == ["Rot", "Grün", "Blau"])
    assert seen and seen[0]["options"] is True
    # Kontrollkästchen: Exportwert
    click(h, page_point(h, 0, *center(one(doc, "Kontrollkästchen 1")["view"])))
    answer_dialog(h, "form_field", {"name": "Zustimmung", "tooltip": "", "required": False, "readOnly": False, "export": "Ja, gelesen", "border": True, "background": True})
    key(h, Qt.Key.Key_Return)
    changed(h, doc, lambda: widgets(doc, "Zustimmung") and one(doc, "Zustimmung")["export"] == "Ja, gelesen")
    # Abbrechen ändert nichts
    undo = doc.undoText
    answer_dialog(h, "form_field", {"name": "Anders"}, button="close")
    press(h, "readerFieldProperties")
    settle(h)
    pump(0.3)
    assert doc.undoText == undo and widgets(doc, "Zustimmung")
    # Ausfüllen mit »Formular ausfüllen«
    doc.setTool("form")
    assert wait_until(lambda: len([w for items in doc.fieldPages.values() for w in items]) == 3, 20)
    check = next(w for w in doc.fieldPages["0"] if w["name"] == "Zustimmung")
    click(h, page_point(h, 0, *center(check["view"])))
    settle(h)
    name = next(w for w in doc.fieldPages["0"] if w["name"] == "Vorname")
    click(h, page_point(h, 0, *center(name["view"])))
    pump(0.2)
    type_text(h, "Erika")
    key(h, Qt.Key.Key_Return)
    settle(h)
    assert wait_until(lambda: {f["name"]: f["value"] for f in doc.fields}.get("Vorname") == "Erika", 10)
    doc.saveDocument()
    settle(h)
    assert wait_until(lambda: not doc.dirty, 30)
    reopened = EditorDocument.open(path)
    try:
        values = {info.name: info for info in forms.list_fields(reopened)}
        assert values["Vorname"].value == "Erika" and values["Vorname"].required and values["Vorname"].max_length == 40
        assert values["Zustimmung"].value is True and values["Zustimmung"].on_values == ("/Ja, gelesen",)
        assert [display for _export, display in values["Farbe"].options] == ["Rot", "Grün", "Blau"]
    finally:
        reopened.close()
    with pikepdf.open(path) as pdf:
        assert pdf.check_pdf_syntax() == []


def test_xfa_form_cannot_be_designed(reader_app, tmp_path: Path) -> None:
    """XFA-Formular: Anlegen wird mit einer verständlichen Meldung abgelehnt, nichts ändert sich."""
    h = reader_app
    path = samples.form(tmp_path / "xfa.pdf")
    with pikepdf.open(path, allow_overwriting_input=True) as pdf:
        pdf.Root.AcroForm.XFA = pdf.make_stream(b"<xdp:xdp xmlns:xdp='http://ns.adobe.com/xdp/'/>")
        pdf.save(path)
    doc = open_pdf(h, path, whole_page=True)
    design_mode(h, doc)
    assert wait_until(lambda: len(widgets(doc)) >= 5, 20)  # vorhandene Felder werden gezeigt
    press(h, "readerFormKind_text")
    drag(h, page_point(h, 0, 300, 400), page_point(h, 0, 450, 422))
    settle(h)
    notice = h.app.notices.get("reader")
    assert notice.title == "Nicht möglich" and "XFA" in notice.message
    assert not doc.dirty and doc.undoText == ""
