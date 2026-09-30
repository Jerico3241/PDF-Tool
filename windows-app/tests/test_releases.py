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

# Veröffentlichte Releases dieses Projekts (Stand 2.7.0) – samt Entwurf und Vorabversion
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
