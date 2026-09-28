"""Übernahme der Benutzerdaten vom Übersichten-Ersteller (bis 2.2) nach PDF Tool (ab 2.3).

%APPDATA%\\Uebersichten-Ersteller → %APPDATA%\\PDF-Tool: einmalig, mit Sicherung, verlustfrei
geprüft; der alte Ordner bleibt erhalten, bei einem Fehler arbeitet die App mit ihm weiter.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import zipfile
from pathlib import Path

import pytest

import appstate

CONFIG = {
    "gesehen": "2.2.0",
    "theme": "dark",
    "vorlagen": [{"name": "Standard", "titel": "Vertragsübersicht"}],
    "kunden": [{"kd": "10042", "name": "Müller & Söhne GmbH"}],
    "regeln": [{"enthaelt": "Hott-KI", "zyklus": "jährlich"}],
    "fusszeile": "Alle Preise zzgl. MwSt.",
    "fusszeile_explizit": True,
}


def hashes(folder: Path) -> dict[str, str]:
    return {
        path.relative_to(folder).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(folder.rglob("*"))
        if path.is_file()
    }


@pytest.fixture
def legacy(tmp_path: Path) -> Path:
    folder = tmp_path / "Uebersichten-Ersteller"
    folder.mkdir()
    (folder / "gui-config.json").write_text(json.dumps(CONFIG, ensure_ascii=False, indent=2), encoding="utf-8")
    (folder / "fehler.log").write_text("alter Fehlerbericht\n", encoding="utf-8")
    (folder / "logos").mkdir()
    (folder / "logos" / "Kundenlogo März.png").write_bytes(bytes(range(256)) * 40)
    return folder


def test_data_is_copied_verified_and_backed_up(tmp_path: Path, legacy: Path) -> None:
    before = hashes(legacy)
    target = tmp_path / "PDF-Tool"
    assert appstate.migrate_user_data(legacy, target, "2.3.0") is True
    # vollständig und identisch übernommen
    copied = {name: digest for name, digest in hashes(target).items() if name in before}
    assert copied == before
    assert json.loads((target / "gui-config.json").read_text(encoding="utf-8")) == CONFIG
    # Sicherung vor der Übernahme, benannt nach der zuletzt verwendeten Version
    backup = target / "migration-backup-2.2.0.zip"
    with zipfile.ZipFile(backup) as archive:
        assert sorted(archive.namelist()) == sorted(before)
        assert archive.read("gui-config.json") == (legacy / "gui-config.json").read_bytes()
    marker = json.loads((target / appstate.MIGRATION_MARKER).read_text(encoding="utf-8"))
    assert marker["version"] == "2.3.0" and marker["zuletzt_gesehen"] == "2.2.0"
    assert marker["dateien"] == len(before) and marker["sicherung"] == backup.name
    # der alte Ordner bleibt unverändert erhalten
    assert hashes(legacy) == before


def test_migration_runs_only_once(tmp_path: Path, legacy: Path) -> None:
    target = tmp_path / "PDF-Tool"
    assert appstate.migrate_user_data(legacy, target) is True
    (target / "gui-config.json").write_text(json.dumps({"theme": "light"}), encoding="utf-8")
    (legacy / "gui-config.json").write_text(json.dumps({"theme": "system"}), encoding="utf-8")
    assert appstate.migrate_user_data(legacy, target) is False
    assert json.loads((target / "gui-config.json").read_text(encoding="utf-8")) == {"theme": "light"}
    # auch ohne Einstellungsdatei: der Vermerk verhindert eine zweite Übernahme
    (target / "gui-config.json").unlink()
    assert appstate.migrate_user_data(legacy, target) is False


def test_existing_settings_are_never_overwritten(tmp_path: Path, legacy: Path) -> None:
    target = tmp_path / "PDF-Tool"
    target.mkdir()
    (target / "gui-config.json").write_text(json.dumps({"theme": "light"}), encoding="utf-8")
    assert appstate.migrate_user_data(legacy, target) is False
    assert json.loads((target / "gui-config.json").read_text(encoding="utf-8")) == {"theme": "light"}
    assert not (target / appstate.MIGRATION_MARKER).exists()


def test_failed_copy_keeps_old_data_and_removes_partial_copy(tmp_path: Path, legacy: Path, monkeypatch) -> None:
    before = hashes(legacy)
    target = tmp_path / "PDF-Tool"
    real_copy = shutil.copy2
    calls = []

    def failing_copy(source, destination, *args, **kwargs):
        calls.append(source)
        if len(calls) == 2:
            raise OSError(28, "Kein Speicherplatz")
        return real_copy(source, destination, *args, **kwargs)

    monkeypatch.setattr(appstate.shutil, "copy2", failing_copy)
    assert appstate.migrate_user_data(legacy, target) is False
    assert hashes(legacy) == before
    assert not (target / "gui-config.json").exists() and not (target / appstate.MIGRATION_MARKER).exists()
    # nur die Sicherung bleibt – teilweise kopierte Dateien sind entfernt
    assert [path.name for path in target.rglob("*") if path.is_file()] == ["migration-backup-2.2.0.zip"]


def test_differing_copy_is_detected(tmp_path: Path, legacy: Path, monkeypatch) -> None:
    target = tmp_path / "PDF-Tool"
    real_copy = shutil.copy2

    def corrupting_copy(source, destination, *args, **kwargs):
        result = real_copy(source, destination, *args, **kwargs)
        if Path(source).suffix == ".png":
            with open(destination, "r+b") as handle:
                handle.write(b"\xff")
        return result

    monkeypatch.setattr(appstate.shutil, "copy2", corrupting_copy)
    assert appstate.migrate_user_data(legacy, target) is False
    assert not (target / "gui-config.json").exists() and not (target / appstate.MIGRATION_MARKER).exists()


def test_data_dir_migrates_on_first_start(tmp_path: Path, legacy: Path, monkeypatch) -> None:
    monkeypatch.delenv("UE_DATA_DIR", raising=False)
    monkeypatch.setenv("APPDATA", str(tmp_path))
    assert appstate.data_dir() == tmp_path / "PDF-Tool"
    assert (tmp_path / "PDF-Tool" / appstate.MIGRATION_MARKER).is_file()
    # zweiter Start: keine erneute Übernahme, derselbe Ordner
    (legacy / "gui-config.json").write_text("{}", encoding="utf-8")
    assert appstate.data_dir() == tmp_path / "PDF-Tool"
    assert json.loads((tmp_path / "PDF-Tool" / "gui-config.json").read_text(encoding="utf-8")) == CONFIG


def test_data_dir_falls_back_to_old_folder_when_migration_fails(tmp_path: Path, legacy: Path, monkeypatch) -> None:
    monkeypatch.delenv("UE_DATA_DIR", raising=False)
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.setattr(appstate, "migrate_user_data", lambda *args, **kwargs: False)
    assert appstate.data_dir() == legacy


def test_data_dir_without_previous_version(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("UE_DATA_DIR", raising=False)
    monkeypatch.setenv("APPDATA", str(tmp_path))
    assert appstate.data_dir() == tmp_path / "PDF-Tool"
    assert not (tmp_path / "PDF-Tool").exists()  # entsteht erst beim ersten Speichern
