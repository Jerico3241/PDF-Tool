"""PDF verkleinern: eine kleinere Kopie speichern – das geöffnete Dokument bleibt unverändert.

Gearbeitet wird an einer Kopie des aktuellen Stands (im Speicher). Was kleiner macht:

* **Bilder**, die deutlich feiner aufgelöst sind, als sie auf der Seite erscheinen, werden auf die
  Zielauflösung verkleinert (Pillow, Lanczos) und als JPEG gespeichert – nur Fotos und Graustufen
  (8 Bit, Gerät-RGB/-Grau bzw. ICC mit 1 oder 3 Kanälen, ohne ``/Decode``); Masken bleiben, wie sie
  sind (sie dürfen eine andere Auflösung haben). Ein neues Bild ersetzt das alte nur, wenn es
  deutlich kleiner ist. Schwarzweiß-Scans (1 Bit), Farbpaletten, CMYK, JBIG2 und JPEG 2000 bleiben
  unverändert – dort gingen Schärfe oder Farben verloren.
* **Struktur:** nicht mehr benutzte Ressourcen entfernen, Datenströme komprimieren,
  Objektströme erzeugen.

Danach wird die Kopie wie beim Speichern geprüft (Struktur, alle Seiten darstellbar) und atomar als
neue Datei geschrieben (nie über das Original). Verschlüsselung und Kennwortschutz bleiben erhalten.
"""

from __future__ import annotations

import io
import math
from dataclasses import dataclass
from pathlib import Path

import pikepdf
from pikepdf import Name

from . import save
from .content import PageContent, page_fonts, page_xobjects
from .document import EditorDocument
from .errors import EditorError

LEVELS = {  # Zielauflösung (dpi) und JPEG-Qualität
    "klein": (110, 60),  # Bildschirm und E-Mail
    "mittel": (150, 72),  # ausgewogen
    "hoch": (220, 85),  # zum Drucken
}
THRESHOLD = 1.3  # erst verkleinern, wenn das Bild mindestens so viel feiner ist als das Ziel
MIN_GAIN = 0.9  # neues Bild nur, wenn es höchstens 90 % der bisherigen Größe hat
MIN_PIXELS = 64  # sehr kleine Bilder (Symbole) bleiben
MAX_PIXELS = 80_000_000  # Schutz vor Speicherbomben
FORM_DEPTH = 4


@dataclass
class OptimizeResult:
    path: Path
    before: int  # Bytes (aktueller Stand, wie er gespeichert würde)
    after: int
    images: int  # verkleinerte Bilder
    skipped: int  # Bilder, die so bleiben (Art oder kein Gewinn)

    @property
    def saved_percent(self) -> int:
        if self.before <= 0:
            return 0
        return max(0, round(100 * (self.before - self.after) / self.before))


def estimate(document: EditorDocument) -> int:
    """Größe des aktuellen Stands, wie er gespeichert würde (Bytes)."""
    return len(document.serialize(keep_encryption=True))


def optimize_copy(document: EditorDocument, target: str | Path, level: str = "mittel") -> OptimizeResult:
    if level not in LEVELS:
        raise EditorError("Unbekannte Stufe.")
    target = Path(target)
    if document.path is not None and save._same(document.path, target):  # noqa: SLF001
        raise EditorError("Die verkleinerte Kopie braucht einen eigenen Namen – das Original bleibt unverändert.")
    dpi, quality = LEVELS[level]
    data = document.serialize(keep_encryption=True)
    password = document.save_password
    pdf = pikepdf.open(io.BytesIO(data), password=password or "")
    try:
        changed, skipped = _images(pdf, dpi, quality)
        try:
            pdf.remove_unreferenced_resources()
        except pikepdf.PdfError:
            pass
        expected = save.structure_of(pdf)
        buffer = io.BytesIO()
        encryption = (document.protection.encryption() if document.protection.enabled else False) if document.protection is not None else (True if pdf.is_encrypted else False)
        pdf.save(buffer, encryption=encryption, compress_streams=True, recompress_flate=True, fix_metadata_version=False, object_stream_mode=pikepdf.ObjectStreamMode.generate)
        result = buffer.getvalue()
    finally:
        pdf.close()
    if len(result) >= len(data):
        result, changed = data, 0  # nichts gewonnen: die Kopie entspricht dem aktuellen Stand
    else:
        save.validate(result, password, expected)
    save.write_copy(document, result, target)
    return OptimizeResult(target, len(data), len(result), changed, skipped)


# --- Bilder ------------------------------------------------------------------------------------------------------
def _images(pdf: pikepdf.Pdf, dpi: int, quality: int) -> tuple[int, int]:
    """Bilder auf ``dpi`` verkleinern, wo es sich lohnt. Liefert (verkleinert, übersprungen)."""
    shown: dict[tuple[int, int], tuple[float, float, pikepdf.Object]] = {}
    for page in pdf.pages:
        _collect(pdf, page.obj, (1.0, 0.0, 0.0, 1.0, 0.0, 0.0), shown, 0)
    changed = skipped = 0
    for key, (width_pt, height_pt, image) in shown.items():
        outcome = _shrink(pdf, image, width_pt, height_pt, dpi, quality)
        if outcome is True:
            changed += 1
        elif outcome is False:
            skipped += 1
    return changed, skipped


def _collect(pdf: pikepdf.Pdf, holder, outer, shown: dict, depth: int) -> None:
    """Größte Darstellungsgröße (Punkte) je Bildobjekt – auf Seiten und in Formular-XObjects."""
    from .content import mul

    try:
        content = PageContent(pdf, holder, page_fonts(holder))
    except (pikepdf.PdfError, ValueError, TypeError):
        return
    xobjects = page_xobjects(holder)
    for op in content.images:
        obj = xobjects.get(op.name) if op.name else None
        if obj is None:
            continue
        matrix = mul(op.ctm, outer)
        if op.kind == "image":
            a, b, c, d = matrix[:4]
            width, height = math.hypot(a, b), math.hypot(c, d)
            key = obj.objgen
            known = shown.get(key)
            if known is None or width * height > known[0] * known[1]:
                shown[key] = (width, height, obj)
        elif op.kind == "form" and depth < FORM_DEPTH:
            form_matrix = tuple(float(v) for v in obj.get("/Matrix", [1, 0, 0, 1, 0, 0]))
            _collect(pdf, obj, mul(form_matrix, matrix), shown, depth + 1)


def _shrink(pdf: pikepdf.Pdf, image: pikepdf.Stream, width_pt: float, height_pt: float, dpi: int, quality: int):
    """``True``: verkleinert, ``False``: bleibt (ungeeignet oder ohne Gewinn), ``None``: nicht nötig."""
    try:
        pixels_w, pixels_h = int(image.Width), int(image.Height)
    except (AttributeError, TypeError, ValueError):
        return False
    if pixels_w < MIN_PIXELS or pixels_h < MIN_PIXELS or pixels_w * pixels_h > MAX_PIXELS or width_pt <= 0 or height_pt <= 0:
        return None
    current = max(pixels_w / (width_pt / 72.0), pixels_h / (height_pt / 72.0))
    if current < dpi * THRESHOLD:
        return None
    if not _suitable(image):
        return False
    try:
        picture = pikepdf.PdfImage(image).as_pil_image()
    except Exception:  # noqa: BLE001 - nicht dekodierbar (z. B. JBIG2): bleibt
        return False
    if picture.mode not in ("L", "RGB"):
        return False
    scale = dpi / current
    size = (max(1, round(pixels_w * scale)), max(1, round(pixels_h * scale)))
    from PIL import Image

    smaller = picture.resize(size, Image.Resampling.LANCZOS)
    buffer = io.BytesIO()
    smaller.save(buffer, "JPEG", quality=quality, optimize=True)
    encoded = buffer.getvalue()
    old_size = len(image.read_raw_bytes())
    if len(encoded) > old_size * MIN_GAIN:
        return False
    image.write(encoded, filter=Name.DCTDecode)
    image.Width, image.Height = size
    image.BitsPerComponent = 8
    image.ColorSpace = Name.DeviceRGB if smaller.mode == "RGB" else Name.DeviceGray
    for key in ("/DecodeParms", "/Decode", "/Interpolate"):
        if key in image:
            del image[key]
    return True


def _suitable(image: pikepdf.Stream) -> bool:
    if bool(image.get("/ImageMask", False)) or int(image.get("/BitsPerComponent", 8) or 8) != 8 or "/Decode" in image or "/Mask" in image:
        return False
    filters = image.get("/Filter")
    names = [str(f) for f in filters] if isinstance(filters, pikepdf.Array) else ([str(filters)] if filters is not None else [])
    if any(name in ("/JBIG2Decode", "/JPXDecode", "/CCITTFaxDecode") for name in names):
        return False
    space = image.get("/ColorSpace")
    if space in (Name.DeviceRGB, Name.DeviceGray):
        return True
    if isinstance(space, pikepdf.Array) and len(space) == 2 and space[0] == Name.ICCBased:
        try:
            return int(space[1].get("/N", 0)) in (1, 3)
        except (AttributeError, TypeError, ValueError):
            return False
    return False
