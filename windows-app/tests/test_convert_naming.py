"""Umbenennen nach Muster (5.0 Beta 7, Fehler behoben in Beta 9): Rückgängig auch nach einem Tausch der Namen."""

from __future__ import annotations

from pathlib import Path

from tools.convert import naming


def _files(folder: Path, *names: str) -> list[Path]:
    paths = []
    for name in names:
        path = folder / name
        path.write_text(name, encoding="utf-8")
        paths.append(path)
    return paths


def test_undo_after_swapping_names(tmp_path: Path) -> None:
    """A → B und B → A: Die ursprünglichen Namen gibt es danach schon – Rückgängig muss trotzdem zurücktauschen."""
    a, b = _files(tmp_path, "1.txt", "2.txt")
    renames = naming.plan([b, a], "{nr}", start=1)
    assert [item.target.name for item in renames] == ["1.txt", "2.txt"]
    pairs = naming.apply(renames)
    assert (tmp_path / "1.txt").read_text(encoding="utf-8") == "2.txt"
    assert len(naming.undo(pairs)) == 2
    assert (tmp_path / "1.txt").read_text(encoding="utf-8") == "1.txt"
    assert (tmp_path / "2.txt").read_text(encoding="utf-8") == "2.txt"
    assert sorted(path.name for path in tmp_path.iterdir()) == ["1.txt", "2.txt"]


def test_undo_keeps_new_name_when_old_one_is_taken(tmp_path: Path) -> None:
    (a,) = _files(tmp_path, "brief.txt")
    pairs = naming.apply(naming.plan([a], "{name}_neu"))
    (tmp_path / "brief.txt").write_text("neue Datei", encoding="utf-8")
    assert naming.undo(pairs) == []
    assert (tmp_path / "brief_neu.txt").read_text(encoding="utf-8") == "brief.txt"
    assert (tmp_path / "brief.txt").read_text(encoding="utf-8") == "neue Datei"
    assert sorted(path.name for path in tmp_path.iterdir()) == ["brief.txt", "brief_neu.txt"]
