"""Updater ohne Netzwerk und ohne Qt: SemVer, Kanäle, Releases, Assets, Prüfsummen, Zustände,
24-Stunden-Regel, erlaubte Adressen, Release Notes und der Download-Ordner.

Die Abläufe mit Netzwerk (lokaler Testserver), Download, Abbruch und Installer-Start prüft
``test_updater_flow.py``; die Oberfläche ``test_qt_updates.py``.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote

import pytest

from updater import github, notes, schedule
from updater.models import Channel, Release, UpdateState
from updater.policy import UrlPolicy
from updater.semver import Version
from updater.state import StateError, StateMachine
from updater.store import UpdateStore
from updater.verifier import ChecksumError, file_sha256, matches, parse_checksum, same_digest

PAGE = "https://github.com/Jerico3241/PDF-Tool/releases/tag/"
DOWNLOAD = "https://github.com/Jerico3241/PDF-Tool/releases/download/"
DIGEST = "3cd865b7b1a82d7045aae23b558c9af319368ace8447b7fcab4f27072f9d3bd9"


def eintrag(tag: str, *, prerelease: bool | None = None, draft: bool = False, assets: list[dict] | None = None, body: str = "Neu.", page: str | None = None) -> dict:
    """Ein Release, wie die GitHub-API es liefert (nur die genutzten Felder)."""
    version = tag[1:] if tag.startswith("v") else tag
    if prerelease is None:
        prerelease = "-" in version
    if assets is None:
        assets = [asset(f"PDF-Tool-Setup-{version}.exe", tag, size=57_311_371, digest=DIGEST), asset(f"PDF-Tool-Setup-{version}.exe.sha256", tag, size=92)]
    return {
        "tag_name": tag,
        "name": f"PDF Tool {version}",
        "body": body,
        "draft": draft,
        "prerelease": prerelease,
        "published_at": "2026-10-01T08:43:37Z",
        "html_url": page if page is not None else PAGE + tag,
        "assets": assets,
    }


def asset(name: str, tag: str, *, size: int = 1000, state: str = "uploaded", url: str | None = None, digest: str | None = None) -> dict:
    # wie GitHub: Tag und Dateiname in der Adresse kodiert (»+« → »%2B«)
    entry = {"name": name, "size": size, "state": state, "browser_download_url": url if url is not None else DOWNLOAD + quote(tag, safe="") + "/" + quote(name, safe="")}
    if digest:
        entry["digest"] = f"sha256:{digest}"
    return entry


def releases(*entries: dict) -> list[Release]:
    return github.parse_releases(json.dumps(list(entries)).encode())


def update(installed: str, channel: Channel, *entries: dict) -> str | None:
    found = github.choose(releases(*entries), Version.parse(installed), channel)
    return str(found.version) if found else None


# --- SemVer ------------------------------------------------------------------------------------------


@pytest.mark.parametrize("text", ["2.7.2", "0.0.0", "2.7.3-beta.1", "2.10.0", "1.0.0-alpha.1+build.5", "10.20.30-rc.1"])
def test_semver_parses_valid_versions(text):
    assert str(Version.parse(text)) == text


@pytest.mark.parametrize("text", ["", "2.7", "2.7.3.1", "v2.7.3", "02.7.3", "2.07.3", "2.7.3-", "2.7.3-beta..1", "2.7.3-beta.01", "latest", "2.7.3 beta", "２.7.3"])
def test_semver_rejects_invalid_versions(text):
    with pytest.raises(ValueError):
        Version.parse(text)


def test_semver_compares_numbers_not_text():
    assert Version.parse("2.10.0") > Version.parse("2.9.0")
    assert "2.10.0" < "2.9.0"  # der Fehler, den der Updater nicht machen darf
    assert Version.parse("10.0.0") > Version.parse("9.99.99")


def test_semver_prerelease_order():
    order = ["2.7.3-alpha", "2.7.3-alpha.1", "2.7.3-beta.1", "2.7.3-beta.2", "2.7.3-beta.3", "2.7.3-beta.10", "2.7.3-rc.1", "2.7.3", "2.7.4-beta.1", "2.8.0"]
    versions = [Version.parse(text) for text in order]
    assert sorted(reversed(versions)) == versions
    assert Version.parse("2.7.3-beta.2") < Version.parse("2.7.3-beta.10")  # Zahlen als Zahlen
    assert Version.parse("2.7.3-beta.9") < Version.parse("2.7.3-beta.x")  # Zahlen vor Text


def test_semver_ignores_build_metadata_for_order():
    assert Version.parse("2.7.3+a") == Version.parse("2.7.3+b") == Version.parse("2.7.3")
    assert len({Version.parse("2.7.3+a"), Version.parse("2.7.3")}) == 1


def test_semver_tags_and_labels():
    assert Version.from_tag("v2.7.3-beta.1") == Version.parse("2.7.3-beta.1")
    assert Version.from_tag("2.7.3") == Version.parse("2.7.3")
    assert Version.from_tag("vv2.7.3") is None and Version.from_tag("release-2.7.3") is None
    assert Version.parse("2.7.3-beta.1").label() == "2.7.3 Beta 1"
    assert Version.parse("2.7.3-rc.2").label() == "2.7.3 RC 2"
    assert Version.parse("2.7.3").label() == "2.7.3"
    assert Version.parse("2.8.0-beta.1").tag == "v2.8.0-beta.1"
    assert Version.coerce("kaputt") == Version.parse("0.0.0")


# --- Kanäle (Tests 82–88 der Vorgabe) ---------------------------------------------------------------


def test_82_stable_ignores_beta():
    assert update("2.7.2", Channel.STABLE, eintrag("v2.7.3-beta.1")) is None


def test_83_beta_finds_beta():
    assert update("2.7.2", Channel.BETA, eintrag("v2.7.3-beta.1")) == "2.7.3-beta.1"


def test_84_beta_finds_newer_beta():
    assert update("2.7.3-beta.1", Channel.BETA, eintrag("v2.7.3-beta.1"), eintrag("v2.7.3-beta.2")) == "2.7.3-beta.2"


def test_85_beta_finds_stable():
    assert update("2.7.3-beta.3", Channel.BETA, eintrag("v2.7.3-beta.3"), eintrag("v2.7.3")) == "2.7.3"


def test_86_no_downgrade():
    assert update("2.8.0", Channel.STABLE, eintrag("v2.7.9")) is None
    assert update("2.8.0", Channel.BETA, eintrag("v2.7.9"), eintrag("v2.8.0-beta.3")) is None


def test_87_beta_to_stable_never_downgrades():
    assert update("2.8.0-beta.3", Channel.STABLE, eintrag("v2.7.2"), eintrag("v2.8.0-beta.3")) is None
    # Sobald eine neuere stabile Version erscheint, wirkt der Wechsel
    assert update("2.8.0-beta.3", Channel.STABLE, eintrag("v2.7.2"), eintrag("v2.8.0")) == "2.8.0"


def test_88_drafts_are_never_offered():
    for channel in Channel:
        assert update("2.7.2", channel, eintrag("v2.7.3", draft=True)) is None
        assert update("2.7.2", channel, eintrag("v2.7.3-beta.1", draft=True)) is None


def test_major_beta_3_0_only_for_the_beta_channel():
    """3.0.0-beta.1 (neue Hauptversion): Beta-Kanal von 2.8.0 aus ja, Stable nie – auch nicht von einer
    älteren Stable oder Beta aus; erst die spätere stabile 3.0.0 erreicht Stable."""
    entries = (eintrag("v2.8.0-beta.1"), eintrag("v2.8.0"), eintrag("v3.0.0-beta.1"))
    assert update("2.8.0", Channel.BETA, *entries) == "3.0.0-beta.1"
    assert update("2.8.0", Channel.STABLE, *entries) is None
    assert update("2.7.2", Channel.STABLE, *entries) == "2.8.0"
    assert update("2.8.0-beta.1", Channel.STABLE, *entries) == "2.8.0"
    assert update("3.0.0-beta.1", Channel.STABLE, *entries) is None  # kein Rückschritt
    assert update("3.0.0-beta.1", Channel.STABLE, *entries, eintrag("v3.0.0")) == "3.0.0"


def test_stable_channel_example_from_the_spec():
    entries = (eintrag("v2.7.3-beta.1"), eintrag("v2.7.3-beta.2"), eintrag("v2.7.3"))
    assert update("2.7.2", Channel.STABLE, *entries) == "2.7.3"
    assert update("2.7.2", Channel.BETA, *entries) == "2.7.3"


def test_beta_user_after_stable_gets_next_beta():
    entries = (eintrag("v2.8.0-beta.3"), eintrag("v2.8.0"), eintrag("v2.8.1-beta.1"))
    assert update("2.8.0-beta.3", Channel.BETA, *entries) == "2.8.1-beta.1"
    assert update("2.8.0", Channel.BETA, *entries) == "2.8.1-beta.1"
    assert update("2.8.0", Channel.STABLE, *entries) is None


def test_prerelease_marks_are_respected_in_both_directions():
    # Auf GitHub als Vorabversion markiert, aber ohne Vorabkennung: in keinem Kanal
    assert update("2.7.2", Channel.STABLE, eintrag("v2.7.3", prerelease=True)) is None
    assert update("2.7.2", Channel.BETA, eintrag("v2.7.3", prerelease=True)) is None
    # Beta-Kennung, aber versehentlich nicht markiert: nie – auch nicht im Beta-Kanal
    for channel in Channel:
        assert update("2.7.2", channel, eintrag("v2.7.3-beta.1", prerelease=False)) is None
    # richtig markiert: Beta nur im Beta-Kanal
    assert update("2.7.2", Channel.BETA, eintrag("v2.7.3-beta.1", prerelease=True)) == "2.7.3-beta.1"
    assert update("2.7.2", Channel.STABLE, eintrag("v2.7.3-beta.1", prerelease=True)) is None


def test_only_beta_prereleases_reach_the_beta_channel():
    assert update("2.7.2", Channel.BETA, eintrag("v2.7.3-rc.1"), eintrag("v2.7.3-alpha.1")) is None


@pytest.mark.parametrize("tag", ["v2.7.3-rc.1", "v2.7.3-alpha.1", "v2.7.3-dev", "v2.7.3-dev.4", "v2.7.3+build.5", "v2.7.3-beta.1+build.5", "v2.7.3-beta", "v2.7.3-beta.0", "v2.7.3-beta.1.2", "v2.7.3-Beta.1", "v2.7.3-beta.x", "2.7.3", "2.7.3-beta.1"])
@pytest.mark.parametrize("prerelease", [True, False])
def test_other_tags_are_never_offered(tag, prerelease):
    """Nur ``vX.Y.Z`` und ``vX.Y.Z-beta.N`` – andere Kennungen (auch versehentlich nicht als
    Vorabversion markiert), Build-Angaben und Tags ohne »v« erreichen keinen Kanal."""
    entry = eintrag(tag, prerelease=prerelease)
    found = releases(entry)[0]
    assert found.complete and found.version > Version.parse("2.7.2")  # vollständig und neuer – nur der Tag passt nicht
    assert found.channel is None
    for channel in Channel:
        assert update("2.7.2", channel, entry) is None
        assert github.skipped([found], Version.parse("2.7.2"), channel) == []


def test_release_channel_comes_from_tag_and_mark():
    def kanal(tag: str, prerelease: bool) -> Channel | None:
        return releases(eintrag(tag, prerelease=prerelease))[0].channel

    assert kanal("v2.7.3", False) is Channel.STABLE and kanal("v10.0.0", False) is Channel.STABLE
    assert kanal("v2.7.3-beta.1", True) is Channel.BETA and kanal("v2.7.3-beta.12", True) is Channel.BETA
    assert kanal("v2.7.3", True) is None and kanal("v2.7.3-beta.1", False) is None


def test_beta_channel_keeps_stable_and_marked_betas_only():
    entries = (eintrag("v2.8.0-rc.1", prerelease=False), eintrag("v2.8.0-beta.2", prerelease=False), eintrag("v2.7.9"), eintrag("v2.8.0-beta.1"))
    assert update("2.7.2", Channel.BETA, *entries) == "2.8.0-beta.1"
    assert update("2.7.2", Channel.STABLE, *entries) == "2.7.9"
    assert update("2.8.0-beta.1", Channel.BETA, *entries) is None  # kein Downgrade auf 2.7.9
    assert update("2.7.2", Channel.BETA, eintrag("v2.8.0-beta.1", draft=True)) is None  # Entwürfe nie


def test_missing_flags_count_as_draft_and_prerelease():
    entry = eintrag("v2.7.3")
    del entry["draft"]
    assert update("2.7.2", Channel.STABLE, entry) is None
    entry = eintrag("v2.7.3")
    entry["prerelease"] = "nein"
    assert update("2.7.2", Channel.STABLE, entry) is None


def test_highest_version_wins_regardless_of_order():
    entries = (eintrag("v2.7.10"), eintrag("v2.7.9"), eintrag("v2.8.0-beta.1"), eintrag("v2.7.11-beta.2"))
    assert update("2.7.2", Channel.STABLE, *entries) == "2.7.10"
    assert update("2.7.2", Channel.BETA, *entries) == "2.8.0-beta.1"


def test_update_from_2_7_x_to_3_x_is_found():
    """Der Updater nimmt keine feste Hauptversion an (Updates des Updaters selbst)."""
    assert update("2.7.2", Channel.STABLE, eintrag("v3.0.0"), eintrag("v2.9.1")) == "3.0.0"


def test_latest_stable_for_the_channel_hint():
    found = releases(eintrag("v2.7.2"), eintrag("v2.8.0-beta.3"), eintrag("v2.7.1"))
    assert github.latest_stable(found) == Version.parse("2.7.2")


# --- Assets (Tests 89 und 90) ----------------------------------------------------------------------------


def test_89_release_without_matching_installer_is_ignored():
    falsch = eintrag("v2.7.3", assets=[asset("PDF-Tool-Setup-2.7.2.exe", "v2.7.3"), asset("PDF-Tool-Setup-2.7.2.exe.sha256", "v2.7.3")])
    assert update("2.7.2", Channel.STABLE, falsch) is None
    found = releases(falsch)[0]
    assert not found.complete and "PDF-Tool-Setup-2.7.3.exe fehlt" in found.problems
    assert github.skipped(releases(falsch), Version.parse("2.7.2"), Channel.STABLE) == [found]


def test_90_release_without_checksum_is_never_offered():
    ohne = eintrag("v2.7.3", assets=[asset("PDF-Tool-Setup-2.7.3.exe", "v2.7.3")])
    assert update("2.7.2", Channel.STABLE, ohne) is None
    assert "PDF-Tool-Setup-2.7.3.exe.sha256 fehlt" in releases(ohne)[0].problems


def test_beta_assets_need_the_full_version_name():
    tag = "v2.8.0-beta.1"
    richtig = eintrag(tag)
    assert releases(richtig)[0].installer.name == "PDF-Tool-Setup-2.8.0-beta.1.exe"
    ohne_kennung = eintrag(tag, assets=[asset("PDF-Tool-Setup-2.8.0.exe", tag), asset("PDF-Tool-Setup-2.8.0.exe.sha256", tag)])
    assert not releases(ohne_kennung)[0].complete


@pytest.mark.parametrize(
    "aenderung",
    [
        {"state": "new"},
        {"size": 0},
        {"size": github.MAX_INSTALLER_SIZE + 1},
        {"url": "https://github.com/someone/PDF-Tool/releases/download/v2.7.3/PDF-Tool-Setup-2.7.3.exe"},
        {"url": "https://evil.example/PDF-Tool-Setup-2.7.3.exe"},
        {"url": "http://github.com/Jerico3241/PDF-Tool/releases/download/v2.7.3/PDF-Tool-Setup-2.7.3.exe"},
        {"url": DOWNLOAD + "v2.7.2/PDF-Tool-Setup-2.7.3.exe"},
    ],
)
def test_installer_asset_must_belong_to_the_release(aenderung):
    tag = "v2.7.3"
    installer = asset("PDF-Tool-Setup-2.7.3.exe", tag, **aenderung)
    entry = eintrag(tag, assets=[installer, asset("PDF-Tool-Setup-2.7.3.exe.sha256", tag)])
    assert releases(entry)[0].installer is None
    assert update("2.7.2", Channel.STABLE, entry) is None


def test_release_page_of_another_repository_or_tag_is_rejected():
    assert releases(eintrag("v2.7.3", page="https://github.com/Jerico3241/PDF-Tool/releases/tag/v2.7.4"))[0].installer is None
    assert releases(eintrag("v2.7.3", page="https://evil.example/Jerico3241/PDF-Tool/releases/tag/v2.7.3"))[0].installer is None


def test_asset_digest_is_read_when_present():
    found = releases(eintrag("v2.7.3"))[0]
    assert found.installer.digest == DIGEST and found.checksum.digest == ""
    assert found.installer.size == 57_311_371


# --- Ungültige Antworten (Security) -----------------------------------------------------------------------


@pytest.mark.parametrize("payload", [b"", b"{", b"<html>Rate limit</html>", b'{"message": "Not Found"}', b"null", "ä".encode("latin-1"), b'"text"'])
def test_malformed_release_json_raises_feed_error(payload):
    with pytest.raises(github.FeedError):
        github.parse_releases(payload)


def test_malformed_entries_are_skipped():
    data = [None, 1, "x", {}, {"tag_name": 5}, {"tag_name": "nightly"}, eintrag("v2.7.3"), {"tag_name": "v2.7.4", "assets": "kaputt"}]
    found = github.parse_releases(json.dumps(data).encode())
    assert [str(release.version) for release in found] == ["2.7.3", "2.7.4"]
    assert not found[1].complete


def test_oversized_feed_is_rejected():
    with pytest.raises(github.FeedError):
        github.parse_releases(b" " * (github.MAX_FEED_SIZE + 1))


def test_cache_roundtrip_keeps_everything_needed():
    original = releases(eintrag("v2.7.3", body="## Neu\n- Punkt"), eintrag("v2.8.0-beta.1"))
    again = github.parse_releases(json.dumps(github.to_cache(original)).encode())
    assert [(r.version, r.complete, r.prerelease, r.notes, r.installer, r.checksum, r.published) for r in again] == [
        (r.version, r.complete, r.prerelease, r.notes, r.installer, r.checksum, r.published) for r in original
    ]


# --- Prüfsummen -----------------------------------------------------------------------------------------------

NAME = "PDF-Tool-Setup-2.7.3.exe"


@pytest.mark.parametrize(
    "inhalt",
    [
        f"{DIGEST}  {NAME}\n",
        f"{DIGEST}  {NAME}\r\n",
        f"\ufeff{DIGEST}  {NAME}\n".encode("utf-8"),
        f"{DIGEST.upper()}  {NAME}",
        f"{DIGEST} *{NAME}\n",
        f"{DIGEST} {NAME}\n",
        f"{DIGEST}\n",
        f"SHA256 ({NAME}) = {DIGEST}\n",
        f"# Prüfsumme\n\n{DIGEST}  andere-datei.zip\n{DIGEST}  {NAME}\n",
    ],
)
def test_checksum_formats(inhalt):
    data = inhalt.encode("utf-8") if isinstance(inhalt, str) else inhalt
    assert parse_checksum(data, NAME) == DIGEST


@pytest.mark.parametrize(
    "inhalt",
    [
        "",
        "\n\n",
        f"{DIGEST}  PDF-Tool-Setup-2.7.2.exe\n",  # gehört zu einer anderen Datei
        f"{DIGEST[:-1]}  {NAME}\n",  # zu kurz
        f"{DIGEST}x  {NAME}\n",
        f"{DIGEST}  {NAME}\n{'0' * 64}  {NAME}\n",  # widersprüchlich
        f"{'0' * 64}\n{DIGEST}  {NAME}\n",  # widersprüchlich
        "<html>404</html>",
        f"md5 {DIGEST}",
    ],
)
def test_invalid_checksum_files_are_rejected(inhalt):
    with pytest.raises(ChecksumError):
        parse_checksum(inhalt.encode("utf-8"), NAME)


def test_checksum_rejects_binary_and_huge_content():
    with pytest.raises(ChecksumError):
        parse_checksum(b"\xff\xfe\x00", NAME)
    with pytest.raises(ChecksumError):
        parse_checksum(b"0" * 70_000, NAME)


def test_file_hash_and_comparison(tmp_path: Path):
    datei = tmp_path / NAME
    datei.write_bytes(b"MZ" + bytes(range(256)) * 5000)
    digest = hashlib.sha256(datei.read_bytes()).hexdigest()
    assert file_sha256(datei) == digest
    assert matches(datei, digest) and matches(datei, digest.upper())
    assert not matches(datei, "0" * 64)
    assert not matches(datei, "kein hash")
    assert not matches(tmp_path / "fehlt.exe", digest)
    assert same_digest(digest, digest.upper()) and not same_digest(digest, "")
    with pytest.raises(InterruptedError):
        file_sha256(datei, cancelled=lambda: True)


# --- Zustände ---------------------------------------------------------------------------------------------------


def test_state_machine_normal_path():
    machine = StateMachine()
    for target in (UpdateState.CHECKING, UpdateState.AVAILABLE, UpdateState.DOWNLOADING, UpdateState.VERIFYING, UpdateState.READY, UpdateState.INSTALLING):
        machine.go(target)
    assert machine.busy and machine.history[-1] is UpdateState.INSTALLING


@pytest.mark.parametrize(
    "start,ziel",
    [
        (UpdateState.IDLE, UpdateState.DOWNLOADING),
        (UpdateState.IDLE, UpdateState.INSTALLING),
        (UpdateState.CHECKING, UpdateState.INSTALLING),
        (UpdateState.AVAILABLE, UpdateState.INSTALLING),
        (UpdateState.DOWNLOADING, UpdateState.READY),  # nie ohne Prüfung bereit
        (UpdateState.ERROR, UpdateState.READY),
        (UpdateState.CANCELLED, UpdateState.READY),
        (UpdateState.UP_TO_DATE, UpdateState.DOWNLOADING),
    ],
)
def test_state_machine_rejects_invalid_transitions(start, ziel):
    machine = StateMachine(start)
    with pytest.raises(StateError):
        machine.go(ziel)


def test_ready_is_only_reachable_through_verification():
    from updater.state import TRANSITIONS

    sources = {state for state in UpdateState if state is not UpdateState.READY and UpdateState.READY in TRANSITIONS[state]}
    assert sources == {UpdateState.VERIFYING, UpdateState.INSTALLING}  # INSTALLING: Start abgelehnt, zurück


# --- 24 Stunden ----------------------------------------------------------------------------------------------------


def test_24_hour_rule():
    jetzt = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)
    assert schedule.due(None, jetzt)
    assert not schedule.due(jetzt - timedelta(hours=23, minutes=59), jetzt)
    assert schedule.due(jetzt - timedelta(hours=24), jetzt)
    assert schedule.due(jetzt + timedelta(hours=3), jetzt)  # Uhr zurückgestellt
    assert not schedule.due(jetzt + timedelta(minutes=2), jetzt)


def test_time_storage_roundtrip():
    moment = datetime(2026, 10, 1, 9, 30, tzinfo=timezone.utc)
    assert schedule.format_time(moment) == "2026-10-01T09:30:00Z"
    assert schedule.parse_time("2026-10-01T09:30:00Z") == moment
    assert schedule.parse_time("2026-10-01T11:30:00+02:00") == moment
    assert schedule.parse_time("gestern") is None and schedule.parse_time(None) is None


# --- Adressen und Weiterleitungen (Security) ------------------------------------------------------------------------

POLICY = UrlPolicy.github()


@pytest.mark.parametrize(
    "url",
    [
        github.RELEASES_URL,
        "https://github.com/Jerico3241/PDF-Tool/releases/download/v2.7.1/PDF-Tool-Setup-2.7.1.exe",
        "https://release-assets.githubusercontent.com/github-production-release-asset/1382108244/abc?sp=r",
        "https://objects.githubusercontent.com/github-production-release-asset-2e65be/1/2",
        "https://api.github.com:443/repositories/1382108244/releases",
    ],
)
def test_policy_allows_github_over_https(url):
    assert POLICY.allows(url)


@pytest.mark.parametrize(
    "url",
    [
        "http://github.com/Jerico3241/PDF-Tool/releases",  # kein HTTPS
        "ftp://github.com/x",
        "https://evil.example/PDF-Tool-Setup-2.7.3.exe",
        "https://github.com.evil.example/x",
        "https://evilgithubusercontent.com/x",
        "https://githubusercontent.com.evil.example/x",
        "https://github.com@evil.example/x",
        "https://user:pass@github.com/x",
        "https://github.com:8443/x",
        "https://github.com\\@evil.example/x",
        "https://github.com/x y",
        "https://github.com/x\n",
        "javascript:alert(1)",
        "",
        "https://",
    ],
)
def test_policy_rejects_everything_else(url):
    assert not POLICY.allows(url)


def test_redirect_handling():
    quelle = "https://github.com/Jerico3241/PDF-Tool/releases/download/v2.7.1/PDF-Tool-Setup-2.7.1.exe"
    assert POLICY.allows_redirect(quelle, "https://release-assets.githubusercontent.com/github-production-release-asset/1/2?sig=x")
    assert not POLICY.allows_redirect(quelle, "http://release-assets.githubusercontent.com/x")  # Herabstufung auf HTTP
    assert not POLICY.allows_redirect(quelle, "https://evil.example/PDF-Tool-Setup-2.7.1.exe")
    assert not POLICY.allows_redirect(quelle, "file:///C:/Windows/System32/cmd.exe")
    assert POLICY.max_redirects == 5


def test_loopback_policy_is_only_for_the_local_test_server():
    local = UrlPolicy.loopback(8123)
    assert local.allows("http://127.0.0.1:8123/releases")
    assert not local.allows("http://127.0.0.1:8124/releases")
    assert not local.allows("http://localhost:8123/releases")
    assert not local.allows("https://github.com/x")


# --- Release Notes (Test 99) ---------------------------------------------------------------------------------------

ERLAUBT = {"b", "/b", "i", "/i", "code", "/code", "br", "a", "/a"}


def tags(markup: str) -> set[str]:
    return {match.split()[0].lower() for match in re.findall(r"<([^<>]+)>", markup)}


def test_99_release_notes_with_headings_lists_and_links():
    blocks = notes.render(
        "# PDF Tool 2.7.3\n\nEinleitung mit **fett** und `Code`.\n\n## Neu\n\n- Erster Punkt\n  mit Fortsetzung\n- Zweiter mit [Link](https://github.com/Jerico3241/PDF-Tool)\n  - Unterpunkt\n1. Nummer eins\n\n---\n"
    )
    arten = [(block["kind"], block["level"], block["marker"]) for block in blocks]
    assert arten == [("heading", 1, ""), ("paragraph", 0, ""), ("heading", 2, ""), ("bullet", 0, "•"), ("bullet", 0, "•"), ("bullet", 1, "•"), ("bullet", 0, "1."), ("rule", 0, "")]
    assert blocks[1]["html"] == "Einleitung mit <b>fett</b> und <code>Code</code>."
    assert blocks[3]["html"] == "Erster Punkt mit Fortsetzung"
    assert '<a href="https://github.com/Jerico3241/PDF-Tool">Link</a>' in blocks[4]["html"]


def test_99_no_code_execution_and_no_remote_content():
    blocks = notes.render(
        '<script>alert("x")</script>\n\n<img src="https://tracker.example/p.png" onerror="alert(1)">\n\n'
        "![Logo](https://tracker.example/logo.png)\n\n[Klick](javascript:alert(1)) [Datei](file:///C:/x.exe) [Alt](http://example.com)\n\n"
        '<a href="https://evil.example">HTML-Link</a> <iframe src="https://evil.example"></iframe>\n\n<!-- verborgen <b>x</b> -->'
    )
    markup = "".join(block["html"] for block in blocks)
    assert tags(markup) <= ERLAUBT
    assert "<script" not in markup and "<img" not in markup and "<iframe" not in markup
    assert "&lt;script&gt;" in markup  # rohes HTML erscheint als Text
    assert "[Bild: Logo]" in markup
    assert "javascript:" not in re.sub(r"&[a-z]+;", "", " ".join(re.findall(r'href="([^"]*)"', markup)))
    assert all(link.startswith("https://") for link in re.findall(r'href="([^"]*)"', markup))
    assert "verborgen" not in markup


def test_release_notes_of_2_7_1_render_cleanly():
    text = (Path(__file__).resolve().parents[1] / "release-notes" / "2.7.1.md").read_text(encoding="utf-8")
    blocks = notes.render(text)
    assert blocks[0] == {"kind": "heading", "level": 2, "marker": "", "html": "PDF Tool 2.7.1 – PDF Repair Batch"}
    assert sum(block["kind"] == "bullet" for block in blocks) >= 10
    assert tags("".join(block["html"] for block in blocks)) <= ERLAUBT
    assert notes.plain(text, 40).endswith("…")


@pytest.mark.parametrize("url,erlaubt", [("https://github.com/x", True), ("http://github.com/x", False), ("javascript:alert(1)", False), ("https://user@github.com/x", False), ('https://x.example/"onmouseover', False), ("https://", False)])
def test_only_https_links_are_clickable(url, erlaubt):
    assert notes.safe_link(url) is erlaubt


# --- Download-Ordner ----------------------------------------------------------------------------------------------------


def test_store_cleanup_removes_only_own_stale_files(tmp_path: Path):
    store = UpdateStore(tmp_path)
    aktuell = releases(eintrag("v2.7.3"))[0]
    alt = ["PDF-Tool-Setup-2.7.1.exe", "PDF-Tool-Setup-2.7.1.exe.sha256", "PDF-Tool-Setup-2.7.3.exe.part", "PDF-Tool-Setup-2.8.0-beta.1.exe.part"]
    fremd = ["notizen.txt", "PDF-Tool-Setup-2.7.1.exe.bak", "Setup.exe", "releases.json"]
    behalten = ["PDF-Tool-Setup-2.7.3.exe", "PDF-Tool-Setup-2.7.3.exe.sha256"]
    for name in alt + fremd + behalten:
        (tmp_path / name).write_bytes(b"x")
    (tmp_path / "Unterordner").mkdir()
    removed = store.cleanup(keep=aktuell)
    assert sorted(path.name for path in removed) == sorted(alt)
    assert sorted(path.name for path in tmp_path.iterdir()) == sorted(fremd + behalten + ["Unterordner"])
    assert sorted(path.name for path in store.cleanup(keep=None)) == sorted(behalten)


def test_store_paths_cache_and_checksum(tmp_path: Path):
    store = UpdateStore(tmp_path / "updates")
    release = releases(eintrag("v2.8.0-beta.1"))[0]
    assert store.installer(release).name == "PDF-Tool-Setup-2.8.0-beta.1.exe"
    assert store.partial(release).name == "PDF-Tool-Setup-2.8.0-beta.1.exe.part"
    assert store.cached(release) is None
    store.write_checksum(release, DIGEST.upper())
    assert store.checksum_file(release).read_text(encoding="utf-8") == f"{DIGEST}  PDF-Tool-Setup-2.8.0-beta.1.exe\n"
    assert store.read_checksum(release) == DIGEST
    moment = datetime(2026, 10, 1, 9, 30, tzinfo=timezone.utc)
    store.save_releases([release], moment)
    geladen, geprueft = store.load_releases()
    assert geprueft == moment and [r.version for r in geladen] == [release.version] and geladen[0].complete
    (store.folder / "releases.json").write_text("{kaputt", encoding="utf-8")
    assert store.load_releases() == ([], None)


def test_default_update_folder_is_outside_the_program_folder(monkeypatch, tmp_path: Path):
    from updater import store as store_module

    monkeypatch.delenv("UE_UPDATE_DIR", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert store_module.default_dir() == tmp_path / "PDF-Tool-Updates"
    assert store_module.default_dir() != tmp_path / "PDF-Tool"  # Programmordner des Setups
    monkeypatch.setenv("UE_UPDATE_DIR", str(tmp_path / "x"))
    assert store_module.default_dir() == tmp_path / "x"


def test_channel_from_config_defaults_to_stable():
    assert Channel.from_config(None) is Channel.STABLE
    assert Channel.from_config("") is Channel.STABLE
    assert Channel.from_config("Beta") is Channel.BETA
    assert Channel.from_config("nightly") is Channel.STABLE
