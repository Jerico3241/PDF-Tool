"""Updater von Anfang bis Ende mit der eingebetteten Laufzeit – ohne Eingriff in ein echtes Release.

Aufruf in der CI (Windows, nach dem Build)::

    build\\payload\\runtime\\python.exe -s windows-app\\tests\\smoke_updater.py --app build\\payload\\app --fake-setup <fake-update-setup.exe>

``--fake-setup`` ist ein echtes Inno-Setup (``fixtures/fake-update-setup.iss``), das beim Start nur
eine Markierung schreibt. Geprüft wird:

1. Qt Network kann HTTPS – unter Windows mit dem Schannel-Backend der Laufzeit.
2. Mit einem lokalen Testserver, der sich wie GitHub verhält (127.0.0.1): App erkennt das Release
   → Download → SHA-256 → bereit → Installation vorbereiten (erneute Prüfung) → der Hilfsprozess
   (``pythonw -I launch.py``) wartet auf das Ende der »App« (ein Platzhalter-Prozess), prüft erneut
   und startet das Setup – die Markierung erscheint erst danach.
3. Manipuliert: eine falsche Prüfsumme führt nie zu »bereit«, die Datei wird gelöscht; der
   Hilfsprozess verweigert eine nachträglich veränderte Datei.
4. Nur lesend gegen GitHub (``--live``): veröffentlichte Prüfsumme von 2.7.1 über github.com samt
   Weiterleitung zum Download-Speicher und die Release-Liste über die Repository-ID. Ein erreichtes
   Anfragelimit von GitHub ist nur eine Warnung.

Endet mit Code 0 und »OK«, sonst mit einer Fehlermeldung und Code 1.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent


def check(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"FEHLER: {message}")


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--app", required=True, type=Path)
    parser.add_argument("--fake-setup", required=True, type=Path)
    parser.add_argument("--live", action="store_true", help="zusätzlich nur lesend gegen GitHub prüfen")
    args = parser.parse_args()
    app_dir = args.app.resolve()
    check((app_dir / "updater" / "launch.py").is_file(), f"Updater fehlt in {app_dir}")
    check(args.fake_setup.is_file(), f"Setup-Attrappe fehlt: {args.fake_setup}")
    sys.path.insert(0, str(app_dir))
    sys.path.insert(0, str(HERE))
    work = Path(tempfile.mkdtemp(prefix="pdf-tool-updater-"))
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    os.environ["UE_DATA_DIR"] = str(work / "daten")  # nie die Daten des Rechners

    from PySide6.QtCore import QCoreApplication, QEventLoop
    from PySide6.QtNetwork import QSslSocket

    from appstate import VERSION
    from qtapp.tasks import Worker
    from updater import github, installer, launch
    from updater.models import Channel, ErrorKind, UpdateState
    from updater.policy import UrlPolicy
    from updater.semver import Version
    from updater.service import UpdateService
    from updater.store import UpdateStore
    from updater.transport import HttpClient
    from updater.verifier import parse_checksum
    from updateserver import UpdateServer

    qt = QCoreApplication.instance() or QCoreApplication([])

    def wait(condition, timeout: float = 60.0) -> bool:
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            QCoreApplication.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 20)
            if condition():
                return True
            time.sleep(0.01)
        return bool(condition())

    # 1. TLS
    print(f"PDF Tool {VERSION} · Python {sys.version.split()[0]} · {sys.executable}")
    backends = list(QSslSocket.availableBackends())
    print(f"TLS: {QSslSocket.activeBackend()} (verfügbar: {', '.join(backends)}) · SSL unterstützt: {QSslSocket.supportsSsl()}")
    if sys.platform == "win32":
        check("schannel" in backends, "Schannel-TLS-Backend fehlt (plugins/tls/qschannelbackend.dll)")
        check(QSslSocket.supportsSsl(), "Qt Network meldet keine TLS-Unterstützung")

    # 2. Ablauf gegen den lokalen Testserver
    installed = Version.parse(VERSION)
    offered = f"{installed.major}.{installed.minor}.{installed.patch + 1}"
    setup_bytes = args.fake_setup.read_bytes()
    server = UpdateServer()
    worker = Worker()
    try:
        server.publish(offered, setup=setup_bytes, notes="## Test\n\n- Updater-Prüfung der CI")
        client = HttpClient(UrlPolicy.loopback(server.port), user_agent=f"PDF-Tool/{VERSION} (CI)", system_proxy=False)
        folder = work / "updates"
        service = UpdateService(installed, client, UpdateStore(folder, site=server.base), worker.run, releases_url=server.releases_url, site=server.base)
        service.restore(Channel.STABLE, None)
        check(service.check(manual=True), "Prüfung startet nicht")
        check(wait(lambda: service.state is UpdateState.AVAILABLE), f"Release nicht erkannt ({service.state.value}, {service.error_detail})")
        check(str(service.offer.version) == offered, f"Falsches Angebot: {service.offer.version}")
        print(f"2. Release erkannt: {offered} (installiert {installed})")
        check(service.download(), "Download startet nicht")
        check(wait(lambda: service.state in (UpdateState.READY, UpdateState.ERROR)), f"Download hängt ({service.state.value})")
        check(service.state is UpdateState.READY, f"Nicht bereit: {service.error} {service.error_detail}")
        setup = folder / f"PDF-Tool-Setup-{offered}.exe"
        digest = hashlib.sha256(setup_bytes).hexdigest()
        check(setup.read_bytes() == setup_bytes and not (folder / (setup.name + ".part")).exists(), "Download unvollständig oder Teil-Datei übrig")
        print(f"   Download und SHA-256 geprüft: {setup.name} ({len(setup_bytes)} Bytes)")
        handed: list = []
        check(service.begin_install(lambda path, sha: handed.append((path, sha))), "Installation lässt sich nicht vorbereiten")
        check(wait(lambda: handed, 30), "Erneute Prüfung vor der Installation endet nicht")
        check(handed[0] == (setup, digest), f"Falsche Übergabe: {handed[0]}")
        if os.name != "nt":
            setup.chmod(0o755)  # Linux (lokaler Probelauf): Skript als »Setup« ausführbar machen
        marker = work / "setup-gestartet.txt"
        os.environ["PDFTOOL_E2E_MARKER"] = str(marker)
        placeholder = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(3)"])  # die »App«
        log = folder / "update-start.log"
        helper = installer.Launcher().start(setup, digest, placeholder.pid, log)
        time.sleep(1.0)
        check(not marker.exists(), "Setup startete, bevor die App beendet war")
        placeholder.wait(30)
        check(helper.wait(60) == launch.OK, f"Hilfsprozess: Code {helper.returncode} – {log.read_text(encoding='utf-8') if log.exists() else ''}")
        check(wait(lambda: marker.exists(), 30), "Setup-Attrappe wurde nicht gestartet")
        print("   Hilfsprozess: wartete auf das Ende der App, prüfte erneut, startete das Setup")
        print("   " + " | ".join(line.split(" ", 2)[-1] for line in log.read_text(encoding="utf-8").splitlines()))
        service.install_aborted()

        # 3. Manipuliert
        server.publish(f"{installed.major}.{installed.minor}.{installed.patch + 2}", setup=setup_bytes, checksum="0" * 64 + f"  PDF-Tool-Setup-{installed.major}.{installed.minor}.{installed.patch + 2}.exe\n", digest=None)
        service.check(manual=True)
        check(wait(lambda: service.state is UpdateState.AVAILABLE), "Manipuliertes Release nicht erkannt")
        service.download()
        check(wait(lambda: service.state in (UpdateState.READY, UpdateState.ERROR)), "Prüfung hängt")
        check(service.state is UpdateState.ERROR and service.error is ErrorKind.VERIFY_FAILED, f"Falsche Prüfsumme wurde nicht erkannt: {service.state}")
        check(not any(path.name.startswith(f"PDF-Tool-Setup-{installed.major}.{installed.minor}.{installed.patch + 2}") for path in folder.iterdir()), "Datei nach fehlgeschlagener Prüfung nicht gelöscht")
        changed = work / setup.name
        changed.write_bytes(setup_bytes + b"\0")
        launch.message = lambda _text: None  # kein Hinweisfenster in der CI
        check(launch.main(["--setup", str(changed), "--sha256", digest, "--wait", "0"]) == launch.NOT_VERIFIED_CODE, "Veränderte Datei wurde nicht abgelehnt")
        print("3. Manipulationen abgelehnt: falsche Prüfsumme (nicht bereit, Datei gelöscht), veränderte Datei (nicht gestartet)")
        service.shutdown()
    finally:
        server.stop()

    # 4. Nur lesend gegen GitHub
    if args.live:
        live = HttpClient(UrlPolicy.github(), user_agent=f"PDF-Tool/{VERSION} (CI)")
        result: dict = {}
        url = "https://github.com/Jerico3241/PDF-Tool/releases/download/v2.7.1/PDF-Tool-Setup-2.7.1.exe.sha256"
        live.fetch(url, max_bytes=github.MAX_CHECKSUM_SIZE, on_done=lambda data: result.update(sha=data), on_error=lambda error: result.update(error=error))
        check(wait(lambda: result, 60), "Abruf von github.com hängt")
        check("sha" in result, f"HTTPS-Abruf von github.com (mit Weiterleitung) fehlgeschlagen: {result.get('error')}")
        sha = parse_checksum(result["sha"], "PDF-Tool-Setup-2.7.1.exe")
        print(f"4. HTTPS zu GitHub (Weiterleitung zum Download-Speicher): Prüfsumme von 2.7.1 = {sha}")
        result.clear()
        live.fetch(github.RELEASES_URL, headers=github.API_HEADERS, max_bytes=github.MAX_FEED_SIZE, on_done=lambda data: result.update(feed=data), on_error=lambda error: result.update(error=error))
        check(wait(lambda: result, 60), "Abruf der Release-Liste hängt")
        if "feed" in result:
            releases = github.parse_releases(result["feed"])
            stable = github.latest_stable(releases)
            check(stable is not None and stable >= Version.parse("2.7.1"), f"Release-Liste ohne stabile Version ≥ 2.7.1: {[str(r.version) for r in releases]}")
            match = next((release for release in releases if str(release.version) == "2.7.1"), None)
            check(match is not None and match.complete, "Release 2.7.1 fehlt oder ist unvollständig")
            if match.installer.digest:
                check(match.installer.digest == sha, "Prüfsummendatei und GitHub-Angabe von 2.7.1 widersprechen sich")
            print(f"   Release-Liste über die Repository-ID: {len(releases)} Releases, neueste stabile {stable}")
        elif getattr(result.get("error"), "rate_limited", False):
            print("   WARNUNG: GitHub-Anfragelimit erreicht – Release-Liste nicht geprüft")
        else:
            check(False, f"Release-Liste über die Repository-ID nicht abrufbar: {result.get('error')}")
    worker.shutdown()
    del qt
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
