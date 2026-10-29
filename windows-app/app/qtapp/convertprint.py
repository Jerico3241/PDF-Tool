"""»Umwandeln« → Drucken: viele Dateien jeder Art mit einem Druckdialog für alle.

Einmal Drucker, Kopien und Ausrichtung wählen; danach wird jede Datei als eigener Druckauftrag gesendet (im
Druckerwarteschlange mit ihrem Namen). Dateien, die keine PDF sind, werden im Hintergrund in eine PDF umgewandelt
(``tools.convert.jobs.to_pdf``); die Seiten zeichnet der GUI-Thread wie »Drucken« im Reader: Originalgröße, wenn die Seite
passt, sonst verkleinert, mittig, je Seite hoch oder quer wie das Dokument.
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from typing import Callable

PRINT_DPI_MAX = 200  # viele Seiten: weniger Daten für den Spooler als im Reader (300 dpi)
TEST_PRINTER: Callable[[], object] | None = None  # Tests: fertiger QPrinter (PDF-Ausgabe) statt des Druckdialogs


def _printer():
    from PySide6.QtPrintSupport import QAbstractPrintDialog, QPrintDialog, QPrinter

    if TEST_PRINTER is not None:
        return TEST_PRINTER()
    printer = QPrinter(QPrinter.PrinterMode.HighResolution)
    dialog = QPrintDialog(printer)
    dialog.setWindowTitle("Alle Dateien drucken")
    dialog.setOptions(QAbstractPrintDialog.PrintDialogOption.PrintCollateCopies | QAbstractPrintDialog.PrintDialogOption.PrintShowPageSize)
    if dialog.exec() != QPrintDialog.DialogCode.Accepted:
        return None
    return printer


def print_files(controller, paths: list[str]) -> None:
    from tools.convert import jobs

    printer = _printer()
    if printer is None:
        return
    controller._begin(len(paths))  # noqa: SLF001
    cancel = controller._cancel  # noqa: SLF001
    work = Path(tempfile.mkdtemp(prefix="novadesk-drucken-"))
    failed: list[tuple[str, str]] = []
    printed = [0]
    keys = {item["path"]: item["key"] for item in controller._items}  # noqa: SLF001

    def finish(cancelled: bool) -> None:
        shutil.rmtree(work, ignore_errors=True)
        controller.print_finished(printed[0], failed, cancelled)

    def step(index: int) -> None:
        if cancel.is_set():
            for path in paths[index:]:
                controller._item_state(keys[path], "cancelled", "", [])  # noqa: SLF001
            finish(True)
            return
        if index >= len(paths):
            finish(False)
            return
        path = paths[index]
        controller._item_state(keys[path], "running", "Wird vorbereitet …", [])  # noqa: SLF001
        controller._progress(index, len(paths), Path(path).name)  # noqa: SLF001

        def ready(pdf: Path) -> None:
            try:
                pages = paint(printer, pdf, Path(path).name, cancel, lambda number, total: controller._item_message(keys[path], f"Seite {number} von {total} …"))  # noqa: SLF001
            except Exception as exc:  # noqa: BLE001 - eine Datei darf den Druck der übrigen nicht verhindern
                failed.append((path, str(exc) or "Die Datei ließ sich nicht drucken."))
                controller._item_state(keys[path], "error", str(exc) or "Die Datei ließ sich nicht drucken.", [])  # noqa: SLF001
            else:
                printed[0] += 1
                controller._item_state(keys[path], "done", f"{pages} {'Seite' if pages == 1 else 'Seiten'} gedruckt", [])  # noqa: SLF001
            step(index + 1)

        def broken(exc: BaseException, _details: str) -> None:
            from .convert import _message

            failed.append((path, _message(exc)))
            controller._item_state(keys[path], "error", _message(exc), [])  # noqa: SLF001
            step(index + 1)

        controller.app.worker.run(lambda: jobs.to_pdf(Path(path), work, cancel), ready, broken)

    step(0)


def paint(printer, pdf: Path, name: str, cancel, progress=None) -> int:
    """Alle Seiten von ``pdf`` als ein Druckauftrag; gibt die Zahl der Seiten zurück."""
    from PySide6.QtCore import QCoreApplication, QRectF
    from PySide6.QtGui import QImage, QPageLayout, QPainter

    from tools.pdf_editor import render
    from tools.pdf_editor.document import EditorDocument
    from tools.pdf_editor.errors import PasswordRequired

    try:
        document = EditorDocument.open(pdf)
    except PasswordRequired:
        raise RuntimeError("Mit einem Kennwort geschützt – bitte im Reader öffnen und dort drucken.") from None
    painter = QPainter()
    try:
        printer.setDocName(name)
        dpi = min(PRINT_DPI_MAX, max(72, printer.resolution()))
        count = document.page_count
        for index in range(count):
            if cancel is not None and cancel.is_set():
                break
            geo = document.geometry(index)
            orientation = QPageLayout.Orientation.Landscape if geo.width > geo.height else QPageLayout.Orientation.Portrait
            printer.setPageOrientation(orientation)
            if index == 0:
                if not painter.begin(printer):
                    raise RuntimeError("Der Drucker konnte nicht angesprochen werden.")
            else:
                printer.newPage()
            raster = render.render_page(document, index, max(8, int(geo.width * dpi / 72)))
            image = QImage(raster.data, raster.width, raster.height, raster.stride, QImage.Format.Format_RGB32)
            resolution = printer.resolution()
            area = QRectF(printer.pageLayout().paintRectPixels(resolution))
            natural_w, natural_h = geo.width / 72 * resolution, geo.height / 72 * resolution
            scale = min(1.0, area.width() / natural_w, area.height() / natural_h)
            w, h = natural_w * scale, natural_h * scale
            painter.drawImage(QRectF((area.width() - w) / 2, (area.height() - h) / 2, w, h), image)
            if progress is not None:
                progress(index + 1, count)
            QCoreApplication.processEvents()
        return count
    finally:
        if painter.isActive():
            painter.end()
        document.close()
