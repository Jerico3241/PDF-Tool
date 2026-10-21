"""Vorlesen in der Oberfläche (QML: ``Speech``, seit 4.0 Beta 5): die Auswahl oder das Dokument ab der aktuellen
Seite mit den Stimmen von Windows sprechen.

Gesprochen wird Seite für Seite; die Ansicht markiert das gerade gesprochene Wort und folgt ihm. Pause, Weiter,
Stopp und das Tempo stehen in einer Leiste über dem Dokument. Das Vorlesen endet beim Wechsel des Tabs, beim
Schließen des Dokuments und mit »Stopp« (Esc). Seiten ohne Text (Scans) werden übersprungen.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, QTimer, Slot

from tools.pdf_editor import speech

from .base import Observable, prop

VOICE_KEY = "vorlesen_stimme"  # gui-config.json: gewählte Stimme (SAPI-Kennung)
RATE_KEY = "vorlesen_tempo"
POLL_MS = 120  # so oft fragt Novadesk die Sprachausgabe nach Wort und Ende


class SpeechController(Observable):
    activeChanged, active = prop(bool, "active", False)  # liest gerade vor (auch pausiert)
    pausedChanged, paused = prop(bool, "paused", False)
    statusChanged, status = prop(str, "status", "")  # »Seite 3 von 12«
    rateChanged, rate = prop(float, "rate", speech.DEFAULT_RATE)
    ratesChanged, rates = prop(list, "rates", [])
    voicesChanged, voices = prop(list, "voices", [])  # [{ident, name}]
    voiceChanged, voice = prop(str, "voice", "")

    def __init__(self, app, cfg: dict, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.app = app
        self.reader = None
        self._backend: speech.Backend | None = None
        self._wanted_voice = str(cfg.get(VOICE_KEY) or "")
        rate = cfg.get(RATE_KEY)
        self.set_quietly("rate", float(rate) if rate in speech.RATES else speech.DEFAULT_RATE)
        self.set_quietly("rates", [{"value": value, "label": f"{value:g}×".replace(".", ",")} for value in speech.RATES])
        self._doc = None
        self._segments: list[tuple[int, int, int]] = []  # noch zu lesen: (Seite, Anfang, Anzahl; -1 = bis Seitenende)
        self._spoken: speech.Spoken | None = None
        self._page = -1
        self._read_any = False  # mindestens eine Seite mit Text gesprochen
        self._serial = 0  # verwirft Ergebnisse eines früheren Vorlesens
        self._last_word = (-1, 0)
        self._timer = QTimer(self)
        self._timer.setInterval(POLL_MS)
        self._timer.timeout.connect(self._tick)
        app.register_config(self.config)
        app.at_shutdown(self.stop)

    def attach_reader(self, reader) -> None:
        self.reader = reader
        reader.currentChanged.connect(self._current_changed)

    def config(self) -> dict:
        return {VOICE_KEY: self._wanted_voice or None, RATE_KEY: self.rate}

    # Starten -------------------------------------------------------------------------------------------------------
    @Slot()
    def toggle(self) -> None:
        """Strg+Umschalt+Y: vorlesen (Auswahl, sonst ab der aktuellen Seite) bzw. beenden."""
        if self.active:
            self.stop()
        else:
            self.readFromHere()

    @Slot()
    def readFromHere(self) -> None:  # noqa: N802
        """Die Auswahl vorlesen – ohne Auswahl das Dokument ab der aktuellen Seite."""
        doc = self.reader.current if self.reader is not None else None
        if doc is None or doc.pageCount == 0:
            return
        spans = doc.selection_spans()
        if spans:
            self._start(doc, spans)
        else:
            self._start(doc, [(page, 0, -1) for page in range(doc.currentPage, doc.pageCount)])

    @Slot()
    def readPage(self) -> None:  # noqa: N802
        doc = self.reader.current if self.reader is not None else None
        if doc is not None and doc.pageCount:
            self._start(doc, [(doc.currentPage, 0, -1)])

    def _start(self, doc, segments: list[tuple[int, int, int]]) -> None:
        if not self._ensure_backend():
            return
        self.stop()
        self._serial += 1
        self._doc = doc
        self._segments = list(segments)
        self._read_any = False
        self.active = True
        self.paused = False
        self._next()

    def _ensure_backend(self) -> bool:
        if self._backend is not None:
            return True
        try:
            backend = speech.default_backend()
        except speech.SpeechError as exc:
            self.app.notify("reader", "warning", str(exc), title="Vorlesen nicht möglich")
            return False
        if backend is None:
            self.app.notify("reader", "warning", "Vorlesen ist nur unter Windows möglich.", title="Vorlesen nicht möglich")
            return False
        try:
            voices = backend.voices()
        except Exception:  # noqa: BLE001 - Stimmen nicht lesbar: Standardstimme von Windows
            voices = []
        self._backend = backend
        self.voices = [{"ident": voice.ident, "name": voice.name} for voice in voices]
        self.voice = speech.choose_voice(voices, self._wanted_voice)
        return True

    # Ablauf --------------------------------------------------------------------------------------------------------
    def _next(self) -> None:
        doc = self._doc
        if doc is None or not self.active:
            return
        if not self._segments:
            self._finish()
            return
        page, start, count = self._segments.pop(0)
        if not 0 <= page < doc.pageCount:
            self._next()
            return
        serial = self._serial

        def done(raw: str) -> None:
            if serial != self._serial or not self.active:
                return
            spoken = speech.prepare(raw, offset=start)
            if not spoken.text.strip():
                self._next()  # Seite ohne Text (Scan)
                return
            self._read_any = True
            self._page = page
            self._spoken = spoken
            self._last_word = (-1, 0)
            self.status = f"Seite {page + 1} von {doc.pageCount}"
            doc.text_rects(page, 0, 0)  # Textschicht für die Markierung laden
            self._speak(spoken.text)

        def failed(_exc: BaseException) -> None:
            if serial == self._serial:
                self._next()

        doc.run(lambda session: session.raw_text(page, start, count), done, refresh=False, failed=failed)

    def _speak(self, text: str) -> None:
        try:
            self._backend.speak(text, self.voice, self.rate)
        except Exception:  # noqa: BLE001 - Sprachausgabe gestört
            self.stop()
            self.app.notify("reader", "warning", "Die Sprachausgabe von Windows hat nicht geantwortet.", title="Vorlesen beendet")
            return
        if not self.paused:
            self._timer.start()

    def _tick(self) -> None:
        if not self.active or self.paused or self._backend is None or self._spoken is None:
            return
        try:
            speaking, position, length = self._backend.state()
        except Exception:  # noqa: BLE001
            speaking, position, length = False, 0, 0
        if not speaking:
            self._timer.stop()
            self._spoken = None
            self._next()
            return
        word = self._spoken.chars(position, length)
        if word == self._last_word or word[0] < 0:
            return
        self._last_word = word
        rects = self._doc.text_rects(self._page, *word) if self._doc is not None else None
        if rects:
            self._doc.speechWord = {"page": self._page, "rects": rects}
            first = rects[0]
            self._doc.reveal(self._page, first[0], first[3])

    def _finish(self) -> None:
        had_text = self._read_any
        self.stop()
        if not had_text:
            self.app.notify("reader", "info", "Diese Seiten enthalten keinen Text, nur Bilder (z. B. Scans). Nach der Texterkennung lassen sie sich vorlesen.", title="Nichts zum Vorlesen")

    # Steuern -------------------------------------------------------------------------------------------------------
    @Slot()
    def pause(self) -> None:
        if self.active and not self.paused and self._backend is not None:
            self._backend.pause()
            self.paused = True
            self._timer.stop()

    @Slot()
    def resume(self) -> None:
        if self.active and self.paused and self._backend is not None:
            self._backend.resume()
            self.paused = False
            self._timer.start()

    @Slot()
    def togglePause(self) -> None:  # noqa: N802
        if self.paused:
            self.resume()
        else:
            self.pause()

    @Slot()
    def stop(self) -> None:
        self._serial += 1
        self._timer.stop()
        if self._backend is not None and self.active:
            try:
                self._backend.stop()
            except Exception:  # noqa: BLE001
                pass
        if self._doc is not None and self._doc.speechWord:
            self._doc.speechWord = {}
        self._doc = None
        self._segments = []
        self._spoken = None
        self._page = -1
        self.active = False
        self.paused = False
        self.status = ""

    @Slot(float)
    def setRate(self, value: float) -> None:  # noqa: N802
        value = min(speech.RATES, key=lambda rate: abs(rate - float(value)))
        if value == self.rate:
            return
        self.rate = value
        self.app.schedule_save()
        self._restart_here()

    @Slot(str)
    def setVoice(self, ident: str) -> None:  # noqa: N802
        if ident == self.voice:
            return
        self.voice = ident
        self._wanted_voice = ident
        self.app.schedule_save()
        self._restart_here()

    def _restart_here(self) -> None:
        """Tempo oder Stimme geändert: ab dem aktuellen Wort neu sprechen."""
        if not self.active or self._spoken is None or self._backend is None:
            return
        try:
            _speaking, position, _length = self._backend.state()
        except Exception:  # noqa: BLE001
            position = 0
        spoken = self._spoken
        position = max(0, min(position, len(spoken.text)))
        self._spoken = speech.Spoken(spoken.text[position:], spoken.index[position:])
        was_paused = self.paused
        self.paused = False
        self._speak(self._spoken.text)
        if was_paused:
            self.pause()

    def _current_changed(self) -> None:
        if self.active and (self.reader is None or self.reader.current is not self._doc):
            self.stop()
