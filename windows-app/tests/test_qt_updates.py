"""Qt-Oberfläche: Updates – Einstellungen, Hinweisleiste, Details, Download, Installation.

Gegen einen lokalen Testserver (``updateserver.py``), nie gegen GitHub; der Hilfsprozess, der das
Setup startet, ist eine Attrappe (``conftest.FakeLauncher``). Geprüft werden u. a. die Tests 82–99
der Vorgabe aus Sicht der Oberfläche: Start ohne Warten, offline still, 24-Stunden-Regel,
manuelle Prüfung, Kanalwechsel ohne Neustart mit Beta-Rückfrage, Persistenz, Hinweis einmal je
Version, Details mit sicheren Release Notes, Fortschritt, Abbruch, Doppelklick, Bereit,
»Jetzt installieren« (nicht während einer Verarbeitung), Animationsprofile.
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from conftest import _prepare, neustart, pump, wait_until
from qtutil import Harness, process_events
from updateserver import UpdateServer

from qtapp import dialogs, files, updates
from updater.policy import UrlPolicy
from updater.service import UpdateService
from updater.store import UpdateStore
from updater.transport import HttpClient

NOTES = "## Neu\n\n- Schnellere Analyse\n- Details auf [GitHub](https://github.com/Jerico3241/PDF-Tool)\n\n<script>alert(1)</script>\n![x](https://tracker.example/p.png)"


@pytest.fixture
def server():
    server = UpdateServer()
    yield server
    server.stop()


@pytest.fixture
def start(request, qt_application, config_file: Path, monkeypatch, server, tmp_path):
    """``start(profile="full", auto=False, **config)`` – App mit Updater am lokalen Testserver."""
    harnesses: list[Harness] = []
    folder = tmp_path / "updates"

    def create(app, installed):
        client = HttpClient(UrlPolicy.loopback(server.port), user_agent="PDF-Tool/Test", system_proxy=False)
        return UpdateService(installed, client, UpdateStore(folder, site=server.base), app.worker.run, releases_url=server.releases_url, site=server.base)

    def launch(profile: str = "full", auto: bool = False, **config) -> Harness:
        _prepare(config_file, monkeypatch, profile, config)
        monkeypatch.setattr(updates, "create_service", create)
        monkeypatch.setattr(updates, "START_DELAY_MS", 100 if auto else 3_600_000)
        monkeypatch.setattr(updates, "BANNER_DELAY_MS", 0)
        harness = Harness(ui=True)
        harness.holder = {"current": harness}
        harnesses.append(harness)
        return harness

    launch.folder = folder
    yield launch
    for harness in harnesses:
        current = harness.holder["current"]
        messages = current.messages()
        if current.runtime is not None:
            current.close()
        assert not messages, "QML-Meldungen:\n" + "\n".join(messages)


def u(h):
    return h.runtime.updates


def settle(h, *states: str, timeout: float = 30) -> str:
    assert wait_until(lambda: u(h).state in states and not u(h).service.checking, timeout), f"Zustand {u(h).state} statt {states}"
    pump(0.05)
    return u(h).state


def config(config_file: Path) -> dict:
    return json.loads(config_file.read_text(encoding="utf-8"))


def requests(server) -> int:
    return server.count("/repositories/1382108244/releases")


# --- Einstellungen und Start ---------------------------------------------------------------------------------------


def test_settings_show_version_channel_automatic_and_last_check(start):
    h = start()
    h.navigate("settings", 0.3)
    assert u(h).currentVersion == "2.7.2" and not u(h).currentBeta
    assert h.item("updateCurrentVersion").property("text") == "PDF Tool 2.7.2"
    assert h.item("updateLastCheck").property("text") == "Letzte Prüfung: Noch nie"
    assert u(h).channel == "stable" and h.item("updateChannelCombo").property("currentText") == "Stable"
    assert u(h).automatic and h.item("updateAutomaticToggle").property("checked")
    assert h.item("updateCheckButton").property("enabled")


def test_08_start_never_waits_for_the_network(start, server):
    server.silent.add("/repositories/1382108244/releases")  # GitHub antwortet nicht
    began = time.monotonic()
    h = start(auto=True)
    assert h.app.ready and time.monotonic() - began < 20
    assert u(h).state == "idle" and not u(h).bannerShown
    assert wait_until(lambda: requests(server) == 1, 10)  # die Prüfung läuft danach im Hintergrund
    assert u(h).state == "idle"  # unsichtbar: keine Anzeige »wird gesucht«, keine Fehlermeldung
    h.navigate("repair", 0.2)
    assert h.app.currentPage == "repair"  # die App bleibt bedienbar


def test_93_offline_start_is_silent_and_manual_check_explains(start, monkeypatch):
    h = start()
    # kein Netzwerk: die Adresse ist nicht erreichbar
    u(h).service.releases_url = "http://127.0.0.1:1/repositories/1382108244/releases"
    u(h).service.client.policy = UrlPolicy.loopback(1)
    u(h)._auto_check()  # wie die automatische Prüfung nach dem Start
    assert wait_until(lambda: u(h).service.auto_failed, 15)
    assert u(h).state == "idle" and not u(h).bannerShown and u(h).statusKind == "neutral"
    h.navigate("settings", 0.2)
    u(h).checkNow()
    assert settle(h, "error") == "error"
    assert u(h).statusTitle == "Updates konnten derzeit nicht geprüft werden."
    assert h.item("updateStatusTitle").property("text") == "Updates konnten derzeit nicht geprüft werden."
    assert u(h).lastCheck == "Noch nie"  # eine fehlgeschlagene Prüfung zählt nicht


def test_automatic_check_finds_update_and_announces_it_once(start, server, config_file):
    server.publish("2.7.3", notes=NOTES)
    h = start(auto=True)
    assert settle(h, "available") == "available"
    assert wait_until(lambda: u(h).bannerShown, 5)
    assert u(h).bannerTitle == "PDF Tool 2.7.3 ist verfügbar."
    assert h.item("updateBannerTitle").property("text") == "PDF Tool 2.7.3 ist verfügbar."
    assert requests(server) == 1
    assert config(config_file)["update_letzte_pruefung"].endswith("Z")
    banners = []
    for page in ("create", "repair", "batch", "home"):
        h.navigate(page, 0.15)
        banners.append(len(h.items("updateBanner")))
    assert banners == [1, 1, 1, 1] and u(h).bannerShown  # eine Leiste, kein neuer Hinweis je Seite
    h.navigate("settings", 0.2)
    assert not u(h).bannerShown  # die Einstellungen zeigen alles selbst
    assert h.item("updateOffer").property("visible") and h.item("updateOfferTitle").property("text") == "PDF Tool 2.7.3"
    assert requests(server) == 1


def test_98_24_hour_rule_and_manual_check(start, server):
    server.publish("2.7.3")
    vor_einer_stunde = (datetime.now(timezone.utc) - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    h = start(auto=True, update_letzte_pruefung=vor_einer_stunde)
    pump(1.0)
    u(h)._auto_check()
    pump(0.3)
    assert requests(server) == 0  # < 24 Stunden: kein Aufruf
    assert u(h).lastCheck.startswith("Heute, ") or u(h).lastCheck.startswith("Gestern, ")
    u(h).checkNow()  # der Knopf prüft trotzdem
    assert settle(h, "available") == "available" and requests(server) == 1


def test_automatic_off_means_no_request(start, server):
    server.publish("2.7.3")
    h = start(auto=True, update_automatisch=False)
    pump(0.8)
    assert requests(server) == 0 and u(h).state == "idle"
    assert u(h).statusTitle == "Automatische Prüfung ist ausgeschaltet."


def test_97_settings_persist_across_restart(start, config_file):
    h = start()
    u(h).setAutomatic(False)
    u(h).setChannel("beta")  # Rückfrage: »Beta verwenden« (AUTO_ANSWER = primary)
    data = config(config_file)
    assert data["update_automatisch"] is False and data["update_kanal"] == "beta" and data["update_beta_bestaetigt"] is True
    h = neustart(h)
    assert u(h).channel == "beta" and not u(h).automatic


# --- Kanäle ---------------------------------------------------------------------------------------------------------


def test_20_beta_needs_confirmation_once(start, monkeypatch, config_file):
    h = start()
    monkeypatch.setattr(dialogs, "AUTO_ANSWER", "close")  # »Abbrechen«
    u(h).setChannel("beta")
    assert u(h).channel == "stable" and config(config_file).get("update_kanal", "stable") == "stable"
    frage = h.app.dialogs.history[-1]
    assert frage["kind"] == "confirm" and frage["title"] == "Beta-Versionen verwenden?" and frage["primary"] == "Beta verwenden"
    assert "instabiler" in frage["message"]
    monkeypatch.setattr(dialogs, "AUTO_ANSWER", "primary")
    u(h).setChannel("beta")
    assert u(h).channel == "beta"
    gefragt = len(h.app.dialogs.history)
    u(h).setChannel("stable")
    u(h).setChannel("beta")  # nicht noch einmal fragen
    assert len(h.app.dialogs.history) == gefragt and u(h).channel == "beta"
    h.navigate("settings", 0.2)
    assert h.item("updateChannelCombo").property("currentText") == "Beta"


def test_81_channel_switch_works_without_restart(start, server):
    server.publish("2.7.3")
    server.publish("2.8.0-beta.1")
    h = start()
    u(h).checkNow()
    assert settle(h, "available") == "available" and u(h).offerTitle == "PDF Tool 2.7.3"
    u(h).setChannel("beta")
    assert settle(h, "available") == "available" and u(h).offerTitle == "PDF Tool 2.8.0-beta.1"
    assert u(h).offerBeta and u(h).offerLabel == "2.8.0 Beta 1"
    assert u(h).bannerTitle == "PDF Tool 2.8.0 Beta 1 ist verfügbar."
    u(h).setChannel("stable")
    assert u(h).offerTitle == "PDF Tool 2.7.3" and not u(h).offerBeta


def test_19_newer_beta_installed_and_switched_to_stable(start, server, monkeypatch):
    monkeypatch.setattr(updates, "VERSION", "2.8.0-beta.3")
    server.publish("2.7.2")
    h = start(update_kanal="beta", update_beta_bestaetigt=True)
    assert u(h).currentBeta and u(h).currentVersion == "2.8.0-beta.3"
    u(h).setChannel("stable")
    u(h).checkNow()
    assert settle(h, "up_to_date") == "up_to_date"  # kein Downgrade auf 2.7.2
    assert u(h).hint.startswith("Sie verwenden derzeit eine neuere Beta-Version.")
    h.navigate("settings", 0.2)
    assert h.item("updateChannelHint").property("visible")
    assert h.item("updateCurrentBeta").property("text") == "Beta"


def test_53_54_beta_user_stays_on_beta_after_stable_update(start, server, monkeypatch, config_file):
    """Nach dem Update von 2.8.0-beta.3 auf 2.8.0 (Stable) bleibt der Kanal Beta – 2.8.1-beta.1 kommt."""
    monkeypatch.setattr(updates, "VERSION", "2.8.0")
    server.publish("2.8.0")
    server.publish("2.8.1-beta.1")
    h = start(update_kanal="beta", update_beta_bestaetigt=True)
    u(h).checkNow()
    assert settle(h, "available") == "available" and u(h).offerTitle == "PDF Tool 2.8.1-beta.1"
    assert config(config_file)["update_kanal"] == "beta"


# --- Details und Release Notes ----------------------------------------------------------------------------------------


def test_28_29_30_details_with_safe_release_notes(start, server, monkeypatch):
    server.publish("2.7.3", notes=NOTES)
    h = start()
    u(h).checkNow()
    settle(h, "available")
    monkeypatch.setattr(dialogs, "AUTO_ANSWER", "close")  # »Später«
    u(h).showDetails()
    request = h.app.dialogs.history[-1]
    assert request["kind"] == "update_details" and request["primary"] == "Herunterladen" and request["close"] == "Später"
    data = request["data"]
    assert (data["version"], data["channel"], data["installed"], data["date"]) == ("2.7.3", "Stable", "2.7.2", "01.10.2026")
    assert data["size"].endswith("KB") or data["size"].endswith("MB")
    markup = "".join(block["html"] for block in data["blocks"])
    assert "<script" not in markup and "<img" not in markup and "[Bild: x]" in markup
    assert '<a href="https://github.com/Jerico3241/PDF-Tool">GitHub</a>' in markup
    assert u(h).state == "available"  # »Später«: nichts geladen
    # Links nur https und nur nach einem Klick
    u(h).openLink("javascript:alert(1)")
    u(h).openLink("http://example.com")
    assert files.URLS == []
    u(h).openLink("https://github.com/Jerico3241/PDF-Tool")
    assert files.URLS == ["https://github.com/Jerico3241/PDF-Tool"]


def test_details_dialog_renders_notes_in_qml(start, server, monkeypatch):
    server.publish("2.7.3", notes=NOTES)
    h = start()
    u(h).checkNow()
    settle(h, "available")
    monkeypatch.setattr(dialogs, "AUTO_ANSWER", None)
    from PySide6.QtCore import QTimer

    seen = {}

    def look():
        details = h.item("updateDetails")
        seen["version"] = h.item("updateDetailsVersion").property("text") if details else None
        seen["blocks"] = len([item for item in h.item("updateNotes").childItems() if item.property("kind")]) if details else 0
        h.app.dialogs.answer(h.app.dialogs.request["id"], "close", {})

    QTimer.singleShot(400, look)
    u(h).showDetails()
    assert seen == {"version": "2.7.3", "blocks": 4}  # Überschrift, 2 Punkte, ein Absatz (Skript als Text, Bild-Ersatz)


# --- Download, Abbruch, Bereit, Installation ----------------------------------------------------------------------------


def test_download_progress_ready_and_install(start, server, config_file):
    server.publish("2.7.3", setup=b"MZ" + os.urandom(2 * 1024 * 1024))
    server.delay = 0.01
    h = start()
    u(h).checkNow()
    settle(h, "available")
    assert wait_until(lambda: u(h).bannerShown, 5)
    texts = []
    u(h).progressTextChanged.connect(lambda: texts.append(u(h).progressText))
    u(h).download()
    assert u(h).state == "downloading" and h.item("updateBannerProgress").property("visible")
    assert settle(h, "ready") == "ready"
    assert any(" von " in text and text.endswith("%") for text in texts)
    assert u(h).bannerTitle == "Update ist bereit zur Installation." and u(h).canInstall
    assert u(h).statusText.endswith("Prüfsumme bestätigt (SHA-256)")
    setup = start.folder / "PDF-Tool-Setup-2.7.3.exe"
    assert setup.is_file()
    u(h).setAutomatic(False)  # eine Einstellung, die beim Beenden gespeichert sein muss
    u(h).installNow()
    assert wait_until(lambda: updates.LAUNCHES, 10)
    call = updates.LAUNCHES[0]
    assert call["setup"] == setup and call["pid"] == os.getpid() and len(call["sha256"]) == 64
    assert call["log"] == start.folder / "update-start.log"
    assert h.app.closing  # App beendet wie über das Schließen-Kreuz – Einstellungen gespeichert
    assert config(config_file)["update_automatisch"] is False
    assert not call["helper"].terminated


def test_96_install_waits_for_running_repair(start, server, tmp_path):
    import pdfsamples as samples

    server.publish("2.7.3")
    h = start()
    u(h).checkNow()
    settle(h, "available")
    u(h).download()
    settle(h, "ready")
    pdf = samples.healthy(tmp_path / "gross.pdf", pages=40)
    h.repair.add([str(pdf)])
    assert "PDF-Reparatur" in h.app.running_work()  # Analyse läuft im Arbeitsprozess
    u(h).installNow()
    assert u(h).state == "ready" and not updates.LAUNCHES and not h.app.closing
    assert u(h).workHint.startswith("Es läuft noch eine Verarbeitung. Bitte warten Sie, bis diese abgeschlossen ist, oder brechen Sie sie ab.")
    assert u(h).bannerKind == "warning" and u(h).bannerText == u(h).workHint
    assert wait_until(lambda: not h.app.running_work(), 60)
    u(h).installNow()
    assert wait_until(lambda: updates.LAUNCHES, 10) and h.app.closing


def test_install_is_undone_when_closing_is_refused(start, server, monkeypatch):
    server.publish("2.7.3")
    h = start()
    u(h).checkNow()
    settle(h, "available")
    u(h).download()
    settle(h, "ready")
    monkeypatch.setattr(h.app, "requestClose", lambda: False)
    monkeypatch.setattr(h.app, "window", None)
    u(h).installNow()
    assert wait_until(lambda: updates.LAUNCHES, 10)
    assert updates.LAUNCHES[0]["helper"].terminated  # Hilfsprozess beendet – kein Setup
    assert u(h).state == "ready" and not h.app.closing


def test_92_cancel_in_the_banner(start, server):
    server.publish("2.7.3", setup=b"MZ" + os.urandom(3 * 1024 * 1024))
    server.delay = 0.02
    h = start()
    u(h).checkNow()
    settle(h, "available")
    u(h).download()
    assert wait_until(lambda: u(h).service.received > 64 * 1024, 20)
    assert h.item("updateBannerCancel").property("visible")
    u(h).cancel()  # »Abbrechen« in der Hinweisleiste
    assert wait_until(lambda: u(h).state == "cancelled", 5)
    pump(0.2)
    assert not (start.folder / "PDF-Tool-Setup-2.7.3.exe.part").exists() and not (start.folder / "PDF-Tool-Setup-2.7.3.exe").exists()
    assert u(h).bannerTitle == "Download abgebrochen." and u(h).canDownload


def test_95_double_click_downloads_once(start, server):
    server.publish("2.7.3")
    server.delay = 0.005
    h = start()
    u(h).checkNow()
    settle(h, "available")
    for _ in range(3):
        u(h).download()
    settle(h, "ready")
    assert u(h).service.downloads == 1


def test_91_wrong_checksum_shows_error_and_never_offers_install(start, server):
    server.publish("2.7.3", checksum="0" * 64 + "  PDF-Tool-Setup-2.7.3.exe\n", digest=None)
    h = start()
    u(h).checkNow()
    settle(h, "available")
    u(h).download()
    assert settle(h, "error") == "error"
    assert u(h).statusTitle == "Das heruntergeladene Update konnte nicht verifiziert werden und wurde daher nicht installiert."
    assert not u(h).canInstall and u(h).canDownload  # »Erneut versuchen«
    assert u(h).bannerKind == "error"
    u(h).installNow()
    assert not updates.LAUNCHES


def test_73_later_hides_banner_until_next_start(start, server):
    server.publish("2.7.3")
    h = start()
    u(h).checkNow()
    settle(h, "available")
    assert wait_until(lambda: u(h).bannerShown, 5)
    u(h).later()
    assert not u(h).bannerShown
    for page in ("create", "home"):
        h.navigate(page, 0.15)
        assert not u(h).bannerShown
    assert u(h).state == "available"  # Update bleibt verfügbar
    count = requests(server)
    h = neustart(h)
    assert u(h).state == "available" and requests(server) == count  # aus der letzten Prüfung, ohne Anfrage
    assert wait_until(lambda: u(h).bannerShown, 5)


def test_44_ready_update_survives_restart_without_download(start, server):
    server.publish("2.7.3")
    h = start()
    u(h).checkNow()
    settle(h, "available")
    u(h).download()
    settle(h, "ready")
    loads = server.count("/storage/")
    h = neustart(h)
    assert settle(h, "ready") == "ready"
    assert server.count("/storage/") == loads


@pytest.mark.parametrize("profile", ["full", "reduced", "off"])
def test_77_banner_follows_the_motion_profile(start, server, profile):
    server.publish("2.7.3")
    h = start(profile=profile)
    u(h).checkNow()
    settle(h, "available")
    banner = h.item("updateBanner")
    bar = h.item("updateBannerBar")
    assert wait_until(lambda: bar.property("opacity") > 0.99 and banner.property("visible"), 3)
    u(h).later()
    assert wait_until(lambda: not banner.property("visible") and banner.property("height") == 0, 3)


def test_94_slow_download_keeps_the_ui_responsive(start, server):
    server.publish("2.7.3", setup=b"MZ" + os.urandom(1024 * 1024))
    server.chunk = 16 * 1024
    server.delay = 0.02
    h = start()
    u(h).checkNow()
    settle(h, "available")
    u(h).download()
    longest, last = 0.0, time.monotonic()
    while u(h).state != "ready" and time.monotonic() - last < 30:
        process_events(10)
        now = time.monotonic()
        longest, last = max(longest, now - last), now
    assert u(h).state == "ready"
    assert longest < 0.5, f"Oberfläche blockiert ({longest:.2f} s)"


def test_about_shows_the_full_version(start):
    h = start()
    h.app.showAbout()
    data = h.app.dialogs.history[-1]["data"]
    assert data["version"] == "2.7.2" and data["beta"] is False
