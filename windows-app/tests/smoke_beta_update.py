"""Beta-Update aus Sicht der Anwender: eine installierte stabile Version findet die veröffentlichte
Beta im Update-Kanal „Beta“ und wird darauf aktualisiert – gegen die echte Release-Liste von GitHub
(nur lesend). Aufruf im manuellen Workflow »Beta-Update-Test« (``beta-update-test.yml``):

1. ``--phase vorbereiten`` – Benutzerdaten einer 2.7.2-Installation anlegen
   (``fixtures/config_v272.json``: Kanal „Beta“ bestätigt, zwei Vorlagen im alten Format). Bricht
   ab, wenn es schon Benutzerdaten gibt (nie fremde Daten überschreiben).
2. ``--phase suchen`` – mit der Laufzeit **und dem Updater-Code der installierten Vorversion**
   (``--app``), also genau dem Weg ihrer App:

   * Kanal „Stable“: Die Beta wird nicht angeboten.
   * Kanal „Beta“: Die erwartete Beta (``--expect``) wird angeboten (GitHub-Vorabversion),
     heruntergeladen, per SHA-256 geprüft und ist »bereit«; »Jetzt installieren« prüft erneut und
     übergibt das Setup. Pfad und SHA-256 stehen danach in ``--result``.

   Das Setup startet der Workflow anschließend still (``/VERYSILENT``). In der App startet es der
   Hilfsprozess sichtbar, sobald die App beendet ist – das prüft der Updater-E2E-Test des Workflows
   »Windows-Setup« mit jedem Build.
3. ``--phase danach`` – mit der Laufzeit der neuen Version: Version, Programmstart ohne Fenster
   (Daten laden wie beim echten Start), Update-Kanal und Einstellungen erhalten, Vorlagen einmalig
   als Vorlagen 2.0 übernommen und die bisherige Liste unverändert, heruntergeladenes Setup
   aufgeräumt.

Endet mit Code 0 und »OK«, sonst mit einer Fehlermeldung und Code 1.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
FIXTURE = HERE / "fixtures" / "config_v272.json"
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


def prepare() -> None:
    folder = data_dir()
    check(not folder.exists(), f"Es gibt schon Benutzerdaten ({folder}) – der Test braucht einen frischen Rechner")
    folder.mkdir(parents=True)
    shutil.copyfile(FIXTURE, folder / "gui-config.json")
    cfg = read_config(folder / "gui-config.json")
    check(cfg.get("update_kanal") == "beta" and cfg.get("update_beta_bestaetigt") is True, "Fixture: Kanal „Beta“ fehlt")
    print(f"Benutzerdaten angelegt: Kanal „Beta“, Vorlagen {[entry['name'] for entry in cfg['vorlagen']]}")


def search(app_dir: Path, installed_text: str, expected: str, result_file: Path) -> None:
    sys.path.insert(0, str(app_dir))
    from types import SimpleNamespace

    from PySide6.QtCore import QCoreApplication, QEventLoop

    from appstate import VERSION
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

    check(VERSION == installed_text, f"Installiert ist {VERSION}, erwartet {installed_text}")
    installed = Version.parse(VERSION)
    print(f"Installiert: PDF Tool {VERSION} · Python {sys.version.split()[0]} · {sys.executable}")
    worker = Worker()
    app = SimpleNamespace(worker=worker)
    done = (UpdateState.UP_TO_DATE, UpdateState.AVAILABLE, UpdateState.ERROR)

    # Kanal „Stable“: nie eine Beta
    stable = updates.create_service(app, installed)
    stable.restore(Channel.STABLE, None)
    check(stable.check(manual=True), "Prüfung (Stable) startet nicht")
    check(wait(lambda: stable.state in done, 120), f"Prüfung (Stable) hängt ({stable.state.value})")
    check(stable.state is not UpdateState.ERROR, f"Prüfung (Stable) fehlgeschlagen: {stable.error} {stable.error_detail}")
    offered = stable.offer
    check(offered is None or (not offered.prerelease and not offered.version.prerelease), f"Stable bietet eine Vorabversion an: {offered.version if offered else ''}")
    print(f"1. Kanal Stable: {'kein Update' if offered is None else f'Angebot {offered.version} (stabil)'} – keine Beta")
    stable.shutdown()

    # Kanal „Beta“: findet die erwartete Beta
    beta = updates.create_service(app, installed)
    beta.restore(Channel.BETA, None)
    check(beta.check(manual=True), "Prüfung (Beta) startet nicht")
    check(wait(lambda: beta.state in done, 120), f"Prüfung (Beta) hängt ({beta.state.value})")
    check(beta.state is UpdateState.AVAILABLE, f"Beta nicht angeboten: {beta.state.value} {beta.error} {beta.error_detail}")
    offer = beta.offer
    check(str(offer.version) == expected, f"Falsches Angebot: {offer.version} statt {expected}")
    check(offer.prerelease and bool(offer.version.prerelease), "Angebot ist auf GitHub keine Vorabversion")
    check(offer.installer is not None and offer.installer.name == f"PDF-Tool-Setup-{expected}.exe", f"Falsches Setup: {offer.installer}")
    print(f"2. Kanal Beta: Angebot {offer.version} (Vorabversion), Setup {offer.installer.name}, {offer.installer.size} Bytes")
    check(beta.download(), "Download startet nicht")
    check(wait(lambda: beta.state in (UpdateState.READY, UpdateState.ERROR), 900), f"Download hängt ({beta.state.value})")
    check(beta.state is UpdateState.READY, f"Nicht bereit: {beta.error} {beta.error_detail}")
    print("3. Heruntergeladen und per SHA-256 geprüft: bereit")
    handed: list = []
    check(beta.begin_install(lambda path, sha: handed.append((Path(path), sha))), "Installation lässt sich nicht vorbereiten")
    check(wait(lambda: handed, 300), "Erneute Prüfung vor der Installation endet nicht")
    setup, digest = handed[0]
    actual = hashlib.sha256(setup.read_bytes()).hexdigest()
    check(actual == digest, f"Übergebenes Setup weicht ab: {actual} ≠ {digest}")
    print(f"4. »Jetzt installieren«: erneut geprüft, übergeben {setup.name} (SHA-256 {digest})")
    result_file.write_text(json.dumps({"version": expected, "setup": str(setup), "sha256": digest, "size": setup.stat().st_size}), encoding="utf-8")
    beta.shutdown()
    worker.shutdown()
    del qt


def after(app_dir: Path, expected: str) -> None:
    sys.path.insert(0, str(app_dir))
    import appstate

    check(appstate.VERSION == expected, f"Nach dem Update ist {appstate.VERSION} installiert, erwartet {expected}")
    folder = data_dir()
    config = folder / "gui-config.json"
    before = read_config(config)
    legacy = [entry["name"] for entry in before.get("vorlagen") or [] if isinstance(entry, dict) and entry.get("name")]
    print(f"Installiert: PDF Tool {appstate.VERSION} · Vorlagen im alten Format: {legacy}")

    from qtapp import application as appmod

    qt = appmod.create_application([])
    appmod.start_log()
    outcome = appmod.prepare_data()
    check(outcome is None, f"Unerwartete Wiederherstellung beim Start: {outcome}")
    runtime = appmod.Runtime(appstate.load_config())
    try:
        check(runtime.updates.channel == "beta", f"Update-Kanal nach dem Update: {runtime.updates.channel}")
        names = sorted(template.name for template in runtime.app.state.templates.templates())
        check(set(legacy) <= set(names), f"Vorlagen nicht übernommen: {names}")
        print(f"1. Programmstart ohne Fenster: Kanal Beta, Vorlagen 2.0 {names}")
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
    check(saved.get("vorlagen_2") == expected, f"Übernahme der Vorlagen nicht vermerkt: {saved.get('vorlagen_2')}")
    files = sorted((folder / "vorlagen").glob("*.json"))
    check(len(files) == len(legacy), f"Vorlagen 2.0: {len(files)} Dateien statt {len(legacy)}")
    print(f"3. Einstellungen erhalten ({len(KEPT)} Schlüssel), bisherige Vorlagenliste unverändert, {len(files)} Vorlagen-Dateien")
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
    parser.add_argument("--app", type=Path, help="Programmordner der installierten App (…\\PDF-Tool\\app)")
    parser.add_argument("--installed", default="", help="installierte Vorversion (Phase »suchen«)")
    parser.add_argument("--expect", default="", help="erwartete Beta, z. B. 2.8.0-beta.1")
    parser.add_argument("--result", type=Path, help="Ergebnis der Phase »suchen« (JSON)")
    args = parser.parse_args()
    if args.phase == "vorbereiten":
        prepare()
    else:
        check(args.app is not None and (args.app / "updater" / "service.py").is_file(), f"Programmordner fehlt: {args.app}")
        check(bool(args.expect), "--expect fehlt")
        if args.phase == "suchen":
            check(bool(args.installed) and args.result is not None, "--installed und --result fehlen")
            search(args.app.resolve(), args.installed, args.expect, args.result)
        else:
            after(args.app.resolve(), args.expect)
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
