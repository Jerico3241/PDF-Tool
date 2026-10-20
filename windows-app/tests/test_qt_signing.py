"""Digitale Signatur (seit 4.0 Beta 6): signieren mit einer Zertifikatsdatei bzw. einem Zertifikat aus Windows
(Attrappe), signierte Kopie öffnen, Signaturen prüfen – auch nach einer Änderung der Datei."""

from __future__ import annotations

import datetime
from pathlib import Path

import pytest
from PySide6.QtCore import QTimer

import editorsamples as samples
from conftest import pump, wait_until
from test_qt_reader import open_pdf, reader

PASSWORD = "geheim"


def make_pfx(folder: Path, name: str = "Erika Mustermann", days: int = 30) -> tuple[Path, bytes]:
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives.serialization import pkcs12
    from cryptography.x509.oid import NameOID

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, name)])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(subject).issuer_name(subject).public_key(key.public_key()).serial_number(4711)
            .not_valid_before(now - datetime.timedelta(days=1)).not_valid_after(now + datetime.timedelta(days=days))
            .add_extension(x509.KeyUsage(True, True, False, False, False, False, False, False, False), critical=True).sign(key, hashes.SHA256()))
    data = pkcs12.serialize_key_and_certificates(b"ci", key, cert, None, serialization.BestAvailableEncryption(PASSWORD.encode()))
    path = folder / "zertifikat.pfx"
    path.write_bytes(data)
    return path, data


@pytest.fixture
def reader_app(ui_app, monkeypatch):
    from qtapp import dialogs

    monkeypatch.setattr(dialogs, "AUTO_ANSWER", None)
    ui_app.app.dialogs.shutdown()
    ui_app.navigate("reader", 0.3)
    return ui_app


def answer(h, kind: str, reply, seen: dict | None = None, button: str = "primary") -> None:
    """Den echten Dialog ``kind`` abwarten, Inhalt merken und antworten (``reply``: Daten oder Funktion)."""
    def respond() -> None:
        service = h.app.dialogs
        if not service.open or service.request.get("kind") != kind:
            QTimer.singleShot(50, respond)
            return
        pump(0.3)
        if seen is not None:
            seen.update(dict(service.request["data"] or {}), message=service.request.get("message", ""))
        data = reply(h) if callable(reply) else reply
        service.answer(service.request["id"], button, data)

    QTimer.singleShot(50, respond)


def test_sign_with_certificate_file_and_check(reader_app, tmp_path: Path, monkeypatch) -> None:
    h = reader_app
    pfx, _data = make_pfx(tmp_path)
    source = samples.standard_text(tmp_path / "vertrag.pdf", pages=2)
    doc = open_pdf(h, source)
    target = tmp_path / "vertrag (signiert).pdf"
    monkeypatch.setattr(type(reader(h)), "pick_save_pdf", lambda self, name, title: str(target))
    seen: dict = {}

    def fill(h) -> dict:
        content = h.item("signUseFile")
        assert content is not None and content.isVisible()
        return {"thumbprint": "", "file": str(pfx), "password": PASSWORD, "reason": "Einverstanden", "location": "Köln", "visible": True, "page": 1}

    answer(h, "digital_sign", fill, seen)
    doc.digitalSign()
    assert wait_until(lambda: target.is_file() and reader(h).current is not None and Path(reader(h).current.path or "") == target, 30), "signierte Kopie wurde nicht geöffnet"
    assert seen["pageCount"] == 2 and seen["certificates"] == []
    assert h.app.notices.get("reader").title == "Digital signiert"
    assert source.read_bytes()[:4] == b"%PDF" and b"/ByteRange" not in source.read_bytes()  # Original unverändert
    signed = reader(h).current
    assert wait_until(lambda: signed.signed == 1, 10)
    # Prüfen: unverändert, Name, Grund, Feld auf Seite 2
    result: dict = {}
    answer(h, "signatures", lambda h: {"page": 1}, result, button="close")
    signed.checkSignatures()
    assert wait_until(lambda: "signatures" in result, 20)
    entry = result["signatures"][0]
    assert entry["status"] == "valid" and entry["title"] in ("Unverändert", "Unverändert, Zertifikat nicht bestätigt"), entry
    assert {line["label"]: line["value"] for line in entry["lines"]}["Grund"] == "Einverstanden"
    assert entry["visible"] and entry["page"] == 1
    assert wait_until(lambda: signed.currentPage == 1, 5)  # »Zum Feld«
    # Die Einstellungen bleiben für das nächste Mal
    assert reader(h).sign_defaults["reason"] == "Einverstanden" and reader(h).sign_defaults["visible"] is True


def test_changed_file_is_reported_invalid(reader_app, tmp_path: Path) -> None:
    from tools.pdf_editor import digsig

    h = reader_app
    _pfx, data = make_pfx(tmp_path)
    source = samples.standard_text(tmp_path / "brief.pdf")
    signed = digsig.sign_pdf(source.read_bytes(), digsig.FileSigner(data, PASSWORD))
    broken = bytearray(signed)
    at = broken.find(b"/MediaBox")
    broken[at + 12] = ord("9") if broken[at + 12] != ord("9") else ord("8")
    path = tmp_path / "brief-geaendert.pdf"
    path.write_bytes(bytes(broken))
    doc = open_pdf(h, path)
    assert "digital signiert" in doc.notice
    result: dict = {}
    answer(h, "signatures", {}, result, button="close")
    doc.checkSignatures()
    assert wait_until(lambda: "signatures" in result, 20)
    assert result["signatures"][0]["status"] == "invalid" and result["signatures"][0]["tone"] == "error"


def test_windows_certificates_are_offered(reader_app, tmp_path: Path, monkeypatch) -> None:
    """Zertifikate aus Windows (Attrappe): im Dialog wählbar, signiert wird mit dem gewählten."""
    from tools.pdf_editor import digsig

    h = reader_app
    _pfx, data = make_pfx(tmp_path, name="Max Beispiel")
    file_signer = digsig.FileSigner(data, PASSWORD)
    info = digsig.cert_info(file_signer.certificate)

    class Entry:
        thumbprint, subject, issuer, email, not_after, self_signed = info.thumbprint, info.subject, info.issuer, "", info.not_after, True

    used: list = []
    monkeypatch.setattr(digsig, "TEST_CERTIFICATES", [Entry()])
    monkeypatch.setattr(digsig, "TEST_SIGNER", lambda thumbprint: used.append(thumbprint) or file_signer)
    source = samples.standard_text(tmp_path / "angebot.pdf")
    doc = open_pdf(h, source)
    target = tmp_path / "angebot-signiert.pdf"
    monkeypatch.setattr(type(reader(h)), "pick_save_pdf", lambda self, name, title: str(target))
    seen: dict = {}

    def choose(h) -> dict:
        radio = h.item("signCertificate_0")
        assert radio is not None and radio.property("checked") is True and "Max Beispiel" in radio.property("text")
        assert not h.item("signPassword").isVisible()
        return {"thumbprint": info.thumbprint, "reason": "", "location": "", "visible": False, "page": 0}

    answer(h, "digital_sign", choose, seen)
    doc.digitalSign()
    assert wait_until(lambda: target.is_file(), 30)
    assert used == [info.thumbprint]
    reports = digsig.verify_pdf(target.read_bytes())
    assert len(reports) == 1 and reports[0].status == digsig.VALID and reports[0].signer == "Max Beispiel" and not reports[0].visible
