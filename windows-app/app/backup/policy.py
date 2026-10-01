"""Automatische Sicherungen, Aufbewahrung und Status.

* Automatisch (Standard: an): höchstens einmal am Tag und nur, wenn sich die Daten seit der
  letzten automatischen Sicherung geändert haben – nie bei jeder Eingabe. Dazu vor jedem Update
  und vor jeder Wiederherstellung.
* Aufbewahrung: die letzten 10 automatischen Sicherungen, je 5 vor Updates und vor
  Wiederherstellungen. Gelöscht wird nur im Ordner der automatischen Sicherungen und nur, was das
  Manifest eindeutig als automatisch ausweist. Manuell erstellte Sicherungen werden nie
  automatisch gelöscht – auch nicht, wenn sie im selben Ordner liegen.
* Der Status (letzte automatische und manuelle Sicherung, Ordner, an/aus) steht in
  ``sicherung.json`` im Datenordner. Diese Datei gehört selbst nicht zur Sicherung: Eine
  Wiederherstellung ändert weder Ordner noch Einstellung der automatischen Sicherung.
"""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass, fields
from datetime import datetime, timedelta, timezone
from pathlib import Path

from storage import read_json, write_json

from .archive import KIND_AUTO, KIND_MANUAL, KIND_PRE_RESTORE, KIND_PRE_UPDATE, PREFIX, SUFFIX, read_manifest

STATE_FILE = "sicherung.json"
STATE_VERSION = 1
DEFAULT_FOLDER = "Sicherungen"
AUTO_INTERVAL = timedelta(hours=24)
KEEP = {KIND_AUTO: 10, KIND_PRE_UPDATE: 5, KIND_PRE_RESTORE: 5}
_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


@dataclass
class BackupState:
    automatic: bool = True
    folder: str = ""  # Ordner der automatischen Sicherungen ("" = Datenordner\Sicherungen)
    manual_folder: str = ""  # zuletzt für eine manuelle Sicherung gewählt
    last_auto: str = ""  # Zeitpunkt (ISO) der letzten automatischen Sicherung
    last_auto_file: str = ""
    last_manual: str = ""
    last_manual_file: str = ""
    fingerprint: str = ""  # Datenstand bei der letzten automatischen Sicherung

    @classmethod
    def load(cls, root: str | os.PathLike) -> "BackupState":
        data, _reason = read_json(Path(root) / STATE_FILE)
        if not isinstance(data, dict):
            return cls()
        state = cls()
        for item in fields(cls):
            value = data.get(item.name)
            if isinstance(value, type(getattr(state, item.name))):
                setattr(state, item.name, value)
        return state

    def save(self, root: str | os.PathLike) -> bool:
        try:
            write_json(Path(root) / STATE_FILE, {"schema_version": STATE_VERSION, **asdict(self)})
        except OSError:
            return False
        return True

    def note(self, kind: str, path: Path, created_at: str, data_fingerprint: str = "") -> None:
        """Erfolgreiche Sicherung vermerken."""
        if kind == KIND_MANUAL:
            self.last_manual, self.last_manual_file = created_at, str(path)
            self.manual_folder = str(path.parent)
        elif kind == KIND_AUTO:
            self.last_auto, self.last_auto_file = created_at, str(path)
            if data_fingerprint:
                self.fingerprint = data_fingerprint


def auto_folder(root: str | os.PathLike, state: BackupState) -> Path:
    return Path(state.folder) if state.folder else Path(root) / DEFAULT_FOLDER


def _parse(value: str) -> datetime | None:
    try:
        stamp = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    return stamp if stamp.tzinfo is not None else stamp.astimezone()


def auto_due(state: BackupState, data_fingerprint: str, now: datetime | None = None) -> bool:
    """Automatische Sicherung fällig? – eingeschaltet, Daten vorhanden und geändert, letzte älter als ein Tag."""
    if not state.automatic or not data_fingerprint:
        return False
    if data_fingerprint == state.fingerprint:
        return False
    last = _parse(state.last_auto)
    now = (now or datetime.now()).astimezone()
    return last is None or now - last >= AUTO_INTERVAL or last > now  # Uhr zurückgestellt: neu sichern


@dataclass(frozen=True)
class BackupEntry:
    path: Path
    kind: str
    created_at: str
    app_version: str
    size: int


def list_backups(folder: str | os.PathLike) -> list[BackupEntry]:
    """Sicherungen von PDF Tool in einem Ordner (neueste zuerst) – nur mit gültigem Manifest."""
    folder = Path(folder)
    entries: list[BackupEntry] = []
    try:
        candidates = sorted(folder.glob(f"{PREFIX}_*{SUFFIX}"))
    except OSError:
        return []
    for path in candidates:
        if not path.is_file():
            continue
        manifest = read_manifest(path)
        if manifest is None:
            continue
        try:
            size = path.stat().st_size
        except OSError:
            continue
        entries.append(BackupEntry(path, str(manifest.get("kind") or ""), str(manifest.get("created_at") or ""), str(manifest.get("app_version") or ""), size))
    entries.sort(key=lambda entry: (_parse(entry.created_at) or _EPOCH, entry.path.name), reverse=True)
    return entries


def prune(folder: str | os.PathLike, keep: dict[str, int] | None = None) -> list[Path]:
    """Ältere automatische Sicherungen entfernen. Rückgabe: gelöschte Dateien.

    Nie gelöscht: manuelle Sicherungen, Dateien ohne gültiges Manifest, unbekannte Arten.
    """
    limits = dict(KEEP if keep is None else keep)
    removed: list[Path] = []
    by_kind: dict[str, list[BackupEntry]] = {}
    for entry in list_backups(folder):
        by_kind.setdefault(entry.kind, []).append(entry)
    for kind, limit in limits.items():
        if kind == KIND_MANUAL:
            continue  # nie
        for entry in by_kind.get(kind, [])[max(1, int(limit)):]:
            try:
                entry.path.unlink()
                removed.append(entry.path)
            except OSError:
                pass
    return removed
