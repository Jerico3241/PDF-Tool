"""Arbeitsthread des PDF Readers/Editors, Zwischenspeicher der Seitenbilder und Bildquelle für QML.

* **Ein** Thread erledigt alle Zugriffe auf geöffnete Dokumente (pikepdf, PDFium) nacheinander –
  die Oberfläche bleibt frei, und kein Dokument wird gleichzeitig gelesen und geändert.
* Aufträge haben Prioritäten: Bearbeiten/Öffnen/Speichern (``EDIT``) vor sichtbaren Seiten
  (``VIEW``) vor Miniaturen (``THUMB``) vor Hintergrundarbeit wie der Suche (``BACKGROUND``). Lange
  Hintergrundarbeit gibt zwischendurch Vorrang (``urgent``) – Speichern wartet nie auf eine Suche.
  Bearbeitungen laufen in der Reihenfolge ihres Eingangs, Seitenbilder »zuletzt angefragt zuerst«
  (beim Scrollen zählen die gerade sichtbaren Seiten). Darstellungsaufträge lassen sich abbrechen –
  etwa wenn eine Seite aus dem Bild scrollt, bevor sie gerendert ist.
* Ergebnisse kommen über ein Qt-Signal im GUI-Thread an; Seitenbilder gehen direkt an QML
  (``image://pdfpage/…``, asynchron) und landen in einem begrenzten Zwischenspeicher.
* Nachtmodus: Die Kennung des Dokuments trägt dann ``~n`` (``image://pdfpage/d1~n/…``) – das Bild wird
  umgekehrt und abgemildert (``night_image``). Nur die Anzeige: Drucken und Export rendern ohne diesen Weg.
"""

from __future__ import annotations

import heapq
import itertools
import threading
import traceback
from collections import OrderedDict
from typing import Any, Callable

from PySide6.QtCore import QObject, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtQuick import QQuickAsyncImageProvider, QQuickImageResponse, QQuickTextureFactory

EDIT, VIEW, THUMB, BACKGROUND = 0, 1, 2, 3
THUMB_WIDTH = 120  # Breite der Miniaturen (Pixel)
CACHE_BYTES = 320 * 1024 * 1024  # Seitenbilder im Speicher (zuletzt benutzte bleiben)
NIGHT_TAG = "~n"  # Kennung + »~n«: Seitenbild im Nachtmodus
NIGHT_PAPER = "#1E1E1E"  # Papier im Nachtmodus (dunkelgrau statt Schwarz)
NIGHT_INK = "#E0E0E0"  # Schrift im Nachtmodus (hellgrau statt Weiß)


class Task:
    """Ein Auftrag; ``cancel()`` verhindert den Start (ein laufender Auftrag läuft zu Ende)."""

    __slots__ = ("priority", "func", "done", "error", "cancelled", "label", "finished", "result", "failure", "event")

    def __init__(self, priority: int, func: Callable[[], Any], done, error, label: str) -> None:
        self.priority = priority
        self.func = func
        self.done = done
        self.error = error
        self.label = label
        self.cancelled = False
        self.finished = False
        self.result = None
        self.failure: BaseException | None = None
        self.event = threading.Event()

    def cancel(self) -> None:
        self.cancelled = True


class Engine(QObject):
    """Warteschlange mit Prioritäten in einem eigenen Thread."""

    _deliver = Signal(object)
    busyChanged = Signal(bool)

    def __init__(self, parent: QObject | None = None, on_exception: Callable[[str], None] | None = None) -> None:
        super().__init__(parent)
        self._heap: list = []
        self._cv = threading.Condition()
        self._order = itertools.count()
        self._closed = False
        self._running: Task | None = None
        self._on_exception = on_exception
        self._deliver.connect(self._handle, Qt.ConnectionType.QueuedConnection)
        self._thread = threading.Thread(target=self._loop, name="pdftool-editor", daemon=True)
        self._thread.start()
        self.completed = 0  # erledigte Aufträge (Tests, Diagnose)

    # Aufträge ------------------------------------------------------------------------------------------------
    def submit(self, func: Callable[[], Any], done: Callable[[Any], None] | None = None, error: Callable[[BaseException, str], None] | None = None, *, priority: int = EDIT, label: str = "") -> Task:
        task = Task(priority, func, done, error, label)
        with self._cv:
            if self._closed:
                task.cancelled = True
                task.event.set()
                return task
            order = next(self._order)
            # Bearbeitungen und Hintergrundarbeit: in Reihenfolge; Bilder: zuletzt angefragt zuerst
            key = order if priority in (EDIT, BACKGROUND) else -order
            heapq.heappush(self._heap, (priority, key, order, task))
            self._cv.notify()
        return task

    def post(self, callback: Callable[..., None], *args: Any) -> None:
        """Aus dem Arbeitsthread: ``callback(*args)`` im GUI-Thread ausführen (Zwischenstände)."""
        relay = Task(BACKGROUND, lambda: None, lambda _result: callback(*args), None, "post")
        relay.finished = True
        try:
            self._deliver.emit((relay, ""))
        except RuntimeError:
            pass

    def wait(self, task: Task, timeout: float = 60.0) -> Any:
        """Auf einen Auftrag warten (Tests, Beenden) – nicht aus dem Arbeitsthread aufrufen."""
        if not task.event.wait(timeout):
            raise TimeoutError(task.label or "Auftrag")
        if task.failure is not None:
            raise task.failure
        return task.result

    def pending(self) -> int:
        with self._cv:
            return sum(1 for item in self._heap if not item[3].cancelled) + (1 if self._running is not None else 0)

    def idle(self) -> bool:
        return self.pending() == 0

    def urgent(self) -> bool:
        """Wartet ein Auftrag mit Vorrang vor Hintergrundarbeit (Speichern, Bearbeiten, sichtbare Seiten,
        Miniaturen)? Lange Hintergrundarbeit (Suche) unterbricht sich dann und läuft danach weiter."""
        with self._cv:
            return any(item[0] < BACKGROUND and not item[3].cancelled for item in self._heap)

    def shutdown(self, timeout: float = 5.0) -> None:
        with self._cv:
            self._closed = True
            for _priority, _key, _order, task in self._heap:
                task.cancelled = True
                task.event.set()
            self._heap.clear()
            self._cv.notify_all()
        if threading.current_thread() is not self._thread:
            self._thread.join(timeout)

    # Thread --------------------------------------------------------------------------------------------------
    def _loop(self) -> None:
        while True:
            with self._cv:
                while not self._heap and not self._closed:
                    self._cv.wait()
                if self._closed:
                    return
                _priority, _key, _order, task = heapq.heappop(self._heap)
                if task.cancelled:
                    task.event.set()
                    continue
                self._running = task
            try:
                task.result = task.func()
            except BaseException as exc:  # noqa: BLE001 - jeder Fehler geht an den Aufrufer
                task.failure = exc
                details = traceback.format_exc()
            else:
                details = ""
            finally:
                with self._cv:
                    self._running = None
                task.finished = True
                task.event.set()
            self.completed += 1
            try:
                self._deliver.emit((task, details))
            except RuntimeError:
                return  # Qt-Objekt beim Beenden schon gelöscht

    def _handle(self, payload) -> None:
        task, details = payload
        if task.cancelled:
            return
        try:
            if task.failure is not None:
                if task.error is not None:
                    task.error(task.failure, details)
                elif self._on_exception is not None:
                    self._on_exception(details)
            elif task.done is not None:
                task.done(task.result)
        except Exception:  # noqa: BLE001 - ein Fehler in einer Rückmeldung darf die App nicht beenden
            text = traceback.format_exc()
            if self._on_exception is not None:
                self._on_exception(text)
            else:
                traceback.print_exc()


# --- Seitenbilder ----------------------------------------------------------------------------------------------
class RenderCache:
    """Gerenderte Seiten als ``QImage`` – begrenzt auf ``limit`` Bytes, zuletzt benutzte bleiben.

    Schlüssel: ``(Dokument, Seite, Breite, Fassung, Art, Ausschnitt, Nachtmodus)`` – das Dokument steht vorn."""

    def __init__(self, limit: int = CACHE_BYTES) -> None:
        self.limit = limit
        self._items: OrderedDict[tuple, QImage] = OrderedDict()
        self._bytes = 0
        self._lock = threading.Lock()
        self._dropped: set[str] = set()  # geschlossene Dokumente (Kennungen werden nie wiederverwendet)

    def get(self, key: tuple) -> QImage | None:
        with self._lock:
            image = self._items.get(key)
            if image is not None:
                self._items.move_to_end(key)
            return image

    def put(self, key: tuple, image: QImage) -> None:
        size = image.sizeInBytes()
        if size > self.limit:
            return
        with self._lock:
            if key[0] in self._dropped:
                return  # Bild eines inzwischen geschlossenen Dokuments (war beim Schließen in Arbeit)
            old = self._items.pop(key, None)
            if old is not None:
                self._bytes -= old.sizeInBytes()
            self._items[key] = image
            self._bytes += size
            while self._bytes > self.limit and self._items:
                _key, dropped = self._items.popitem(last=False)
                self._bytes -= dropped.sizeInBytes()

    def drop(self, document: str) -> None:
        """Alle Bilder eines geschlossenen Dokuments entfernen – auch solche, die danach noch fertig werden."""
        with self._lock:
            self._dropped.add(document)
            for key in [key for key in self._items if key[0] == document]:
                self._bytes -= self._items.pop(key).sizeInBytes()

    def nearest(self, document: str, page: int, revision: int, kind: str, night: bool = False) -> QImage | None:
        """Irgendein vorhandenes Bild dieser Seite (andere Größe) – als Platzhalter beim Zoomen."""
        with self._lock:
            best = None
            for key, image in self._items.items():
                if key[0] == document and key[1] == page and key[3] == revision and key[4] == kind and (len(key) > 6 and bool(key[6])) == night:
                    if best is None or image.width() > best.width():
                        best = image
            return best

    @property
    def bytes(self) -> int:
        return self._bytes

    def __len__(self) -> int:
        return len(self._items)


def raster_to_qimage(raster) -> QImage:
    """PDFium-Raster (BGRx) → eigenständiges ``QImage`` (auch außerhalb des GUI-Threads erlaubt)."""
    image = QImage(raster.data, raster.width, raster.height, raster.stride, QImage.Format.Format_RGB32)
    return image.copy()


def night_image(image: QImage) -> QImage:
    """Seitenbild für den Nachtmodus (im Arbeitsthread erlaubt): Farben umkehren, danach Papier dunkelgrau
    (``NIGHT_PAPER``) statt Schwarz und Schrift hellgrau (``NIGHT_INK``) statt Weiß – angenehmer zu lesen.
    Ändert ``image`` selbst und gibt es zurück."""
    if image.isNull():
        return image
    image.invertPixels()
    painter = QPainter(image)
    try:
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Lighten)
        painter.fillRect(image.rect(), QColor(NIGHT_PAPER))
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Darken)
        painter.fillRect(image.rect(), QColor(NIGHT_INK))
    finally:
        painter.end()
    return image


class PageResponse(QQuickImageResponse):
    def __init__(self) -> None:
        super().__init__()
        self._image = QImage()
        self._error = ""
        self.task: Task | None = None

    def textureFactory(self):  # noqa: N802 - Qt-Schnittstelle
        return QQuickTextureFactory.textureFactoryForImage(self._image)

    def errorString(self) -> str:  # noqa: N802
        return self._error

    def cancel(self) -> None:
        if self.task is not None:
            self.task.cancel()

    def deliver(self, image: QImage | None, error: str = "") -> None:
        self._image = image if image is not None else QImage()
        self._error = error
        self.finished.emit()


class PageImageProvider(QQuickAsyncImageProvider):
    """``image://pdfpage/<dokument>/<seite>/<breite_px>/<stand>[/thumb]`` – ganze Seite bzw.
    Miniatur – und ``…/<stand>/region/<x0>/<y0>/<x1>/<y1>``: ein Ausschnitt (Anzeige-Punkte × 10)
    im Maßstab der Seitenbreite ``breite_px`` (scharfe Darstellung bei hohem Zoom). Bilder kommen
    aus dem Zwischenspeicher oder vom Arbeitsthread (abbrechbar, wenn QML sie nicht mehr braucht).
    Endet ``<dokument>`` auf ``~n`` (``NIGHT_TAG``), ist es das Bild für den Nachtmodus."""

    def __init__(self, render: Callable[..., Task | None], cache: RenderCache) -> None:
        super().__init__()
        self._render = render
        self._cache = cache

    def requestImageResponse(self, ident: str, requested: QSize):  # noqa: N802 - Qt-Schnittstelle
        response = PageResponse()
        try:
            parts = ident.split("/")
            document, page, width, revision = parts[0], int(parts[1]), int(parts[2]), int(parts[3])
            night = document.endswith(NIGHT_TAG)
            if night:
                document = document[: -len(NIGHT_TAG)]
            kind = parts[4] if len(parts) > 4 else "page"
            region = tuple(int(value) for value in parts[5:9]) if kind == "region" else ()
            if not document or kind not in ("page", "thumb", "region") or (kind == "region" and (len(region) != 4 or region[2] <= region[0] or region[3] <= region[1])):
                raise ValueError(kind)
        except (IndexError, ValueError):
            QTimer.singleShot(0, lambda: response.deliver(None, "Ungültige Bildadresse"))
            return response
        cached = self._cache.get((document, page, width, revision, kind, region, night))
        if cached is not None:
            # Erst nach der Rückkehr melden – sonst verpasst QML das Signal
            QTimer.singleShot(0, lambda: response.deliver(cached))
            return response
        response.task = self._render(document, page, width, revision, kind, region, response.deliver, night)
        if response.task is None:
            QTimer.singleShot(0, lambda: response.deliver(None, "Dokument nicht geöffnet"))
        return response
