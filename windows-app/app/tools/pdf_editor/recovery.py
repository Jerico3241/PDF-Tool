"""Sitzungssicherung: ungespeicherte Bearbeitungen nach einem Absturz wiederherstellen.

* Solange ein Dokument ungespeicherte Änderungen hat, legt der Editor in regelmäßigen Abständen
  den aktuellen Stand in einem eigenen Ordner ab (``<root>/Sitzungen/<id>/``) – lokal, nie in der
  Cloud, nie in Sicherungen oder Diagnosepaketen. Verschlüsselte PDFs bleiben dabei verschlüsselt;
  zum Wiederherstellen ist das Passwort erneut nötig (es wird nie gespeichert).
* Jede Sitzung hält eine Sperrdatei offen. Endet der Prozess (auch durch einen Absturz), gibt das
  Betriebssystem die Sperre frei – so erkennt ein späterer Start verwaiste Sitzungen sicher, auch
  wenn PDF Tool mehrmals läuft.
* Nach dem Speichern oder Schließen (auch »Nicht speichern«) wird die Sitzung gelöscht.

Wurzel unter Windows: ``%LOCALAPPDATA%\\PDF-Tool-Editor`` (nicht im servergespeicherten Profil).
"""

from __future__ import annotations

import json
import os
import secrets
import shutil
import sys
import time
from dataclasses import dataclass
from pathlib import Path

SESSIONS = "Sitzungen"
BACKUPS = "Sicherungen"
DATA = "dokument.pdf"
META = "sitzung.json"
LOCK = "sperre"
FOLDER = "PDF-Tool-Editor"
STALE_AFTER = 30 * 24 * 3600  # verwaiste Sitzungen nach 30 Tagen ohne Rückfrage entfernen
BACKUP_MAX_AGE = 7 * 24 * 3600  # Sicherungskopien vor dem Überschreiben


def root_dir() -> Path:
    override = os.environ.get("PDFTOOL_EDITOR_DIR")
    if override:
        return Path(override)
    base = os.environ.get("LOCALAPPDATA")
    if base:
        return Path(base) / FOLDER
    from storage import data_root

    return data_root() / "editor"


def backups_dir(root: Path | None = None) -> Path:
    return (root or root_dir()) / BACKUPS


def cleanup_backups(backup_dir: Path, now: float | None = None) -> int:
    """Sicherungen älter als ``BACKUP_MAX_AGE`` entfernen (beim Start)."""
    now = time.time() if now is None else now
    removed = 0
    try:
        entries = list(backup_dir.glob("*.pdf"))
    except OSError:
        return 0
    for entry in entries:
        try:
            if now - entry.stat().st_mtime > BACKUP_MAX_AGE:
                entry.unlink()
                removed += 1
        except OSError:
            continue
    return removed


@dataclass(frozen=True)
class SessionInfo:
    folder: Path
    name: str  # Dateiname des Dokuments
    original: str  # Pfad der Originaldatei ("" bei neuem Dokument)
    saved_at: float
    encrypted: bool


class _Lock:
    """Exklusive Sperre auf einer Datei – vom Betriebssystem beim Prozessende freigegeben."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.handle = None

    def acquire(self) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = open(self.path, "a+b")
        try:
            if sys.platform == "win32":
                import msvcrt

                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            handle.close()
            return False
        self.handle = handle
        return True

    def release(self) -> None:
        if self.handle is None:
            return
        try:
            if sys.platform == "win32":
                import msvcrt

                self.handle.seek(0)
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        self.handle.close()
        self.handle = None


class RecoverySession:
    """Sicherung eines geöffneten Dokuments (Ordner entsteht erst mit der ersten Sicherung)."""

    def __init__(self, name: str, original: Path | None, encrypted: bool, root: Path | None = None) -> None:
        self.root = root or root_dir()
        self.folder = self.root / SESSIONS / f"{time.strftime('%Y%m%d-%H%M%S')}-{secrets.token_hex(4)}"
        self.name = name
        self.original = original
        self.encrypted = encrypted
        self._lock = _Lock(self.folder / LOCK)
        self.written = False

    def write(self, data: bytes) -> None:
        """Stand sichern (atomar: erst schreiben, dann ersetzen)."""
        if not self.written:
            self.folder.mkdir(parents=True, exist_ok=True)
            if not self._lock.acquire():
                raise OSError("Sitzungssperre nicht verfügbar")
        temp = self.folder / (DATA + ".neu")
        with open(temp, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, self.folder / DATA)
        meta = {"name": self.name, "original": str(self.original or ""), "saved_at": time.time(), "encrypted": self.encrypted, "schema": 1}
        (self.folder / META).write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
        self.written = True

    def discard(self) -> None:
        self._lock.release()
        if self.written or self.folder.exists():
            shutil.rmtree(self.folder, ignore_errors=True)
        self.written = False


def orphaned_sessions(root: Path | None = None, now: float | None = None) -> list[SessionInfo]:
    """Sitzungen ohne lebenden Prozess (Absturz) – neueste zuerst. Sehr alte werden entfernt."""
    root = root or root_dir()
    now = time.time() if now is None else now
    found: list[SessionInfo] = []
    try:
        folders = [path for path in (root / SESSIONS).iterdir() if path.is_dir()]
    except OSError:
        return []
    for folder in folders:
        lock = _Lock(folder / LOCK)
        if not lock.acquire():
            continue  # gehört zu einem laufenden PDF Tool
        lock.release()
        try:
            meta = json.loads((folder / META).read_text(encoding="utf-8"))
            if not (folder / DATA).is_file():
                raise ValueError("ohne Dokument")
        except (OSError, ValueError):
            shutil.rmtree(folder, ignore_errors=True)  # unvollständige Sicherung
            continue
        info = SessionInfo(folder, str(meta.get("name") or "Dokument.pdf"), str(meta.get("original") or ""), float(meta.get("saved_at") or 0), bool(meta.get("encrypted")))
        if now - info.saved_at > STALE_AFTER:
            shutil.rmtree(folder, ignore_errors=True)
            continue
        found.append(info)
    return sorted(found, key=lambda info: info.saved_at, reverse=True)


def read_session(info: SessionInfo) -> bytes:
    return (info.folder / DATA).read_bytes()


def discard_session(info: SessionInfo) -> None:
    shutil.rmtree(info.folder, ignore_errors=True)
