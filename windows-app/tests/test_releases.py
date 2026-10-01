"""Auswahl der Vorversion für den Update-Test der CI (``windows-app/releases.py``): SemVer, nie alphabetisch."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("releases", ROOT / "releases.py")
releases = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(releases)

# Veröffentlichte Releases dieses Projekts (Stand 2.7.1) – samt Entwurf und Vorabversion
PUBLISHED = [
    {"tagName": "v2.7.0", "isDraft": False, "isPrerelease": False},
    {"tagName": "v2.6.1", "isDraft": False, "isPrerelease": False},
    {"tagName": "v2.6.0", "isDraft": False, "isPrerelease": False},
    {"tagName": "v2.5.0", "isDraft": False, "isPrerelease": False},
    {"tagName": "v2.4.0", "isDraft": False, "isPrerelease": False},
    {"tagName": "v2.3.0", "isDraft": False, "isPrerelease": False},
    {"tagName": "v2.2.0", "isDraft": False, "isPrerelease": False},
    {"tagName": "v2.1.0", "isDraft": False, "isPrerelease": False},
    {"tagName": "v2.8.0-rc1", "isDraft": False, "isPrerelease": True},
    {"tagName": "v2.7.1", "isDraft": True, "isPrerelease": False},
    {"tagName": "nightly", "isDraft": False, "isPrerelease": False},
]


def test_previous_stable_for_270_is_261() -> None:
    versions = releases.stable_versions(PUBLISHED)
    assert releases.previous_stable((2, 7, 0), versions) == (2, 6, 1)
    # Entwürfe, Vorabversionen und fremde Tags zählen nie
    assert (2, 7, 1) not in versions and (2, 8, 0) not in versions


def test_previous_stable_for_271_is_270() -> None:
    """Update-Test von 2.7.1: von 2.7.0 (der Entwurf von 2.7.1 selbst zählt nicht)."""
    versions = releases.stable_versions(PUBLISHED)
    assert releases.previous_stable((2, 7, 1), versions) == (2, 7, 0)
    assert [releases.text(v) for v in releases.older_stable((2, 7, 1), versions)][-2:] == ["2.6.1", "2.7.0"]


def test_semver_not_alphabetical() -> None:
    tags = [{"tagName": tag} for tag in ("v2.9.1", "v2.10.0", "v2.4.0", "v2.10.1-beta")]
    versions = releases.stable_versions(tags)
    assert versions == [(2, 4, 0), (2, 9, 1), (2, 10, 0)]
    # alphabetisch wäre »2.9.1« größer als »2.10.0«
    assert releases.previous_stable((2, 10, 1), versions) == (2, 10, 0)
    assert releases.previous_stable((2, 10, 0), versions) == (2, 9, 1)
    assert releases.previous_stable((2, 4, 0), versions) is None


def test_all_older_versions_for_the_manual_deep_test() -> None:
    versions = releases.stable_versions(PUBLISHED)
    assert [releases.text(v) for v in releases.older_stable((2, 7, 0), versions)] == ["2.2.0", "2.3.0", "2.4.0", "2.5.0", "2.6.0", "2.6.1"]


def test_command_line(tmp_path: Path, capsys) -> None:
    liste = tmp_path / "releases.json"
    liste.write_text(json.dumps(PUBLISHED), encoding="utf-8")
    aktuell = releases.text(releases.current_version())
    assert releases.main(["previous", "--releases", str(liste)]) == 0
    vorher = capsys.readouterr().out.strip()
    assert releases.parse(vorher) == releases.previous_stable(releases.current_version(), releases.stable_versions(PUBLISHED))
    assert releases.parse(vorher) < releases.parse(aktuell)
    assert releases.main(["all", "--releases", str(liste), "--only", "2.4.0,2.2.0", "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == ["2.2.0", "2.4.0"]
    assert releases.main(["all", "--releases", str(liste), "--only", "1.0.0"]) == 1


@pytest.mark.parametrize("value,expected", [("v2.6.1", (2, 6, 1)), ("2.10.0", (2, 10, 0)), ("v2.7.0-rc1", None), ("2.7", None), ("", None)])
def test_parse(value: str, expected) -> None:
    assert releases.parse(value) == expected


def test_previous_stable_for_272_is_271_and_betas_never_count() -> None:
    """Normaler Workflow für 2.7.2: Clean Install und genau 2.7.1 → 2.7.2 (keine historische Kette)."""
    published = [{"tagName": "v2.7.1", "isDraft": False, "isPrerelease": False}, {"tagName": "v2.7.2-beta.1", "isDraft": False, "isPrerelease": True}] + PUBLISHED
    versions = releases.stable_versions(published)
    assert releases.previous_stable((2, 7, 2), versions) == (2, 7, 1)


def test_beta_version_file_is_understood(tmp_path, monkeypatch) -> None:
    """VERSION »2.8.0-beta.1«: der Update-Test startet bei der letzten stabilen Version vor 2.8.0."""
    (tmp_path / "VERSION").write_text("2.8.0-beta.1\n", encoding="utf-8")
    monkeypatch.setattr(releases, "HERE", tmp_path)
    assert releases.current_version() == (2, 8, 0)
    published = [{"tagName": "v2.7.2", "isDraft": False, "isPrerelease": False}, {"tagName": "v2.8.0-beta.0", "isDraft": False, "isPrerelease": True}]
    assert releases.previous_stable(releases.current_version(), releases.stable_versions(published)) == (2, 7, 2)
    (tmp_path / "VERSION").write_text("2.8.0-rc1\n", encoding="utf-8")
    with pytest.raises(SystemExit):
        releases.current_version()


# --- Release-Dateien prüfen (release_check.py) --------------------------------------------------------------------------

_check_spec = importlib.util.spec_from_file_location("release_check", ROOT / "release_check.py")
release_check = importlib.util.module_from_spec(_check_spec)
_check_spec.loader.exec_module(release_check)


@pytest.mark.parametrize("version,ok", [("2.7.2", True), ("2.8.0-beta.1", True), ("2.8.0-beta.12", True), ("2.8.0-beta.0", False), ("2.8.0-beta", False), ("2.8.0-rc.1", False), ("2.8.0-beta.1+b5", False), ("v2.8.0", False), ("2.8", False), ("2.08.0", False)])
def test_release_versions(version, ok) -> None:
    assert release_check.valid_version(version) is ok


def test_beta_is_a_prerelease_and_stable_is_not() -> None:
    assert release_check.outputs("2.8.0-beta.1") == {
        "version": "2.8.0-beta.1",
        "tag": "v2.8.0-beta.1",
        "title": "PDF Tool 2.8.0-beta.1",
        "prerelease": "true",
        "setup": "PDF-Tool-Setup-2.8.0-beta.1.exe",
        "checksum": "PDF-Tool-Setup-2.8.0-beta.1.exe.sha256",
        "notes": "windows-app/release-notes/2.8.0-beta.1.md",
    }
    assert release_check.outputs("2.7.2")["prerelease"] == "false" and release_check.outputs("2.7.2")["tag"] == "v2.7.2"
    assert release_check.numeric_version("2.8.0-beta.1") == "2.8.0"


def _setup_bytes(numeric: str) -> bytes:
    import struct

    major, minor, patch = (int(part) for part in numeric.split("."))
    info = b"\xbd\x04\xef\xfe" + struct.pack("<I", 0x10000) + struct.pack("<II", (major << 16) | minor, patch << 16)
    return b"MZ" + b"\0" * 200 + info + b"\0" * 4000


def _dist(tmp_path, version: str, numeric: str | None = None, line: str | None = None):
    dist = tmp_path / "dist"
    dist.mkdir()
    name = f"PDF-Tool-Setup-{version}.exe"
    data = _setup_bytes(numeric or release_check.numeric_version(version))
    (dist / name).write_bytes(data)
    digest = __import__("hashlib").sha256(data).hexdigest()
    (dist / (name + ".sha256")).write_bytes((line if line is not None else f"{digest}  {name}\n").encode("ascii"))
    notes = tmp_path / "notes"
    notes.mkdir()
    (notes / f"{version}.md").write_text("# Notes", encoding="utf-8")
    return dist, notes, digest


@pytest.mark.parametrize("version", ["2.7.2", "2.8.0-beta.1"])
def test_release_files_are_validated(tmp_path, version) -> None:
    dist, notes, _digest = _dist(tmp_path, version)
    assert release_check.check(dist, version, notes, min_size=0) == []


def test_release_check_finds_every_problem(tmp_path) -> None:
    dist, notes, digest = _dist(tmp_path, "2.7.2", line=f"{'0' * 64}  PDF-Tool-Setup-2.7.1.exe\n")
    problems = release_check.check(dist, "2.7.2", notes, min_size=0)
    assert "Prüfsumme gehört nicht zum Setup" in problems
    assert any("nennt 'PDF-Tool-Setup-2.7.1.exe'" in problem for problem in problems)
    (dist / "PDF-Tool-Setup-2.7.2.exe.sha256").write_text(f"{digest}\n", encoding="ascii")  # nur der Hash: nicht das vereinbarte Format
    assert any("Format" in problem for problem in release_check.check(dist, "2.7.2", notes, min_size=0))
    (dist / "PDF-Tool-Setup-2.7.2.exe.sha256").unlink()
    assert release_check.check(dist, "2.7.2", notes, min_size=0) == ["Prüfsummendatei fehlt: PDF-Tool-Setup-2.7.2.exe.sha256"]
    (dist / "PDF-Tool-Setup-2.7.1.exe").write_bytes(b"MZ")
    assert any("Unerwartete Dateien" in problem for problem in release_check.check(dist, "2.7.2", notes, min_size=0))
    assert release_check.check(dist, "2.7.2-rc.1", notes) == ["VERSION ist ungültig: '2.7.2-rc.1' (erlaubt: X.Y.Z oder X.Y.Z-beta.N)"]


def test_release_check_compares_the_file_version_and_notes(tmp_path) -> None:
    dist, notes, _digest = _dist(tmp_path, "2.7.2", numeric="2.7.1")
    (notes / "2.7.2.md").unlink()
    problems = release_check.check(dist, "2.7.2", notes, min_size=0)
    assert "Dateiversion des Setups ist 2.7.1, erwartet 2.7.2" in problems
    assert "Release Notes fehlen: release-notes/2.7.2.md" in problems
