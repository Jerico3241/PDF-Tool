"""Update aus Sicht der Anwender: eine installierte Version findet die veröffentlichte neue Version
in ihrem Update-Kanal und wird darauf aktualisiert – gegen die echte Release-Liste von GitHub
(nur lesend). Aufruf im manuellen Workflow »Update-Test« (``update-test.yml``), z. B.
2.7.2 → 2.8.0-beta.1 (Kanal „Beta“), 2.7.2 → 2.8.0 (Kanal „Stable“), 2.8.0-beta.1 → 2.8.0 (Kanal „Beta“):

1. ``--phase vorbereiten`` – Benutzerdaten einer 2.7.2-Installation anlegen
   (``fixtures/config_v272.json``: zwei Vorlagen im alten Format) mit dem Update-Kanal ``--kanal``.
   Bringt die installierte Version (``--app``) schon Vorlagen 2.0 mit (ab 2.8.0-beta.1), startet sie
   einmal ohne Fenster wie nach ihrer Installation und übernimmt die Vorlagen selbst. Bricht ab,
   wenn es schon Benutzerdaten gibt (nie fremde Daten überschreiben).
2. ``--phase suchen`` – mit der Laufzeit **und dem Updater-Code der installierten Version**
   (``--app``), also genau dem Weg ihrer App:

   * Kanal „Stable“: Eine Vorabversion wird nie angeboten.
   * Kanal ``--kanal``: Die erwartete Version (``--expect``) wird angeboten (eine Beta als
     GitHub-Vorabversion, eine stabile Version als normales Release), heruntergeladen, per SHA-256
     geprüft und ist »bereit«; »Jetzt installieren« prüft erneut und übergibt das Setup. Pfad und
     SHA-256 stehen danach in ``--result``.

   Das Setup startet der Workflow anschließend still (``/VERYSILENT``). In der App startet es der
   Hilfsprozess sichtbar, sobald die App beendet ist – das prüft der Updater-E2E-Test des Workflows
   »Windows-Setup« mit jedem Build.
3. ``--phase danach`` – mit der Laufzeit der neuen Version: Version, Programmstart ohne Fenster
   (Daten laden wie beim echten Start), Update-Kanal und Einstellungen erhalten, Vorlagen genau
   einmal als Vorlagen 2.0 übernommen und die bisherige Liste unverändert, heruntergeladenes Setup
   aufgeräumt.

Endet mit Code 0 und »OK«, sonst mit einer Fehlermeldung und Code 1.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
FIXTURE = HERE / "fixtures" / "config_v272.json"
CHANNELS = {"stable": "Stable", "beta": "Beta"}
# Übernahme der Vorlagen bis 2.7 in Vorlagen 2.0 – vorhanden ab 2.8.0-beta.1
MIGRATION = Path("tools") / "contract_overview" / "templates" / "migration.py"
# Einstellungen, die ein Update nie verändern darf
KEPT = ("firmenname", "kundennummer", "rechnungsempfaenger", "titel", "untertitel", "fusszeile", "kopfzeile", "regeln", "bausteine", "vorlagen", "kundenakte_verwenden", "update_kanal", "update_beta_bestaetigt", "update_automatisch")


def check(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"FEHLER: {message}")


def data_dir() -> Path:
    base = os.environ.get("APPDATA")
    check(bool(base), "APPDATA fehlt – nur unter Windows")
    return Path(base) / "PDF-Tool"


def read_config(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def use_app(app_dir: Path):
    """Code der installierten Version verwenden (Programmordner ``…\\PDF-Tool\\app``)."""
    sys.path.insert(0, str(app_dir))
    import appstate

    return appstate


def start(appstate):
    """Programmstart ohne Fenster wie beim echten Start: Daten laden, Vorlagen übernehmen …"""
    from qtapp import application as appmod

    qt = appmod.create_application([])
    appmod.start_log()
    outcome = appmod.prepare_data()
    check(outcome is None, f"Unerwartete Wiederherstellung beim Start: {outcome}")
    return qt, appmod.Runtime(appstate.load_config())


def prepare(app_dir: Path | None, channel: str) -> None:
    folder = data_dir()
    check(not folder.exists(), f"Es gibt schon Benutzerdaten ({folder}) – der Test braucht einen frischen Rechner")
    cfg = read_config(FIXTURE)
    cfg["update_kanal"] = channel
    if channel != "beta":
        cfg.pop("update_beta_bestaetigt", None)  # Kanal „Beta“ nie bestätigt
    folder.mkdir(parents=True)
    config = folder / "gui-config.json"
    config.write_text(json.dumps(cfg, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"Benutzerdaten angelegt: Kanal „{CHANNELS[channel]}“, Vorlagen {[entry['name'] for entry in cfg['vorlagen']]}")
    if app_dir is None or not (app_dir / MIGRATION).is_file():
        return  # Version ohne Vorlagen 2.0 (bis 2.7): die neue Version übernimmt sie
    appstate = use_app(app_dir)
    qt, runtime = start(appstate)
    try:
        names = sorted(template.name for template in runtime.app.state.templates.templates())
    finally:
        runtime.app.shutdown()
    saved = read_config(config)
    check(saved.get("vorlagen_2") == appstate.VERSION, f"PDF Tool {appstate.VERSION} hat die Vorlagen nicht übernommen: {saved.get('vorlagen_2')}")
    check(saved.get("update_kanal") == channel, f"Update-Kanal nach dem ersten Start: {saved.get('update_kanal')}")
    print(f"Erster Start von PDF Tool {appstate.VERSION} ohne Fenster: Vorlagen 2.0 {names}")
    del runtime
    del qt


def search(app_dir: Path, installed_text: str, expected: str, channel_name: str, result_file: Path) -> None:
    appstate = use_app(app_dir)
    from types import SimpleNamespace

    from PySide6.QtCore import QCoreApplication, QEventLoop

    from qtapp import updates
    from qtapp.tasks import Worker
    from updater.models import Channel, UpdateState
    from updater.semver import Version

    qt = QCoreApplication.instance() or QCoreApplication([])

    def wait(condition, timeout: float) -> bool:
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            QCoreApplication.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 20)
            if condition():
                return True
            time.sleep(0.01)
        return bool(condition())

    check(appstate.VERSION == installed_text, f"Installiert ist {appstate.VERSION}, erwartet {installed_text}")
    installed = Version.parse(appstate.VERSION)
    target = Version.parse(expected)
    check(installed < target, f"{expected} ist nicht neuer als die installierte Version {installed}")
    beta_target = bool(target.prerelease)
    label = CHANNELS[channel_name]
    print(f"Installiert: PDF Tool {appstate.VERSION} · Kanal {label} · Python {sys.version.split()[0]} · {sys.executable}")
    worker = Worker()
    app = SimpleNamespace(worker=worker)
    done = (UpdateState.UP_TO_DATE, UpdateState.AVAILABLE, UpdateState.ERROR)

    def checked(channel):
        service = updates.create_service(app, installed)
        service.restore(channel, None)
        check(service.check(manual=True), f"Prüfung ({channel.value}) startet nicht")
        check(wait(lambda: service.state in done, 120), f"Prüfung ({channel.value}) hängt ({service.state.value})")
        check(service.state is not UpdateState.ERROR, f"Prüfung ({channel.value}) fehlgeschlagen: {service.error} {service.error_detail}")
        return service

    # Kanal „Stable“: nie eine Vorabversion
    stable = checked(Channel.STABLE)
    offered = stable.offer
    check(offered is None or (not offered.prerelease and not offered.version.prerelease), f"Stable bietet eine Vorabversion an: {offered.version if offered else ''}")
    print(f"1. Kanal Stable: {'kein Update' if offered is None else f'Angebot {offered.version} (stabil)'} – keine Vorabversion")
    if channel_name == "beta":
        stable.shutdown()
        service = checked(Channel.BETA)
    else:
        service = stable

    # Kanal der Anwender: findet genau die erwartete Version
    check(service.state is UpdateState.AVAILABLE, f"{expected} im Kanal {label} nicht angeboten: {service.state.value} {service.error} {service.error_detail}")
    offer = service.offer
    check(str(offer.version) == expected, f"Falsches Angebot im Kanal {label}: {offer.version} statt {expected}")
    kind = "Vorabversion" if beta_target else "normales Release"
    check(bool(offer.prerelease) == beta_target and bool(offer.version.prerelease) == beta_target, f"Angebot ist auf GitHub kein(e) {kind}")
    check(offer.installer is not None and offer.installer.name == f"PDF-Tool-Setup-{expected}.exe", f"Falsches Setup: {offer.installer}")
    print(f"2. Kanal {label}: Angebot {offer.version} ({kind}), Setup {offer.installer.name}, {offer.installer.size} Bytes")
    check(service.download(), "Download startet nicht")
    check(wait(lambda: service.state in (UpdateState.READY, UpdateState.ERROR), 900), f"Download hängt ({service.state.value})")
    check(service.state is UpdateState.READY, f"Nicht bereit: {service.error} {service.error_detail}")
    print("3. Heruntergeladen und per SHA-256 geprüft: bereit")
    handed: list = []
    check(service.begin_install(lambda path, sha: handed.append((Path(path), sha))), "Installation lässt sich nicht vorbereiten")
    check(wait(lambda: handed, 300), "Erneute Prüfung vor der Installation endet nicht")
    setup, digest = handed[0]
    actual = hashlib.sha256(setup.read_bytes()).hexdigest()
    check(actual == digest, f"Übergebenes Setup weicht ab: {actual} ≠ {digest}")
    print(f"4. »Jetzt installieren«: erneut geprüft, übergeben {setup.name} (SHA-256 {digest})")
    result_file.write_text(json.dumps({"version": expected, "setup": str(setup), "sha256": digest, "size": setup.stat().st_size}), encoding="utf-8")
    service.shutdown()
    worker.shutdown()
    del qt


def after(app_dir: Path, expected: str, channel: str) -> None:
    appstate = use_app(app_dir)
    check(appstate.VERSION == expected, f"Nach dem Update ist {appstate.VERSION} installiert, erwartet {expected}")
    folder = data_dir()
    config = folder / "gui-config.json"
    before = read_config(config)
    legacy = [entry["name"] for entry in before.get("vorlagen") or [] if isinstance(entry, dict) and entry.get("name")]
    # Hat die Vorversion die Vorlagen schon übernommen (ab 2.8.0-beta.1), bleibt es dabei – nie doppelt
    taken_over = before.get("vorlagen_2") or expected
    print(f"Installiert: PDF Tool {appstate.VERSION} · Vorlagen im alten Format: {legacy} · übernommen von: {before.get('vorlagen_2') or '–'}")

    qt, runtime = start(appstate)
    try:
        check(runtime.updates.channel == channel, f"Update-Kanal nach dem Update: {runtime.updates.channel}")
        names = sorted(template.name for template in runtime.app.state.templates.templates())
        check(set(legacy) <= set(names), f"Vorlagen nicht übernommen: {names}")
        print(f"1. Programmstart ohne Fenster: Kanal {CHANNELS[channel]}, Vorlagen 2.0 {names}")
        updates_dir = Path(os.environ["LOCALAPPDATA"]) / "PDF-Tool-Updates"
        leftover = updates_dir / f"PDF-Tool-Setup-{expected}.exe"
        end = time.monotonic() + 30
        while leftover.exists() and time.monotonic() < end:
            qt.processEvents()
            time.sleep(0.05)
        check(not leftover.exists(), f"Heruntergeladenes Setup nicht aufgeräumt: {leftover}")
        print("2. Heruntergeladenes Setup nach dem Update aufgeräumt")
    finally:
        runtime.app.shutdown()
    saved = read_config(config)
    changed = [key for key in KEPT if before.get(key) != saved.get(key)]
    check(not changed, f"Einstellungen verändert: {changed}")
    check(saved.get("vorlagen_2") == taken_over, f"Übernahme der Vorlagen: vermerkt {saved.get('vorlagen_2')}, erwartet {taken_over}")
    files = sorted((folder / "vorlagen").glob("*.json"))
    check(len(files) == len(legacy), f"Vorlagen 2.0: {len(files)} Dateien statt {len(legacy)}")
    print(f"3. Einstellungen erhalten ({len(KEPT)} Schlüssel), bisherige Vorlagenliste unverändert, {len(files)} Vorlagen-Dateien (übernommen von {taken_over})")
    del runtime
    del qt


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--phase", required=True, choices=("vorbereiten", "suchen", "danach"))
    parser.add_argument("--kanal", required=True, choices=tuple(CHANNELS), help="Update-Kanal der Anwender")
    parser.add_argument("--app", type=Path, help="Programmordner der installierten App (…\\PDF-Tool\\app)")
    parser.add_argument("--installed", default="", help="installierte Version (Phase »suchen«)")
    parser.add_argument("--expect", default="", help="erwartete neue Version, z. B. 2.8.0 oder 2.8.0-beta.1")
    parser.add_argument("--result", type=Path, help="Ergebnis der Phase »suchen« (JSON)")
    args = parser.parse_args()
    if args.app is not None or args.phase != "vorbereiten":
        check(args.app is not None and (args.app / "updater" / "service.py").is_file(), f"Programmordner fehlt: {args.app}")
    if args.phase == "vorbereiten":
        prepare(args.app.resolve() if args.app is not None else None, args.kanal)
    else:
        check(bool(args.expect), "--expect fehlt")
        check(args.kanal == "beta" or "-" not in args.expect, f"Kanal „Stable“ bietet nie eine Vorabversion an: {args.expect}")
        if args.phase == "suchen":
            check(bool(args.installed) and args.result is not None, "--installed und --result fehlen")
            search(args.app.resolve(), args.installed, args.expect, args.kanal, args.result)
        else:
            after(args.app.resolve(), args.expect, args.kanal)
    print("OK")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception:  # noqa: BLE001
        import traceback

        traceback.print_exc()
        sys.exit(1)
