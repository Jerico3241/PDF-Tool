"""Sicherung und Wiederherstellung – Kern (Tests 102–104 der Vorgabe).

* Format: ZIP ``.pdtbackup`` mit Manifest (Format, Version, Zeitpunkt, Art, Bereiche, SHA-256 je Datei).
* Nur Daten von PDF Tool – nie Protokolle, andere Sicherungen, Excel-/PDF-Dateien oder Logos.
* Erstellen atomar und nachgeprüft; Prüfen erkennt Beschädigung, fremde Pfade, neuere Versionen.
* Wiederherstellen: vollständig oder je Bereich, atomar, mit Rückabwicklung bei Fehlern und nach
  einem Abbruch.
* Automatisch höchstens einmal am Tag und nur bei Änderungen; manuelle Sicherungen werden nie gelöscht.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
import zipfile
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from backup import archive, policy, restore
from backup.archive import NEWER, BackupError

VERSION = "2.8.0-beta.1"


def schreibe(path: Path, data) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, (dict, list)):
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    else:
        path.write_bytes(data if isinstance(data, bytes) else str(data).encode("utf-8"))
    return path


def datenordner(root: Path, kunden: int = 2, staende: int = 3) -> Path:
    """Ein Datenordner wie unter %APPDATA%\\PDF-Tool – samt Dateien, die nie in eine Sicherung gehören."""
    schreibe(root / "gui-config.json", {"gesehen": "2.8.0", "titel": "Übersicht", "vorlage_aktiv": "t-1"})
    schreibe(root / "stapel.json", {"version": 1, "eintraege": [{"pfad": "C:/x.xlsx"}]})
    customers = [{"id": f"k{i}", "company": f"Firma {i}", "number": str(i)} for i in range(kunden)]
    schreibe(root / "kundenakten.json", {"schema_version": 2, "customers": customers})
    for i in range(kunden):
        for j in range(staende):
            schreibe(root / "contract-history" / f"k{i}" / f"2026-0{1 + j % 9}-01T00-00-0{j % 10}.json", {"schema_version": 1, "contracts": [{"nummer": str(j)}]})
    schreibe(root / "vorlagen" / "t-1.json", {"schema_version": 1, "id": "t-1", "name": "Energie"})
    schreibe(root / "regelwerke" / "r-1.json", {"schema_version": 1, "id": "r-1", "name": "Regeln", "rules": []})
    # Nie Teil einer Sicherung
    schreibe(root / "fehler.log", "Traceback …")
    schreibe(root / "stapel.log", "log")
    schreibe(root / "pdf-repair.log", "log")
    schreibe(root / "migration-backup-2.2.0.zip", b"PK")
    schreibe(root / "sicherung.json", {"automatic": True})
    schreibe(root / "vorlagen" / ".~abc.tmp", "halb")
    schreibe(root / "Sicherungen" / "alt.pdtbackup", b"x")
    schreibe(root / "kunde.pdf", b"%PDF-1.4")
    schreibe(root / "liste.xlsx", b"PK")
    return root


def inhalt(root: Path) -> dict[str, str]:
    """Relativer Pfad → SHA-256 aller Dateien der Bereiche."""
    return {rel: hashlib.sha256(path.read_bytes()).hexdigest() for _area, rel, path in archive.collect_files(root)}


# --- Erstellen -----------------------------------------------------------------------------------------------


def test_102_backup_contains_exactly_the_app_data_with_manifest(tmp_path: Path) -> None:
    root = datenordner(tmp_path / "daten")
    result = archive.create_backup(root, tmp_path / "ziel", kind=archive.KIND_MANUAL, app_version=VERSION)
    assert result.path.name.startswith("PDF-Tool-Sicherung_") and result.path.suffix == ".pdtbackup"
    assert not list((tmp_path / "ziel").glob("*.partial"))  # atomar: keine Reste
    with zipfile.ZipFile(result.path) as zf:
        names = set(zf.namelist())
        manifest = json.loads(zf.read("manifest.json"))
    expected = {
        "data/gui-config.json",
        "data/stapel.json",
        "data/kundenakten.json",
        "data/vorlagen/t-1.json",
        "data/regelwerke/r-1.json",
        *(f"data/contract-history/k{i}/2026-0{1 + j}-01T00-00-0{j}.json" for i in range(2) for j in range(3)),
    }
    assert names == {"manifest.json", *expected}
    assert not any(name.endswith((".log", ".zip", ".pdf", ".xlsx", ".tmp", ".pdtbackup")) or "sicherung.json" in name for name in names)
    assert manifest["format"] == "pdf-tool-backup" and manifest["format_version"] == 1 and manifest["app_version"] == VERSION
    assert manifest["kind"] == "manuell" and manifest["areas"]["kunden"]["files"] == 7
    assert datetime.fromisoformat(manifest["created_at"]).tzinfo is not None
    for entry in manifest["files"]:
        source = root / entry["path"]
        assert entry["sha256"] == hashlib.sha256(source.read_bytes()).hexdigest() and entry["size"] == source.stat().st_size
    assert manifest["schemas"] == archive.current_schemas()
    assert result.files == 11 and result.size == result.path.stat().st_size


def test_backup_names_are_unique_and_failures_leave_nothing(tmp_path: Path, monkeypatch) -> None:
    root = datenordner(tmp_path / "daten")
    when = datetime(2026, 10, 1, 9, 30, 0)
    first = archive.create_backup(root, tmp_path / "ziel", now=when)
    second = archive.create_backup(root, tmp_path / "ziel", now=when)
    auto = archive.create_backup(root, tmp_path / "ziel", kind=archive.KIND_AUTO, now=when)
    assert first.path.name == "PDF-Tool-Sicherung_2026-10-01_09-30-00.pdtbackup"
    assert second.path.name == "PDF-Tool-Sicherung_2026-10-01_09-30-00_2.pdtbackup"
    assert auto.path.name == "PDF-Tool-Sicherung_2026-10-01_09-30-00_automatisch.pdtbackup"
    # Abbruch und Schreibfehler: keine halbe Datei
    with pytest.raises(BackupError, match="abgebrochen"):
        archive.create_backup(root, tmp_path / "ziel", cancelled=lambda: True)

    def kaputt(self, *args, **kwargs):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(zipfile.ZipFile, "writestr", kaputt)
    with pytest.raises(BackupError, match="nicht genug Platz"):
        archive.create_backup(root, tmp_path / "ziel")
    assert sorted(p.name for p in (tmp_path / "ziel").iterdir()) == sorted([first.path.name, second.path.name, auto.path.name])


def test_unwritable_target_is_reported(tmp_path: Path) -> None:
    root = datenordner(tmp_path / "daten")
    blocker = schreibe(tmp_path / "keinordner", "datei statt ordner")
    with pytest.raises(BackupError, match="nicht angelegt"):
        archive.create_backup(root, blocker / "unter")


# --- Prüfen ------------------------------------------------------------------------------------------------


def test_inspect_summarizes_areas(tmp_path: Path) -> None:
    root = datenordner(tmp_path / "daten", kunden=3, staende=2)
    result = archive.create_backup(root, tmp_path / "ziel", app_version=VERSION)
    info = archive.inspect_backup(result.path, app_version=VERSION)
    summaries = {area.key: area.summary for area in info.areas}
    assert summaries == {
        "einstellungen": "Einstellungen · Stapel mit 1 Eintrag",
        "kunden": "3 Kundenakten · 6 Vertragsstände",
        "vorlagen": "1 Vorlage",
        "regelwerke": "1 Regelwerk",
    }
    assert info.kind_label == "Manuell" and info.app_version == VERSION and not info.notes
    older = archive.inspect_backup(result.path, app_version="2.7.2")  # mit 2.8 erstellt, in 2.7 gelesen …
    assert any("Erstellt mit PDF Tool" in note for note in older.notes)


def _rewrite(path: Path, change) -> None:
    """Sicherung umbauen (Manifest oder Einträge), z. B. um Beschädigungen nachzustellen."""
    with zipfile.ZipFile(path) as zf:
        items = {name: zf.read(name) for name in zf.namelist()}
    items = change(items) or items
    with zipfile.ZipFile(path, "w") as zf:
        for name, data in items.items():
            zf.writestr(name, data)


def _manifest(items: dict) -> dict:
    return json.loads(items["manifest.json"])


@pytest.mark.parametrize(
    "schaden,erwartet",
    [
        ("inhalt", "Prüfsumme"),
        ("groesse", "Dateigröße"),
        ("manifest_fehlt", "keine Sicherung von PDF Tool"),
        ("fremde_datei", "fremde Dateien"),
        ("pfad_ausserhalb", "ungültigen Dateipfad"),
        ("absoluter_pfad", "ungültigen Dateipfad"),
        ("kein_zip", "kein gültiges Archiv"),
        ("abgeschnitten", "kein gültiges Archiv"),
    ],
)
def test_103_damaged_or_foreign_backups_are_rejected(tmp_path: Path, schaden: str, erwartet: str) -> None:
    root = datenordner(tmp_path / "daten")
    path = archive.create_backup(root, tmp_path / "ziel").path
    if schaden == "inhalt":  # gleiche Länge, anderer Inhalt
        _rewrite(path, lambda items: {**items, "data/vorlagen/t-1.json": items["data/vorlagen/t-1.json"].replace(b"Energie", b"Energia")})
    elif schaden == "groesse":
        _rewrite(path, lambda items: {**items, "data/vorlagen/t-1.json": b'{"schema_version": 1, "id": "t-1", "name": "Manipuliert"}'})
    elif schaden == "manifest_fehlt":
        _rewrite(path, lambda items: {k: v for k, v in items.items() if k != "manifest.json"})
    elif schaden == "fremde_datei":
        _rewrite(path, lambda items: {**items, "data/vorlagen/zusatz.json": b"{}"})
    elif schaden in ("pfad_ausserhalb", "absoluter_pfad"):
        bad = "vorlagen/../../start.py" if schaden == "pfad_ausserhalb" else "/etc/passwd"

        def change(items):
            manifest = _manifest(items)
            original = manifest["files"][0]["path"]
            manifest["files"][0]["path"] = bad
            items["manifest.json"] = json.dumps(manifest).encode()
            items["data/" + bad] = items.pop("data/" + original)
            return items

        _rewrite(path, change)
    elif schaden == "kein_zip":
        path.write_bytes(b"nur Text")
    elif schaden == "abgeschnitten":
        path.write_bytes(path.read_bytes()[:200])
    with pytest.raises(BackupError, match=erwartet) as raised:
        archive.inspect_backup(path)
    assert raised.value.newer is False


def test_103_newer_backups_are_blocked(tmp_path: Path) -> None:
    root = datenordner(tmp_path / "daten")
    path = archive.create_backup(root, tmp_path / "ziel").path
    for change in (
        lambda m: m.update(format_version=2),
        lambda m: m["schemas"].update(vorlagen=99),
    ):
        copy = tmp_path / f"neuer-{time.perf_counter_ns()}.pdtbackup"
        copy.write_bytes(path.read_bytes())

        def rewrite(items, change=change):
            manifest = _manifest(items)
            change(manifest)
            items["manifest.json"] = json.dumps(manifest).encode()

        _rewrite(copy, rewrite)
        with pytest.raises(BackupError) as raised:
            archive.inspect_backup(copy)
        assert str(raised.value) == NEWER and raised.value.newer is True
    # Eine einzelne Datei einer neueren Version genügt
    schreibe(root / "regelwerke" / "r-2.json", {"schema_version": 7, "id": "r-2", "name": "Zukunft"})
    with pytest.raises(BackupError, match="neueren Version"):
        archive.inspect_backup(archive.create_backup(root, tmp_path / "ziel2").path)


def test_files_damaged_before_the_backup_are_notes_not_errors(tmp_path: Path) -> None:
    root = datenordner(tmp_path / "daten")
    schreibe(root / "vorlagen" / "kaputt.json", "{ nicht json")
    info = archive.inspect_backup(archive.create_backup(root, tmp_path / "ziel").path)
    assert any("kaputt.json" in note for note in info.notes)


# --- Wiederherstellen ---------------------------------------------------------------------------------------


def test_104_full_restore_replaces_all_areas(tmp_path: Path) -> None:
    root = datenordner(tmp_path / "daten")
    vorher = inhalt(root)
    backup = archive.create_backup(root, tmp_path / "ziel").path
    # Danach: Änderungen in allen Bereichen, neue und gelöschte Dateien
    schreibe(root / "gui-config.json", {"gesehen": "2.8.0", "titel": "Neu"})
    schreibe(root / "vorlagen" / "t-2.json", {"schema_version": 1, "id": "t-2", "name": "Neu"})
    (root / "regelwerke" / "r-1.json").unlink()
    schreibe(root / "contract-history" / "k9" / "neu.json", {"schema_version": 1})
    (root / "stapel.json").unlink()
    plan = restore.stage_restore(backup, root, [area.key for area in archive.AREAS], pre_backup="vorher.pdtbackup")
    assert restore.pending(root) == plan and plan.areas == ("einstellungen", "kunden", "vorlagen", "regelwerke")
    assert json.loads((root / "gui-config.json").read_text(encoding="utf-8"))["titel"] == "Neu"  # erst beim Start
    outcome = restore.apply_pending(root)
    assert outcome.ok and "Wiederhergestellt" in outcome.message
    assert inhalt(root) == vorher
    assert not (root / restore.STAGE).exists() and not (root / restore.ASIDE).exists()
    # Nicht gesicherte Dateien bleiben unberührt
    assert (root / "fehler.log").read_text(encoding="utf-8") == "Traceback …" and (root / "kunde.pdf").is_file()
    assert restore.take_result(root).ok and restore.take_result(root) is None  # nur einmal
    assert restore.apply_pending(root) is None


def test_104_selective_restore_touches_only_the_chosen_areas(tmp_path: Path) -> None:
    root = datenordner(tmp_path / "daten")
    backup = archive.create_backup(root, tmp_path / "ziel").path
    schreibe(root / "vorlagen" / "t-2.json", {"schema_version": 1, "id": "t-2", "name": "Neu"})
    schreibe(root / "gui-config.json", {"titel": "Neu"})
    restore.stage_restore(backup, root, ["vorlagen"])
    assert restore.apply_pending(root).ok
    assert sorted(p.name for p in (root / "vorlagen").iterdir() if not p.name.startswith(".")) == ["t-1.json"]
    assert json.loads((root / "gui-config.json").read_text(encoding="utf-8")) == {"titel": "Neu"}
    with pytest.raises(BackupError, match="mindestens einen Bereich"):
        restore.stage_restore(backup, root, [])


def test_104_failed_step_rolls_everything_back(tmp_path: Path, monkeypatch) -> None:
    root = datenordner(tmp_path / "daten")
    backup = archive.create_backup(root, tmp_path / "ziel").path
    schreibe(root / "gui-config.json", {"titel": "Aktuell"})
    schreibe(root / "vorlagen" / "t-2.json", {"schema_version": 1, "id": "t-2", "name": "Aktuell"})
    aktuell = inhalt(root)
    restore.stage_restore(backup, root, [area.key for area in archive.AREAS])
    import storage

    original = os.replace

    def flaky(src, dst):
        # Der Ordner »vorlagen« ist gesperrt (z. B. im Explorer geöffnet) – mitten im Austausch
        if Path(src).name == "vorlagen" and restore.ASIDE in str(dst):
            raise PermissionError(13, "Zugriff verweigert")
        return original(src, dst)

    monkeypatch.setattr(storage.os, "replace", flaky)
    outcome = restore.apply_pending(root)
    monkeypatch.setattr(storage.os, "replace", original)
    assert not outcome.ok and "bisherige Stand bleibt" in outcome.message
    assert inhalt(root) == aktuell
    assert not (root / restore.STAGE).exists() and not (root / restore.ASIDE).exists()
    assert restore.take_result(root).ok is False


def test_incomplete_rollback_keeps_the_previous_state_and_never_deletes_it(tmp_path: Path, monkeypatch) -> None:
    root = datenordner(tmp_path / "daten")
    backup = archive.create_backup(root, tmp_path / "ziel").path
    schreibe(root / "vorlagen" / "t-2.json", {"schema_version": 1, "id": "t-2", "name": "Aktuell"})
    restore.stage_restore(backup, root, [area.key for area in archive.AREAS])
    import storage

    original = os.replace

    def locked(src, dst):
        src, dst = Path(src), Path(dst)
        if dst == root / "regelwerke" and restore.STAGE + os.sep in str(src):
            raise PermissionError(13, "Zugriff verweigert")  # Austausch scheitert …
        if src == root / restore.ASIDE / "vorlagen" and dst == root / "vorlagen":
            raise PermissionError(13, "Zugriff verweigert")  # … und das Zurücknehmen von »vorlagen« auch
        return original(src, dst)

    monkeypatch.setattr(storage.os, "replace", locked)
    outcome = restore.apply_pending(root)
    monkeypatch.setattr(storage.os, "replace", original)
    kept = [path for path in root.iterdir() if path.name.startswith(restore.KEPT)]
    assert not outcome.ok and "nicht vollständig zurückgenommen werden (vorlagen)" in outcome.message
    assert len(kept) == 1 and kept[0].name in outcome.message
    assert json.loads((kept[0] / "vorlagen" / "t-2.json").read_text(encoding="utf-8"))["name"] == "Aktuell"
    assert restore.leftovers(root) == [] and not (root / restore.ASIDE).exists()
    # Der nächste Start löscht ihn nicht, die Datenprüfung nennt ihn
    assert restore.apply_pending(root) is None and restore.remove_leftovers(root) == 0 and kept[0].is_dir()
    from diagnostics import checks

    befund = next(check for check in checks.run_checks(root, tmp_path / "ziel") if check.key == "restore")
    assert befund.status == checks.WARNING and kept[0].name in befund.detail


def test_104_interrupted_restore_is_rolled_back_at_next_start(tmp_path: Path, monkeypatch) -> None:
    root = datenordner(tmp_path / "daten")
    backup = archive.create_backup(root, tmp_path / "ziel").path
    schreibe(root / "vorlagen" / "t-2.json", {"schema_version": 1, "id": "t-2", "name": "Aktuell"})
    aktuell = inhalt(root)
    restore.stage_restore(backup, root, ["vorlagen", "regelwerke"])

    class Absturz(BaseException):
        pass

    import storage

    original = os.replace
    calls = {"n": 0}

    def crash(src, dst):
        calls["n"] += 1
        if calls["n"] == 4:  # nach dem Beiseitelegen von »vorlagen«, beim nächsten Journal-Eintrag
            raise Absturz()  # wie ein Stromausfall: kein Aufräumen
        return original(src, dst)

    monkeypatch.setattr(storage.os, "replace", crash)
    with pytest.raises(Absturz):
        restore.apply_pending(root)
    monkeypatch.setattr(storage.os, "replace", original)
    assert (root / restore.STAGE / restore.JOURNAL).is_file() and (root / restore.ASIDE / "vorlagen").is_dir()
    assert not (root / "vorlagen").exists()  # mitten im Austausch stehen geblieben
    outcome = restore.apply_pending(root)  # nächster Start
    assert not outcome.ok and "unterbrochen" in outcome.message
    assert inhalt(root) == aktuell


def test_old_state_is_only_renamed_at_start_and_removed_in_the_background(tmp_path: Path) -> None:
    root = datenordner(tmp_path / "daten")
    backup = archive.create_backup(root, tmp_path / "ziel").path
    schreibe(root / "vorlagen" / "t-2.json", {"schema_version": 1, "id": "t-2", "name": "Aktuell"})
    restore.stage_restore(backup, root, ["vorlagen"])
    assert restore.apply_pending(root).ok
    reste = restore.leftovers(root)
    assert len(reste) == 1 and (reste[0] / "vorlagen" / "t-2.json").is_file()  # bisheriger Stand, nur umbenannt
    assert not (root / restore.ASIDE).exists()
    # Noch eine Wiederherstellung, bevor gelöscht wurde: eigener Ordner, nichts vermischt
    restore.stage_restore(backup, root, ["vorlagen"])
    assert restore.apply_pending(root).ok and len(restore.leftovers(root)) == 2
    # Abbruch nach dem Austausch, vor dem Umbenennen: der nächste Start räumt beiseite
    (root / restore.ASIDE / "vorlagen").mkdir(parents=True)
    assert restore.apply_pending(root) is None
    assert not (root / restore.ASIDE).exists() and len(restore.leftovers(root)) == 3
    assert restore.remove_leftovers(root) == 3 and restore.leftovers(root) == []
    assert sorted(p.name for p in (root / "vorlagen").iterdir() if not p.name.startswith(".")) == ["t-1.json"]
    assert restore.remove_leftovers(root) == 0


def test_staged_restore_can_be_discarded_and_is_replaced_by_a_newer_one(tmp_path: Path) -> None:
    root = datenordner(tmp_path / "daten")
    backup = archive.create_backup(root, tmp_path / "ziel").path
    restore.stage_restore(backup, root, ["vorlagen"])
    restore.stage_restore(backup, root, ["regelwerke"])
    assert restore.pending(root).areas == ("regelwerke",)
    assert restore.discard_pending(root) and restore.pending(root) is None
    assert restore.apply_pending(root) is None


def test_restore_of_a_damaged_backup_changes_nothing(tmp_path: Path) -> None:
    root = datenordner(tmp_path / "daten")
    backup = archive.create_backup(root, tmp_path / "ziel").path
    _rewrite(backup, lambda items: {**items, "data/gui-config.json": b"{}"})
    vorher = inhalt(root)
    with pytest.raises(BackupError):
        restore.stage_restore(backup, root, ["einstellungen"])
    assert restore.pending(root) is None and inhalt(root) == vorher
    assert not any(p.name.startswith(".wiederherstellung") for p in root.iterdir())


def _flip_inside(path: Path, member: str) -> Path:
    """Ein Byte mitten in den komprimierten Daten eines Eintrags kippen (z. B. defekter Datenträger)."""
    data = bytearray(path.read_bytes())
    with zipfile.ZipFile(path) as zf:
        info = zf.getinfo(member)
    offset = info.header_offset
    name_len, extra_len = int.from_bytes(data[offset + 26 : offset + 28], "little"), int.from_bytes(data[offset + 28 : offset + 30], "little")
    data[offset + 30 + name_len + extra_len + info.compress_size // 2] ^= 0xFF
    target = path.with_name("defekt-" + path.name)
    target.write_bytes(bytes(data))
    return target


def test_staging_checks_every_restored_file_and_reports_progress(tmp_path: Path) -> None:
    root = datenordner(tmp_path / "daten")
    backup = archive.create_backup(root, tmp_path / "ziel").path
    schritte: list[tuple[int, int]] = []
    restore.stage_restore(backup, root, ["vorlagen", "regelwerke"], progress=lambda done, total: schritte.append((done, total)))
    assert schritte and schritte[-1][0] == schritte[-1][1] == len(schritte)
    assert restore.discard_pending(root)
    vorher = inhalt(root)
    # Gleiche Länge, anderer Inhalt: beim Entpacken erkannt
    manipuliert = tmp_path / "manipuliert.pdtbackup"
    manipuliert.write_bytes(backup.read_bytes())
    _rewrite(manipuliert, lambda items: {**items, "data/vorlagen/t-1.json": items["data/vorlagen/t-1.json"].replace(b"Energie", b"Energia")})
    with pytest.raises(BackupError, match="Prüfsumme"):
        restore.stage_restore(manipuliert, root, ["vorlagen"])
    # Defekte komprimierte Daten: eine verständliche Meldung, kein Programmfehler
    for kaputt in (_flip_inside(backup, "data/vorlagen/t-1.json"),):
        with pytest.raises(BackupError, match="beschädigt"):
            archive.inspect_backup(kaputt)
        with pytest.raises(BackupError, match="beschädigt"):
            restore.stage_restore(kaputt, root, ["vorlagen"])
    assert restore.pending(root) is None and inhalt(root) == vorher
    assert not any(p.name.startswith(".wiederherstellung") for p in root.iterdir())


# --- Automatisch, Aufbewahrung, Status -------------------------------------------------------------------------


def test_auto_backup_at_most_daily_and_only_after_changes(tmp_path: Path) -> None:
    root = datenordner(tmp_path / "daten")
    state = policy.BackupState()
    now = datetime(2026, 10, 1, 9, 0).astimezone()
    stand = archive.fingerprint(root)
    assert policy.auto_due(state, stand, now)
    state.note(archive.KIND_AUTO, root / "x.pdtbackup", now.isoformat(), stand)
    assert not policy.auto_due(state, stand, now + timedelta(days=3))  # nichts geändert
    schreibe(root / "vorlagen" / "t-2.json", {"schema_version": 1, "id": "t-2", "name": "Neu"})
    neu = archive.fingerprint(root)
    assert neu != stand
    assert not policy.auto_due(state, neu, now + timedelta(hours=5))  # noch kein Tag vergangen
    assert policy.auto_due(state, neu, now + timedelta(hours=24))
    state.automatic = False
    assert not policy.auto_due(state, neu, now + timedelta(days=9))
    # Status bleibt außerhalb der Sicherung erhalten
    assert state.save(root) and policy.BackupState.load(root) == state
    schreibe(root / policy.STATE_FILE, "{ kaputt")
    assert policy.BackupState.load(root) == policy.BackupState()


def test_retention_never_deletes_manual_backups(tmp_path: Path) -> None:
    root = datenordner(tmp_path / "daten")
    folder = tmp_path / "Sicherungen"
    start = datetime(2026, 1, 1, 8, 0)
    manual = [archive.create_backup(root, folder, kind=archive.KIND_MANUAL, now=start + timedelta(minutes=i)).path for i in range(3)]
    autos = [archive.create_backup(root, folder, kind=archive.KIND_AUTO, now=start + timedelta(days=i)).path for i in range(13)]
    updates = [archive.create_backup(root, folder, kind=archive.KIND_PRE_UPDATE, now=start + timedelta(days=i, hours=1)).path for i in range(7)]
    fremd = schreibe(folder / "PDF-Tool-Sicherung_fremd.pdtbackup", b"kein zip")
    removed = policy.prune(folder)
    assert sorted(removed) == sorted(autos[:3] + updates[:2])
    assert all(path.is_file() for path in manual + autos[3:] + updates[2:] + [fremd])
    listed = policy.list_backups(folder)
    assert [entry.kind for entry in listed].count("automatisch") == 10 and listed[0].created_at >= listed[-1].created_at


# --- Leistung ----------------------------------------------------------------------------------------------------


def test_large_backup_and_restore_performance(tmp_path: Path) -> None:
    """Großer Datenbestand: 500 Kundenakten mit je 10 Vertragsständen, 100 Vorlagen, 100 Regelwerke."""
    root = tmp_path / "daten"
    datenordner(root, kunden=500, staende=10)
    for i in range(100):
        schreibe(root / "vorlagen" / f"t-{i}.json", {"schema_version": 1, "id": f"t-{i}", "name": f"Vorlage {i}", "text": "x" * 2000})
        schreibe(root / "regelwerke" / f"r-{i}.json", {"schema_version": 1, "id": f"r-{i}", "name": f"Regelwerk {i}", "rules": [{"id": f"x{j}"} for j in range(10)]})
    start = time.perf_counter()
    result = archive.create_backup(root, tmp_path / "ziel", app_version=VERSION)
    created = time.perf_counter() - start
    start = time.perf_counter()
    info = archive.inspect_backup(result.path)
    checked = time.perf_counter() - start
    start = time.perf_counter()
    restore.stage_restore(result.path, root, [area.key for area in archive.AREAS])
    assert restore.apply_pending(root).ok
    restored = time.perf_counter() - start
    print(f"\nSicherung: {result.files} Dateien, {result.data_bytes / 1e6:.1f} MB Daten → {result.size / 1e6:.2f} MB; erstellen {created:.2f} s, prüfen {checked:.2f} s, wiederherstellen {restored:.2f} s")
    assert info.area("kunden").summary.startswith("500 Kundenakten · 5000 Vertragsstände")
    assert created < 60 and checked < 60 and restored < 60
