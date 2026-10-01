"""Gemeinsame Ablage für Benutzerdaten: atomar schreiben, sicher lesen, Schema-Versionen.

* ``write_json`` / ``write_bytes`` schreiben über eine temporäre Datei im selben Ordner,
  erzwingen das Schreiben auf den Datenträger (``fsync``) und ersetzen die Zieldatei erst dann
  in einem Schritt (``os.replace``). Nach einem Absturz oder Stromausfall gibt es nie eine halbe
  Datei – entweder der alte oder der neue Stand.
* ``read_json`` liefert für fehlende, unlesbare oder beschädigte Dateien kein Ergebnis und einen
  Grund – nie eine Ausnahme. Eine beschädigte Datei macht so nie die ganze App unbrauchbar.
* ``check_schema`` erkennt Daten einer neueren PDF-Tool-Version (``NewerSchema``): Solche Daten
  werden nie überschrieben oder blind gelesen.
* ``data_root`` ist der Ordner der Benutzerdaten (neben ``gui-config.json``, unter Windows
  ``%APPDATA%\\PDF-Tool``).
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


class SchemaError(ValueError):
    """Datei ist kein gültiger Stand dieses Datentyps."""


class NewerSchema(SchemaError):
    """Datei stammt aus einer neueren PDF-Tool-Version (höhere Schema-Version)."""


def data_root() -> Path:
    """Ordner der Benutzerdaten – derselbe wie der von ``gui-config.json`` (Tests: eigener Ordner)."""
    import appstate

    return Path(appstate.CONFIG_FILE).parent


def now_iso() -> str:
    """Aktueller Zeitpunkt (UTC) im Format ``2026-10-01T12:00:00Z``."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def replace_file(source: str | os.PathLike, target: str | os.PathLike, attempts: int = 6) -> None:
    """``os.replace`` mit kurzen Wiederholungen: Unter Windows halten Virenscanner, die Suche oder
    eine laufende Sicherung eine Datei manchmal für Millisekunden offen (Zugriff verweigert)."""
    import time

    for attempt in range(attempts):
        try:
            os.replace(source, target)
            return
        except PermissionError:
            if attempt == attempts - 1:
                raise
            time.sleep(0.02 * (attempt + 1))


def write_bytes(path: str | os.PathLike, payload: bytes, prefix: str = ".~") -> None:
    """Atomar schreiben (temporäre Datei, fsync, ersetzen). Fehler: ``OSError``."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    handle, temp = tempfile.mkstemp(prefix=prefix, suffix=".tmp", dir=str(target.parent))
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        replace_file(temp, target)
    finally:
        if os.path.exists(temp):
            try:
                os.remove(temp)
            except OSError:
                pass


def write_json(path: str | os.PathLike, data, indent: int = 1, prefix: str = ".~") -> None:
    """JSON atomar schreiben (UTF-8, Umlaute unverändert). Fehler: ``OSError``."""
    payload = json.dumps(data, ensure_ascii=False, indent=indent).encode("utf-8")
    write_bytes(path, payload, prefix=prefix)


def read_json(path: str | os.PathLike) -> tuple[object | None, str]:
    """JSON lesen: ``(daten, "")`` oder ``(None, Grund)`` – nie eine Ausnahme."""
    target = Path(path)
    try:
        text = target.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None, "Datei fehlt"
    except OSError as exc:
        return None, f"nicht lesbar ({exc.__class__.__name__})"
    except UnicodeDecodeError:
        return None, "keine Textdatei (UTF-8)"
    try:
        return json.loads(text), ""
    except ValueError:
        return None, "beschädigt (kein gültiges JSON)"


def check_schema(data: object, current: int, kind: str) -> int:
    """Schema-Version eines gelesenen Stands prüfen und zurückgeben.

    ``SchemaError``: kein Objekt oder keine/ungültige Version; ``NewerSchema``: neuer als
    ``current`` – diese PDF-Tool-Version kennt das Format noch nicht.
    """
    if not isinstance(data, dict):
        raise SchemaError(f"{kind}: kein gültiger Datensatz")
    version = data.get("schema_version")
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise SchemaError(f"{kind}: Schema-Version fehlt oder ist ungültig")
    if version > current:
        raise NewerSchema(f"{kind}: mit einer neueren Version von PDF Tool erstellt (Schema {version})")
    return version


# --- Ordner mit je einer JSON-Datei pro Datensatz (Vorlagen, Regelwerke) ------------------------------


_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{0,63}$")


def safe_id(value) -> bool:
    """IDs dienen als Dateinamen: nur Buchstaben, Ziffern und Bindestriche (UUID)."""
    return isinstance(value, str) and bool(_SAFE_ID.match(value))


@dataclass(frozen=True)
class StoreProblem:
    """Eine Datei, die nicht gelesen werden konnte (übersprungen, nie gelöscht)."""

    file: str
    reason: str
    newer: bool = False


class JsonFolderStore:
    """Datensätze mit stabiler ID, je Datensatz eine atomar geschriebene Datei ``<id>.json``.

    * Beschädigte Dateien und Dateien einer neueren Version werden übersprungen und in
      ``problems`` gemeldet – nie gelöscht oder überschrieben.
    * Ohne Ordner (``folder=None``) nur im Arbeitsspeicher (Tests).
    * Unterklassen legen ``kind`` fest und implementieren ``parse``/``serialize``.
    """

    kind = "Datensatz"

    def __init__(self, folder: str | os.PathLike | None) -> None:
        self.folder = Path(folder) if folder is not None else None
        self._items: dict = {}
        self.problems: list[StoreProblem] = []
        self.last_error = ""
        self.writes = 0  # Anzahl gespeicherter Dateien (Tests, Diagnose)

    # Unterklassen -----------------------------------------------------------------------------------
    def parse(self, data):  # pragma: no cover - abstrakt
        raise NotImplementedError

    def serialize(self, item) -> dict:  # pragma: no cover - abstrakt
        raise NotImplementedError

    @staticmethod
    def item_id(item) -> str:
        return item.id

    @staticmethod
    def item_name(item) -> str:
        return item.name

    # Lesen --------------------------------------------------------------------------------------------
    def load(self):
        self._items.clear()
        self.problems = []
        if self.folder is None or not self.folder.is_dir():
            return self
        for path in sorted(self.folder.glob("*.json")):
            if path.name.startswith("."):
                continue
            data, reason = read_json(path)
            if data is None:
                self.problems.append(StoreProblem(path.name, reason))
                continue
            try:
                item = self.parse(data)
            except NewerSchema as exc:
                self.problems.append(StoreProblem(path.name, str(exc), newer=True))
                continue
            except SchemaError as exc:
                self.problems.append(StoreProblem(path.name, str(exc)))
                continue
            if path.stem != self.item_id(item):
                self.problems.append(StoreProblem(path.name, f"{self.kind}: Dateiname passt nicht zur ID"))
                continue
            self._items[self.item_id(item)] = item
        return self

    def __len__(self) -> int:
        return len(self._items)

    def get(self, item_id: str | None):
        return self._items.get(item_id) if item_id else None

    def values(self) -> list:
        return list(self._items.values())

    # Schreiben ----------------------------------------------------------------------------------------
    def path_of(self, item_id: str) -> Path | None:
        if self.folder is None or not safe_id(item_id):
            return None
        return self.folder / f"{item_id}.json"

    def put(self, item) -> bool:
        """Speichern (neu oder geändert). ``False``: Schreibfehler – der Speicher bleibt unverändert."""
        item_id = self.item_id(item)
        if not safe_id(item_id):
            self.last_error = f"{self.kind}: ungültige ID"
            return False
        path = self.path_of(item_id)
        if path is not None:
            try:
                write_json(path, self.serialize(item))
            except OSError as exc:
                self.last_error = f"{self.kind} „{self.item_name(item)}“ konnte nicht gespeichert werden ({exc.__class__.__name__})."
                return False
            self.writes += 1
        self.last_error = ""
        self._items[item_id] = item
        return True

    def remove(self, item_id: str) -> bool:
        item = self.get(item_id)
        if item is None:
            return False
        path = self.path_of(item_id)
        if path is not None:
            try:
                path.unlink(missing_ok=True)
            except OSError as exc:
                self.last_error = f"{self.kind} „{self.item_name(item)}“ konnte nicht gelöscht werden ({exc.__class__.__name__})."
                return False
        del self._items[item_id]
        self.last_error = ""
        return True
