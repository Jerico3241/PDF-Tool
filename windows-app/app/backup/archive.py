"""Sicherung erstellen und prüfen (``.pdtbackup``).

Erstellen ist atomar: Die ZIP-Datei entsteht als temporäre Datei im Zielordner, wird auf den
Datenträger geschrieben (``fsync``), vollständig nachgeprüft (jede Datei gegen ihre SHA-256)
und erst dann unter ihrem endgültigen Namen sichtbar. Eine halbe Sicherung gibt es nie.

Prüfen liest das Manifest und jede Datei: Größe und SHA-256 müssen stimmen, Pfade müssen in
einem bekannten Bereich liegen (nie außerhalb des Datenordners), Schema-Versionen dürfen nicht
neuer sein als die dieser PDF-Tool-Version. Eine Sicherung einer neueren Version wird nie
eingespielt.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import time
import zipfile
import zlib
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Callable

FORMAT = "pdf-tool-backup"
FORMAT_VERSION = 1
SUFFIX = ".pdtbackup"
PREFIX = "PDF-Tool-Sicherung"
MANIFEST = "manifest.json"
DATA = "data/"
MAX_FILES = 200_000
MAX_FILE = 256 * 1024 * 1024  # Bytes einer Datei (Datenordner enthalten nur kleine JSON-Dateien)
MAX_TOTAL = 2 * 1024 * 1024 * 1024  # Bytes insgesamt, unkomprimiert

KIND_MANUAL = "manuell"
KIND_AUTO = "automatisch"
KIND_PRE_UPDATE = "vor-update"
KIND_PRE_RESTORE = "vor-wiederherstellung"
KINDS = {
    KIND_MANUAL: "Manuell",
    KIND_AUTO: "Automatisch",
    KIND_PRE_UPDATE: "Vor einem Update",
    KIND_PRE_RESTORE: "Vor einer Wiederherstellung",
}
NEWER = "Dieses Backup wurde mit einer neueren Version von PDF Tool erstellt."
_HEX64 = re.compile(r"^[0-9a-f]{64}$")


class BackupError(Exception):
    """Sicherung nicht möglich oder nicht verwendbar. ``str()`` ist für Benutzer formuliert."""

    def __init__(self, message: str, newer: bool = False) -> None:
        super().__init__(message)
        self.newer = newer


@dataclass(frozen=True)
class Area:
    key: str
    label: str
    paths: tuple[str, ...]  # Dateien oder Ordner relativ zum Datenordner (Schreibweise mit »/«)


AREAS: tuple[Area, ...] = (
    Area("einstellungen", "Einstellungen, Darstellung und Stapel", ("gui-config.json", "stapel.json")),
    Area("kunden", "Kundenakten und Vertragsstände", ("kundenakten.json", "kundenakten.json.bak", "contract-history")),
    Area("vorlagen", "Vorlagen", ("vorlagen",)),
    Area("regelwerke", "Regelwerke", ("regelwerke",)),
)
AREA = {area.key: area for area in AREAS}


def current_schemas() -> dict[str, int]:
    """Schema-Versionen, die diese PDF-Tool-Version lesen kann."""
    from tools.contract_overview.customers.models import SCHEMA_VERSION as CUSTOMERS
    from tools.contract_overview.history.models import SCHEMA_VERSION as HISTORY
    from tools.contract_overview.rules.models import SCHEMA_VERSION as RULES
    from tools.contract_overview.templates.models import SCHEMA_VERSION as TEMPLATES

    return {"kundenakten": CUSTOMERS, "vertragsstaende": HISTORY, "vorlagen": TEMPLATES, "regelwerke": RULES}


# --- Dateien der Bereiche ---------------------------------------------------------------------------------


def area_of(rel: str) -> str | None:
    """Bereich einer Datei (relativer Pfad mit »/«) – ``None``, wenn sie zu keinem gehört."""
    for area in AREAS:
        for base in area.paths:
            if rel == base or rel.startswith(base + "/"):
                return area.key
    return None


def _is_folder_area(base: str) -> bool:
    return "." not in PurePosixPath(base).name


def valid_member(rel) -> bool:
    """Pfad einer gesicherten Datei: relativ, ohne »..«, ohne Laufwerk, in einem Bereich."""
    if not isinstance(rel, str) or not rel or len(rel) > 400 or "\\" in rel or ":" in rel or "\x00" in rel:
        return False
    path = PurePosixPath(rel)
    if path.is_absolute() or any(part in ("", ".", "..") or part.startswith(".") for part in path.parts):
        return False
    key = area_of(rel)
    if key is None:
        return False
    # Ordner-Bereiche enthalten Dateien, nie den Ordner selbst
    return not any(rel == base and _is_folder_area(base) for base in AREA[key].paths)


def collect_files(root: str | os.PathLike) -> list[tuple[str, str, Path]]:
    """Alle zu sichernden Dateien: ``(Bereich, relativer Pfad, Pfad)`` – sortiert, ohne temporäre Dateien."""
    root = Path(root)
    found: list[tuple[str, str, Path]] = []
    for area in AREAS:
        for base in area.paths:
            path = root / base
            if path.is_symlink():
                continue
            if path.is_file():
                found.append((area.key, base, path))
            elif path.is_dir():
                for child in sorted(path.rglob("*")):
                    if child.is_symlink() or not child.is_file():
                        continue
                    rel = child.relative_to(root).as_posix()
                    if valid_member(rel):  # temporäre Dateien (».~…«) und Fremdes bleiben draußen
                        found.append((area.key, rel, child))
    return found


def fingerprint(root: str | os.PathLike) -> str:
    """Kurzer Schlüssel des Datenstands (Pfade, Größen, Änderungszeiten) – »hat sich etwas geändert?«."""
    digest = hashlib.sha256()
    for _area, rel, path in collect_files(root):
        try:
            stat = path.stat()
        except OSError:
            continue
        digest.update(f"{rel}\0{stat.st_size}\0{stat.st_mtime_ns}\n".encode("utf-8"))
    return digest.hexdigest()[:32]


# --- Erstellen ------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class BackupResult:
    path: Path
    created_at: str
    kind: str
    files: int
    data_bytes: int  # Bytes der gesicherten Dateien
    size: int  # Bytes der Sicherungsdatei
    seconds: float
    areas: dict


def backup_name(kind: str, when: datetime) -> str:
    stamp = when.strftime("%Y-%m-%d_%H-%M-%S")
    return f"{PREFIX}_{stamp}{'' if kind == KIND_MANUAL else '_' + kind}{SUFFIX}"


def _unique(path: Path) -> Path:
    if not path.exists():
        return path
    for number in range(2, 1000):
        candidate = path.with_name(f"{path.name[: -len(SUFFIX)]}_{number}{SUFFIX}")
        if not candidate.exists():
            return candidate
    raise BackupError("Im Zielordner gibt es zu viele Sicherungen mit diesem Zeitpunkt.")


def _zip_time(path: Path) -> tuple[int, int, int, int, int, int]:
    try:
        stamp = time.localtime(path.stat().st_mtime)
    except OSError:
        stamp = time.localtime()
    if stamp.tm_year < 1980:
        return (1980, 1, 1, 0, 0, 0)
    return (stamp.tm_year, stamp.tm_mon, stamp.tm_mday, stamp.tm_hour, stamp.tm_min, stamp.tm_sec - stamp.tm_sec % 2)


def _os_reason(exc: OSError) -> str:
    return exc.strerror or exc.__class__.__name__


def create_backup(
    root: str | os.PathLike,
    folder: str | os.PathLike,
    kind: str = KIND_MANUAL,
    app_version: str = "",
    now: datetime | None = None,
    progress: Callable[[int, int], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> BackupResult:
    """Sicherung des Datenordners ``root`` in ``folder`` erstellen (atomar, nachgeprüft).

    ``BackupError`` mit verständlichem Grund, wenn das nicht möglich ist – dann bleibt keine
    halbe Datei zurück.
    """
    if kind not in KINDS:
        raise ValueError(kind)
    started = time.perf_counter()
    root, folder = Path(root), Path(folder)
    when = (now or datetime.now()).astimezone()
    try:
        folder.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise BackupError(f"Der Ordner für die Sicherung kann nicht angelegt werden ({_os_reason(exc)}).") from exc
    entries = collect_files(root)
    target = _unique(folder / backup_name(kind, when))
    try:
        handle, temp = tempfile.mkstemp(prefix=".~sicherung-", suffix=".partial", dir=str(folder))
    except OSError as exc:
        raise BackupError(f"In diesen Ordner kann nicht geschrieben werden ({_os_reason(exc)}).") from exc
    files: list[dict] = []
    areas = {area.key: {"files": 0, "bytes": 0} for area in AREAS}
    try:
        with os.fdopen(handle, "w+b") as stream:
            with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
                for index, (key, rel, path) in enumerate(entries, 1):
                    if cancelled is not None and cancelled():
                        raise BackupError("Die Sicherung wurde abgebrochen.")
                    try:
                        payload = path.read_bytes()
                    except FileNotFoundError:
                        continue  # inzwischen entfernt (z. B. Stapel geleert)
                    except OSError as exc:
                        raise BackupError(f"„{rel}“ kann nicht gelesen werden ({_os_reason(exc)}).") from exc
                    info = zipfile.ZipInfo(DATA + rel, date_time=_zip_time(path))
                    info.compress_type = zipfile.ZIP_DEFLATED
                    info.external_attr = 0o644 << 16
                    archive.writestr(info, payload)
                    files.append({"path": rel, "area": key, "size": len(payload), "sha256": hashlib.sha256(payload).hexdigest()})
                    areas[key]["files"] += 1
                    areas[key]["bytes"] += len(payload)
                    if progress is not None:
                        progress(index, len(entries))
                manifest = {
                    "format": FORMAT,
                    "format_version": FORMAT_VERSION,
                    "app": "PDF Tool",
                    "app_version": app_version,
                    "created_at": when.isoformat(timespec="seconds"),
                    "kind": kind,
                    "areas": areas,
                    "schemas": current_schemas(),
                    "files": files,
                }
                archive.writestr(MANIFEST, json.dumps(manifest, ensure_ascii=False, indent=1))
            stream.flush()
            os.fsync(stream.fileno())
        _verify_written(Path(temp), files)
        os.replace(temp, target)
    except OSError as exc:
        _remove(temp)
        if getattr(exc, "errno", None) == 28:  # ENOSPC
            raise BackupError("Auf dem Datenträger ist nicht genug Platz für die Sicherung.") from exc
        raise BackupError(f"Die Sicherung konnte nicht geschrieben werden ({_os_reason(exc)}).") from exc
    except BaseException:
        _remove(temp)
        raise
    return BackupResult(
        path=target,
        created_at=manifest["created_at"],
        kind=kind,
        files=len(files),
        data_bytes=sum(entry["size"] for entry in files),
        size=target.stat().st_size,
        seconds=time.perf_counter() - started,
        areas=areas,
    )


def _verify_written(path: Path, files: list[dict]) -> None:
    """Die eben geschriebene Sicherung noch einmal vollständig lesen und vergleichen."""
    try:
        with zipfile.ZipFile(path) as archive:
            names = set(archive.namelist())
            if names != {MANIFEST, *(DATA + entry["path"] for entry in files)}:
                raise BackupError("Die Sicherung ist unvollständig – bitte erneut versuchen.")
            for entry in files:
                if hashlib.sha256(archive.read(DATA + entry["path"])).hexdigest() != entry["sha256"]:
                    raise BackupError("Die Sicherung weicht vom Original ab – bitte erneut versuchen.")
    except zipfile.BadZipFile as exc:
        raise BackupError("Die Sicherung ist beschädigt – bitte erneut versuchen.") from exc


def _remove(path) -> None:
    try:
        os.remove(path)
    except OSError:
        pass


# --- Prüfen ---------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class AreaInfo:
    key: str
    label: str
    files: int
    bytes: int
    summary: str  # z. B. »42 Kundenakten · 120 Vertragsstände«


@dataclass(frozen=True)
class BackupInfo:
    path: Path
    size: int
    created_at: str
    app_version: str
    kind: str
    files: int
    areas: tuple[AreaInfo, ...]
    notes: tuple[str, ...]
    manifest: dict

    def area(self, key: str) -> AreaInfo | None:
        return next((area for area in self.areas if area.key == key), None)

    @property
    def kind_label(self) -> str:
        return KINDS.get(self.kind, self.kind)

    @property
    def created_label(self) -> str:
        return format_time(self.created_at)


def format_time(value: str) -> str:
    try:
        return datetime.fromisoformat(value).astimezone().strftime("%d.%m.%Y, %H:%M")
    except (TypeError, ValueError):
        return ""


def read_manifest(path: str | os.PathLike) -> dict | None:
    """Nur das Manifest lesen (schnell, z. B. für Listen) – ``None``, wenn es keine gültige Sicherung ist."""
    try:
        with zipfile.ZipFile(path) as archive:
            info = archive.getinfo(MANIFEST)
            if info.file_size > 64 * 1024 * 1024:
                return None
            data = json.loads(archive.read(MANIFEST).decode("utf-8"))
    except (OSError, KeyError, ValueError, zipfile.BadZipFile, UnicodeDecodeError):
        return None
    return data if isinstance(data, dict) and data.get("format") == FORMAT else None


def _counts(key: str, entries: list[dict], parsed: dict[str, object]) -> str:
    def plural(number: int, one: str, many: str) -> str:
        return f"{number} {one if number == 1 else many}"

    if key == "einstellungen":
        parts = ["Einstellungen"] if any(e["path"] == "gui-config.json" for e in entries) else []
        queue = parsed.get("stapel.json")
        if isinstance(queue, dict) and isinstance(queue.get("eintraege"), list):
            parts.append("Stapel mit " + plural(len(queue["eintraege"]), "Eintrag", "Einträgen"))
        return " · ".join(parts) or "leer"
    if key == "kunden":
        data = parsed.get("kundenakten.json")
        customers = len(data["customers"]) if isinstance(data, dict) and isinstance(data.get("customers"), list) else 0
        snapshots = sum(1 for e in entries if e["path"].startswith("contract-history/") and e["path"].endswith(".json"))
        return plural(customers, "Kundenakte", "Kundenakten") + " · " + plural(snapshots, "Vertragsstand", "Vertragsstände")
    if key == "vorlagen":
        return plural(sum(1 for e in entries if e["path"].endswith(".json")), "Vorlage", "Vorlagen")
    if key == "regelwerke":
        return plural(sum(1 for e in entries if e["path"].endswith(".json")), "Regelwerk", "Regelwerke")
    return plural(len(entries), "Datei", "Dateien")


def _check_schema(rel: str, data: object, schemas: dict[str, int]) -> str:
    """"" = in Ordnung, "newer" = neuere Version, sonst ein Hinweis (beschädigte Datei)."""
    if rel in ("kundenakten.json", "kundenakten.json.bak"):
        kind, version_key = "kundenakten", "schema_version"
    elif rel.startswith("vorlagen/"):
        kind, version_key = "vorlagen", "schema_version"
    elif rel.startswith("regelwerke/"):
        kind, version_key = "regelwerke", "schema_version"
    elif rel.startswith("contract-history/"):
        kind, version_key = "vertragsstaende", "schema_version"
    else:
        return "" if isinstance(data, dict) else "kein gültiger Datensatz"
    if not isinstance(data, dict):
        return "kein gültiger Datensatz"
    version = data.get(version_key)
    if isinstance(version, bool) or not isinstance(version, int):
        return "" if kind == "vertragsstaende" else "ohne Schema-Version"
    return "newer" if version > schemas[kind] else ""


def inspect_backup(path: str | os.PathLike, app_version: str = "", verify: bool = True, progress: Callable[[int, int], None] | None = None) -> BackupInfo:
    """Sicherung vollständig prüfen. ``BackupError`` (``newer=True`` für neuere Versionen), wenn sie
    nicht verwendbar ist; Hinweise (z. B. eine schon beim Sichern beschädigte Vorlage) in ``notes``."""
    path = Path(path)
    if not path.is_file():
        raise BackupError("Die Sicherungsdatei wurde nicht gefunden.")
    if not zipfile.is_zipfile(path):
        raise BackupError("Die Datei ist keine Sicherung von PDF Tool (kein gültiges Archiv).")
    try:
        archive = zipfile.ZipFile(path)
    except (OSError, zipfile.BadZipFile) as exc:
        raise BackupError("Die Sicherung ist beschädigt und kann nicht gelesen werden.") from exc
    with archive:
        manifest = read_manifest(path)
        if manifest is None:
            raise BackupError("Die Datei ist keine Sicherung von PDF Tool (Manifest fehlt oder ist beschädigt).")
        version = manifest.get("format_version")
        if isinstance(version, bool) or not isinstance(version, int) or version < 1:
            raise BackupError("Die Sicherung hat ein unbekanntes Format.")
        if version > FORMAT_VERSION:
            raise BackupError(NEWER, newer=True)
        schemas = current_schemas()
        for key, value in (manifest.get("schemas") or {}).items():
            if key in schemas and isinstance(value, int) and not isinstance(value, bool) and value > schemas[key]:
                raise BackupError(NEWER, newer=True)
        entries = manifest.get("files")
        if not isinstance(entries, list) or len(entries) > MAX_FILES:
            raise BackupError("Die Sicherung hat ein unbekanntes Format (Dateiliste).")
        seen: set[str] = set()
        total = 0
        for entry in entries:
            if not isinstance(entry, dict):
                raise BackupError("Die Sicherung hat ein unbekanntes Format (Dateiliste).")
            rel, size, digest = entry.get("path"), entry.get("size"), entry.get("sha256")
            if not valid_member(rel) or entry.get("area") != area_of(rel) or rel in seen:
                raise BackupError("Die Sicherung enthält einen ungültigen Dateipfad und wird nicht verwendet.")
            if isinstance(size, bool) or not isinstance(size, int) or not 0 <= size <= MAX_FILE or not isinstance(digest, str) or not _HEX64.match(digest):
                raise BackupError("Die Sicherung hat ein unbekanntes Format (Dateiangaben).")
            seen.add(rel)
            total += size
        if total > MAX_TOTAL:
            raise BackupError("Die Sicherung ist unplausibel groß und wird nicht verwendet.")
        members = {info.filename: info for info in archive.infolist()}
        if set(members) != {MANIFEST, *(DATA + rel for rel in seen)}:
            raise BackupError("Die Sicherung ist unvollständig oder enthält fremde Dateien.")
        for entry in entries:
            if members[DATA + entry["path"]].file_size != entry["size"]:
                raise BackupError("Die Sicherung ist beschädigt (Dateigröße stimmt nicht).")
        notes: list[str] = []
        parsed: dict[str, object] = {}
        if verify:
            for index, entry in enumerate(entries, 1):
                rel = entry["path"]
                try:
                    payload = archive.read(DATA + rel)
                except (OSError, zipfile.BadZipFile, RuntimeError, zlib.error) as exc:  # zlib: beschädigte Daten
                    raise BackupError("Die Sicherung ist beschädigt und kann nicht gelesen werden.") from exc
                if len(payload) != entry["size"] or hashlib.sha256(payload).hexdigest() != entry["sha256"]:
                    raise BackupError(f"Die Sicherung ist beschädigt: „{rel}“ stimmt nicht mit der Prüfsumme überein.")
                if rel.endswith(".json") or rel.endswith(".json.bak"):
                    try:
                        data = json.loads(payload.decode("utf-8"))
                    except (UnicodeDecodeError, ValueError):
                        notes.append(f"„{rel}“ war schon beim Sichern beschädigt und wird beim Einlesen übersprungen.")
                        continue
                    problem = _check_schema(rel, data, schemas)
                    if problem == "newer":
                        raise BackupError(NEWER, newer=True)
                    if problem:
                        notes.append(f"„{rel}“: {problem} – wird beim Einlesen übersprungen.")
                    if rel in ("kundenakten.json", "stapel.json"):
                        parsed[rel] = data
                if progress is not None:
                    progress(index, len(entries))
    created = str(manifest.get("created_at") or "")
    backup_version = str(manifest.get("app_version") or "")
    if app_version and backup_version:
        from updater.semver import Version

        mine, theirs = Version.coerce(app_version), Version.coerce(backup_version)
        if theirs > mine:
            notes.append(f"Erstellt mit PDF Tool {backup_version} – die Daten sind mit dieser Version lesbar.")
    infos = []
    for area in AREAS:
        area_entries = [entry for entry in entries if entry["area"] == area.key]
        infos.append(AreaInfo(area.key, area.label, len(area_entries), sum(e["size"] for e in area_entries), _counts(area.key, area_entries, parsed)))
    return BackupInfo(
        path=path,
        size=path.stat().st_size,
        created_at=created,
        app_version=backup_version,
        kind=str(manifest.get("kind") or ""),
        files=len(entries),
        areas=tuple(infos),
        notes=tuple(notes),
        manifest=manifest,
    )
