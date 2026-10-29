"""Backup-Center (5.0 Beta 7): Ablage der Fassungen ohne Oberfläche – Ablegen, doppelte Stände, Aufräumen,
Wiederherstellen als Kopie und über das Original."""

from __future__ import annotations

import os
import time
from pathlib import Path

from backup import versions


def store(tmp_path: Path, **settings) -> versions.VersionStore:
    return versions.VersionStore(tmp_path / "Fassungen", versions.Settings(**settings))


def test_remember_skips_duplicates_and_empty_files(tmp_path: Path) -> None:
    s = store(tmp_path)
    original = tmp_path / "Brief.docx"
    original.write_bytes(b"eins")
    first = s.remember(original)
    assert first is not None and first.read_bytes() == b"eins"
    assert s.remember(original) is None  # gleich der neuesten Fassung
    original.write_bytes(b"zwei")
    second = s.remember(original)
    assert second is not None and second != first
    (tmp_path / "leer.pdf").write_bytes(b"")
    assert s.remember(tmp_path / "leer.pdf") is None
    assert s.remember(tmp_path / "fehlt.pdf") is None
    document = s.document(versions.key_of(original))
    assert document is not None and document.name == "Brief.docx" and document.exists
    assert [v.path.read_bytes() for v in document.versions] == [b"zwei", b"eins"]
    assert all(v.kind == versions.BEFORE_SAVE for v in document.versions)


def test_disabled_store_keeps_nothing(tmp_path: Path) -> None:
    s = store(tmp_path, enabled=False)
    original = tmp_path / "a.pdf"
    original.write_bytes(b"x")
    assert s.remember(original) is None and s.documents() == []


def test_names_stay_unique_within_one_millisecond(tmp_path: Path, monkeypatch) -> None:
    s = store(tmp_path)
    monkeypatch.setattr(versions.time, "time", lambda: 1_800_000_000.5)
    original = tmp_path / "a.pdf"
    paths = []
    for number in range(3):
        original.write_bytes(f"stand {number}".encode())
        paths.append(s.remember(original))
    assert len(set(paths)) == 3 and all(path.is_file() for path in paths)


def test_prune_keeps_limit_and_always_the_newest(tmp_path: Path) -> None:
    s = store(tmp_path, keep=5, days=7)
    original = tmp_path / "Tabelle.xlsx"
    for number in range(7):
        original.write_bytes(f"stand {number}".encode())
        s.remember(original)
    document = s.document(versions.key_of(original))
    assert len(document.versions) == 5 and document.versions[0].path.read_bytes() == b"stand 6"
    # Alles älter als die Aufbewahrungszeit geht – außer der neuesten Fassung
    assert s.prune_all(now=time.time() + 30 * 86400) == 4
    document = s.document(versions.key_of(original))
    assert [v.path.read_bytes() for v in document.versions] == [b"stand 6"]


def test_snapshot_written_and_added(tmp_path: Path) -> None:
    s = store(tmp_path)
    original = tmp_path / "Folien.pptx"
    original.write_bytes(b"gespeichert")
    s.remember(original)
    target = s.snapshot_path(original, ".pptx")
    assert target.is_file() and target.stat().st_size == 0
    assert len(s.document(versions.key_of(original)).versions) == 1  # leere Platzhalter zählen nicht
    target.write_bytes(b"ungespeichert")
    assert s.added(target)
    document = s.document(versions.key_of(original))
    assert document.versions[0].kind == versions.AUTOMATIC and document.versions[0].path.read_bytes() == b"ungespeichert"
    again = s.snapshot_path(original, ".pptx")
    again.write_bytes(b"ungespeichert")
    assert not s.added(again) and not again.exists()  # gleicher Stand wie die neueste Fassung
    empty = s.snapshot_path(original, ".pptx")
    assert not s.added(empty) and not empty.exists()
    # Liegengebliebener Platzhalter wird beim Aufräumen entfernt
    stale = s.snapshot_path(original, ".pptx")
    os.utime(stale, (time.time() - 2 * 86400, time.time() - 2 * 86400))
    s.prune_all()
    assert not stale.exists()


def test_restore_copy_and_replace(tmp_path: Path) -> None:
    s = store(tmp_path)
    original = tmp_path / "Brief.docx"
    original.write_bytes(b"alt")
    old = s.remember(original)
    original.write_bytes(b"neu")
    copy = s.restore_copy(old, str(original))
    assert copy.parent == tmp_path and copy.name.startswith("Brief (Fassung ") and copy.suffix == ".docx"
    assert copy.read_bytes() == b"alt" and original.read_bytes() == b"neu"
    second = s.restore_copy(old, str(original))
    assert second != copy and second.read_bytes() == b"alt"  # nie überschreiben
    s.restore_replace(old, str(original))
    assert original.read_bytes() == b"alt"
    contents = [v.path.read_bytes() for v in s.document(versions.key_of(original)).versions]
    assert contents[0] == b"neu" and b"alt" in contents  # der Stand vor dem Ersetzen ist gesichert


def test_delete_only_inside_the_store(tmp_path: Path) -> None:
    s = store(tmp_path)
    original = tmp_path / "a.pdf"
    original.write_bytes(b"x")
    version = s.remember(original)
    assert not s.delete(original) and original.exists()
    assert s.delete(version) and not version.exists()
    original.write_bytes(b"y")
    s.remember(original)
    s.delete_document(versions.key_of(original))
    assert s.documents() == [] and original.exists()


def test_settings_round_trip_and_invalid_values() -> None:
    settings = versions.Settings(enabled=False, minutes=5, keep=50, days=365)
    assert versions.Settings.from_config(settings.to_config()) == settings
    broken = versions.Settings.from_config({"minuten": 7, "behalten": "viele", "tage": -1})
    assert broken == versions.Settings()
    assert versions.Settings.from_config(None) == versions.Settings()
