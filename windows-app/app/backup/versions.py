"""Backup-Center (seit 5.0 Beta 7): frühere Fassungen der Dokumente, die in Novadesk bearbeitet werden.

* **Vor dem Speichern:** Bevor Novadesk eine Datei überschreibt (PDF, Text, Tabelle, Präsentation), kommt der bisherige
  Stand der Datei als Fassung in die Ablage (``remember``).
* **Automatisch:** Solange ein geöffnetes Dokument ungespeicherte Änderungen hat, legt Novadesk in festen Abständen eine
  Kopie des aktuellen Stands ab (``snapshot_path`` + ``added``) – auch nach einem Absturz ist sie noch da.

Ablage: ``%LOCALAPPDATA%\\PDF-Tool-Editor\\Fassungen\\<Schlüssel>\\`` (lokal, nicht im servergespeicherten Profil, nie in
Sicherungen oder Support-Paketen), je Dokument ein Ordner mit ``dokument.json`` (Pfad und Name) und den Fassungen
``JJJJMMTT-HHMMSS-mmm-<art>.<endung>``. Aufbewahrt werden höchstens ``keep`` Fassungen je Dokument und keine älter als
``days`` Tage; die neueste Fassung bleibt immer. Eine Fassung, die der neuesten gleicht (gleiche Prüfsumme), wird nicht
noch einmal abgelegt.

Wiederherstellen ändert nie still das Original: »Als Kopie« legt eine neue Datei daneben, »Original ersetzen« sichert
vorher den jetzigen Stand als eigene Fassung.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import os
import re
import secrets
import shutil
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

FOLDER = "Fassungen"
META = "dokument.json"
BEFORE_SAVE = "vorher"
AUTOMATIC = "auto"
KINDS = (BEFORE_SAVE, AUTOMATIC)
KIND_LABELS = {BEFORE_SAVE: "Vor dem Speichern", AUTOMATIC: "Automatische Sicherung"}
DEFAULTS = {"an": True, "minuten": 10, "behalten": 20, "tage": 30}
INTERVALS = (5, 10, 15, 30)
KEEP_CHOICES = (5, 10, 20, 50)
DAY_CHOICES = (7, 30, 90, 365)
MAX_FILE = 512 * 1024 * 1024  # größere Dateien (Videos in Präsentationen …) werden nicht kopiert
_NAME = re.compile(r"^(\d{8}-\d{6}-\d{3})-(vorher|auto)(\.[A-Za-z0-9]{1,8})$")
_LOCK = threading.Lock()


def root_dir() -> Path:
    override = os.environ.get("NOVADESK_FASSUNGEN")
    if override:
        return Path(override)
    from tools.pdf_editor import recovery

    return recovery.root_dir() / FOLDER


def key_of(path: str | os.PathLike) -> str:
    normal = os.path.normcase(os.path.abspath(str(path)))
    return hashlib.sha256(normal.encode("utf-8", "replace")).hexdigest()[:16]


def _digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


@dataclass(frozen=True)
class Version:
    path: Path
    kind: str
    created: float  # Sekunden seit 1970
    size: int

    @property
    def stamp(self) -> str:
        return datetime.datetime.fromtimestamp(self.created).strftime("%d.%m.%Y %H:%M")


@dataclass
class Document:
    key: str
    original: str  # Pfad der Datei, zu der die Fassungen gehören
    name: str
    versions: list[Version] = field(default_factory=list)  # neueste zuerst

    @property
    def size(self) -> int:
        return sum(version.size for version in self.versions)

    @property
    def exists(self) -> bool:
        return bool(self.original) and Path(self.original).is_file()


@dataclass
class Settings:
    enabled: bool = True
    minutes: int = 10
    keep: int = 20
    days: int = 30

    @classmethod
    def from_config(cls, data) -> "Settings":
        data = data if isinstance(data, dict) else {}
        settings = cls()
        settings.enabled = bool(data.get("an", DEFAULTS["an"]))
        settings.minutes = int(data["minuten"]) if data.get("minuten") in INTERVALS else DEFAULTS["minuten"]
        settings.keep = int(data["behalten"]) if data.get("behalten") in KEEP_CHOICES else DEFAULTS["behalten"]
        settings.days = int(data["tage"]) if data.get("tage") in DAY_CHOICES else DEFAULTS["tage"]
        return settings

    def to_config(self) -> dict:
        return {"an": self.enabled, "minuten": self.minutes, "behalten": self.keep, "tage": self.days}


class VersionStore:
    def __init__(self, root: Path | None = None, settings: Settings | None = None) -> None:
        self.root = Path(root) if root is not None else root_dir()
        self.settings = settings or Settings()

    # Ablegen --------------------------------------------------------------------------------------------------
    def _folder(self, original: Path) -> Path:
        folder = self.root / key_of(original)
        folder.mkdir(parents=True, exist_ok=True)
        meta = folder / META
        data = {"schema": 1, "pfad": str(original.resolve()) if original.exists() else str(original), "name": original.name}
        try:
            current = json.loads(meta.read_text(encoding="utf-8")) if meta.is_file() else {}
        except (OSError, ValueError):
            current = {}
        if current != data:
            temp = folder / f".{secrets.token_hex(4)}.tmp"
            temp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            os.replace(temp, meta)
        return folder

    @staticmethod
    def _name(folder: Path, kind: str, suffix: str) -> str:
        """Dateiname der neuen Fassung – eindeutig, auch wenn zwei in derselben Millisekunde entstehen."""
        millis = int(time.time() * 1000)
        while True:
            stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(millis / 1000)) + f"-{millis % 1000:03d}"
            name = f"{stamp}-{kind}{suffix.lower()}"
            if not (folder / name).exists():
                return name
            millis += 1

    def remember(self, original: str | os.PathLike, kind: str = BEFORE_SAVE) -> Path | None:
        """Den jetzigen Stand der Datei als Fassung ablegen (vor dem Überschreiben). ``None``: nichts abgelegt (aus,
        Datei fehlt, leer, zu groß oder gleich der neuesten Fassung). Fehler beim Kopieren gibt es als ``OSError``."""
        original = Path(original)
        if not self.settings.enabled or not original.is_file():
            return None
        size = original.stat().st_size
        if size == 0 or size > MAX_FILE:
            return None
        with _LOCK:
            folder = self._folder(original)
            newest = self._versions(folder)
            if newest and newest[0].size == size and _digest(newest[0].path) == _digest(original):
                return None
            target = folder / self._name(folder, kind, original.suffix)
            temp = folder / f".{secrets.token_hex(4)}.tmp"
            try:
                shutil.copyfile(original, temp)
                os.replace(temp, target)
            finally:
                temp.unlink(missing_ok=True)
            self._prune(folder)
        return target

    def snapshot_path(self, original: str | os.PathLike, suffix: str) -> Path:
        """Wohin ein Dokument seinen ungespeicherten Stand schreibt (automatische Sicherung); danach ``added``."""
        with _LOCK:
            folder = self._folder(Path(original))
            target = folder / self._name(folder, AUTOMATIC, suffix)
            target.touch()  # Platz belegen: eine zweite Sicherung in derselben Millisekunde bekommt einen anderen Namen
            return target

    def added(self, snapshot: str | os.PathLike) -> bool:
        """Nach dem Schreiben einer automatischen Sicherung: leere oder doppelte Fassung entfernen, aufräumen."""
        snapshot = Path(snapshot)
        with _LOCK:
            if not snapshot.is_file():
                return False
            if snapshot.stat().st_size == 0:
                snapshot.unlink(missing_ok=True)
                return False
            others = [version for version in self._versions(snapshot.parent) if version.path != snapshot]
            if others and others[0].size == snapshot.stat().st_size and _digest(others[0].path) == _digest(snapshot):
                snapshot.unlink(missing_ok=True)
                return False
            self._prune(snapshot.parent)
        return True

    # Lesen ----------------------------------------------------------------------------------------------------
    @staticmethod
    def _versions(folder: Path) -> list[Version]:
        result = []
        try:
            entries = list(folder.iterdir())
        except OSError:
            return []
        for entry in entries:
            match = _NAME.match(entry.name)
            if not match:
                continue
            try:
                created = time.mktime(time.strptime(match.group(1)[:15], "%Y%m%d-%H%M%S")) + int(match.group(1)[16:]) / 1000
                size = entry.stat().st_size
            except (OSError, ValueError, OverflowError):
                continue
            if size == 0:
                continue  # automatische Sicherung wird gerade geschrieben (oder ist liegen geblieben: ``_prune``)
            result.append(Version(entry, match.group(2), created, size))
        result.sort(key=lambda version: version.created, reverse=True)
        return result

    def documents(self) -> list[Document]:
        """Alle Dokumente mit Fassungen, zuletzt gesicherte zuerst."""
        result = []
        try:
            folders = [entry for entry in self.root.iterdir() if entry.is_dir()]
        except OSError:
            return []
        for folder in folders:
            versions = self._versions(folder)
            if not versions:
                continue
            try:
                meta = json.loads((folder / META).read_text(encoding="utf-8"))
            except (OSError, ValueError):
                meta = {}
            original = str(meta.get("pfad") or "") if isinstance(meta, dict) else ""
            name = str(meta.get("name") or "") if isinstance(meta, dict) else ""
            result.append(Document(folder.name, original, name or Path(original).name or versions[0].path.name, versions))
        result.sort(key=lambda document: document.versions[0].created, reverse=True)
        return result

    def document(self, key: str) -> Document | None:
        return next((document for document in self.documents() if document.key == key), None)

    def total_size(self) -> int:
        return sum(document.size for document in self.documents())

    # Aufräumen ------------------------------------------------------------------------------------------------
    def _prune(self, folder: Path, now: float | None = None) -> int:
        now = time.time() if now is None else now
        versions = self._versions(folder)
        limit = now - self.settings.days * 86400
        removed = 0
        for entry in folder.glob(f"*-{AUTOMATIC}.*"):
            try:
                if entry.stat().st_size == 0 and entry.stat().st_mtime < now - 86400:
                    entry.unlink()  # nie fertig geschriebene automatische Sicherung
            except OSError:
                continue
        for number, version in enumerate(versions):
            if number == 0:
                continue  # die neueste bleibt immer
            if number >= self.settings.keep or version.created < limit:
                try:
                    version.path.unlink()
                    removed += 1
                except OSError:
                    continue
        return removed

    def prune_all(self, now: float | None = None) -> int:
        """Beim Start: alte Fassungen aller Dokumente entfernen, leere Ordner löschen."""
        removed = 0
        try:
            folders = [entry for entry in self.root.iterdir() if entry.is_dir()]
        except OSError:
            return 0
        with _LOCK:
            for folder in folders:
                removed += self._prune(folder, now)
                if not self._versions(folder):
                    shutil.rmtree(folder, ignore_errors=True)
        return removed

    def delete(self, version: str | os.PathLike) -> bool:
        path = Path(version)
        if not self._inside(path):
            return False
        with _LOCK:
            path.unlink(missing_ok=True)
            if not self._versions(path.parent):
                shutil.rmtree(path.parent, ignore_errors=True)
        return True

    def delete_document(self, key: str) -> None:
        if re.fullmatch(r"[0-9a-f]{16}", key or ""):
            with _LOCK:
                shutil.rmtree(self.root / key, ignore_errors=True)

    def clear(self) -> None:
        with _LOCK:
            for folder in list(self.root.iterdir()) if self.root.is_dir() else []:
                if folder.is_dir() and re.fullmatch(r"[0-9a-f]{16}", folder.name):
                    shutil.rmtree(folder, ignore_errors=True)

    def _inside(self, path: Path) -> bool:
        try:
            return path.resolve().parent.parent == self.root.resolve() and bool(_NAME.match(path.name))
        except OSError:
            return False

    # Wiederherstellen -----------------------------------------------------------------------------------------
    def restore_copy(self, version: str | os.PathLike, original: str) -> Path:
        """Fassung als neue Datei neben das Original (bzw. in den Ordner des Originals): »Name (Fassung 29.10.2026
        13.05).docx« – nie über eine bestehende Datei."""
        version = Path(version)
        if not self._inside(version) or not version.is_file():
            raise OSError("Diese Fassung gibt es nicht mehr.")
        target_dir = Path(original).parent if original and Path(original).parent.is_dir() else Path.home()
        stem = Path(original).stem if original else "Dokument"
        when = datetime.datetime.fromtimestamp(_created(version)).strftime("%d.%m.%Y %H.%M")
        candidate = target_dir / f"{stem} (Fassung {when}){version.suffix}"
        number = 2
        while candidate.exists():
            candidate = target_dir / f"{stem} (Fassung {when}, {number}){version.suffix}"
            number += 1
        temp = target_dir / f".{secrets.token_hex(4)}.novadesk.tmp"
        try:
            shutil.copyfile(version, temp)
            os.replace(temp, candidate)
        finally:
            temp.unlink(missing_ok=True)
        return candidate

    def restore_replace(self, version: str | os.PathLike, original: str) -> Path:
        """Original durch die Fassung ersetzen – der jetzige Stand kommt vorher als eigene Fassung in die Ablage."""
        version, target = Path(version), Path(original)
        if not self._inside(version) or not version.is_file():
            raise OSError("Diese Fassung gibt es nicht mehr.")
        if not target.parent.is_dir():
            raise OSError("Der Ordner des Originals existiert nicht mehr.")
        if target.is_file():
            enabled = self.settings.enabled
            self.settings.enabled = True  # auch bei ausgeschalteter Sicherung: vor dem Ersetzen immer sichern
            try:
                self.remember(target, BEFORE_SAVE)
            finally:
                self.settings.enabled = enabled
        temp = target.parent / f".{secrets.token_hex(4)}.novadesk.tmp"
        try:
            shutil.copyfile(version, temp)
            os.replace(temp, target)
        finally:
            temp.unlink(missing_ok=True)
        return target


def _created(version: Path) -> float:
    match = _NAME.match(version.name)
    if not match:
        return time.time()
    return time.mktime(time.strptime(match.group(1)[:15], "%Y%m%d-%H%M%S"))


_SETTINGS = Settings()


def store() -> VersionStore:
    """Die Ablage der laufenden App – Ordner aus der Umgebung (Tests: je Test ein eigener), Einstellungen gemeinsam
    (setzt der ``VersionsController``)."""
    return VersionStore(root_dir(), _SETTINGS)


def configure(settings: Settings) -> None:
    _SETTINGS.enabled, _SETTINGS.minutes, _SETTINGS.keep, _SETTINGS.days = settings.enabled, settings.minutes, settings.keep, settings.days
