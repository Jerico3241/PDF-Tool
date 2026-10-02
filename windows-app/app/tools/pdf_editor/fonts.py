"""Schriften im PDF: Zeichen ↔ Codes, Breiten, Ersatzschriften.

* ``FontCodec`` – Kodierung einer Schrift aus den Seitenressourcen. Gelesen wird über
  ``/ToUnicode`` (wie beim Kopieren), sonst über ``/Encoding`` samt ``/Differences`` und der
  Adobe-Glyphenliste (Tabellen aus pypdf). ``encode`` liefert die Codes für neuen Text – oder
  ``CannotEncode``, wenn ein Zeichen in dieser Schrift nicht kodierbar ist (z. B. Teilmenge ohne
  dieses Zeichen). Nie wird still ein falsches Zeichen erzeugt.
* Unterstützt für native Änderungen: einfache Schriften (Type1, TrueType, MMType1) und
  Type0-Schriften mit ``Identity-H``/``Identity-V``. Type3-Schriften und andere CMaps: nur lesen.
* Ersatzschriften: die 14 Standardschriften (nicht eingebettet, WinAnsi; Breiten von ReportLab)
  oder eine passende Systemschrift, als **Teilmenge** eingebettet (fontTools) – nur, wenn die
  Schrift das Einbetten erlaubt (OS/2 ``fsType``). Schriftdateien werden nie aus PDFs extrahiert
  oder weitergegeben.
"""

from __future__ import annotations

import functools
import io
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

import pikepdf
from pikepdf import Array, Dictionary, Name

STANDARD_FAMILIES = {
    "Helvetica": ("Helvetica", "Helvetica-Bold", "Helvetica-Oblique", "Helvetica-BoldOblique"),
    "Times": ("Times-Roman", "Times-Bold", "Times-Italic", "Times-BoldItalic"),
    "Courier": ("Courier", "Courier-Bold", "Courier-Oblique", "Courier-BoldOblique"),
}
STANDARD_14 = {name for names in STANDARD_FAMILIES.values() for name in names} | {"Symbol", "ZapfDingbats"}


class CannotEncode(Exception):
    """Ein Zeichen ist in dieser Schrift nicht verfügbar."""

    def __init__(self, char: str) -> None:
        super().__init__(f"Zeichen nicht verfügbar: {char!r}")
        self.char = char


# --- ToUnicode-CMaps ----------------------------------------------------------------------------------
_TOKEN = re.compile(rb"<([0-9A-Fa-f\s]*)>|\[|\]|(begincodespacerange|endcodespacerange|beginbfchar|endbfchar|beginbfrange|endbfrange)")


@dataclass
class CMap:
    codespace: list[tuple[bytes, bytes]] = field(default_factory=list)
    to_unicode: dict[bytes, str] = field(default_factory=dict)

    def code_lengths(self) -> list[int]:
        lengths = sorted({len(low) for low, _high in self.codespace}) or sorted({len(code) for code in self.to_unicode}) or [1]
        return lengths


def _hex(value: bytes) -> bytes:
    digits = re.sub(rb"\s", b"", value)
    if len(digits) % 2:
        digits += b"0"
    return bytes.fromhex(digits.decode("ascii"))


def _utf16(value: bytes) -> str:
    try:
        return value.decode("utf-16-be")
    except UnicodeDecodeError:
        return ""


def parse_cmap(data: bytes) -> CMap:
    """``/ToUnicode``-CMap (codespacerange, bfchar, bfrange) lesen – robust gegen Unsinn."""
    cmap = CMap()
    section = None
    items: list = []
    for match in _TOKEN.finditer(data):
        keyword = match.group(2)
        if keyword is not None:
            if keyword.startswith(b"begin"):
                section, items = keyword[5:], []
            else:
                _apply(cmap, section, items)
                section, items = None, []
            continue
        if section is None:
            continue
        text = match.group(0)
        if text == b"[":
            items.append("[")
        elif text == b"]":
            group = []
            while items and items[-1] != "[":
                group.append(items.pop())
            if items:
                items.pop()
            items.append(list(reversed(group)))
        else:
            items.append(_hex(match.group(1)))
    return cmap


def _apply(cmap: CMap, section, items) -> None:
    if section == b"codespacerange":
        for low, high in zip(items[0::2], items[1::2]):
            if isinstance(low, bytes) and isinstance(high, bytes) and len(low) == len(high):
                cmap.codespace.append((low, high))
    elif section == b"bfchar":
        for code, target in zip(items[0::2], items[1::2]):
            if isinstance(code, bytes) and isinstance(target, bytes):
                text = _utf16(target)
                if text:
                    cmap.to_unicode[code] = text
    elif section == b"bfrange":
        for i in range(0, len(items) - 2, 3):
            low, high, target = items[i], items[i + 1], items[i + 2]
            if not (isinstance(low, bytes) and isinstance(high, bytes)) or len(low) != len(high):
                continue
            start, end = int.from_bytes(low, "big"), int.from_bytes(high, "big")
            if end < start or end - start > 0xFFFF:
                continue
            for offset, code in enumerate(range(start, end + 1)):
                key = code.to_bytes(len(low), "big")
                if isinstance(target, list):
                    if offset < len(target) and isinstance(target[offset], bytes):
                        text = _utf16(target[offset])
                        if text:
                            cmap.to_unicode[key] = text
                elif isinstance(target, bytes) and target:
                    value = int.from_bytes(target, "big") + offset
                    raw = value.to_bytes(len(target), "big")
                    text = _utf16(raw)
                    if text:
                        cmap.to_unicode[key] = text


# --- Kodierungen einfacher Schriften ---------------------------------------------------------------------
def _tables():
    from pypdf import _codecs

    return _codecs.charset_encoding, _codecs.adobe_glyphs


def glyph_to_unicode(name: str) -> str:
    """Glyphenname (``/adieresis``, ``uni00E4``, ``u1F600``) → Unicode."""
    _charsets, glyphs = _tables()
    if not name.startswith("/"):
        name = "/" + name
    text = glyphs.get(name)
    if text:
        return text
    bare = name[1:].split(".", 1)[0]
    if bare.startswith("uni") and len(bare) >= 7:
        try:
            return "".join(chr(int(bare[i : i + 4], 16)) for i in range(3, len(bare) - 3, 4))
        except ValueError:
            return ""
    if bare.startswith("u") and 5 <= len(bare) <= 7:
        try:
            return chr(int(bare[1:], 16))
        except ValueError:
            return ""
    return glyphs.get("/" + bare, "")


def base_encoding(name: str | None, font_name: str = "") -> list[str]:
    charsets, _glyphs = _tables()
    if name and name in charsets:
        return list(charsets[name])
    if font_name.split("+")[-1] in ("Symbol", "ZapfDingbats"):
        key = "/Symbol" if "Symbol" in font_name else "/ZapfDingbats"
        if key in charsets:
            return list(charsets[key])
    return list(charsets["/WinAnsiEncoding"]) if not name else list(charsets["/StandardEncoding"])


# --- Codec ---------------------------------------------------------------------------------------------
class FontCodec:
    """Kodierung, Dekodierung und Breiten einer Schrift aus den Ressourcen einer Seite."""

    def __init__(self, font: pikepdf.Object) -> None:
        self.font = font
        self.subtype = str(font.get("/Subtype", ""))
        self.base_font = str(font.get("/BaseFont", "")).lstrip("/")
        self.name = self.base_font.split("+", 1)[-1]
        self.kind = "unsupported"
        self.two_byte = False
        self.cmap = None
        self._decode: dict[bytes, str] = {}
        self._encode: dict[str, bytes] = {}
        self._widths: dict[bytes, float] = {}
        self.default_width = 1000.0
        self.embedded = False
        self.descriptor = None
        try:
            self._load()
        except (pikepdf.PdfError, TypeError, ValueError, KeyError):
            self.kind = "unsupported"

    # Aufbau --------------------------------------------------------------------------------------------
    def _load(self) -> None:
        font = self.font
        to_unicode = font.get("/ToUnicode")
        if isinstance(to_unicode, pikepdf.Stream):
            try:
                self.cmap = parse_cmap(to_unicode.read_bytes())
            except (pikepdf.PdfError, ValueError):
                self.cmap = None
        if self.subtype in ("/Type1", "/TrueType", "/MMType1"):
            self._load_simple()
        elif self.subtype == "/Type0":
            self._load_type0()
        # Type3 und Unbekanntes bleiben »unsupported« (nur lesen)

    def _load_simple(self) -> None:
        font = self.font
        descriptor = font.get("/FontDescriptor")
        self.descriptor = descriptor if isinstance(descriptor, pikepdf.Dictionary) else None
        if self.descriptor is not None:
            self.embedded = any(key in self.descriptor for key in ("/FontFile", "/FontFile2", "/FontFile3"))
        encoding = font.get("/Encoding")
        base_name = None
        differences = None
        if isinstance(encoding, pikepdf.Name):
            base_name = str(encoding)
        elif isinstance(encoding, pikepdf.Dictionary):
            base = encoding.get("/BaseEncoding")
            base_name = str(base) if isinstance(base, pikepdf.Name) else None
            differences = encoding.get("/Differences")
        if base_name is None and not self.embedded and self.name in STANDARD_14 and self.name not in ("Symbol", "ZapfDingbats"):
            base_name = "/StandardEncoding"
        table = base_encoding(base_name, self.name)
        if isinstance(differences, pikepdf.Array):
            code = 0
            for item in differences:
                if isinstance(item, (int, pikepdf.Object)) and not isinstance(item, pikepdf.Name):
                    try:
                        code = int(item)
                    except (TypeError, ValueError):
                        continue
                else:
                    if 0 <= code < 256:
                        table[code] = glyph_to_unicode(str(item)) or table[code]
                    code += 1
        for code in range(256):
            char = table[code]
            key = bytes([code])
            if char and char not in ("\x00",):
                self._decode[key] = char
        if self.cmap is not None:
            for code, text in self.cmap.to_unicode.items():
                if len(code) == 1:
                    self._decode[code] = text
        # Kodieren: ToUnicode zuerst (dort stehen die tatsächlich benutzten Glyphen), dann Kodierung
        for code in range(255, -1, -1):
            text = table[code]
            if text and len(text) == 1 and code >= 32:
                self._encode.setdefault(text, bytes([code]))
        if self.cmap is not None:
            for code, text in sorted(self.cmap.to_unicode.items(), reverse=True):
                if len(code) == 1 and len(text) == 1:
                    self._encode[text] = code
        widths = font.get("/Widths")
        first = int(font.get("/FirstChar", 0))
        if isinstance(widths, pikepdf.Array):
            for offset, width in enumerate(widths):
                try:
                    self._widths[bytes([first + offset])] = float(width)
                except (TypeError, ValueError, OverflowError):
                    continue
        if self.descriptor is not None and "/MissingWidth" in self.descriptor:
            self.default_width = float(self.descriptor.MissingWidth)
        elif not widths:
            self.default_width = 0.0
        self.kind = "simple"

    def _load_type0(self) -> None:
        font = self.font
        encoding = font.get("/Encoding")
        if not (isinstance(encoding, pikepdf.Name) and str(encoding) in ("/Identity-H", "/Identity-V")):
            return  # vordefinierte CJK-CMaps o. ä.: nur lesen
        descendants = font.get("/DescendantFonts")
        if not isinstance(descendants, pikepdf.Array) or not len(descendants):
            return
        cid = descendants[0]
        descriptor = cid.get("/FontDescriptor")
        self.descriptor = descriptor if isinstance(descriptor, pikepdf.Dictionary) else None
        if self.descriptor is not None:
            self.embedded = any(key in self.descriptor for key in ("/FontFile", "/FontFile2", "/FontFile3"))
        self.two_byte = True
        if self.cmap is not None:
            for code, text in self.cmap.to_unicode.items():
                if len(code) == 2:
                    self._decode[code] = text
            for code, text in sorted(self.cmap.to_unicode.items(), reverse=True):
                if len(code) == 2 and len(text) == 1:
                    self._encode[text] = code
        self.default_width = float(cid.get("/DW", 1000))
        widths = cid.get("/W")
        if isinstance(widths, pikepdf.Array):
            items = list(widths)
            i = 0
            while i < len(items) - 1:
                try:
                    start = int(items[i])
                    nxt = items[i + 1]
                    if isinstance(nxt, pikepdf.Array):
                        for offset, width in enumerate(nxt):
                            self._widths[(start + offset).to_bytes(2, "big")] = float(width)
                        i += 2
                    else:
                        end, width = int(nxt), float(items[i + 2])
                        for value in range(start, min(end, start + 65535) + 1):
                            self._widths[value.to_bytes(2, "big")] = width
                        i += 3
                except (TypeError, ValueError, IndexError, OverflowError):
                    break
        self.kind = "cid"

    # Benutzung ------------------------------------------------------------------------------------------
    @property
    def editable(self) -> bool:
        return self.kind in ("simple", "cid")

    def codes(self, data: bytes) -> list[bytes]:
        step = 2 if self.two_byte else 1
        return [data[i : i + step] for i in range(0, len(data) - step + 1, step)]

    def decode(self, data: bytes) -> str:
        return "".join(self._decode.get(code, "") for code in self.codes(data))

    def encode(self, text: str) -> bytes:
        out = bytearray()
        for char in text:
            code = self._encode.get(char)
            if code is None:
                raise CannotEncode(char)
            out += code
        return bytes(out)

    def can_encode(self, text: str) -> str | None:
        """Erstes nicht kodierbares Zeichen oder ``None``."""
        for char in text:
            if char not in self._encode:
                return char
        return None

    def width(self, code: bytes) -> float:
        """Breite eines Codes in Glyphenraum-Einheiten (1/1000 der Schriftgröße)."""
        width = self._widths.get(code)
        if width is not None:
            return width
        if self.kind == "simple" and not self._widths and self.name in STANDARD_14:
            char = self._decode.get(code, "")
            return standard_width(self.name, char) if char else 0.0
        return self.default_width

    def text_width(self, data: bytes, size: float, char_spacing: float = 0.0, word_spacing: float = 0.0, hscale: float = 1.0) -> float:
        """Breite eines kodierten Strings im Textraum (wie im PDF-Modell, ohne Textmatrix)."""
        total = 0.0
        for code in self.codes(data):
            spacing = char_spacing + (word_spacing if code == b" " and not self.two_byte else 0.0)
            total += (self.width(code) / 1000.0 * size + spacing) * hscale
        return total


def standard_width(font_name: str, char: str) -> float:
    """Breite eines Zeichens einer Standardschrift (1/1000) – AFM-Werte von ReportLab."""
    from reportlab.pdfbase.pdfmetrics import stringWidth

    try:
        return stringWidth(char, font_name, 1000)
    except (KeyError, UnicodeEncodeError, ValueError):
        return 0.0


# --- Ersatzschriften ----------------------------------------------------------------------------------
@dataclass(frozen=True)
class Style:
    family: str  # »Helvetica«, »Times«, »Courier« oder Name einer Systemschrift
    bold: bool = False
    italic: bool = False


def style_of(base_font: str, descriptor=None) -> Style:
    """Familie und Schnitt aus dem Schriftnamen (und den Merkmalen der Schriftbeschreibung)."""
    name = base_font.split("+", 1)[-1]
    lower = name.lower()
    bold = any(token in lower for token in ("bold", "black", "heavy", "semibold", "demi")) or lower.endswith(",bold")
    italic = any(token in lower for token in ("italic", "oblique", "kursiv"))
    flags = 0
    if isinstance(descriptor, pikepdf.Dictionary):
        try:
            flags = int(descriptor.get("/Flags", 0))
            weight = float(descriptor.get("/FontWeight", 0))
            bold = bold or weight >= 600 or bool(flags & (1 << 18))
            italic = italic or bool(flags & (1 << 6)) or float(descriptor.get("/ItalicAngle", 0)) != 0
        except (TypeError, ValueError):
            pass
    family = re.split(r"[,\-]", name, maxsplit=1)[0]
    family = re.sub(r"(PSMT|PS|MT)$", "", family)
    family = re.sub(r"(Bold|Italic|Oblique|Regular|Roman|Book|Medium|Light)+$", "", family) or family
    return Style(family or "Helvetica", bold, italic)


def standard_substitute(style: Style, descriptor=None) -> str:
    """Passende Standardschrift (Helvetica/Times/Courier) für eine Schrift."""
    family = style.family.lower()
    flags = 0
    if isinstance(descriptor, pikepdf.Dictionary):
        try:
            flags = int(descriptor.get("/Flags", 0))
        except (TypeError, ValueError):
            flags = 0
    if "courier" in family or "mono" in family or "consol" in family or flags & 1:
        names = STANDARD_FAMILIES["Courier"]
    elif any(word in family for word in ("times", "serif", "roman", "georgia", "garamond", "cambria", "book", "palatino", "minion")) and "sans" not in family or (flags & 2 and "sans" not in family):
        names = STANDARD_FAMILIES["Times"]
    else:
        names = STANDARD_FAMILIES["Helvetica"]
    return names[(1 if style.bold else 0) + (2 if style.italic else 0)]


def standard_font(pdf: pikepdf.Pdf, name: str) -> pikepdf.Object:
    """Standardschrift als neues Schriftobjekt (WinAnsi, nicht eingebettet)."""
    return pdf.make_indirect(Dictionary(Type=Name.Font, Subtype=Name.Type1, BaseFont=Name("/" + name), Encoding=Name.WinAnsiEncoding))


def font_dirs() -> list[Path]:
    """Ordner mit Systemschriften (Windows: Systemordner und Schriften des Benutzers)."""
    override = os.environ.get("PDFTOOL_FONT_DIRS")
    if override:
        return [Path(part) for part in override.split(os.pathsep) if part]
    dirs: list[Path] = []
    if sys.platform == "win32":
        dirs.append(Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts")
        local = os.environ.get("LOCALAPPDATA")
        if local:
            dirs.append(Path(local) / "Microsoft" / "Windows" / "Fonts")
    else:
        dirs += [Path("/usr/share/fonts"), Path.home() / ".fonts"]
    return [d for d in dirs if d.is_dir()]


# Häufige Windows-Schriften: Familie → Dateinamen (normal, fett, kursiv, fett kursiv)
KNOWN_FILES = {
    "arial": ("arial.ttf", "arialbd.ttf", "ariali.ttf", "arialbi.ttf"),
    "helvetica": ("arial.ttf", "arialbd.ttf", "ariali.ttf", "arialbi.ttf"),
    "timesnewroman": ("times.ttf", "timesbd.ttf", "timesi.ttf", "timesbi.ttf"),
    "times": ("times.ttf", "timesbd.ttf", "timesi.ttf", "timesbi.ttf"),
    "couriernew": ("cour.ttf", "courbd.ttf", "couri.ttf", "courbi.ttf"),
    "courier": ("cour.ttf", "courbd.ttf", "couri.ttf", "courbi.ttf"),
    "calibri": ("calibri.ttf", "calibrib.ttf", "calibrii.ttf", "calibriz.ttf"),
    "cambria": ("cambria.ttc", "cambriab.ttf", "cambriai.ttf", "cambriaz.ttf"),
    "verdana": ("verdana.ttf", "verdanab.ttf", "verdanai.ttf", "verdanaz.ttf"),
    "tahoma": ("tahoma.ttf", "tahomabd.ttf", "tahoma.ttf", "tahomabd.ttf"),
    "georgia": ("georgia.ttf", "georgiab.ttf", "georgiai.ttf", "georgiaz.ttf"),
    "segoeui": ("segoeui.ttf", "segoeuib.ttf", "segoeuii.ttf", "segoeuiz.ttf"),
    "trebuchetms": ("trebuc.ttf", "trebucbd.ttf", "trebucit.ttf", "trebucbi.ttf"),
    "garamond": ("GARA.TTF", "GARABD.TTF", "GARAIT.TTF", "GARABD.TTF"),
    "bitstreamverasans": ("Vera.ttf", "VeraBd.ttf", "VeraIt.ttf", "VeraBI.ttf"),
    "dejavusans": ("DejaVuSans.ttf", "DejaVuSans-Bold.ttf", "DejaVuSans-Oblique.ttf", "DejaVuSans-BoldOblique.ttf"),
}
# Allgemeine Ersatzschriften mit großem Zeichenvorrat (falls die Familie fehlt)
GENERIC_SANS = ("arial", "segoeui", "dejavusans", "bitstreamverasans")


@functools.lru_cache(maxsize=64)
def find_system_font(style: Style) -> Path | None:
    """Systemschrift (TrueType) für eine Familie – sonst eine allgemeine mit großem Zeichenvorrat."""
    key = re.sub(r"[^a-z]", "", style.family.lower())
    index = (1 if style.bold else 0) + (2 if style.italic else 0)
    candidates: list[str] = []
    for family in (key, *GENERIC_SANS):
        names = KNOWN_FILES.get(family)
        if names:
            candidates += [names[index], names[0]]
    folders = font_dirs()
    for name in candidates:
        if not name.lower().endswith(".ttf"):
            continue
        for folder in folders:
            path = folder / name
            if path.is_file():
                return path
            for found in folder.rglob(name):
                if found.is_file():
                    return found
    return None


def embedding_allowed(data: bytes) -> bool:
    """Darf die Schrift eingebettet werden? (OS/2 fsType: »eingeschränkt« oder »nur Bitmap« → nein)"""
    from fontTools.ttLib import TTFont

    try:
        font = TTFont(io.BytesIO(data), lazy=True)
        fs_type = int(font["OS/2"].fsType) if "OS/2" in font else 0
    except Exception:  # noqa: BLE001 - unlesbare Schrift: nicht einbetten
        return False
    if fs_type & 0x0002 and not fs_type & 0x000C:
        return False  # Restricted License embedding
    if fs_type & 0x0200:
        return False  # Bitmap embedding only
    return True


@dataclass
class EmbeddedFont:
    """Eingebettete Teilmenge einer Systemschrift (Type0, Identity-H) und ihre Kodierung."""

    font: pikepdf.Object
    gid_of: dict[str, int]
    widths: dict[int, float]  # GID → Breite (1/1000)
    name: str

    def encode(self, text: str) -> bytes:
        out = bytearray()
        for char in text:
            gid = self.gid_of.get(char)
            if gid is None:
                raise CannotEncode(char)
            out += gid.to_bytes(2, "big")
        return bytes(out)

    def text_width(self, text: str, size: float) -> float:
        return sum(self.widths.get(self.gid_of.get(char, 0), 0.0) for char in text) / 1000.0 * size


def embed_truetype(pdf: pikepdf.Pdf, path: Path, text: str) -> EmbeddedFont:
    """Teilmenge einer TrueType-Schrift mit den Zeichen von ``text`` einbetten (CIDFontType2,
    Identity-H, ToUnicode). Wirft ``CannotEncode`` für Zeichen ohne Glyphe."""
    from fontTools import subset
    from fontTools.ttLib import TTFont

    data = path.read_bytes()
    if not embedding_allowed(data):
        raise PermissionError("Die Schrift erlaubt kein Einbetten.")
    full = TTFont(io.BytesIO(data))
    cmap = full.getBestCmap() or {}
    chars = sorted(set(text) | {" "})
    gid_of: dict[str, int] = {}
    order = full.getGlyphOrder()
    for char in chars:
        glyph = cmap.get(ord(char))
        if glyph is None:
            if char == " ":
                continue
            raise CannotEncode(char)
        gid_of[char] = full.getGlyphID(glyph)
    options = subset.Options()
    options.retain_gids = True  # GID bleibt CID (Identity) – kleine Datei, da leere Glyphen nichts kosten
    options.notdef_outline = True
    options.layout_features = []
    options.name_IDs = ["*"]
    options.hinting = False
    options.drop_tables += ["GSUB", "GPOS", "GDEF", "kern", "DSIG"]
    subsetter = subset.Subsetter(options)
    subsetter.populate(glyphs=[order[gid] for gid in gid_of.values()])
    subsetter.subset(full)
    buffer = io.BytesIO()
    full.save(buffer)
    program = buffer.getvalue()
    head, hhea, os2 = full["head"], full["hhea"], full["OS/2"] if "OS/2" in full else None
    scale = 1000.0 / head.unitsPerEm
    hmtx = full["hmtx"].metrics
    widths = {gid: round(hmtx[order[gid]][0] * scale, 2) for gid in gid_of.values() if order[gid] in hmtx}
    base = re.sub(r"[^A-Za-z0-9\-]", "", (full["name"].getDebugName(6) or path.stem)) or "Schrift"
    tag = "".join(chr(65 + (b % 26)) for b in os.urandom(6))
    base_name = f"{tag}+{base}"
    descriptor = pdf.make_indirect(Dictionary(
        Type=Name.FontDescriptor,
        FontName=Name("/" + base_name),
        Flags=32 if not (os2 and os2.panose.bFamilyType == 3) else 32,
        FontBBox=Array([round(head.xMin * scale), round(head.yMin * scale), round(head.xMax * scale), round(head.yMax * scale)]),
        ItalicAngle=float(full["post"].italicAngle) if "post" in full else 0,
        Ascent=round(hhea.ascent * scale),
        Descent=round(hhea.descent * scale),
        CapHeight=round((getattr(os2, "sCapHeight", 0) or hhea.ascent) * scale),
        StemV=80,
        FontFile2=pdf.make_stream(program),
    ))
    w_array = Array()
    for gid in sorted(widths):
        w_array.append(gid)
        w_array.append(Array([widths[gid]]))
    cid_font = pdf.make_indirect(Dictionary(
        Type=Name.Font,
        Subtype=Name.CIDFontType2,
        BaseFont=Name("/" + base_name),
        CIDSystemInfo=Dictionary(Registry=pikepdf.String("Adobe"), Ordering=pikepdf.String("Identity"), Supplement=0),
        FontDescriptor=descriptor,
        DW=1000,
        W=w_array,
        CIDToGIDMap=Name.Identity,
    ))
    to_unicode = pdf.make_stream(_tounicode_cmap({gid: char for char, gid in gid_of.items()}))
    font = pdf.make_indirect(Dictionary(Type=Name.Font, Subtype=Name.Type0, BaseFont=Name("/" + base_name), Encoding=Name("/Identity-H"), DescendantFonts=Array([cid_font]), ToUnicode=to_unicode))
    return EmbeddedFont(font, gid_of, widths, base)


def _tounicode_cmap(mapping: dict[int, str]) -> bytes:
    lines = [
        "/CIDInit /ProcSet findresource begin", "12 dict begin", "begincmap",
        "/CIDSystemInfo << /Registry (Adobe) /Ordering (UCS) /Supplement 0 >> def",
        "/CMapName /Adobe-Identity-UCS def", "/CMapType 2 def",
        "1 begincodespacerange", "<0000> <FFFF>", "endcodespacerange",
    ]
    items = sorted(mapping.items())
    for start in range(0, len(items), 100):
        chunk = items[start : start + 100]
        lines.append(f"{len(chunk)} beginbfchar")
        for gid, char in chunk:
            lines.append(f"<{gid:04X}> <{char.encode('utf-16-be').hex().upper()}>")
        lines.append("endbfchar")
    lines += ["endcmap", "CMapName currentdict /CMap defineresource pop", "end", "end"]
    return ("\n".join(lines) + "\n").encode("ascii")


def pdf_string(data: bytes) -> pikepdf.String:
    return pikepdf.String(data)
