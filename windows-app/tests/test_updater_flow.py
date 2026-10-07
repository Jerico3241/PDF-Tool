"""Updater mit Netzwerk – gegen einen lokalen Testserver (``updateserver.py``), nie gegen GitHub.

Geprüft werden Prüfen, Herunterladen, SHA-256-Prüfung, Bereit, Abbruch, Doppelklick, Offline,
langsames Netz, Zeitlimits, Weiterleitungen, Anfragelimit, ungültige Antworten, Download-Cache,
Kanalwechsel ohne Neustart, Installation vorbereiten und der Hilfsprozess, der das Setup erst
nach dem Ende der App startet (Tests 83–95, 98, 103–107 der Vorgabe).
"""

from __future__ import annotations

import hashlib
import logging
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from qtutil import process_events, wait_until
from updateserver import UpdateServer
from updater import installer, launch
from updater.models import Channel, ErrorKind, UpdateState
from updater.policy import UrlPolicy
from updater.semver import Version
from updater.service import UpdateService
from updater.store import UpdateStore
from updater.transport import HttpClient

S = UpdateState


@pytest.fixture
def server():
    server = UpdateServer()
    yield server
    server.stop()


@pytest.fixture(autouse=True)
def messages(monkeypatch) -> list[str]:
    """Hinweise des Hilfsprozesses nur mitschreiben: unter Windows wären es Hinweisfenster, die ohne
    Bildschirm (CI) niemand schließt – der Test bliebe stehen."""
    shown: list[str] = []
    monkeypatch.setattr(launch, "message", shown.append)
    return shown


def make_service(server: UpdateServer, folder: Path, installed: str = "2.7.2", channel: Channel = Channel.STABLE, **timeouts) -> UpdateService:
    from qtapp.tasks import Worker

    client = HttpClient(UrlPolicy.loopback(server.port), user_agent=f"PDF-Tool/{installed}", system_proxy=False, **timeouts)
    worker = Worker()
    service = UpdateService(Version.parse(installed), client, UpdateStore(folder, site=server.base), worker.run, releases_url=server.releases_url, site=server.base)
    service._test_refs = (client, worker)  # am Leben halten
    service.restore(channel, None)
    return service


@pytest.fixture
def service_factory(qt_application, server, tmp_path):
    created: list[UpdateService] = []

    def create(installed: str = "2.7.2", channel: Channel = Channel.STABLE, folder: Path | None = None, **timeouts) -> UpdateService:
        service = make_service(server, folder or tmp_path / "updates", installed, channel, **timeouts)
        created.append(service)
        return service

    yield create
    for service in created:
        service.shutdown()
    process_events(50)


def settle(service: UpdateService, *states: UpdateState, timeout: float = 30) -> UpdateState:
    assert wait_until(lambda: service.state in states and not service.checking, timeout), f"Zustand {service.state} statt {states}"
    return service.state


def files(folder: Path) -> list[str]:
    return sorted(path.name for path in folder.iterdir()) if folder.is_dir() else []


# --- Prüfen ----------------------------------------------------------------------------------------------------------


def test_check_download_verify_ready(server, service_factory, tmp_path):
    setup = server.publish("2.7.3")
    service = service_factory()
    progress: list[tuple[int, int]] = []
    service.progressChanged.connect(lambda: progress.append((service.received, service.total)))
    assert service.check(manual=True) and service.state is S.CHECKING
    assert settle(service, S.AVAILABLE) is S.AVAILABLE
    assert str(service.offer.version) == "2.7.3" and service.last_check is not None
    assert service.download() and service.state is S.DOWNLOADING
    assert settle(service, S.READY) is S.READY
    folder = tmp_path / "updates"
    assert files(folder) == ["PDF-Tool-Setup-2.7.3.exe", "PDF-Tool-Setup-2.7.3.exe.sha256", "releases.json"]
    assert (folder / "PDF-Tool-Setup-2.7.3.exe").read_bytes() == setup
    assert progress[-1] == (len(setup), len(setup))
    assert service.machine.history[-4:] == [S.AVAILABLE, S.DOWNLOADING, S.VERIFYING, S.READY]
    # erst die Prüfsumme, dann das Setup – jede Datei genau einmal
    assert server.count("PDF-Tool-Setup-2.7.3.exe.sha256") == 2  # Weiterleitung + Speicher
    assert server.count("/storage/v2.7.3/PDF-Tool-Setup-2.7.3.exe") == 2  # Setup und Prüfsumme


def test_up_to_date_and_beta_not_offered_to_stable(server, service_factory):
    server.publish("2.7.2")
    server.publish("2.7.3-beta.1")
    service = service_factory()
    service.check(manual=True)
    assert settle(service, S.UP_TO_DATE) is S.UP_TO_DATE and service.offer is None


def test_83_to_85_beta_channel(server, service_factory, tmp_path):
    server.publish("2.7.3-beta.1")
    service = service_factory(channel=Channel.BETA)
    service.check(manual=True)
    settle(service, S.AVAILABLE)
    assert str(service.offer.version) == "2.7.3-beta.1"
    server.publish("2.7.3-beta.2")
    beta = service_factory(installed="2.7.3-beta.1", channel=Channel.BETA, folder=tmp_path / "b")
    beta.check(manual=True)
    settle(beta, S.AVAILABLE)
    assert str(beta.offer.version) == "2.7.3-beta.2"
    server.publish("2.7.3")
    stable_after_beta = service_factory(installed="2.7.3-beta.3", channel=Channel.BETA, folder=tmp_path / "c")
    stable_after_beta.check(manual=True)
    settle(stable_after_beta, S.AVAILABLE)
    assert str(stable_after_beta.offer.version) == "2.7.3"


def test_channel_switch_takes_effect_without_restart_or_request(server, service_factory):
    server.publish("2.7.3")
    server.publish("2.8.0-beta.1")
    service = service_factory()
    service.check(manual=True)
    settle(service, S.AVAILABLE)
    assert str(service.offer.version) == "2.7.3"
    requests = len(server.requests)
    service.set_channel(Channel.BETA)
    assert service.state is S.AVAILABLE and str(service.offer.version) == "2.8.0-beta.1"
    service.set_channel(Channel.STABLE)
    assert str(service.offer.version) == "2.7.3"
    assert len(server.requests) == requests  # ohne neue Anfrage


def test_87_beta_install_switched_to_stable_is_not_downgraded(server, service_factory):
    server.publish("2.7.2")
    service = service_factory(installed="2.8.0-beta.3", channel=Channel.BETA)
    service.check(manual=True)
    settle(service, S.UP_TO_DATE)
    service.set_channel(Channel.STABLE)
    assert service.state is S.UP_TO_DATE and service.offer is None


def test_88_draft_is_invisible_in_both_channels(server, service_factory):
    server.publish("2.7.3", draft=True)
    server.publish("2.8.0-beta.1", draft=True)
    for channel in Channel:
        service = service_factory(channel=channel)
        service.check(manual=True)
        assert settle(service, S.UP_TO_DATE) is S.UP_TO_DATE


class Protokoll(logging.Handler):
    """Meldungen eines Loggers mitschreiben (unabhängig davon, ob ``pdf-tool.log`` eingerichtet ist)."""

    def __init__(self, name: str) -> None:
        super().__init__(logging.INFO)
        self.logger = logging.getLogger(name)
        self.lines: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append(f"{record.name}: {record.getMessage()}")

    def __enter__(self) -> "Protokoll":
        self.level_before = self.logger.level
        self.logger.setLevel(logging.INFO)
        self.logger.addHandler(self)
        return self

    def __exit__(self, *_exc) -> None:
        self.logger.removeHandler(self)
        self.logger.setLevel(self.level_before)


def test_beta_channel_offers_only_marked_beta_tags(server, service_factory, tmp_path):
    """Beta-Kanal: nur ``vX.Y.Z-beta.N`` mit Vorabversions-Markierung – kein unmarkiertes Beta-Tag,
    kein ``-rc``/``-dev``; das Ergebnis steht im Protokoll (Kategorie »update«), ohne Pfade."""
    server.publish("2.7.3-beta.1", prerelease=False)  # versehentlich nicht als Vorabversion markiert
    server.publish("2.7.3-rc.1")
    server.publish("2.7.3-dev.1", prerelease=False)
    with Protokoll("pdftool.update") as protokoll:
        service = service_factory(channel=Channel.BETA)
        service.check(manual=True)
        assert settle(service, S.UP_TO_DATE) is S.UP_TO_DATE and service.offer is None
        server.publish("2.7.3-beta.2")
        service.check(manual=True)
        assert settle(service, S.AVAILABLE) is S.AVAILABLE and str(service.offer.version) == "2.7.3-beta.2"
        service.set_channel(Channel.STABLE)
        assert service.offer is None
    assert "pdftool.update: Prüfung (manuell, Kanal beta): 3 Releases, kein neueres Update" in protokoll.lines
    assert "pdftool.update: Prüfung (manuell, Kanal beta): 4 Releases, Update 2.7.3-beta.2" in protokoll.lines
    assert "pdftool.update: Kanal: beta → stable" in protokoll.lines
    assert not any(str(tmp_path) in line for line in protokoll.lines)


def test_89_release_without_installer_is_ignored(server, service_factory):
    server.publish("2.7.3")
    server.releases[0]["assets"] = [asset for asset in server.releases[0]["assets"] if not asset["name"].endswith(".exe")]
    service = service_factory()
    service.check(manual=True)
    assert settle(service, S.UP_TO_DATE) is S.UP_TO_DATE
    assert service.download() is False


# --- Offline, Zeitlimits, Fehler der API --------------------------------------------------------------------------------


def test_93_offline_manual_check_reports_and_automatic_stays_silent(qt_application, tmp_path):
    from qtapp.tasks import Worker

    client = HttpClient(UrlPolicy.loopback(1), system_proxy=False)
    worker = Worker()
    service = UpdateService(Version.parse("2.7.2"), client, UpdateStore(tmp_path), worker.run, releases_url="http://127.0.0.1:1/repositories/1/releases")
    service.restore(Channel.STABLE, None)
    start = time.monotonic()
    assert service.check(manual=False)
    assert wait_until(lambda: not service.checking, 20)
    assert service.state is S.IDLE and service.error is None and service.auto_failed
    service.check(manual=True)
    assert wait_until(lambda: service.state is S.ERROR, 20)
    assert service.error is ErrorKind.CHECK_FAILED and service.last_check is None
    assert time.monotonic() - start < 15
    service.shutdown()


def test_check_timeout_never_hangs(server, service_factory):
    server.silent.add("/repositories/1382108244/releases")
    service = service_factory(connect_timeout_ms=400, read_timeout_ms=400)
    start = time.monotonic()
    service.check(manual=True)
    assert wait_until(lambda: service.state is S.ERROR, 15)
    assert service.error is ErrorKind.CHECK_FAILED and "timeout" in service.error_detail
    assert time.monotonic() - start < 10


@pytest.mark.parametrize("status", [404, 500, 502])
def test_api_errors_are_handled(server, service_factory, status):
    server.status["/repositories/1382108244/releases"] = status
    service = service_factory()
    service.check(manual=True)
    assert settle(service, S.ERROR) is S.ERROR and service.error is ErrorKind.CHECK_FAILED


def test_rate_limit_is_recognised(server, service_factory):
    server.status["/repositories/1382108244/releases"] = 403
    server.headers["/repositories/1382108244/releases"] = {"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "1790850416"}
    service = service_factory()
    service.check(manual=True)
    assert settle(service, S.ERROR) is S.ERROR and service.error is ErrorKind.RATE_LIMITED


@pytest.mark.parametrize("payload", [b"{kaputt", b'{"message": "Moved"}', b"<html>Wartung</html>", b"[1, 2, 3]"])
def test_107_malformed_release_json(server, service_factory, payload):
    server.raw_releases = payload
    service = service_factory()
    service.check(manual=True)
    state = settle(service, S.ERROR, S.UP_TO_DATE)
    if payload == b"[1, 2, 3]":
        assert state is S.UP_TO_DATE  # gültige Liste ohne brauchbare Releases
    else:
        assert state is S.ERROR and service.error is ErrorKind.CHECK_FAILED


# --- Prüfsumme (Tests 90, 91) ---------------------------------------------------------------------------------------------


def test_91_wrong_sha_never_becomes_ready(server, service_factory, tmp_path):
    server.publish("2.7.3", checksum="0" * 64 + "  PDF-Tool-Setup-2.7.3.exe\n", digest=None)
    service = service_factory()
    service.check(manual=True)
    settle(service, S.AVAILABLE)
    service.download()
    assert settle(service, S.ERROR) is S.ERROR and service.error is ErrorKind.VERIFY_FAILED
    assert files(tmp_path / "updates") == ["releases.json"]  # keine Datei bleibt liegen
    assert service.begin_install(lambda *_args: pytest.fail("darf nie starten")) is False


def test_tampered_download_is_deleted(server, service_factory, tmp_path):
    server.publish("2.7.3")
    server.files[server.storage("2.7.3")] = b"MZ manipuliert" + b"x" * (len(server.files[server.storage("2.7.3")]) - 14)
    service = service_factory()
    service.check(manual=True)
    settle(service, S.AVAILABLE)
    service.download()
    assert settle(service, S.ERROR) is S.ERROR and service.error is ErrorKind.VERIFY_FAILED
    assert files(tmp_path / "updates") == ["releases.json"]


def test_90_missing_sha_file_means_no_installation(server, service_factory, tmp_path):
    server.publish("2.7.3")
    server.status[server.storage("2.7.3", ".sha256")] = 404
    service = service_factory()
    service.check(manual=True)
    settle(service, S.AVAILABLE)
    service.download()
    assert settle(service, S.ERROR) is S.ERROR and service.error is ErrorKind.VERIFY_FAILED
    assert server.count("/storage/v2.7.3/PDF-Tool-Setup-2.7.3.exe") == 1  # nur die Prüfsumme versucht, kein Setup geladen
    assert files(tmp_path / "updates") == ["releases.json"]


def test_empty_sha_file_makes_the_release_incomplete(server, service_factory):
    server.publish("2.7.3", checksum="", digest=None)
    service = service_factory()
    service.check(manual=True)
    assert settle(service, S.UP_TO_DATE) is S.UP_TO_DATE  # nie angeboten
    assert service.download() is False


@pytest.mark.parametrize("inhalt", ["kein hash\n", "0123  PDF-Tool-Setup-2.7.3.exe\n", "3cd865b7b1a82d7045aae23b558c9af319368ace8447b7fcab4f27072f9d3bd9  PDF-Tool-Setup-2.7.2.exe\n"])
def test_107_malformed_or_foreign_sha_file(server, service_factory, inhalt):
    server.publish("2.7.3", checksum=inhalt, digest=None)
    service = service_factory()
    service.check(manual=True)
    settle(service, S.AVAILABLE)
    service.download()
    assert settle(service, S.ERROR) is S.ERROR and service.error is ErrorKind.VERIFY_FAILED


def test_sha_file_contradicting_github_digest_is_rejected(server, service_factory):
    server.publish("2.7.3", digest="f" * 64)
    service = service_factory()
    service.check(manual=True)
    settle(service, S.AVAILABLE)
    service.download()
    assert settle(service, S.ERROR) is S.ERROR and service.error is ErrorKind.VERIFY_FAILED


# --- Download: Abbruch, Doppelklick, Fehler, Weiterleitungen -----------------------------------------------------------------


def test_92_cancel_removes_partial_file_and_restart_downloads_fresh(server, service_factory, tmp_path):
    server.publish("2.7.3", setup=b"MZ" + os.urandom(3 * 1024 * 1024))
    server.delay = 0.02
    service = service_factory()
    service.check(manual=True)
    settle(service, S.AVAILABLE)
    service.download()
    assert wait_until(lambda: service.received > 128 * 1024, 20)
    service.cancel()
    assert service.state is S.CANCELLED
    process_events(100)
    folder = tmp_path / "updates"
    assert not (folder / "PDF-Tool-Setup-2.7.3.exe.part").exists() and not (folder / "PDF-Tool-Setup-2.7.3.exe").exists()
    server.delay = 0
    assert service.download()
    assert settle(service, S.READY) is S.READY
    assert (folder / "PDF-Tool-Setup-2.7.3.exe").read_bytes() == server.files[server.storage("2.7.3")]


def test_95_double_click_starts_one_download(server, service_factory):
    server.publish("2.7.3")
    server.delay = 0.01
    service = service_factory()
    service.check(manual=True)
    settle(service, S.AVAILABLE)
    assert service.download() is True
    assert service.download() is False
    assert service.download() is False
    settle(service, S.READY)
    assert service.downloads == 1
    assert server.count("/storage/v2.7.3/PDF-Tool-Setup-2.7.3.exe") == 2  # Setup einmal, Prüfsumme einmal


def test_94_slow_network_keeps_the_event_loop_responsive(server, service_factory):
    server.publish("2.7.3", setup=b"MZ" + os.urandom(1024 * 1024))
    server.chunk = 16 * 1024
    server.delay = 0.03
    service = service_factory()
    service.check(manual=True)
    settle(service, S.AVAILABLE)
    progress = []
    service.progressChanged.connect(lambda: progress.append((time.monotonic(), service.received, service.total)))
    service.download()
    longest, last = 0.0, time.monotonic()
    while service.state is not S.READY and time.monotonic() - last < 30:
        process_events(10)
        now = time.monotonic()
        longest, last = max(longest, now - last), now
        assert service.state in (S.DOWNLOADING, S.VERIFYING, S.READY)
    assert service.state is S.READY
    assert longest < 0.25, f"Ereignisschleife blockiert ({longest:.2f} s)"
    running = [moment for moment, received, total in progress if 0 < received < total]
    gaps = [b - a for a, b in zip(running, running[1:])]
    assert len(gaps) >= 5 and min(gaps) >= 0.09  # gedrosselt: höchstens etwa zehnmal pro Sekunde


def test_truncated_download_fails_cleanly(server, service_factory, tmp_path):
    server.publish("2.7.3")
    server.truncate[server.storage("2.7.3")] = 100_000
    service = service_factory()
    service.check(manual=True)
    settle(service, S.AVAILABLE)
    service.download()
    assert settle(service, S.ERROR) is S.ERROR and service.error is ErrorKind.DOWNLOAD_FAILED
    assert files(tmp_path / "updates") == ["releases.json"]


def test_107_redirect_to_foreign_or_insecure_target_is_refused(server, service_factory, tmp_path):
    server.publish("2.7.3")
    path = server.download_path("v2.7.3", "PDF-Tool-Setup-2.7.3.exe.sha256")
    for target in ("http://127.0.0.2:%d/storage/x" % server.port, "https://evil.example/x", "file:///etc/passwd"):
        server.redirects[path] = target
        service = service_factory(folder=tmp_path / str(len(target)))
        service.check(manual=True)
        settle(service, S.AVAILABLE)
        service.download()
        assert settle(service, S.ERROR) is S.ERROR, target
        assert service.error in (ErrorKind.DOWNLOAD_FAILED, ErrorKind.VERIFY_FAILED)
        assert "policy" in service.error_detail or "Weiterleitung" in service.error_detail


def test_redirect_loop_is_stopped(server, service_factory):
    server.publish("2.7.3")
    path = server.download_path("v2.7.3", "PDF-Tool-Setup-2.7.3.exe.sha256")
    server.redirects[path] = server.base + path
    service = service_factory()
    service.check(manual=True)
    settle(service, S.AVAILABLE)
    service.download()
    assert settle(service, S.ERROR) is S.ERROR
    assert server.count("PDF-Tool-Setup-2.7.3.exe.sha256") <= 6  # höchstens fünf Weiterleitungen


def test_download_error_offers_retry(server, service_factory):
    server.publish("2.7.3")
    server.status[server.storage("2.7.3")] = 500
    service = service_factory()
    service.check(manual=True)
    settle(service, S.AVAILABLE)
    service.download()
    assert settle(service, S.ERROR) is S.ERROR and service.error is ErrorKind.DOWNLOAD_FAILED
    del server.status[server.storage("2.7.3")]
    assert service.download()  # »Erneut versuchen«
    assert settle(service, S.READY) is S.READY


# --- Download-Cache und Neustart ------------------------------------------------------------------------------------------------


def test_verified_download_is_reused_after_restart(server, service_factory, tmp_path):
    server.publish("2.7.3")
    first = service_factory()
    first.check(manual=True)
    settle(first, S.AVAILABLE)
    first.download()
    settle(first, S.READY)
    first.shutdown()
    downloads = server.count("/storage/")
    again = service_factory()  # gleicher Ordner: Zwischenspeicher und geladenes Setup
    assert settle(again, S.READY) is S.READY
    assert str(again.offer.version) == "2.7.3"
    assert server.count("/storage/") == downloads  # nichts erneut geladen
    assert again.machine.history == [S.IDLE, S.AVAILABLE, S.VERIFYING, S.READY]


def test_cached_setup_with_wrong_hash_is_not_used(server, service_factory, tmp_path):
    server.publish("2.7.3")
    first = service_factory()
    first.check(manual=True)
    settle(first, S.AVAILABLE)
    first.download()
    settle(first, S.READY)
    first.shutdown()
    setup = tmp_path / "updates" / "PDF-Tool-Setup-2.7.3.exe"
    data = bytearray(setup.read_bytes())
    data[1000] ^= 0xFF
    setup.write_bytes(bytes(data))
    again = service_factory()
    assert settle(again, S.ERROR) is S.ERROR and again.error is ErrorKind.VERIFY_FAILED
    assert not setup.exists()


def test_cleanup_removes_old_installers_but_keeps_the_offer(server, service_factory, tmp_path):
    folder = tmp_path / "updates"
    folder.mkdir()
    for name in ("PDF-Tool-Setup-2.7.1.exe", "PDF-Tool-Setup-2.7.1.exe.sha256", "PDF-Tool-Setup-2.7.2.exe", "PDF-Tool-Setup-2.7.3.exe.part", "eigene-notiz.txt"):
        (folder / name).write_bytes(b"x")
    server.publish("2.7.3")
    service = service_factory()
    service.check(manual=True)
    settle(service, S.AVAILABLE)
    service.download()
    settle(service, S.READY)
    assert wait_until(lambda: files(folder) == ["PDF-Tool-Setup-2.7.3.exe", "PDF-Tool-Setup-2.7.3.exe.sha256", "eigene-notiz.txt", "releases.json"], 10), files(folder)


# --- Installation vorbereiten -----------------------------------------------------------------------------------------------------


def test_install_reverifies_and_hands_over_path_and_hash(server, service_factory, tmp_path):
    setup = server.publish("2.7.3")
    service = service_factory()
    service.check(manual=True)
    settle(service, S.AVAILABLE)
    service.download()
    settle(service, S.READY)
    calls = []
    assert service.begin_install(lambda path, digest: calls.append((path, digest)))
    assert service.state is S.INSTALLING
    assert wait_until(lambda: calls, 10)
    path, digest = calls[0]
    assert path == tmp_path / "updates" / "PDF-Tool-Setup-2.7.3.exe" and digest == hashlib.sha256(setup).hexdigest()
    service.install_aborted()
    assert service.state is S.READY


def test_install_refuses_a_file_changed_after_verification(server, service_factory, tmp_path):
    server.publish("2.7.3")
    service = service_factory()
    service.check(manual=True)
    settle(service, S.AVAILABLE)
    service.download()
    settle(service, S.READY)
    (tmp_path / "updates" / "PDF-Tool-Setup-2.7.3.exe").write_bytes(b"MZ anderes Programm")
    calls = []
    service.begin_install(lambda *args: calls.append(args))
    assert wait_until(lambda: service.state is S.ERROR, 10)
    assert not calls and service.error is ErrorKind.VERIFY_FAILED
    assert not (tmp_path / "updates" / "PDF-Tool-Setup-2.7.3.exe").exists()


# --- Hilfsprozess: Setup erst nach dem Ende der App (Test 103) ----------------------------------------------------------------


def fake_setup(folder: Path, version: str = "2.7.3") -> tuple[Path, str]:
    """Ein »Setup«, das beim Start eine Markierung schreibt (unter Linux ein Shell-Skript)."""
    folder.mkdir(parents=True, exist_ok=True)
    setup = folder / f"PDF-Tool-Setup-{version}.exe"
    marker = folder / "gestartet.txt"
    setup.write_text(f"#!/bin/sh\necho gestartet > '{marker}'\n", encoding="utf-8")
    setup.chmod(0o755)
    return setup, hashlib.sha256(setup.read_bytes()).hexdigest()


@pytest.mark.skipif(sys.platform == "win32", reason="Shell-Skript als Setup-Attrappe (Windows: Updater-E2E-Test der CI)")
def test_103_helper_waits_for_the_app_then_starts_the_verified_setup(tmp_path):
    setup, digest = fake_setup(tmp_path)
    app = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(0.8)"])
    log = tmp_path / "start.log"
    helper = installer.Launcher(Path(sys.executable)).start(setup, digest, app.pid, log)
    time.sleep(0.4)
    assert helper.poll() is None and not (tmp_path / "gestartet.txt").exists()  # wartet noch
    app.wait(5)
    assert helper.wait(10) == launch.OK
    assert wait_until(lambda: (tmp_path / "gestartet.txt").exists(), 5)
    text = log.read_text(encoding="utf-8")
    assert "PDF Tool ist beendet." in text and "SHA-256 geprüft" in text and "Setup gestartet: PDF-Tool-Setup-2.7.3.exe" in text


@pytest.mark.skipif(sys.platform == "win32", reason="Shell-Skript als Setup-Attrappe")
def test_helper_refuses_a_changed_setup(tmp_path, messages):
    setup, digest = fake_setup(tmp_path)
    setup.write_text(setup.read_text(encoding="utf-8") + "# verändert\n", encoding="utf-8")
    assert launch.main(["--setup", str(setup), "--sha256", digest, "--wait", "0"]) == launch.NOT_VERIFIED_CODE
    assert not setup.exists() and not (tmp_path / "gestartet.txt").exists()
    assert messages == [launch.NOT_VERIFIED]


def test_helper_refuses_foreign_programs_and_bad_arguments(tmp_path, messages):
    other = tmp_path / "cmd.exe"
    other.write_bytes(b"MZ")
    digest = hashlib.sha256(b"MZ").hexdigest()
    assert launch.main(["--setup", str(other), "--sha256", digest, "--wait", "0"]) == launch.NOT_VERIFIED_CODE
    assert other.exists()  # fremde Dateien werden nie gelöscht
    assert launch.main(["--setup", str(tmp_path / "PDF-Tool-Setup-2.7.3.exe"), "--sha256", "kein-hash"]) == launch.NOT_VERIFIED_CODE
    assert messages == [launch.NOT_VERIFIED, launch.NOT_VERIFIED]  # der Benutzer erfährt es, nichts startet
    assert launch.main([]) == launch.USAGE_CODE


def test_helper_waits_at_most_the_timeout(tmp_path):
    app = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        start = time.monotonic()
        assert launch.wait_for_exit(app.pid, 0.3) is False
        assert time.monotonic() - start < 3
    finally:
        app.kill()
        app.wait(5)
    assert launch.wait_for_exit(app.pid, 1) is True
    assert launch.wait_for_exit(0, 1) is True


def test_helper_command_uses_isolated_mode_without_shell(tmp_path):
    args = installer.command(tmp_path / "PDF-Tool-Setup-2.7.3.exe", "a" * 64, 4242, tmp_path / "start.log", python=Path("pythonw.exe"))
    assert args[:3] == ["pythonw.exe", "-I", str(installer.LAUNCH_SCRIPT)]
    assert args[3:] == ["--setup", str(tmp_path / "PDF-Tool-Setup-2.7.3.exe"), "--sha256", "a" * 64, "--wait", "4242", "--log", str(tmp_path / "start.log")]
