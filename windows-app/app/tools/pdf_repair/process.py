"""Analyse und Reparatur in einem eigenen Prozess – und die Übernahme der Ausgabe.

* Die Oberfläche bleibt bedienbar: Die Arbeit läuft nicht im Tk-Hauptthread,
  Fortschritt und Ergebnis kommen über eine Pipe zurück.
* »Abbrechen« ist echt: Der Arbeitsprozess wird beendet und sein Arbeitsordner
  gelöscht. Es bleibt keine unvollständige Ausgabe zurück.
* Stürzt eine PDF-Bibliothek an einer bösartigen oder extrem beschädigten Datei
  ab, endet nur der Arbeitsprozess – nicht die App. Unter Windows begrenzt ein
  Job-Objekt zusätzlich seinen Arbeitsspeicher (Schutz vor »Speicherbomben«).
* Ausgaben entstehen nur im Arbeitsordner (Temp). Erst nach bestandener Prüfung
  wird die Datei exklusiv unter einem freien Namen gespeichert – eine vorhandene
  Datei, insbesondere das Original, wird nie überschrieben.
"""

from __future__ import annotations

import multiprocessing
import os
import shutil
import sys
import tempfile
import threading
import time
from pathlib import Path

TEMP_PREFIX = "pdf-tool-reparatur-"
SUFFIX = "_repariert"
STALE_SECONDS = 24 * 3600
REAP_SECONDS = 30  # so lange holt ein Hilfsthread einen sich beendenden Arbeitsprozess höchstens ab
# Arbeitsspeicher des Arbeitsprozesses: halber physischer Speicher, mindestens 1,5 GB, höchstens 8 GB
MEMORY_MIN = 1536 * 1024 * 1024
MEMORY_MAX = 8 * 1024 * 1024 * 1024
MEMORY_TEXT = (
    "Die Datei benötigt mehr Arbeitsspeicher als zulässig. Zum Schutz des PCs wurde die Verarbeitung beendet "
    "(z. B. bei extrem großen oder manipulierten Datenströmen). Es wurde keine Datei gespeichert."
)


def _lower_priority() -> None:
    """Der Arbeitsprozess soll die Oberfläche nicht ausbremsen."""
    try:
        if sys.platform == "win32":
            import ctypes

            kernel32 = ctypes.windll.kernel32
            kernel32.SetPriorityClass(kernel32.GetCurrentProcess(), 0x00004000)  # BELOW_NORMAL_PRIORITY_CLASS
        else:
            os.nice(5)
    except Exception:
        pass


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


def _worker(conn, kind: str, request: dict) -> None:
    """Einstiegspunkt des Arbeitsprozesses (muss auf Modulebene liegen – »spawn«)."""
    _lower_priority()
    _limit_memory()
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
        conn.send(("result", result))
    except BaseException as exc:  # Meldung zurückgeben statt still zu sterben
        try:
            conn.send(("error", _error_text(exc, request)))
        except Exception:
            pass
    finally:
        try:
            conn.close()
        except Exception:
            pass


class Job:
    """Eine Analyse oder Reparatur im Arbeitsprozess.

    ``events()`` liefert neue Ereignisse, ohne zu blockieren:
    ``("progress", stufe, anteil)``, ``("result", ergebnis)``, ``("error", text)``
    und ``("crash", exitcode)``, wenn der Prozess ohne Ergebnis endet.
    """

    def __init__(self, kind: str, request: dict) -> None:
        self.kind = kind
        self.work_dir: Path | None = None
        request = dict(request)
        if kind == "repair":
            self.work_dir = Path(tempfile.mkdtemp(prefix=TEMP_PREFIX))
            request["work_dir"] = str(self.work_dir)
        context = multiprocessing.get_context("spawn")
        self._receiver, sender = context.Pipe(duplex=False)
        self._process = context.Process(target=_worker, args=(sender, kind, request), name=f"pdf-tool-{kind}", daemon=True)
        self._process.start()
        sender.close()
        self.done = False
        self.cancelled = False
        self.started = time.monotonic()
        self._reaper: threading.Thread | None = None

    def events(self) -> list[tuple]:
        found: list[tuple] = []
        if self.done:
            return found
        try:
            while self._receiver.poll():
                event = self._receiver.recv()
                found.append(event)
                if event[0] in ("result", "error"):
                    self.done = True
                    break
        except (EOFError, OSError):
            pass
        if not self.done and not self._process.is_alive():
            # Letzte Nachrichten abholen, dann Absturz melden
            try:
                while self._receiver.poll():
                    event = self._receiver.recv()
                    found.append(event)
                    if event[0] in ("result", "error"):
                        self.done = True
                        break
            except (EOFError, OSError):
                pass
            if not self.done:
                self.done = True
                found.append(("crash", self._process.exitcode))
        if self.done:
            self._finish_process()
        return found

    def cancel(self) -> None:
        """Arbeitsprozess beenden und Arbeitsordner entfernen."""
        self.cancelled = True
        self.done = True
        if self._process.is_alive():
            self._process.terminate()
            self._process.join(3)
            if self._process.is_alive():
                self._process.kill()
                self._process.join(3)
        self._finish_process()
        self.cleanup()

    def cleanup(self) -> None:
        """Arbeitsordner entfernen – erst nach dem Ende des Arbeitsprozesses (unter Windows hält er
        sonst noch Dateien darin offen); beendet er sich noch, geschieht das im Hintergrund."""
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
        try:
            self._receiver.close()
        except Exception:
            pass
        if self._process.is_alive():
            # Das Ergebnis ist da, der Arbeitsprozess beendet sich gerade – mit geladenen PDF-Bibliotheken
            # dauert das unter Windows bis zu einer Sekunde. Die Oberfläche wartet nicht darauf:
            # Ein Hilfsthread holt den Prozess ab.
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


def output_name(source: Path, number: int = 1) -> str:
    """»Rechnung.pdf« → »Rechnung_repariert.pdf«, bei Konflikt »Rechnung_repariert_2.pdf« …"""
    return f"{source.stem}{SUFFIX}.pdf" if number <= 1 else f"{source.stem}{SUFFIX}_{number}.pdf"


def next_output(source: Path, folder: Path | None = None) -> Path:
    """Vorschau des Ausgabenamens (der erste freie)."""
    folder = folder or source.parent
    number = 1
    while (folder / output_name(source, number)).exists() or _same_file(folder / output_name(source, number), source):
        number += 1
    return folder / output_name(source, number)


def deliver(temp_output: Path, source: Path, folder: Path | None = None) -> Path:
    """Geprüfte Ausgabe exklusiv unter dem ersten freien Namen speichern – nie überschreiben."""
    folder = Path(folder or source.parent)
    folder.mkdir(parents=True, exist_ok=True)
    number = 1
    while True:
        target = folder / output_name(source, number)
        number += 1
        if _same_file(target, source):
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
