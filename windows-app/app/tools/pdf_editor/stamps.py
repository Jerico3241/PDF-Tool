"""Stempel und Unterschrift – als Anmerkung ``/Stamp`` mit eigenem Erscheinungsbild.

Stempel: vorgegebene (GENEHMIGT, ENTWURF, VERTRAULICH …) oder eigener Text, auf Wunsch mit einer zweiten
Zeile (Datum, Name). Rahmen mit runden Ecken, Text fett; Umlaute über WinAnsi, andere Zeichen mit einer
eingebetteten Systemschrift.

Unterschrift: gezeichnete Striche (als glatte Vektorlinien – scharf in jeder Größe) oder ein eingelesenes
Bild (Hintergrund wird durchsichtig, die Tinte behält ihre Farbe). Eine Unterschrift ist **keine**
digitale Signatur; sie lässt sich wie ein Kommentar verschieben, in der Größe ändern, löschen und mit
»Reduzieren« fest in die Seite übernehmen.

Das Erscheinungsbild hat einen eigenen Raum (``/BBox`` = Breite × Höhe in der Anzeige) und eine
``/Matrix``, die es gegen die Seitendrehung zurückdreht: Stempel und Unterschrift stehen in der Anzeige
immer aufrecht. Verschieben und Größe ändern ändern nur ``/Rect`` – jedes Programm bildet das
Erscheinungsbild darauf ab (PDF 32000-1, 12.5.5).

Gespeicherte Unterschriften liegen nur lokal (``SignatureStore``) und nur, wenn der Nutzer sie speichert.
"""

from __future__ import annotations

import base64
import io
import json
import math
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import pikepdf
from pikepdf import Array, Dictionary, Name, String

from . import annotations, commands
from .commands import History
from .content import fmt
from .document import EditorDocument
from .errors import UnsupportedEdit
from .geometry import Rect, normalize

STAMP, SIGNATURE = "stamp", "signature"
# Schlüssel → (Text, Farbe, Name nach PDF 32000-1 bzw. eigener)
PRESETS: dict[str, tuple[str, tuple[int, int, int], str]] = {
    "genehmigt": ("GENEHMIGT", (34, 128, 60), "/Approved"),
    "geprueft": ("GEPRÜFT", (25, 95, 175), "/PTChecked"),
    "erledigt": ("ERLEDIGT", (34, 128, 60), "/Final"),
    "bezahlt": ("BEZAHLT", (34, 128, 60), "/PTPaid"),
    "eingegangen": ("EINGEGANGEN", (25, 95, 175), "/PTReceived"),
    "entwurf": ("ENTWURF", (96, 96, 96), "/Draft"),
    "kopie": ("KOPIE", (96, 96, 96), "/PTCopy"),
    "vertraulich": ("VERTRAULICH", (190, 30, 45), "/Confidential"),
    "abgelehnt": ("ABGELEHNT", (190, 30, 45), "/NotApproved"),
}
MAX_TEXT = 60
MAX_SUBTITLE = 80
INK = (22, 46, 120)  # Tintenblau für gezeichnete Unterschriften
MAX_STROKES = 400
MAX_POINTS = 20000
MAX_IMAGE_SIDE = 1600
MAX_IMAGE_PIXELS = 40_000_000  # größere Bilder lehnt das Einlesen ab (Schutz vor »Bildbomben«)
MAX_STORED = 6


# --- Stempel -----------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Stamp:
    text: str
    subtitle: str = ""  # zweite Zeile; »{datum}«, »{zeit}« werden ersetzt
    color: tuple[int, int, int] = (190, 30, 45)
    name: str = "/PTStamp"

    @classmethod
    def preset(cls, key: str, subtitle: str = "") -> "Stamp":
        text, color, name = PRESETS[key]
        return cls(text, subtitle, color, name)


def expand(text: str, now: datetime | None = None) -> str:
    now = now or datetime.now()
    return text.replace("{datum}", now.strftime("%d.%m.%Y")).replace("{zeit}", now.strftime("%H:%M"))


def stamp_size(stamp: Stamp, height: float = 0.0) -> tuple[float, float]:
    """Natürliche Größe eines Stempels (Anzeige-Punkte): Höhe 34 pt (mit zweiter Zeile 46 pt)."""
    text, subtitle = _clean(stamp.text, MAX_TEXT), _clean(expand(stamp.subtitle), MAX_SUBTITLE)
    height = height or (46.0 if subtitle else 34.0)
    main = height * (0.42 if subtitle else 0.55)
    width = max(_measure(text, True) * main, _measure(subtitle, False) * main * 0.5) + height * 0.7
    return round(max(width, height * 1.6), 2), round(height, 2)


def add_stamp(document: EditorDocument, history: History, page: int, rect: Rect, stamp: Stamp, *, author: str = "") -> str:
    """Stempel im Bereich ``rect`` (Seitenkoordinaten) – der Text passt sich dem Bereich an."""
    text = _clean(stamp.text, MAX_TEXT)
    if not text:
        raise UnsupportedEdit("Bitte einen Text für den Stempel eingeben.")
    subtitle = _clean(expand(stamp.subtitle), MAX_SUBTITLE)
    width, height = _view_size(document, page, rect)
    if width < 12 or height < 8:
        raise UnsupportedEdit("Der Stempel ist zu klein.")
    resources = Dictionary()
    ops = _stamp_ops(document.pdf, text, subtitle, stamp.color, width, height, resources)
    contents = text + (f" – {subtitle}" if subtitle else "")
    annot = _annotation(document, page, rect, contents, stamp.color, author, stamp.name if stamp.name.startswith("/") else "/PTStamp", STAMP)
    return _insert(document, history, page, annot, ops, resources, width, height, "Stempel hinzufügen")


def _stamp_ops(pdf: pikepdf.Pdf, text: str, subtitle: str, color, width: float, height: float, resources: Dictionary) -> list[str]:
    rgb = " ".join(fmt(v / 255) for v in color)
    line = max(1.2, min(width, height) * 0.06)
    inset = line / 2 + 0.5
    radius = min(height * 0.18, 8.0)
    ops = [f"{rgb} RG {fmt(line)} w 1 j", _rounded(inset, inset, width - 2 * inset, height - 2 * inset, radius) + " S"]
    fonts = Dictionary()
    main_key, main_font, main_measure, main_encode = _font(pdf, text, bold=True, key="/PTSF1")
    fonts[main_key] = main_font
    padding = height * 0.3
    if subtitle:
        size = min(height * 0.42, (width - 2 * padding) / max(0.01, main_measure(text, 1.0)))
        sub_key, sub_font, sub_measure, sub_encode = _font(pdf, subtitle, bold=False, key="/PTSF2")
        fonts[sub_key] = sub_font
        sub_size = min(size * 0.5, (width - 2 * padding) / max(0.01, sub_measure(subtitle, 1.0)))
        gap = height * 0.06
        block = size * 0.72 + gap + sub_size * 0.72
        base = (height - block) / 2 + sub_size * 0.72 + gap
        ops.append(f"BT {main_key} {fmt(size)} Tf {rgb} rg {fmt((width - main_measure(text, size)) / 2)} {fmt(base)} Td <{main_encode(text).hex()}> Tj ET")
        ops.append(f"BT {sub_key} {fmt(sub_size)} Tf {rgb} rg {fmt((width - sub_measure(subtitle, sub_size)) / 2)} {fmt((height - block) / 2)} Td <{sub_encode(subtitle).hex()}> Tj ET")
    else:
        size = min(height * 0.55, (width - 2 * padding) / max(0.01, main_measure(text, 1.0)))
        ops.append(f"BT {main_key} {fmt(size)} Tf {rgb} rg {fmt((width - main_measure(text, size)) / 2)} {fmt((height - size * 0.72) / 2)} Td <{main_encode(text).hex()}> Tj ET")
    resources.Font = fonts
    return ops


# --- Unterschrift ----------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Signature:
    """Unterschrift: Striche in einem eigenen Raum (x nach rechts, y nach unten, 0…width × 0…height)
    oder ein Bild (``mask``: PNG in Graustufen, 255 = volle Tinte)."""

    width: float
    height: float
    strokes: tuple[tuple[tuple[float, float], ...], ...] = ()
    pen: float = 0.035  # Strichstärke im Verhältnis zur Höhe
    color: tuple[int, int, int] = INK
    mask: bytes = b""

    @property
    def kind(self) -> str:
        return "image" if self.mask else "strokes"

    @property
    def aspect(self) -> float:
        return self.width / max(0.01, self.height)

    def to_dict(self) -> dict:
        data = {"width": round(self.width, 3), "height": round(self.height, 3), "pen": round(self.pen, 4), "color": list(self.color)}
        if self.mask:
            data["mask"] = base64.b64encode(self.mask).decode("ascii")
        else:
            data["strokes"] = [[[round(x, 2), round(y, 2)] for x, y in stroke] for stroke in self.strokes]
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "Signature":
        try:
            color = tuple(max(0, min(255, int(v))) for v in data.get("color", INK))[:3]
            mask = base64.b64decode(data["mask"]) if data.get("mask") else b""
            strokes = tuple(tuple((float(p[0]), float(p[1])) for p in stroke) for stroke in data.get("strokes", ()))
            signature = cls(float(data["width"]), float(data["height"]), strokes, float(data.get("pen", 0.035)), color if len(color) == 3 else INK, mask)  # type: ignore[arg-type]
        except (KeyError, TypeError, ValueError, IndexError) as exc:
            raise UnsupportedEdit("Die gespeicherte Unterschrift ist beschädigt.") from exc
        if signature.width <= 0 or signature.height <= 0 or not (signature.strokes or signature.mask):
            raise UnsupportedEdit("Die gespeicherte Unterschrift ist leer.")
        return signature


def signature_from_strokes(strokes, *, color: tuple[int, int, int] = INK, pen: float = 2.2) -> Signature:
    """Gezeichnete Striche (Punkte in Pixeln/Punkten, y nach unten; ``pen`` in denselben Einheiten) →
    Unterschrift: auf ihren Inhalt zugeschnitten, sehr dicht liegende Punkte zusammengefasst."""
    cleaned = []
    total = 0
    for stroke in list(strokes)[:MAX_STROKES]:
        points: list[tuple[float, float]] = []
        for point in stroke:
            x, y = float(point[0]), float(point[1])
            if not (math.isfinite(x) and math.isfinite(y)):
                continue
            if points and abs(points[-1][0] - x) + abs(points[-1][1] - y) < 0.6:
                continue
            points.append((x, y))
        if len(points) == 1:
            points.append((points[0][0] + 0.6, points[0][1]))  # ein Punkt (i-Punkt) bleibt sichtbar
        if points:
            cleaned.append(points)
            total += len(points)
        if total > MAX_POINTS:
            break
    if not cleaned:
        raise UnsupportedEdit("Die Unterschrift ist leer – bitte im Feld unterschreiben.")
    xs = [x for stroke in cleaned for x, _y in stroke]
    ys = [y for stroke in cleaned for _x, y in stroke]
    pad = pen
    x0, y0 = min(xs) - pad, min(ys) - pad
    width, height = max(xs) + pad - x0, max(ys) + pad - y0
    if max(width, height) < 8:
        raise UnsupportedEdit("Die Unterschrift ist zu klein – bitte größer unterschreiben.")
    height = max(height, width / 12)  # ein waagerechter Strich bekommt Platz nach oben und unten
    shift_y = (height - (max(ys) + pad - y0)) / 2
    moved = tuple(tuple((round(x - x0, 2), round(y - y0 + shift_y, 2)) for x, y in stroke) for stroke in cleaned)
    return Signature(round(width, 2), round(height, 2), moved, round(max(0.004, min(0.2, pen / height)), 4), color)


def signature_from_image(path: str | os.PathLike) -> Signature:
    """Unterschrift aus einem Bild (Scan, Foto, PNG): Hintergrund durchsichtig, Tintenfarbe aus dem Bild,
    auf die Unterschrift zugeschnitten und auf höchstens 1600 Pixel verkleinert."""
    from PIL import Image, ImageChops, ImageOps, UnidentifiedImageError

    try:
        with Image.open(path) as source:
            if source.width * source.height > MAX_IMAGE_PIXELS:
                raise UnsupportedEdit("Das Bild ist zu groß.")
            source.load()
            image = ImageOps.exif_transpose(source)
            if image.mode in ("RGBA", "LA", "PA") or (image.mode == "P" and "transparency" in image.info):
                rgba = image.convert("RGBA")
            else:
                rgba = image.convert("RGB").convert("RGBA")
    except (OSError, UnidentifiedImageError, Image.DecompressionBombError) as exc:
        raise UnsupportedEdit("Dieses Bild lässt sich nicht lesen.") from exc
    rgba.thumbnail((MAX_IMAGE_SIDE * 2, MAX_IMAGE_SIDE * 2))
    gray = rgba.convert("L")
    alpha_in = rgba.getchannel("A")
    histogram = gray.histogram(mask=alpha_in.point(lambda v: 255 if v > 127 else 0))
    paper = _percentile(histogram, 0.75)  # Papier: der hellere Großteil des Bildes
    ink_level = _percentile(histogram, 0.02)
    span = max(24, paper - ink_level)
    ink = gray.point(lambda v, p=paper, s=span: max(0, min(255, round((p - v) * 255 / s * 1.15 - 18))))
    alpha = ImageChops.multiply(ink, alpha_in)
    box = alpha.point(lambda v: 255 if v > 40 else 0).getbbox()
    if box is None:
        raise UnsupportedEdit("Auf dem Bild ist keine Unterschrift zu erkennen.")
    margin = max(2, int(max(box[2] - box[0], box[3] - box[1]) * 0.02))
    box = (max(0, box[0] - margin), max(0, box[1] - margin), min(alpha.width, box[2] + margin), min(alpha.height, box[3] + margin))
    alpha = alpha.crop(box)
    color_source = rgba.crop(box).convert("RGB")
    alpha.thumbnail((MAX_IMAGE_SIDE, MAX_IMAGE_SIDE))
    color = _ink_color(color_source.resize(alpha.size), alpha)
    out = io.BytesIO()
    alpha.save(out, format="PNG", optimize=True)
    return Signature(float(alpha.width), float(alpha.height), (), 0.0, color, out.getvalue())


def _percentile(histogram: list[int], share: float) -> int:
    total = sum(histogram)
    if not total:
        return 255
    running = 0
    for value, count in enumerate(histogram):
        running += count
        if running >= total * share:
            return value
    return 255


def _ink_color(image, alpha) -> tuple[int, int, int]:
    """Mittlere Farbe der kräftigen Tinte – sehr helle Ergebnisse werden abgedunkelt (lesbar auf Papier)."""
    from PIL import ImageStat

    strong = alpha.point(lambda v: 255 if v > 160 else 0)
    if strong.getbbox() is None:
        return (20, 20, 20)
    mean = ImageStat.Stat(image, mask=strong).mean
    r, g, b = (int(round(v)) for v in mean[:3])
    lightness = (r * 299 + g * 587 + b * 114) / 1000
    if lightness > 110:
        factor = 110 / lightness
        r, g, b = (int(v * factor) for v in (r, g, b))
    return (r, g, b)


def add_signature(document: EditorDocument, history: History, page: int, rect: Rect, signature: Signature, *, author: str = "") -> str:
    """Unterschrift in den Bereich ``rect`` (Seitenkoordinaten) setzen – mittig, Seitenverhältnis bleibt."""
    width, height = _view_size(document, page, rect)
    if width < 8 or height < 4:
        raise UnsupportedEdit("Der Bereich für die Unterschrift ist zu klein.")
    resources = Dictionary()
    scale = min(width / signature.width, height / signature.height)
    box_w, box_h = signature.width * scale, signature.height * scale
    left, bottom = (width - box_w) / 2, (height - box_h) / 2
    if signature.mask:
        ops = _image_ops(document.pdf, signature, left, bottom, box_w, box_h, resources)
    else:
        ops = _stroke_ops(signature, left, bottom, scale, box_h)
    annot = _annotation(document, page, rect, "Unterschrift", signature.color, author, "/PTSignature", SIGNATURE)
    return _insert(document, history, page, annot, ops, resources, width, height, "Unterschrift hinzufügen")


def fit_rect(signature_aspect: float, center_u: float, center_v: float, height: float = 36.0) -> list[float]:
    """Bereich (Anzeige-Punkte) für einen Klick: Höhe ``height``, Breite nach dem Seitenverhältnis."""
    width = max(12.0, height * max(0.2, min(12.0, signature_aspect)))
    return [center_u - width / 2, center_v - height / 2, center_u + width / 2, center_v + height / 2]


def _stroke_ops(signature: Signature, left: float, bottom: float, scale: float, box_h: float) -> list[str]:
    rgb = " ".join(fmt(v / 255) for v in signature.color)
    pen = max(0.4, signature.pen * box_h)
    ops = [f"{rgb} RG {fmt(pen)} w 1 J 1 j"]
    for stroke in signature.strokes:
        points = [(left + x * scale, bottom + box_h - y * scale) for x, y in stroke]
        ops.append(_smooth(points) + " S")
    return ops


def _smooth(points: list[tuple[float, float]]) -> str:
    """Glatte Linie durch die Punkte: quadratische Bögen über die Mittelpunkte, als kubische Bézier-Kurven."""
    parts = [f"{fmt(points[0][0])} {fmt(points[0][1])} m"]
    if len(points) < 3:
        parts += [f"{fmt(x)} {fmt(y)} l" for x, y in points[1:]]
        return " ".join(parts)
    current = points[0]
    for index in range(1, len(points) - 1):
        control = points[index]
        end = ((control[0] + points[index + 1][0]) / 2, (control[1] + points[index + 1][1]) / 2)
        c1 = (current[0] + 2 / 3 * (control[0] - current[0]), current[1] + 2 / 3 * (control[1] - current[1]))
        c2 = (end[0] + 2 / 3 * (control[0] - end[0]), end[1] + 2 / 3 * (control[1] - end[1]))
        parts.append(f"{fmt(c1[0])} {fmt(c1[1])} {fmt(c2[0])} {fmt(c2[1])} {fmt(end[0])} {fmt(end[1])} c")
        current = end
    parts.append(f"{fmt(points[-1][0])} {fmt(points[-1][1])} l")
    return " ".join(parts)


def _image_ops(pdf: pikepdf.Pdf, signature: Signature, left: float, bottom: float, width: float, height: float, resources: Dictionary) -> list[str]:
    """Bild der Unterschrift: Fläche in Tintenfarbe mit der Unterschrift als weicher Maske."""
    import zlib

    from PIL import Image

    with Image.open(io.BytesIO(signature.mask)) as loaded:
        mask = loaded.convert("L")
    smask = pdf.make_stream(zlib.compress(mask.tobytes(), 9))
    smask.Type, smask.Subtype = Name.XObject, Name.Image
    smask.Width, smask.Height = mask.width, mask.height
    smask.ColorSpace, smask.BitsPerComponent, smask.Filter = Name.DeviceGray, 8, Name.FlateDecode
    color = bytes(signature.color) * (mask.width * mask.height)
    image = pdf.make_stream(zlib.compress(color, 9))
    image.Type, image.Subtype = Name.XObject, Name.Image
    image.Width, image.Height = mask.width, mask.height
    image.ColorSpace, image.BitsPerComponent, image.Filter = Name.DeviceRGB, 8, Name.FlateDecode
    image.SMask = smask
    resources.XObject = Dictionary(PTSig=image)
    return [f"q {fmt(width)} 0 0 {fmt(height)} {fmt(left)} {fmt(bottom)} cm /PTSig Do Q"]


# --- Gemeinsame Bausteine ----------------------------------------------------------------------------------------
def _view_size(document: EditorDocument, page: int, rect: Rect) -> tuple[float, float]:
    rect = normalize(rect)
    width, height = rect[2] - rect[0], rect[3] - rect[1]
    return (height, width) if document.geometry(page).rotation in (90, 270) else (width, height)


def _annotation(document: EditorDocument, page: int, rect: Rect, contents: str, color, author: str, name: str, kind: str) -> Dictionary:
    document.ensure_editable("annotate")
    if not 0 <= page < document.page_count:
        raise UnsupportedEdit("Diese Seite gibt es nicht.")
    now = annotations._now()  # noqa: SLF001
    annot = Dictionary(
        Type=Name.Annot,
        Subtype=Name.Stamp,
        Rect=Array([round(v, 3) for v in normalize(rect)]),
        Name=Name(name),
        C=Array([round(v / 255, 4) for v in color]),
        F=4,
        NM=String(str(uuid.uuid4())),
        M=String(now),
        CreationDate=String(now),
        Contents=String(contents),
        PTEditor=String("PDF Tool"),
        PTKind=Name("/" + kind.capitalize()),
    )
    if author:
        annot.T = String(author)
    return annot


def _insert(document: EditorDocument, history: History, page: int, annot: Dictionary, ops: list[str], resources: Dictionary, width: float, height: float, title: str) -> str:
    pdf = document.pdf
    rotation = document.geometry(page).rotation
    cos, sin = {0: (1, 0), 90: (0, 1), 180: (-1, 0), 270: (0, -1)}.get(rotation, (1, 0))
    with commands.record(document, history, title, pages=(page,)) as rec:
        obj = rec.page(page, ("/Annots",))
        stream = pdf.make_stream("\n".join(ops).encode("latin-1"))
        stream.Type, stream.Subtype = Name.XObject, Name.Form
        stream.BBox = Array([0, 0, round(width, 3), round(height, 3)])
        stream.Matrix = Array([cos, sin, -sin, cos, 0, 0])
        stream.Resources = resources
        annot.AP = Dictionary(N=stream)
        annot = pdf.make_indirect(annot)
        annot.P = obj
        existing = obj.get("/Annots")
        obj.Annots = Array([*(list(existing) if isinstance(existing, Array) else []), annot])
    return annotations.key_of(annot, page, 0)


def _rounded(x: float, y: float, w: float, h: float, r: float) -> str:
    k = r * (1 - annotations.KAPPA)
    return (f"{fmt(x + r)} {fmt(y)} m {fmt(x + w - r)} {fmt(y)} l {fmt(x + w - k)} {fmt(y)} {fmt(x + w)} {fmt(y + k)} {fmt(x + w)} {fmt(y + r)} c "
            f"{fmt(x + w)} {fmt(y + h - r)} l {fmt(x + w)} {fmt(y + h - k)} {fmt(x + w - k)} {fmt(y + h)} {fmt(x + w - r)} {fmt(y + h)} c "
            f"{fmt(x + r)} {fmt(y + h)} l {fmt(x + k)} {fmt(y + h)} {fmt(x)} {fmt(y + h - k)} {fmt(x)} {fmt(y + h - r)} c "
            f"{fmt(x)} {fmt(y + r)} l {fmt(x)} {fmt(y + k)} {fmt(x + k)} {fmt(y)} {fmt(x + r)} {fmt(y)} c h")


def _clean(text: str, limit: int) -> str:
    return " ".join(str(text or "").split())[:limit]


def _measure(text: str, bold: bool) -> float:
    from .fonts import standard_width

    name = "Helvetica-Bold" if bold else "Helvetica"
    return sum(standard_width(name, char) or 556.0 for char in text) / 1000.0


def _font(pdf: pikepdf.Pdf, text: str, *, bold: bool, key: str):
    """(Schlüssel, Schrift, Breite(text, größe), Kodierung) – Helvetica (WinAnsi), sonst eine eingebettete
    Teilmenge einer Systemschrift (nur, wenn ihre Lizenz das Einbetten erlaubt)."""
    from .fonts import CannotEncode, Style as FontStyle, embed_truetype, find_system_font, standard_font, standard_width

    name = "Helvetica-Bold" if bold else "Helvetica"
    try:
        text.encode("cp1252")
        return key, standard_font(pdf, name), (lambda value, at: sum(standard_width(name, char) for char in value) / 1000.0 * at), (lambda value: value.encode("cp1252"))
    except UnicodeEncodeError:
        pass
    path = find_system_font(FontStyle("Helvetica", bold=bold)) or find_system_font(FontStyle("Helvetica"))
    if path is None:
        raise UnsupportedEdit("Für diese Zeichen ist keine passende Schrift verfügbar.")
    try:
        embedded = embed_truetype(pdf, path, text)
    except CannotEncode as exc:
        raise UnsupportedEdit(f"Keine verfügbare Schrift enthält das Zeichen »{exc.char}«.") from exc
    except PermissionError as exc:
        raise UnsupportedEdit("Die passende Schrift erlaubt kein Einbetten.") from exc
    return key, embedded.font, (lambda value, at, e=embedded: e.text_width(value, at)), embedded.encode


# --- Gespeicherte Unterschriften (nur lokal) --------------------------------------------------------------------
@dataclass
class StoredSignature:
    ident: str
    label: str
    created: str
    signature: Signature = field(repr=False)


class SignatureStore:
    """Gespeicherte Unterschriften in einer JSON-Datei – höchstens sechs. Schreiben atomar (temporäre Datei,
    dann ersetzen); Inhalte werden nie protokolliert."""

    def __init__(self, path: str | os.PathLike) -> None:
        self.path = Path(path)

    def load(self) -> list[StoredSignature]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return []
        except (OSError, ValueError):
            return []
        result = []
        for entry in data.get("unterschriften", []) if isinstance(data, dict) else []:
            try:
                result.append(StoredSignature(str(entry["id"]), str(entry.get("label", "")), str(entry.get("created", "")), Signature.from_dict(entry["signature"])))
            except (KeyError, TypeError, UnsupportedEdit):
                continue
        return result[:MAX_STORED]

    def add(self, signature: Signature, label: str = "") -> StoredSignature:
        items = self.load()
        if len(items) >= MAX_STORED:
            raise UnsupportedEdit(f"Es lassen sich höchstens {MAX_STORED} Unterschriften speichern – bitte vorher eine löschen.")
        stored = StoredSignature(uuid.uuid4().hex[:12], _clean(label, 40) or f"Unterschrift {len(items) + 1}", datetime.now().strftime("%d.%m.%Y"), signature)
        self._write([*items, stored])
        return stored

    def remove(self, ident: str) -> bool:
        items = self.load()
        kept = [item for item in items if item.ident != ident]
        if len(kept) == len(items):
            return False
        self._write(kept)
        return True

    def get(self, ident: str) -> StoredSignature | None:
        return next((item for item in self.load() if item.ident == ident), None)

    def _write(self, items: list[StoredSignature]) -> None:
        if not items:
            try:
                self.path.unlink()
            except FileNotFoundError:
                pass
            return
        payload = {"version": 1, "unterschriften": [{"id": item.ident, "label": item.label, "created": item.created, "signature": item.signature.to_dict()} for item in items]}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_name("." + self.path.name + ".tmp")
        temp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        os.replace(temp, self.path)
