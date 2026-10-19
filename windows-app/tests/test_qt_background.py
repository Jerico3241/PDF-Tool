"""Im Hintergrund bereithalten (ab 3.2.0-beta.4): Symbol im Infobereich, Start mit Windows, Schließen-Kreuz.

Der Infobereich ist eine Attrappe (unter »offscreen« gibt es keinen), der Autostart-Eintrag ein Wörterbuch statt der
Registry. Geprüft wird das Verhalten wie von Hand: Kreuz → Fenster versteckt, Dokumente geschlossen, PDF Tool läuft
weiter; Infobereich »Öffnen« bzw. ein weiterer Start → Fenster wieder da; »Beenden«, Update und ausgeschaltete
Einstellung → PDF Tool endet wie bisher.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

import editorsamples as samples
from conftest import pump, wait_until
from test_qt_reader import open_pdf, reader, settle

APP_DIR = Path(__file__).resolve().parents[1] / "app"


class FakeTray:
    def __init__(self) -> None:
        self.messages: list[tuple[str, str]] = []
        self.visible = True

    def hide(self) -> None:
        self.visible = False

    def deleteLater(self) -> None:  # noqa: N802 - Qt-Schreibweise
        pass

    def showMessage(self, title: str, text: str, *_args) -> None:  # noqa: N802
        self.messages.append((title, text))


@pytest.fixture
def resident(ui_app, monkeypatch):
    """App wie aus ``main``: Hintergrundmodus eingerichtet (Attrappe für Infobereich und Hauptschleife)."""
    from qtapp import background

    h = ui_app
    h.app.dialogs.shutdown()  # »Neu in Version« schließen
    trays: list[FakeTray] = []
    quits: list[int] = []

    def create(_self):
        trays.append(FakeTray())
        return trays[-1]

    monkeypatch.setattr(background.Background, "_create_tray", create)
    h.runtime.background.attach(h.qt, tray_available=lambda: True, autostart=False)
    h.runtime.background._quit = lambda: quits.append(1)  # noqa: SLF001
    h.trays, h.quits = trays, quits
    yield h
    h.qt.setQuitOnLastWindowClosed(True)


def test_defaults_and_autostart_entry(tmp_path: Path) -> None:
    """Standard: an. Den Eintrag unter »Start mit Windows« setzt nur eine installierte App – und nur, wenn er anders ist."""
    from qtapp import background

    assert background.enabled_in({}) is True and background.enabled_in({"hintergrund": False}) is False
    assert background.launcher_path(APP_DIR) is None  # Quellbaum: kein PDF-Tool.exe, kein Autostart
    app_dir = tmp_path / "PDF Tool" / "app"
    app_dir.mkdir(parents=True)
    exe = app_dir.parent / "PDF-Tool.exe"
    exe.write_bytes(b"MZ")
    assert background.launcher_path(app_dir) == exe
    registry: dict = {}
    writes: list = []

    def write(name, command):
        writes.append((name, command))
        if command is None:
            registry.pop(name, None)
        else:
            registry[name] = command
        return True

    assert background.sync_autostart(True, exe, registry.get, write) is True
    assert registry == {"PDF Tool": f'"{exe}" --hintergrund'}
    assert background.sync_autostart(True, exe, registry.get, write) is True and len(writes) == 1  # unverändert: kein Schreiben
    assert background.sync_autostart(False, exe, registry.get, write) is True and registry == {}
    assert background.sync_autostart(False, exe, registry.get, write) is True and len(writes) == 2
    assert background.sync_autostart(True, None, registry.get, write) is False  # Quellbaum: nichts zu tun


def test_message_of_a_second_start() -> None:
    from qtapp import instance

    assert instance.received(json.dumps({"open": [], "show": True}).encode()) == ([], True)
    assert instance.received(json.dumps({"open": []}).encode()) == ([], False)  # ältere Version: nur Pfade
    assert instance.received(b"kaputt") == ([], False)
    assert instance.received(json.dumps({"open": [str(APP_DIR / "start.py")], "show": "ja"}).encode()) == ([str(APP_DIR / "start.py")], False)


def test_second_start_without_files_shows_the_running_app(qt_application, tmp_path: Path) -> None:
    """Weiterer Start (Startmenü): die laufende App zeigt ihr Fenster. Start mit Windows (``show=False``): nur prüfen,
    ob PDF Tool läuft – nichts wird gezeigt. Beide Prozesse enden mit 0."""
    from qtapp import instance

    calls: list = []
    name = instance.PREFIX + "test-" + hashlib.sha1(str(tmp_path).encode()).hexdigest()[:8]
    server = instance.InstanceServer(lambda paths: calls.append(list(paths)), name=name)
    assert server.listening
    script = (
        "import sys; sys.path.insert(0, sys.argv[1]);"
        "from PySide6.QtCore import QCoreApplication; app = QCoreApplication([]);"
        "from qtapp import instance;"
        "sys.exit(0 if instance.forward([], name=sys.argv[2], show=sys.argv[3] == '1') else 3)"
    )
    try:
        for show, expected in (("1", [[]]), ("0", [[]])):
            second = subprocess.Popen([sys.executable, "-c", script, str(APP_DIR), name, show])
            assert wait_until(lambda: second.poll() is not None, 30)
            assert second.returncode == 0
            pump(0.2)
            assert calls == expected
    finally:
        server.close()


def test_close_button_hides_the_window_and_keeps_running(resident, tmp_path: Path) -> None:
    """Kreuz: Dokumente schließen, Fenster versteckt, PDF Tool läuft weiter (Hinweis einmal). Infobereich »Öffnen«: das
    Fenster ist wieder da – auf der Startseite, ohne die geschlossenen Dokumente."""
    h = resident
    assert h.runtime.background.active and not h.qt.quitOnLastWindowClosed()
    h.navigate("reader", 0.3)
    open_pdf(h, samples.standard_text(tmp_path / "Brief.pdf"))
    settle(h)
    assert reader(h).tabs.count == 1
    h.window.close()
    pump(0.2)
    assert not h.window.isVisible() and not h.app.closing
    assert reader(h).tabs.count == 0 and h.app.currentPage == "home"
    assert h.trays[0].messages and h.trays[0].messages[0][0] == "PDF Tool läuft im Hintergrund weiter"
    assert h.quits == []
    h.app.present_window()
    assert wait_until(lambda: h.window.isVisible(), 5)
    pump(0.2)
    h.window.close()
    pump(0.2)
    assert not h.window.isVisible() and len(h.trays[0].messages) == 1  # der Hinweis erscheint nur einmal
    h.app.present_window()
    assert wait_until(lambda: h.window.isVisible(), 5)


def test_unsaved_question_cancelled_keeps_the_window(resident, tmp_path: Path, monkeypatch) -> None:
    """Rückfrage zu ungespeicherten Änderungen mit »Abbrechen«: Fenster und Dokument bleiben."""
    h = resident
    h.navigate("reader", 0.3)
    open_pdf(h, samples.standard_text(tmp_path / "Entwurf.pdf"))
    settle(h)
    reasons: list[str] = []

    def cancel(reason="PDF Tool wird beendet."):
        reasons.append(reason)
        return False

    monkeypatch.setattr(reader(h), "confirm_close", cancel)
    h.window.close()
    pump(0.2)
    assert h.window.isVisible() and reader(h).tabs.count == 1 and reasons == ["Das Fenster wird geschlossen."]


def test_quit_from_tray_ends_the_app(resident) -> None:
    h = resident
    h.window.close()
    pump(0.2)
    assert not h.window.isVisible()
    h.app.quit_app()
    pump(0.1)
    assert h.app.closing and h.quits == [1] and not h.trays[0].visible


def test_update_quits_completely(resident) -> None:
    """Vor der Installation eines Updates endet PDF Tool ganz – das Kreuz-Verhalten gilt dabei nicht."""
    h = resident
    assert h.updates._quit_app() is True  # noqa: SLF001
    assert h.app.closing and h.quits == [1]


def test_switching_off_restores_the_old_behaviour(resident, config_file: Path) -> None:
    """Einstellungen → Verhalten: ausgeschaltet kein Symbol, das Kreuz beendet wieder; die Wahl wird gespeichert."""
    h = resident
    h.navigate("settings", 0.3)
    toggle = h.item("backgroundToggle")
    assert h.item("backgroundCard").property("title") == "Im Hintergrund bereithalten"
    assert toggle.property("checked") and h.settings.background
    h.settings.setBackground(False)
    pump(0.1)
    assert not toggle.property("checked") and not h.runtime.background.active and not h.trays[0].visible
    assert h.qt.quitOnLastWindowClosed()
    assert json.loads(config_file.read_text(encoding="utf-8"))["hintergrund"] is False
    assert h.app.requestClose() is True and h.app.closing


def test_outlook_attachments_are_copied_before_outlook_deletes_them(tmp_path, monkeypatch):
    import handoff

    monkeypatch.setenv("TEMP", str(tmp_path / "temp"))
    monkeypatch.setenv("UE_DATA_DIR", str(tmp_path / "daten"))
    outlook = tmp_path / "AppData" / "Local" / "Microsoft" / "Windows" / "INetCache" / "Content.Outlook" / "AB12CD34"
    outlook.mkdir(parents=True)
    attachment = outlook / "Rechnung.pdf"
    attachment.write_bytes(b"%PDF-1.7\n%%EOF\n")
    other = tmp_path / "Dokumente" / "Vertrag.pdf"
    other.parent.mkdir()
    other.write_bytes(b"%PDF-1.7\n%%EOF\n")
    (tmp_path / "temp").mkdir()
    in_temp = tmp_path / "temp" / "mail.pdf"
    in_temp.write_bytes(b"%PDF-1.7\n%%EOF\n")
    target = tmp_path / "Anhaenge"
    secured = handoff.secure_transient([str(attachment), str(other), "--hintergrund", str(in_temp)], target)
    assert secured[1:3] == [str(other), "--hintergrund"]  # alles andere bleibt, wie es ist
    copies = [Path(secured[0]), Path(secured[3])]
    assert all(copy.parent.parent == target and copy.read_bytes() == b"%PDF-1.7\n%%EOF\n" for copy in copies)
    assert [copy.name for copy in copies] == ["Rechnung.pdf", "mail.pdf"]
    attachment.unlink()  # Outlook räumt auf – die Kopie bleibt
    assert copies[0].is_file()
    # Übergabe-Protokoll (Support-Paket): Art des Ordners und Ergebnis, nie der Dateiname
    log = (tmp_path / "daten" / handoff.HANDOFF_LOG).read_text(encoding="utf-8")
    assert "Start mit Datei: Outlook" in log and log.count("Anhang gesichert") == 2
    assert "Rechnung" not in log and "Vertrag" not in log
