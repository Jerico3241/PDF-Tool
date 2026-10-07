"""»Per E-Mail senden« (``qtapp/mail.py``) ohne Oberfläche und ohne echtes E-Mail-Programm.

Geprüft werden die Adresse für ``mailto:``, die Empfängerprüfung, die Ergebnisse von ``send_file`` (Simple MAPI
übernommen, abgebrochen, Fehler → Ersatzweg, kein MAPI, Datei fehlt, beschäftigt) und der Aufbau der MAPI-Strukturen
für 64-Bit-Windows. MAPI, ``mailto:`` und der Explorer sind Attrappen – es öffnet sich nie ein Programm.
"""

from __future__ import annotations

import ctypes
import threading
from pathlib import Path

import pytest

from qtapp import mail


@pytest.fixture
def pdf(tmp_path: Path) -> Path:
    path = tmp_path / "Angebot März 2026.pdf"
    path.write_bytes(b"%PDF-1.7\n%%EOF\n")
    return path


@pytest.fixture
def fake(monkeypatch):
    """MAPI-Weg wie unter Windows, aber mit einer Attrappe; ``mailto:`` und Explorer werden nur protokolliert."""
    calls: dict = {"mapi": [], "urls": [], "shown": [], "code": None, "url_ok": True}

    def mapi(path, subject, to, body):
        calls["mapi"].append({"path": path, "subject": subject, "to": to, "body": body})
        return calls["code"]

    monkeypatch.setattr(mail, "_mapi_send", mapi)
    monkeypatch.setattr(mail, "open_url", lambda url: calls["urls"].append(url) or calls["url_ok"])
    monkeypatch.setattr(mail, "show_in_folder", lambda path: calls["shown"].append(path) or True)
    monkeypatch.setattr(mail, "_com_init", lambda: False)
    return calls


def test_mailto_url_and_recipient_check() -> None:
    assert mail.mailto_url() == "mailto:"
    assert mail.mailto_url("rechnung@muster.de", "Vertragsübersicht Kd 10042.pdf") == "mailto:rechnung@muster.de?subject=Vertrags%C3%BCbersicht%20Kd%2010042.pdf"
    assert mail.mailto_url("", "a&b?c=d", "Zeile 1\nZeile 2") == "mailto:?subject=a%26b%3Fc%3Dd&body=Zeile%201%0AZeile%202"
    assert mail.mailto_url("max+rechnung@firma.de") == "mailto:max+rechnung@firma.de"
    # Keine Adresse (oder mehrere, Namen, eingeschleuste Felder): kein Empfänger
    for text in ("", "–", "Frau Muster", "a@b", "a@b.de, c@d.de", "a@b.de?cc=x@y.de", "SMTP:a@b.de", "<a@b.de>", " a @b.de"):
        assert not mail.valid_address(text), text
        assert mail.mailto_url(text, "x") == "mailto:?subject=x"
    assert mail.valid_address(" rechnung@muster.de ")


def test_fallback_on_other_systems_opens_mailto_and_shows_the_file(pdf: Path, fake, monkeypatch) -> None:
    """Außerhalb von Windows (Tests): nie MAPI, immer der Ersatzweg – neue Nachricht ohne Anhang, Datei markiert."""
    monkeypatch.setattr(mail, "IS_WINDOWS", False)
    assert mail.send_file(str(pdf), subject=pdf.name, to="rechnung@muster.de") == mail.MANUAL
    assert fake["mapi"] == [] and fake["shown"] == [str(pdf)]
    assert fake["urls"] == ["mailto:rechnung@muster.de?subject=Angebot%20M%C3%A4rz%202026.pdf"]
    fake["url_ok"] = False
    assert mail.send_file(str(pdf)) == mail.NO_CLIENT
    assert fake["shown"] == [str(pdf), str(pdf)]


@pytest.mark.parametrize("code,outcome,fallback", [
    (mail.SUCCESS_SUCCESS, mail.OK, False),
    (mail.MAPI_USER_ABORT, mail.CANCELLED, False),  # abgebrochen ist kein Fehler: kein Ersatzweg
    (2, mail.MANUAL, True),  # MAPI_E_FAILURE
    (26, mail.MANUAL, True),  # MAPI_E_NOT_SUPPORTED
    (None, mail.MANUAL, True),  # kein E-Mail-Programm für Simple MAPI
])
def test_mapi_results(pdf: Path, fake, monkeypatch, code, outcome: str, fallback: bool) -> None:
    monkeypatch.setattr(mail, "IS_WINDOWS", True)
    fake["code"] = code
    assert mail.send_file(str(pdf), subject="Betreff", to="rechnung@muster.de", body="Hallo") == outcome
    assert fake["mapi"] == [{"path": str(pdf), "subject": "Betreff", "to": "rechnung@muster.de", "body": "Hallo"}]
    assert bool(fake["urls"]) is fallback and bool(fake["shown"]) is fallback


def test_failing_mapi_falls_back_to_mailto(pdf: Path, fake, monkeypatch) -> None:
    """Scheitert Simple MAPI mit einer Ausnahme (z. B. im Treiber des E-Mail-Programms), bleibt der Ersatzweg."""
    monkeypatch.setattr(mail, "IS_WINDOWS", True)

    def broken(*_args):
        raise OSError("exception: access violation")

    monkeypatch.setattr(mail, "_mapi_send", broken)
    assert mail.send_file(str(pdf), subject="x") == mail.MANUAL
    assert fake["urls"] == ["mailto:?subject=x"] and fake["shown"] == [str(pdf)]
    assert mail.send_file(str(pdf)) == mail.MANUAL  # die Sperre ist wieder frei


def test_invalid_recipient_is_left_empty_and_missing_file_is_reported(pdf: Path, fake, monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(mail, "IS_WINDOWS", True)
    fake["code"] = mail.SUCCESS_SUCCESS
    assert mail.send_file(str(pdf), to="–") == mail.OK
    assert fake["mapi"][-1]["to"] == ""
    assert mail.send_file(str(tmp_path / "fehlt.pdf")) == mail.MISSING
    assert len(fake["mapi"]) == 1


def test_only_one_message_at_a_time(pdf: Path, fake, monkeypatch) -> None:
    """Simple MAPI wartet, bis die Nachricht gesendet oder verworfen ist – ein zweiter Versuch währenddessen meldet
    »beschäftigt« statt eine zweite Nachricht zu öffnen."""
    monkeypatch.setattr(mail, "IS_WINDOWS", True)
    entered, release = threading.Event(), threading.Event()

    def slow(path, subject, to, body):
        entered.set()
        release.wait(10)
        return mail.SUCCESS_SUCCESS

    monkeypatch.setattr(mail, "_mapi_send", slow)
    results: list = []
    worker = threading.Thread(target=lambda: results.append(mail.send_file(str(pdf))))
    worker.start()
    assert entered.wait(10)
    assert mail.send_file(str(pdf)) == mail.BUSY
    release.set()
    worker.join(10)
    assert results == [mail.OK]
    assert mail.send_file(str(pdf)) == mail.OK  # danach wieder frei


def test_mapi_is_skipped_without_a_registered_mail_program(monkeypatch, pdf: Path) -> None:
    """Ohne eingetragenes E-Mail-Programm wird ``mapi32.dll`` gar nicht erst gerufen (sie zeigte sonst selbst eine
    Fehlermeldung von Windows)."""
    monkeypatch.setattr(mail, "IS_WINDOWS", True)
    monkeypatch.setattr(mail, "_mapi_client", lambda: False)
    assert mail._mapi_send(str(pdf), "", "", "") is None  # noqa: SLF001


def test_module_works_without_windows_apis(monkeypatch, pdf: Path) -> None:
    """Auf anderen Systemen: importierbar, COM und MAPI fehlen ohne Fehler."""
    monkeypatch.setattr(mail, "IS_WINDOWS", False)
    assert mail._com_init() is False  # noqa: SLF001
    assert mail._mapi_send(str(pdf), "", "", "") is None  # noqa: SLF001


@pytest.mark.skipif(ctypes.sizeof(ctypes.c_void_p) != 8, reason="Aufbau für 64-Bit-Prozesse")
def test_mapi_structures_match_the_64_bit_layout() -> None:
    """MapiMessageW, MapiRecipDescW und MapiFileDescW wie in MAPI.h (x64: ULONG 4 Byte, Zeiger 8 Byte, ausgerichtet)."""
    assert ctypes.sizeof(mail.MapiRecipDescW) == 40 and mail.MapiRecipDescW.lpszName.offset == 8 and mail.MapiRecipDescW.lpEntryID.offset == 32
    assert ctypes.sizeof(mail.MapiFileDescW) == 40 and mail.MapiFileDescW.nPosition.offset == 8 and mail.MapiFileDescW.lpszPathName.offset == 16
    offsets = {name: getattr(mail.MapiMessageW, name).offset for name, _type in mail.MapiMessageW._fields_}
    assert offsets == {"ulReserved": 0, "lpszSubject": 8, "lpszNoteText": 16, "lpszMessageType": 24, "lpszDateReceived": 32, "lpszConversationID": 40,
                       "flFlags": 48, "lpOriginator": 56, "nRecipCount": 64, "lpRecips": 72, "nFileCount": 80, "lpFiles": 88}
    assert ctypes.sizeof(mail.MapiMessageW) == 96 and ctypes.sizeof(mail.MapiMessage) == 96
    assert mail.MAPI_DIALOG | mail.MAPI_LOGON_UI == 0x9 and mail.NO_POSITION == 0xFFFFFFFF


def test_report_texts() -> None:
    """Rückmeldung an die Oberfläche: Statuszeile bzw. Hinweis mit »Pfad kopieren«."""

    class App:
        def __init__(self) -> None:
            self.status: list = []
            self.notices: list = []
            self.copied: list = []

        def set_status(self, text: str, kind: str = "neutral") -> None:
            self.status.append((text, kind))

        def notify(self, area, severity, message, title="", actions=(), auto_hide=None, **_kwargs) -> None:
            self.notices.append((area, severity, title, message, [label for label, _callback in actions]))
            for _label, callback in actions:
                callback()

        def copy_path(self, path) -> None:
            self.copied.append(str(path))

    app = App()
    mail.report(app, mail.OK, "C:/Daten/brief.pdf", "reader")
    mail.report(app, mail.CANCELLED, "C:/Daten/brief.pdf", "reader")
    assert app.status == [("»brief.pdf« wurde an Ihr E-Mail-Programm übergeben.", "success"), ("Senden per E-Mail abgebrochen.", "neutral")]
    mail.report(app, mail.MANUAL, "C:/Daten/brief.pdf", "reader")
    mail.report(app, mail.NO_CLIENT, "C:/Daten/brief.pdf", "pdf_mail_info")
    mail.report(app, mail.MISSING, "C:/Daten/brief.pdf", "reader")
    mail.report(app, mail.BUSY, "C:/Daten/brief.pdf", "reader")
    assert [(area, severity, title) for area, severity, title, _message, _actions in app.notices] == [
        ("reader", "info", "Bitte Anhang hinzufügen"), ("pdf_mail_info", "warning", "Kein E-Mail-Programm gefunden"),
        ("reader", "error", "Senden nicht möglich"), ("reader", "info", "E-Mail-Programm ist beschäftigt"),
    ]
    assert app.notices[0][4] == ["Pfad kopieren"] and app.copied == ["C:/Daten/brief.pdf", "C:/Daten/brief.pdf"]
    assert "bitte ziehen Sie die Datei in die Nachricht" in app.notices[0][3]
