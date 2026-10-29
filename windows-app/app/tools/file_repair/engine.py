"""Analyse und Reparatur von Office-Dateien, Bildern und Text/CSV.

Office (ZIP-Formate: docx, xlsx, pptx, odt, ods, odp …)
    Die Teile werden aus dem Inhaltsverzeichnis des Archivs gelesen, fehlt oder ist es kaputt, direkt aus den
    lokalen Köpfen (»PK\\3\\4«) – auch aus einer abgeschnittenen Datei. Abgeschnittene XML-Teile werden bis zum
    letzten vollständigen Element übernommen und sauber geschlossen. Danach wird neu verpackt (ODF: »mimetype«
    zuerst und unkomprimiert) und – wenn LibreOffice da ist – von LibreOffice geöffnet und neu gespeichert.
Ältere Office-Formate (doc, xls, ppt, rtf)
    Nur LibreOffice kann sie lesen: Es öffnet die Datei (mit seiner eigenen Fehlertoleranz) und speichert neu.
Bilder (jpg, png, gif, bmp, tiff, webp)
    Pillow liest auch abgeschnittene Bilder; der fehlende Rest wird grau. Gespeichert wird im Format der Endung –
    das repariert auch Bilder mit falscher Endung.
Text und CSV
    Gemischte oder falsche Zeichenkodierung (UTF-8, Windows-1252, UTF-16 ohne Kennung), Nullbytes und
    Steuerzeichen, gemischte Zeilenenden. Ergebnis: UTF-8 (CSV mit BOM, damit Excel Umlaute richtig liest).

Das Original wird nie verändert; die Ausgabe liegt im Arbeitsordner und wird wie bei PDFs übernommen.
"""

from __future__ import annotations

import hashlib
import os
import re
import struct
import zipfile
import zlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable
from xml.parsers import expat

from tools.pdf_repair.models import Check, Condition, Method, PdfAnalysis, PdfRepairResult, RepairMode, RepairStatus

Progress = Callable[..., None]

ZIP_OFFICE = (".docx", ".docm", ".dotx", ".xlsx", ".xlsm", ".xltx", ".pptx", ".pptm", ".potx", ".odt", ".ods", ".odp", ".ott", ".ots", ".otp")
LEGACY_OFFICE = (".doc", ".xls", ".ppt", ".rtf")
IMAGES = (".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tif", ".tiff", ".webp")
TEXTS = (".txt", ".csv")
SUFFIXES = ZIP_OFFICE + LEGACY_OFFICE + IMAGES + TEXTS
ENGINE = "Novadesk Dateireparatur"
MAX_PART = 512 * 1024 * 1024  # größter Teil eines Archivs, der entpackt wird (Schutz vor »ZIP-Bomben«)
MAX_TEXT = 256 * 1024 * 1024
OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
IMAGE_FORMATS = {".jpg": "JPEG", ".jpeg": "JPEG", ".png": "PNG", ".gif": "GIF", ".bmp": "BMP", ".tif": "TIFF", ".tiff": "TIFF", ".webp": "WEBP"}
NO_OFFICE = "LibreOffice fehlt – ohne LibreOffice lässt sich diese Dateiart nicht reparieren."


def handles(path: str | os.PathLike) -> bool:
    """Datei für dieses Modul (und nicht für die PDF-Reparatur)?"""
    return Path(path).suffix.lower() in SUFFIXES


def _noop(*_args) -> None:
    pass


def _digest(path: Path) -> tuple[int, float, str]:
    stat = os.stat(path)
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return stat.st_size, stat.st_mtime, digest.hexdigest()


def _kind(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in ZIP_OFFICE:
        return "zip"
    if suffix in LEGACY_OFFICE:
        return "legacy"
    if suffix in IMAGES:
        return "image"
    return "text"


def _office_available() -> bool:
    try:
        from tools.pdf_editor import office

        return office.libreoffice() is not None
    except Exception:  # noqa: BLE001
        return False


# --- Analyse -----------------------------------------------------------------------------------------------------
def analyze(path: str | os.PathLike, password: str | None = None, progress: Progress | None = None) -> PdfAnalysis:
    del password  # Office-Kennwörter: LibreOffice fragt nicht – verschlüsselte Dateien meldet die Analyse
    progress = progress or _noop
    path = Path(path)
    result = PdfAnalysis(path=str(path), engine=ENGINE)
    progress("hash")
    try:
        result.size, result.mtime, result.sha256 = _digest(path)
    except OSError as exc:
        result.error = f"Die Datei kann nicht gelesen werden ({exc.strerror or exc})."
        return result
    if result.size == 0:
        result.error = "Die Datei ist leer."
        result.checks.append(Check("size", "Inhalt", False, "Datei ist leer"))
        return result
    progress("open")
    kind = _kind(path)
    if kind == "zip":
        _analyze_zip(path, result)
    elif kind == "legacy":
        _analyze_legacy(path, result)
    elif kind == "image":
        _analyze_image(path, result)
    else:
        _analyze_text(path, result)
    result.repairable = result.condition not in (Condition.UNREADABLE, Condition.ENCRYPTED)
    return result


# ZIP-Formate ------------------------------------------------------------------------------------------------------
@dataclass
class _Part:
    name: str
    data: bytes
    complete: bool = True  # vollständig entpackt (Prüfsumme stimmt)
    salvaged: bool = False  # abgeschnittener XML-Teil, sauber geschlossen


@dataclass
class _Archive:
    parts: dict[str, _Part] = field(default_factory=dict)
    directory: bool = False  # Inhaltsverzeichnis lesbar
    broken: list[str] = field(default_factory=list)  # Teile mit Fehlern (Prüfsumme, nicht entpackbar)
    lost: list[str] = field(default_factory=list)  # Teile, die sich nicht retten ließen
    encrypted: bool = False


def _main_parts(suffix: str) -> tuple[str, ...]:
    if suffix in (".docx", ".docm", ".dotx"):
        return ("[Content_Types].xml", "word/document.xml")
    if suffix in (".xlsx", ".xlsm", ".xltx"):
        return ("[Content_Types].xml", "xl/workbook.xml")
    if suffix in (".pptx", ".pptm", ".potx"):
        return ("[Content_Types].xml", "ppt/presentation.xml")
    return ("mimetype", "content.xml")


def _is_xml(name: str) -> bool:
    return name.lower().endswith((".xml", ".rels", ".vml")) or name == "[Content_Types].xml"


def _xml_ok(data: bytes) -> bool:
    parser = expat.ParserCreate()
    try:
        parser.Parse(data, True)
        return True
    except expat.ExpatError:
        return False


def _salvage_xml(data: bytes) -> bytes | None:
    """Abgeschnittenes oder beschädigtes XML: bis zum letzten vollständigen Element übernehmen, offene Elemente
    schließen. ``None``, wenn nicht einmal das Wurzelelement lesbar ist."""
    stack: list[str] = []
    last = {"pos": 0, "stack": []}
    parser = expat.ParserCreate()

    def start(name, _attrs):
        stack.append(name)

    def end(_name):
        stack.pop()
        last["pos"] = parser.CurrentByteIndex
        last["stack"] = list(stack)

    parser.StartElementHandler = start
    parser.EndElementHandler = end
    try:
        parser.Parse(data, True)
        return data
    except expat.ExpatError:
        pass
    if not last["stack"] and last["pos"] == 0:
        return None
    # CurrentByteIndex zeigt beim Ende-Ereignis auf den Anfang des schließenden Tags
    cut = data.find(b">", last["pos"])
    if cut < 0:
        return None
    body = data[: cut + 1]
    closing = b"".join(f"</{name}>".encode("utf-8") for name in reversed(last["stack"]))
    repaired = body + closing
    return repaired if _xml_ok(repaired) else None


def _read_directory(path: Path, archive: _Archive) -> None:
    try:
        with zipfile.ZipFile(path) as source:
            archive.directory = True
            for info in source.infolist():
                if info.is_dir():
                    continue
                if info.flag_bits & 0x1:
                    archive.encrypted = True
                    continue
                if info.file_size > MAX_PART:
                    archive.lost.append(info.filename)
                    continue
                try:
                    data = source.read(info)
                    archive.parts[info.filename] = _Part(info.filename, data)
                except (zipfile.BadZipFile, zlib.error, OSError, EOFError, NotImplementedError, ValueError):
                    archive.broken.append(info.filename)
    except (zipfile.BadZipFile, OSError, ValueError, EOFError):
        archive.directory = False


def _inflate(raw: bytes, method: int) -> tuple[bytes, bool]:
    """(Daten, vollständig) – Deflate auch aus einem abgeschnittenen Datenstrom, soweit lesbar."""
    if method == 0:
        return raw, True
    if method != 8:
        return b"", False
    inflater = zlib.decompressobj(-15)
    out = bytearray()
    try:
        for start in range(0, len(raw), 1 << 16):
            out += inflater.decompress(raw[start:start + (1 << 16)], MAX_PART - len(out))
            if inflater.eof or len(out) >= MAX_PART:
                break
    except zlib.error:
        return bytes(out), False
    return bytes(out), inflater.eof


def _scan_local(path: Path, archive: _Archive) -> None:
    """Teile direkt aus den lokalen Köpfen lesen – ohne Inhaltsverzeichnis (abgeschnittene oder kaputte Datei)."""
    data = path.read_bytes()
    position = 0
    while True:
        start = data.find(b"PK\x03\x04", position)
        if start < 0 or start + 30 > len(data):
            break
        try:
            _sig, _ver, flags, method, _time, _date, crc, csize, _usize, nlen, xlen = struct.unpack("<IHHHHHIIIHH", data[start:start + 30])
        except struct.error:
            break
        name_start = start + 30
        name = data[name_start:name_start + nlen].decode("cp437" if not flags & 0x800 else "utf-8", "replace")
        body = name_start + nlen + xlen
        position = start + 4
        if not name or name.endswith("/") or name in archive.parts:
            continue
        if flags & 0x1:
            archive.encrypted = True
            continue
        if flags & 0x8 or csize == 0 or body + csize > len(data):
            # Größe steht erst danach (oder Datei abgeschnitten): bis zum nächsten Kopf bzw. Dateiende
            following = data.find(b"PK\x03\x04", body)
            raw = data[body:following if following > 0 else len(data)]
        else:
            raw = data[body:body + csize]
        content, complete = _inflate(raw, method)
        if method == 0 and not flags & 0x8 and complete:
            complete = (zlib.crc32(content) & 0xFFFFFFFF) == crc
        if not content and not complete:
            archive.lost.append(name)
            continue
        archive.parts[name] = _Part(name, content, complete)
        position = body + max(len(raw), 1)


def _collect(path: Path) -> _Archive:
    archive = _Archive()
    _read_directory(path, archive)
    if not archive.directory or archive.broken:
        scanned = _Archive()
        _scan_local(path, scanned)
        for name, part in scanned.parts.items():
            if name not in archive.parts:
                archive.parts[name] = part
        archive.encrypted = archive.encrypted or scanned.encrypted
        archive.lost += [name for name in scanned.lost if name not in archive.parts]
        archive.broken = [name for name in archive.broken if name not in archive.parts or not archive.parts[name].complete]
    for name, part in list(archive.parts.items()):
        if _is_xml(name) and not _xml_ok(part.data):
            salvaged = _salvage_xml(part.data)
            if salvaged is None:
                del archive.parts[name]
                archive.lost.append(name)
            else:
                archive.parts[name] = _Part(name, salvaged, False, True)
    archive.lost = sorted(set(archive.lost) - set(archive.parts))
    return archive


def _analyze_zip(path: Path, result: PdfAnalysis) -> None:
    archive = _collect(path)
    main = _main_parts(path.suffix.lower())
    damaged = [part.name for part in archive.parts.values() if not part.complete or part.salvaged]
    result.checks.append(Check("directory", "Inhaltsverzeichnis", archive.directory, "lesbar" if archive.directory else "fehlt oder ist beschädigt"))
    result.checks.append(Check("parts", "Teile der Datei", not damaged and not archive.lost,
                               f"{len(archive.parts)} lesbar" + (f", {len(damaged)} beschädigt" if damaged else "") + (f", {len(archive.lost)} verloren" if archive.lost else "")))
    missing = [name for name in main if name not in archive.parts]
    result.checks.append(Check("main", "Hauptinhalt", not missing and not any(name in damaged for name in main),
                               "vorhanden" if not missing else "fehlt"))
    if archive.encrypted and not archive.parts:
        result.condition = Condition.UNREADABLE
        result.error = "Die Datei ist mit einem Kennwort geschützt und lässt sich nicht reparieren."
        return
    if not archive.parts or main[1] in missing:
        result.condition = Condition.UNREADABLE
        result.error = "In der Datei ist kein lesbarer Inhalt mehr."
        return
    if archive.directory and not damaged and not archive.lost and not archive.broken:
        result.condition = Condition.HEALTHY
        return
    if damaged or archive.broken:
        result.structural_errors.append(f"{len(damaged) or len(archive.broken)} Teile beschädigt (z. B. abgeschnitten).")
    if not archive.directory:
        result.structural_errors.append("Das Inhaltsverzeichnis der Datei fehlt – die Teile werden direkt gesucht.")
    if archive.lost:
        result.structural_errors.append(f"{len(archive.lost)} Teile lassen sich nicht mehr lesen.")
    heavy = archive.lost or any(name in damaged for name in main)
    result.condition = Condition.DAMAGED if heavy else Condition.REPAIRABLE


def _write_zip(archive: _Archive, target: Path, suffix: str) -> None:
    names = list(archive.parts)
    odf = suffix.startswith((".od", ".ot"))
    first = "mimetype" if odf else "[Content_Types].xml"
    if first in names:
        names.remove(first)
        names.insert(0, first)
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as out:
        for name in names:
            stored = odf and name == "mimetype"
            out.writestr(zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0)) if not stored else zipfile.ZipInfo(name), archive.parts[name].data,
                         compress_type=zipfile.ZIP_STORED if stored else zipfile.ZIP_DEFLATED)


def _resave(source: Path, target: Path, technical: list[str]) -> bool:
    """Von LibreOffice öffnen und im selben Format speichern lassen."""
    from tools.convert import jobs
    from tools.pdf_editor import office

    suffix = source.suffix.lower().lstrip(".")
    convert_to = jobs.WRITER.get(suffix) or jobs.CALC.get(suffix) or jobs.IMPRESS.get(suffix) or suffix
    try:
        office.convert_file(source, target, convert_to)
        return target.is_file() and target.stat().st_size > 0
    except Exception as exc:  # noqa: BLE001 - LibreOffice konnte die Datei nicht lesen
        technical.append(f"LibreOffice: {type(exc).__name__}")
        target.unlink(missing_ok=True)
        return False


def _repair_zip(path: Path, work: Path, mode: RepairMode, result: PdfRepairResult, progress: Progress) -> None:
    progress("zip_scan")
    archive = _collect(path)
    main = _main_parts(path.suffix.lower())
    if not archive.parts or main[1] not in archive.parts:
        result.error = "In der Datei ist kein lesbarer Inhalt mehr." if not archive.encrypted else "Die Datei ist mit einem Kennwort geschützt."
        return
    progress("zip_rebuild")
    rebuilt = work / f"neu-verpackt{path.suffix.lower()}"
    _write_zip(archive, rebuilt, path.suffix.lower())
    damaged = [part.name for part in archive.parts.values() if not part.complete or part.salvaged]
    actions = ["Teile der Datei gelesen" + (" (ohne Inhaltsverzeichnis)" if not archive.directory else ""), "Datei neu verpackt"]
    if damaged:
        actions.insert(1, f"{len(damaged)} beschädigte Teile bis zur Bruchstelle übernommen")
    output, method = rebuilt, Method.ZIP_REBUILD
    if _office_available():
        progress("office_resave")
        resaved = work / f"repariert{path.suffix.lower()}"
        if _resave(rebuilt, resaved, result.technical):
            output, method = resaved, Method.OFFICE_RESAVE
            actions.append("Von LibreOffice geöffnet und neu gespeichert")
    progress("validate")
    try:
        with zipfile.ZipFile(output) as check:
            bad = check.testzip()
    except zipfile.BadZipFile:
        bad = "?"
    if bad is not None:
        result.error = "Die reparierte Datei ließ sich nicht prüfen."
        return
    result.output_path, result.method, result.repair_actions = str(output), method, actions
    result.size_after = output.stat().st_size
    if damaged or archive.lost:
        result.status = RepairStatus.PARTIALLY_RECOVERED
        result.warnings.append("Teile der Datei waren beschädigt – Inhalte am Ende einzelner Teile können fehlen. Bitte das Ergebnis prüfen.")
        if archive.lost:
            result.warnings.append(f"{len(archive.lost)} Teile ließen sich nicht retten (z. B. Bilder oder Formatvorlagen).")
    else:
        result.status = RepairStatus.REPAIRED
    del mode


# Ältere Office-Formate ---------------------------------------------------------------------------------------------
def _analyze_legacy(path: Path, result: PdfAnalysis) -> None:
    with open(path, "rb") as handle:
        head = handle.read(16)
    if path.suffix.lower() == ".rtf":
        ok = head.lstrip().startswith(b"{\\rtf")
        result.checks.append(Check("header", "RTF-Kennung", ok, "vorhanden" if ok else "nicht gefunden"))
    else:
        ok = head.startswith(OLE_MAGIC)
        result.checks.append(Check("header", "Office-Kennung", ok, "vorhanden" if ok else "nicht gefunden"))
    office = _office_available()
    result.checks.append(Check("office", "LibreOffice", office, "vorhanden" if office else "fehlt"))
    if not ok:
        if head.startswith(b"PK\x03\x04"):
            result.warnings.append("Die Datei ist eigentlich eine neuere Office-Datei (ZIP) mit falscher Endung.")
            result.condition = Condition.REPAIRABLE if office else Condition.UNREADABLE
        else:
            result.condition = Condition.DAMAGED if office else Condition.UNREADABLE
            result.structural_errors.append("Der Anfang der Datei ist beschädigt.")
    else:
        result.condition = Condition.HEALTHY
    if not office:
        result.error = NO_OFFICE
        result.condition = Condition.UNREADABLE if not ok else result.condition
    else:
        result.warnings.append("Ältere Office-Formate prüft Novadesk nur grob. »Neu aufbauen« lässt LibreOffice die Datei öffnen und neu speichern.")


def _repair_legacy(path: Path, work: Path, result: PdfRepairResult, progress: Progress) -> None:
    if not _office_available():
        result.error = NO_OFFICE
        return
    progress("office_resave")
    source = path
    with open(path, "rb") as handle:
        head = handle.read(4)
    if head.startswith(b"PK\x03\x04"):  # neuere Office-Datei mit alter Endung: unter passender Endung lesen
        modern = {".doc": ".docx", ".xls": ".xlsx", ".ppt": ".pptx", ".rtf": ".docx"}[path.suffix.lower()]
        source = work / f"quelle{modern}"
        source.write_bytes(path.read_bytes())
    target = work / f"repariert{path.suffix.lower()}"
    copy = work / f"eingabe{path.suffix.lower()}" if source == path else source
    if source == path:
        copy.write_bytes(path.read_bytes())
    from tools.convert import jobs
    from tools.pdf_editor import office

    suffix = path.suffix.lower().lstrip(".")
    convert_to = {"doc": "doc:MS Word 97", "xls": "xls:MS Excel 97", "ppt": "ppt:MS PowerPoint 97", "rtf": jobs.WRITER["rtf"]}[suffix]
    try:
        office.convert_file(copy, target, convert_to)
    except Exception as exc:  # noqa: BLE001
        result.technical.append(f"LibreOffice: {type(exc).__name__}")
        result.error = "LibreOffice konnte die Datei nicht lesen – sie ist zu stark beschädigt."
        return
    progress("validate")
    if not target.is_file() or target.stat().st_size == 0:
        result.error = "LibreOffice konnte die Datei nicht lesen – sie ist zu stark beschädigt."
        return
    result.output_path, result.method = str(target), Method.OFFICE_RESAVE
    result.size_after = target.stat().st_size
    result.repair_actions = ["Von LibreOffice geöffnet und neu gespeichert"]
    result.status = RepairStatus.REPAIRED


# Bilder -------------------------------------------------------------------------------------------------------------
def _open_image(path: Path, truncated: bool):
    from PIL import Image, ImageFile

    before = ImageFile.LOAD_TRUNCATED_IMAGES
    ImageFile.LOAD_TRUNCATED_IMAGES = truncated
    try:
        image = Image.open(path)
        image.load()
        return image
    finally:
        ImageFile.LOAD_TRUNCATED_IMAGES = before


def _analyze_image(path: Path, result: PdfAnalysis) -> None:
    from PIL import Image, UnidentifiedImageError

    try:
        with Image.open(path) as probe:
            actual = probe.format or ""
            result.checks.append(Check("format", "Bildformat", True, f"{actual}, {probe.width} × {probe.height} Pixel"))
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
        result.checks.append(Check("format", "Bildformat", False, "nicht erkannt"))
        result.condition = Condition.UNREADABLE
        result.error = "Die Datei ist kein lesbares Bild (mehr)."
        return
    expected = IMAGE_FORMATS[path.suffix.lower()]
    if actual and actual != expected:
        result.warnings.append(f"Die Datei ist eigentlich ein {actual}-Bild – die Reparatur speichert sie als {expected}.")
    try:
        _open_image(path, False).close()
        result.checks.append(Check("data", "Bilddaten", True, "vollständig"))
        result.condition = Condition.HEALTHY if actual == expected else Condition.REPAIRABLE
    except (OSError, ValueError, SyntaxError) as exc:
        result.technical.append(f"Pillow: {type(exc).__name__}: {str(exc)[:120]}")
        try:
            _open_image(path, True).close()
        except (OSError, ValueError, SyntaxError):
            result.checks.append(Check("data", "Bilddaten", False, "nicht lesbar"))
            result.condition = Condition.UNREADABLE
            result.error = "Die Bilddaten sind nicht mehr lesbar."
            return
        result.checks.append(Check("data", "Bilddaten", False, "unvollständig (abgeschnitten)"))
        result.structural_errors.append("Das Bild ist unvollständig – der fehlende Teil wird grau gefüllt.")
        result.condition = Condition.DAMAGED


def _repair_image(path: Path, work: Path, result: PdfRepairResult, progress: Progress) -> None:
    from PIL import Image

    progress("image_resave")
    try:
        _open_image(path, False).close()
        complete = True
    except (OSError, ValueError, SyntaxError):
        complete = False
    try:
        image = _open_image(path, True)
    except (OSError, ValueError, SyntaxError, Image.DecompressionBombError):
        result.error = "Die Bilddaten sind nicht mehr lesbar."
        return
    fmt = IMAGE_FORMATS[path.suffix.lower()]
    target = work / f"repariert{path.suffix.lower()}"
    try:
        frames = getattr(image, "n_frames", 1) if complete else 1
        if fmt == "JPEG" and image.mode not in ("RGB", "L", "CMYK"):
            image = image.convert("RGB")
        elif fmt == "BMP" and image.mode not in ("RGB", "L", "1", "P"):
            image = image.convert("RGB")
        options = {"quality": 95} if fmt in ("JPEG", "WEBP") else {}
        if image.info.get("icc_profile"):
            options["icc_profile"] = image.info["icc_profile"]
        if frames > 1 and fmt in ("GIF", "TIFF", "WEBP"):
            image.save(target, fmt, save_all=True, **options)
        else:
            image.save(target, fmt, **options)
    except (OSError, ValueError) as exc:
        result.technical.append(f"Pillow: {type(exc).__name__}")
        result.error = "Das Bild ließ sich nicht neu speichern."
        return
    finally:
        image.close()
    progress("validate")
    try:
        _open_image(target, False).close()
    except (OSError, ValueError, SyntaxError):
        result.error = "Das reparierte Bild ließ sich nicht prüfen."
        return
    result.output_path, result.method = str(target), Method.IMAGE_RESAVE
    result.size_after = target.stat().st_size
    result.repair_actions = ["Lesbare Bilddaten übernommen", f"Als {fmt} neu gespeichert"]
    if complete:
        result.status = RepairStatus.REPAIRED
    else:
        result.status = RepairStatus.PARTIALLY_RECOVERED
        result.warnings.append("Das Bild war unvollständig – der fehlende Teil ist grau.")


# Text und CSV --------------------------------------------------------------------------------------------------------
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


@dataclass
class _TextScan:
    encoding: str = "utf-8"
    bom: bool = False
    utf16: str = ""  # »le«/»be«: UTF-16 ohne Kennung erkannt
    bad_lines: int = 0  # Zeilen, die kein gültiges UTF-8 sind (als Windows-1252 gelesen)
    nuls: int = 0
    controls: int = 0
    endings: dict[str, int] = field(default_factory=dict)

    @property
    def healthy(self) -> bool:
        return not self.utf16 and not self.bad_lines and not self.nuls and not self.controls and len([n for n in self.endings.values() if n]) <= 1


def _scan_text(data: bytes) -> tuple[_TextScan, str]:
    scan = _TextScan()
    if data.startswith(b"\xef\xbb\xbf"):
        scan.bom, data = True, data[3:]
    elif data.startswith((b"\xff\xfe", b"\xfe\xff")):
        scan.encoding = "utf-16"
        text = data.decode("utf-16", "replace")
        return _finish_scan(scan, text), text
    sample = data[: 1 << 16]
    if len(sample) >= 4 and sample.count(b"\x00") > len(sample) // 4:
        even, odd = sample[0::2].count(0), sample[1::2].count(0)
        scan.utf16 = "le" if odd > even else "be"
        text = data.decode(f"utf-16-{scan.utf16}", "replace")
        return _finish_scan(scan, text), text
    pieces = []
    for line in data.splitlines(keepends=True):
        try:
            pieces.append(line.decode("utf-8"))
        except UnicodeDecodeError:
            scan.bad_lines += 1
            pieces.append(line.decode("cp1252", "replace"))
    text = "".join(pieces)
    return _finish_scan(scan, text), text


def _finish_scan(scan: _TextScan, text: str) -> _TextScan:
    scan.nuls = text.count("\x00")
    scan.controls = len(_CONTROL.findall(text)) - scan.nuls
    crlf = text.count("\r\n")
    scan.endings = {"crlf": crlf, "lf": text.count("\n") - crlf, "cr": text.count("\r") - crlf}
    return scan


def _analyze_text(path: Path, result: PdfAnalysis) -> None:
    if result.size > MAX_TEXT:
        result.condition = Condition.UNREADABLE
        result.error = "Die Datei ist zu groß für die Reparatur."
        return
    scan, _text = _scan_text(path.read_bytes())
    result.checks.append(Check("encoding", "Zeichenkodierung", not scan.bad_lines and not scan.utf16,
                               "UTF-16 ohne Kennung" if scan.utf16 else (f"{scan.bad_lines} Zeilen nicht in UTF-8" if scan.bad_lines else ("UTF-16" if scan.encoding == "utf-16" else "UTF-8"))))
    result.checks.append(Check("controls", "Steuerzeichen", not scan.nuls and not scan.controls,
                               f"{scan.nuls + scan.controls} gefunden" if scan.nuls or scan.controls else "keine"))
    kinds = [name for name, number in scan.endings.items() if number]
    result.checks.append(Check("endings", "Zeilenenden", len(kinds) <= 1, "gemischt" if len(kinds) > 1 else "einheitlich"))
    if scan.healthy:
        result.condition = Condition.HEALTHY
        return
    if scan.bad_lines:
        result.structural_errors.append("Gemischte Zeichenkodierung – Umlaute erscheinen sonst falsch (z. B. »Ã¤« statt »ä«).")
    if scan.nuls or scan.controls:
        result.structural_errors.append("Die Datei enthält unsichtbare Steuerzeichen (z. B. Nullbytes nach einem Absturz).")
    result.condition = Condition.REPAIRABLE


def _repair_text(path: Path, work: Path, result: PdfRepairResult, progress: Progress) -> None:
    progress("text_cleanup")
    if path.stat().st_size > MAX_TEXT:
        result.error = "Die Datei ist zu groß für die Reparatur."
        return
    scan, text = _scan_text(path.read_bytes())
    actions = []
    if scan.bad_lines or scan.utf16 or scan.encoding == "utf-16":
        actions.append("Zeichenkodierung vereinheitlicht (UTF-8)")
    if scan.nuls or scan.controls:
        text = _CONTROL.sub("", text)
        actions.append(f"{scan.nuls + scan.controls} Steuerzeichen entfernt")
    dominant = max(scan.endings, key=lambda name: scan.endings[name]) if any(scan.endings.values()) else "crlf"
    if len([n for n in scan.endings.values() if n]) > 1:
        actions.append("Zeilenenden vereinheitlicht")
    newline = {"crlf": "\r\n", "lf": "\n", "cr": "\r"}[dominant]
    text = re.sub(r"\r\n|\r|\n", newline, text)
    bom = scan.bom or path.suffix.lower() == ".csv"
    target = work / f"repariert{path.suffix.lower()}"
    target.write_bytes((b"\xef\xbb\xbf" if bom else b"") + text.encode("utf-8"))
    progress("validate")
    result.output_path, result.method = str(target), Method.TEXT_CLEANUP
    result.size_after = target.stat().st_size
    result.repair_actions = actions or ["Datei neu geschrieben (UTF-8)"]
    result.status = RepairStatus.REPAIRED


# --- Reparatur ---------------------------------------------------------------------------------------------------
def repair(
    path: str | os.PathLike,
    work_dir: str | os.PathLike,
    password: str | None = None,
    mode: RepairMode = RepairMode.AUTO,
    expected_sha256: str | None = None,
    progress: Progress | None = None,
) -> PdfRepairResult:
    """Repariert ``path`` in ``work_dir`` (Ausgabe dort, mit der Endung des Originals)."""
    del password
    progress = progress or _noop
    path, work = Path(path), Path(work_dir)
    result = PdfRepairResult(status=RepairStatus.FAILED, input_path=str(path))
    progress("hash")
    try:
        size, _mtime, digest = _digest(path)
    except OSError as exc:
        result.error = f"Die Datei ist nicht mehr lesbar ({exc.strerror or exc})."
        return result
    result.size_before = size
    if expected_sha256 and digest != expected_sha256:
        result.error = "Die Datei wurde seit der Analyse verändert. Bitte erneut auswählen."
        return result
    if mode is RepairMode.RASTER:
        result.error = "Der Rettungsmodus gilt nur für PDFs."
        return result
    work.mkdir(parents=True, exist_ok=True)
    kind = _kind(path)
    try:
        if kind == "zip":
            _repair_zip(path, work, mode, result, progress)
        elif kind == "legacy":
            _repair_legacy(path, work, result, progress)
        elif kind == "image":
            _repair_image(path, work, result, progress)
        else:
            _repair_text(path, work, result, progress)
    except MemoryError:
        raise
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        result.status, result.output_path = RepairStatus.FAILED, None
        result.error = "Die Datei ließ sich nicht reparieren."
        result.technical.append(f"{type(exc).__name__}: {str(exc)[:200]}")
    if result.output_path:
        progress("finish")
    return result

