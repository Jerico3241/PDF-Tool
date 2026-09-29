"""Voranalyse der Excel-Dateien eines Stapels – mit derselben Prüfung wie im Einzelmodus.

* ``analyze_file`` ruft ``engine.pruefe_excel`` auf (keine zweite Excel-Logik).
* ``AnalysisCache`` merkt sich Ergebnisse innerhalb der Sitzung: Ist eine Datei seit der
  letzten Prüfung unverändert (Größe und Änderungszeit), wird sie nicht erneut gelesen.
  Eine geänderte Datei wird immer neu geprüft – nie wird eine alte Analyse verwendet.
* ``Analyzer`` prüft nacheinander in genau einem Hintergrund-Thread (schonend für
  Arbeitsspeicher und Datenträger) und liefert Ergebnisse gebündelt an die Oberfläche,
  damit die Liste nicht Zeile für Zeile »nachploppt«.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from pathlib import Path
from typing import Callable

from ..overview import ExcelAnalysis
from .models import FileStamp, path_key

NOT_FOUND = "Datei nicht gefunden."


def analyze_file(path) -> tuple[ExcelAnalysis, FileStamp | None]:
    """Excel-Datei prüfen. Liefert das Ergebnis und den Stand der Datei *vor* dem Lesen.

    Ändert sich die Datei während des Lesens, passt der Stand später nicht mehr – sie wird
    dann vor dem Erstellen erneut geprüft.
    """
    stamp = FileStamp.of(path)
    if stamp is None or not Path(path).is_file():
        return ExcelAnalysis(ok=False, error=NOT_FOUND), None
    from engine import pruefe_excel

    try:
        result = pruefe_excel(Path(path), None)
    except Exception as exc:  # noqa: BLE001 - pruefe_excel meldet Lesefehler selbst; das hier ist der Rest
        text = str(exc).strip() or exc.__class__.__name__
        return ExcelAnalysis(ok=False, error=f"Die Datei konnte nicht geprüft werden ({text})."), stamp
    return ExcelAnalysis.from_result(result), stamp  # type: ignore[return-value]


class AnalysisCache:
    """Prüfergebnisse der Sitzung je Datei – gültig, solange Größe und Änderungszeit gleich sind."""

    def __init__(self) -> None:
        self._entries: dict[str, tuple[FileStamp, ExcelAnalysis]] = {}
        self._lock = threading.Lock()

    def get(self, path) -> tuple[ExcelAnalysis, FileStamp] | None:
        stamp = FileStamp.of(path)
        if stamp is None:
            return None
        with self._lock:
            entry = self._entries.get(path_key(path))
        if entry is None or entry[0] != stamp:
            return None
        return entry[1], stamp

    def put(self, path, stamp: FileStamp | None, analysis: ExcelAnalysis) -> None:
        if stamp is None:
            return
        with self._lock:
            self._entries[path_key(path)] = (stamp, analysis)

    def forget(self, path) -> None:
        with self._lock:
            self._entries.pop(path_key(path), None)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)


def analyze_cached(path, cache: AnalysisCache | None) -> tuple[ExcelAnalysis, FileStamp | None]:
    if cache is not None:
        cached = cache.get(path)
        if cached is not None:
            return cached
    analysis, stamp = analyze_file(path)
    if cache is not None and analysis.ok:
        cache.put(path, stamp, analysis)
    return analysis, stamp


Result = tuple[str, ExcelAnalysis, "FileStamp | None"]  # (Eintrag, Ergebnis, Stand)


class Analyzer:
    """Prüft Dateien nacheinander in einem Hintergrund-Thread.

    ``submit`` nimmt weitere Dateien auch während einer laufenden Prüfung an – es läuft
    nie mehr als ein Prüf-Thread. Ergebnisse gehen höchstens alle ``FLUSH_S`` Sekunden
    gesammelt an ``deliver`` (über ``post`` im Thread der Oberfläche).

    ``start`` startet eine Funktion im Hintergrund (in der App: ``worker.run``), ``post``
    ruft eine Funktion im Thread der Oberfläche auf (``worker.post``).
    """

    FLUSH_S = 0.25

    def __init__(
        self,
        cache: AnalysisCache,
        start: Callable[[Callable[[], None]], None],
        post: Callable[..., None],
        deliver: Callable[[list[Result]], None],
        analyze: Callable[[str, AnalysisCache], tuple[ExcelAnalysis, FileStamp | None]] = analyze_cached,
    ) -> None:
        self.cache = cache
        self._start = start
        self._post = post
        self._deliver = deliver
        self._analyze = analyze
        self._pending: deque[tuple[str, str]] = deque()
        self._lock = threading.Lock()
        self._running = False
        self._generation = 0  # »clear« verwirft laufende Ergebnisse

    def submit(self, entries: list[tuple[str, str]]) -> None:
        """Einträge (ID, Pfad) zur Prüfung anmelden."""
        if not entries:
            return
        with self._lock:
            self._pending.extend(entries)
            if self._running:
                return
            self._running = True
        self._start(self._loop)

    def clear(self) -> None:
        """Ausstehende Prüfungen verwerfen (z. B. »Neuer Stapel«)."""
        with self._lock:
            self._pending.clear()
            self._generation += 1

    def busy(self) -> bool:
        with self._lock:
            return self._running

    def pending(self) -> int:
        with self._lock:
            return len(self._pending)

    def _loop(self) -> None:
        completed = False
        try:
            self._run()  # endet erst, wenn nichts mehr aussteht (und gibt dann »läuft« frei)
            completed = True
        finally:
            if not completed:
                # Unerwarteter Fehler: die übrigen Dateien trotzdem prüfen – in einem neuen Thread.
                with self._lock:
                    self._running = bool(self._pending)
                    restart = self._running
                if restart:
                    self._start(self._loop)

    def _run(self) -> None:
        results: list[Result] = []
        last = time.monotonic()
        generation = self._generation
        while True:
            with self._lock:
                if generation != self._generation:
                    results = []
                    generation = self._generation
                if not self._pending:
                    self._running = False
                    break
                item_id, path = self._pending.popleft()
            try:
                analysis, stamp = self._analyze(path, self.cache)
            except Exception as exc:  # noqa: BLE001 - eine Datei darf die Prüfung der anderen nie stoppen
                analysis, stamp = ExcelAnalysis(ok=False, error=f"Die Datei konnte nicht geprüft werden ({exc})."), None
            results.append((item_id, analysis, stamp))
            if time.monotonic() - last >= self.FLUSH_S:
                self._flush(results, generation)
                results = []
                last = time.monotonic()
        self._flush(results, generation)

    def _flush(self, results: list[Result], generation: int) -> None:
        if not results:
            return
        with self._lock:
            if generation != self._generation:
                return
        self._post(self._deliver, list(results))
