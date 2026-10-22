"""Tastenkürzel (QML: ``Shortcuts``, seit 4.0 Beta 5): alle Befehle mit Tastenkürzel an einer Stelle, eigene
Kürzel und die Übersicht (Einstellungen › Tastenkürzel, Strg+F1).

Jeder Befehl hat eine feste Kennung (``reader.save``) und Standardkürzel. Eigene Kürzel speichert Novadesk nur als
Abweichung (``tastenkuerzel`` in gui-config.json); »Zurücksetzen« entfernt sie. Ein Kürzel gehört immer genau einem
Befehl: wer es neu vergibt, nimmt es dem bisherigen Befehl weg (die Übersicht sagt, welchem).

QML liest ``keys`` (Kennung → Tastenfolgen für ``Shortcut.sequences``, Qt-Schreibweise »Ctrl+S«) und ``hints``
(Kennung → » (Strg+S)« für Kurzinfos und Menüs, leer ohne Kürzel). Tasten wie Esc, Pfeile oder Bild ↑/↓ sind fest
(``FIXED``) und stehen nur zur Information in der Übersicht.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from PySide6.QtCore import QObject, Qt, Slot
from PySide6.QtGui import QKeySequence

import i18n

from .base import Observable, prop

CONFIG_KEY = "tastenkuerzel"
GENERAL, READER = "Allgemein", "PDF Reader & Editor"


@dataclass(frozen=True)
class Command:
    key: str
    group: str
    label: str
    defaults: tuple[str, ...]


COMMANDS = (
    Command("app.new", GENERAL, "Neue Tabelle", ("Ctrl+N",)),
    Command("app.open", GENERAL, "Datei öffnen", ("Ctrl+O",)),
    Command("app.find", GENERAL, "Suchen", ("Ctrl+F",)),
    Command("app.primary", GENERAL, "Hauptbefehl der Seite (z. B. PDF erstellen)", ("Ctrl+Return", "Ctrl+Enter")),
    Command("app.help", GENERAL, "Kurzanleitung", ("F1",)),
    Command("app.shortcuts", GENERAL, "Tastenkürzel anzeigen", ("Ctrl+F1",)),
    Command("app.home", GENERAL, "Start", ("Ctrl+1",)),
    Command("app.contracts", GENERAL, "Vertragsübersichten", ("Ctrl+2",)),
    Command("app.repair", GENERAL, "PDF reparieren", ("Ctrl+3",)),
    Command("app.settings", GENERAL, "Einstellungen", ("Ctrl+4",)),
    Command("app.reader", GENERAL, "PDF Reader & Editor", ("Ctrl+5",)),
    Command("app.actions", GENERAL, "Stapel-Aktionen", ("Ctrl+6",)),
    Command("app.closeTab", GENERAL, "Tab bzw. Dokument schließen", ("Ctrl+W",)),
    Command("app.reopen", GENERAL, "Geschlossenen Tab wieder öffnen", ("Ctrl+Shift+T",)),
    Command("reader.save", READER, "Speichern", ("Ctrl+S",)),
    Command("reader.saveAs", READER, "Speichern unter", ("Ctrl+Shift+S",)),
    Command("reader.print", READER, "Drucken", ("Ctrl+P",)),
    Command("reader.undo", READER, "Rückgängig", ("Ctrl+Z",)),
    Command("reader.redo", READER, "Wiederholen", ("Ctrl+Y", "Ctrl+Shift+Z")),
    Command("reader.copy", READER, "Ausgewählten Text kopieren", ("Ctrl+C",)),
    Command("reader.selectAll", READER, "Alles auswählen (Seite)", ("Ctrl+A",)),
    Command("reader.delete", READER, "Ausgewähltes Bild bzw. Kommentar löschen", ("Del",)),
    Command("reader.nextHit", READER, "Nächster Treffer", ("F3",)),
    Command("reader.previousHit", READER, "Vorheriger Treffer", ("Shift+F3",)),
    Command("reader.goToPage", READER, "Gehe zu Seite", ("Ctrl+G",)),
    Command("reader.zoomIn", READER, "Vergrößern", ("Ctrl++", "Ctrl+=")),
    Command("reader.zoomOut", READER, "Verkleinern", ("Ctrl+-",)),
    Command("reader.fitPage", READER, "Ganze Seite", ("Ctrl+0",)),
    Command("reader.fullScreen", READER, "Vollbild", ("F11",)),
    Command("reader.present", READER, "Präsentation", ("F5",)),
    Command("reader.speech", READER, "Vorlesen starten bzw. beenden", ("Ctrl+Shift+Y",)),
    Command("reader.nextTab", READER, "Nächstes Dokument", ("Ctrl+Tab",)),
    Command("reader.previousTab", READER, "Vorheriges Dokument", ("Ctrl+Shift+Tab",)),
)
BY_KEY = {command.key: command for command in COMMANDS}

# Feste Tasten (nur Übersicht): (Bereich, Tasten, Bedeutung)
FIXED = (
    (GENERAL, "Esc", "Dialog schließen, Auswahl aufheben, Vollbild bzw. Vorlesen beenden"),
    (GENERAL, "Strg+Umschalt+← / →", "Tab verschieben (im fokussierten Tab)"),
    (READER, "Bild ↑ / Bild ↓, ← / →", "Vorige bzw. nächste Seite"),
    (READER, "Pos1 / Ende", "Erste bzw. letzte Seite"),
    (READER, "Strg+Mausrad", "Zoomen um den Mauszeiger"),
    (READER, "Doppelklick", "Wort auswählen"),
    (READER, "Strg+X / Strg+V / Strg+D", "Objekte bzw. Seiten ausschneiden, einfügen, duplizieren"),
    (READER, "Eingabe / F2", "Ausgewähltes Objekt, Feld oder Lesezeichen bearbeiten"),
)

# Qt-Schreibweise → Anzeige (deutsche Tastatur)
_NAMES = {
    "Ctrl": "Strg", "Shift": "Umschalt", "Alt": "Alt", "Meta": "Win", "Del": "Entf", "Ins": "Einfg", "Return": "Eingabe",
    "Enter": "Eingabe (Ziffernblock)", "PgUp": "Bild ↑", "PgDown": "Bild ↓", "Home": "Pos1", "End": "Ende", "Left": "←", "Right": "→",
    "Up": "↑", "Down": "↓", "Space": "Leertaste", "Backspace": "Rücktaste", "Tab": "Tab", "Esc": "Esc", "-": "−",
}
_FREE_KEYS = {Qt.Key.Key_Delete, Qt.Key.Key_Insert, *(getattr(Qt.Key, f"Key_F{number}") for number in range(1, 25))}
_MODIFIER_KEYS = {Qt.Key.Key_Control, Qt.Key.Key_Shift, Qt.Key.Key_Alt, Qt.Key.Key_Meta, Qt.Key.Key_AltGr}
_RESERVED = {"Alt+F4", "Ctrl+Alt+Del", "Alt+Tab", "Ctrl+Esc", "Alt+Esc", "Ctrl+Shift+Esc"}
# Tasten der Eingabefelder und des Objektmodus (Ausschneiden, Einfügen, Duplizieren, Formatieren, Cursor)
_EDITING = {
    "Ctrl+X", "Ctrl+V", "Ctrl+D", "Ctrl+B", "Ctrl+I", "Ctrl+U", "Ctrl+L", "Ctrl+E", "Ctrl+R", "Ctrl+]", "Ctrl+[",
    "Ctrl+Shift+]", "Ctrl+Shift+[", "Ctrl+Left", "Ctrl+Right", "Ctrl+Up", "Ctrl+Down", "Ctrl+Home", "Ctrl+End",
    "Ctrl+Backspace", "Ctrl+Del", "Shift+Del", "Ctrl+Ins", "Shift+Ins", "Ctrl+Shift+Left", "Ctrl+Shift+Right",
}


# … und auf einer englischen Oberfläche (seit 4.0 Beta 8: vorher stand dort »Strg+F1«)
_ENGLISH_NAMES = {
    "Meta": "Win", "Return": "Enter", "Enter": "Enter (numpad)", "PgUp": "Page Up", "PgDown": "Page Down", "Left": "←",
    "Right": "→", "Up": "↑", "Down": "↓", "-": "−",
}


def display(sequence: str, german: bool = False) -> str:
    """»Ctrl+Shift+S« → »Strg+Umschalt+S« (englische Oberfläche: »Ctrl+Shift+S«), »Ctrl++« → »Strg++«.
    ``german``: immer die deutschen Namen (Texte, die erst danach übersetzt werden)."""
    if not sequence:
        return ""
    if sequence == "+":
        return "+"
    names = _ENGLISH_NAMES if i18n.language() == "en" and not german else _NAMES
    parts = sequence[:-2].split("+") + ["+"] if sequence.endswith("++") else sequence.split("+")
    return "+".join(names.get(part, part) for part in parts)


def normalize(sequence: str) -> str:
    """Qt-Schreibweise einer einzelnen Tastenkombination ("" wenn ungültig)."""
    parsed = QKeySequence(str(sequence or ""), QKeySequence.SequenceFormat.PortableText)
    if parsed.count() != 1:
        return ""
    return parsed.toString(QKeySequence.SequenceFormat.PortableText)


def problem(sequence: str) -> str:
    """Warum ein Kürzel nicht geht – leer, wenn es passt."""
    parsed = QKeySequence(sequence, QKeySequence.SequenceFormat.PortableText)
    if parsed.count() != 1:
        return "Bitte genau eine Tastenkombination drücken."
    combination = parsed[0]
    key, modifiers = combination.key(), combination.keyboardModifiers()
    if key in _MODIFIER_KEYS or key == Qt.Key.Key_unknown:
        return "Bitte zusätzlich eine Taste drücken, nicht nur Strg, Umschalt oder Alt."
    if sequence in _RESERVED:
        return f"{display(sequence)} gehört zu Windows."
    if sequence in _EDITING:
        return f"{display(sequence)} brauchen Textfelder und »Objekt bearbeiten« – bitte eine andere Kombination wählen."
    if key in (Qt.Key.Key_Escape,) or (key in (Qt.Key.Key_Tab, Qt.Key.Key_Backtab) and not modifiers & Qt.KeyboardModifier.ControlModifier):
        return f"{display(sequence)} ist fest vergeben."
    both = Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier
    if modifiers & both == both and key not in _FREE_KEYS:
        return "Strg+Alt mit einer Zeichentaste ist AltGr – damit schreibt man Zeichen wie @ oder €."
    if not modifiers & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier) and key not in _FREE_KEYS:
        return "Bitte eine Kombination mit Strg oder Alt wählen (oder F1 bis F12, Entf)."
    return ""


class ShortcutsController(Observable):
    keysChanged, keys = prop(dict, "keys", {})  # Kennung → ["Ctrl+S", …]
    hintsChanged, hints = prop(dict, "hints", {})  # Kennung → " (Strg+S)" bzw. ""
    labelsChanged, labels = prop(dict, "labels", {})  # Kennung → "Strg+S" bzw. ""
    groupsChanged, groups = prop(list, "groups", [])  # Übersicht: [{title, items: [{key, label, keys, custom}], fixed}]

    def __init__(self, app, cfg: dict, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.app = app
        self._custom: dict[str, list[str]] = {}
        stored = cfg.get(CONFIG_KEY)
        if isinstance(stored, dict):
            for key, value in stored.items():
                if key in BY_KEY and isinstance(value, list):
                    cleaned = [normalize(item) for item in value if isinstance(item, str)]
                    self._custom[key] = [item for item in cleaned if item and not problem(item)][:3]
        self._publish()
        app.register_config(self.config)
        app.key_text = self.localize
        self.observe("labels", lambda _labels: app.refresh_hint())

    def config(self) -> dict:
        return {CONFIG_KEY: {key: list(value) for key, value in self._custom.items()} or None}

    def sequences(self, key: str) -> list[str]:
        if key in self._custom:
            return list(self._custom[key])
        command = BY_KEY.get(key)
        return list(command.defaults) if command is not None else []

    def owner(self, sequence: str) -> str:
        """Befehl, dem ein Kürzel gerade gehört ("" = frei)."""
        for command in COMMANDS:
            if sequence in self.sequences(command.key):
                return command.key
        return ""

    # Ändern --------------------------------------------------------------------------------------------------------
    @Slot(int, int, result=str)
    def sequenceFor(self, key: int, modifiers: int) -> str:  # noqa: N802
        """Taste aus einem Tastaturereignis der Übersicht → Qt-Schreibweise ("" für eine reine Umschalttaste)."""
        if key in {value.value for value in _MODIFIER_KEYS} or key == Qt.Key.Key_unknown.value:
            return ""
        if key == Qt.Key.Key_Backtab.value:  # Umschalt+Tab meldet Qt als eigene Taste
            key = Qt.Key.Key_Tab.value
        mask = sum(flag.value for flag in (Qt.KeyboardModifier.ControlModifier, Qt.KeyboardModifier.ShiftModifier, Qt.KeyboardModifier.AltModifier, Qt.KeyboardModifier.MetaModifier))
        return QKeySequence(int(modifiers) & mask | key).toString(QKeySequence.SequenceFormat.PortableText)

    @Slot(str, str, result=str)
    def assign(self, key: str, sequence: str) -> str:
        """Kürzel für einen Befehl festlegen (ersetzt seine bisherigen). Rückgabe: Hinweis für die Übersicht – ein
        Grund, warum es nicht geht, oder welcher Befehl das Kürzel abgegeben hat."""
        if key not in BY_KEY:
            return ""
        sequence = normalize(sequence)
        reason = problem(sequence) if sequence else "Bitte genau eine Tastenkombination drücken."
        if reason:
            return reason
        note = ""
        previous = self.owner(sequence)
        if previous and previous != key:
            remaining = [item for item in self.sequences(previous) if item != sequence]
            self._set(previous, remaining)
            note = f"{display(sequence)} war »{BY_KEY[previous].label}« zugeordnet – dort entfernt."
        self._set(key, [sequence])
        self._publish()
        self.app.schedule_save()
        return note

    @Slot(str)
    def clear(self, key: str) -> None:
        """Befehl ohne Tastenkürzel."""
        if key in BY_KEY:
            self._set(key, [])
            self._publish()
            self.app.schedule_save()

    @Slot(str)
    def reset(self, key: str) -> None:
        """Standardkürzel wiederherstellen – andere Befehle, die eines davon bekommen haben, geben es ab."""
        command = BY_KEY.get(key)
        if command is None:
            return
        self._custom.pop(key, None)
        for sequence in command.defaults:
            other = self.owner_except(sequence, key)
            if other:
                self._set(other, [item for item in self.sequences(other) if item != sequence])
        self._publish()
        self.app.schedule_save()

    @Slot()
    def resetAll(self) -> None:  # noqa: N802
        self._custom = {}
        self._publish()
        self.app.schedule_save()

    def owner_except(self, sequence: str, key: str) -> str:
        for command in COMMANDS:
            if command.key != key and sequence in self.sequences(command.key):
                return command.key
        return ""

    def _set(self, key: str, sequences: list[str]) -> None:
        if list(sequences) == list(BY_KEY[key].defaults):
            self._custom.pop(key, None)
        else:
            self._custom[key] = list(sequences)

    def refresh(self) -> None:
        """Sprache umgeschaltet: Tastennamen neu (»Strg« ↔ »Ctrl«)."""
        self._publish()

    def _publish(self) -> None:
        keys = {command.key: self.sequences(command.key) for command in COMMANDS}
        labels = {key: display(value[0]) if value else "" for key, value in keys.items()}
        self.keys = keys
        self.labels = labels
        self.hints = {key: f" ({label})" if label else "" for key, label in labels.items()}
        groups = []
        for title in (GENERAL, READER):
            items = [
                {"key": command.key, "label": command.label, "keys": [display(item) for item in keys[command.key]], "custom": command.key in self._custom}
                for command in COMMANDS
                if command.group == title
            ]
            fixed = [{"keys": shown, "label": label} for group, shown, label in FIXED if group == title]
            groups.append({"title": title, "items": items, "fixed": fixed})
        self.groups = groups

    def localize(self, text: str) -> str:
        """Statuszeile (»Strg+O Öffnen   ·   Strg+F Suchen«): Standardkürzel durch die eigenen ersetzen; Abschnitte
        eines Befehls ohne Kürzel entfallen."""
        # Die Hinweise sind deutsch geschrieben (»Strg+5«) und werden erst danach übersetzt: beide Seiten deutsch, sonst
        # fand die englische Oberfläche kein Kürzel und zeigte die alten Standardkürzel.
        changed = {}
        for command in COMMANDS:
            default = display(command.defaults[0], german=True) if command.defaults else ""
            sequences = self.keys.get(command.key) or []
            current = display(sequences[0], german=True) if sequences else ""
            if default and current != default:
                changed[default] = current
        if not changed:
            return text
        pattern = re.compile(r"(?<![\w+])(" + "|".join(re.escape(key) for key in sorted(changed, key=len, reverse=True)) + r")(?![\w+])")
        parts = []
        for part in text.split("·"):
            dropped = False

            def swap(match: re.Match) -> str:
                nonlocal dropped
                value = changed[match.group(1)]
                dropped = dropped or not value
                return value

            replaced = pattern.sub(swap, part)
            if not dropped:
                parts.append(replaced)
        return "·".join(parts).strip(" ·")

    # Übersicht -----------------------------------------------------------------------------------------------------
    @Slot()
    def showOverview(self) -> None:  # noqa: N802
        if not self.app.dialogs.open:
            self.app.dialogs.show("shortcuts", "Tastenkürzel", {}, width=800)

    @Slot(str, result=str)
    def text(self, key: str) -> str:
        """Erstes Kürzel eines Befehls zum Anzeigen ("" ohne)."""
        return self.labels.get(key, "")
