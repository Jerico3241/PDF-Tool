"""Qt-Oberfläche: Einstellungen → »Sicherung & Wiederherstellung« und »Diagnose« (Tests 102–105).

* Jetzt sichern, automatische Sicherung (höchstens täglich, nur bei Änderungen), Status.
* Wiederherstellen: Prüfung, Zusammenfassung mit Bereichen, Sicherung des aktuellen Stands,
  Neustart, Ausführung beim Start, Ergebnis auf der Startseite.
* Eine Sicherung einer neueren Version wird nie eingespielt.
* Vor einem Update wird gesichert; während einer Sicherung startet keine Installation.
* Diagnose: Datenprüfung, Support-Paket, Systeminformationen.
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

from backup import archive, restore
from conftest import neustart, pump, wait_until
from test_qt_customers import antworten, hinweis


def sicherung_anlegen(h, folder: Path) -> Path:
    h.app.persist()
    h.backup.create(str(folder), archive.KIND_MANUAL)
    assert wait_until(lambda: not h.backup.busy, 30)
    entries = sorted(folder.glob("*.pdtbackup"))
    assert entries
    return entries[-1]


def test_settings_show_backup_and_diagnose(app) -> None:
    app.navigate("settings", 0.3)
    for name in ("backupCard", "backupAutomaticToggle", "backupNow", "restoreBackup", "diagnoseCard", "runChecks", "supportPackage", "diagnoseFacts"):
        assert app.item(name) is not None, name
    assert app.backup.automatic is True and app.backup.lastAuto == "Noch keine"
    # Systeminformationen: feste Zeilen von Anfang an, die Werte kommen im Hintergrund (kein Neuaufbau)
    from diagnostics import info
    from qtapp import diagnose

    model = app.diagnose.fact_model
    assert model.rowCount() == len(info.FACTS) and model.get(0)["label"] == "PDF Tool"
    assert wait_until(lambda: all(model.get(row)["value"] != diagnose.PENDING for row in range(model.rowCount())), 10)
    assert {fact["label"]: fact["value"] for fact in app.diagnose.facts}["PDF Tool"] == model.get(0)["value"]


def test_102_manual_and_automatic_backup(ui_app, tmp_path: Path, monkeypatch) -> None:
    from qtapp import files

    h = ui_app
    assert h.overview.saveAsTemplate("Energie")
    monkeypatch.setattr(files, "RESPONSES", [str(tmp_path / "usb")])
    h.backup.backupNow()
    assert wait_until(lambda: not h.backup.busy and h.backup.state.last_manual, 30)
    files_ = list((tmp_path / "usb").glob("PDF-Tool-Sicherung_*.pdtbackup"))
    assert len(files_) == 1 and "Sicherung" in hinweis(h, "sicherung_info").message
    info = archive.inspect_backup(files_[0])
    assert info.area("vorlagen").summary == "1 Vorlage" and info.kind == "manuell"
    assert h.backup.lastManual != "Noch keine"
    # Automatisch: beim ersten Mal, danach erst nach Änderungen und einem Tag
    h.backup.run_auto()
    assert wait_until(lambda: not h.backup.busy and h.backup.auto_runs == 1, 30)
    assert wait_until(lambda: h.backup.recentModel.count == 1, 10) and h.backup.lastAuto != "Noch keine"
    h.backup.run_auto()
    assert wait_until(lambda: not h.backup.busy, 30) and h.backup.auto_runs == 1
    h.backup.setAutomatic(False)
    neu = neustart(h)
    assert neu.backup.automatic is False and neu.backup.state.last_manual  # Status in sicherung.json


def test_103_newer_or_damaged_backup_is_never_restored(ui_app, tmp_path: Path) -> None:
    h = ui_app
    path = sicherung_anlegen(h, tmp_path / "ziel")
    with zipfile.ZipFile(path) as zf:
        items = {name: zf.read(name) for name in zf.namelist()}
    manifest = json.loads(items["manifest.json"])
    manifest["format_version"] = 2
    items["manifest.json"] = json.dumps(manifest).encode()
    newer = tmp_path / "neuer.pdtbackup"
    with zipfile.ZipFile(newer, "w") as zf:
        for name, data in items.items():
            zf.writestr(name, data)
    h.backup.restore(str(newer))
    assert wait_until(lambda: not h.backup.busy, 30)
    assert hinweis(h, "sicherung_info").message == archive.NEWER
    assert restore.pending(h.backup.root) is None
    (tmp_path / "kaputt.pdtbackup").write_bytes(b"kein zip")
    h.backup.restore(str(tmp_path / "kaputt.pdtbackup"))
    assert wait_until(lambda: not h.backup.busy, 30)
    assert "keine Sicherung" in hinweis(h, "sicherung_info").message and restore.pending(h.backup.root) is None


def test_104_restore_with_summary_pre_backup_and_restart(ui_app, tmp_path: Path, monkeypatch) -> None:
    h = ui_app
    assert h.overview.saveAsTemplate("Energie") and h.overview.saveAsTemplate("Bank")
    path = sicherung_anlegen(h, tmp_path / "ziel")
    # Danach: eine Vorlage gelöscht, eine neue angelegt
    store = h.app.state.templates
    h.contracts.delete_template(store.by_name("Bank").id)
    assert h.overview.saveAsTemplate("Neu")
    gestellt = antworten(monkeypatch, "restore_summary", "primary", {"areas": ["vorlagen"]})
    restarted = []
    h.backup.restart = lambda: restarted.append(True)
    h.backup.restore(str(path))
    assert wait_until(lambda: restarted and not h.backup.busy, 30)
    data = gestellt[-1]["data"]
    assert [area["key"] for area in data["areas"]] == ["einstellungen", "kunden", "vorlagen", "regelwerke"]
    assert next(area for area in data["areas"] if area["key"] == "vorlagen")["summary"] == "2 Vorlagen"
    plan = restore.pending(h.backup.root)
    assert plan is not None and plan.areas == ("vorlagen",) and plan.pre_backup.endswith("_vor-wiederherstellung.pdtbackup")
    assert (h.backup.folder() / plan.pre_backup).is_file()  # aktueller Stand gesichert
    assert h.app.running_work() == []
    # Neustart: die Wiederherstellung läuft vor dem Laden der Daten
    neu = neustart(h)
    names = sorted(t.name for t in neu.app.state.templates.templates())
    assert names == ["Bank", "Energie"]
    assert restore.pending(neu.backup.root) is None
    assert wait_until(lambda: restore.leftovers(neu.backup.root) == [], 10)  # bisheriger Stand: im Hintergrund gelöscht
    # Ergebnis: auf der Startseite (blendet sich nach 12 s aus – der Neustart im Test kann länger
    # dauern, deshalb zählt »wurde gezeigt«) und dauerhaft unter Einstellungen
    start = hinweis(neu, "home_info")
    assert wait_until(lambda: start.serial >= 1, 5)
    assert start.severity == "success" and "Wiederhergestellt" in start.message
    assert hinweis(neu, "sicherung_info").shown and "Wiederhergestellt" in hinweis(neu, "sicherung_info").message


def test_restore_can_be_cancelled_before_restart(ui_app, tmp_path: Path, monkeypatch) -> None:
    from qtapp import dialogs

    h = ui_app
    path = sicherung_anlegen(h, tmp_path / "ziel")
    antworten(monkeypatch, "restore_summary", "primary", {"areas": ["einstellungen"]})
    original = dialogs.DialogService.confirm

    def no_restart(self, title, message, confirm, danger=True):
        if title == "Neu starten":
            return False
        return original(self, title, message, confirm, danger)

    monkeypatch.setattr(dialogs.DialogService, "confirm", no_restart)
    h.backup.restore(str(path))
    assert wait_until(lambda: not h.backup.busy and "abgebrochen" in (hinweis(h, "sicherung_info").message or ""), 30)
    assert restore.pending(h.backup.root) is None


def test_update_waits_for_backup_and_backs_up_first(ui_app, tmp_path: Path, monkeypatch) -> None:
    from qtapp import dialogs

    h = ui_app
    proceeded = []
    assert h.backup.backup_before_update(lambda: proceeded.append(True)) is True
    assert "Sicherung" in h.app.running_work()  # keine Installation während der Sicherung
    assert h.backup.backup_before_update(lambda: proceeded.append("zweimal")) is False
    assert wait_until(lambda: proceeded == [True], 30)
    assert any(path.name.endswith("_vor-update.pdtbackup") for path in h.backup.folder().iterdir())
    # Scheitert die Sicherung, entscheidet der Benutzer
    blocker = tmp_path / "datei"
    blocker.write_text("x")
    h.backup.state.folder = str(blocker / "unter")
    monkeypatch.setattr(dialogs, "AUTO_ANSWER", "close")
    proceeded.clear()
    h.backup.backup_before_update(lambda: proceeded.append(True))
    assert wait_until(lambda: not h.backup.busy, 30)
    pump(0.1)
    assert proceeded == [] and h.app.dialogs.history[-1]["title"] == "Sicherung vor dem Update fehlgeschlagen"
    monkeypatch.setattr(dialogs, "AUTO_ANSWER", "primary")
    h.backup.backup_before_update(lambda: proceeded.append(True))
    assert wait_until(lambda: proceeded == [True], 30)


def test_105_diagnose_checks_and_support_package(ui_app, tmp_path: Path, monkeypatch) -> None:
    from qtapp import files

    h = ui_app
    h.navigate("settings", 0.3)
    h.diagnose.runChecks()
    assert wait_until(lambda: not h.diagnose.busy and h.diagnose.verdict, 30)
    labels = [result["label"] for result in h.diagnose.results]
    assert {"Einstellungen", "Kundenakten", "Vorlagen", "Regelwerke", "Vertragsstände", "Sicherungsordner"} <= set(labels)
    assert h.diagnose.lastRun.startswith("Geprüft am")
    monkeypatch.setattr(files, "RESPONSES", [str(tmp_path / "support")])
    h.diagnose.createPackage()
    assert wait_until(lambda: not h.diagnose.busy and h.diagnose.packages == 1, 30)
    package = next((tmp_path / "support").glob("PDF-Tool-Support_*.zip"))
    with zipfile.ZipFile(package) as zf:
        assert {"LIESMICH.txt", "bericht.txt", "diagnose.json", "einstellungen.json"} <= set(zf.namelist())
    assert "Support-Paket" in hinweis(h, "diagnose_info").message
    facts = {fact["label"]: fact["value"] for fact in h.diagnose.facts}
    assert facts["PDF Tool"] and facts["Update-Kanal"] in ("Stable", "Beta")
