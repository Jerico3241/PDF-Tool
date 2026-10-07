"""Veröffentlichte Versionen für die Update-Tests der CI bestimmen und Releases prüfen – nach SemVer,
nie alphabetisch.

Der normale Workflow »Windows-Setup« prüft genau ein echtes Installer-Update: von der unmittelbar
vorherigen veröffentlichten Version auf die neue (``windows-app/VERSION``). Welche Vorversion das
ist, hängt vom Ziel ab:

* Ziel stabil: die höchste stabile Version darunter (für 2.7.0: 2.6.1 → 2.7.0).
* Ziel Beta: die höchste veröffentlichte Version darunter – stabil oder Beta-Vorabversion (für
  3.1.0-beta.1: 3.0.0-beta.2 → 3.1.0-beta.1).

Der manuelle Workflow »Update-Test« wählt seine Vorversion ebenso, wenn ``von`` leer ist – abhängig
von Ziel und Kanal: Im Kanal Beta zählt auch eine Beta-Vorabversion (2.8.0-beta.3 → 2.8.0), im Kanal
Stable nur stabile Versionen (2.7.2 → 2.8.0). Der manuelle Workflow »Deep Compatibility Test« kann
dagegen alle älteren stabilen Versionen prüfen (ab 2.2.0 – ältere Setups kennt
``tests/smoke_installer.ps1`` nicht).

Beta vor Stable (Workflows »Release« und »Release-Prüfung«): Eine stabile Version X.Y.Z braucht eine
veröffentlichte Beta X.Y.Z-beta.N, auf die ein Lauf von »Update-Test« auf main im Kanal Beta
erfolgreich aktualisiert hat – erkannt am Laufnamen ``Update-Test <von> → X.Y.Z-beta.N (beta)``.

Aufruf (in der CI, mit der GitHub-CLI ``gh``)::

    python windows-app/releases.py previous                              # Ziel: windows-app/VERSION
    python windows-app/releases.py previous --ziel 3.1.0-beta.1          # z. B. »3.0.0-beta.2«
    python windows-app/releases.py previous --ziel 2.8.0 --kanal beta    # z. B. »2.8.0-beta.3«
    python windows-app/releases.py all --json                            # z. B. ["2.2.0", "2.3.0", …]
    python windows-app/releases.py all --only 2.4.0,2.5.0 --json
    python windows-app/releases.py tested-beta --ziel 3.1.0 --runs update-tests.json
    python windows-app/releases.py check-release --release release.json --runs update-tests.json

``--runs`` ist die Antwort von ``GET …/actions/workflows/update-test.yml/runs``, ``--release`` die
von ``GET …/releases/<id>``; die Liste der Releases liest ``gh release list`` (oder ``--releases``).

Stabil heißt: Tag ``vMAJOR.MINOR.PATCH`` ohne Vorabkennung, weder Entwurf noch Vorabversion. Beta
heißt: Tag ``vMAJOR.MINOR.PATCH-beta.N``, als Vorabversion veröffentlicht. Entwürfe zählen nie. Die
aktuelle Version steht in ``windows-app/VERSION`` – auch eine Beta (``3.1.0-beta.1``).
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Iterable

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import release_check  # noqa: E402 - Versionsformat wie im Build: X.Y.Z oder X.Y.Z-beta.N
from updater.semver import Version as SemVer  # noqa: E402 - dieselbe SemVer-Rangfolge wie der Updater

OLDEST_SUPPORTED = (2, 2, 0)  # älteste Vorversion, die smoke_installer.ps1 installieren und prüfen kann
_TAG = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")
_BETA = re.compile(r"^\d+\.\d+\.\d+-beta\.[1-9]\d*$")
# Laufname von »Update-Test« (run-name in update-test.yml), z. B. »Update-Test 3.0.0-beta.2 → 3.1.0-beta.1 (beta)«;
# ohne Angabe von »von« steht dort »automatisch«
_UPDATE_TEST = re.compile(r"^Update-Test (?P<von>\S+) → (?P<ziel>\S+) \((?P<kanal>beta|stable)\)$")
# Konto von GITHUB_TOKEN: Releases mit diesem Autor erstellt nur der Workflow »Release« (release.yml)
WORKFLOW_BOT = "github-actions[bot]"

Version = tuple[int, int, int]


def parse(value: str) -> Version | None:
    """``"v2.6.1"`` → ``(2, 6, 1)``; Vorabversionen (``2.7.0-rc1``) und Fremdes → ``None``."""
    match = _TAG.match(str(value).strip())
    return tuple(int(part) for part in match.groups()) if match else None  # type: ignore[return-value]


def text(version: Version) -> str:
    return ".".join(str(part) for part in version)


def stable_versions(releases: Iterable[dict]) -> list[Version]:
    """Stabile, veröffentlichte Versionen aus ``gh release list --json tagName,isDraft,isPrerelease``."""
    found = set()
    for release in releases:
        if release.get("isDraft") or release.get("isPrerelease"):
            continue
        version = parse(release.get("tagName", ""))
        if version is not None:
            found.add(version)
    return sorted(found)


def previous_stable(current: Version, versions: Iterable[Version]) -> Version | None:
    """Unmittelbar vorherige stabile Version (größte Version kleiner als ``current``)."""
    older = [version for version in versions if version < current]
    return max(older) if older else None


def older_stable(current: Version, versions: Iterable[Version], oldest: Version = OLDEST_SUPPORTED) -> list[Version]:
    """Alle stabilen Versionen vor ``current`` ab ``oldest`` – aufsteigend (für den manuellen Volltest)."""
    return sorted(version for version in set(versions) if oldest <= version < current)


def current_version() -> Version:
    """Zahlenteil der Version aus ``windows-app/VERSION`` (bei einer Beta ``2.8.0-beta.1`` → ``(2, 8, 0)``)."""
    text = (HERE / "VERSION").read_text(encoding="utf-8").strip()
    version = parse(text.split("-", 1)[0]) if "-" in text and _BETA.match(text) else parse(text)
    if version is None:
        raise SystemExit("windows-app/VERSION enthält keine Version MAJOR.MINOR.PATCH bzw. MAJOR.MINOR.PATCH-beta.N")
    return version


# --- Vorversion nach Ziel und Kanal (Stable und Beta) -------------------------------------------------------------


def release_version(tag: str) -> SemVer | None:
    """Tag ``v3.1.0`` oder ``v3.1.0-beta.2`` (auch ohne ``v``) → Version; andere Vorabkennungen und Fremdes → ``None``."""
    value = str(tag or "").strip()
    return release_check.parse(value[1:] if value.startswith("v") else value)


def target_version(value: str | None = None) -> SemVer:
    """Zielversion ``X.Y.Z`` oder ``X.Y.Z-beta.N`` – angegeben oder vollständig aus ``windows-app/VERSION``."""
    text = (value if value is not None else (HERE / "VERSION").read_text(encoding="utf-8")).strip()
    version = release_check.parse(text)
    if version is None:
        raise SystemExit(f"Keine gültige Zielversion: {text!r} (erlaubt: X.Y.Z oder X.Y.Z-beta.N)")
    return version


def published_versions(releases: Iterable[dict]) -> list[SemVer]:
    """Stabile Versionen und Beta-Vorabversionen aus ``gh release list --json tagName,isDraft,isPrerelease`` –
    aufsteigend nach SemVer (``3.0.0-beta.2 < 3.0.0-beta.10 < 3.0.0``). Entwürfe zählen nie, ebenso andere
    Vorabkennungen (``-rc1``) und Releases, deren Markierung nicht zum Tag passt (eine Beta, die auf GitHub
    keine Vorabversion ist, oder eine stabile Version als Vorabversion)."""
    found = set()
    for release in releases:
        version = release_version(release.get("tagName", ""))
        if release.get("isDraft") or version is None or bool(release.get("isPrerelease")) != version.is_prerelease:
            continue
        found.add(version)
    return sorted(found)


def previous_version(target: SemVer, versions: Iterable[SemVer], channel: str | None = None) -> SemVer | None:
    """Unmittelbar vorherige veröffentlichte Version für den Update-Test auf ``target``.

    Kanal ``beta`` (ohne Angabe: bei einer Beta als Ziel) – die höchste Version darunter, stabil oder Beta:
    3.1.0-beta.1 → 3.0.0-beta.2, im Kanal Beta 2.8.0 → 2.8.0-beta.3. Kanal ``stable`` (ohne Angabe: bei
    einer stabilen Version als Ziel) – wie bisher nur stabile Versionen: 2.8.0 → 2.7.2."""
    beta = target.is_prerelease if channel is None else channel == "beta"
    older = [version for version in versions if version < target and (beta or not version.is_prerelease)]
    return max(older, default=None)


# --- Beta vor Stable: veröffentlichte und per »Update-Test« geprüfte Beta ---------------------------------------


def update_tests(response: dict) -> list[tuple[SemVer, str, dict]]:
    """Ziel, Kanal und Lauf der erfolgreichen main-Läufe von »Update-Test« (manuell gestartet, abgeschlossen)
    aus der Antwort von ``GET …/actions/workflows/update-test.yml/runs`` – neuester zuerst. Läufe ohne
    passenden Laufnamen zählen nie (auch nicht die Läufe vor dessen Einführung)."""
    found = []
    for run in response.get("workflow_runs", []) if isinstance(response, dict) else []:
        match = _UPDATE_TEST.match(str(run.get("display_title") or ""))
        target = release_check.parse(match.group("ziel")) if match else None
        if (
            target is not None
            and run.get("head_branch") == "main"
            and run.get("event") == "workflow_dispatch"
            and run.get("status") == "completed"
            and run.get("conclusion") == "success"
        ):
            found.append((target, match.group("kanal"), run))
    found.sort(key=lambda item: (item[2].get("run_number", 0), item[2].get("run_attempt", 0)), reverse=True)
    return found


def tested_beta(stable: SemVer, releases: Iterable[dict], response: dict) -> tuple[SemVer, dict] | None:
    """Die höchste veröffentlichte Beta ``X.Y.Z-beta.N`` der stabilen Version ``stable``, auf die ein Lauf
    von »Update-Test« im Kanal Beta erfolgreich aktualisiert hat – mit dem neuesten solchen Lauf. ``None``,
    wenn es keine gibt (keine Beta, nur Entwürfe, nie getestet oder Test fehlgeschlagen)."""
    if stable.is_prerelease:
        return None
    betas = {version for version in published_versions(releases) if version.is_prerelease and version.core == stable.core}
    tested = [(target, run) for target, channel, run in update_tests(response) if channel == "beta" and target in betas]
    return max(tested, key=lambda item: item[0], default=None)


# --- Releases von Hand (Workflow »Release-Prüfung«) -------------------------------------------------------------


def _login(user: object) -> str:
    return str(user.get("login") or "") if isinstance(user, dict) else ""


def created_by_release_workflow(release: dict) -> bool:
    """Release und alle seine Dateien stammen von ``github-actions[bot]`` – erstellt vom Workflow »Release«, der
    Beta vor Stable samt Hotfix-Regel beim Erstellen geprüft hat. Eine von Hand ersetzte Datei hebt das auf."""
    assets = release.get("assets") or []
    return _login(release.get("author")) == WORKFLOW_BOT and all(isinstance(asset, dict) and _login(asset.get("uploader")) == WORKFLOW_BOT for asset in assets)


def release_problems(release: dict, releases: Iterable[dict], response: dict) -> list[str]:
    """Verstöße eines veröffentlichten Releases (Antwort von ``GET …/releases/<id>``) gegen die Release-Regeln
    (leer = in Ordnung) – für Releases, die von Hand auf GitHub erstellt oder geändert werden:

    * Tag ``vX.Y.Z`` oder ``vX.Y.Z-beta.N``
    * Beta-Tag ⇒ GitHub-Vorabversion
    * stabiler Tag ⇒ veröffentlichte Beta derselben Version mit erfolgreichem »Update-Test« (``tested_beta``),
      ohne Hotfix-Ausnahme – außer das Release stammt vom Workflow »Release«, der das beim Erstellen prüft
    * genau die Dateien ``PDF-Tool-Setup-<Version>.exe`` und ``PDF-Tool-Setup-<Version>.exe.sha256``
    """
    tag = str(release.get("tag_name") or "")
    version = release_check.parse(tag[1:]) if tag.startswith("v") else None
    if version is None:
        return [f"Tag {tag!r} hat nicht das Format vX.Y.Z oder vX.Y.Z-beta.N"]
    problems = []
    if version.is_prerelease and release.get("prerelease") is not True:
        problems.append(f"Beta {tag} ist nicht als Vorabversion (Prerelease) veröffentlicht")
    if not version.is_prerelease and not created_by_release_workflow(release) and tested_beta(version, releases, response) is None:
        problems.append(
            f"Stabile Version {tag} ohne veröffentlichte und per »Update-Test« geprüfte Beta {tag}-beta.N "
            "(erfolgreicher Lauf von update-test.yml auf main mit dieser Beta als Ziel, Kanal beta) – "
            "Beta vor Stable gilt auch für Releases von Hand, ohne Hotfix-Ausnahme"
        )
    files = release_check.outputs(str(version))
    expected = sorted((files["setup"], files["checksum"]))
    names = sorted(str(asset.get("name") or "") for asset in release.get("assets") or [] if isinstance(asset, dict))
    if names != expected:
        problems.append(f"Dateien des Releases: {', '.join(names) or 'keine'} – erwartet genau {' und '.join(expected)}")
    return problems


def published_releases(repo: str | None) -> list[dict]:
    command = ["gh", "release", "list", "--limit", "200", "--json", "tagName,isDraft,isPrerelease"]
    if repo:
        command += ["--repo", repo]
    result = subprocess.run(command, check=True, capture_output=True, text=True, encoding="utf-8")
    return json.loads(result.stdout or "[]")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Versionen für die Update-Tests bestimmen und Releases prüfen (SemVer)")
    parser.add_argument(
        "mode",
        choices=("previous", "all", "tested-beta", "check-release"),
        help="previous: unmittelbar vorherige veröffentlichte Version (nach Ziel und Kanal); all: alle älteren stabilen Versionen; "
        "tested-beta: veröffentlichte, per »Update-Test« geprüfte Beta einer stabilen Version; check-release: Release-Regeln eines Releases",
    )
    parser.add_argument("--repo", default=None, help="owner/name (Standard: Repository des Arbeitsordners)")
    parser.add_argument("--releases", type=Path, default=None, help="Liste der Releases als JSON-Datei statt »gh release list« (Tests)")
    parser.add_argument("--only", default="", help="nur diese Versionen (kommagetrennt, müssen veröffentlicht sein)")
    parser.add_argument("--json", action="store_true", help="Ausgabe als JSON")
    parser.add_argument("--ziel", default=None, help="previous, tested-beta: Zielversion X.Y.Z oder X.Y.Z-beta.N (Standard: windows-app/VERSION)")
    parser.add_argument("--kanal", choices=("beta", "stable"), default=None, help="previous: Update-Kanal – beta zählt auch Beta-Vorabversionen (Standard: beta bei einer Beta als Ziel)")
    parser.add_argument("--runs", type=Path, default=None, help="tested-beta, check-release: Antwort von GET …/actions/workflows/update-test.yml/runs")
    parser.add_argument("--release", type=Path, default=None, help="check-release: Antwort von GET …/releases/<id>")
    args = parser.parse_args(argv)
    if args.mode in ("tested-beta", "check-release") and args.runs is None:
        parser.error("--runs fehlt (Antwort von GET …/actions/workflows/update-test.yml/runs)")
    if args.mode == "check-release" and args.release is None:
        parser.error("--release fehlt (Antwort von GET …/releases/<id>)")
    release = json.loads(args.release.read_text(encoding="utf-8")) if args.mode == "check-release" else {}
    if release.get("draft") is True:
        print(f"OK: {release.get('tag_name')} ist ein Entwurf – Entwürfe bietet der Updater nie an")
        return 0
    releases = json.loads(args.releases.read_text(encoding="utf-8")) if args.releases else published_releases(args.repo)

    if args.mode == "previous":
        target = target_version(args.ziel)
        previous = previous_version(target, published_versions(releases), args.kanal)
        if previous is None:
            print(f"Keine veröffentlichte Version vor {target} (Kanal {args.kanal or ('beta' if target.is_prerelease else 'stable')})", file=sys.stderr)
            return 1
        print(json.dumps(str(previous)) if args.json else str(previous))
        return 0

    if args.mode == "tested-beta":
        stable = target_version(args.ziel)
        if stable.is_prerelease:
            print(f"tested-beta gilt nur für eine stabile Version, nicht für {stable}", file=sys.stderr)
            return 1
        found = tested_beta(stable, releases, json.loads(args.runs.read_text(encoding="utf-8")))
        if found is None:
            print(f"Keine veröffentlichte Beta {stable}-beta.N mit erfolgreichem Lauf von »Update-Test« (main, Kanal beta, Laufname »Update-Test … → {stable}-beta.N (beta)«)", file=sys.stderr)
            return 1
        beta, run = found
        print(f"Getestete Beta: {beta} · Lauf »{run.get('display_title')}« {run.get('html_url') or run.get('id')}")
        return 0

    if args.mode == "check-release":
        response = json.loads(args.runs.read_text(encoding="utf-8"))
        problems = release_problems(release, releases, response)
        if problems:
            for problem in problems:
                print(f"FEHLER: {problem}", file=sys.stderr)
            return 1
        version = release_version(release["tag_name"])
        if version.is_prerelease:
            kind = "Beta (Vorabversion)"
        elif created_by_release_workflow(release):
            kind = "Stable, erstellt vom Workflow »Release« (Beta vor Stable dort geprüft)"
        else:
            beta, run = tested_beta(version, releases, response)
            kind = f"Stable nach getesteter Beta {beta} (Lauf {run.get('html_url') or run.get('id')})"
        print(f"OK: {release['tag_name']} · {kind} · {', '.join(sorted(asset['name'] for asset in release['assets']))}")
        return 0

    versions = stable_versions(releases)
    current = current_version()
    chosen = older_stable(current, versions)
    if args.only.strip():
        wanted = [parse(item) for item in args.only.split(",") if item.strip()]
        unknown = [item for item, version in zip(args.only.split(","), wanted) if version is None or version not in chosen]
        if unknown:
            print(f"Nicht als stabile Vorversion veröffentlicht: {', '.join(item.strip() for item in unknown)}", file=sys.stderr)
            return 1
        chosen = sorted(set(wanted))  # type: ignore[arg-type]
    names = [text(version) for version in chosen]
    print(json.dumps(names) if args.json else "\n".join(names))
    return 0


if __name__ == "__main__":
    sys.exit(main())
