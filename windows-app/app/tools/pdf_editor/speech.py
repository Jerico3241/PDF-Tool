"""Vorlesen (seit 4.0 Beta 5): Text einer PDF mit den Stimmen von Windows sprechen (SAPI).

Gesprochen wird mit den Stimmen, die Windows unter »Sprachausgabe« kennt (Deutsch z. B. »Hedda« oder »Katja«),
ohne Netzwerk. ``prepare`` macht aus dem Text einer Seite einen Sprechtext: Zeilenumbrüche werden zu Leerzeichen,
am Zeilenende getrennte Wörter wieder zusammengesetzt. Dazu gehört eine Zuordnung Sprechtext → Zeichen der Seite,
damit die Ansicht das gerade gesprochene Wort markieren kann.

Unter Linux und in Tests ersetzt eine Attrappe die Schnittstelle (``Backend``).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

RATES = (0.75, 1.0, 1.25, 1.5, 2.0)  # Tempo in der Oberfläche
SAPI_RATE = {0.75: -3, 1.0: 0, 1.25: 2, 1.5: 4, 2.0: 7}  # SAPI: -10 … 10
DEFAULT_RATE = 1.0

# SAPI (sapi.h): SpeechVoiceSpeakFlags, SpeechRunState
SVSF_ASYNC = 1
SVSF_PURGE = 2
SVSF_IS_NOT_XML = 16
RUN_DONE = 1

_LINEBREAKS = "\r\n"
_DROP = "\x00\x02￾­"  # Nullzeichen, Trennhilfen von PDFium, weiches Trennzeichen


class SpeechError(Exception):
    """Vorlesen nicht möglich – ``str()`` ist die Meldung für die Anwendenden."""


@dataclass(frozen=True)
class Voice:
    ident: str
    name: str
    language: str  # z. B. »de«, »en« ("" = unbekannt)


@dataclass(frozen=True)
class Spoken:
    """Sprechtext einer Seite; ``index[i]``: Zeichen der Seite zum Zeichen ``i`` des Sprechtexts."""

    text: str
    index: tuple[int, ...]

    def chars(self, start: int, length: int) -> tuple[int, int]:
        """Zeichen der Seite zu einem Wort des Sprechtexts als (Anfang, Anzahl); (-1, 0), wenn außerhalb."""
        if not self.index or start < 0 or start >= len(self.index) or length <= 0:
            return (-1, 0)
        end = min(len(self.index), start + length) - 1
        first, last = self.index[start], self.index[end]
        return (first, last - first + 1)


def prepare(raw: str, offset: int = 0) -> Spoken:
    """Text der Seite (wie PDFium ihn liefert, ein Zeichen je Zeichen der Seite) → Sprechtext mit Zuordnung."""
    out: list[str] = []
    index: list[int] = []
    i, total = 0, len(raw)
    while i < total:
        char = raw[i]
        if char in _DROP:
            i += 1
            continue
        if char in _LINEBREAKS:
            j = i
            while j < total and raw[j] in _LINEBREAKS:
                j += 1
            # »Ver-« am Zeilenende + Kleinbuchstabe am Anfang der nächsten: ein Wort
            if out and out[-1] == "-" and len(out) > 1 and out[-2].isalpha() and j < total and raw[j].islower():
                out.pop()
                index.pop()
            elif out and out[-1] != " ":
                out.append(" ")
                index.append(offset + i)
            i = j
            continue
        if char.isspace():
            if out and out[-1] != " ":
                out.append(" ")
                index.append(offset + i)
            i += 1
            continue
        out.append(char)
        index.append(offset + i)
        i += 1
    while out and out[-1] == " ":
        out.pop()
        index.pop()
    return Spoken("".join(out), tuple(index))


class Backend(Protocol):
    def voices(self) -> list[Voice]: ...

    def speak(self, text: str, voice: str, rate: float) -> None:
        """Sofort sprechen (ohne zu warten); ersetzt, was gerade gesprochen wird."""
        ...

    def pause(self) -> None: ...

    def resume(self) -> None: ...

    def stop(self) -> None: ...

    def state(self) -> tuple[bool, int, int]:
        """(spricht noch, Anfang und Länge des gerade gesprochenen Worts im Sprechtext)."""
        ...


# Windows: SAPI über COM (comtypes) ---------------------------------------------------------------------------------

class SapiBackend:
    """``SAPI.SpVoice`` (seit Windows XP Teil von Windows) im GUI-Thread: Sprechen läuft asynchron."""

    def __init__(self) -> None:
        import comtypes.client

        self._voice = comtypes.client.CreateObject("SAPI.SpVoice", dynamic=True)
        self._tokens: dict[str, object] = {}

    def voices(self) -> list[Voice]:
        found = []
        tokens = self._voice.GetVoices()
        for index in range(int(tokens.Count)):
            token = tokens.Item(index)
            ident = str(token.Id)
            self._tokens[ident] = token
            found.append(Voice(ident, str(token.GetDescription()), _language(_attribute(token, "Language"))))
        return found

    def speak(self, text: str, voice: str, rate: float) -> None:
        if voice:
            if not self._tokens:
                self.voices()
            token = self._tokens.get(voice)
            if token is not None:
                self._voice.Voice = token
        self._voice.Rate = SAPI_RATE.get(rate, 0)
        self._voice.Resume()  # nach »Pause« spricht SAPI sonst nicht weiter
        self._voice.Speak(text, SVSF_ASYNC | SVSF_PURGE | SVSF_IS_NOT_XML)

    def pause(self) -> None:
        self._voice.Pause()

    def resume(self) -> None:
        self._voice.Resume()

    def stop(self) -> None:
        self._voice.Resume()
        self._voice.Speak("", SVSF_ASYNC | SVSF_PURGE)

    def state(self) -> tuple[bool, int, int]:
        status = self._voice.Status
        return (int(status.RunningState) != RUN_DONE, int(status.InputWordPosition), int(status.InputWordLength))


def _attribute(token, name: str) -> str:
    try:
        return str(token.GetAttribute(name) or "")
    except Exception:  # noqa: BLE001 - Stimme ohne diese Angabe
        return ""


# Sprachkennungen (LCID, hexadezimal, z. B. »407« oder »409;9«) → Sprache
_LCID = {0x07: "de", 0x09: "en", 0x0C: "fr", 0x10: "it", 0x0A: "es", 0x13: "nl", 0x16: "pt", 0x15: "pl", 0x1F: "tr", 0x19: "ru"}


def _language(value: str) -> str:
    try:
        lcid = int(value.split(";")[0], 16)
    except ValueError:
        return ""
    return _LCID.get(lcid & 0x3FF, "")


_TEST_BACKEND: Backend | None = None


def default_backend() -> Backend | None:
    """Die Sprachausgabe von Windows – ``None`` unter Linux oder ohne comtypes. Fehler beim Einrichten (kein
    Sprachdienst) werden zu ``SpeechError``."""
    if _TEST_BACKEND is not None:
        return _TEST_BACKEND
    import sys

    if sys.platform != "win32":
        return None
    try:
        return SapiBackend()
    except ImportError:
        return None
    except Exception as exc:  # noqa: BLE001 - Sprachdienst fehlt oder ist abgeschaltet
        raise SpeechError("Die Sprachausgabe von Windows ist nicht verfügbar.") from exc


def choose_voice(voices: list[Voice], wanted: str, language: str = "de") -> str:
    """Gewählte Stimme, sonst die erste deutsche, sonst die erste überhaupt ("" = Standard von Windows)."""
    if any(voice.ident == wanted for voice in voices):
        return wanted
    for voice in voices:
        if voice.language == language:
            return voice.ident
    return voices[0].ident if voices else ""
