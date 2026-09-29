"""Ablage der Vertragsstände: je Kunde ein Ordner, je Stand eine kleine JSON-Datei.

::

    %APPDATA%\\PDF-Tool\\contract-history\\
        <Kunden-ID>\\
            20260812T140312000123-3f2a9c1b.json
            20260929T103000000456-8d41e0aa.json

* Zugeordnet wird allein über die stabile ID der Kundenakte – nie über Firmenname,
  Kundennummer oder E-Mail-Adresse. Ohne Kundenakte entsteht kein Stand.
* Jede Datei wird atomar geschrieben (temporäre Datei, dann ersetzen): Nach einem
  Absturz gibt es nie einen halben Stand.
* Ein Export mit genau demselben Vertragsstand wie der letzte gespeicherte legt keine
  neue Datei an; der vorhandene Stand erhält nur Zeitpunkt und Anzahl des Exports.
* Je Kunde bleiben die letzten ``DEFAULT_LIMIT`` unterschiedlichen Stände erhalten;
  ältere werden beim Speichern eines neuen Stands entfernt (dokumentiert in der README).
* Beschädigte oder neuere Dateien werden übersprungen, nie gelöscht.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
import uuid
from datetime import datetime
from pathlib import Path
from typing import Sequence

from .models import ContractRecord, Snapshot, SnapshotSource, content_hash

FOLDER = "contract-history"
DEFAULT_LIMIT = 50
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")


def file_sha256(path: str | os.PathLike | None) -> str:
    """SHA-256 einer Datei, blockweise gelesen ("" wenn nicht lesbar)."""
    if not path:
        return ""
    digest = hashlib.sha256()
    try:
        with open(path, "rb") as handle:
            for block in iter(lambda: handle.read(1 << 20), b""):
                digest.update(block)
    except OSError:
        return ""
    return digest.hexdigest()


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temp = tempfile.mkstemp(prefix=".~", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(data, stream, ensure_ascii=False, indent=1)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    except BaseException:
        try:
            os.unlink(temp)
        except OSError:
            pass
        raise


class HistoryStore:
    """Lesen und Schreiben der Vertragsstände. Ohne ``root`` (kein Datenordner) bleibt alles leer."""

    def __init__(self, root: str | os.PathLike | None, limit: int = DEFAULT_LIMIT) -> None:
        self.root = Path(root) if root else None
        self.limit = max(1, int(limit))
        self.skipped: list[str] = []  # Dateinamen, die nicht gelesen werden konnten (Protokoll)

    # Lesen ----------------------------------------------------------------------------------------
    def folder(self, customer_id: str | None) -> Path | None:
        if self.root is None or not customer_id or not _SAFE_ID.match(str(customer_id)):
            return None
        return self.root / str(customer_id)

    def _entries(self, customer_id: str | None) -> list[tuple[Path, Snapshot]]:
        """(Datei, Stand) – älteste zuerst."""
        folder = self.folder(customer_id)
        if folder is None or not folder.is_dir():
            return []
        entries: list[tuple[Path, Snapshot]] = []
        try:
            files = sorted(path for path in folder.iterdir() if path.suffix == ".json" and not path.name.startswith("."))
        except OSError:
            return []
        for path in files:
            try:
                snapshot = Snapshot.from_dict(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, ValueError, TypeError, AttributeError):
                if path.name not in self.skipped:
                    self.skipped.append(path.name)
                continue
            if snapshot.customer_id != str(customer_id):
                continue  # gehört nicht zu diesem Kunden – nie vermischen
            entries.append((path, snapshot))
        entries.sort(key=lambda entry: (entry[1].created, entry[0].name))
        return entries

    def snapshots(self, customer_id: str | None) -> list[Snapshot]:
        """Alle Stände eines Kunden, neueste zuerst."""
        return [snapshot for _path, snapshot in reversed(self._entries(customer_id))]

    def latest(self, customer_id: str | None) -> Snapshot | None:
        entries = self._entries(customer_id)
        return entries[-1][1] if entries else None

    def get(self, customer_id: str | None, snapshot_id: str) -> Snapshot | None:
        return next((snapshot for _path, snapshot in self._entries(customer_id) if snapshot.id == snapshot_id), None)

    def count(self, customer_id: str | None) -> int:
        return len(self._entries(customer_id))

    # Schreiben ----------------------------------------------------------------------------------------
    def record(
        self,
        customer_id: str,
        contracts: Sequence[ContractRecord],
        source: SnapshotSource,
        customer_label: str = "",
        now: datetime | None = None,
    ) -> tuple[Snapshot, bool]:
        """Stand nach einem erfolgreichen Export speichern. Rückgabe: (Stand, neu angelegt?).

        Gleicht der Stand genau dem zuletzt gespeicherten, wird keine neue Datei angelegt.
        """
        folder = self.folder(customer_id)
        if folder is None:
            raise ValueError("Ohne Kundenakte wird kein Vertragsstand gespeichert.")
        now = now or datetime.now()
        now = now if now.tzinfo is not None else now.astimezone()  # Ortszeit mit Zeitzone
        stamp = now.isoformat(timespec="seconds")
        contracts = tuple(contracts)
        digest = content_hash(contracts)
        entries = self._entries(customer_id)
        if entries and entries[-1][1].content_hash == digest:
            path, latest = entries[-1]
            updated = Snapshot(
                id=latest.id,
                customer_id=latest.customer_id,
                created_at=latest.created_at,
                contracts=latest.contracts,
                content_hash=latest.content_hash,
                source=source,
                customer_label=customer_label or latest.customer_label,
                last_exported_at=stamp,
                export_count=latest.export_count + 1,
            )
            _write_json(path, updated.to_dict())
            return updated, False
        snapshot = Snapshot(
            id=uuid.uuid4().hex,
            customer_id=str(customer_id),
            created_at=stamp,
            contracts=contracts,
            content_hash=digest,
            source=source,
            customer_label=customer_label,
            last_exported_at=stamp,
        )
        path = folder / f"{now.strftime('%Y%m%dT%H%M%S%f')}-{snapshot.id[:8]}.json"
        _write_json(path, snapshot.to_dict())
        self._trim(customer_id)
        return snapshot, True

    def _trim(self, customer_id: str) -> int:
        """Nur die letzten ``limit`` Stände behalten (älteste zuerst entfernen)."""
        entries = self._entries(customer_id)
        removed = 0
        for path, _snapshot in entries[: max(0, len(entries) - self.limit)]:
            try:
                path.unlink()
                removed += 1
            except OSError:
                continue
        return removed

    def merge(self, target_id: str, source_id: str) -> int:
        """Kundenakten wurden zusammengeführt: Stände von ``source_id`` gehören jetzt zu ``target_id``."""
        source = self.folder(source_id)
        target = self.folder(target_id)
        if source is None or target is None or source == target or not source.is_dir():
            return 0
        moved = 0
        for path, snapshot in self._entries(source_id):
            data = snapshot.to_dict()
            data["customer_id"] = str(target_id)
            destination = target / path.name
            if destination.exists():
                destination = target / f"{path.stem}-{uuid.uuid4().hex[:6]}.json"
            _write_json(destination, data)
            try:
                path.unlink()
            except OSError:
                pass
            moved += 1
        try:
            if not any(source.iterdir()):
                shutil.rmtree(source, ignore_errors=True)
        except OSError:
            pass
        if moved:
            self._trim(target_id)
        return moved
