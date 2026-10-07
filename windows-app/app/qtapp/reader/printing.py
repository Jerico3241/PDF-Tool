"""Drucken mit dem Druckdialog von Windows (Qt Print Support): Bereich, Kopien, Ausrichtung,
Seitenanpassung und Vorschau. Gerendert wird jede Seite im Arbeitsthread in Druckerauflösung
(höchstens 300 dpi); gezeichnet wird im GUI-Thread.

* Bereich: alle Seiten, aktuelle Seite, ausgewählte Seiten (Auswahl in »Seiten organisieren«) oder
  Seitenbereiche wie »1-3, 5«.
* Kopien: übernimmt der Druckertreiber; kann er keine Kopien, druckt PDF Tool sie selbst (sortiert
  bzw. unsortiert wie gewählt).
* Ausrichtung: wie im Dialog gewählt; ohne Änderung im Dialog je Seite wie das Dokument
  (Querformat-Seiten quer).
* Anpassung: Originalgröße, wenn die Seite auf das Papier passt – sonst verkleinert auf den
  bedruckbaren Bereich (Seitenverhältnis bleibt), mittig.
"""

from __future__ import annotations

PRINT_DPI_MAX = 300


def print_document(doc, selection: list[int] | None = None) -> None:
    """Druckdialog; ``selection``: ausgewählte Seiten (dann ist »Auswahl« vorgewählt)."""
    from PySide6.QtCore import QRectF
    from PySide6.QtPrintSupport import QAbstractPrintDialog, QPrintDialog, QPrinter

    printer = QPrinter(QPrinter.PrinterMode.HighResolution)
    printer.setDocName(doc.name or "PDF")
    printer.setFromTo(1, max(1, doc.pageCount))
    selection = sorted({page for page in (selection or []) if 0 <= page < doc.pageCount})
    before = printer.pageLayout().orientation()
    dialog = QPrintDialog(printer)
    dialog.setWindowTitle("Drucken")
    options = (
        QAbstractPrintDialog.PrintDialogOption.PrintPageRange
        | QAbstractPrintDialog.PrintDialogOption.PrintCurrentPage
        | QAbstractPrintDialog.PrintDialogOption.PrintCollateCopies
        | QAbstractPrintDialog.PrintDialogOption.PrintShowPageSize
    )
    if selection:
        options |= QAbstractPrintDialog.PrintDialogOption.PrintSelection
        printer.setPrintRange(QPrinter.PrintRange.Selection)
    dialog.setOptions(options)
    if dialog.exec() != QPrintDialog.DialogCode.Accepted:
        return
    pages = chosen_pages(printer, doc.pageCount, doc.currentPage, selection)
    chosen = printer.pageLayout().orientation()
    _paint(printer, doc, copies(pages, printer), QRectF, fixed=chosen if chosen != before else None)


def preview_document(doc) -> None:
    """Druckvorschau (Qt) – zeichnet dieselben Seiten wie der Druck."""
    from PySide6.QtCore import QRectF
    from PySide6.QtPrintSupport import QPrinter, QPrintPreviewDialog

    printer = QPrinter(QPrinter.PrinterMode.HighResolution)
    printer.setDocName(doc.name or "PDF")
    dialog = QPrintPreviewDialog(printer)
    dialog.setWindowTitle("Druckvorschau")
    dialog.paintRequested.connect(lambda target: _paint(target, doc, list(range(doc.pageCount)), QRectF, preview=True))
    dialog.exec()


def chosen_pages(printer, count: int, current: int, selection: list[int]) -> list[int]:
    """Zu druckende Seiten (0-basiert) nach dem Bereich im Druckdialog."""
    from PySide6.QtPrintSupport import QPrinter

    mode = printer.printRange()
    if mode == QPrinter.PrintRange.CurrentPage:
        return [current] if 0 <= current < count else []
    if mode == QPrinter.PrintRange.Selection and selection:
        return list(selection)
    if mode == QPrinter.PrintRange.PageRange:
        ranges = printer.pageRanges()
        pages: list[int] = []
        if not ranges.isEmpty():
            for item in ranges.toRangeList():  # mehrere Bereiche wie »1-3, 5«
                pages += [page - 1 for page in range(max(1, item.from_), min(count, item.to) + 1)]
            return pages
        first, last = max(1, printer.fromPage()), min(count, printer.toPage() or count)
        return list(range(first - 1, last))
    return list(range(count))


def copies(pages: list[int], printer) -> list[int]:
    """Kopien, die der Treiber nicht selbst druckt: Seitenfolge vervielfachen (sortiert: 1 2 3 1 2 3,
    unsortiert: 1 1 2 2 3 3). Kann der Treiber Kopien, bleibt es bei einer Folge."""
    count = max(1, printer.copyCount())
    if count == 1 or printer.supportsMultipleCopies():
        return pages
    if printer.collateCopies():
        return pages * count
    return [page for page in pages for _copy in range(count)]


def _paint(printer, doc, pages: list[int], QRectF, preview: bool = False, fixed=None) -> None:  # noqa: N803
    from PySide6.QtCore import QCoreApplication
    from PySide6.QtGui import QPageLayout, QPainter

    if not pages:
        return
    dpi = min(PRINT_DPI_MAX, max(72, printer.resolution()))
    painter = QPainter()
    sizes = doc.pageSizes
    first = True
    try:
        for number, page in enumerate(pages):
            width, height = sizes[page] if page < len(sizes) else (595, 842)
            # Ausrichtung: im Dialog gewählt, sonst je Seite wie das Dokument (Querformat-Seiten quer)
            orientation = fixed if fixed is not None else (QPageLayout.Orientation.Landscape if width > height else QPageLayout.Orientation.Portrait)
            if first:
                printer.setPageOrientation(orientation)
                if not painter.begin(printer):
                    doc.app.notify("reader", "error", "Der Drucker konnte nicht angesprochen werden.", title="Drucken nicht möglich")
                    return
                first = False
            else:
                printer.setPageOrientation(orientation)
                printer.newPage()
            task = doc.engine.submit(lambda page=page: doc.session.print_image(page, dpi), priority=0, label="drucken")
            image = doc.engine.wait(task, timeout=120)
            if image is None or image.isNull():
                continue
            resolution = printer.resolution()
            area = printer.pageLayout().paintRectPixels(resolution)
            target = QRectF(area)
            # Originalgröße, wenn die Seite passt – sonst verkleinern (Seitenverhältnis bleibt), mittig
            natural_w, natural_h = width / 72 * resolution, height / 72 * resolution
            scale = min(1.0, target.width() / natural_w, target.height() / natural_h)
            w, h = natural_w * scale, natural_h * scale
            x = (target.width() - w) / 2
            y = (target.height() - h) / 2
            painter.drawImage(QRectF(x, y, w, h), image)
            if not preview:
                doc.app.set_status(f"Drucken: Seite {number + 1} von {len(pages)} …", "busy")
                QCoreApplication.processEvents()
    finally:
        if painter.isActive():
            painter.end()
    if not preview:
        doc.app.set_status(f"An den Drucker gesendet: {len(pages)} Seite(n).", "success")
