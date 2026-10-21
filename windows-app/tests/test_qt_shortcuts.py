"""Tastenkürzel (seit 4.0.0-beta.5): Verzeichnis, eigene Kürzel, Übersicht, Statuszeile und Kurzinfos."""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

import editorsamples as samples
from conftest import pump, wait_until
from test_qt_reader import open_pdf, reader

CTRL, SHIFT = Qt.KeyboardModifier.ControlModifier, Qt.KeyboardModifier.ShiftModifier


class FakeApp:
    def __init__(self) -> None:
        self.saved = 0
        self.hints = 0
        self.dialogs = None

    def register_config(self, _part) -> None:
        pass

    def schedule_save(self) -> None:
        self.saved += 1

    def refresh_hint(self) -> None:
        self.hints += 1


@pytest.fixture
def controller(qt_application):
    from qtapp.shortcuts import ShortcutsController

    return ShortcutsController(FakeApp(), {})


def test_display_and_rules(qt_application) -> None:
    from qtapp import shortcuts

    assert shortcuts.display("Ctrl+Shift+S") == "Strg+Umschalt+S"
    assert shortcuts.display("Ctrl++") == "Strg++" and shortcuts.display("Ctrl+-") == "Strg+−"
    assert shortcuts.display("Del") == "Entf" and shortcuts.display("Ctrl+Return") == "Strg+Eingabe"
    assert shortcuts.normalize("ctrl+shift+p") == "Ctrl+Shift+P" and shortcuts.normalize("Ctrl+K, Ctrl+L") == ""
    assert shortcuts.problem("Ctrl+K") == "" and shortcuts.problem("F7") == "" and shortcuts.problem("Alt+K") == ""
    assert "Strg oder Alt" in shortcuts.problem("K") and "Strg oder Alt" in shortcuts.problem("Shift+K")
    assert "Windows" in shortcuts.problem("Alt+F4")
    assert "AltGr" in shortcuts.problem("Ctrl+Alt+Q")  # @ auf deutschen Tastaturen
    assert "Textfelder" in shortcuts.problem("Ctrl+V")
    assert "fest vergeben" in shortcuts.problem("Esc")
    # jedes Standardkürzel ist erlaubt und gehört genau einem Befehl
    seen: dict[str, str] = {}
    for command in shortcuts.COMMANDS:
        for sequence in command.defaults:
            assert shortcuts.normalize(sequence) == sequence, sequence
            assert shortcuts.problem(sequence) == "", sequence
            assert sequence not in seen, f"{sequence}: {seen.get(sequence)} und {command.key}"
            seen[sequence] = command.key


def test_assign_moves_a_taken_shortcut_and_reset_takes_it_back(controller) -> None:
    c = controller
    assert c.keys["reader.print"] == ["Ctrl+P"] and c.hints["reader.print"] == " (Strg+P)"
    note = c.assign("reader.speech", "Ctrl+P")
    assert note == "Strg+P war »Drucken« zugeordnet – dort entfernt."
    assert c.keys["reader.speech"] == ["Ctrl+P"] and c.keys["reader.print"] == [] and c.hints["reader.print"] == ""
    assert c.assign("reader.print", "K").startswith("Bitte eine Kombination")
    assert c.keys["reader.print"] == []
    assert c.assign("reader.print", "Alt+P") == ""
    assert c.labels["reader.print"] == "Alt+P"
    # Standard wiederherstellen: »Vorlesen« gibt Strg+P ab
    c.reset("reader.print")
    assert c.keys["reader.print"] == ["Ctrl+P"] and c.keys["reader.speech"] == []
    c.reset("reader.speech")
    assert c.keys["reader.speech"] == ["Ctrl+Shift+Y"]
    c.clear("reader.redo")
    assert c.keys["reader.redo"] == [] and c.config()["tastenkuerzel"] == {"reader.redo": []}
    c.resetAll()
    assert c.config()["tastenkuerzel"] is None and c.keys["reader.redo"] == ["Ctrl+Y", "Ctrl+Shift+Z"]
    overview = {item["key"]: item for group in c.groups for item in group["items"]}
    assert overview["reader.redo"]["keys"] == ["Strg+Y", "Strg+Umschalt+Z"] and not overview["reader.redo"]["custom"]
    assert any(fixed["keys"] == "Strg+Mausrad" for group in c.groups for fixed in group["fixed"])


def test_custom_shortcuts_survive_a_restart_and_bad_ones_are_dropped(qt_application) -> None:
    from qtapp.shortcuts import ShortcutsController

    stored = {"tastenkuerzel": {"reader.print": ["Ctrl+Shift+P"], "reader.save": ["K", "Ctrl+V"], "gibtsnicht": ["Ctrl+Q"]}}
    c = ShortcutsController(FakeApp(), stored)
    assert c.keys["reader.print"] == ["Ctrl+Shift+P"] and c.keys["reader.save"] == []
    assert "gibtsnicht" not in c.keys


def test_status_line_follows_custom_shortcuts(controller) -> None:
    c = controller
    hint = "Strg+O Öffnen   ·   Strg+F Suchen   ·   Strg+S Speichern   ·   Strg+P Drucken"
    assert c.localize(hint) == hint
    c.assign("app.open", "Ctrl+Shift+O")
    c.clear("reader.print")
    assert c.localize(hint) == "Strg+Umschalt+O Öffnen   ·   Strg+F Suchen   ·   Strg+S Speichern"
    assert c.app.hints >= 2  # die Statuszeile wird neu aufgebaut


def test_status_line_follows_custom_shortcuts_in_english(controller, monkeypatch) -> None:
    """Auf Englisch zeigte die Statuszeile die alten Standardkürzel und auch gelöschte (bis 4.0 Beta 8)."""
    import i18n

    monkeypatch.setattr(i18n, "language", lambda: "en")
    c = controller
    hint = "Strg+O Öffnen   ·   Strg+F Suchen   ·   Strg+P Drucken"
    c.assign("app.open", "Ctrl+K")
    c.clear("reader.print")
    assert c.localize(hint) == "Strg+K Öffnen   ·   Strg+F Suchen"  # deutsch, die Übersetzung folgt danach
    assert c.labels["app.open"] == "Ctrl+K"


def test_overview_changes_a_shortcut_that_works_at_once(ui_app, tmp_path: Path, monkeypatch) -> None:
    from qtapp import dialogs
    from qtapp.reader.document import DocumentController

    monkeypatch.setattr(dialogs, "AUTO_ANSWER", None)
    h = ui_app
    h.app.dialogs.shutdown()
    h.navigate("reader", 0.3)
    printed: list = []
    monkeypatch.setattr(DocumentController, "printDocument", lambda self: printed.append(self.name))
    open_pdf(h, samples.standard_text(tmp_path / "kuerzel.pdf"))
    QTest.keyClick(h.window, Qt.Key.Key_F1, CTRL)
    assert wait_until(lambda: (h.app.dialogs.request or {}).get("kind") == "shortcuts", 5)
    pump(0.3)
    change = h.item("shortcutChange_reader.print")
    assert change is not None and h.item("shortcutKeys_reader.print").property("text") == "Strg+P"
    change.clicked.emit()
    pump(0.1)
    assert "Tasten drücken" in h.item("shortcutKeys_reader.print").property("text")
    QTest.keyClick(h.window, Qt.Key.Key_Escape)  # bricht nur das Ändern ab, nicht die Übersicht
    pump(0.1)
    assert h.app.dialogs.open and h.item("shortcutKeys_reader.print").property("text") == "Strg+P"
    change.clicked.emit()
    pump(0.1)
    QTest.keyClick(h.window, Qt.Key.Key_K)  # ohne Strg: abgelehnt, wartet weiter
    pump(0.1)
    assert "Strg oder Alt" in h.item("shortcutNote_reader.print").property("text")
    QTest.keyClick(h.window, Qt.Key.Key_D, CTRL | SHIFT)
    pump(0.2)
    assert h.item("shortcutKeys_reader.print").property("text") == "Strg+Umschalt+D"
    assert h.item("shortcutReset_reader.print").property("enabled")
    h.app.dialogs.answer(h.app.dialogs.request["id"], "close", {})
    pump(0.3)
    # Neu: Strg+Umschalt+D druckt, Strg+P nicht mehr; Kurzinfo nennt das neue Kürzel
    h.item("readerView").forceActiveFocus()
    QTest.keyClick(h.window, Qt.Key.Key_P, CTRL)
    pump(0.2)
    assert printed == []
    QTest.keyClick(h.window, Qt.Key.Key_D, CTRL | SHIFT)
    assert wait_until(lambda: printed == ["kuerzel.pdf"], 5)
    assert h.item("readerPrint").property("tip") == "Drucken (Strg+Umschalt+D)"
    assert h.runtime.shortcuts.config()["tastenkuerzel"] == {"reader.print": ["Ctrl+Shift+D"]}
    assert reader(h).current is not None
