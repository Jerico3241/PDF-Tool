"""Rohanalyse: klassische PDF-Objekte direkt in den Bytes der Datei finden.

Kein vollständiger PDF-Parser – eine gezielte, defensive Suche für Dateien, die qpdf,
PDFium und pypdf nicht mehr öffnen können:

* Die Datei wird über ``mmap`` gelesen, nie vollständig in den Arbeitsspeicher kopiert.
* Ein Objektkopf »12 0 obj« zählt nur, wenn davor ein Trennzeichen steht, danach ein
  gültiger Objektanfang folgt und das Objekt mit »endobj« endet.
* Datenströme werden übersprungen (über ``/Length`` oder »endstream«): Zufällige Bytes
  »20 0 obj« in Bild- oder Schriftdaten werden nie zu einem Objekt.
* Kommt ein Objekt mehrfach vor (inkrementelle Updates), gilt die letzte vollständige
  Definition in der Datei – nicht die erste Fundstelle.
* Objekte in Objektströmen (PDF 1.5+) werden entpackt, soweit sie nur mit Flate
  komprimiert sind; andere Filter werden nicht geraten.
* Trailer-Angaben (``/Root``, ``/Info``, ``/ID``, ``/Encrypt``) werden gesammelt, damit
  später nur sichere Werte übernommen werden. Verschlüsselung wird erkannt, nie umgangen.
"""

from __future__ import annotations

import mmap
import os
import re
import zlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from ..models import RawStructure

MAX_OBJECT_NUMBER = 8_388_607  # Grenze der PDF-Norm
MAX_DICT_BYTES = 4 << 20  # so weit wird ein Wörterbuch höchstens verfolgt
MAX_PLAIN_OBJECT = 16 << 20  # Objekte ohne Datenstrom
MAX_OBJSTM_BYTES = 64 << 20  # entpackte Objektströme (Schutz vor »Zip-Bomben«)
WHITESPACE = b" \t\r\n\f\x00"
DELIMITERS = WHITESPACE + b"()<>[]{}/%"

_OBJ = re.compile(rb"(?<![0-9])(\d{1,10})[ \t\r\n\f\x00]+(\d{1,5})[ \t\r\n\f\x00]+obj(?![A-Za-z0-9_])")
_SPECIAL = re.compile(rb"[<>()%]")
_NESTING = re.compile(rb"<<|>>|\(")
_TYPE = re.compile(rb"/Type\s*/([A-Za-z]+)")
_LENGTH = re.compile(rb"/Length\s+(\d+)(\s+\d+\s+R)?")
_REF = re.compile(rb"(\d+)\s+(\d+)\s+R")
_TRAILER = re.compile(rb"(?<![A-Za-z])trailer\s*<<")
_XREF = re.compile(rb"(?<![A-Za-z0-9])xref[ \t]*\r?\n[ \t\r\n]*\d+[ \t]+\d+")
_STARTXREF = re.compile(rb"startxref\s+(\d+)")
_INT = re.compile(rb"\s*(-?\d+)")

Progress = Callable[..., None]


@dataclass
class RawObject:
    """Eine gefundene Objektdefinition (nur Positionen und Einordnung, keine Inhalte)."""

    number: int
    generation: int
    start: int  # Beginn von »N G obj« (bei Objekten aus Objektströmen: Position des Objektstroms)
    end: int  # nach »endobj«
    kind: str = ""  # Catalog, Pages, Page, ObjStm, XRef, Sig oder leer
    stream: tuple[int, int] | None = None  # Bereich der Stromdaten
    complete: bool = True
    text: bytes | None = None  # nur für entpackte Objekte aus Objektströmen
    dict_head: bytes = b""  # Wörterbuch (gekürzt) für Einordnung und Verweise

    @property
    def is_page(self) -> bool:
        return self.kind == "Page"


@dataclass
class TrailerInfo:
    root: tuple[int, int] | None = None
    info: tuple[int, int] | None = None
    id_bytes: bytes | None = None  # das /ID-Feld unverändert, z. B. b"[<ab..><ab..>]"
    encrypt: bool = False
    offset: int = 0


@dataclass
class RawScan:
    path: str
    size: int = 0
    version: str | None = None
    objects: dict[int, RawObject] = field(default_factory=dict)
    trailers: list[TrailerInfo] = field(default_factory=list)
    stats: RawStructure = field(default_factory=RawStructure)

    def of_kind(self, kind: str) -> list[RawObject]:
        return sorted((obj for obj in self.objects.values() if obj.kind == kind), key=lambda obj: obj.start)


# --- Hilfen zum Lesen der Bytes ----------------------------------------------------------------------------------


def _starts(data, prefix: bytes, pos: int) -> bool:
    """``startswith`` für ``mmap`` und ``bytes`` (mmap kennt es nicht)."""
    return data[pos : pos + len(prefix)] == prefix


def _skip_space(data, pos: int, end: int) -> int:
    while pos < end:
        byte = data[pos]
        if byte in WHITESPACE:
            pos += 1
        elif byte == 0x25:  # Kommentar bis Zeilenende
            newline = data.find(b"\n", pos, end)
            carriage = data.find(b"\r", pos, end)
            candidates = [value for value in (newline, carriage) if value >= 0]
            pos = min(candidates) + 1 if candidates else end
        else:
            break
    return pos


def _skip_string(data, pos: int, end: int) -> int:
    """Literale Zeichenkette ab »(« überspringen (Verschachtelung, Escapes). -1: kein Ende."""
    depth = 0
    index = pos
    while index < end:
        byte = data[index]
        if byte == 0x5C:  # Backslash
            index += 2
            continue
        if byte == 0x28:
            depth += 1
        elif byte == 0x29:
            depth -= 1
            if depth == 0:
                return index + 1
        index += 1
    return -1


def dict_end(data, pos: int, end: int) -> int:
    """Ende des Wörterbuchs, das bei ``pos`` mit »<<« beginnt (Offset nach »>>«), sonst -1."""
    depth = 0
    index = pos
    limit = min(end, pos + MAX_DICT_BYTES)
    while index < limit:
        match = _SPECIAL.search(data, index, limit)
        if match is None:
            return -1
        index = match.start()
        byte = data[index]
        if byte == 0x3C:  # <
            if index + 1 < limit and data[index + 1] == 0x3C:
                depth += 1
                index += 2
                continue
            close = data.find(b">", index + 1, limit)  # Hex-Zeichenkette
            if close < 0:
                return -1
            index = close + 1
        elif byte == 0x3E:  # >
            if index + 1 < limit and data[index + 1] == 0x3E:
                depth -= 1
                index += 2
                if depth == 0:
                    return index
            else:
                index += 1
        elif byte == 0x28:  # (
            index = _skip_string(data, index, limit)
            if index < 0:
                return -1
        else:  # % Kommentar
            index = _skip_space(data, index, limit)
    return -1


def top_level(head: bytes) -> bytes:
    """Nur die oberste Ebene eines Wörterbuchs – verschachtelte Wörterbücher (z. B. /Resources
    mit »/Type /Font«) bestimmen nie die Art des Objekts."""
    if head.count(b"<<") <= 1:
        return head
    out = bytearray()
    depth = 0
    index = 0
    end = len(head)
    while index < end:
        match = _NESTING.search(head, index)
        stop = match.start() if match else end
        if depth == 1:
            out += head[index:stop]
        if match is None:
            break
        token = match.group(0)
        if token == b"<<":
            depth += 1
            index = match.end()
        elif token == b">>":
            depth -= 1
            index = match.end()
        else:  # Zeichenkette: vollständig übernehmen (auf oberster Ebene) oder überspringen
            close = _skip_string(head, match.start(), end)
            close = end if close < 0 else close
            if depth == 1:
                out += head[match.start() : close]
            index = close
    return b"<<" + bytes(out) + b">>"


def _valid_start(data, pos: int, end: int) -> bool:
    """Beginnt hier plausibel ein PDF-Objekt?"""
    if pos >= end:
        return False
    byte = data[pos]
    if byte in b"<[(/+-.0123456789":
        return True
    return any(_starts(data, word, pos) for word in (b"true", b"false", b"null"))


def _kind(head: bytes) -> str:
    match = _TYPE.search(head)
    if match is None:
        if b"/FT" in head and re.search(rb"/FT\s*/Sig\b", head):
            return "Sig"
        # Seitenobjekt ohne /Type (kommt in der Praxis vor): Eltern-Verweis, Inhalt, keine Kinder
        if b"/Parent" in head and b"/Kids" not in head and (b"/Contents" in head or b"/MediaBox" in head):
            return "Page"
        return ""
    name = match.group(1).decode("ascii", "replace")
    return name if name in ("Catalog", "Pages", "Page", "ObjStm", "XRef", "Sig") else ""


def _trailer_info(head: bytes, offset: int) -> TrailerInfo:
    info = TrailerInfo(offset=offset)
    for key, attr in ((rb"/Root", "root"), (rb"/Info", "info")):
        match = re.search(key + rb"\s+(\d+)\s+(\d+)\s+R", head)
        if match:
            setattr(info, attr, (int(match.group(1)), int(match.group(2))))
    match = re.search(rb"/ID\s*(\[[^\]]{0,600}\])", head)
    if match:
        info.id_bytes = match.group(1)
    info.encrypt = b"/Encrypt" in head
    return info


def _is_encryption_dict(head: bytes) -> bool:
    return bool(re.search(rb"/Filter\s*/Standard\b", head) and re.search(rb"/O\s*[(<]", head) and re.search(rb"/U\s*[(<]", head))


# --- Objekte -------------------------------------------------------------------------------------------------------


def _parse_object(data, match: re.Match, size: int) -> tuple[RawObject | None, int]:
    """Objekt ab ``match`` lesen. Rückgabe: (Objekt oder None, Position für die weitere Suche)."""
    start = match.start()
    if start > 0 and data[start - 1] not in DELIMITERS:
        return None, match.end()
    number, generation = int(match.group(1)), int(match.group(2))
    if not 0 < number <= MAX_OBJECT_NUMBER or generation > 65535:
        return None, match.end()
    body = _skip_space(data, match.end(), size)
    if not _valid_start(data, body, size):
        return None, match.end()
    obj = RawObject(number, generation, start, start)
    if _starts(data, b"<<", body):
        close = dict_end(data, body, size)
        if close < 0:
            return None, match.end()
        head = top_level(bytes(data[body : min(close, body + 65536)]))
        obj.dict_head = head
        obj.kind = _kind(head)
        after = _skip_space(data, close, size)
        if _starts(data, b"stream", after):
            begin = after + 6
            if _starts(data, b"\r\n", begin):
                begin += 2
            elif begin < size and data[begin] in (0x0A, 0x0D):
                begin += 1
            finish = -1
            length = _LENGTH.search(head)
            if length and not length.group(2):
                candidate = begin + int(length.group(1))
                check = _skip_space(data, candidate, size) if candidate <= size else size
                if candidate <= size and _starts(data, b"endstream", check):
                    finish = candidate
                    tail = check + 9
            if finish < 0:
                found = data.find(b"endstream", begin)
                if found < 0:
                    # Abgeschnittener Datenstrom: Objekt unvollständig, Daten bis zum Ende der Datei
                    obj.stream = (begin, size)
                    obj.complete = False
                    obj.end = size
                    return obj, size
                finish = found
                while finish > begin and data[finish - 1] in (0x0A, 0x0D):
                    finish -= 1
                tail = found + 9
            obj.stream = (begin, finish)
            ending = _skip_space(data, tail, size)
            if _starts(data, b"endobj", ending):
                obj.end = ending + 6
            else:
                obj.end = tail
                obj.complete = False
            return obj, obj.end
        ending = _skip_space(data, close, size)
        if _starts(data, b"endobj", ending):
            obj.end = ending + 6
            return obj, obj.end
        obj.end = close
        obj.complete = False
        return obj, close
    # Einfaches Objekt (Zahl, Feld, Zeichenkette …): »endobj« vor dem nächsten Objektkopf
    limit = min(size, body + MAX_PLAIN_OBJECT)
    following = _OBJ.search(data, body, limit)
    bound = following.start() if following else limit
    ending = data.find(b"endobj", body, bound)
    if ending < 0:
        obj.end = bound
        obj.complete = False
        return obj, bound
    obj.end = ending + 6
    return obj, obj.end


def _object_stream_members(data, container: RawObject) -> list[RawObject]:
    """Objekte eines Objektstroms (nur Flate ohne Prädiktor – sonst nichts raten)."""
    head = container.dict_head
    if container.stream is None or not container.complete:
        return []
    if re.search(rb"/DecodeParms", head) or (b"/Filter" in head and not re.search(rb"/Filter\s*/FlateDecode\b|/Filter\s*\[\s*/FlateDecode\s*\]", head)):
        return []
    count = re.search(rb"/N\s+(\d+)", head)
    first = re.search(rb"/First\s+(\d+)", head)
    if not count or not first:
        return []
    raw = bytes(data[container.stream[0] : container.stream[1]])
    try:
        if b"/Filter" in head:
            inflater = zlib.decompressobj()
            payload = inflater.decompress(raw, MAX_OBJSTM_BYTES)
        else:
            payload = raw
    except zlib.error:
        return []
    total, begin = int(count.group(1)), int(first.group(1))
    numbers: list[tuple[int, int]] = []
    pos = 0
    for _index in range(total):
        pair = []
        for _part in range(2):
            match = _INT.match(payload, pos)
            if match is None:
                return []
            pair.append(int(match.group(1)))
            pos = match.end()
        numbers.append((pair[0], pair[1]))
    members = []
    for index, (number, offset) in enumerate(numbers):
        if not 0 < number <= MAX_OBJECT_NUMBER:
            continue
        a = begin + offset
        b = begin + numbers[index + 1][1] if index + 1 < len(numbers) else len(payload)
        text = payload[a:b].strip()
        if not text or not _valid_start(text, 0, len(text)):
            continue
        member = RawObject(number, 0, container.start, container.start, text=text)
        if text.startswith(b"<<"):
            close = dict_end(text, 0, len(text))
            member.dict_head = top_level(text[: close if close > 0 else len(text)][:65536])
            member.kind = _kind(member.dict_head)
        members.append(member)
    return members


def scan(path: str | os.PathLike, progress: Progress | None = None) -> RawScan:
    """Datei nach klassischen Objekten, Trailern, Querverweisen und Dateiende durchsuchen."""
    progress = progress or (lambda *_args: None)
    path = Path(path)
    result = RawScan(str(path))
    stats = result.stats
    with open(path, "rb") as handle:
        size = os.fstat(handle.fileno()).st_size
        result.size = size
        if size == 0:
            return result
        with mmap.mmap(handle.fileno(), 0, access=mmap.ACCESS_READ) as data:
            header = re.search(rb"%PDF-(\d\.\d)", data[:1024])
            result.version = header.group(1).decode() if header else None
            stats.eof = b"%%EOF" in data[max(0, size - 4096) :]
            stats.xref_table = _XREF.search(data) is not None
            last_startxref = None
            for match in _STARTXREF.finditer(data, max(0, size - (1 << 20))):
                last_startxref = match
            stats.startxref = last_startxref is not None
            for match in _TRAILER.finditer(data):
                close = dict_end(data, match.end() - 2, size)
                if close > 0:
                    result.trailers.append(_trailer_info(top_level(bytes(data[match.end() - 2 : close])), match.start()))
            stats.trailer = bool(result.trailers)
            # Objekte der Reihe nach; Datenströme und Objektinhalte werden übersprungen
            pos = 0
            chosen: dict[int, RawObject] = {}
            next_report = 0
            while True:
                match = _OBJ.search(data, pos)
                if match is None:
                    break
                stats.candidates += 1
                obj, pos = _parse_object(data, match, size)
                if pos >= next_report:
                    progress("raw_scan", min(0.99, pos / size))
                    next_report = pos + max(1 << 20, size // 50)
                if obj is None:
                    stats.rejected += 1
                    continue
                if obj.stream is not None:
                    stats.streams += 1
                if obj.kind == "XRef":
                    stats.xref_stream = True
                    result.trailers.append(_trailer_info(obj.dict_head, obj.start))
                    continue  # veraltete Querverweise werden neu erzeugt
                if _is_encryption_dict(obj.dict_head):
                    stats.encrypted = True
                previous = chosen.get(obj.number)
                if previous is not None:
                    stats.superseded += 1
                    if previous.complete and not obj.complete:
                        continue  # neuere, aber abgeschnittene Definition: die vollständige bleibt
                chosen[obj.number] = obj
            # Objektströme entpacken (Objekte darin gelten an der Stelle ihres Objektstroms)
            for container in [obj for obj in chosen.values() if obj.kind == "ObjStm"]:
                stats.object_streams += 1
                for member in _object_stream_members(data, container):
                    current = chosen.get(member.number)
                    if current is None or current.start < container.start:
                        chosen[member.number] = member  # die spätere Definition gilt
            if last_startxref is not None:
                offset = int(last_startxref.group(1))
                target = _skip_space(data, offset, size) if offset < size else size
                stats.startxref_valid = offset < size and (_starts(data, b"xref", target) or bool(_OBJ.match(data, target)))
    result.objects = {number: obj for number, obj in chosen.items() if obj.kind != "ObjStm" or obj.text is not None}
    stats.encrypted = stats.encrypted or any(trailer.encrypt for trailer in result.trailers)
    stats.objects = len(result.objects)
    stats.catalog = any(obj.kind == "Catalog" for obj in result.objects.values())
    stats.pages = sum(1 for obj in result.objects.values() if obj.kind == "Page")
    stats.page_nodes = sum(1 for obj in result.objects.values() if obj.kind == "Pages")
    stats.signatures = sum(1 for obj in result.objects.values() if obj.kind == "Sig")
    progress("raw_scan", 1.0)
    return result
