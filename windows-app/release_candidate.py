"""Release Candidate: das auf ``main`` vollständig geprüfte Setup – eindeutig einem Commit zugeordnet.

Der main-Lauf von »Windows-Setup« (Push oder manueller Lauf) speichert Setup und Prüfsumme erst,
wenn alle Tests, der Build und alle Installer-Prüfungen bestanden sind – als Artifact
``PDF-Tool-Release-Candidate-<Commit-SHA>`` mit einem Manifest (``release-candidate.json``):
Commit, Lauf, Version, Setup und SHA-256. Der Release-Workflow veröffentlicht genau dieses
Artifact – ohne neuen Build und ohne erneute Tests.

    python windows-app/release_candidate.py write rc --commit <SHA> --run <Lauf> --attempt <Versuch>
    python windows-app/release_candidate.py runs runs.json --commit <SHA>
    python windows-app/release_candidate.py artifact artifacts.json --commit <SHA> --run <Lauf>
    python windows-app/release_candidate.py verify rc --commit <SHA> --run <Lauf> --root <Checkout des Commits>

* ``write`` (main-Lauf): Setup und Prüfsumme wie ``release_check.py`` prüfen, Manifest schreiben.
* ``runs`` (Release): aus der Antwort der GitHub-API die erfolgreichen main-Läufe für GENAU diesen
  Commit (neuester zuerst). Ein Lauf eines anderen Commits zählt nie.
* ``artifact`` (Release): das noch vorhandene Release-Candidate-Artifact dieses Laufs und Commits.
* ``verify`` (Release): Dateien, Manifest (Commit, Lauf, Version, Setup, SHA-256), Prüfsumme neu
  berechnet, Dateiversion und Release Notes aus dem Checkout des Release-Commits. Mit
  ``--github-output`` die Angaben für den Release-Schritt (wie ``release_check.py`` plus ``sha256``).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import release_check  # noqa: E402 - dieselben Prüfungen wie im Build

MANIFEST = "release-candidate.json"
PREFIX = "PDF-Tool-Release-Candidate-"
FORMAT = 1
_COMMIT = re.compile(r"^[0-9a-f]{40}$")
MAIN_EVENTS = ("push", "workflow_dispatch")
MIN_SIZE = 20 * 1024 * 1024  # wie release_check.check: ein echtes Setup ist deutlich größer


def valid_commit(commit: str) -> bool:
    """Vollständiger Commit-SHA (40 Hex-Zeichen, klein) – keine Kurzform, kein Branch- oder Tag-Name."""
    return bool(_COMMIT.match(commit or ""))


def artifact_name(commit: str) -> str:
    return PREFIX + commit


def _files(version: str) -> tuple[str, str]:
    setup = f"{release_check.SETUP_PREFIX}{version}.exe"
    return setup, setup + ".sha256"


def write(folder: Path, commit: str, run_id: int, attempt: int, version: str, notes_dir: Path | None = None, min_size: int = 20 * 1024 * 1024) -> list[str]:
    """Setup und Prüfsumme prüfen und das Manifest des Release Candidates schreiben (leer = in Ordnung)."""
    if not valid_commit(commit):
        return [f"Ungültiger Commit: {commit!r} (erwartet: vollständiger SHA)"]
    folder = Path(folder)
    problems = release_check.check(folder, version, notes_dir, min_size)
    if problems:
        return problems
    setup, checksum = _files(version)
    extra = sorted(path.name for path in folder.iterdir() if path.name not in (setup, checksum))
    if extra:
        return ["Unerwartete Dateien: " + ", ".join(extra)]
    manifest = {
        "format": FORMAT,
        "commit": commit,
        "run_id": int(run_id),
        "run_attempt": int(attempt),
        "version": version,
        "setup": setup,
        "sha256": release_check.sha256(folder / setup),
    }
    (folder / MANIFEST).write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return []


def candidate_runs(response: dict, commit: str) -> list[int]:
    """Erfolgreiche, abgeschlossene main-Läufe (Push oder manuell) für genau ``commit`` – neuester zuerst."""
    if not valid_commit(commit):
        return []
    runs = [
        run for run in response.get("workflow_runs", [])
        if run.get("head_sha") == commit
        and run.get("head_branch") == "main"
        and run.get("event") in MAIN_EVENTS
        and run.get("status") == "completed"
        and run.get("conclusion") == "success"
    ]
    runs.sort(key=lambda run: (run.get("run_number", 0), run.get("run_attempt", 0)), reverse=True)
    return [int(run["id"]) for run in runs]


def candidate_artifact(response: dict, commit: str, run_id: int) -> int | None:
    """Das noch vorhandene Release-Candidate-Artifact von ``commit`` aus genau dem Lauf ``run_id``."""
    if not valid_commit(commit):
        return None
    for artifact in response.get("artifacts", []):
        origin = artifact.get("workflow_run") or {}
        if (
            artifact.get("name") == artifact_name(commit)
            and not artifact.get("expired")
            and origin.get("id") == run_id
            and origin.get("head_sha") == commit
            and origin.get("head_branch") == "main"
        ):
            return int(artifact["id"])
    return None


def verify(folder: Path, commit: str, run_id: int, version: str, notes_dir: Path | None = None, min_size: int = 20 * 1024 * 1024) -> list[str]:
    """Release Candidate vor dem Veröffentlichen prüfen (leer = in Ordnung)."""
    if not valid_commit(commit):
        return [f"Ungültiger Commit: {commit!r} (erwartet: vollständiger SHA)"]
    if not release_check.valid_version(version):
        return [f"VERSION ist ungültig: {version!r} (erlaubt: X.Y.Z oder X.Y.Z-beta.N)"]
    folder = Path(folder)
    if not folder.is_dir():
        return [f"Release Candidate fehlt: {folder}"]
    setup, checksum = _files(version)
    present = {path.name for path in folder.iterdir()}
    problems = []
    if present - {setup, checksum, MANIFEST}:
        problems.append("Unerwartete Dateien: " + ", ".join(sorted(present - {setup, checksum, MANIFEST})))
    if MANIFEST not in present:
        return problems + [f"Manifest fehlt: {MANIFEST}"]
    problems += release_check.check(folder, version, notes_dir, min_size)
    try:
        manifest = json.loads((folder / MANIFEST).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return problems + [f"Manifest unlesbar: {exc}"]
    if not isinstance(manifest, dict):
        return problems + ["Manifest unlesbar: kein Objekt"]
    if manifest.get("format") != FORMAT:
        problems.append(f"Unbekanntes Manifest-Format: {manifest.get('format')!r}")
    if manifest.get("commit") != commit:
        problems.append(f"Release Candidate gehört zu Commit {manifest.get('commit')}, nicht zum Release-Commit {commit}")
    if manifest.get("run_id") != run_id:
        problems.append(f"Release Candidate stammt aus Lauf {manifest.get('run_id')}, nicht aus dem geprüften main-Lauf {run_id}")
    if manifest.get("version") != version:
        problems.append(f"Release Candidate hat Version {manifest.get('version')}, VERSION des Commits ist {version}")
    if manifest.get("setup") != setup:
        problems.append(f"Manifest nennt {manifest.get('setup')!r} statt {setup!r}")
    if (folder / setup).is_file() and manifest.get("sha256") != release_check.sha256(folder / setup):
        problems.append("SHA-256 des Setups weicht vom Manifest ab")
    return problems


def outputs(version: str, digest: str, notes_dir: Path) -> dict[str, str]:
    values = release_check.outputs(version)
    values["notes"] = str(Path(notes_dir) / f"{version}.md")
    values["sha256"] = digest
    return values


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Release Candidate schreiben, finden und prüfen")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("write", "verify"):
        sub = commands.add_parser(name)
        sub.add_argument("folder", type=Path, help="Ordner mit Setup und .sha256 (und Manifest)")
        sub.add_argument("--commit", required=True)
        sub.add_argument("--run", type=int, required=True)
        sub.add_argument("--root", type=Path, default=HERE.parent, help="Checkout des Commits (VERSION, Release Notes)")
        if name == "write":
            sub.add_argument("--attempt", type=int, default=1)
        else:
            sub.add_argument("--github-output", type=Path, default=None)
    runs = commands.add_parser("runs")
    runs.add_argument("response", type=Path, help="Antwort von GET …/actions/workflows/windows-setup.yml/runs")
    runs.add_argument("--commit", required=True)
    artifact = commands.add_parser("artifact")
    artifact.add_argument("response", type=Path, help="Antwort von GET …/actions/runs/<Lauf>/artifacts")
    artifact.add_argument("--commit", required=True)
    artifact.add_argument("--run", type=int, required=True)
    args = parser.parse_args(argv)

    if args.command == "runs":
        found = candidate_runs(json.loads(args.response.read_text(encoding="utf-8")), args.commit)
        for run_id in found:
            print(run_id)
        return 0 if found else 1
    if args.command == "artifact":
        found = candidate_artifact(json.loads(args.response.read_text(encoding="utf-8")), args.commit, args.run)
        if found is None:
            return 1
        print(found)
        return 0

    app_dir = Path(args.root) / "windows-app"
    version = (app_dir / "VERSION").read_text(encoding="utf-8").strip()
    notes_dir = app_dir / "release-notes"
    if args.command == "write":
        problems = write(args.folder, args.commit, args.run, args.attempt, version, notes_dir, MIN_SIZE)
    else:
        problems = verify(args.folder, args.commit, args.run, version, notes_dir, MIN_SIZE)
    if problems:
        for problem in problems:
            print(f"FEHLER: {problem}", file=sys.stderr)
        return 1
    setup = _files(version)[0]
    digest = release_check.sha256(Path(args.folder) / setup)
    if args.command == "verify" and args.github_output:
        with open(args.github_output, "a", encoding="utf-8") as handle:
            for key, value in outputs(version, digest, notes_dir).items():
                handle.write(f"{key}={value}\n")
    print(f"OK: {setup} · Commit {args.commit} · Lauf {args.run} · SHA-256 {digest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
