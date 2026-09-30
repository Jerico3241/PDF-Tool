"""Live-Vorschau der Vertragsübersicht.

Die Vorschau erzeugt die PDF genau wie »PDF erstellen« (``engine.erstelle_pdf``) – nur in
einen privaten temporären Ordner – und zeigt ihre Seiten als Bild (PDFium):

* Änderungen markieren die Vorschau als veraltet. Neu erzeugt wird verzögert (Entprellung)
  und nur, solange die Ansicht »Vorschau« sichtbar ist.
* Eine Signatur aller Eingaben (samt Änderungszeit von Excel und Logo) verhindert unnötige
  Läufe. Ein Ergebnis wird nur angezeigt, wenn es noch zur aktuellen Signatur passt – ein
  schneller Wechsel (Kunde A → B) zeigt nie ein veraltetes Bild.
* ``RENDER_LOCK`` serialisiert PDF-Erzeugung und PDFium (nicht threadsicher); auch
  »PDF erstellen« nimmt diese Sperre.
* Temporäre Dateien werden beim Ersetzen und beim Beenden gelöscht; nichts landet im Zielordner.
"""

from __future__ import annotations

import base64
import io
import json
import shutil
import tempfile
import threading
import time
from dataclasses import dataclass, field
from itertools import count
from pathlib import Path

RENDER_LOCK = threading.Lock()
DEBOUNCE_MS = 450
ZOOMS = (0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 3.0)
MAX_SCALE = 4.0  # PDFium-Pixel je Punkt – begrenzt den Speicherbedarf
CACHE_PAGES = 6
PLACEHOLDER_KD = "–"
FOLDER_PREFIX = "pdf-tool-vorschau-"
STALE_AFTER = 12 * 3600  # verwaiste Vorschau-Ordner (z. B. nach einem Absturz) nach 12 Stunden entfernen
_TOKENS = count(1)


@dataclass
class PreviewDocument:
    """Eine erzeugte Vorschau-PDF im eigenen temporären Ordner."""

    folder: Path
    path: Path
    sizes: list[tuple[float, float]]  # Seitengröße in Punkt
    token: int = field(default_factory=lambda: next(_TOKENS))
    created: float = field(default_factory=time.time)

    @property
    def pages(self) -> int:
        return len(self.sizes)

    @classmethod
    def build(cls, fields: dict) -> "PreviewDocument":
        """PDF erzeugen (Hintergrund-Thread). Wirft dieselben Fehler wie »PDF erstellen«."""
        from engine import PdfAuftrag, erstelle_pdf

        folder = Path(tempfile.mkdtemp(prefix=FOLDER_PREFIX))
        try:
            with RENDER_LOCK:
                path = erstelle_pdf(PdfAuftrag(**{**fields, "zielordner": folder, "dateiname": "vorschau.pdf", "pdf_oeffnen": False}))
                sizes = _page_sizes(path)
        except BaseException:
            shutil.rmtree(folder, ignore_errors=True)
            raise
        return cls(folder, Path(path), sizes)

    def render(self, index: int, scale: float) -> tuple[bytes, int, int]:
        """Seite als PNG (Base64) – im Hintergrund kodiert, damit die Oberfläche flüssig bleibt."""
        import pypdfium2 as pdfium

        scale = max(0.1, min(MAX_SCALE, scale))
        with RENDER_LOCK:
            doc = pdfium.PdfDocument(str(self.path))
            try:
                page = doc[index]
                try:
                    bitmap = page.render(scale=scale)
                    try:
                        image = bitmap.to_pil().convert("RGB")
                    finally:
                        bitmap.close()
                finally:
                    page.close()
            finally:
                doc.close()
        buffer = io.BytesIO()
        image.save(buffer, format="PNG", compress_level=1)
        return base64.b64encode(buffer.getvalue()), image.width, image.height

    def close(self) -> None:
        shutil.rmtree(self.folder, ignore_errors=True)


def sweep_stale_folders(now: float | None = None) -> int:
    """Vorschau-Ordner früherer Sitzungen entfernen, die älter als ``STALE_AFTER`` sind."""
    now = time.time() if now is None else now
    removed = 0
    for folder in Path(tempfile.gettempdir()).glob(FOLDER_PREFIX + "*"):
        try:
            if folder.is_dir() and now - folder.stat().st_mtime > STALE_AFTER:
                shutil.rmtree(folder, ignore_errors=True)
                removed += 1
        except OSError:
            continue
    return removed


def _close_locked(doc: PreviewDocument) -> None:
    with RENDER_LOCK:
        doc.close()


def _page_sizes(path: Path) -> list[tuple[float, float]]:
    import pypdfium2 as pdfium

    doc = pdfium.PdfDocument(str(path))
    try:
        return [tuple(doc.get_page_size(index)) for index in range(len(doc))]  # type: ignore[misc]
    finally:
        doc.close()


def signature(fields: dict) -> tuple:
    """Vergleichswert aller Eingaben; Dateien mit Änderungszeit und Größe."""
    items = []
    for key in sorted(fields):
        value = fields[key]
        if key in ("excel", "logo"):
            try:
                stat = Path(value).stat()
                value = (str(value), stat.st_mtime_ns, stat.st_size)
            except OSError:
                value = (str(value), None, None)
        items.append((key, json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)))
    return tuple(items)


class PreviewFlow:
    """Ablauf der Vorschau (Baustein des Hauptfensters, Teil von »Vertragsübersichten«)."""

    def _init_preview(self) -> None:
        self._preview_doc: PreviewDocument | None = None
        self._preview_signature: tuple | None = None
        self._preview_building: tuple | None = None  # Signatur der laufenden Erzeugung
        self._preview_again = False
        self._preview_page = 0
        self._preview_zoom: float | None = None  # None: an Breite anpassen
        self._preview_view: tuple | None = None  # (Dokument, Seite, Maßstab) der laufenden Anzeige
        self._preview_images: dict[tuple[int, int, float], tuple[bytes, int, int]] = {}
        self._preview_problem = ""
        self._preview_item: str | None = None  # Stapel-Eintrag, dessen Vorschau gezeigt wird (sonst die Übersicht)
        self.preview_runs = 0  # erzeugte Vorschauen (Tests, Diagnose)
        threading.Thread(target=sweep_stale_folders, name="vorschau-aufraeumen", daemon=True).start()

    # Auslöser ------------------------------------------------------------------------------
    def mark_preview_dirty(self) -> None:
        """Eine Eingabe hat sich geändert: Vorschau verzögert neu erzeugen, solange sie sichtbar ist."""
        if getattr(self, "nav", None) is None or self.nav.current != "preview":
            return
        self.ctx.anim.later("preview:refresh", DEBOUNCE_MS, self.refresh_preview)
        if self._preview_doc is not None and self._preview_building is None:
            self._preview_status("stale")

    def preview_shown(self) -> None:
        """Ansicht »Vorschau« geöffnet: sofort prüfen, ob die Vorschau noch aktuell ist."""
        self.ctx.anim.cancel_later("preview:refresh")
        self._show_preview_source()
        self.refresh_preview()

    def preview_left(self) -> None:
        """Ansicht »Vorschau« verlassen: beim nächsten Öffnen wieder die Übersicht (nicht den Stapel-Eintrag)."""
        if self._preview_item is not None:
            self._preview_item = None
            self._show_preview_source()

    def _show_preview_source(self) -> None:
        item = self.batch_by_id.get(self._preview_item) if self._preview_item else None
        if item is None:
            self._preview_item = None
            self.hide_notice("preview_source")
            return
        res = self.batch_resolution(item.id)
        who = f" – {res.customer.label}" if res is not None and res.customer is not None else (f" – {res.company or res.number}" if res is not None and (res.company or res.number) else "")
        self.notify(
            "preview_source",
            "info",
            f"„{item.name}“{who}. Die Vorschau zeigt diesen Eintrag genau so, wie der Stapel ihn erstellt.",
            title="Stapel-Eintrag",
            actions=(("Zurück zum Stapel", self._preview_back_to_batch), ("Übersicht anzeigen", self._preview_single)),
            status=False,
            animate=False,
        )

    def _preview_back_to_batch(self) -> None:
        item_id = self._preview_item
        self.nav.navigate("batch")
        if item_id and self.batch_page is not None:
            self.batch_page.show_detail(item_id)

    def _preview_single(self) -> None:
        self._preview_item = None
        self._show_preview_source()
        self.refresh_preview()

    # Erzeugen --------------------------------------------------------------------------------
    def _preview_fields(self) -> tuple[dict | None, str]:
        """Eingaben der Vorschau – dieselben wie für »PDF erstellen«. Ohne Voraussetzung: Grund.

        Aus dem Stapel geöffnet (``_preview_item``): der Auftrag dieses Eintrags – dieselbe Pipeline.
        """
        if getattr(self, "_preview_item", None) is not None:
            return self.batch_preview_fields(self._preview_item)
        blocking = [(area, text) for area, text in self.readiness() if area in ("excel", "busy", "logo", "breite")]
        if blocking:
            return None, blocking[0][1]
        try:
            breite = float(self.var_breite.get().replace(",", "."))
        except ValueError:
            return None, "Logo-Breite ungültig"
        kd = self.var_kd.get().strip() or PLACEHOLDER_KD
        empfaenger = self.var_mail.get().strip()
        return self._pdf_fields(kd, empfaenger, breite), ""

    def refresh_preview(self, force: bool = False) -> None:
        if getattr(self, "ui", None) is None or getattr(self.ui, "preview_canvas", None) is None:
            return
        fields, problem = self._preview_fields()
        if fields is None:
            self._preview_problem = problem
            self._preview_status("empty")
            return
        self._preview_problem = ""
        wanted = signature(fields)
        if self._preview_building is not None:
            if wanted != self._preview_building:
                self._preview_again = True  # nach der laufenden Erzeugung erneut
            return
        if not force and wanted == self._preview_signature and self._preview_doc is not None:
            self._preview_status("current")
            self._show_preview_page()
            return
        self._preview_building = wanted
        self._preview_again = False
        self._preview_status("busy")
        self.worker.run(lambda: PreviewDocument.build(fields), lambda doc: self._preview_built(wanted, doc), lambda exc, tb: self._preview_failed(wanted, exc, tb))

    def _preview_built(self, built: tuple, doc: PreviewDocument) -> None:
        self._preview_building = None
        if getattr(self, "_closing", False):
            doc.close()
            return
        fields, _problem = self._preview_fields()
        current = signature(fields) if fields is not None else None
        if current != built:
            # Inzwischen geändert (z. B. Kunde A → B): dieses Ergebnis nie anzeigen.
            doc.close()
            self.refresh_preview()
            return
        old, self._preview_doc = self._preview_doc, doc
        if old is not None:
            self.worker.run(lambda: _close_locked(old))  # eine laufende Seitenanzeige endet zuerst
        self._preview_signature = built
        self._preview_images.clear()
        self.preview_runs += 1
        from ui import diagnostics

        diagnostics.count("preview_render")
        self._preview_page = max(0, min(self._preview_page, doc.pages - 1))
        self._preview_status("current")
        self._show_preview_page()
        if self._preview_again:
            self._preview_again = False
            self.refresh_preview()

    def _preview_failed(self, built: tuple, exc: BaseException, tb: str) -> None:
        self._preview_building = None
        if getattr(self, "_closing", False):
            return
        fields, _problem = self._preview_fields()
        if fields is None or signature(fields) != built:
            self.refresh_preview()
            return
        self.write_error_log(tb)
        self._preview_problem = str(exc) or exc.__class__.__name__
        self._preview_status("error")

    # Anzeigen ----------------------------------------------------------------------------------
    def _preview_scale(self, doc: PreviewDocument, index: int) -> float:
        from ui.theme import px

        width_pt = doc.sizes[index][0] or 595.0
        if self._preview_zoom is None:
            available = max(px(200), self.ui.preview_canvas.view_width() - 2 * self.ui.preview_canvas.MARGIN)
            return round(available / width_pt, 3)
        return round(px(width_pt * 96 / 72 * self._preview_zoom) / width_pt, 3)

    def _show_preview_page(self) -> None:
        doc = self._preview_doc
        canvas = getattr(self.ui, "preview_canvas", None)
        if doc is None or canvas is None or not doc.pages:
            return
        index = max(0, min(self._preview_page, doc.pages - 1))
        self._preview_page = index
        if canvas.winfo_width() <= 1:
            canvas.update_idletasks()  # gerade eingeblendet: erst die echte Breite kennen
        scale = min(MAX_SCALE, self._preview_scale(doc, index))
        key = (doc.token, index, scale)
        self._update_preview_tools()
        cached = self._preview_images.get(key)
        if cached is not None:
            self._preview_view = None
            canvas.show(*cached, page=(doc.token, index))
            return
        if self._preview_view == key:
            return
        self._preview_view = key
        # Platz für die Seite schon jetzt freihalten: Das Bild erscheint ohne Layoutsprung.
        width_pt, height_pt = doc.sizes[index]
        canvas.reserve(int(round(width_pt * scale)), int(round(height_pt * scale)))

        def done(result) -> None:
            if self._preview_view != key or self._preview_doc is not doc:
                return  # inzwischen andere Seite, anderer Maßstab oder neue Vorschau
            self._preview_view = None
            self._preview_images[key] = result
            while len(self._preview_images) > CACHE_PAGES:
                self._preview_images.pop(next(iter(self._preview_images)))
            canvas.show(*result, page=(doc.token, index))

        def failed(exc, tb) -> None:
            if self._preview_view == key:
                self._preview_view = None
                self.write_error_log(tb)
                self._preview_problem = str(exc) or exc.__class__.__name__
                self._preview_status("error")

        self.worker.run(lambda: doc.render(index, scale), done, failed)

    def preview_step(self, delta: int) -> None:
        doc = self._preview_doc
        if doc is None:
            return
        target = max(0, min(doc.pages - 1, self._preview_page + delta))
        if target != self._preview_page:
            self._preview_page = target
            self._show_preview_page()
            canvas = getattr(self.ui, "preview_canvas", None)
            if canvas is not None:
                canvas.scroll_to_top()

    def preview_goto(self, index: int) -> None:
        self.preview_step(index - self._preview_page)

    def preview_zoom(self, direction: int) -> None:
        """Zoomstufe wechseln (+1/−1); 0 = an Breite anpassen."""
        if direction == 0:
            self._preview_zoom = None
        else:
            doc = self._preview_doc
            current = self._preview_zoom
            if current is None:
                current = self._current_fit_zoom(doc) if doc is not None else 1.0
            if direction > 0:
                bigger = [zoom for zoom in ZOOMS if zoom > current + 0.01]
                self._preview_zoom = bigger[0] if bigger else ZOOMS[-1]
            else:
                smaller = [zoom for zoom in ZOOMS if zoom < current - 0.01]
                self._preview_zoom = smaller[-1] if smaller else ZOOMS[0]
        self._show_preview_page()

    def _current_fit_zoom(self, doc: PreviewDocument) -> float:
        from ui.theme import px

        index = max(0, min(self._preview_page, doc.pages - 1))
        width_pt = doc.sizes[index][0] or 595.0
        return self._preview_scale(doc, index) * width_pt / px(width_pt * 96 / 72)

    def preview_resized(self) -> None:
        """Breite der Ansicht geändert: bei »An Breite anpassen« passend neu zeichnen."""
        if self._preview_zoom is None and self._preview_doc is not None and self.nav.current == "preview":
            self.ctx.anim.later("preview:fit", 120, self._show_preview_page)

    def _update_preview_tools(self) -> None:
        tools = getattr(self.ui, "preview_tools", None)
        if tools is not None:
            tools.update(self)

    def _preview_status(self, state: str) -> None:
        page = getattr(self.ui, "preview_view", None)
        if page is not None:
            page.set_state(state, self._preview_problem)
        self._update_preview_tools()

    def _close_preview(self) -> None:
        doc, self._preview_doc = self._preview_doc, None
        self._preview_images.clear()
        if doc is not None:
            with RENDER_LOCK:
                doc.close()
