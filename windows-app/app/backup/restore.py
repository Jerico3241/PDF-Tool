"""Wiederherstellung: vorbereiten, beim nächsten Start ausführen, bei Fehlern zurückrollen.

Warum beim nächsten Start? Die laufende App hält Einstellungen, Kundenakten und Vorlagen im
Arbeitsspeicher und speichert sie beim Beenden. Würden die Dateien im laufenden Betrieb ersetzt,
überschriebe die App sie danach wieder mit dem alten Stand. Deshalb:

1. ``stage_restore``: Aufbau und Version der Sicherung prüfen und die gewählten Bereiche in den
   Ordner ``.wiederherstellung`` im Datenordner entpacken – jede Datei gegen ihre SHA-256 geprüft
   (die vollständige Prüfung aller Dateien lief schon vor der Zusammenfassung). Erst wenn alles da
   ist, wird der Ordner in einem Schritt sichtbar (Umbenennen).
2. PDF Tool startet neu. ``apply_pending`` läuft vor dem Laden der Einstellungen: Je Bereich
   wandern die aktuellen Dateien nach ``.wiederherstellung-alt`` und die gesicherten an ihren Platz
   (Umbenennen – auf demselben Datenträger atomar). Jeder Schritt steht im Journal.
3. Scheitert ein Schritt, werden alle bisherigen Schritte rückwärts zurückgenommen – der bisherige
   Stand bleibt vollständig. Bricht der Vorgang ab (Absturz, Stromausfall), nimmt der nächste
   Start die Schritte anhand des Journals zurück. Gelingt das Zurücknehmen nicht vollständig, bleibt
   der beiseitegelegte Stand als ``.wiederherstellung-nicht-zurueckgenommen-<Zeitpunkt>`` erhalten
   (nie automatisch gelöscht).

Das Ergebnis steht in ``wiederherstellung-ergebnis.json``; die App zeigt es nach dem Start an.
Ältere Datenstände (z. B. Vorlagen aus 2.8) übernimmt die App beim Laden wie bei einem Update.

Der beiseitegelegte bisherige Stand (bei vielen Vertragsständen tausende Dateien) wird nach dem
Erfolg nur umbenannt (``.wiederherstellung-alt-<Kennung>``) und danach im Hintergrund gelöscht
(``remove_leftovers``) – der Start wartet nicht darauf. Bricht das Löschen ab, setzt der nächste
Start es fort. Den bisherigen Stand enthält ohnehin die Sicherung vor der Wiederherstellung.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import uuid
import zipfile
import zlib
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Callable

from storage import read_json, replace_file, write_json

from .archive import AREA, AREAS, DATA, BackupError, inspect_backup

STAGE = ".wiederherstellung"
ASIDE = ".wiederherstellung-alt"
LEFTOVER = ASIDE + "-"  # Präfix: erledigt, wird im Hintergrund gelöscht
KEPT = ".wiederherstellung-nicht-zurueckgenommen"  # Präfix: bleibt, bis der Benutzer ihn entfernt
RESULT = "wiederherstellung-ergebnis.json"
PLAN = "plan.json"
JOURNAL = "journal.json"
PLAN_VERSION = 1


@dataclass(frozen=True)
class RestorePlan:
    backup: str  # Dateiname der Sicherung
    areas: tuple[str, ...]
    created_at: str
    pre_backup: str  # Dateiname der Sicherung des Stands vor der Wiederherstellung


@dataclass(frozen=True)
class RestoreOutcome:
    ok: bool
    message: str
    areas: tuple[str, ...]
    backup: str
    pre_backup: str


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _rmtree(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path, ignore_errors=True)
    elif path.exists() or path.is_symlink():
        try:
            path.unlink()
        except OSError:
            pass


def _set_aside_for_removal(root: Path, path: Path) -> None:
    """Ordner sofort aus dem Weg räumen (ein Umbenennen); löschen erst ``remove_leftovers``.

    Der neue Name ist eindeutig: Ein späterer Start legt seinen bisherigen Stand nie in einen
    Ordner, aus dem gerade noch gelöscht wird."""
    if not (path.exists() or path.is_symlink()):
        return
    try:
        os.replace(path, root / f"{LEFTOVER}{uuid.uuid4().hex[:12]}")
    except OSError:
        _rmtree(path)


def _keep_aside(root: Path, aside: Path) -> str:
    """Nach einer unvollständigen Rücknahme: den beiseitegelegten Stand behalten – er kann Änderungen
    enthalten, die nach der Sicherung vor der Wiederherstellung entstanden sind. Nie automatisch
    gelöscht. Rückgabe: Ordnername für die Meldung."""
    target = root / f"{KEPT}-{datetime.now():%Y-%m-%d_%H-%M-%S}"
    try:
        os.replace(aside, target)
    except OSError:
        return aside.name
    return target.name


def _not_undone(failed: list[str], kept: str) -> str:
    return f"konnte nicht vollständig zurückgenommen werden ({', '.join(failed)}). Der bisherige Stand liegt im Datenordner unter „{kept}“; auch die Sicherung vor der Wiederherstellung enthält ihn."


def leftovers(root: str | os.PathLike) -> list[Path]:
    """Reste abgeschlossener Wiederherstellungen, die noch gelöscht werden müssen."""
    try:
        return sorted(path for path in Path(root).iterdir() if path.name.startswith(LEFTOVER))
    except OSError:
        return []


def remove_leftovers(root: str | os.PathLike) -> int:
    """Reste abgeschlossener Wiederherstellungen löschen (läuft im Hintergrund). Rückgabe: Anzahl."""
    paths = leftovers(root)
    for path in paths:
        _rmtree(path)
    return len(paths)


def area_labels(keys) -> str:
    return ", ".join(AREA[key].label for key in keys if key in AREA)


# --- Vorbereiten -------------------------------------------------------------------------------------------


def stage_restore(
    backup: str | os.PathLike,
    root: str | os.PathLike,
    areas,
    pre_backup: str = "",
    app_version: str = "",
    progress: Callable[[int, int], None] | None = None,
) -> RestorePlan:
    """Gewählte Bereiche der Sicherung für den nächsten Start bereitlegen (geprüft, vollständig oder gar nicht)."""
    backup, root = Path(backup), Path(root)
    keys = tuple(area.key for area in AREAS if area.key in set(areas))
    if not keys:
        raise BackupError("Bitte mindestens einen Bereich zum Wiederherstellen wählen.")
    # Aufbau, Version, Pfade und Größen; die Prüfsummen prüft das Entpacken je Datei
    info = inspect_backup(backup, app_version=app_version, verify=False)
    entries = [entry for entry in info.manifest["files"] if entry["area"] in keys]
    discard_pending(root)
    temp = root / (STAGE + ".tmp")
    _rmtree(temp)
    try:
        (temp / "data").mkdir(parents=True)
        with zipfile.ZipFile(backup) as archive:
            for index, entry in enumerate(entries, 1):
                try:
                    payload = archive.read(DATA + entry["path"])
                except (zipfile.BadZipFile, RuntimeError, zlib.error) as exc:
                    raise BackupError("Die Sicherung ist beschädigt und kann nicht gelesen werden.") from exc
                if len(payload) != entry["size"] or hashlib.sha256(payload).hexdigest() != entry["sha256"]:
                    raise BackupError(f"Die Sicherung ist beschädigt: „{entry['path']}“ stimmt nicht mit der Prüfsumme überein.")
                target = temp / "data" / PurePosixPath(entry["path"])
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(payload)
                if progress is not None:
                    progress(index, len(entries))
        plan = {
            "schema_version": PLAN_VERSION,
            "state": "staged",
            "backup": backup.name,
            "areas": list(keys),
            "created_at": _now(),
            "pre_backup": pre_backup,
            "app_version": app_version,
        }
        write_json(temp / PLAN, plan)
        os.replace(temp, root / STAGE)
    except OSError as exc:
        _rmtree(temp)
        raise BackupError(f"Die Wiederherstellung konnte nicht vorbereitet werden ({exc.strerror or exc.__class__.__name__}).") from exc
    except BaseException:
        _rmtree(temp)
        raise
    return RestorePlan(backup.name, keys, plan["created_at"], pre_backup)


def pending(root: str | os.PathLike) -> RestorePlan | None:
    """Vorbereitete, noch nicht ausgeführte Wiederherstellung (oder ``None``)."""
    data, _reason = read_json(Path(root) / STAGE / PLAN)
    if not isinstance(data, dict) or data.get("state") != "staged":
        return None
    return RestorePlan(str(data.get("backup") or ""), tuple(k for k in data.get("areas") or () if k in AREA), str(data.get("created_at") or ""), str(data.get("pre_backup") or ""))


def discard_pending(root: str | os.PathLike) -> bool:
    """Vorbereitete Wiederherstellung verwerfen (nur solange sie noch nicht läuft)."""
    stage = Path(root) / STAGE
    if not stage.exists() or (stage / JOURNAL).exists():
        return False
    _rmtree(stage)
    return True


# --- Ausführen (beim Start) ----------------------------------------------------------------------------------


def _journal(stage: Path, steps: list[list[str]]) -> None:
    write_json(stage / JOURNAL, {"state": "applying", "steps": steps})


def _rollback(root: Path, stage: Path, steps: list[list[str]]) -> list[str]:
    """Schritte rückwärts zurücknehmen. Rückgabe: Pfade, die nicht zurückgenommen werden konnten.

    Das Journal vermerkt jeden Schritt *vor* seiner Ausführung. Ob er tatsächlich ausgeführt
    wurde, zeigt der Zustand der Dateien – deshalb prüft jeder Rückschritt erst, ob es etwas
    zurückzunehmen gibt (mehrfach ausführbar, auch nach einem erneuten Abbruch)."""
    aside = root / ASIDE
    failed: list[str] = []
    for action, rel in reversed(steps):
        current = root / rel
        try:
            if action == "placed":
                back = stage / "data" / rel
                if (current.exists() or current.is_symlink()) and not back.exists():
                    back.parent.mkdir(parents=True, exist_ok=True)
                    replace_file(current, back)
            elif action == "aside":
                saved = aside / rel
                if saved.exists():
                    if current.exists() or current.is_symlink():
                        failed.append(rel)  # beide vorhanden: nichts überschreiben
                        continue
                    current.parent.mkdir(parents=True, exist_ok=True)
                    replace_file(saved, current)
        except OSError:
            failed.append(rel)
    return failed


def _result(root: Path, outcome: RestoreOutcome) -> RestoreOutcome:
    try:
        write_json(root / RESULT, {"ok": outcome.ok, "message": outcome.message, "areas": list(outcome.areas), "backup": outcome.backup, "pre_backup": outcome.pre_backup, "at": _now()})
    except OSError:
        pass
    return outcome


def apply_pending(root: str | os.PathLike) -> RestoreOutcome | None:
    """Vor dem Laden der Daten: vorbereitete Wiederherstellung ausführen (oder eine unterbrochene
    zurückrollen). ``None``, wenn nichts vorbereitet war."""
    root = Path(root)
    stage = root / STAGE
    aside = root / ASIDE
    if not stage.is_dir():
        # Rest einer abgeschlossenen Wiederherstellung. Ein liegen gebliebenes ».wiederherstellung.tmp«
        # bleibt: Daran arbeitet womöglich eine zweite laufende Instanz (aufgeräumt wird es nach
        # einem Tag von ``diagnostics.cleanup``, sonst beim nächsten Vorbereiten).
        _set_aside_for_removal(root, aside)
        return None
    plan, _reason = read_json(stage / PLAN)
    journal, _reason = read_json(stage / JOURNAL)
    name = str(plan.get("backup") or "") if isinstance(plan, dict) else ""
    pre = str(plan.get("pre_backup") or "") if isinstance(plan, dict) else ""
    keys = tuple(k for k in (plan.get("areas") or ()) if k in AREA) if isinstance(plan, dict) else ()
    if isinstance(journal, dict) and journal.get("state") == "done":
        # Alle Schritte waren erledigt, nur das Aufräumen fehlte
        outcome = _result(root, RestoreOutcome(True, f"Wiederhergestellt aus „{name}“: {area_labels(keys)}.", keys, name, pre))
        _rmtree(stage)
        _set_aside_for_removal(root, aside)
        return outcome
    if isinstance(journal, dict):
        # Beim letzten Start unterbrochen: alles zurücknehmen
        failed = _rollback(root, stage, [list(step) for step in journal.get("steps") or [] if isinstance(step, list) and len(step) == 2])
        _rmtree(stage)
        message = "Die Wiederherstellung wurde unterbrochen. Der bisherige Stand wurde wiederhergestellt."
        if failed:
            message = "Die Wiederherstellung wurde unterbrochen und " + _not_undone(failed, _keep_aside(root, aside))
        else:
            _rmtree(aside)  # nur noch leere Ordner
        return _result(root, RestoreOutcome(False, message, keys, name, pre))
    if not isinstance(plan, dict) or plan.get("state") != "staged" or not keys or not (stage / "data").is_dir():
        _rmtree(stage)
        return _result(root, RestoreOutcome(False, "Die vorbereitete Wiederherstellung war unvollständig. Es wurde nichts geändert.", keys, name, pre))
    _set_aside_for_removal(root, aside)
    steps: list[list[str]] = []
    try:
        _journal(stage, steps)
        for key in keys:
            for rel in AREA[key].paths:
                current = root / rel
                staged = stage / "data" / rel
                # Erst vermerken, dann ausführen (Write-Ahead): Nach einem Abbruch steht jeder
                # womöglich ausgeführte Schritt im Journal.
                if current.exists() or current.is_symlink():
                    target = aside / rel
                    target.parent.mkdir(parents=True, exist_ok=True)
                    steps.append(["aside", rel])
                    _journal(stage, steps)
                    replace_file(current, target)
                if staged.exists():
                    current.parent.mkdir(parents=True, exist_ok=True)
                    steps.append(["placed", rel])
                    _journal(stage, steps)
                    replace_file(staged, current)
    except OSError as exc:
        failed = _rollback(root, stage, steps)
        _rmtree(stage)
        reason = exc.strerror or exc.__class__.__name__
        message = f"Die Wiederherstellung ist fehlgeschlagen ({reason}). Der bisherige Stand bleibt unverändert."
        if failed:
            message = f"Die Wiederherstellung ist fehlgeschlagen ({reason}) und " + _not_undone(failed, _keep_aside(root, aside))
        else:
            _rmtree(aside)  # nur noch leere Ordner
        return _result(root, RestoreOutcome(False, message, keys, name, pre))
    try:
        write_json(stage / JOURNAL, {"state": "done", "steps": steps})
    except OSError:
        pass  # ohne Vermerk nimmt der nächste Start die Schritte zurück – sicher, nur unnötig
    outcome = _result(root, RestoreOutcome(True, f"Wiederhergestellt aus „{name}“: {area_labels(keys)}.", keys, name, pre))
    _rmtree(stage)  # nur noch leere Ordner – alles Gesicherte liegt an seinem Platz
    _set_aside_for_removal(root, aside)
    return outcome


def take_result(root: str | os.PathLike) -> RestoreOutcome | None:
    """Ergebnis der letzten Wiederherstellung lesen und entfernen (einmal anzeigen)."""
    path = Path(root) / RESULT
    data, _reason = read_json(path)
    try:
        path.unlink()
    except OSError:
        pass
    if not isinstance(data, dict):
        return None
    return RestoreOutcome(bool(data.get("ok")), str(data.get("message") or ""), tuple(k for k in data.get("areas") or () if k in AREA), str(data.get("backup") or ""), str(data.get("pre_backup") or ""))
