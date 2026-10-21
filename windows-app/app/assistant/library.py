"""Mehrere PDFs oder ein ganzer Ordner für den KI-Assistenten (seit 4.0 Beta 6): Text aller Dateien lesen – Scans ohne
Text auf Wunsch über die Texterkennung (OCR) –, als Abschnitte mit Datei und Seite.

Gelesen wird mit PDFium direkt aus den Dateien (nichts wird geöffnet oder verändert). Grenzen schützen Zeit und
Speicher: höchstens ``MAX_FILES`` Dateien, ``MAX_CHARS`` Zeichen zusammen und ``MAX_OCR_PAGES`` erkannte Seiten. Was
darüber hinausgeht, nennt das Ergebnis. Nichts hier protokolliert Text.
"""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .text import Passage, passages

MAX_FILES = 200
MAX_CHARS = 3_000_000
MAX_OCR_PAGES = 60
MIN_PAGE_TEXT = 20  # weniger Zeichen: die Seite gilt als Scan
OCR_DPI = 200


@dataclass
class Library:
    files: list[Path]  # gelesene Dateien; ``Passage.source`` ist der Index hierin
    items: list[Passage]
    page_counts: list[int]
    unreadable: list[str] = field(default_factory=list)  # Dateinamen (beschädigt, Kennwort)
    scans: list[str] = field(default_factory=list)  # Dateien mit Seiten ohne Text, die nicht erkannt wurden
    recognized: int = 0  # Seiten, deren Text die OCR geliefert hat
    truncated: bool = False  # Grenze erreicht: nicht alles gelesen

    @property
    def label(self) -> str:
        if len(self.files) == 1:
            return self.files[0].name
        folders = {path.parent for path in self.files}
        where = f" aus »{next(iter(folders)).name}«" if len(folders) == 1 else ""
        return f"{len(self.files)} PDFs{where}"


def collect(paths: list[str]) -> list[Path]:
    """PDFs aus Dateien und Ordnern (Ordner mit Unterordnern), sortiert, ohne Doppelte – höchstens ``MAX_FILES`` + 1
    (so erkennt der Aufrufer, dass es mehr waren)."""
    found: list[Path] = []
    seen: set[str] = set()

    def add(path: Path) -> bool:
        key = os.path.normcase(str(path.resolve()))
        if key not in seen:
            seen.add(key)
            found.append(path)
        return len(found) > MAX_FILES

    for raw in paths:
        path = Path(raw)
        if path.is_dir():
            for root, dirs, names in os.walk(path):
                dirs[:] = sorted(d for d in dirs if not d.startswith("."))
                for name in sorted(names, key=str.lower):
                    if name.lower().endswith(".pdf") and add(Path(root) / name):
                        return found
        elif path.is_file() and path.suffix.lower() == ".pdf":
            if add(path):
                return found
    return found


OcrText = Callable[[bytes, int], str]  # (PNG, dpi) → erkannter Text


def read(files: list[Path], *, ocr: OcrText | None = None, cancel: threading.Event | None = None, progress: Callable[[int, int, str], None] | None = None) -> Library:
    """Text der Dateien lesen. ``ocr``: Texterkennung für Seiten ohne Text (``None`` = ohne). ``progress(fertig,
    gesamt, Name)`` meldet den Fortschritt; ``cancel`` bricht ab (``Cancelled`` des Clients)."""
    import pypdfium2 as pdfium

    from .client import Cancelled

    library = Library([], [], [])
    used = 0
    for number, path in enumerate(files[:MAX_FILES]):
        if cancel is not None and cancel.is_set():
            raise Cancelled()
        if progress is not None:
            progress(number, len(files), path.name)
        if used >= MAX_CHARS:
            library.truncated = True
            break
        try:
            texts = _file_texts(pdfium, path, library, ocr, cancel)
        except Cancelled:
            raise
        except Exception:  # noqa: BLE001 - beschädigt, Kennwort, nicht lesbar: auslassen und nennen
            library.unreadable.append(path.name)
            continue
        source = len(library.files)
        library.files.append(path)
        library.page_counts.append(len(texts))
        for item in passages(texts):
            if used + len(item.text) > MAX_CHARS:
                library.truncated = True
                break
            used += len(item.text)
            library.items.append(Passage(item.page, item.text, source))
    if len(files) > MAX_FILES:
        library.truncated = True
    return library


def _file_texts(pdfium, path: Path, library: Library, ocr: OcrText | None, cancel) -> list[str]:
    from pdfium_lock import PDFIUM_LOCK

    texts: list[str] = []
    missing = False
    with PDFIUM_LOCK:
        document = pdfium.PdfDocument(str(path))
    try:
        for index in range(len(document)):
            with PDFIUM_LOCK:
                page = document[index]
                textpage = page.get_textpage()
                text = textpage.get_text_range()
                textpage.close()
            if len(text.strip()) < MIN_PAGE_TEXT:
                if ocr is not None and library.recognized < MAX_OCR_PAGES:
                    if cancel is not None and cancel.is_set():
                        page.close()
                        from .client import Cancelled

                        raise Cancelled()
                    with PDFIUM_LOCK:
                        image = page.render(scale=OCR_DPI / 72).to_pil()
                    import io

                    buffer = io.BytesIO()
                    image.save(buffer, "PNG")
                    recognized = ocr(buffer.getvalue(), OCR_DPI)
                    if recognized.strip():
                        library.recognized += 1
                        text = recognized
                    else:
                        missing = True
                else:
                    missing = True
            with PDFIUM_LOCK:
                page.close()
            texts.append(text)
    finally:
        with PDFIUM_LOCK:
            document.close()
    if missing:
        library.scans.append(path.name)
    return texts


def tesseract_text(engine, languages: list[str], cancel: threading.Event | None = None) -> OcrText:
    """Texterkennung (Tesseract) als ``OcrText``: Seitenbild erkennen, den Text aus dessen Text-PDF lesen."""
    from tools.pdf_editor import ocr as ocrmod

    def run(png: bytes, dpi: int) -> str:
        import pypdfium2 as pdfium

        from pdfium_lock import PDFIUM_LOCK

        from .client import Cancelled

        try:
            result = ocrmod.recognize(engine, 0, png, languages, dpi, cancel=cancel)
        except ocrmod.OcrCancelled:
            raise Cancelled() from None
        except ocrmod.OcrError:
            return ""  # diese Seite bleibt ohne Text
        with PDFIUM_LOCK:
            document = pdfium.PdfDocument(result.pdf)
            try:
                return "\n".join(document[i].get_textpage().get_text_range() for i in range(len(document)))
            finally:
                document.close()

    return run
