"""Datenprüfung: liest alle Daten von PDF Tool und meldet, was nicht stimmt – ändert nie etwas.

Nur zwei Proben schreiben: je eine kurze Testdatei im Daten- und im Sicherungsordner (mit
eigenem Präfix, sofort wieder entfernt), um die Schreibrechte zu prüfen.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from storage import read_json

OK = "ok"
INFO = "info"
WARNING = "warning"
ERROR = "error"
LOW_SPACE = 200 * 1024 * 1024


@dataclass(frozen=True)
class Check:
    key: str
    label: str
    status: str
    detail: str


def _plural(number: int, one: str, many: str) -> str:
    return f"{number} {one if number == 1 else many}"


def _config(root: Path) -> Check:
    data, reason = read_json(root / "gui-config.json")
    if data is None and reason == "Datei fehlt":
        return Check("config", "Einstellungen", INFO, "Noch nicht gespeichert – es gelten die Standardwerte.")
    if data is None:
        return Check("config", "Einstellungen", ERROR, f"gui-config.json ist {reason}.")
    if not isinstance(data, dict):
        return Check("config", "Einstellungen", ERROR, "gui-config.json hat ein unbekanntes Format.")
    return Check("config", "Einstellungen", OK, "Lesbar.")


def _customers(root: Path) -> Check:
    from tools.contract_overview.customers.models import SCHEMA_VERSION

    data, reason = read_json(root / "kundenakten.json")
    if data is None and reason == "Datei fehlt":
        return Check("customers", "Kundenakten", INFO, "Keine Kundenakten gespeichert.")
    if data is None:
        backup = (root / "kundenakten.json.bak").is_file()
        return Check("customers", "Kundenakten", ERROR, f"kundenakten.json ist {reason}." + (" Die Sicherheitskopie (.bak) wird verwendet." if backup else ""))
    if not isinstance(data, dict) or not isinstance(data.get("customers"), list):
        return Check("customers", "Kundenakten", ERROR, "kundenakten.json hat ein unbekanntes Format.")
    version = data.get("schema_version")
    if isinstance(version, int) and not isinstance(version, bool) and version > SCHEMA_VERSION:
        return Check("customers", "Kundenakten", ERROR, "Mit einer neueren Version von PDF Tool gespeichert.")
    return Check("customers", "Kundenakten", OK, _plural(len(data["customers"]), "Kundenakte", "Kundenakten") + ".")


def _folder_store(key: str, label: str, store, one: str, many: str) -> Check:
    store.load()
    count = len(store)
    if not store.problems:
        return Check(key, label, OK if count else INFO, f"{_plural(count, one, many)}." if count else f"Keine {many} gespeichert.")
    newer = sum(1 for problem in store.problems if problem.newer)
    detail = f"{_plural(count, one, many)} lesbar, {len(store.problems)} nicht lesbar"
    if newer:
        detail += f" (davon {newer} aus einer neueren Version)"
    names = ", ".join(problem.file for problem in store.problems[:5])
    return Check(key, label, WARNING, f"{detail}: {names}. Die Dateien bleiben unverändert.")


def _history(root: Path) -> Check:
    from tools.contract_overview.history.models import SCHEMA_VERSION

    folder = root / "contract-history"
    if not folder.is_dir():
        return Check("history", "Vertragsstände", INFO, "Keine Vertragsstände gespeichert.")
    total = broken = newer = 0
    for path in folder.rglob("*.json"):
        if any(part.startswith(".") for part in path.relative_to(folder).parts):
            continue
        total += 1
        data, _reason = read_json(path)
        if not isinstance(data, dict):
            broken += 1
            continue
        version = data.get("schema_version")
        if isinstance(version, int) and not isinstance(version, bool) and version > SCHEMA_VERSION:
            newer += 1
    if broken or newer:
        parts = []
        if broken:
            parts.append(f"{broken} beschädigt")
        if newer:
            parts.append(f"{newer} aus einer neueren Version")
        return Check("history", "Vertragsstände", WARNING, f"{_plural(total, 'Vertragsstand', 'Vertragsstände')}, davon {', '.join(parts)} – sie werden übersprungen.")
    return Check("history", "Vertragsstände", OK, f"{_plural(total, 'Vertragsstand', 'Vertragsstände')}.")


def _writable(key: str, label: str, folder: Path) -> Check:
    try:
        folder.mkdir(parents=True, exist_ok=True)
        handle, probe = tempfile.mkstemp(prefix=".~diagnose-", suffix=".tmp", dir=str(folder))
        os.close(handle)
        os.remove(probe)
    except OSError as exc:
        return Check(key, label, ERROR, f"Nicht beschreibbar ({exc.strerror or exc.__class__.__name__}).")
    return Check(key, label, OK, "Beschreibbar.")


def _temp() -> Check:
    try:
        with tempfile.TemporaryFile(prefix="pdf-tool-diagnose-") as handle:
            handle.write(b"PDF Tool")
            handle.seek(0)
            if handle.read() != b"PDF Tool":
                raise OSError("Inhalt weicht ab")
    except OSError as exc:
        return Check("temp", "Temporärer Ordner", ERROR, f"Nicht nutzbar ({exc.strerror or exc}).")
    return Check("temp", "Temporärer Ordner", OK, "Nutzbar.")


def _space(root: Path) -> Check:
    try:
        free = shutil.disk_usage(root if root.exists() else root.parent).free
    except OSError:
        return Check("space", "Freier Speicher", INFO, "Nicht ermittelbar.")
    text = (f"{free / 1024**3:.1f} GB frei" if free >= 1024**3 else f"{free / 1024**2:.0f} MB frei").replace(".", ",")
    return Check("space", "Freier Speicher", WARNING if free < LOW_SPACE else OK, text + (" – zu wenig für Sicherungen und PDFs." if free < LOW_SPACE else "."))


def _engines() -> Check:
    from .info import repair_engines

    engines = repair_engines()
    return Check("engines", "Reparatur-Engines", OK if engines != "nicht verfügbar" else ERROR, engines)


def _pending(root: Path) -> Check | None:
    from backup.restore import KEPT, pending

    plan = pending(root)
    if plan is not None:
        return Check("restore", "Wiederherstellung", INFO, f"Vorbereitet aus „{plan.backup}“ – wird beim nächsten Start ausgeführt.")
    try:
        kept = sorted(path.name for path in root.iterdir() if path.name.startswith(KEPT))
    except OSError:
        kept = []
    if kept:
        return Check("restore", "Wiederherstellung", WARNING, f"Eine Wiederherstellung konnte nicht vollständig zurückgenommen werden; der damalige Stand liegt im Datenordner unter „{kept[-1]}“.")
    return None


def run_checks(root: str | os.PathLike, backup_folder: str | os.PathLike) -> list[Check]:
    """Alle Prüfungen (dauert bei vielen Vertragsständen einen Moment – im Hintergrund aufrufen)."""
    from tools.contract_overview.rules.repository import FOLDER as RULES
    from tools.contract_overview.rules.repository import RuleSetStore
    from tools.contract_overview.templates.repository import FOLDER as TEMPLATES
    from tools.contract_overview.templates.repository import TemplateStore

    root = Path(root)
    checks = [
        _config(root),
        _customers(root),
        _folder_store("templates", "Vorlagen", TemplateStore(root / TEMPLATES), "Vorlage", "Vorlagen"),
        _folder_store("rules", "Regelwerke", RuleSetStore(root / RULES), "Regelwerk", "Regelwerke"),
        _history(root),
        _writable("data", "Datenordner", root),
        _writable("backups", "Sicherungsordner", Path(backup_folder)),
        _temp(),
        _space(root),
        _engines(),
    ]
    pending = _pending(root)
    if pending is not None:
        checks.append(pending)
    return checks


def summary(checks: list[Check]) -> tuple[str, str]:
    """Gesamturteil (Status, Text)."""
    errors = sum(1 for check in checks if check.status == ERROR)
    warnings = sum(1 for check in checks if check.status == WARNING)
    if errors:
        return ERROR, f"{_plural(errors, 'Fehler', 'Fehler')}" + (f", {_plural(warnings, 'Hinweis', 'Hinweise')}" if warnings else "") + " gefunden."
    if warnings:
        return WARNING, f"{_plural(warnings, 'Hinweis', 'Hinweise')} – PDF Tool arbeitet weiter, betroffene Dateien werden übersprungen."
    return OK, "Alles in Ordnung."
