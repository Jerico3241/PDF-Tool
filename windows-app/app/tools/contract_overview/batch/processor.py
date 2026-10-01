"""Verarbeitung eines Stapels: bereite Einträge nacheinander als PDF erstellen.

* ``Job`` – ein vorbereiteter Auftrag. Er entsteht erst unmittelbar vor der Verarbeitung
  des Eintrags (im Thread der Oberfläche) – mit den dann aktuellen Werten aus Kundenakte,
  Vorlage und Stapel-Einstellungen.
* ``run_job`` – erstellt eine PDF im Hintergrund mit derselben Engine wie der Einzelmodus
  (``engine.erstelle_pdf``). Jeder Fehler bleibt bei seinem Eintrag: Die Funktion liefert
  immer ein ``JobResult``, nie eine Ausnahme – ein Fehler bei Datei 4 hält Datei 5 nicht auf.
* ``BatchRunner`` – Ablauf nacheinander (Stabilität vor Tempo: Arbeitsspeicher, Excel-
  Dateien, PDF-Erzeugung und Dateizugriffe), Fortschritt, Abbruch.

Sicherheit der Ausgabe: Die PDF entsteht als temporäre Datei im Zielordner und wird erst
fertig an ihren Platz gebracht (siehe ``engine``) – ein Abbruch oder Fehler hinterlässt nie
eine halbe PDF. Vorhandene Dateien werden nur mit der Einstellung »Überschreiben« ersetzt,
nie eine Datei, die im selben Lauf entstanden ist.
"""

from __future__ import annotations

import threading
import time
import traceback
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from ..customers.matching import normalize_email
from ..history.models import records_from
from ..overview import ExcelAnalysis
from .analyzer import analyze_file
from .models import CREATED, ConflictMode, FileStamp, ItemStatus, RunSummary, path_key

LOG_FILE = "stapel.log"
LOG_LIMIT = 1_000_000  # Byte, danach wird das Protokoll einmal rotiert


@dataclass(frozen=True)
class Job:
    item_id: str
    label: str  # z. B. »Muster GmbH« – für »… wird verarbeitet«
    excel: str
    stamp: FileStamp | None  # Stand der Datei bei der Prüfung
    identity: tuple  # Prüfergebnis, von dem die Zuordnung abhängt (siehe ``identity_of``)
    fields: dict  # Auftrag für engine.erstelle_pdf (ohne Zielordner und Ausgabe)
    folder: str
    conflict: ConflictMode = ConflictMode.NUMBER
    created: frozenset[str] = frozenset()  # in diesem Lauf bereits erstellte Dateien (Schlüssel)


@dataclass
class JobResult:
    item_id: str
    status: ItemStatus
    output: str = ""
    notes: tuple[str, ...] = ()
    error: str = ""
    trace: tuple[str, ...] = ()  # technische Kurzfassung für das Protokoll (ohne Inhalte)
    cancelled: bool = False
    changed: bool = False  # Excel nach der Prüfung geändert – nicht verarbeitet, neu prüfen
    analysis: ExcelAnalysis | None = None
    stamp: FileStamp | None = None
    duration: float = 0.0
    # Verträge der erstellten PDF (history.ContractRecord) – Grundlage des Vertragsstands
    contracts: tuple = ()


def identity_of(analysis: ExcelAnalysis | None) -> tuple:
    """Was an einer Prüfung die Kundenzuordnung und die Erstellbarkeit bestimmt."""
    if analysis is None:
        return ()
    return (
        analysis.ok,
        analysis.usable,
        tuple(sorted({normalize_email(mail) for mail in analysis.emails})),
        tuple(sorted(analysis.numbers)),
        tuple(sorted(analysis.companies)),
    )


def unique_path(path: Path, taken: frozenset[str] | set[str] = frozenset()) -> Path:
    """Freier Name: »Name.pdf«, sonst »Name_2.pdf«, »Name_3.pdf« …"""
    candidate = path
    number = 2
    while candidate.exists() or path_key(candidate) in taken:
        candidate = path.with_name(f"{path.stem}_{number}{path.suffix}")
        number += 1
    return candidate


def plan_output(planned: Path, conflict: ConflictMode, created: frozenset[str] = frozenset()) -> tuple[Path | None, list[str], bool]:
    """Ausgabedatei nach der Konfliktregel. Rückgabe: (Datei oder None = überspringen, Hinweise, ersetzen)."""
    in_run = path_key(planned) in created
    exists = planned.exists()
    if not exists and not in_run:
        return planned, [], False
    if not in_run:
        if conflict is ConflictMode.SKIP:
            return None, [f"»{planned.name}« gibt es bereits – übersprungen."], False
        if conflict is ConflictMode.OVERWRITE:
            return planned, [f"Vorhandene »{planned.name}« ersetzt."], True
    # Automatisch nummerieren – und immer, wenn der Name in diesem Lauf schon vergeben wurde
    target = unique_path(planned, created)
    reason = "in diesem Stapel schon vergeben" if in_run else "gab es schon"
    return target, [f"»{planned.name}« {reason} – gespeichert als »{target.name}«."], False


def friendly_error(exc: BaseException) -> str:
    """Verständliche Fehlermeldung (erste Zeilen, ohne technische Details)."""
    if exc.__class__.__name__ == "UnidentifiedImageError" or "cannot identify image file" in str(exc):
        return "Das Logo ist keine lesbare Bilddatei."
    if isinstance(exc, PermissionError):
        text = str(exc)
        if "geöffnet oder schreibgeschützt" in text:
            return text
        return "Keine Berechtigung: Die Datei oder der Zielordner ist gesperrt oder schreibgeschützt."
    if isinstance(exc, FileNotFoundError):
        return str(exc).split("\n")[0].rstrip(":") or "Datei nicht gefunden."
    if isinstance(exc, OSError) and getattr(exc, "strerror", None):
        return f"Die Datei konnte nicht geschrieben werden ({exc.strerror})."
    text = str(exc).strip()
    if isinstance(exc, (ValueError, KeyError)) and text:
        return text.split("\n")[0]
    return f"{exc.__class__.__name__}: {text}" if text else exc.__class__.__name__


def _trace(exc: BaseException) -> tuple[str, ...]:
    """Stelle des Fehlers für das Protokoll – nur Datei, Zeile und Funktion, keine Werte."""
    frames = traceback.extract_tb(exc.__traceback__)[-6:]
    lines = [f"  {Path(frame.filename).name}:{frame.lineno} in {frame.name}" for frame in frames]
    return (exc.__class__.__name__, *lines)


def run_job(job: Job, cancelled: Callable[[], bool], analyze: Callable = analyze_file) -> JobResult:
    """Eine PDF erstellen (Hintergrund-Thread). Wirft nie – jedes Ergebnis ist ein ``JobResult``."""
    from engine import Abgebrochen, PdfAuftrag, ausgabe_pfad, erstelle_pdf

    from ..preview import RENDER_LOCK

    started = time.monotonic()

    def result(status: ItemStatus, **kwargs) -> JobResult:
        return JobResult(job.item_id, status, duration=time.monotonic() - started, **kwargs)

    try:
        if cancelled():
            return result(ItemStatus.READY, cancelled=True)
        stamp = FileStamp.of(job.excel)
        if stamp is None or not Path(job.excel).is_file():
            return result(ItemStatus.FAILED, error="Datei nicht gefunden.")
        notes: list[str] = []
        if stamp != job.stamp:
            # Nach der Prüfung geändert: neu prüfen – nie mit veralteten Angaben erstellen.
            analysis, new_stamp = analyze(job.excel)
            if identity_of(analysis) != job.identity:
                return result(ItemStatus.NEEDS_INPUT, changed=True, analysis=analysis, stamp=new_stamp, error="Die Excel wurde nach der Prüfung geändert – bitte Angaben prüfen.")
            notes.append("Die Excel wurde nach der Prüfung geändert und neu gelesen.")
        auftrag = PdfAuftrag(**job.fields, zielordner=Path(job.folder))
        planned = ausgabe_pfad(auftrag)
        target, conflict_notes, overwrite = plan_output(planned, job.conflict, job.created)
        if target is None:
            return result(ItemStatus.SKIPPED, notes=tuple(conflict_notes))
        notes += conflict_notes
        for attempt in range(3):
            try:
                auftrag = PdfAuftrag(**job.fields, zielordner=Path(job.folder), ausgabe=target, ueberschreiben=overwrite, abbrechen=cancelled)
                with RENDER_LOCK:  # nie parallel zu Vorschau oder Einzel-PDF
                    path = erstelle_pdf(auftrag)
                break
            except FileExistsError:
                # Inzwischen von außen angelegt: nächsten freien Namen nehmen (nie ersetzen)
                if overwrite or attempt == 2:
                    raise
                target = unique_path(planned, job.created)
                notes = [note for note in notes if not note.startswith(f"»{planned.name}«")]
                notes.append(f"»{planned.name}« gab es schon – gespeichert als »{target.name}«.")
        contracts = records_from(auftrag.vertraege, job.fields.get("regeln"), job.fields.get("regelwerk"))
        return result(ItemStatus.WARNING if notes else ItemStatus.SUCCESS, output=str(path), notes=tuple(notes), contracts=contracts)
    except Abgebrochen:
        return result(ItemStatus.READY, cancelled=True)
    except Exception as exc:  # noqa: BLE001 - jeder Fehler bleibt bei diesem Eintrag
        return result(ItemStatus.FAILED, error=friendly_error(exc), trace=_trace(exc))


class BatchRunner:
    """Arbeitet Einträge nacheinander ab – unabhängig von der Oberfläche (testbar).

    * ``prepare(item_id, created)`` liefert den ``Job`` mit aktuellen Werten – oder ``None``,
      wenn der Eintrag inzwischen nicht mehr bereit ist (er wird übersprungen).
    * ``submit(func, on_done, on_error)`` führt ``func`` im Hintergrund aus und meldet das
      Ergebnis im Thread der Oberfläche (in der App: ``worker.run``).
    * ``on_start(item_id, job)``, ``on_result(result)`` und ``on_finish(summary, remaining)``
      melden den Verlauf; ``remaining`` sind die wegen Abbruch nicht verarbeiteten Einträge.
    """

    def __init__(
        self,
        item_ids: list[str],
        prepare: Callable[[str, frozenset[str]], Job | None],
        submit: Callable[..., None],
        on_start: Callable[[str, Job], None],
        on_result: Callable[[JobResult], None],
        on_finish: Callable[[RunSummary, list[str]], None],
        run: Callable[[Job, Callable[[], bool]], JobResult] = run_job,
    ) -> None:
        self._queue: deque[str] = deque(item_ids)
        self._prepare = prepare
        self._submit = submit
        self._on_start = on_start
        self._on_result = on_result
        self._on_finish = on_finish
        self._run = run
        self._cancel = threading.Event()
        self.summary = RunSummary(total=len(item_ids))
        self.created: set[str] = set()
        self.current: str | None = None
        self.current_job: Job | None = None
        self.finished = False

    @property
    def cancel_requested(self) -> bool:
        return self._cancel.is_set()

    def start(self) -> None:
        self._next()

    def cancel(self) -> None:
        """Abbrechen: die laufende PDF endet am nächsten sicheren Punkt, der Rest bleibt unverarbeitet."""
        self._cancel.set()

    def _next(self) -> None:
        while self._queue and not self._cancel.is_set():
            item_id = self._queue.popleft()
            try:
                job = self._prepare(item_id, frozenset(self.created))
            except Exception:  # noqa: BLE001 - ein Eintrag darf den Stapel nie anhalten
                job = None
            if job is None:
                self.summary.skipped += 1
                continue
            self.current, self.current_job = item_id, job
            self._on_start(item_id, job)
            self._submit(lambda job=job: self._run(job, self._cancel.is_set), self._done, lambda exc, tb, job=job: self._failed(job, exc, tb))
            return
        remaining = list(self._queue)
        self._queue.clear()
        if self._cancel.is_set():
            self.summary.aborted = True
            self.summary.cancelled += len(remaining)
        self.current, self.current_job = None, None
        self.finished = True
        self._on_finish(self.summary, remaining)

    def _failed(self, job: Job, exc: BaseException, _tb: str) -> None:
        self._done(JobResult(job.item_id, ItemStatus.FAILED, error=friendly_error(exc), trace=_trace(exc)))

    def _done(self, result: JobResult) -> None:
        self.current, self.current_job = None, None
        summary = self.summary
        if result.cancelled:
            summary.cancelled += 1
            summary.aborted = True
        elif result.status in CREATED:
            summary.created += 1
            if result.status is ItemStatus.WARNING:
                summary.warnings += 1
            self.created.add(path_key(result.output))
            folder = str(Path(result.output).parent)
            if folder not in summary.folders:
                summary.folders.append(folder)
        elif result.status is ItemStatus.FAILED:
            summary.failed += 1
        else:
            summary.skipped += 1
        self._on_result(result)
        self._next()


class BatchLog:
    """Technisches Protokoll ``stapel.log`` im Datenordner.

    Enthält Zeitpunkt, Dateiname, Fehlerart und Fehlerstelle – keine Excel-Inhalte, keine
    Kundendaten und keine vollständigen Pfade (Ordner werden durch »…« ersetzt).
    """

    def __init__(self, folder: Path) -> None:
        self.path = Path(folder) / LOG_FILE

    def write(self, lines: list[str]) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            if self.path.is_file() and self.path.stat().st_size > LOG_LIMIT:
                self.path.replace(self.path.with_suffix(".log.1"))
            stamp = time.strftime("%Y-%m-%d %H:%M:%S")
            with open(self.path, "a", encoding="utf-8") as handle:
                for line in lines:
                    handle.write(f"{stamp}  {line}\n")
        except OSError:
            pass


def redact(text: str, paths: list[str] | tuple[str, ...]) -> str:
    """Vollständige Pfade durch den Dateinamen ersetzen (für das Protokoll)."""
    for raw in sorted({str(path) for path in paths if path}, key=len, reverse=True):
        text = text.replace(raw, "…" + ("\\" if "\\" in raw else "/") + Path(raw).name)
    return text


@dataclass
class ProgressText:
    """Texte für den Fortschritt, z. B. »7 von 20 Übersichten erstellt«."""

    summary: RunSummary = field(default_factory=RunSummary)

    def line(self) -> str:
        s = self.summary
        text = f"{s.created} von {s.total} Übersichten erstellt" if s.total != 1 else f"{s.created} von 1 Übersicht erstellt"
        extra = []
        if s.failed:
            extra.append(f"{s.failed} fehlgeschlagen")
        if s.skipped:
            extra.append(f"{s.skipped} übersprungen")
        return " · ".join([text, *extra])
