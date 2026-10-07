"""Eigene temporäre Dateien früherer Sitzungen entfernen – nie fremde.

Entfernt wird nur, was PDF Tool selbst anlegt und was älter als ein Tag ist (eine laufende
zweite Instanz verliert so nie eine Datei, an der sie gerade arbeitet):

* im temporären Ordner von Windows: ``pdf-tool-vorschau-*``, ``pdf-tool-reparatur-*``,
  ``pdf-tool-logo-*``, ``pdf-tool-diagnose-*``, ``pdf-tool-ocr-*`` (Texterkennung),
  ``pdf-tool-anhaenge-*`` (geöffnete Anhänge) und ``pdf-tool-einfuegen-*`` (eingefügte Bilder);
* im Datenordner und seinen Unterordnern: halbe atomare Schreibvorgänge (``.~*.tmp``,
  ``.gui-config-*.tmp``, ``.kundenakten-*.tmp``, ``.stapel-*.tmp``) sowie ein liegen gebliebener
  ``.wiederherstellung.tmp``;
* im Ordner der automatischen Sicherungen: halbe Sicherungen (``.~sicherung-*.partial``).
"""

from __future__ import annotations

import fnmatch
import os
import shutil
import tempfile
import time
from pathlib import Path

MAX_AGE = 24 * 3600
SYSTEM_TEMP = ("pdf-tool-vorschau-*", "pdf-tool-reparatur-*", "pdf-tool-logo-*", "pdf-tool-diagnose-*", "pdf-tool-ocr-*", "pdf-tool-anhaenge-*", "pdf-tool-einfuegen-*")
DATA_TEMP = (".~*.tmp", ".gui-config-*.tmp", ".kundenakten-*.tmp", ".stapel-*.tmp", ".releases-*.tmp")
DATA_DIRS = ("", "vorlagen", "regelwerke", "contract-history")
BACKUP_TEMP = (".~sicherung-*.partial",)


def _old(path: Path, now: float, max_age: float) -> bool:
    try:
        return now - path.stat().st_mtime > max_age
    except OSError:
        return False


def _remove(path: Path) -> bool:
    try:
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        else:
            path.unlink()
    except OSError:
        return False
    return True


def cleanup_temp(data_dir: str | os.PathLike, backup_folder: str | os.PathLike | None = None, max_age: float = MAX_AGE, temp_dir: str | os.PathLike | None = None) -> list[str]:
    """Aufräumen. Rückgabe: Namen der entfernten Dateien und Ordner."""
    now = time.time()
    removed: list[str] = []
    temp = Path(temp_dir) if temp_dir is not None else Path(tempfile.gettempdir())
    try:
        entries = list(temp.iterdir())
    except OSError:
        entries = []
    for entry in entries:
        if any(fnmatch.fnmatchcase(entry.name, pattern) for pattern in SYSTEM_TEMP) and _old(entry, now, max_age) and _remove(entry):
            removed.append(entry.name)
    data = Path(data_dir)
    for sub in DATA_DIRS:
        folder = data / sub if sub else data
        if not folder.is_dir():
            continue
        candidates = folder.rglob("*") if sub == "contract-history" else folder.iterdir()
        for entry in list(candidates):
            if entry.is_file() and any(fnmatch.fnmatchcase(entry.name, pattern) for pattern in DATA_TEMP) and _old(entry, now, max_age) and _remove(entry):
                removed.append(entry.name)
    stale_stage = data / ".wiederherstellung.tmp"
    if stale_stage.exists() and _old(stale_stage, now, max_age) and _remove(stale_stage):
        removed.append(stale_stage.name)
    if backup_folder is not None and Path(backup_folder).is_dir():
        for entry in Path(backup_folder).iterdir():
            if entry.is_file() and any(fnmatch.fnmatchcase(entry.name, pattern) for pattern in BACKUP_TEMP) and _old(entry, now, max_age) and _remove(entry):
                removed.append(entry.name)
    return removed
