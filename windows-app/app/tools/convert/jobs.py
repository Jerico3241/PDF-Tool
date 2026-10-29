"""Umwandeln, zusammenfügen und teilen – je Aufruf eine Datei (bzw. beim Zusammenfügen eine Liste).

Alle Wege führen über vorhandene Werkzeuge:

* **PDF** → Word, Excel, Webseite, Text, PowerPoint: ``tools.pdf_editor.convert`` (PowerPoint über den PDF-Import von
  LibreOffice Impress); → Bilder: Seiten mit PDFium darstellen (150 dpi).
* **Text, Tabelle, Präsentation** → PDF und andere Office-Formate: mitgeliefertes LibreOffice (``office.convert_file``);
  → Bilder: erst eine PDF im Arbeitsordner, dann deren Seiten (so sieht das Bild aus wie der Ausdruck).
* **Bilder** → PDF: ``imagepdf.create`` (eine Seite je Bild); → andere Bildformate: Pillow, HEIC/HEIF über pi-heif (nur
  lesen), AVIF und WEBP kann Pillow selbst. Die Ausrichtung aus den EXIF-Angaben wird übernommen, Transparenz bei JPEG
  auf Weiß gelegt.

Ergebnisse sind immer neue Dateien unter einem freien Namen (»Name.pdf«, »Name (2).pdf« …) – nie über eine bestehende.
"""

from __future__ import annotations

import io
import os
import re
import secrets
import shutil
import tempfile
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from tools.pdf_editor.errors import EditorError, PasswordRequired

from . import formats

Progress = Callable[[str], None]
IMAGE_DPI = 150
MAX_SPLIT_FILES = 500
MAX_PAGES_AS_IMAGES = 500
# Office-Ziele für ``soffice --convert-to`` (Endung:Filter[:Optionen])
WRITER = {
    "docx": "docx:MS Word 2007 XML",
    "odt": "odt:writer8",
    "rtf": "rtf:Rich Text Format",
    "txt": "txt:Text (encoded):UTF8",
    "html": "html:HTML (StarWriter):EmbedImages",
}
CALC = {
    "xlsx": "xlsx:Calc MS Excel 2007 XML",
    "ods": "ods:calc8",
    "csv": "csv:Text - txt - csv (StarCalc):59,34,76,1",  # Semikolon, Anführungszeichen, UTF-8 – wie deutsches Excel
    "html": "html:HTML (StarCalc)",
}
IMPRESS = {
    "pptx": "pptx:Impress MS PowerPoint 2007 XML",
    "odp": "odp:impress8",
}


class Cancelled(Exception):
    """»Abbrechen« – die Datei wurde nicht fertig umgewandelt."""


class ConvertError(EditorError):
    pass


@dataclass
class FileResult:
    source: Path
    outputs: list[Path] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


@dataclass
class MergeResult:
    target: Path
    pages: int
    parts: int
    skipped: list[tuple[str, str]] = field(default_factory=list)  # (Pfad wie übergeben, Grund)


def register_image_formats() -> bool:
    """HEIC/HEIF für Pillow anmelden (pi-heif, nur lesen). ``False``, wenn pi-heif fehlt."""
    try:
        import pi_heif
    except ImportError:
        return False
    pi_heif.register_heif_opener()
    return True


def _check(cancel: threading.Event | None) -> None:
    if cancel is not None and cancel.is_set():
        raise Cancelled()


def safe_stem(stem: str) -> str:
    return re.sub(r'[\\/:*?"<>|\x00-\x1f]+', "_", stem).strip(" .")[:120] or "Dokument"


def unique_path(folder: Path, name: str, taken: set[str] | None = None) -> Path:
    """Freier Dateiname: »Name.pdf«, sonst »Name (2).pdf« … – nie eine bestehende oder schon vergebene Datei."""
    stem, suffix = os.path.splitext(name)
    taken = taken if taken is not None else set()
    candidate, number = folder / name, 2
    while candidate.exists() or candidate.name.casefold() in taken:
        candidate = folder / f"{stem} ({number}){suffix}"
        number += 1
    taken.add(candidate.name.casefold())
    return candidate


def write_new(target: Path, data: bytes) -> Path:
    """Neue Datei atomar schreiben (temporäre Datei im Zielordner, dann umbenennen)."""
    if not target.parent.is_dir():
        raise ConvertError("Der Zielordner existiert nicht.")
    temp = target.parent / f".{target.stem[:40]}.novadesk-{secrets.token_hex(4)}.tmp"
    try:
        temp.write_bytes(data)
        os.replace(temp, target)
    except OSError as exc:
        raise ConvertError(f"Die Datei konnte nicht gespeichert werden ({exc.strerror or 'Ein-/Ausgabefehler'}).") from exc
    finally:
        temp.unlink(missing_ok=True)
    return target


def _move_new(produced: Path, target: Path) -> Path:
    if not target.parent.is_dir():
        raise ConvertError("Der Zielordner existiert nicht.")
    try:
        shutil.move(str(produced), str(target))
    except OSError as exc:
        raise ConvertError(f"Die Datei konnte nicht gespeichert werden ({exc.strerror or 'Ein-/Ausgabefehler'}).") from exc
    return target


# PDF als Zwischenschritt -------------------------------------------------------------------------------------------
def to_pdf(source: Path, work: Path, cancel: threading.Event | None = None) -> Path:
    """Beliebige unterstützte Datei als PDF im Arbeitsordner ``work`` (eine PDF selbst: unverändert zurück)."""
    from tools.pdf_editor import imagepdf, office

    kind = formats.kind_of(source)
    if kind == formats.PDF:
        return source
    target = work / f"{safe_stem(source.stem)}-{secrets.token_hex(3)}.pdf"
    _check(cancel)
    if kind == formats.IMAGE:
        register_image_formats()
        imagepdf.create([source], target)
    elif kind == formats.TEXT and source.suffix.lower() == ".txt":
        office.convert_file(source, target, "pdf:writer_pdf_Export")
    elif kind in (formats.TEXT, formats.SHEET, formats.SLIDES):
        office.to_pdf(source, target)
    else:
        raise ConvertError(formats.why_not(source, "pdf"))
    return target


def _open_pdf(path: Path):
    """PDF mit pikepdf öffnen – mit Kennwort geschützte Dateien werden ausgelassen (Grund als Text)."""
    import pikepdf

    try:
        return pikepdf.open(path)
    except pikepdf.PasswordError as exc:
        raise ConvertError("Die PDF ist mit einem Kennwort geschützt – zuerst im Reader entsperren.") from exc
    except (pikepdf.PdfError, OSError, ValueError) as exc:
        raise ConvertError("Die PDF ist beschädigt – zuerst mit »Dateien reparieren« reparieren.") from exc


# Umwandeln ---------------------------------------------------------------------------------------------------------
def convert_file(source: str | os.PathLike, target: str, folder: str | os.PathLike, *, base: str | None = None,
                 taken: set[str] | None = None, cancel: threading.Event | None = None, progress: Progress | None = None) -> FileResult:
    """``source`` in ``target`` (Schlüssel aus ``formats.TARGETS``) umwandeln; Ergebnis in ``folder``, Name aus ``base``
    (ohne Endung; Standard: Name des Originals)."""
    source, folder = Path(source), Path(folder)
    if not source.is_file():
        raise ConvertError("Die Datei gibt es nicht mehr.")
    if not formats.can_convert(source, target):
        raise ConvertError(formats.why_not(source, target))
    if not folder.is_dir():
        raise ConvertError("Der Zielordner existiert nicht.")
    taken = taken if taken is not None else set()
    info = formats.TARGETS[target]
    stem = safe_stem(base if base else source.stem)
    kind = formats.kind_of(source)
    result = FileResult(source)
    work = Path(tempfile.mkdtemp(prefix="novadesk-umwandeln-"))
    try:
        if info.images:
            if kind == formats.IMAGE:
                result.outputs.append(_image_to_image(source, target, unique_path(folder, stem + info.suffix, taken), result.notes))
            else:
                pdf = to_pdf(source, work, cancel)
                result.outputs += _pages_to_images(pdf, target, folder, stem, taken, cancel, progress)
        elif kind == formats.PDF:
            _pdf_to(source, target, unique_path(folder, stem + info.suffix, taken), result, cancel)
        elif target == "pdf":
            produced = to_pdf(source, work, cancel)
            result.outputs.append(_move_new(produced, unique_path(folder, stem + ".pdf", taken)))
        else:
            from tools.pdf_editor import office

            table = {formats.TEXT: WRITER, formats.SHEET: CALC, formats.SLIDES: IMPRESS}[kind]
            _check(cancel)
            produced = work / f"umgewandelt{info.suffix}"
            try:
                office.convert_file(source, produced, table[target])
            except office.OfficeError as exc:
                raise ConvertError(str(exc)) from exc
            result.outputs.append(_move_new(produced, unique_path(folder, stem + info.suffix, taken)))
            if kind == formats.SHEET and target == "csv":
                result.notes.append("CSV enthält nur das erste Blatt, ohne Formate")
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return result


def _pdf_to(source: Path, target: str, destination: Path, result: FileResult, cancel) -> None:
    from tools.pdf_editor import convert
    from tools.pdf_editor.document import EditorDocument

    try:
        document = EditorDocument.open(source)
    except PasswordRequired as exc:
        raise ConvertError("Die PDF ist mit einem Kennwort geschützt – zuerst im Reader entsperren.") from exc
    try:
        converted = convert.convert(document, destination, target, [], cancelled=(lambda: cancel.is_set()) if cancel is not None else None)
    finally:
        document.close()
    result.outputs.append(converted.path)
    if converted.empty and target != "pptx":
        count = len(converted.empty)
        result.notes.append(f"{count} {'Seite' if count == 1 else 'Seiten'} ohne Text – für Scans vorher »Text erkennen (OCR)«")


def _pages_to_images(pdf: Path, target: str, folder: Path, stem: str, taken: set[str], cancel, progress) -> list[Path]:
    """Jede Seite als Bild: »Name.png« bei einer Seite, sonst »Name - Seite 1.png« …"""
    from tools.pdf_editor import render
    from tools.pdf_editor.document import EditorDocument

    info = formats.TARGETS[target]
    try:
        document = EditorDocument.open(pdf)
    except PasswordRequired as exc:
        raise ConvertError("Die PDF ist mit einem Kennwort geschützt – zuerst im Reader entsperren.") from exc
    outputs: list[Path] = []
    try:
        count = document.page_count
        if count > MAX_PAGES_AS_IMAGES:
            raise ConvertError(f"Höchstens {MAX_PAGES_AS_IMAGES} Seiten als Bilder auf einmal.")
        for index in range(count):
            _check(cancel)
            if progress is not None and count > 1:
                progress(f"Seite {index + 1} von {count} …")
            geo = document.geometry(index)
            image = render.to_pil(render.render_page(document, index, max(8, int(geo.width * IMAGE_DPI / 72))))
            name = f"{stem}{info.suffix}" if count == 1 else f"{stem} - Seite {index + 1}{info.suffix}"
            buffer = io.BytesIO()
            _save_image(image, target, buffer, dpi=IMAGE_DPI)
            outputs.append(write_new(unique_path(folder, name, taken), buffer.getvalue()))
    except BaseException:
        for path in outputs:  # halbe Ergebnisse nicht liegen lassen
            path.unlink(missing_ok=True)
        raise
    finally:
        document.close()
    return outputs


def _save_image(image, target: str, handle, dpi: int | None = None) -> None:
    from PIL import Image

    options: dict = {}
    if dpi:
        options["dpi"] = (dpi, dpi)
    if target == "jpg":
        if image.mode in ("RGBA", "LA", "P", "PA"):
            rgba = image.convert("RGBA")
            background = Image.new("RGB", rgba.size, (255, 255, 255))
            background.paste(rgba, mask=rgba.split()[-1])
            image = background
        elif image.mode not in ("RGB", "L", "CMYK"):
            image = image.convert("RGB")
        image.save(handle, "JPEG", quality=90, optimize=True, **options)
    elif target == "png":
        if image.mode not in ("RGB", "RGBA", "L", "LA", "P", "1", "I;16"):
            image = image.convert("RGBA" if "A" in image.getbands() else "RGB")
        image.save(handle, "PNG", optimize=True, **options)
    elif target == "webp":
        image = image.convert("RGBA" if "A" in image.getbands() or image.mode == "P" else "RGB")
        image.save(handle, "WEBP", quality=90, method=4)
    elif target == "avif":
        image = image.convert("RGBA" if "A" in image.getbands() or image.mode == "P" else "RGB")
        image.save(handle, "AVIF", quality=80)
    elif target == "tiff":
        if image.mode not in ("RGB", "RGBA", "L", "1", "CMYK"):
            image = image.convert("RGBA" if "A" in image.getbands() else "RGB")
        image.save(handle, "TIFF", compression="tiff_lzw", **options)
    else:
        raise ConvertError("Unbekanntes Bildformat.")


def _image_to_image(source: Path, target: str, destination: Path, notes: list[str]) -> Path:
    from PIL import Image, ImageOps, UnidentifiedImageError

    from tools.pdf_editor.imagepdf import MAX_PIXELS

    register_image_formats()
    try:
        with Image.open(source) as image:
            if image.width * image.height > MAX_PIXELS:
                raise ConvertError("Das Bild ist zu groß.")
            frames = getattr(image, "n_frames", 1)
            dpi = image.info.get("dpi")
            picture = ImageOps.exif_transpose(image)
            picture.load()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        if source.suffix.lower() in (".heic", ".heif") and not register_image_formats():
            raise ConvertError("HEIC-Bilder kann diese Installation nicht lesen.") from exc
        raise ConvertError("Das Bild ist beschädigt oder kein Bild.") from exc
    if frames > 1:
        notes.append(f"nur das erste von {frames} Bildern übernommen")
    buffer = io.BytesIO()
    resolution = None
    if isinstance(dpi, tuple) and dpi and dpi[0]:
        resolution = max(1, round(float(dpi[0])))
    _save_image(picture, target, buffer, dpi=resolution)
    return write_new(destination, buffer.getvalue())


# Zusammenfügen -----------------------------------------------------------------------------------------------------
def merge(paths: list[str | os.PathLike], target: str | os.PathLike, *, bookmarks: bool = True,
          cancel: threading.Event | None = None, progress: Progress | None = None) -> MergeResult:
    """Dateien jeder Art in dieser Reihenfolge zu einer PDF zusammenfügen (je Datei ein Lesezeichen). Dateien, die sich
    nicht umwandeln lassen, werden ausgelassen und mit Grund gemeldet; bleibt keine übrig, entsteht keine Datei."""
    import pikepdf

    given = [str(path) for path in paths]
    items = [Path(path) for path in paths]
    target = Path(target)
    if len(items) < 2:
        raise ConvertError("Zum Zusammenfügen bitte mindestens zwei Dateien wählen.")
    if target.exists():
        raise ConvertError("Es gibt bereits eine Datei mit diesem Namen.")
    skipped: list[tuple[str, str]] = []
    marks: list[tuple[str, int]] = []
    work = Path(tempfile.mkdtemp(prefix="novadesk-zusammenfuegen-"))
    merged = pikepdf.new()
    opened = []
    try:
        for number, (path, original) in enumerate(zip(items, given), start=1):
            _check(cancel)
            if progress is not None:
                progress(f"{path.name} ({number} von {len(items)}) …")
            try:
                if not path.is_file():
                    raise ConvertError("Die Datei gibt es nicht mehr.")
                if not formats.supported(path):
                    raise ConvertError("Diese Dateiart kann Novadesk nicht umwandeln.")
                source = _open_pdf(to_pdf(path, work, cancel))
            except (EditorError, OSError) as exc:
                if isinstance(exc, Cancelled):
                    raise
                skipped.append((original, str(exc) or "Die Datei ließ sich nicht umwandeln."))
                continue
            opened.append(source)
            marks.append((path.stem, len(merged.pages)))
            merged.pages.extend(source.pages)
        if not marks:
            raise ConvertError("Keine der Dateien ließ sich umwandeln.")
        if bookmarks:
            with merged.open_outline() as outline:
                for title, page in marks:
                    outline.root.append(pikepdf.OutlineItem(title, page))
        _check(cancel)
        buffer = io.BytesIO()
        merged.save(buffer)
        pages = len(merged.pages)
    finally:
        merged.close()
        for source in opened:
            source.close()
        shutil.rmtree(work, ignore_errors=True)
    write_new(target, buffer.getvalue())
    return MergeResult(target, pages, len(marks), skipped)


# Teilen ------------------------------------------------------------------------------------------------------------
SPLIT_PAGES = "pages"  # jede Seite eine Datei
SPLIT_EVERY = "every"  # alle n Seiten
SPLIT_RANGES = "ranges"  # »1-3, 4-6«: je Bereich eine Datei


def split_ranges(mode: str, value: str, count: int) -> list[list[int]]:
    """Bereiche (0-basierte Seiten) für ``mode``; ``ValueError`` mit einem verständlichen Satz."""
    from tools.pdf_editor.pages import parse_pages

    if mode == SPLIT_PAGES:
        return [[index] for index in range(count)]
    if mode == SPLIT_EVERY:
        try:
            size = int(str(value).strip())
        except ValueError:
            raise ValueError("Bitte eine Seitenzahl angeben, z. B. »2«.") from None
        if size < 1:
            raise ValueError("Bitte eine Seitenzahl ab 1 angeben.")
        return [list(range(start, min(count, start + size))) for start in range(0, count, size)]
    if mode == SPLIT_RANGES:
        parts = [part.strip() for part in re.split(r"[,;]", value or "") if part.strip()]
        if not parts:
            raise ValueError("Bitte Bereiche angeben, z. B. »1-3, 4-6«.")
        return [parse_pages(part, count) for part in parts]
    raise ValueError("Unbekannte Art zu teilen.")


def split(source: str | os.PathLike, folder: str | os.PathLike, mode: str, value: str = "", *, taken: set[str] | None = None,
          cancel: threading.Event | None = None, progress: Progress | None = None) -> FileResult:
    """Eine Datei (jede Art, vorher als PDF) in mehrere PDFs teilen: »Name - Teil 1.pdf« bzw. »Name - Seite 1.pdf«."""
    import pikepdf

    source, folder = Path(source), Path(folder)
    if not source.is_file():
        raise ConvertError("Die Datei gibt es nicht mehr.")
    if not formats.supported(source):
        raise ConvertError("Diese Dateiart kann Novadesk nicht umwandeln.")
    if not folder.is_dir():
        raise ConvertError("Der Zielordner existiert nicht.")
    taken = taken if taken is not None else set()
    result = FileResult(source)
    work = Path(tempfile.mkdtemp(prefix="novadesk-teilen-"))
    try:
        with _open_pdf(to_pdf(source, work, cancel)) as pdf:
            count = len(pdf.pages)
            try:
                ranges = split_ranges(mode, value, count)
            except ValueError as exc:
                raise ConvertError(str(exc)) from exc
            if len(ranges) < 2 and mode != SPLIT_RANGES:
                raise ConvertError("Die Datei hat nur eine Seite – es gibt nichts zu teilen." if count == 1 else "Bei dieser Angabe entsteht nur eine Datei.")
            if len(ranges) > MAX_SPLIT_FILES:
                raise ConvertError(f"Höchstens {MAX_SPLIT_FILES} Dateien auf einmal.")
            stem = safe_stem(source.stem)
            try:
                for number, chosen in enumerate(ranges, start=1):
                    _check(cancel)
                    if progress is not None:
                        progress(f"Teil {number} von {len(ranges)} …")
                    with pikepdf.new() as part:
                        for index in chosen:
                            part.pages.append(pdf.pages[index])
                        buffer = io.BytesIO()
                        part.save(buffer)
                    name = f"{stem} - Seite {chosen[0] + 1}.pdf" if mode == SPLIT_PAGES else f"{stem} - Teil {number}.pdf"
                    result.outputs.append(write_new(unique_path(folder, name, taken), buffer.getvalue()))
            except BaseException:
                for path in result.outputs:
                    path.unlink(missing_ok=True)
                raise
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return result
