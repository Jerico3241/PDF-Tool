"""Sprachmodelle auf diesem PC: ``%LOCALAPPDATA%\\PDF-Tool-KI\\modelle`` (Tests: ``PDFTOOL_AI_DIR``).

Bewusst nicht im Datenordner von PDF Tool: Modelle sind groß, gehören nicht in Sicherungen oder Support-Pakete und
lassen sich jederzeit löschen (``remove`` – auch die Deinstallation entfernt den Ordner). Ein Modell gilt erst als
eingerichtet, wenn Größe und SHA-256 stimmen: Nach dem Download schreibt ``mark_verified`` die geprüfte Prüfsumme
neben die Datei; ``installed`` vergleicht danach nur Größe und Vermerk (eine 2,7-GB-Datei bei jedem Start zu prüfen
dauerte zu lange).
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from .catalog import MODELS, Model

FOLDER = "PDF-Tool-KI"
DIR_VARIABLE = "PDFTOOL_AI_DIR"
PARTIAL_SUFFIX = ".part"
VERIFIED_SUFFIX = ".sha256"
SPACE_RESERVE = 512 * 1024 * 1024  # nach dem Download sollen noch mindestens 512 MB frei sein


def root() -> Path:
    configured = os.environ.get(DIR_VARIABLE, "").strip()
    if configured:
        return Path(configured)
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / ".local" / "share")
    return Path(base) / FOLDER


def models_dir() -> Path:
    return root() / "modelle"


def path(model: Model) -> Path:
    return models_dir() / model.file


def partial(model: Model) -> Path:
    return models_dir() / (model.file + PARTIAL_SUFFIX)


def _marker(model: Model) -> Path:
    return models_dir() / (model.file + VERIFIED_SUFFIX)


def installed(model: Model) -> bool:
    """Eingerichtet: Datei in der erwarteten Größe und mit dem Vermerk der geprüften Prüfsumme."""
    file = path(model)
    try:
        if not file.is_file() or file.stat().st_size != model.size:
            return False
        return _marker(model).read_text(encoding="ascii").strip().lower() == model.sha256
    except (OSError, UnicodeDecodeError):
        return False


def installed_models() -> list[Model]:
    return [model for model in MODELS if installed(model)]


def partial_size(model: Model) -> int:
    """Bytes eines unterbrochenen Downloads (Fortsetzen) – 0, wenn keiner vorliegt oder er nicht passt."""
    try:
        size = partial(model).stat().st_size
    except OSError:
        return 0
    return size if 0 < size < model.size else 0


def mark_verified(model: Model) -> Path:
    """Geprüften Download übernehmen: ``.part`` → Modelldatei, Vermerk der Prüfsumme daneben."""
    target = path(model)
    os.replace(partial(model), target)
    _marker(model).write_text(model.sha256 + "\n", encoding="ascii")
    return target


def remove(model: Model) -> int:
    """Modell (auch einen unterbrochenen Download) löschen – Ergebnis: freigegebene Bytes."""
    freed = 0
    for file in (path(model), partial(model), _marker(model)):
        try:
            size = file.stat().st_size
            file.unlink()
            freed += size
        except FileNotFoundError:
            continue
        except OSError:
            continue
    _remove_empty(models_dir())
    _remove_empty(root())
    return freed


def used_bytes() -> int:
    total = 0
    for model in MODELS:
        for file in (path(model), partial(model)):
            try:
                total += file.stat().st_size
            except OSError:
                continue
    return total


def free_space() -> int:
    """Freier Platz auf dem Laufwerk der Modelle (0: unbekannt)."""
    folder = root()
    probe = folder
    while not probe.exists() and probe.parent != probe:
        probe = probe.parent
    try:
        return int(shutil.disk_usage(probe).free)
    except OSError:
        return 0


def space_needed(model: Model) -> int:
    """So viel Platz braucht der (restliche) Download, samt Reserve."""
    return max(0, model.size - partial_size(model)) + SPACE_RESERVE


def _remove_empty(folder: Path) -> None:
    try:
        folder.rmdir()  # nur, wenn leer
    except OSError:
        pass
