"""Live-Vorschau der Vertragsübersicht (in QML: ``Preview``).

Die Vorschau erzeugt die PDF genau wie »PDF erstellen« (``engine.erstelle_pdf``) – nur in einen
privaten temporären Ordner – und zeigt ihre Seiten als Bild (PDFium). Die Pipeline ist dieselbe
wie bis 2.6 (``tools.contract_overview.preview``):

* Änderungen markieren die Vorschau als veraltet. Neu erzeugt wird verzögert (Entprellung) und
  nur, solange die Ansicht »Vorschau« sichtbar ist.
* Eine Signatur aller Eingaben (samt Änderungszeit von Excel und Logo) verhindert unnötige Läufe;
  ein Ergebnis wird nur angezeigt, wenn es noch zur aktuellen Signatur passt.
* Gerenderte Seiten liegen als ``QImage`` im Zwischenspeicher und gehen direkt an QML
  (``image://preview/…`` – keine Umwege über Dateien). Erneutes Öffnen, Tab- oder Designwechsel
  rendern nichts neu.
* Zoom: feste Stufen, »An Breite anpassen« und »Ganze Seite«; gerendert wird in Gerätepixeln.
"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict

from PySide6.QtCore import Property, QObject, Signal, Slot
from PySide6.QtGui import QImage

from tools.contract_overview.preview import (
    A4_POINTS,
    CACHE_PAGES,
    DEBOUNCE_MS,
    MAX_SCALE,
    PLACEHOLDER_KD,
    ZOOMS,
    PreviewDocument,
    expected_page,
    signature,
    sweep_stale_folders,
)
from tools.contract_overview.preview import RENDER_LOCK

from ..base import Observable, prop
from ..images import pil_to_qimage

MARGIN = 16  # Rand um die Seite (geräteunabhängige Pixel)
PT_TO_PX = 96 / 72  # 100 % = Originalgröße bei 96 dpi
FIT_WIDTH = "width"
FIT_PAGE = "page"
EMPTY_TITLE = "Noch keine Vorschau"
EMPTY_HINT = "Die Vorschau erscheint, sobald eine geprüfte Excel-Liste mit aktiven Verträgen und ein Logo vorliegen. Eine fehlende Kundennummer steht hier als »–«."


def _close_locked(doc: PreviewDocument) -> None:
    with RENDER_LOCK:
        doc.close()


class PreviewController(Observable):
    """Vorschau: erzeugen, zwischenspeichern, blättern, zoomen."""

    stateChanged, state = prop(str, "state", "empty")  # empty, busy, stale, current, error
    stateTextChanged, stateText = prop(str, "stateText", "")
    problemChanged, problem = prop(str, "problem", "")
    pagesChanged, pages = prop(int, "pages", 0)
    pageChanged, page = prop(int, "page", 0)
    zoomTextChanged, zoomText = prop(str, "zoomText", "An Breite")
    fitChanged, fit = prop(str, "fit", FIT_WIDTH)  # width, page oder "" (feste Zoomstufe)
    imageSourceChanged, imageSource = prop(str, "imageSource", "")
    pageWidthChanged, pageWidth = prop(float, "pageWidth", 0.0)  # angezeigte Größe (geräteunabhängig)
    pageHeightChanged, pageHeight = prop(float, "pageHeight", 0.0)
    canPrevChanged, canPrev = prop(bool, "canPrev", False)
    canNextChanged, canNext = prop(bool, "canNext", False)

    def __init__(self, app, tool, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.app = app
        self.tool = tool
        self.c = None
        self._doc: PreviewDocument | None = None
        self._signature: tuple | None = None
        self._building: tuple | None = None  # Signatur der laufenden Erzeugung
        self._again = False
        self._zoom: float | None = None  # feste Zoomstufe; None: an Breite bzw. Seite anpassen
        self._view: tuple | None = None  # (Dokument, Seite, Maßstab) der laufenden Anzeige
        self._images: OrderedDict[tuple[int, int, float], QImage] = OrderedDict()
        self._item: str | None = None  # Stapel-Eintrag, dessen Vorschau gezeigt wird (sonst die Übersicht)
        self._viewport = (800.0, 600.0, 1.0)  # Breite, Höhe, Gerätepixelverhältnis
        self._reserved: tuple[float, float] | None = None  # Seitenmaß (pt), für das die erste Vorschau Platz hält
        self._closing = False
        self.runs = 0  # erzeugte Vorschauen (Tests, Diagnose)
        self.renders = 0  # gerenderte Seitenbilder
        threading.Thread(target=sweep_stale_folders, name="vorschau-aufraeumen", daemon=True).start()

    def attach(self, overview) -> None:
        self.c = overview

    # Bildquelle für QML -----------------------------------------------------------------
    def lookup(self, ident: str) -> QImage | None:
        """``image://preview/<token>/<seite>/<maßstab>`` → gerendertes Bild (nur aus dem Zwischenspeicher)."""
        try:
            token, index, scale = ident.split("/")[:3]
            key = (int(token), int(index), round(float(scale), 3))
        except ValueError:
            return None
        return self._images.get(key)

    # Auslöser --------------------------------------------------------------------------------
    def shown(self) -> bool:
        return self.app.currentPage == "preview"

    def mark_dirty(self) -> None:
        """Eine Eingabe hat sich geändert: Vorschau verzögert neu erzeugen, solange sie sichtbar ist."""
        if not self.shown():
            return
        self.app.timers.later("preview:refresh", DEBOUNCE_MS, self.refresh)
        if self._doc is not None and self._building is None:
            self._set_state("stale")

    def page_prepare(self) -> None:
        """Ansicht »Vorschau« wird geöffnet: sofort prüfen, ob die Vorschau noch aktuell ist."""
        self.app.timers.cancel("preview:refresh")
        self._show_source()
        self.refresh()

    def page_left(self) -> None:
        """Ansicht verlassen: beim nächsten Öffnen wieder die Übersicht (nicht den Stapel-Eintrag)."""
        if self._item is not None:
            self._item = None
            self._show_source()

    def show_batch_item(self, item_id: str) -> None:
        """Aus dem Stapel: die Vorschau genau dieses Eintrags zeigen."""
        self._item = item_id
        if self.app.currentPage == "preview":
            self._show_source()
            self.refresh()
        else:
            self.app.navigate("preview")

    def _show_source(self) -> None:
        batch = self.tool.batch
        item = batch.item(self._item) if (self._item and batch is not None) else None
        if item is None:
            self._item = None
            self.app.hide_notice("preview_source", animate=False)
            return
        res = batch.resolution(item.id)
        who = f" – {res.customer.label}" if res is not None and res.customer is not None else (f" – {res.company or res.number}" if res is not None and (res.company or res.number) else "")
        self.app.notify(
            "preview_source",
            "info",
            f"„{item.name}“{who}. Die Vorschau zeigt diesen Eintrag genau so, wie der Stapel ihn erstellt.",
            title="Stapel-Eintrag",
            actions=(("Zurück zum Stapel", self._back_to_batch), ("Übersicht anzeigen", self._single)),
            status=False,
            animate=False,
        )

    def _back_to_batch(self) -> None:
        item_id = self._item
        self.app.navigate("batch")
        if item_id and self.tool.batch is not None:
            self.tool.batch.show_detail(item_id)

    def _single(self) -> None:
        self._item = None
        self._show_source()
        self.refresh()

    # Erzeugen ----------------------------------------------------------------------------------
    def fields(self) -> tuple[dict | None, str]:
        """Eingaben der Vorschau – dieselben wie für »PDF erstellen«. Ohne Voraussetzung: Grund.

        Aus dem Stapel geöffnet: der Auftrag dieses Eintrags – dieselbe Pipeline.
        """
        if self._item is not None and self.tool.batch is not None:
            return self.tool.batch.preview_fields(self._item)
        c = self.c
        blocking = [(area, text) for area, text in c.readiness() if area in ("excel", "busy", "logo", "breite")]
        if blocking:
            return None, blocking[0][1]
        try:
            breite = float(c.breite.replace(",", "."))
        except ValueError:
            return None, "Logo-Breite ungültig"
        kd = c.kd.strip() or PLACEHOLDER_KD
        empfaenger = c.mail.strip()
        return c.pdf_fields(kd, empfaenger, breite), ""

    @Slot()
    def refreshNow(self) -> None:  # noqa: N802
        """»Aktualisieren«: Vorschau neu erzeugen (z. B. nach Änderungen an der Excel-Datei)."""
        self.refresh(force=True)

    def refresh(self, force: bool = False) -> None:
        fields, problem = self.fields()
        if fields is None:
            self.problem = problem
            self._set_state("empty")
            return
        self.problem = ""
        wanted = signature(fields)
        if self._building is not None:
            if wanted != self._building:
                self._again = True  # nach der laufenden Erzeugung erneut
            return
        if not force and wanted == self._signature and self._doc is not None:
            self._set_state("current")
            self._show_page()
            return
        self._building = wanted
        self._again = False
        self._set_state("busy")
        if self._doc is None:
            # Erste Vorschau: Platz für die Seite schon jetzt freihalten – kein Sprung, wenn sie erscheint.
            self._reserved = expected_page(fields)
            self._update_reserved()
        self.app.worker.run(lambda: PreviewDocument.build(fields), lambda doc: self._built(wanted, doc), lambda exc, tb: self._failed(wanted, exc, tb))

    def _built(self, built: tuple, doc: PreviewDocument) -> None:
        self._building = None
        if self._closing:
            doc.close()
            return
        fields, _problem = self.fields()
        current = signature(fields) if fields is not None else None
        if current != built:
            # Inzwischen geändert (z. B. Kunde A → B): dieses Ergebnis nie anzeigen.
            doc.close()
            self.refresh()
            return
        old, self._doc = self._doc, doc
        self._reserved = None
        if old is not None:
            self.app.worker.run(lambda: _close_locked(old))  # eine laufende Seitenanzeige endet zuerst
        self._signature = built
        self._images.clear()
        self.runs += 1
        self.pages = doc.pages
        self.page = max(0, min(self.page, doc.pages - 1))
        self._set_state("current")
        self._show_page()
        if self._again:
            self._again = False
            self.refresh()

    def _failed(self, built: tuple, exc: BaseException, tb: str) -> None:
        self._building = None
        if self._closing:
            return
        fields, _problem = self.fields()
        if fields is None or signature(fields) != built:
            self.refresh()
            return
        self.app.write_error_log(tb)
        self.problem = str(exc) or exc.__class__.__name__
        self._set_state("error")

    # Anzeigen ----------------------------------------------------------------------------------
    @Slot(float, float, float)
    def setViewport(self, width: float, height: float, ratio: float) -> None:  # noqa: N802
        """Verfügbare Fläche der Ansicht (aus QML). Beim Anpassen an Breite/Seite wird entprellt neu gerendert."""
        viewport = (max(1.0, float(width)), max(1.0, float(height)), max(0.5, float(ratio) or 1.0))
        if viewport == self._viewport:
            return
        previous, self._viewport = self._viewport, viewport
        if self._doc is None:
            if self._building is not None:
                # Die erste Vorschau entsteht noch (vorbereitet, bevor die Ansicht ihre Größe kannte):
                # den freigehaltenen Platz an die echte Fläche anpassen.
                self._update_reserved()
        elif self.shown():
            if self._zoom is None:
                self._update_size()
                self.app.timers.later("preview:fit", 120, self._show_page)
            elif viewport[2] != previous[2]:
                self.app.timers.later("preview:fit", 120, self._show_page)

    def _logical_scale(self, width_pt: float, height_pt: float) -> float:
        """Geräteunabhängige Pixel je Punkt für die aktuelle Zoomeinstellung."""
        view_w, view_h, _ratio = self._viewport
        if self._zoom is not None:
            return self._zoom * PT_TO_PX
        available_w = max(200.0, view_w - 2 * MARGIN)
        if self.fit == FIT_PAGE:
            available_h = max(200.0, view_h - 2 * MARGIN)
            return min(available_w / width_pt, available_h / height_pt)
        return available_w / width_pt

    def _page_size(self, index: int) -> tuple[float, float]:
        doc = self._doc
        if doc is None or not doc.sizes:
            return A4_POINTS
        width_pt, height_pt = doc.sizes[max(0, min(index, doc.pages - 1))]
        return (width_pt or A4_POINTS[0], height_pt or A4_POINTS[1])

    def _update_reserved(self) -> None:
        if self._reserved is None:
            return
        width_pt, height_pt = self._reserved
        scale = self._logical_scale(width_pt, height_pt)
        self.pageWidth, self.pageHeight = width_pt * scale, height_pt * scale

    def _update_size(self) -> None:
        width_pt, height_pt = self._page_size(self.page)
        scale = self._logical_scale(width_pt, height_pt)
        self.pageWidth, self.pageHeight = width_pt * scale, height_pt * scale

    def _show_page(self) -> None:
        doc = self._doc
        if doc is None or not doc.pages:
            return
        index = max(0, min(self.page, doc.pages - 1))
        self.page = index
        width_pt, height_pt = self._page_size(index)
        logical = self._logical_scale(width_pt, height_pt)
        render_scale = round(min(MAX_SCALE, logical * self._viewport[2]), 3)
        key = (doc.token, index, render_scale)
        self.pageWidth, self.pageHeight = width_pt * logical, height_pt * logical
        self._update_tools()
        if key in self._images:
            self._images.move_to_end(key)
            self._view = None
            self.imageSource = f"image://preview/{doc.token}/{index}/{render_scale}"
            return
        if self._view == key:
            return
        self._view = key

        def work() -> QImage:
            return pil_to_qimage(doc.render_image(index, render_scale))

        def done(image: QImage) -> None:
            if self._view != key or self._doc is not doc:
                return  # inzwischen andere Seite, anderer Maßstab oder neue Vorschau
            self._view = None
            self.renders += 1
            self._images[key] = image
            while len(self._images) > CACHE_PAGES:
                self._images.popitem(last=False)
            self.imageSource = f"image://preview/{doc.token}/{index}/{render_scale}"

        def failed(exc, tb) -> None:
            if self._view == key:
                self._view = None
                self.app.write_error_log(tb)
                self.problem = str(exc) or exc.__class__.__name__
                self._set_state("error")

        self.app.worker.run(work, done, failed)

    @Slot(int)
    def step(self, delta: int) -> None:
        doc = self._doc
        if doc is None:
            return
        target = max(0, min(doc.pages - 1, self.page + int(delta)))
        if target != self.page:
            self.page = target
            self._show_page()

    @Slot(int)
    def goTo(self, index: int) -> None:  # noqa: N802
        self.step(int(index) - self.page)

    @Slot()
    def zoomIn(self) -> None:  # noqa: N802
        self._zoom_step(1)

    @Slot()
    def zoomOut(self) -> None:  # noqa: N802
        self._zoom_step(-1)

    def _zoom_step(self, direction: int) -> None:
        current = self._zoom
        if current is None:
            width_pt, height_pt = self._page_size(self.page)
            current = self._logical_scale(width_pt, height_pt) / PT_TO_PX
        if direction > 0:
            bigger = [zoom for zoom in ZOOMS if zoom > current + 0.01]
            self._zoom = bigger[0] if bigger else ZOOMS[-1]
        else:
            smaller = [zoom for zoom in ZOOMS if zoom < current - 0.01]
            self._zoom = smaller[-1] if smaller else ZOOMS[0]
        self.fit = ""
        self._show_page()

    @Slot()
    def fitWidth(self) -> None:  # noqa: N802
        self._zoom = None
        self.fit = FIT_WIDTH
        self._show_page()

    @Slot()
    def fitPage(self) -> None:  # noqa: N802
        self._zoom = None
        self.fit = FIT_PAGE
        self._show_page()

    def _update_tools(self) -> None:
        pages = self._doc.pages if self._doc is not None else 0
        self.pages = pages
        self.canPrev = pages > 0 and self.page > 0
        self.canNext = pages > 0 and self.page < pages - 1
        if self._zoom is not None:
            self.zoomText = f"{round(self._zoom * 100)} %"
        else:
            self.zoomText = "Ganze Seite" if self.fit == FIT_PAGE else "An Breite"

    def _set_state(self, state: str) -> None:
        self.state = state
        c = self.c
        if state == "empty":
            self.stateText = ""
            self.app.hide_notice("preview_info")
        elif state == "busy":
            self.stateText = "Vorschau wird erstellt …"
        elif state == "stale":
            self.stateText = "Änderungen – Vorschau wird aktualisiert …"
        elif state == "current":
            doc = self._doc
            placeholder = c is not None and self._item is None and c.kd.strip() == "" and doc is not None
            note = f" · Kundennummer fehlt (in der Vorschau »{PLACEHOLDER_KD}«)" if placeholder else ""
            # Zeit der Erzeugung – ein erneutes Öffnen ohne Änderung erzeugt nichts neu und ändert nichts.
            built = time.localtime(doc.created) if doc is not None else time.localtime()
            self.stateText = f"Aktuell · {time.strftime('%H:%M:%S', built)}{note}"
            self.app.hide_notice("preview_info")
        elif state == "error":
            self.stateText = "Vorschau nicht möglich"
            if self._doc is None:
                self._reserved = None
                self.pageWidth, self.pageHeight = 0.0, 0.0  # kein leerer Seitenrahmen unter der Fehlermeldung
            self.app.notify("preview_info", "error", self.problem or "Unbekannter Fehler", title="Vorschau konnte nicht erstellt werden", status=False)
        self._update_tools()

    def close(self) -> None:
        self._closing = True
        doc, self._doc = self._doc, None
        self._images.clear()
        if doc is not None:
            with RENDER_LOCK:
                doc.close()

    def _texts(self) -> dict:
        return {"emptyTitle": EMPTY_TITLE, "emptyHint": EMPTY_HINT}

    _constant = Signal()
    texts = Property("QVariantMap", _texts, notify=_constant)
