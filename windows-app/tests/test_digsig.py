"""Digitale Signaturen (seit 4.0 Beta 6): Signieren nach PAdES, Prüfen, mehrere Signaturen, Querverweis-Ströme;
unter Windows zusätzlich der Zertifikatspeicher (Schlüssel aus CNG und aus der alten CryptoAPI) und die Prüfung der
Vertrauenskette."""

from __future__ import annotations

import io
import os
import subprocess
import sys
from pathlib import Path

import pikepdf
import pytest

import editorsamples as samples
from test_qt_signing import PASSWORD, make_pfx
from tools.pdf_editor import digsig


@pytest.fixture
def signer(tmp_path: Path):
    _path, data = make_pfx(tmp_path)
    return digsig.FileSigner(data, PASSWORD)


def test_sign_verify_and_detect_changes(tmp_path: Path, signer) -> None:
    source = samples.standard_text(tmp_path / "a.pdf", pages=2).read_bytes()
    signed = digsig.sign_pdf(source, signer, digsig.SignOptions(reason="Geprüft", location="Köln", visible_page=1))
    with pikepdf.open(io.BytesIO(signed)) as pdf:  # gültiges PDF, gleiche Seiten
        assert len(pdf.pages) == 2 and int(pdf.Root.AcroForm.SigFlags) == 3
    [report] = digsig.verify_pdf(signed, trust=lambda cert, extra, when: ("trusted", "ok"))
    assert report.status == digsig.VALID and report.signer == "Erika Mustermann" and report.reason == "Geprüft"
    assert report.location == "Köln" and report.page == 1 and report.visible and report.covers_whole
    assert digsig.summary(report)["title"] == "Gültig"
    # Zweite Signatur dahinter: die erste bleibt mathematisch gültig, deckt aber nicht mehr alles ab
    twice = digsig.sign_pdf(signed, signer, digsig.SignOptions(reason="Freigabe"))
    first, second = digsig.verify_pdf(twice)
    assert first.status == digsig.CHANGED and second.status == digsig.VALID and twice.startswith(signed)
    # Ein geändertes Byte im signierten Bereich: ungültig
    broken = bytearray(signed)
    at = broken.find(b"/MediaBox")
    broken[at + 12] = ord("9") if broken[at + 12] != ord("9") else ord("8")
    assert digsig.verify_pdf(bytes(broken))[0].status == digsig.INVALID


def test_wrong_password_and_unsigned(tmp_path: Path) -> None:
    _path, data = make_pfx(tmp_path)
    with pytest.raises(digsig.SignError, match="Kennwort"):
        digsig.FileSigner(data, "falsch")
    assert digsig.verify_pdf(samples.standard_text(tmp_path / "b.pdf").read_bytes()) == []


def test_existing_xref_streams_get_a_stream_update(tmp_path: Path, signer) -> None:
    """Hat das PDF schon eine Signatur und Querverweis-Ströme, bleibt es unverändert und die Aktualisierung ist auch
    ein Strom – so liest jedes Programm die Datei."""
    with pikepdf.open(samples.standard_text(tmp_path / "c.pdf")) as pdf:
        buffer = io.BytesIO()
        pdf.save(buffer, object_stream_mode=pikepdf.ObjectStreamMode.generate)
    first = digsig.sign_pdf(buffer.getvalue(), signer)
    with pikepdf.open(io.BytesIO(first)) as pdf:  # neu geschrieben: Objektströme sind weg
        assert digsig.signatures_present(pdf)
    second = digsig.sign_pdf(first, signer)
    assert second.startswith(first)
    assert [report.status for report in digsig.verify_pdf(second)] == [digsig.CHANGED, digsig.VALID]


def test_pdf_dates() -> None:
    moment = digsig.parse_pdf_date("D:20261020083000+02'00'")
    assert moment is not None and moment.hour == 8 and moment.utcoffset().total_seconds() == 7200
    assert digsig.parse_pdf_date("D:20261020083000Z").utcoffset().total_seconds() == 0
    assert digsig.parse_pdf_date("kein Datum") is None


# Windows: Zertifikatspeicher ---------------------------------------------------------------------------------------

windows = pytest.mark.skipif(sys.platform != "win32", reason="nur unter Windows")


def _powershell(script: str) -> str:
    # Windows PowerShell 5.1 aus einem pwsh-7-Schritt: ohne dessen PSModulePath, sonst fehlt das Laufwerk »Cert:«
    env = {key: value for key, value in os.environ.items() if key.upper() != "PSMODULEPATH"}
    result = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", "Import-Module Microsoft.PowerShell.Security; " + script],
                            capture_output=True, text=True, timeout=120, env=env)
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


@pytest.fixture
def store_certificates():
    """Zwei selbst ausgestellte Zertifikate in »Eigene Zertifikate«: Schlüssel in CNG und in der alten CryptoAPI."""
    made = {}
    for key, provider in (("cng", "Microsoft Software Key Storage Provider"), ("capi", "Microsoft Enhanced RSA and AES Cryptographic Provider")):
        made[key] = _powershell(
            f"(New-SelfSignedCertificate -Subject 'CN=PDF Tool Test {key}' -CertStoreLocation Cert:\\CurrentUser\\My "
            f"-Provider '{provider}' -KeyUsage DigitalSignature -KeyAlgorithm RSA -KeyLength 2048 -NotAfter (Get-Date).AddDays(2)).Thumbprint"
        )
    yield made
    for thumbprint in made.values():
        _powershell(f"Remove-Item -Path Cert:\\CurrentUser\\My\\{thumbprint} -DeleteKey -ErrorAction SilentlyContinue")


@windows
def test_windows_store_signs_with_cng_and_cryptoapi_keys(tmp_path: Path, store_certificates) -> None:
    from tools.pdf_editor import winsign

    listed = {item.thumbprint: item for item in winsign.certificates()}
    source = samples.standard_text(tmp_path / "d.pdf").read_bytes()
    for key, thumbprint in store_certificates.items():
        assert thumbprint in listed, f"{key}: Zertifikat wird nicht angeboten"
        assert listed[thumbprint].subject == f"PDF Tool Test {key}" and listed[thumbprint].self_signed
        store_signer = winsign.StoreSigner(thumbprint)
        try:
            signed = digsig.sign_pdf(source, store_signer)
        finally:
            store_signer.close()
        [report] = digsig.verify_pdf(signed)
        assert report.status == digsig.VALID, (key, report.detail)
        assert report.signer == f"PDF Tool Test {key}"
        assert report.trust == "untrusted" and "selbst ausgestellt" in report.trust_detail  # Windows kennt den Aussteller nicht


@windows
def test_windows_trusts_a_certificate_from_a_known_authority() -> None:
    """Gegenprobe der Kettenprüfung mit einem Zertifikat, dem Windows vertraut: dem Stammzertifikat selbst."""
    from tools.pdf_editor import winsign

    store = winsign.crypt32.CertOpenSystemStoreW(None, "ROOT")
    context = winsign.crypt32.CertEnumCertificatesInStore(store, None)
    found = None
    while context:
        der = winsign._der(context)
        from datetime import datetime, timezone

        try:
            info = digsig.cert_info(der)
        except ValueError:  # fehlerhaft kodierte Stammzertifikate gibt es (ROOT-Speicher der CI)
            context = winsign.crypt32.CertEnumCertificatesInStore(store, context)
            continue
        if info.self_signed and info.valid_at(datetime.now(timezone.utc)) and "Microsoft" in info.subject:
            found = der
            break
        context = winsign.crypt32.CertEnumCertificatesInStore(store, context)
    winsign.crypt32.CertCloseStore(store, 0)
    if found is None:
        pytest.skip("kein Microsoft-Stammzertifikat im Speicher")
    level, _text = winsign.trust(found, [], None)
    assert level == "trusted"
