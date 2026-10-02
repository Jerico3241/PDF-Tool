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


# --- Release Candidate (release_candidate.py): Build once → Test → Release exakt dieses Artifact ------------------

_rc_spec = importlib.util.spec_from_file_location("release_candidate", ROOT / "release_candidate.py")
release_candidate = importlib.util.module_from_spec(_rc_spec)
_rc_spec.loader.exec_module(release_candidate)

CI_COMMIT = "abc123" + "0" * 34  # erfolgreich auf main geprüft
RELEASE_COMMIT = "abc124" + "0" * 34  # ein anderer Commit
RUN = 4711


def _candidate(tmp_path, version: str = "3.0.0-beta.1", commit: str = CI_COMMIT, run: int = RUN):
    dist, notes, digest = _dist(tmp_path, version)
    assert release_candidate.write(dist, commit, run, 1, version, notes, min_size=0) == []
    return dist, notes, digest


def _run(sha: str, run_id: int, number: int, **changes) -> dict:
    run = {"id": run_id, "run_number": number, "run_attempt": 1, "head_sha": sha, "head_branch": "main", "event": "push", "status": "completed", "conclusion": "success"}
    run.update(changes)
    return run


def _artifact(sha: str, run_id: int, **changes) -> dict:
    artifact = {"id": 99, "name": release_candidate.artifact_name(sha), "expired": False, "workflow_run": {"id": run_id, "head_sha": sha, "head_branch": "main"}}
    artifact.update(changes)
    return artifact


def test_release_candidate_is_bound_to_commit_run_and_setup(tmp_path) -> None:
    dist, notes, digest = _candidate(tmp_path)
    manifest = json.loads((dist / release_candidate.MANIFEST).read_text(encoding="utf-8"))
    assert manifest == {"format": 1, "commit": CI_COMMIT, "run_id": RUN, "run_attempt": 1, "version": "3.0.0-beta.1", "setup": "PDF-Tool-Setup-3.0.0-beta.1.exe", "sha256": digest}
    assert release_candidate.artifact_name(CI_COMMIT) == f"PDF-Tool-Release-Candidate-{CI_COMMIT}"
    assert release_candidate.verify(dist, CI_COMMIT, RUN, "3.0.0-beta.1", notes, min_size=0) == []


def test_ci_of_another_commit_never_releases(tmp_path) -> None:
    """CI erfolgreich für abc123, Release-Commit abc124 → ablehnen (nur CI-Commit == Release-Commit)."""
    dist, notes, _digest = _candidate(tmp_path)
    problems = release_candidate.verify(dist, RELEASE_COMMIT, RUN, "3.0.0-beta.1", notes, min_size=0)
    assert f"Release Candidate gehört zu Commit {CI_COMMIT}, nicht zum Release-Commit {RELEASE_COMMIT}" in problems
    assert release_candidate.candidate_runs({"workflow_runs": [_run(CI_COMMIT, RUN, 7)]}, RELEASE_COMMIT) == []
    assert release_candidate.candidate_artifact({"artifacts": [_artifact(CI_COMMIT, RUN)]}, RELEASE_COMMIT, RUN) is None
    # auch ein umbenanntes Artifact eines anderen Commits zählt nicht: entscheidend ist der Lauf dahinter
    renamed = _artifact(CI_COMMIT, RUN, name=release_candidate.artifact_name(RELEASE_COMMIT))
    assert release_candidate.candidate_artifact({"artifacts": [renamed]}, RELEASE_COMMIT, RUN) is None


def test_only_successful_main_runs_of_exactly_this_commit_count() -> None:
    runs = {"workflow_runs": [
        _run(CI_COMMIT, 1, 10),
        _run(CI_COMMIT, 2, 12, event="workflow_dispatch"),  # manueller main-Lauf, neuer
        _run(CI_COMMIT, 3, 13, conclusion="failure"),
        _run(CI_COMMIT, 4, 14, status="in_progress", conclusion=None),
        _run(CI_COMMIT, 5, 15, event="pull_request", head_branch="feature/x"),
        _run(CI_COMMIT, 6, 16, head_branch="feature/x", event="workflow_dispatch"),
        _run(CI_COMMIT[:7], 7, 17),
        _run(RELEASE_COMMIT, 8, 18),
    ]}
    assert release_candidate.candidate_runs(runs, CI_COMMIT) == [2, 1]
    assert release_candidate.candidate_runs(runs, CI_COMMIT[:7]) == []  # nie eine Kurzform


def test_expired_or_foreign_artifacts_are_never_used() -> None:
    assert release_candidate.candidate_artifact({"artifacts": [_artifact(CI_COMMIT, RUN)]}, CI_COMMIT, RUN) == 99
    assert release_candidate.candidate_artifact({"artifacts": [_artifact(CI_COMMIT, RUN, expired=True)]}, CI_COMMIT, RUN) is None
    assert release_candidate.candidate_artifact({"artifacts": [_artifact(CI_COMMIT, RUN + 1)]}, CI_COMMIT, RUN) is None
    assert release_candidate.candidate_artifact({"artifacts": [_artifact(CI_COMMIT, RUN, name="PDF-Tool-Setup-" + CI_COMMIT)]}, CI_COMMIT, RUN) is None
    feature = _artifact(CI_COMMIT, RUN, workflow_run={"id": RUN, "head_sha": CI_COMMIT, "head_branch": "feature/x"})
    assert release_candidate.candidate_artifact({"artifacts": [feature]}, CI_COMMIT, RUN) is None


def test_tampered_or_mixed_candidates_are_rejected(tmp_path) -> None:
    dist, notes, _digest = _candidate(tmp_path)
    setup = dist / "PDF-Tool-Setup-3.0.0-beta.1.exe"
    # anderer Lauf, andere Version des Commits
    assert any("nicht aus dem geprüften main-Lauf" in p for p in release_candidate.verify(dist, CI_COMMIT, RUN + 1, "3.0.0-beta.1", notes, min_size=0))
    assert any("VERSION des Commits ist 3.0.0" in p for p in release_candidate.verify(dist, CI_COMMIT, RUN, "3.0.0", notes, min_size=0))
    # nachträglich verändertes Setup: Prüfsumme und Manifest passen nicht mehr
    setup.write_bytes(setup.read_bytes() + b"\0")
    problems = release_candidate.verify(dist, CI_COMMIT, RUN, "3.0.0-beta.1", notes, min_size=0)
    assert "Prüfsumme gehört nicht zum Setup" in problems and "SHA-256 des Setups weicht vom Manifest ab" in problems
    # fremde Datei im Artifact, fehlendes Manifest
    (tmp_path / "zwei").mkdir()
    dist2, notes2, _ = _candidate(tmp_path / "zwei")
    (dist2 / "notiz.txt").write_text("x", encoding="utf-8")
    assert release_candidate.verify(dist2, CI_COMMIT, RUN, "3.0.0-beta.1", notes2, min_size=0) == ["Unerwartete Dateien: notiz.txt"]
    (dist2 / "notiz.txt").unlink()
    (dist2 / release_candidate.MANIFEST).unlink()
    assert release_candidate.verify(dist2, CI_COMMIT, RUN, "3.0.0-beta.1", notes2, min_size=0) == ["Manifest fehlt: release-candidate.json"]
    assert release_candidate.verify(dist2, "abc124", RUN, "3.0.0-beta.1", notes2, min_size=0)[0].startswith("Ungültiger Commit")


def test_write_refuses_a_failed_check(tmp_path) -> None:
    dist, notes, _digest = _dist(tmp_path, "3.0.0-beta.1", line=f"{'0' * 64}  PDF-Tool-Setup-3.0.0-beta.1.exe\n")
    assert "Prüfsumme gehört nicht zum Setup" in release_candidate.write(dist, CI_COMMIT, RUN, 1, "3.0.0-beta.1", notes, min_size=0)
    assert not (dist / release_candidate.MANIFEST).exists()


def test_release_candidate_command_line(tmp_path, monkeypatch, capsys) -> None:
    root = tmp_path / "checkout"
    (root / "windows-app" / "release-notes").mkdir(parents=True)
    (root / "windows-app" / "VERSION").write_text("3.0.0-beta.1\n", encoding="utf-8")
    (root / "windows-app" / "release-notes" / "3.0.0-beta.1.md").write_text("# Notes", encoding="utf-8")
    dist, _notes, digest = _dist(tmp_path, "3.0.0-beta.1")
    monkeypatch.setattr(release_candidate, "MIN_SIZE", 0)  # künstliches Setup statt 70 MB
    assert release_candidate.main(["write", str(dist), "--commit", CI_COMMIT, "--run", str(RUN), "--attempt", "2", "--root", str(root)]) == 0
    output = tmp_path / "github_output"
    assert release_candidate.main(["verify", str(dist), "--commit", CI_COMMIT, "--run", str(RUN), "--root", str(root), "--github-output", str(output)]) == 0
    values = dict(line.split("=", 1) for line in output.read_text(encoding="utf-8").splitlines())
    assert values["tag"] == "v3.0.0-beta.1" and values["prerelease"] == "true" and values["sha256"] == digest
    assert values["notes"] == str(root / "windows-app" / "release-notes" / "3.0.0-beta.1.md")
    assert release_candidate.main(["verify", str(dist), "--commit", RELEASE_COMMIT, "--run", str(RUN), "--root", str(root)]) == 1
    runs = tmp_path / "runs.json"
    runs.write_text(json.dumps({"workflow_runs": [_run(CI_COMMIT, RUN, 3)]}), encoding="utf-8")
    capsys.readouterr()
    assert release_candidate.main(["runs", str(runs), "--commit", CI_COMMIT]) == 0 and capsys.readouterr().out.split() == [str(RUN)]
    assert release_candidate.main(["runs", str(runs), "--commit", RELEASE_COMMIT]) == 1
    artifacts = tmp_path / "artifacts.json"
    artifacts.write_text(json.dumps({"artifacts": [_artifact(CI_COMMIT, RUN)]}), encoding="utf-8")
    assert release_candidate.main(["artifact", str(artifacts), "--commit", CI_COMMIT, "--run", str(RUN)]) == 0 and capsys.readouterr().out.split() == ["99"]
    assert release_candidate.main(["artifact", str(artifacts), "--commit", RELEASE_COMMIT, "--run", str(RUN)]) == 1


# --- Workflows: ein Veröffentlichungsweg, kein Neubau beim Release, Härtung erhalten --------------------------------

WORKFLOWS = ROOT.parent / ".github" / "workflows"


def test_actions_stay_pinned_to_commit_shas_and_checkouts_keep_no_credentials() -> None:
    import re

    for path in sorted(WORKFLOWS.glob("*.yml")):
        text = path.read_text(encoding="utf-8")
        for uses in re.findall(r"uses:\s*(\S+)", text):
            assert re.fullmatch(r"[\w.-]+/[\w./-]+@[0-9a-f]{40}", uses), f"{path.name}: {uses}"
        assert text.count("actions/checkout@") == text.count("persist-credentials: false"), path.name


def test_release_workflow_publishes_the_tested_artifact_without_rebuilding() -> None:
    text = (WORKFLOWS / "release.yml").read_text(encoding="utf-8")
    trigger = text.split("on:", 1)[1].split("permissions:", 1)[0]
    assert "workflow_dispatch:" in trigger and "push:" not in trigger and "release:" not in trigger and "pull_request" not in trigger
    for forbidden in ("build.py", "pytest", "ISCC", "upload-artifact", "--clobber", "git push", "git tag"):
        assert forbidden not in text, forbidden
    assert "run-id: ${{ steps.run.outputs.run }}" in text and "release_candidate.py verify" in text
    assert "refs/heads/main" in text and "merge-base --is-ancestor" in text and "hotfix_ohne_beta" in text


def test_setup_workflow_is_the_only_tester_and_stores_the_candidate_per_commit() -> None:
    text = (WORKFLOWS / "windows-setup.yml").read_text(encoding="utf-8")
    trigger = text.split("\non:", 1)[1].split("\npermissions:", 1)[0]
    assert "tags:" not in trigger and "release:" not in trigger and "inputs:" not in trigger
    assert "pull_request:" in trigger and "branches: [main]" in trigger
    assert "name: PDF-Tool-Release-Candidate-${{ github.sha }}" in text and "retention-days: 90" in text
    assert "needs: [qt-tests, setup]" in text and "contents: write" not in text
    assert "gh release create" not in text and "gh release upload" not in text  # veröffentlicht nie selbst
