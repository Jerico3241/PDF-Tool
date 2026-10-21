"""Vorlesen (seit 4.0.0-beta.5): Sprechtext, Ablauf Seite für Seite, Wortmarkierung, Pause, Tempo, Ende.

Die Sprachausgabe von Windows ersetzt eine Attrappe, die jedes Wort einzeln »spricht«, sobald der Test es will.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

import editorsamples as samples
from conftest import pump, wait_until
from test_qt_reader import open_pdf, reader, settle

from tools.pdf_editor import speech


class FakeVoice:
    """Sprachausgabe zum Mitschreiben: ``advance()`` springt zum nächsten Wort, danach endet der Text."""

    def __init__(self) -> None:
        self.spoken: list[tuple[str, str, float]] = []
        self.events: list[str] = []
        self.word = -1
        self.words: list[tuple[int, int]] = []

    def voices(self):
        return [speech.Voice("en-1", "Zira (Englisch)", "en"), speech.Voice("de-1", "Hedda (Deutsch)", "de")]

    def speak(self, text, voice, rate):
        self.spoken.append((text, voice, rate))
        self.words, position = [], 0
        for part in text.split(" "):
            self.words.append((position, len(part)))
            position += len(part) + 1
        self.word = 0

    def advance(self, count: int = 1) -> None:
        self.word += count

    def finish(self) -> None:
        self.word = len(self.words)

    def pause(self):
        self.events.append("pause")

    def resume(self):
        self.events.append("resume")

    def stop(self):
        self.events.append("stop")
        self.word = len(self.words)

    def state(self):
        if 0 <= self.word < len(self.words):
            return (True, *self.words[self.word])
        return (False, 0, 0)


@pytest.fixture
def voice(monkeypatch):
    fake = FakeVoice()
    monkeypatch.setattr(speech, "_TEST_BACKEND", fake)
    return fake


@pytest.fixture
def reader_app(ui_app):
    ui_app.app.dialogs.shutdown()
    ui_app.navigate("reader", 0.3)
    return ui_app


def test_prepare_joins_lines_and_hyphenated_words() -> None:
    raw = "Ver-\r\ntrag über 1.234 EUR\r\nZweite  Zeile\x00"
    spoken = speech.prepare(raw)
    assert spoken.text == "Vertrag über 1.234 EUR Zweite Zeile"
    assert len(spoken.index) == len(spoken.text)
    # »Vertrag«: Zeichen 0 bis 9 der Seite (mit Trennstrich und Zeilenumbruch dazwischen)
    assert spoken.chars(0, 7) == (0, 10)
    assert spoken.chars(spoken.text.index("Zweite"), 6) == (raw.index("Zweite"), 6)
    assert spoken.chars(500, 3) == (-1, 0)
    # Gedankenstrich am Zeilenende bleibt, ebenso Großschreibung danach
    assert speech.prepare("Preis -\r\nRabatt").text == "Preis - Rabatt"
    assert speech.prepare("Müller-\r\nLüdenscheidt").text == "Müller- Lüdenscheidt"
    assert speech.prepare("ab\r\n", offset=10).index == (10, 11)


def test_choose_voice_prefers_the_choice_then_german() -> None:
    voices = FakeVoice().voices()
    assert speech.choose_voice(voices, "en-1") == "en-1"
    assert speech.choose_voice(voices, "fehlt") == "de-1"
    assert speech.choose_voice(voices[:1], "") == "en-1"
    assert speech.choose_voice([], "") == ""
    assert speech._language("407") == "de" and speech._language("409;9") == "en" and speech._language("x") == ""


def test_read_aloud_page_by_page_marks_the_word_and_ends(reader_app, tmp_path: Path, voice) -> None:
    h = reader_app
    s = h.runtime.speech
    doc = open_pdf(h, samples.standard_text(tmp_path / "vorlesen.pdf", pages=2))
    bar = h.item("readerSpeechBar")
    assert not bar.isVisible()
    QTest.keyClick(h.window, Qt.Key.Key_Y, Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)
    assert wait_until(lambda: len(voice.spoken) == 1, 10)
    text, chosen, rate = voice.spoken[0]
    assert text.startswith("Rechnung Nr. 4711 vom 01.10.2026 Gesamtbetrag") and text.endswith("Seite 1 von 2")
    assert chosen == "de-1" and rate == 1.0
    assert s.active and s.status == "Seite 1 von 2"
    assert wait_until(lambda: doc.speechWord.get("page") == 0, 5)
    first = doc.speechWord["rects"]
    assert len(first) == 1 and first[0][0] == pytest.approx(72, abs=1)  # »Rechnung« links oben
    assert wait_until(lambda: bar.isVisible() and h.item("readerSpeechWord") is not None, 5)
    voice.advance()
    assert wait_until(lambda: doc.speechWord["rects"] != first, 5)
    assert doc.speechWord["rects"][0][0] > first[0][2] - 1  # »Nr.« rechts daneben
    # Pause und Weiter
    s.togglePause()
    assert s.paused and voice.events[-1] == "pause" and "Pausiert" in h.item("readerSpeechStatus").property("text")
    s.togglePause()
    assert not s.paused and voice.events[-1] == "resume"
    # Tempo: ab dem aktuellen Wort neu, gemerkt
    s.setRate(1.5)
    assert voice.spoken[-1][2] == 1.5 and voice.spoken[-1][0].startswith("Nr. 4711")
    assert s.config()["vorlesen_tempo"] == 1.5
    # Seite 1 zu Ende: weiter mit Seite 2
    voice.finish()
    assert wait_until(lambda: s.status == "Seite 2 von 2", 10)
    assert voice.spoken[-1][0].endswith("Seite 2 von 2")
    assert wait_until(lambda: doc.speechWord.get("page") == 1, 5)
    voice.finish()
    assert wait_until(lambda: not s.active, 10)
    assert doc.speechWord == {} and s.status == ""
    assert wait_until(lambda: not bar.isVisible(), 5)


def test_read_selection_only_and_escape_stops(reader_app, tmp_path: Path, voice) -> None:
    h = reader_app
    s = h.runtime.speech
    doc = open_pdf(h, samples.standard_text(tmp_path / "auswahl.pdf", pages=2))
    doc.loadText(0)
    settle(h)
    assert doc.selectRange(0, 70, 105, 230, 108)  # zweite Zeile
    s.readFromHere()
    assert wait_until(lambda: len(voice.spoken) == 1, 10)
    assert voice.spoken[0][0] == "Gesamtbetrag: 1.234,56 EUR"
    assert wait_until(lambda: doc.speechWord.get("page") == 0, 5)
    assert doc.speechWord["rects"][0][1] > 95  # Wort der zweiten Zeile
    h.item("readerView").forceActiveFocus()
    QTest.keyClick(h.window, Qt.Key.Key_Escape)
    assert wait_until(lambda: not s.active, 5)
    assert voice.events[-1] == "stop" and doc.speechWord == {}


def test_switching_the_tab_stops_reading(reader_app, tmp_path: Path, voice) -> None:
    h = reader_app
    s = h.runtime.speech
    open_pdf(h, samples.standard_text(tmp_path / "eins.pdf"))
    s.readFromHere()
    assert wait_until(lambda: s.active and len(voice.spoken) == 1, 10)
    open_pdf(h, samples.standard_text(tmp_path / "zwei.pdf"))
    assert wait_until(lambda: not s.active, 5)


def test_scanned_pages_have_nothing_to_read(reader_app, tmp_path: Path, voice) -> None:
    h = reader_app
    s = h.runtime.speech
    open_pdf(h, samples.scanned(tmp_path / "scan.pdf"))
    s.readFromHere()
    assert wait_until(lambda: not s.active, 10)
    assert voice.spoken == []
    notice = h.runtime.app.notices.get("reader")
    assert notice.shown and notice.title == "Nichts zum Vorlesen"


def test_without_speech_output_reading_explains(reader_app, tmp_path: Path, monkeypatch) -> None:
    h = reader_app
    monkeypatch.setattr(speech, "_TEST_BACKEND", None)
    monkeypatch.setattr("sys.platform", "linux")  # wie ohne Windows: keine Sprachausgabe
    open_pdf(h, samples.standard_text(tmp_path / "ohne.pdf"))
    h.runtime.speech.readFromHere()
    pump(0.2)
    assert not h.runtime.speech.active
    assert h.runtime.app.notices.get("reader").title == "Vorlesen nicht möglich"
    assert reader(h).current is not None
