"""Analyse und Reparatur in einem eigenen Prozess – und die Übernahme der Ausgabe.

* Die Oberfläche bleibt bedienbar: Die Arbeit läuft nicht im Hauptthread der Oberfläche,
  Fortschritt und Ergebnis kommen über eine Pipe zurück.
* »Abbrechen« ist echt: Der Arbeitsprozess wird beendet und sein Arbeitsordner
  gelöscht. Es bleibt keine unvollständige Ausgabe zurück.
* Ein Arbeitsprozess erledigt mehrere Aufträge nacheinander (``WORKER_JOBS``); nach einem Fehler,
  einem Absturz oder einem Abbruch übernimmt immer ein frischer. Gestartet wird er in einem
  Hilfsthread, nie im Thread der Oberfläche.
* Stürzt eine PDF-Bibliothek an einer bösartigen oder extrem beschädigten Datei
  ab, endet nur der Arbeitsprozess – nicht die App. Unter Windows begrenzt ein
  Job-Objekt zusätzlich seinen Arbeitsspeicher (Schutz vor »Speicherbomben«).
* Ausgaben entstehen nur im Arbeitsordner (Temp). Erst nach bestandener Prüfung
  wird die Datei exklusiv unter einem freien Namen gespeichert – eine vorhandene
  Datei, insbesondere das Original, wird nie überschrieben (Namen und Nummerierung:
  ``batch``).
* Protokollzeilen des Bereichs »repair« aus dem Arbeitsprozess (nur technische Angaben)
  reicht die Pipe an die App weiter; sie schreibt sie in ihr Protokoll.
"""

from __future__ import annotations

import gc
import logging
import multiprocessing
import os
import shutil
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Iterable

from .batch import DEFAULT_SUFFIX as SUFFIX
from .batch import folder_key, names_in, numbered

TEMP_PREFIX = "pdf-tool-reparatur-"
STALE_SECONDS = 24 * 3600
REAP_SECONDS = 30  # so lange holt ein Hilfsthread einen sich beendenden Arbeitsprozess höchstens ab
WORKER_JOBS = 25  # so viele Aufträge erledigt ein Arbeitsprozess, dann folgt ein frischer
WORKER_IDLE = 60  # Sekunden ohne Auftrag: der Arbeitsprozess endet und gibt seinen Speicher frei
REUSE_MARGIN = 10  # so kurz vor diesem Ende wird ein wartender Arbeitsprozess nicht mehr vergeben
# Arbeitsspeicher des Arbeitsprozesses: halber physischer Speicher, mindestens 1,5 GB, höchstens 8 GB
MEMORY_MIN = 1536 * 1024 * 1024
MEMORY_MAX = 8 * 1024 * 1024 * 1024
MEMORY_TEXT = (
    "Die Datei benötigt mehr Arbeitsspeicher als zulässig. Zum Schutz des PCs wurde die Verarbeitung beendet "
    "(z. B. bei extrem großen oder manipulierten Datenströmen). Es wurde keine Datei gespeichert."
)


def _log() -> logging.Logger:
    """Protokoll des Bereichs »repair« – nur technische Angaben, nie Inhalte, Passwörter, Datei- oder Ordnernamen."""
    from diagnostics.applog import get

    return get("repair")


class _ToApp(logging.Handler):
    """Im Arbeitsprozess: Protokollzeilen über die Pipe an die App weiterreichen (nur der Text)."""

    def __init__(self, conn) -> None:
        super().__init__(logging.INFO)
        self.conn = conn

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.conn.send(("log", record.levelno, record.getMessage()[:500]))
        except (OSError, ValueError):
            self.handleError(record)  # Verbindung zur App getrennt: Standardbehandlung von logging


def _lower_priority() -> None:
    """Der Arbeitsprozess soll die Oberfläche nicht ausbremsen."""
    try:
        if sys.platform == "win32":
            import ctypes

            kernel32 = ctypes.windll.kernel32
            kernel32.SetPriorityClass(kernel32.GetCurrentProcess(), 0x00004000)  # BELOW_NORMAL_PRIORITY_CLASS
        else:
            os.nice(5)
    except (OSError, AttributeError) as exc:
        _log().info("Arbeitsprozess: Priorität nicht gesenkt (%s)", type(exc).__name__)


def memory_limit(total: int) -> int:
    return max(MEMORY_MIN, min(MEMORY_MAX, total // 2))


def _limit_memory() -> bool:
    """Obergrenze für den zugesicherten Speicher dieses Prozesses (Windows-Job-Objekt).

    Überschreitet eine Datei die Grenze, schlagen weitere Anforderungen fehl (MemoryError)
    oder der Prozess endet – der PC bleibt bedienbar, die App meldet den Abbruch.
    """
    if sys.platform != "win32":
        return False
    try:
        import ctypes
        from ctypes import wintypes

        class MemoryStatus(ctypes.Structure):
            _fields_ = [("dwLength", wintypes.DWORD), ("dwMemoryLoad", wintypes.DWORD)] + [
                (name, ctypes.c_ulonglong)
                for name in ("ullTotalPhys", "ullAvailPhys", "ullTotalPageFile", "ullAvailPageFile", "ullTotalVirtual", "ullAvailVirtual", "ullAvailExtendedVirtual")
            ]

        class BasicLimit(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_longlong),
                ("PerJobUserTimeLimit", ctypes.c_longlong),
                ("LimitFlags", wintypes.DWORD),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD),
            ]

        class ExtendedLimit(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", BasicLimit),
                ("IoInfo", ctypes.c_ulonglong * 6),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        kernel32.CreateJobObjectW.argtypes = (ctypes.c_void_p, wintypes.LPCWSTR)
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        kernel32.SetInformationJobObject.argtypes = (wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD)
        kernel32.AssignProcessToJobObject.argtypes = (wintypes.HANDLE, wintypes.HANDLE)
        status = MemoryStatus()
        status.dwLength = ctypes.sizeof(MemoryStatus)
        total = status.ullTotalPhys if kernel32.GlobalMemoryStatusEx(ctypes.byref(status)) else 0
        job = kernel32.CreateJobObjectW(None, None)
        if not job:
            return False
        info = ExtendedLimit()
        info.BasicLimitInformation.LimitFlags = 0x00000100  # JOB_OBJECT_LIMIT_PROCESS_MEMORY
        info.ProcessMemoryLimit = memory_limit(total)
        if not kernel32.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info)):  # JobObjectExtendedLimitInformation
            return False
        # Das Handle bleibt bis zum Prozessende offen – die Grenze gilt so lange.
        return bool(kernel32.AssignProcessToJobObject(job, kernel32.GetCurrentProcess()))
    except Exception:
        return False


def _error_text(exc: BaseException, request: dict) -> str:
    """Verständliche Meldung ohne vollständige Pfade (für Oberfläche und Protokoll)."""
    if isinstance(exc, MemoryError):
        return MEMORY_TEXT
    text = f"{type(exc).__name__}: {exc}"
    for key in ("path", "work_dir"):
        value = str(request.get(key) or "")
        if value:
            text = text.replace(value, Path(value).name)
    return f"Die Datei konnte nicht verarbeitet werden ({text[:300]})."


def _serve(conn) -> None:
    """Einstiegspunkt des Arbeitsprozesses (muss auf Modulebene liegen – »spawn«): Aufträge
    ``(art, anfrage)`` nacheinander bearbeiten. Er endet, wenn die App ``None`` schickt oder die
    Verbindung schließt, und nach ``WORKER_IDLE`` Sekunden ohne Auftrag."""
    logger = _log()
    forward = _ToApp(conn)
    logger.addHandler(forward)
    logger.setLevel(logging.INFO)
    _lower_priority()
    _limit_memory()
    try:
        from . import engine  # noqa: F401 - PDF-Bibliotheken laden, solange der Prozess noch wartet
    except Exception as exc:  # noqa: BLE001 - der Auftrag meldet den Fehler dann selbst
        logger.warning("Arbeitsprozess: Engine nicht vorab geladen (%s)", type(exc).__name__)
    try:
        while conn.poll(WORKER_IDLE):
            message = conn.recv()
            if message is None:
                break
            _run(conn, *message)
    except (EOFError, OSError) as exc:
        # Die App wartet nicht mehr (abgebrochen oder beendet): nur noch im eigenen Protokoll
        logger.removeHandler(forward)
        logger.debug("Arbeitsprozess: Verbindung zur App getrennt (%s)", type(exc).__name__)
    finally:
        logger.removeHandler(forward)
        try:
            conn.close()
        except OSError as exc:
            logger.debug("Arbeitsprozess: Pipe nicht geschlossen (%s)", type(exc).__name__)


def _run(conn, kind: str, request: dict) -> None:
    """Einen Auftrag bearbeiten: Fortschritt und dann Ergebnis oder Fehler an die App."""
    try:
        from . import engine
        from .models import RepairMode

        def progress(stage: str, fraction: float | None = None) -> None:
            conn.send(("progress", stage, fraction))

        if kind == "analyze":
            result = engine.analyze(request["path"], request.get("password"), progress)
        elif kind == "repair":
            result = engine.repair(
                request["path"],
                request["work_dir"],
                request.get("password"),
                RepairMode(request.get("mode", RepairMode.AUTO.value)),
                request.get("sha256"),
                progress,
            )
        else:
            raise ValueError(f"Unbekannte Aufgabe: {kind}")
    except (EOFError, OSError) as exc:
        if isinstance(exc, (BrokenPipeError, ConnectionError, EOFError)):
            raise  # Verbindung zur App getrennt
        conn.send(("error", _error_text(exc, request)))
        return
    except BaseException as exc:  # Meldung zurückgeben statt still zu sterben
        conn.send(("error", _error_text(exc, request)))
        return
    # Offene Dateien von Objekten in Referenzzyklen schließen, bevor die App den Arbeitsordner aufräumt
    # oder der Anwender das Original verschiebt – der Prozess bleibt für den nächsten Auftrag bestehen
    gc.collect()
    conn.send(("result", result))


class _Worker:
    """Ein Arbeitsprozess für mehrere Aufträge nacheinander (der Start mit den PDF-Bibliotheken kostet
    unter Windows eine halbe Sekunde und mehr – bei vielen Dateien je Datei)."""

    def __init__(self) -> None:
        context = multiprocessing.get_context("spawn")
        self.conn, child = context.Pipe(duplex=True)
        self.process = context.Process(target=_serve, args=(child,), name="pdf-tool-arbeit", daemon=True)
        try:
            self.process.start()  # dauert – nur in Hilfsthreads aufrufen
        except BaseException:
            self.conn.close()
            raise
        finally:
            child.close()
        self.jobs = 0
        self.idle_since = time.monotonic()

    def reusable(self) -> bool:
        return self.process.is_alive() and self.jobs < WORKER_JOBS and time.monotonic() - self.idle_since < WORKER_IDLE - REUSE_MARGIN

    def retire(self) -> None:
        """Ohne zu warten beenden lassen: Er arbeitet nichts mehr und endet von selbst."""
        try:
            self.conn.send(None)
        except (OSError, ValueError):
            pass
        try:
            self.conn.close()
        except OSError:
            pass


class _Pool:
    """Wartende Arbeitsprozesse (höchstens ``size``)."""

    def __init__(self, size: int) -> None:
        self.size = size
        self._idle: list[_Worker] = []
        self._lock = threading.Lock()
        self._warming = 0

    def take(self) -> _Worker:
        """Einen wartenden Arbeitsprozess oder einen neuen (blockiert beim Start – nur in Hilfsthreads)."""
        with self._lock:
            while self._idle:
                worker = self._idle.pop()
                if worker.reusable():
                    return worker
                worker.retire()
        return _Worker()

    def give_back(self, worker: _Worker) -> None:
        worker.jobs += 1
        worker.idle_since = time.monotonic()
        with self._lock:
            if worker.reusable() and len(self._idle) < self.size:
                self._idle.append(worker)
                return
        worker.retire()

    def warm(self) -> None:
        """Einen Arbeitsprozess im Hintergrund vorbereiten (z. B. sobald »PDF reparieren« geöffnet wird)."""
        with self._lock:
            if self._idle or self._warming:
                return
            self._warming += 1

        def start() -> None:
            try:
                worker = _Worker()
            except Exception as exc:  # noqa: BLE001 - der erste Auftrag versucht es erneut und meldet den Fehler
                _log().info("Arbeitsprozess nicht vorbereitet (%s)", type(exc).__name__)
                worker = None
            with self._lock:
                self._warming -= 1
                if worker is not None and len(self._idle) < self.size:
                    self._idle.append(worker)
                    worker = None
            if worker is not None:
                worker.retire()

        threading.Thread(target=start, name="pdf-tool-arbeit-start", daemon=True).start()

    def close(self) -> None:
        """Alle wartenden Arbeitsprozesse beenden (App endet, Tests)."""
        with self._lock:
            idle, self._idle = self._idle, []
        for worker in idle:
            worker.retire()


_POOL = _Pool(2)


def prepare_worker() -> None:
    """Einen Arbeitsprozess vorbereiten, damit die erste Analyse nicht auf den Prozessstart wartet."""
    _POOL.warm()


def stop_workers() -> None:
    """Wartende Arbeitsprozesse beenden."""
    _POOL.close()


class Job:
    """Eine Analyse oder Reparatur in einem Arbeitsprozess.

    ``events()`` liefert neue Ereignisse, ohne zu blockieren:
    ``("progress", stufe, anteil)``, ``("result", ergebnis)``, ``("error", text)``
    und ``("crash", exitcode)``, wenn der Prozess ohne Ergebnis endet.

    Arbeitsprozesse werden wiederverwendet (``_Pool``): Nach einem Ergebnis wartet der Prozess auf den
    nächsten Auftrag, nach einem Fehler, einem Absturz oder »Abbrechen« nie – dann folgt ein frischer.
    Den Prozess holt bzw. startet ein Hilfsthread: Unter Windows dauert das Anlegen eines Prozesses
    (»spawn«) auf einem ausgelasteten Rechner bis zu einer halben Sekunde – die Oberfläche wartet nicht
    darauf. Bis er den Auftrag hat, liefert ``events()`` nichts; ein Abbruch in dieser Zeit beendet ihn
    gleich danach.
    """

    _starter: threading.Thread | None = None  # holt bzw. startet den Arbeitsprozess
    _start_error: BaseException | None = None  # kein Arbeitsprozess verfügbar
    _worker: _Worker | None = None  # Arbeitsprozess aus dem Vorrat (geht nach einem Ergebnis zurück)
    _outcome = ""  # letztes Ereignis: »result«, »error« oder »crash«

    def __init__(self, kind: str, request: dict) -> None:
        self.kind = kind
        self.work_dir: Path | None = None
        request = dict(request)
        if kind == "repair":
            self.work_dir = Path(tempfile.mkdtemp(prefix=TEMP_PREFIX))
            request["work_dir"] = str(self.work_dir)
        self._request = request
        self._receiver = None
        self._process = None
        self.done = False
        self.cancelled = False
        self.started = time.monotonic()
        self._reaper: threading.Thread | None = None
        self._starter = threading.Thread(target=self._start, name=f"pdf-tool-{kind}-start", daemon=True)
        self._starter.start()

    def _start(self) -> None:
        try:
            worker = _POOL.take()
            try:
                worker.conn.send((self.kind, self._request))
            except (OSError, ValueError):
                # Der wartende Prozess endete gerade (z. B. nach langer Pause) – ein frischer übernimmt
                worker.retire()
                worker = _Worker()
                worker.conn.send((self.kind, self._request))
            self._worker, self._receiver, self._process = worker, worker.conn, worker.process
        except BaseException as exc:  # z. B. zu wenig Systemressourcen: als Fehler melden
            self._start_error = exc
            _log().warning("Arbeitsprozess (%s) ließ sich nicht starten (%s)", self.kind, type(exc).__name__)

    def starting(self) -> bool:
        """Wird der Arbeitsprozess noch geholt bzw. gestartet?"""
        return self._starter is not None and self._starter.is_alive()

    def _receive(self, found: list[tuple]) -> None:
        """Wartende Nachrichten abholen – Protokollzeilen gehen gleich ins Protokoll der App."""
        try:
            while self._receiver.poll():
                event = self._receiver.recv()
                if event[0] == "log":
                    _log().log(event[1], "Arbeitsprozess (%s): %s", self.kind, event[2])
                    continue
                found.append(event)
                if event[0] in ("result", "error"):
                    self.done = True
                    self._outcome = event[0]
                    break
        except (EOFError, OSError) as exc:
            # Pipe zu: Der Prozess hat sich beendet – das Ende meldet ``events`` (Ergebnis oder Absturz)
            _log().debug("Arbeitsprozess (%s): Pipe geschlossen (%s)", self.kind, type(exc).__name__)

    def events(self) -> list[tuple]:
        found: list[tuple] = []
        if self.done or self.starting():
            return found
        if self._start_error is not None:
            self.done = True
            found.append(("error", f"Der Vorgang konnte nicht gestartet werden ({type(self._start_error).__name__})."))
            return found
        self._receive(found)
        if not self.done and not self._process.is_alive():
            # Letzte Nachrichten abholen, dann Absturz melden
            self._receive(found)
            if not self.done:
                self.done = True
                self._outcome = "crash"
                found.append(("crash", self._process.exitcode))
        if self.done:
            self._finish_process()
        return found

    def cancel(self) -> None:
        """Arbeitsprozess beenden und Arbeitsordner entfernen."""
        self.cancelled = True
        self.done = True
        if self.starting():
            # Erst nach dem Start beenden – im Hilfsthread, die Oberfläche wartet nicht
            threading.Thread(target=self._stop_after_start, name=f"pdf-tool-{self.kind}-abbruch", daemon=True).start()
            return
        self._stop()

    def _stop_after_start(self) -> None:
        self._starter.join()
        self._stop()

    def _stop(self) -> None:
        self._worker = None  # nie zurück in den Vorrat
        if self._process is not None and self._process.is_alive():
            self._process.terminate()
            self._process.join(3)
            if self._process.is_alive():
                self._process.kill()
                self._process.join(3)
        self._finish_process()
        self.cleanup()

    def cleanup(self) -> None:
        """Arbeitsordner entfernen – erst nach dem Ende des Arbeitsprozesses, wenn er sich gerade beendet
        (unter Windows hält er sonst noch Dateien darin offen); das geschieht dann im Hintergrund."""
        work_dir, self.work_dir = self.work_dir, None
        if work_dir is None:
            return
        reaper = self._reaper
        if reaper is not None and reaper.is_alive():

            def remove_later() -> None:
                reaper.join()
                shutil.rmtree(work_dir, ignore_errors=True)

            threading.Thread(target=remove_later, name=f"pdf-tool-{self.kind}-aufraeumen", daemon=True).start()
        else:
            shutil.rmtree(work_dir, ignore_errors=True)

    def _finish_process(self) -> None:
        if self._process is None:
            return  # nie gestartet
        worker, self._worker = self._worker, None
        if worker is not None and self._outcome == "result" and not self.cancelled and self._process.is_alive():
            _POOL.give_back(worker)  # wartet auf den nächsten Auftrag (Dateien hat er geschlossen)
            return
        if worker is not None:
            worker.retire()  # nach einem Fehler nie wiederverwenden
        else:
            try:
                self._receiver.close()
            except OSError as exc:
                _log().debug("Arbeitsprozess (%s): Pipe nicht geschlossen (%s)", self.kind, type(exc).__name__)
        if self._process.is_alive():
            # Der Arbeitsprozess beendet sich gerade – mit geladenen PDF-Bibliotheken dauert das unter
            # Windows bis zu einer Sekunde. Die Oberfläche wartet nicht darauf: Ein Hilfsthread holt ihn ab.
            self._reaper = threading.Thread(target=self._process.join, args=(REAP_SECONDS,), name=f"pdf-tool-{self.kind}-ende", daemon=True)
            self._reaper.start()
        else:
            self._process.join(0)

    def wait(self, timeout: float = 600.0, interval: float = 0.05) -> list[tuple]:
        """Blockierend auf das Ende warten (Tests und Prüfskripte, nie in der Oberfläche)."""
        found: list[tuple] = []
        end = time.monotonic() + timeout
        while not self.done and time.monotonic() < end:
            found.extend(self.events())
            if not self.done:
                time.sleep(interval)
        if not self.done:
            self.cancel()
            found.append(("error", "Zeitüberschreitung"))
        elif self._reaper is not None:
            self._reaper.join(REAP_SECONDS)  # blockierend wie bisher: danach räumt cleanup() sofort auf
        return found


# --- Ausgabe übernehmen ------------------------------------------------------------------


def _same_file(a: Path, b: Path) -> bool:
    try:
        return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b)) or (a.exists() and b.exists() and os.path.samefile(a, b))
    except OSError:
        return False


def _taken(target: Path, source: Path, avoid: set[str], existing: set[str]) -> bool:
    """Name belegt: vorhanden (ohne Rücksicht auf Groß-/Kleinschreibung, wie unter Windows), das
    Original oder für eine andere Datei reserviert."""
    folded = target.name.casefold()
    if folded in avoid or folded in existing or _same_file(target, source):
        return True
    if folder_key(target.parent) == folder_key(source.parent) and folded == source.name.casefold():
        return True
    return target.exists()


def next_output(source: Path, folder: Path | None = None, base: str | None = None) -> Path:
    """Vorschau des Ausgabenamens (der erste freie): »Rechnung_repariert.pdf«, »… (1).pdf« …"""
    folder = Path(folder or source.parent)
    base = base or f"{source.stem}{SUFFIX}"
    existing = names_in(folder)
    number = 0
    while _taken(folder / numbered(base, number), source, set(), existing):
        number += 1
    return folder / numbered(base, number)


def deliver(
    temp_output: Path,
    source: Path,
    folder: Path | None = None,
    base: str | None = None,
    start: int = 0,
    avoid: Iterable[str] = (),
) -> Path:
    """Geprüfte Ausgabe exklusiv unter dem ersten freien Namen speichern – nie überschreiben.

    Gewünscht ist ``numbered(base, start)`` (Standard: »<Original>_repariert.pdf«); ist der Name
    belegt (vorhanden, das Original oder in ``avoid`` für eine andere Datei reserviert), folgt die
    nächste Nummer. Geschrieben wird exklusiv (»xb«): Entsteht die Datei gleichzeitig anderswo,
    schlägt das Öffnen fehl und die nächste Nummer wird versucht.
    """
    folder = Path(folder or source.parent)
    base = base or f"{source.stem}{SUFFIX}"
    reserved = {name.casefold() for name in avoid}
    folder.mkdir(parents=True, exist_ok=True)
    existing = names_in(folder)
    number = max(0, start)
    while True:
        target = folder / numbered(base, number)
        number += 1
        if _taken(target, source, reserved, existing):
            continue
        try:
            handle = open(target, "xb")  # schlägt fehl, wenn die Datei schon existiert
        except FileExistsError:
            continue
        try:
            with handle, open(temp_output, "rb") as src:
                shutil.copyfileobj(src, handle, 1 << 20)
                handle.flush()
                os.fsync(handle.fileno())
        except BaseException:
            try:
                target.unlink()
            except OSError:
                pass
            raise
        return target


def cleanup_stale(max_age: float = STALE_SECONDS) -> int:
    """Arbeitsordner früherer, abgebrochener Sitzungen entfernen (z. B. nach einem Absturz)."""
    removed = 0
    base = Path(tempfile.gettempdir())
    now = time.time()
    try:
        entries = list(base.iterdir())
    except OSError:
        return 0
    for entry in entries:
        if not entry.name.startswith(TEMP_PREFIX) or not entry.is_dir():
            continue
        try:
            if now - entry.stat().st_mtime > max_age:
                shutil.rmtree(entry, ignore_errors=True)
                removed += 1
        except OSError:
            continue
    return removed
