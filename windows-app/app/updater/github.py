"""Releases des offiziellen Repositories einlesen und das passende Update bestimmen.

Quelle ist die GitHub-API über die feste Repository-ID (bleibt bei einer Umbenennung gleich;
ein anderes Repository mit demselben Namen wird nie gelesen). Pro Prüfung genau eine Anfrage.

Ein Release kommt als Update nur in Frage, wenn

* es veröffentlicht ist – Entwürfe (``draft``) nie, auch nicht im Beta-Kanal,
* es zum Kanal passt: Stable nur Releases ohne Vorabkennung, die auf GitHub nicht als
  Vorabversion markiert sind; Beta zusätzlich Beta-Vorabversionen (``vX.Y.Z-beta.N``),
* es vollständig ist: Setup ``PDF-Tool-Setup-<Version>.exe`` und Prüfsummendatei
  ``PDF-Tool-Setup-<Version>.exe.sha256`` – genau diese Namen, hochgeladen, Download-Adresse
  des Releases selbst,
* seine Version nach SemVer neuer ist als die installierte (nie ein Downgrade).

Unter mehreren passenden Releases gewinnt die höchste Version. Unvollständige Releases werden
übergangen (z. B. während des Hochladens) und beim nächsten Prüfen erneut betrachtet.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Iterable
from urllib.parse import quote, unquote

from .models import Asset, Channel, Release
from .semver import Version

REPOSITORY = "Jerico3241/PDF-Tool"
REPOSITORY_ID = 1382108244  # feste ID des offiziellen Repositories (api.github.com/repos/Jerico3241/PDF-Tool)
RELEASES_URL = f"https://api.github.com/repositories/{REPOSITORY_ID}/releases?per_page=30"
SITE = "https://github.com"  # Release-Seiten und Downloads (Tests: lokaler Testserver)
API_HEADERS = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
SETUP_PREFIX = "PDF-Tool-Setup-"
MAX_INSTALLER_SIZE = 512 * 1024 * 1024
MAX_CHECKSUM_SIZE = 4096
MAX_FEED_SIZE = 8 * 1024 * 1024
MAX_NOTES = 60_000

_PAGE = r"/(?P<owner>[A-Za-z0-9](?:[A-Za-z0-9-]{0,38}))/(?P<repo>[A-Za-z0-9._-]{1,100})/releases/tag/(?P<tag>[^/?#]+)$"
_DIGEST = re.compile(r"^sha256:([0-9a-fA-F]{64})$")


class FeedError(ValueError):
    """Die Antwort ist keine gültige Release-Liste."""


def installer_name(version: Version) -> str:
    return f"{SETUP_PREFIX}{version}.exe"


def checksum_name(version: Version) -> str:
    return installer_name(version) + ".sha256"


def _published(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def _download_base(page: str, tag: str, site: str) -> str | None:
    """Download-Adresse der Assets eines Releases – aus seiner Seite abgeleitet."""
    match = re.match("^" + re.escape(site) + _PAGE, page)
    if match is None or unquote(match.group("tag")) != tag:
        return None
    return f"{site}/{match.group('owner')}/{match.group('repo')}/releases/download/{quote(tag, safe='')}/"


def _asset(raw: object, base: str | None, limit: int) -> tuple[Asset | None, str]:
    if not isinstance(raw, dict):
        return None, "ungültiger Eintrag"
    name = raw.get("name")
    size = raw.get("size")
    url = raw.get("browser_download_url")
    if not isinstance(name, str) or not isinstance(size, int) or isinstance(size, bool) or not isinstance(url, str):
        return None, "unvollständige Angaben"
    if raw.get("state", "uploaded") != "uploaded":
        return None, f"{name}: noch nicht vollständig hochgeladen"
    if not 0 < size <= limit:
        return None, f"{name}: ungültige Größe ({size} Bytes)"
    if base is None or url != base + quote(name, safe=""):
        return None, f"{name}: Download-Adresse gehört nicht zu diesem Release"
    digest = raw.get("digest")
    match = _DIGEST.match(digest) if isinstance(digest, str) else None
    return Asset(name=name, size=size, url=url, digest=match.group(1).lower() if match else ""), ""


def parse_release(raw: object, site: str = SITE) -> Release | None:
    """Ein Eintrag der API → ``Release``; ``None``, wenn er keine gültige Version trägt."""
    if not isinstance(raw, dict):
        return None
    tag = raw.get("tag_name")
    if not isinstance(tag, str):
        return None
    version = Version.from_tag(tag)
    if version is None:
        return None
    # Fehlt eine Angabe oder ist sie ungültig, gilt die vorsichtige Annahme (Entwurf/Vorabversion).
    draft = raw.get("draft") is not False
    prerelease = raw.get("prerelease") is not False
    page = raw.get("html_url") if isinstance(raw.get("html_url"), str) else ""
    base = _download_base(page, tag, site)
    problems: list[str] = []
    if base is None:
        problems.append("Release-Seite fehlt oder passt nicht")
    wanted = {installer_name(version): MAX_INSTALLER_SIZE, checksum_name(version): MAX_CHECKSUM_SIZE}
    found: dict[str, Asset] = {}
    assets = raw.get("assets")
    for item in assets if isinstance(assets, list) else []:
        name = item.get("name") if isinstance(item, dict) else None
        if name not in wanted:
            continue  # andere Dateien des Releases (z. B. Quellcode) spielen keine Rolle
        asset, problem = _asset(item, base, wanted[name])
        if asset is not None:
            found[name] = asset
        elif problem:
            problems.append(problem)
    installer = found.get(installer_name(version))
    checksum = found.get(checksum_name(version))
    if installer is None:
        problems.append(f"{installer_name(version)} fehlt")
    if checksum is None:
        problems.append(f"{checksum_name(version)} fehlt")
    title = raw.get("name") if isinstance(raw.get("name"), str) and raw.get("name").strip() else f"PDF Tool {version}"
    notes = raw.get("body") if isinstance(raw.get("body"), str) else ""
    return Release(
        version=version,
        tag=tag,
        title=title.strip(),
        notes=notes[:MAX_NOTES],
        published=_published(raw.get("published_at")),
        page=page if base is not None else "",
        prerelease=prerelease,
        draft=draft,
        installer=installer,
        checksum=checksum,
        problems=tuple(dict.fromkeys(problems)),
    )


def parse_releases(payload: bytes | str | list, site: str = SITE) -> list[Release]:
    """Antwort der API (JSON-Liste) → Releases. Ungültiges JSON oder keine Liste → ``FeedError``;
    einzelne unbrauchbare Einträge werden übergangen."""
    data = payload
    if isinstance(payload, (bytes, bytearray)):
        if len(payload) > MAX_FEED_SIZE:
            raise FeedError("Antwort zu groß")
        try:
            data = json.loads(bytes(payload).decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise FeedError(f"Ungültige Antwort: {exc}") from exc
    elif isinstance(payload, str):
        try:
            data = json.loads(payload)
        except ValueError as exc:
            raise FeedError(f"Ungültige Antwort: {exc}") from exc
    if not isinstance(data, list):
        raise FeedError("Antwort ist keine Release-Liste")
    return [release for release in (parse_release(entry, site) for entry in data) if release is not None]


def eligible(release: Release, channel: Channel) -> bool:
    """Passt das Release zum Kanal? (Vollständigkeit und Version prüft ``choose``.)"""
    if release.draft:
        return False
    if not release.is_beta:
        return True  # stabile Releases sehen beide Kanäle
    return channel is Channel.BETA and release.version.stage == "beta"


def choose(releases: Iterable[Release], installed: Version, channel: Channel) -> Release | None:
    """Das Update für diese Installation: höchste passende, vollständige Version über ``installed``."""
    candidates = [release for release in releases if eligible(release, channel) and release.complete and release.version > installed]
    return max(candidates, key=lambda release: release.version, default=None)


def skipped(releases: Iterable[Release], installed: Version, channel: Channel) -> list[Release]:
    """Neuere, passende Releases, die (noch) unvollständig sind – für das Protokoll."""
    return [release for release in releases if eligible(release, channel) and not release.complete and release.version > installed]


def latest_stable(releases: Iterable[Release]) -> Version | None:
    """Höchste vollständige stabile Version (für den Hinweis beim Wechsel Beta → Stable)."""
    versions = [release.version for release in releases if eligible(release, Channel.STABLE) and release.complete]
    return max(versions, default=None)


# --- Zwischenspeicher (letzte erfolgreiche Prüfung) ---------------------------------------------------


def to_cache(releases: Iterable[Release]) -> list[dict]:
    """Releases in der Form der API speichern (nur die genutzten Felder) – ``parse_releases`` liest sie wieder."""
    entries = []
    for release in releases:
        assets = []
        for asset in (release.installer, release.checksum):
            if asset is not None:
                entry = {"name": asset.name, "size": asset.size, "state": "uploaded", "browser_download_url": asset.url}
                if asset.digest:
                    entry["digest"] = f"sha256:{asset.digest}"
                assets.append(entry)
        entries.append(
            {
                "tag_name": release.tag,
                "name": release.title,
                "body": release.notes,
                "draft": release.draft,
                "prerelease": release.prerelease,
                "published_at": release.published.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if release.published else None,
                "html_url": release.page,
                "assets": assets,
            }
        )
    return entries
