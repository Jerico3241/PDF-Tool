"""Live-Vorschau der Vertragsübersicht.

Die Vorschau erzeugt die PDF genau wie »PDF erstellen« (``engine.erstelle_pdf``) – nur in
einen privaten temporären Ordner – und zeigt ihre Seiten als Bild (PDFium):

* Änderungen markieren die Vorschau als veraltet. Neu erzeugt wird verzögert (Entprellung)
  und nur, solange die Ansicht »Vorschau« sichtbar ist (Ablauf: ``qtapp/contracts/preview.py``).
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
A4_POINTS = (595.2756, 841.8898)  # Seitenmaß der Übersicht (ReportLab A4)
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

    def render_image(self, index: int, scale: float):
        """Seite als PIL-Bild (RGB) – im Hintergrund; die Oberfläche zeigt es direkt an."""
        import pypdfium2 as pdfium

        scale = max(0.1, min(MAX_SCALE, scale))
        with RENDER_LOCK:
            doc = pdfium.PdfDocument(str(self.path))
            try:
                page = doc[index]
                try:
                    bitmap = page.render(scale=scale)
                    try:
                        return bitmap.to_pil().convert("RGB")
                    finally:
                        bitmap.close()
                finally:
                    page.close()
            finally:
                doc.close()

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


def expected_page(fields: dict) -> tuple[float, float]:
    """Seitenmaß der entstehenden PDF (A4 hoch oder quer) – für den Platz vor dem ersten Bild."""
    width, height = A4_POINTS
    return (height, width) if fields.get("seitenformat") == "quer" else (width, height)


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
