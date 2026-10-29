"""Viele Dateien umbenennen: Muster mit Platzhaltern, Vorschau, Prüfung und Rückgängig.

Platzhalter: ``{name}`` (bisheriger Name ohne Endung), ``{nr}`` (fortlaufende Nummer, mit führenden Nullen nach der
Stellenzahl), ``{datum}`` (Änderungsdatum der Datei, JJJJ-MM-TT), ``{ordner}`` (Name des Ordners). Die Endung bleibt immer
erhalten. Umbenannt wird nur, wenn alle neuen Namen gültig und frei sind – sonst gar nicht. Tauschen zwei Dateien ihre
Namen (A → B, B → A), wird über vorläufige Namen umbenannt.
"""

from __future__ import annotations

import datetime
import os
import secrets
from dataclasses import dataclass
from pathlib import Path

from tools.pdf_repair.batch import name_error

PLACEHOLDERS = ("{name}", "{nr}", "{datum}", "{ordner}")
DEFAULT_PATTERN = "{name}_{nr}"


@dataclass
class Rename:
    source: Path
    target: Path | None
    error: str = ""

    @property
    def changes(self) -> bool:
        return self.target is not None and self.target.name != self.source.name


def _date(path: Path) -> str:
    try:
        return datetime.date.fromtimestamp(path.stat().st_mtime).isoformat()
    except (OSError, OverflowError, ValueError):
        return datetime.date.today().isoformat()


def pattern_error(pattern: str) -> str:
    if not pattern.strip():
        return "Bitte ein Muster für die neuen Namen eingeben, z. B. »{name}_{nr}«."
    if "{nr}" not in pattern and "{name}" not in pattern and "{datum}" not in pattern:
        return "Das Muster braucht {nr}, {name} oder {datum} – sonst bekämen alle Dateien denselben Namen."
    return ""


def plan(paths: list[str | os.PathLike], pattern: str, start: int = 1, digits: int = 0) -> list[Rename]:
    """Neue Namen in der Reihenfolge der Liste. ``digits`` 0: so viele Stellen wie die größte Nummer braucht."""
    items = [Path(path) for path in paths]
    problem = pattern_error(pattern)
    if problem:
        return [Rename(path, None, problem) for path in items]
    start = max(0, int(start))
    width = digits if digits > 0 else len(str(start + max(0, len(items) - 1)))
    sources = {os.path.normcase(os.path.abspath(path)) for path in items}
    seen: dict[str, int] = {}
    result: list[Rename] = []
    for number, path in enumerate(items):
        base = (pattern.replace("{name}", path.stem).replace("{nr}", str(start + number).zfill(width))
                .replace("{datum}", _date(path)).replace("{ordner}", path.parent.name)).strip()
        error = name_error(base)
        target = path.with_name(base + path.suffix) if not error else None
        if target is not None:
            key = os.path.normcase(os.path.abspath(target))
            if key in seen:
                error = f"Gleicher neuer Name wie Datei {seen[key] + 1}."
                target = None
            else:
                seen[key] = number
                # belegt von einer Datei, die nicht selbst umbenannt wird
                if target.exists() and key not in sources and not _same(target, path):
                    error = f"»{target.name}« gibt es in diesem Ordner schon."
                    target = None
        result.append(Rename(path, target, error))
    return result


def _same(a: Path, b: Path) -> bool:
    try:
        return os.path.samefile(a, b)
    except OSError:
        return False


def apply(renames: list[Rename]) -> list[tuple[Path, Path]]:
    """Umbenennen (alles oder nichts, soweit das Dateisystem es zulässt). Gibt (neu, alt) für »Rückgängig« zurück.
    Schlägt ein Schritt fehl, werden die bereits umbenannten Dateien zurückbenannt und ``OSError`` weitergegeben."""
    if any(item.error for item in renames):
        raise ValueError("Nicht alle neuen Namen sind gültig.")
    moves = [(item.source, item.target) for item in renames if item.changes and item.target is not None]
    done: list[tuple[Path, Path]] = []  # (jetziger Ort, ursprünglicher Ort)
    temps: list[tuple[Path, Path]] = []  # (vorläufig, Ziel)
    try:
        # erst alle auf vorläufige Namen (Tausch von Namen, Groß-/Kleinschreibung), dann auf die Ziele
        for source, target in moves:
            temp = source.with_name(f".{secrets.token_hex(6)}.novadesk-umbenennen{source.suffix}")
            os.rename(source, temp)
            done.append((temp, source))
            temps.append((temp, target))
        for index, (temp, target) in enumerate(temps):
            if target.exists():
                raise FileExistsError(f"»{target.name}« gibt es schon.")
            os.rename(temp, target)
            done[index] = (target, done[index][1])
    except OSError:
        for current, original in reversed(done):
            try:
                os.rename(current, original)
            except OSError:
                pass
        raise
    return [(current, original) for current, original in done]


def undo(pairs: list[tuple[Path, Path]]) -> int:
    """Umbenennen rückgängig machen; gibt die Zahl der zurückbenannten Dateien zurück."""
    back = 0
    for current, original in reversed(pairs):
        if current.exists() and not original.exists():
            try:
                os.rename(current, original)
                back += 1
            except OSError:
                continue
    return back
