"""Datenströme retten: Flate-Daten, die sich nicht vollständig dekodieren lassen.

Greift im Modus AUTO, bevor qpdf eine Ausgabe schreibt (qpdf übernähme beschädigte Ströme sonst
unverändert oder – mit vorgeschalteten ASCII-Filtern – stillschweigend gekürzt), und noch einmal
nach der Auswahl der besten Ausgabe, wenn deren Prüfung unlesbare Datenströme meldet (``engine``).
Jede so entstandene Ausgabe wird danach wie alle anderen geprüft.

* Gelesen wird mit ``zlib.decompressobj`` – so weit die Daten reichen (abgeschnitten) bzw. bis
  zur ersten beschädigten Stelle. Vorgeschaltete ASCII-Filter (ASCII85, ASCIIHex) werden ebenso
  tolerant gelesen; andere Filter und Prädiktoren werden nicht geraten.
* Inhaltsströme von Seiten und Formularen (Form-XObjects, Erscheinungsbilder von Anmerkungen):
  Übernommen wird der lesbare Teil bis zum letzten vollständigen Befehl; offene Text-,
  Grafikzustands-, Markierungs- und Kompatibilitätsblöcke werden geschlossen. Die Seite zeigt so
  den lesbaren Teil, statt leer zu bleiben oder einen Fehler zu melden. Es zählen nur bekannte
  Befehle – was danach nicht mehr wie ein Inhaltsstrom aussieht, wird nicht übernommen.
* Bilder nur, wenn das sicher geht: nur Flate (ohne oder mit PNG-Prädiktor), Farbraum Grau, RGB
  oder CMYK (auch kalibriert oder ICC-basiert), kein /Decode, keine Maske. Übernommen werden ganze
  Zeilen, fehlende Zeilen werden weiß aufgefüllt. Alle anderen Bilder und Datenströme bleiben
  unverändert und werden gemeldet.
* Endet der Flate-Strom regulär (es fehlte z. B. nur die Prüfsumme), wird er vollständig neu
  geschrieben. Sonst gilt er als »teilweise gerettet« – nie als vollständig repariert.

Meldungen enthalten nur Objektnummern und Längen, nie Inhalte der PDF.
"""

from __future__ import annotations

import binascii
import re
import zlib
from dataclasses import dataclass, field

CHUNK = 4096  # Flate-Daten blockweise lesen: bei einem Fehler bleibt das bis dahin Gelesene erhalten
MAX_CONTENT = 64 << 20  # entpackter Inhaltsstrom (Schutz vor »Zip-Bomben«)
MAX_IMAGE = 256 << 20  # entpacktes Bild
FLATE = ("/FlateDecode", "/Fl")
ASCII_HEX = ("/ASCIIHexDecode", "/AHx")
ASCII_85 = ("/ASCII85Decode", "/A85")
CONTENT, IMAGE, OTHER = "Inhalt", "Bild", "sonstiger"  # Arten beschädigter Datenströme (Protokoll)

# Befehle in Inhaltsströmen (PDF 32000-1, Anhang A)
OPERATORS = frozenset(
    b"b B b* B* BDC BI BMC BT BX c cm CS cs d d0 d1 Do DP EI EMC ET EX f F f* G g gs h i ID j J K k l m M MP n "
    b"q Q re RG rg ri s S SC sc SCN scn sh T* Tc Td TD Tf Tj TJ TL Tm Tr Ts Tw Tz v w W W* y ' \"".split()
)
OPENS = {b"q": b"q", b"BT": b"BT", b"BMC": b"BMC", b"BDC": b"BMC", b"BX": b"BX"}  # Befehl → offener Block
CLOSES = {b"Q": b"q", b"ET": b"BT", b"EMC": b"BMC", b"EX": b"BX"}  # Befehl → Block, den er schließt
FINISH = {b"q": b"Q", b"BT": b"ET", b"BMC": b"EMC", b"BX": b"EX"}  # offener Block → Abschluss

_SPACE = re.compile(rb"(?:[\x00\t\n\x0c\r ]+|%[^\r\n]*)+")
_REGULAR = re.compile(rb"[^\x00\t\n\x0c\r ()<>\[\]{}/%]+")
_NUMBER = re.compile(rb"[+-]?(?:\d+\.?\d*|\.\d+)")
_HEX = re.compile(rb"[0-9A-Fa-f\x00\t\n\x0c\r ]*")
_PARENS = re.compile(rb"[()\\]")
_IMAGE_START = re.compile(rb"(?<![^\x00\t\n\x0c\r ])ID[\x00\t\n\x0c\r ]")
_IMAGE_END = re.compile(rb"[\x00\t\n\x0c\r ]EI(?![^\x00\t\n\x0c\r ()<>\[\]{}/%])")
_WHITE = re.compile(rb"[\x00\t\n\x0c\r ]+")


@dataclass
class Decoded:
    data: bytes
    complete: bool  # Datenende regulär erreicht – nichts fehlt


# --- Dekodieren -------------------------------------------------------------------------------------------------------


def _until_error(engine, chunk: bytes) -> bytes:
    """Block mit der Fehlerstelle Byte für Byte lesen – jedes lesbare Byte bleibt erhalten."""
    out = bytearray()
    for index in range(len(chunk)):
        try:
            out += engine.decompress(chunk[index : index + 1])
        except zlib.error:
            break
    return bytes(out)


def _inflate(data: bytes, wbits: int, limit: int) -> tuple[Decoded, bytes]:
    """(gelesene Daten, Bytes nach dem Ende des Flate-Stroms)."""
    engine = zlib.decompressobj(wbits)
    out = bytearray()
    for start in range(0, len(data), CHUNK):
        chunk = data[start : start + CHUNK]
        before = engine.copy()
        try:
            out += engine.decompress(chunk)
        except zlib.error:
            out += _until_error(before, chunk)
            return Decoded(bytes(out[:limit]), False), b""
        if engine.eof:
            return Decoded(bytes(out[:limit]), len(out) <= limit), engine.unused_data
        if len(out) > limit:
            return Decoded(bytes(out[:limit]), False), b""
    try:
        out += engine.flush()
    except zlib.error:
        return Decoded(bytes(out[:limit]), False), b""
    return Decoded(bytes(out[:limit]), engine.eof and len(out) <= limit), engine.unused_data


def zlib_header(data: bytes) -> bool:
    return len(data) >= 2 and data[0] & 0x0F == 8 and data[0] >> 4 <= 7 and ((data[0] << 8) | data[1]) % 31 == 0


def inflate(data: bytes, limit: int, guess: bool = True) -> Decoded:
    """Flate-Daten so weit wie möglich dekodieren – bei abgeschnittenen oder beschädigten Daten alles
    bis zur Fehlerstelle. Endet der Deflate-Strom regulär und fehlt nur die Prüfsumme, gilt er als
    vollständig; eine falsche Prüfsumme heißt: beschädigt. ``guess``: auch ohne gültigen zlib-Kopf
    als rohes Deflate lesen (nur, wo das Ergebnis danach noch geprüft wird)."""
    if zlib_header(data):
        found, _rest = _inflate(data, zlib.MAX_WBITS, limit)
        if found.complete:
            return found
        bare, rest = _inflate(data[2:], -zlib.MAX_WBITS, limit)  # ohne Kopf und Prüfsumme
        if bare.complete and (len(rest) < 4 or int.from_bytes(rest[:4], "big") == zlib.adler32(bare.data)):
            return bare
        best = bare if len(bare.data) > len(found.data) else found
        return Decoded(best.data, False)
    if not guess:
        return Decoded(b"", False)
    # zlib-Kopf fehlt oder ist beschädigt: rohes Deflate (mit und ohne die ersten zwei Byte)
    options = [_inflate(data, -zlib.MAX_WBITS, limit)[0], _inflate(data[2:], -zlib.MAX_WBITS, limit)[0]]
    return max(options, key=lambda item: (item.complete, len(item.data)))


def flate_ok(data: bytes) -> bool:
    """Lassen sich die Flate-Daten vollständig und mit gültiger Prüfsumme dekodieren? (ohne die
    entpackten Daten zu behalten)"""
    engine = zlib.decompressobj()
    try:
        for start in range(0, len(data), 1 << 16):
            pending = data[start : start + (1 << 16)]
            while pending:
                engine.decompress(pending, 1 << 20)
                pending = engine.unconsumed_tail
                if engine.eof:
                    return True
        engine.flush()
    except zlib.error:
        return False
    return engine.eof


def flate_complete(data: bytes) -> bool:
    """Endet der Deflate-Strom regulär, auch wenn nur die Prüfsumme am Ende fehlt? Eine vorhandene,
    aber falsche Prüfsumme heißt: beschädigt. (Ohne die entpackten Daten zu behalten.)"""
    if not zlib_header(data):
        return False
    engine = zlib.decompressobj(-zlib.MAX_WBITS)
    checksum = 1
    step = 1 << 16
    try:
        for start in range(2, len(data), step):
            pending = data[start : start + step]
            while pending:
                checksum = zlib.adler32(engine.decompress(pending, 1 << 20), checksum)
                pending = engine.unconsumed_tail
                if engine.eof:
                    rest = engine.unused_data + data[start + step :]
                    return len(rest) < 4 or int.from_bytes(rest[:4], "big") == checksum
        checksum = zlib.adler32(engine.flush(), checksum)
    except zlib.error:
        return False
    return engine.eof and (len(engine.unused_data) < 4 or int.from_bytes(engine.unused_data[:4], "big") == checksum)


def ascii_hex(data: bytes) -> Decoded:
    end = data.find(b">")
    complete = end >= 0
    digits = _WHITE.sub(b"", data[:end] if complete else data)
    bad = re.search(rb"[^0-9A-Fa-f]", digits)
    if bad:
        digits, complete = digits[: bad.start()], False
    if len(digits) % 2:
        digits = digits + b"0" if complete else digits[:-1]  # Norm: fehlende letzte Ziffer ist 0
    return Decoded(binascii.unhexlify(digits), complete)


def _base85(group: list[int]) -> int:
    value = 0
    for digit in group:
        value = value * 85 + digit
    return value


def ascii85(data: bytes) -> Decoded:
    text = _WHITE.sub(b"", data)
    end = text.find(b"~>")
    complete = end >= 0
    if complete:
        text = text[:end]
    out = bytearray()
    group: list[int] = []
    for byte in text:
        if byte == 0x7A and not group:  # »z«: vier Null-Bytes
            out += b"\x00\x00\x00\x00"
            continue
        if not 0x21 <= byte <= 0x75:
            complete = False  # ungültiges Zeichen: bis hierher lesbar
            break
        group.append(byte - 33)
        if len(group) == 5:
            value = _base85(group)
            if value > 0xFFFFFFFF:
                complete = False
                break
            out += value.to_bytes(4, "big")
            group = []
    if group and complete:  # letzte, kürzere Gruppe (nur mit Endkennung »~>« sicher)
        value = _base85(group + [84] * (5 - len(group)))
        if len(group) == 1 or value > 0xFFFFFFFF:
            complete = False
        else:
            out += value.to_bytes(4, "big")[: len(group) - 1]
    return Decoded(bytes(out), complete)


def flate_layer(raw: bytes, filters: list[str]) -> bytes | None:
    """Die Flate-Daten einer Filterkette (vorgeschaltete ASCII-Filter tolerant gelesen).
    ``None``: kein Flate oder andere Filter davor. Ob etwas fehlt, zeigt erst die Flate-Schicht:
    Abgeschnittene ASCII-Daten sind abgeschnittene Flate-Daten."""
    position = next((index for index, name in enumerate(filters) if name in FLATE), -1)
    if position < 0:
        return None
    data = raw
    for name in filters[:position]:
        if name in ASCII_HEX:
            data = ascii_hex(data).data
        elif name in ASCII_85:
            data = ascii85(data).data
        else:
            return None
    return data


def decode(raw: bytes, filters: list[str], limit: int, guess: bool = True) -> Decoded | None:
    """Filterkette, die mit Flate endet, tolerant dekodieren. ``None``: andere Filter (nichts raten)."""
    if not filters or filters[-1] not in FLATE:
        return None
    layer = flate_layer(raw, filters)
    return inflate(layer, limit, guess) if layer is not None else None


# --- Inhaltsströme ----------------------------------------------------------------------------------------------------


@dataclass
class Cut:
    data: bytes  # lesbarer Teil bis zum letzten vollständigen Befehl, offene Blöcke geschlossen
    operators: int  # übernommene Befehle
    closed: list[str] = field(default_factory=list)  # angefügte Abschlüsse, z. B. ["ET", "Q"]


def _string_end(data: bytes, pos: int) -> int:
    """Ende der Zeichenkette ab »(« (nach der schließenden Klammer) – -1, wenn sie abgeschnitten ist."""
    depth = 0
    index = pos
    while True:
        found = _PARENS.search(data, index)
        if found is None:
            return -1
        index = found.start()
        if data[index] == 0x5C:  # Backslash: nächstes Zeichen überspringen
            index += 2
            continue
        depth += 1 if data[index] == 0x28 else -1
        index += 1
        if depth == 0:
            return index


def _inline_image_end(data: bytes, pos: int) -> int:
    """Ende eines Inline-Bilds ab »BI« (nach »EI«) – -1, wenn es abgeschnitten ist."""
    start = _IMAGE_START.search(data, pos)
    if start is None:
        return -1
    end = _IMAGE_END.search(data, start.end())
    return end.end() if end else -1


def _track(blocks: list[bytes], word: bytes) -> None:
    if word in OPENS:
        blocks.append(OPENS[word])
    elif word in CLOSES:
        block = CLOSES[word]
        for index in range(len(blocks) - 1, -1, -1):
            if blocks[index] == block:
                del blocks[index]
                break


def cut_content(data: bytes) -> Cut | None:
    """Lesbaren Anfang eines Inhaltsstroms bestimmen: alles bis zum letzten vollständigen Befehl,
    danach die Abschlüsse der noch offenen Blöcke. ``None``: kein vollständiger Befehl."""
    size = len(data)
    pos = end = count = 0
    depth = 0  # offene »[« und »<<« der Operanden
    blocks: list[bytes] = []  # offene Blöcke (q, BT, BMC/BDC, BX) – Stand nach dem letzten Befehl
    while True:
        space = _SPACE.match(data, pos)
        if space:
            pos = space.end()
        if pos >= size:
            break
        byte = data[pos]
        if byte == 0x28:  # (
            close = _string_end(data, pos)
            if close < 0:
                break
            pos = close
        elif byte == 0x3C:  # <
            if data[pos + 1 : pos + 2] == b"<":
                depth += 1
                pos += 2
                continue
            close = data.find(b">", pos + 1)
            if close < 0 or not _HEX.fullmatch(data, pos + 1, close):
                break
            pos = close + 1
        elif byte == 0x3E:  # >
            if data[pos + 1 : pos + 2] != b">" or depth == 0:
                break
            depth -= 1
            pos += 2
        elif byte == 0x5B:  # [
            depth += 1
            pos += 1
        elif byte == 0x5D:  # ]
            if depth == 0:
                break
            depth -= 1
            pos += 1
        elif byte == 0x2F:  # /Name
            name = _REGULAR.match(data, pos + 1)
            pos = name.end() if name else pos + 1
        elif byte in b"){}":
            break
        else:
            word = _REGULAR.match(data, pos).group(0)
            after = pos + len(word)
            if _NUMBER.fullmatch(word) or word in (b"true", b"false", b"null"):
                pos = after
                continue
            if depth or word in (b"ID", b"EI") or (word not in OPERATORS and b"BX" not in blocks):
                break  # Befehl mitten in Operanden oder unbekannt (erlaubt nur zwischen BX und EX): nicht verlässlich
            if word == b"BI":
                after = _inline_image_end(data, after)
                if after < 0:
                    break
            _track(blocks, word)
            count += 1
            pos = end = after
    if not count:
        return None
    closers = [FINISH[block] for block in reversed(blocks)]
    tail = b"\n" + b" ".join(closers) + b"\n" if closers else b"\n"
    return Cut(data[:end] + tail, count, [closer.decode() for closer in closers])


# --- Bilder -----------------------------------------------------------------------------------------------------------


@dataclass
class ImageFormat:
    width: int
    height: int
    row: int  # Byte je Zeile (ohne Filter-Byte des PNG-Prädiktors)
    png: bool  # PNG-Prädiktor: jede Zeile beginnt mit einem Filter-Byte
    white: int  # Füllwert für fehlende Zeilen (Grau/RGB: 0xFF, CMYK: 0x00)

    @property
    def size(self) -> int:
        return self.height * (self.row + (1 if self.png else 0))


def pad_rows(data: bytes, fmt: ImageFormat) -> tuple[bytes, int] | None:
    """Ganze Zeilen übernehmen, fehlende weiß auffüllen: (Bilddaten, gerettete Zeilen).
    ``None``: keine einzige ganze Zeile lesbar."""
    step = fmt.row + (1 if fmt.png else 0)
    rows = min(fmt.height, len(data) // step)
    if fmt.png:
        for index in range(rows):
            if data[index * step] > 4:  # ungültiges Filter-Byte: ab hier unbrauchbar
                rows = index
                break
    if rows <= 0:
        return None
    filler = (b"\x00" if fmt.png else b"") + bytes([fmt.white]) * fmt.row
    return data[: rows * step] + filler * (fmt.height - rows), rows


def _number(value) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _colors(space) -> tuple[int, int] | None:
    """(Komponenten, Weiß) eines Farbraums – nur Grau, RGB und CMYK (auch kalibriert oder ICC-basiert)."""
    import pikepdf

    if isinstance(space, pikepdf.Name):
        return {"/DeviceGray": (1, 0xFF), "/DeviceRGB": (3, 0xFF), "/DeviceCMYK": (4, 0x00)}.get(str(space))
    if isinstance(space, pikepdf.Array) and len(space) == 2:
        family = str(space[0])
        if family == "/CalGray":
            return 1, 0xFF
        if family == "/CalRGB":
            return 3, 0xFF
        if family == "/ICCBased" and isinstance(space[1], pikepdf.Stream):
            return {1: (1, 0xFF), 3: (3, 0xFF), 4: (4, 0x00)}.get(_number(space[1].get("/N")))
    return None


def image_format(image, parms) -> tuple[ImageFormat | None, str]:
    """Format eines Bilds, wenn sich fehlende Zeilen sicher auffüllen lassen – sonst (None, Grund)."""
    import pikepdf

    if image.get("/ImageMask") is True:
        return None, "Maske"
    if "/Decode" in image:
        return None, "/Decode"
    width, height, bits = (_number(image.get(key)) for key in ("/Width", "/Height", "/BitsPerComponent"))
    if not width or not height or width <= 0 or height <= 0 or bits not in (1, 2, 4, 8, 16):
        return None, "Größe oder Farbtiefe"
    colors = _colors(image.get("/ColorSpace"))
    if colors is None:
        return None, "Farbraum"
    components, white = colors
    png = False
    if isinstance(parms, pikepdf.Dictionary):
        predictor = _number(parms.get("/Predictor", 1))
        if predictor is not None and predictor >= 10:
            expected = (components, bits, width)
            found = tuple(_number(parms.get(key, default)) for key, default in (("/Colors", 1), ("/BitsPerComponent", 8), ("/Columns", 1)))
            if found != expected:
                return None, "Prädiktor"
            png = True
        elif predictor != 1:
            return None, "Prädiktor"
    fmt = ImageFormat(width, height, (width * components * bits + 7) // 8, png, white)
    if fmt.size > MAX_IMAGE:
        return None, "zu groß"
    return fmt, ""


# --- Dokument ---------------------------------------------------------------------------------------------------------


@dataclass
class Rescue:
    """Ergebnis je Objektnummer und Art (``CONTENT``, ``IMAGE``, ``OTHER``)."""

    partial: dict[int, str] = field(default_factory=dict)  # nur der lesbare Teil übernommen
    restored: dict[int, str] = field(default_factory=dict)  # vollständig gelesen und neu geschrieben
    kept: dict[int, str] = field(default_factory=dict)  # beschädigt, unverändert übernommen

    @property
    def changed(self) -> bool:
        return bool(self.partial or self.restored)


def count(found: dict[int, str], kind: str) -> int:
    """Wie viele Datenströme einer Art (``CONTENT``, ``IMAGE``, ``OTHER``)."""
    return sum(1 for value in found.values() if value == kind)


def _filters(stream) -> tuple[list[str], list]:
    """(Filter, DecodeParms je Filter) eines Datenstroms."""
    import pikepdf

    value = stream.get("/Filter")
    if isinstance(value, pikepdf.Name):
        filters = [str(value)]
    elif isinstance(value, pikepdf.Array):
        filters = [str(item) for item in value]
    else:
        filters = []
    parms = stream.get("/DecodeParms")
    if isinstance(parms, pikepdf.Array):
        listed = list(parms)
    else:
        listed = [parms] if len(filters) == 1 else []
    return filters, listed + [None] * (len(filters) - len(listed))


def _content_streams(pdf, technical: list[str]) -> set[tuple[int, int]]:
    """Inhaltsströme der Seiten und Erscheinungsbilder der Anmerkungen (Formulare erkennt /Subtype)."""
    import pikepdf

    found: set[tuple[int, int]] = set()
    for index, page in enumerate(pdf.pages):
        try:
            contents = page.obj.get("/Contents")
            items = list(contents) if isinstance(contents, pikepdf.Array) else [contents]
            annots = page.obj.get("/Annots")
            for annot in annots if isinstance(annots, pikepdf.Array) else []:
                appearance = annot.get("/AP") if isinstance(annot, pikepdf.Dictionary) else None
                if not isinstance(appearance, pikepdf.Dictionary):
                    continue
                for key in ("/N", "/R", "/D"):
                    value = appearance.get(key)
                    items += list(value.values()) if isinstance(value, pikepdf.Dictionary) else [value]
            found.update(item.objgen for item in items if isinstance(item, pikepdf.Stream) and item.is_indirect)
        except (pikepdf.PdfError, ValueError, TypeError) as exc:
            technical.append(f"Seite {index + 1}: Inhaltsströme nicht vollständig bestimmbar ({type(exc).__name__})")
    return found


def _masks(pdf) -> set[tuple[int, int]]:
    """Bilder, die anderen als Maske dienen (/SMask, /Mask) – fehlende Zeilen wären dort nicht »weiß«."""
    import pikepdf

    found = set()
    for obj in pdf.objects:
        if isinstance(obj, pikepdf.Stream) and obj.get("/Subtype") == "/Image":
            for key in ("/SMask", "/Mask"):
                mask = obj.get(key)
                if isinstance(mask, pikepdf.Stream) and mask.is_indirect:
                    found.add(mask.objgen)
    return found


def _rescue_content(stream, raw: bytes, filters: list[str], parms: list, number: int, technical: list[str]) -> str | None:
    """Inhaltsstrom retten: »restored«, »partial« oder ``None`` (nichts Lesbares)."""
    import pikepdf

    flate = parms[-1] if parms else None
    decoded = None
    if not isinstance(flate, pikepdf.Dictionary) or _number(flate.get("/Predictor", 1)) == 1:
        decoded = decode(raw, filters, MAX_CONTENT)  # ein Prädiktor in einem Inhaltsstrom wird nicht geraten
    if decoded is None:
        technical.append(f"Datenstrom {number} ({CONTENT}): Filter oder Prädiktor nicht sicher lesbar – unverändert übernommen")
        return None
    if decoded.complete:
        stream.write(decoded.data)
        technical.append(f"Datenstrom {number} ({CONTENT}): vollständig gelesen ({len(decoded.data)} Byte), neu geschrieben")
        return "restored"
    cut = cut_content(decoded.data)
    if cut is None:
        technical.append(f"Datenstrom {number} ({CONTENT}): {len(decoded.data)} Byte lesbar, aber kein vollständiger Befehl")
        return None
    stream.write(cut.data)
    closed = f", geschlossen: {' '.join(cut.closed)}" if cut.closed else ""
    technical.append(f"Datenstrom {number} ({CONTENT}): {len(decoded.data)} Byte lesbar, {cut.operators} Befehle übernommen{closed}")
    return "partial"


def _rescue_image(stream, raw: bytes, filters: list[str], parms: list, number: int, masks: set, technical: list[str]) -> str | None:
    """Bild retten, wenn das sicher geht: »restored«, »partial« oder ``None``."""
    import pikepdf

    flate = parms[-1] if parms else None
    fmt, reason = (None, "dient als Maske") if stream.objgen in masks else image_format(stream, flate)
    decoded = decode(raw, filters, fmt.size, guess=False) if fmt is not None else None
    if fmt is None or decoded is None:
        technical.append(f"Datenstrom {number} ({IMAGE}): nicht sicher zu retten ({reason or 'Filter'}) – unverändert übernommen")
        return None
    if decoded.complete and len(decoded.data) >= fmt.size:
        data, outcome = decoded.data[: fmt.size], "restored"
        technical.append(f"Datenstrom {number} ({IMAGE}): vollständig gelesen, neu geschrieben")
    else:
        padded = pad_rows(decoded.data, fmt)
        if padded is None:
            technical.append(f"Datenstrom {number} ({IMAGE}): keine ganze Bildzeile lesbar – unverändert übernommen")
            return None
        (data, rows), outcome = padded, "partial"
        technical.append(f"Datenstrom {number} ({IMAGE}): {rows} von {fmt.height} Zeilen gerettet, Rest weiß aufgefüllt")
    # Neu geschrieben nur mit Flate; ein PNG-Prädiktor bleibt (die Zeilen enthalten seine Filter-Bytes)
    keep = pikepdf.Dictionary({key: flate[key] for key in ("/Predictor", "/Colors", "/BitsPerComponent", "/Columns") if key in flate}) if fmt.png else None
    stream.write(zlib.compress(data), filter=pikepdf.Name.FlateDecode, decode_parms=keep)
    return outcome


def _broken(stream) -> tuple[bytes, list[str], list, bytes] | None:
    """(Rohdaten, Filter, DecodeParms, Flate-Daten), wenn der Datenstrom Flate-Daten enthält, die sich
    nicht vollständig dekodieren lassen – sonst ``None`` (auch bei anderen Filtern vor Flate: nichts raten)."""
    filters, parms = _filters(stream)
    if not any(name in FLATE for name in filters):
        return None
    raw = stream.read_raw_bytes()
    if not raw.strip():
        return None  # leerer Datenstrom (z. B. eine leere Seite): nichts zu dekodieren, nichts fehlt
    layer = flate_layer(raw, filters)
    if layer is None or flate_ok(layer):
        return None
    return raw, filters, parms, layer


def _kind(stream, contents: set) -> str:
    subtype = stream.get("/Subtype")
    if stream.objgen in contents or subtype == "/Form":
        return CONTENT
    return IMAGE if subtype == "/Image" else OTHER


def damaged(pdf, technical: list[str]) -> tuple[dict[int, str], set[int]]:
    """Nur prüfen: Flate-Datenströme, die sich nicht vollständig dekodieren lassen (Objektnummer → Art),
    und darunter die, denen nur die Prüfsumme am Ende fehlt (vollständig lesbar, werden neu geschrieben).
    Erkennt auch Ströme, die qpdf beim Neuschreiben stillschweigend gekürzt übernähme (z. B. ASCII85
    und Flate, abgeschnitten)."""
    import pikepdf

    contents = _content_streams(pdf, technical)
    found: dict[int, str] = {}
    restorable: set[int] = set()
    for obj in pdf.objects:
        if not isinstance(obj, pikepdf.Stream):
            continue
        number = obj.objgen[0]
        try:
            broken = _broken(obj)
            if broken is not None:
                found[number] = _kind(obj, contents)
                if flate_complete(broken[3]):
                    restorable.add(number)
        except (pikepdf.PdfError, ValueError, TypeError) as exc:
            technical.append(f"Datenstrom {number}: Filterdaten nicht lesbar ({type(exc).__name__})")
            found[number] = OTHER
    # Wortwahl »Filterdaten«: die Meldung zählt als Befund »Datenströme« (``engine._RULES``)
    for number, kind in list(found.items())[:20]:
        state = "ohne Prüfsumme am Ende, sonst vollständig" if number in restorable else "unvollständig oder beschädigt"
        technical.append(f"Datenstrom {number} ({kind}): Filterdaten {state}")
    return found, restorable


def _rescue_stream(stream, number: int, contents: set, masks: set, technical: list[str]) -> tuple[str, str | None] | None:
    """Einen Datenstrom prüfen und, falls beschädigt, retten: (Art, Ergebnis) – ``None``: lesbar."""
    broken = _broken(stream)
    if broken is None:
        return None
    raw, filters, parms, _layer = broken
    kind = _kind(stream, contents)
    if kind == CONTENT:
        return kind, _rescue_content(stream, raw, filters, parms, number, technical)
    if kind == IMAGE:
        return kind, _rescue_image(stream, raw, filters, parms, number, masks, technical)
    technical.append(f"Datenstrom {number}: beschädigt – unverändert übernommen")
    return kind, None


def rescue(pdf, technical: list[str], only: set[int] | None = None) -> Rescue:
    """Beschädigte Flate-Datenströme des geöffneten Dokuments retten, soweit sicher (ändert ``pdf``).
    ``only``: nur diese Objekte prüfen (schon bekannt aus ``damaged`` für dasselbe Dokument)."""
    import pikepdf

    result = Rescue()
    if only is not None and not only:
        return result
    contents = _content_streams(pdf, technical)
    masks = _masks(pdf)
    for obj in pdf.objects:
        if not isinstance(obj, pikepdf.Stream):
            continue
        number = obj.objgen[0]
        if only is not None and number not in only:
            continue
        try:
            found = _rescue_stream(obj, number, contents, masks, technical)
        except (pikepdf.PdfError, ValueError, TypeError) as exc:
            technical.append(f"Datenstrom {number}: nicht lesbar ({type(exc).__name__}) – unverändert übernommen")
            found = OTHER, None
        if found is None:
            continue
        kind, outcome = found
        if outcome == "partial":
            result.partial[number] = kind
        elif outcome == "restored":
            result.restored[number] = kind
        else:
            result.kept[number] = kind
    return result
