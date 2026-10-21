"""PDF aus Bildern erstellen (seit 4.0): Fotos, Scans und Screenshots als Seiten einer neuen PDF.

Jedes Bild wird eine Seite (mehrseitige TIFF-Dateien: jede Seite des Bildes). Die Ausrichtung aus
den EXIF-Angaben der Kamera wird übernommen – hochkant fotografiert bleibt hochkant.

* **Seitengröße:** »auto« – die Seite ist so groß wie das Bild (bei 150 dpi, mindestens 72 dpi für
  sehr große Bilder, damit keine Seite größer als 5 m wird; Bilder mit Auflösungsangabe behalten
  ihre Größe), »a4« bzw. »letter« – das Bild steht mittig auf der Seite, verkleinert auf die Fläche
  innerhalb des Rands, nie vergrößert. Hoch- oder Querformat folgt dem Bild.
* **Qualität:** JPEG-Dateien werden unverändert übernommen (kein erneutes Komprimieren), andere
  Bilder verlustfrei (Flate). Transparenz wird auf Weiß gelegt – so sieht die Seite in jedem
  Programm gleich aus und bleibt PDF/A-tauglich.

Gespeichert wird wie beim Speichern im Reader: atomar und nach einer Prüfung, nie über eine
vorhandene Datei, die nicht ausdrücklich gewählt wurde (die Nachfrage stellt der Dateidialog).
"""

from __future__ import annotations

import io
import zlib
from dataclasses import dataclass, field
from pathlib import Path

import pikepdf
from pikepdf import Array, Dictionary, Name

from .errors import EditorError

EXTENSIONS = (".jpg", ".jpeg", ".jpe", ".png", ".bmp", ".gif", ".tif", ".tiff", ".webp")
FILTER = "Bilder (*.jpg *.jpeg *.png *.bmp *.gif *.tif *.tiff *.webp);;Alle Dateien (*.*)"
PAGE_SIZES = {  # Punkte (1/72 Zoll), Hochformat
    "a4": (595.276, 841.89),
    "letter": (612.0, 792.0),
}
DEFAULT_DPI = 150.0  # »auto« ohne Auflösungsangabe im Bild
MAX_SIDE = 14_400.0  # größte Seitenlänge in Punkten (200 Zoll, Grenze von Acrobat)
MAX_PIXELS = 120_000_000  # Schutz vor Speicherbomben
MAX_IMAGES = 2000
MARGINS = {"none": 0.0, "small": 14.17, "normal": 28.35}  # 0, 5 mm, 10 mm


class ImageError(EditorError):
    """Ein Bild lässt sich nicht lesen – mit dem Dateinamen in der Meldung."""


@dataclass
class ImagePdfResult:
    path: Path
    pages: int
    skipped: list[str] = field(default_factory=list)  # Dateien, die sich nicht als Bild lesen ließen


def is_image(path: str | Path) -> bool:
    return Path(path).suffix.lower() in EXTENSIONS


def create(paths: list[str | Path], target: str | Path, *, page_size: str = "auto", margin: str = "none", cancel=None, progress=None) -> ImagePdfResult:
    """Bilder in der gegebenen Reihenfolge als neue PDF speichern."""
    from . import save
    from .document import EditorDocument

    if page_size not in ("auto", *PAGE_SIZES):
        raise EditorError("Unbekannte Seitengröße.")
    if margin not in MARGINS:
        raise EditorError("Unbekannter Rand.")
    items = [Path(p) for p in paths]
    if not items:
        raise EditorError("Bitte mindestens ein Bild wählen.")
    if len(items) > MAX_IMAGES:
        raise EditorError(f"Höchstens {MAX_IMAGES} Bilder auf einmal.")
    target = Path(target)
    pdf = pikepdf.new()
    skipped: list[str] = []
    try:
        for number, path in enumerate(items):
            if cancel is not None and cancel.is_set():
                raise EditorError("Abgebrochen.")
            if progress is not None:
                progress(number, len(items), path.name)
            try:
                frames = _frames(path)
            except ImageError:
                skipped.append(path.name)
                continue
            for frame in frames:
                _add_page(pdf, frame, page_size, MARGINS[margin])
        if len(pdf.pages) == 0:
            raise ImageError("Keines der gewählten Bilder ließ sich lesen.")
        pdf.docinfo[Name.Title] = pikepdf.String(target.stem)  # ohne XMP: die Laufzeit hat kein lxml
        pdf.docinfo[Name.Creator] = pikepdf.String("Novadesk")
        pdf.docinfo[Name.Producer] = pikepdf.String("Novadesk")
        buffer = io.BytesIO()
        pdf.save(buffer, compress_streams=True, object_stream_mode=pikepdf.ObjectStreamMode.generate, fix_metadata_version=False)
    finally:
        pdf.close()
    document = EditorDocument.from_bytes(buffer.getvalue(), name=target.name, path=None)
    try:
        save.write_copy(document, buffer.getvalue(), target)
        pages = document.page_count
    finally:
        document.close()
    return ImagePdfResult(target, pages, skipped)


@dataclass
class _Frame:
    name: str
    data: bytes  # Bilddaten (JPEG unverändert oder rohe Pixel)
    filter: str  # »DCTDecode« oder »FlateDecode«
    width: int
    height: int
    colorspace: str  # »DeviceRGB«, »DeviceGray«, »DeviceCMYK«
    dpi: tuple[float, float] | None
    invert_cmyk: bool = False  # Adobe-JPEG in CMYK: Werte sind umgekehrt gespeichert


def _frames(path: Path) -> list[_Frame]:
    from PIL import Image, UnidentifiedImageError

    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise ImageError(f"»{path.name}« kann nicht gelesen werden ({exc.strerror or 'Zugriff verweigert'}).") from exc
    try:
        image = Image.open(io.BytesIO(raw))
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise ImageError(f"»{path.name}« ist kein lesbares Bild.") from exc
    frames: list[_Frame] = []
    with image:
        count = getattr(image, "n_frames", 1) if image.format == "TIFF" else 1
        for index in range(count):
            try:
                image.seek(index)
                if image.width * image.height > MAX_PIXELS:
                    raise ValueError("zu groß")
                frames.append(_frame(path.name, image, raw if count == 1 else None))
            except (OSError, ValueError, Image.DecompressionBombError) as exc:
                raise ImageError(f"»{path.name}« ist beschädigt oder zu groß.") from exc
    return frames


def _frame(name: str, image, raw: bytes | None) -> _Frame:
    from PIL import ImageOps

    dpi = _dpi(image)
    orientation = 1
    try:
        orientation = int(image.getexif().get(0x0112, 1) or 1)
    except Exception:  # noqa: BLE001 - kaputte EXIF-Angaben: Bild so nehmen, wie es ist
        orientation = 1
    if image.format == "JPEG" and raw is not None and orientation == 1 and image.mode in ("RGB", "L", "CMYK"):
        space = {"RGB": "DeviceRGB", "L": "DeviceGray", "CMYK": "DeviceCMYK"}[image.mode]
        adobe = image.mode == "CMYK" and "adobe" in image.info
        return _Frame(name, raw, "DCTDecode", image.width, image.height, space, dpi, invert_cmyk=adobe)
    picture = ImageOps.exif_transpose(image) if orientation != 1 else image.copy()
    if orientation in (5, 6, 7, 8) and dpi is not None:
        dpi = (dpi[1], dpi[0])
    picture = _flatten(picture)
    space = "DeviceGray" if picture.mode == "L" else "DeviceRGB"
    return _Frame(name, zlib.compress(picture.tobytes(), 6), "FlateDecode", picture.width, picture.height, space, dpi)


def _flatten(picture):
    """Pixel als RGB oder Graustufen – Transparenz auf Weiß gelegt."""
    from PIL import Image

    if picture.mode in ("1", "L", "I;16", "I;16B", "I;16L", "I", "F"):
        return picture.convert("L")
    if picture.mode in ("LA", "La"):
        background = Image.new("L", picture.size, 255)
        background.paste(picture.convert("L"), mask=picture.getchannel("A"))
        return background
    if picture.mode == "P" and "transparency" in picture.info or picture.mode in ("RGBA", "RGBa", "PA"):
        rgba = picture.convert("RGBA")
        background = Image.new("RGB", rgba.size, (255, 255, 255))
        background.paste(rgba, mask=rgba.getchannel("A"))
        return background
    return picture.convert("RGB")


def _dpi(image) -> tuple[float, float] | None:
    value = image.info.get("dpi")
    try:
        x, y = float(value[0]), float(value[1])
    except (TypeError, ValueError, IndexError):
        return None
    if not (20 <= x <= 5000 and 20 <= y <= 5000):
        return None  # fehlende (0/1) oder unsinnige Angaben
    return x, y


def _add_page(pdf: pikepdf.Pdf, frame: _Frame, page_size: str, margin: float) -> None:
    stream = pdf.make_stream(frame.data)
    stream[Name.Type] = Name.XObject
    stream[Name.Subtype] = Name.Image
    stream[Name.Width] = frame.width
    stream[Name.Height] = frame.height
    stream[Name.ColorSpace] = Name("/" + frame.colorspace)
    stream[Name.BitsPerComponent] = 8
    stream[Name.Filter] = Name("/" + frame.filter)
    if frame.invert_cmyk:
        stream[Name.Decode] = Array([1, 0, 1, 0, 1, 0, 1, 0])
    image_w, image_h = _natural_size(frame)
    if page_size == "auto":
        page_w, page_h = image_w + 2 * margin, image_h + 2 * margin
        draw_w, draw_h = image_w, image_h
    else:
        page_w, page_h = PAGE_SIZES[page_size]
        if image_w > image_h:  # Querformat folgt dem Bild
            page_w, page_h = page_h, page_w
        room_w, room_h = page_w - 2 * margin, page_h - 2 * margin
        scale = min(1.0, room_w / image_w, room_h / image_h)
        draw_w, draw_h = image_w * scale, image_h * scale
    x, y = (page_w - draw_w) / 2, (page_h - draw_h) / 2
    content = f"q {draw_w:.4f} 0 0 {draw_h:.4f} {x:.4f} {y:.4f} cm /Im0 Do Q".encode("ascii")
    page = pdf.add_blank_page(page_size=(round(page_w, 4), round(page_h, 4)))
    page.obj[Name.Resources] = Dictionary(XObject=Dictionary(Im0=stream))
    page.obj[Name.Contents] = pdf.make_stream(content)


def _natural_size(frame: _Frame) -> tuple[float, float]:
    """Größe des Bildes in Punkten: nach seiner Auflösung, sonst 150 dpi – höchstens ``MAX_SIDE``."""
    dpi_x, dpi_y = frame.dpi or (DEFAULT_DPI, DEFAULT_DPI)
    width, height = frame.width * 72.0 / dpi_x, frame.height * 72.0 / dpi_y
    largest = max(width, height)
    if largest > MAX_SIDE:
        width, height = width * MAX_SIDE / largest, height * MAX_SIDE / largest
    return max(width, 3.0), max(height, 3.0)
