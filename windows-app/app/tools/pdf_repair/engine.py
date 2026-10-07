"""Analyse und Reparatur beschädigter PDF-Dateien – läuft im Arbeitsprozess (``process.py``).

Engines
-------
* **qpdf** über pikepdf: Strukturprüfung, Rekonstruktion der Querverweistabelle,
  Neu-Schreiben mit neuem Trailer und neu nummerierten Objekten.
* **PDFium** über pypdfium2: zweite Meinung beim Öffnen, Übertragen lesbarer
  Seiten, wenn qpdf eine Datei nicht verarbeiten kann, und – nur nach
  ausdrücklicher Bestätigung – der Rettungsmodus (Seiten als Bilder).
* **pypdf** (``recovery.lenient``): dritte, tolerante Engine mit eigenen Regeln.
* **Rohrekonstruktion** (``recovery.scanner``/``recovery.rebuild``): Objekte direkt in
  den Bytes finden, Querverweise, Trailer, ``startxref`` und ``%%EOF`` neu schreiben,
  bei Bedarf den Seitenbaum neu aufbauen – danach mit qpdf normalisiert.

Ablauf im Modus AUTO: qpdf neu schreiben → Seiten einzeln (qpdf) → Seiten über PDFium →
pypdf → Rohrekonstruktion. Jeder Kandidat wird geprüft; der beste gewinnt (vollständige
Seitenzahl vor Struktur vor Methode). Ein vollständiges Ergebnis beendet die Suche.

Zwei Strategien ergänzen die Stufen:

* **Fremde Daten vor bzw. nach der PDF** (``_scan``): Steht »%PDF-« erst hinter Byte 1024
  (z. B. nach einem E-Mail- oder HTTP-Kopf, HTML oder anderen Daten; gesucht wird in den ersten
  8 MB) oder folgen auf das letzte %%EOF mehr Daten, als die Engines überspringen, durchläuft
  zuerst eine Kopie nur mit den PDF-Daten alle Stufen. Ihre Kandidaten werden geprüft und
  bewertet wie alle anderen; das Original folgt, wenn sie kein vollständiges Ergebnis liefert.
* **Datenströme retten** (``recovery.streams``, Modus AUTO): Bevor qpdf eine Ausgabe schreibt
  (Stufen 2, 3a, 4 und 5), wird von Flate-Datenströmen, die sich nicht vollständig dekodieren
  lassen, der lesbare Teil übernommen – bei Inhaltsströmen bis zum letzten vollständigen Befehl,
  bei Bildern nur, wenn das sicher geht. Seiten mit beschädigten Strömen zählen als unvollständig,
  das Ergebnis höchstens als »teilweise wiederhergestellt«. Meldet die Prüfung der besten Ausgabe
  danach noch unlesbare Ströme (z. B. von PDFium unverändert übernommen), folgt derselbe Schritt
  noch einmal; diese Fassung wird wie jede Ausgabe geprüft und nur übernommen, wenn sie nichts
  verschlechtert.

Grundsätze
----------
* Die Originaldatei wird nur gelesen. Ausgaben entstehen ausschließlich im
  übergebenen Arbeitsordner; übernommen werden sie erst nach bestandener Prüfung.
* Eine Ausgabe zählt erst, wenn sie ohne Wiederherstellung erneut geöffnet,
  ihr Seitenbaum gelesen und ihre Struktur geprüft wurde.
* Meldungen enthalten weder Passwörter noch Inhalte der PDF.
"""

from __future__ import annotations

import hashlib
import io
import math
import mmap
import os
import re
import shutil
import tempfile
import warnings
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .models import Check, Condition, Method, PdfAnalysis, PdfRepairResult, RawStructure, RepairMode, RepairStatus
from .recovery import lenient, rebuild, scanner, streams

Progress = Callable[..., None]

HEAD_BYTES = 1024
TAIL_BYTES = 4096
HEADER_LIMIT = 8 << 20  # so weit wird »%PDF-« gesucht, wenn sie nicht am Anfang steht
TAIL_LIMIT = 1024  # so viele Byte nach %%EOF überspringen alle Engines (so verlangt es die PDF-Norm)
INPUT_DIR = "eingabe"  # im Arbeitsordner: Kopie der Eingabe ohne fremde Daten
CLEAN_DIR = "bereinigt"  # … und die Ausgaben der Stufen für diese Kopie
RASTER_DPI = 150
RASTER_MAX_PIXELS = 24_000_000  # je Seite – schützt vor riesigen Bitmaps
JPEG_QUALITY = 85
MAX_TECHNICAL = 300
MAX_FIELDS = 10_000
MAX_PAGE_REFS = 5_000  # je Seite untersuchte Objekte (Inhalt und Ressourcen)

FINDINGS = {
    "header": "Vor dem PDF-Anfang stehen fremde Daten (z. B. ein E-Mail- oder Webseiten-Kopf).",
    "tail": "Nach dem Dateiende (%%EOF) folgen fremde Daten.",
    "xref": "Die Querverweistabelle (xref) ist beschädigt.",
    "trailer": "Der Trailer fehlt oder ist beschädigt.",
    "streams": "Datenströme sind beschädigt oder unvollständig.",
    "content": "Seiteninhalte sind teilweise fehlerhaft.",
    "pages": "Der Seitenbaum ist fehlerhaft.",
    "eof": "Das Dateiende (%%EOF) fehlt – die Datei ist möglicherweise abgeschnitten.",
    "objects": "Objekte der Dateistruktur sind fehlerhaft.",
    "other": "Weitere Unstimmigkeiten in der Dateistruktur.",
}
ACTIONS = {
    "header": "Daten vor dem PDF-Anfang entfernt",
    "tail": "Daten nach dem Dateiende (%%EOF) entfernt",
    "xref": "Querverweistabelle neu aufgebaut",
    "trailer": "Trailer neu geschrieben",
    "streams": "Lesbare Teile beschädigter Datenströme übernommen",
    "content": "Seiteninhalte übernommen, soweit lesbar",
    "pages": "Seitenbaum neu aufgebaut",
    "objects": "Objektstruktur rekonstruiert",
    "eof": "Dateiende (%%EOF) neu geschrieben",
}
# Reihenfolge bei sonst gleichwertigen Kandidaten (höher = bevorzugt)
PRIORITY = {
    Method.REWRITE: 6,
    Method.PAGES: 5,
    Method.LENIENT: 4,
    Method.RAW_REBUILD: 3,
    Method.PAGE_TREE_REBUILD: 2,
    Method.PDFIUM: 1,
    Method.RASTER: 0,
}
_RULES = (
    ("trailer", re.compile(r"trailer", re.I)),
    ("xref", re.compile(r"xref|cross-reference|startxref", re.I)),
    ("content", re.compile(r"content stream|\bcontent\b", re.I)),
    ("streams", re.compile(r"stream|inflate|decod|filter|zlib|lzw|dct|jbig|jpx|ccitt", re.I)),
    ("pages", re.compile(r"\bpages?\b", re.I)),
    ("objects", re.compile(r"object|\bobj\b|endobj|expected|unexpected|token|dictionary|array|reference|offset", re.I)),
)
LOST_ENCRYPTION = "Die PDF ist verschlüsselt, ihre Verschlüsselungsangaben sind aber beschädigt. Ohne sie lässt sich der Inhalt nicht wiederherstellen – ein Passwortschutz wird nie umgangen."
_OBJECT_RE = re.compile(r"\bobject (\d+) (\d+)\b")
_PAGE_RE = re.compile(r"\bpage (\d+)\b", re.I)
_GENERIC = ("file is damaged",)


def _noop(*_args) -> None:
    pass


def _log():
    """Protokoll des Bereichs »repair« – im Arbeitsprozess reicht ``process`` es an die App weiter.
    Nur technische Angaben: keine Inhalte der PDF, keine Passwörter, keine Datei- oder Ordnernamen."""
    from diagnostics.applog import get

    return get("repair")


def _amount(size: int) -> str:
    """»2.880 Byte«, ab 1 MB »8,4 MB«."""
    if size < 1 << 20:
        return f"{size:,} Byte".replace(",", ".")
    return f"{size / (1 << 20):.1f} MB".replace(".", ",")


# --- Datei ---------------------------------------------------------------------------


def file_digest(path: Path) -> tuple[int, float, str]:
    """Größe, Änderungszeit und SHA-256 – blockweise gelesen, nie die ganze Datei im Speicher."""
    stat = os.stat(path)
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return stat.st_size, stat.st_mtime, digest.hexdigest()


_HEADER_RE = re.compile(rb"%PDF-(\d\.\d)")
_EOF_AFTER_RE = re.compile(rb"startxref\s+\d+\s*\Z")  # ein echtes Dateiende: startxref, Offset, %%EOF
_STRUCTURE_RE = re.compile(rb"(?<![0-9])\d{1,10}\s+\d{1,5}\s+obj\b|\bxref\b|\btrailer\b|startxref")


@dataclass
class _Scan:
    header: bool  # »%PDF-« in den ersten 1024 Byte – dort, wo die Engines sie suchen
    version: str | None
    eof: bool
    startxref: bool
    before: int = 0  # fremde Daten vor dem PDF-Anfang (»%PDF-« erst hinter Byte 1024)
    after: int = 0  # fremde Daten nach dem letzten %%EOF (mehr, als die Engines überspringen)
    size: int = 0


def _scan(path: Path, size: int) -> _Scan:
    """PDF-Kennung, Dateiende und fremde Daten davor bzw. danach – ohne die Datei in den Speicher zu lesen."""
    with open(path, "rb") as handle:
        head = handle.read(HEAD_BYTES)
        handle.seek(max(0, size - TAIL_BYTES))
        tail = handle.read()
        match = _HEADER_RE.search(head)
        found = _Scan(bool(match), match.group(1).decode() if match else None, b"%%EOF" in tail, b"startxref" in tail, size=size)
        if size == 0:
            return found
        with mmap.mmap(handle.fileno(), 0, access=mmap.ACCESS_READ) as data:
            if match is None:
                found.before, found.version = _far_header(data, size)
            found.after = _foreign_tail(data, size, found.before)
    if found.after:
        found.eof = found.startxref = True  # die PDF selbst endet regulär, danach folgen fremde Daten
    return found


def _far_header(data, size: int) -> tuple[int, str | None]:
    """»%PDF-« hinter Byte 1024 (gesucht bis HEADER_LIMIT): (Position, Version). Zählt nur, wenn davor
    keine PDF-Objekte stehen – sonst ist die Kennung am Anfang zerstört und dies z. B. eine
    eingebettete PDF."""
    match = _HEADER_RE.search(data, 0, min(size, HEADER_LIMIT))
    if match is None or _OBJ_HEADER_RE.search(data, 0, match.start()):
        return 0, None
    return match.start(), match.group(1).decode()


def _foreign_tail(data, size: int, start: int) -> int:
    """Fremde Daten nach dem letzten %%EOF (Byte): nur, wenn davor ein echtes Dateiende steht
    (startxref mit Offset), es mehr sind, als die Engines überspringen, und darunter keine
    PDF-Struktur ist – sonst wäre es z. B. ein abgeschnittenes inkrementelles Update."""
    last = data.rfind(b"%%EOF", start)
    if last < 0 or not _EOF_AFTER_RE.search(data, max(start, last - 64), last):
        return 0
    end = last + 5
    for eol in (b"\r\n", b"\n", b"\r"):
        if data[end : end + len(eol)] == eol:
            end += len(eol)
            break
    if size - end <= TAIL_LIMIT or _STRUCTURE_RE.search(data, end):
        return 0
    return size - end


def _write_pdf_data(path: Path, scan: _Scan, target: Path) -> Path:
    """Nur die PDF-Daten in eine neue Datei kopieren – ohne fremde Daten davor und danach.
    Exklusiv geschrieben: eine vorhandene Datei wird nie überschrieben."""
    remaining = scan.size - scan.after - scan.before
    with open(path, "rb") as source, open(target, "xb") as out:
        source.seek(scan.before)
        while remaining > 0:
            block = source.read(min(1 << 20, remaining))
            if not block:
                break
            out.write(block)
            remaining -= len(block)
    return target


@contextmanager
def _pdf_data(path: Path, scan: _Scan, technical: list[str]):
    """Für die Analyse: bei fremden Daten davor oder danach eine Kopie nur mit den PDF-Daten (im
    Temp-Ordner, gleicher Dateiname – die Meldungen lauten wie beim Original), sonst das Original."""
    if not (scan.before or scan.after):
        yield path
        return
    from .process import TEMP_PREFIX

    folder = Path(tempfile.mkdtemp(prefix=TEMP_PREFIX))
    try:
        try:
            copy = _write_pdf_data(path, scan, folder / path.name)
        except OSError as exc:
            technical.append(f"Kopie ohne fremde Daten nicht möglich ({type(exc).__name__}) – das Original wird geprüft")
            copy = path
        yield copy
    finally:
        try:
            shutil.rmtree(folder)
        except OSError as exc:
            _log().info("Analyse: Temp-Ordner nicht entfernt (%s) – das übernimmt die nächste Aufräumrunde", type(exc).__name__)


def engine_name() -> str:
    parts = []
    try:
        import pikepdf

        parts.append(f"qpdf {pikepdf.__libqpdf_version__}")
    except (ImportError, OSError, AttributeError) as exc:  # pragma: no cover - ohne pikepdf nicht lauffähig
        _log().warning("Engine qpdf nicht verfügbar (%s)", type(exc).__name__)
    try:
        import pypdfium2

        info = getattr(pypdfium2, "PDFIUM_INFO", "")
        parts.append(f"PDFium {getattr(info, 'build', info)}")
    except (ImportError, OSError) as exc:  # pragma: no cover
        _log().warning("Engine PDFium nicht verfügbar (%s)", type(exc).__name__)
    return " · ".join(parts)


# --- Meldungen der Engines ------------------------------------------------------------


def _clean(message: str, path: Path) -> str:
    """Meldung ohne vollständigen Pfad (Protokoll)."""
    text = str(message)
    for form in {str(path), str(path).replace("\\", "/"), os.fspath(path)}:
        text = text.replace(form, path.name)
    return text.strip()


def _category(message: str) -> str | None:
    """Befund-Kategorie einer qpdf-Meldung, z. B. »x.pdf (object 23 0, offset 3544): expected endstream«."""
    lower = message.lower().strip()
    if any(lower.endswith(generic) for generic in _GENERIC):
        return None
    context, _, detail = message.rpartition("): ")
    if not detail or not context:
        context, detail = "", message.split(": ", 1)[-1]
    if "content" in context.lower():
        return "content"
    for key, rule in _RULES:
        if rule.search(detail):
            return key
    for key, rule in _RULES:
        if rule.search(context):
            return key
    return "other"


def _findings(messages: list[str]) -> list[str]:
    keys: list[str] = []
    for message in messages:
        key = _category(message)
        if key and key not in keys:
            keys.append(key)
    return keys


def _damaged_objects(messages: list[str]) -> set[int]:
    found = set()
    for message in messages:
        for match in _OBJECT_RE.finditer(message):
            found.add(int(match.group(1)))
    return found


def _mentioned_pages(messages: list[str]) -> set[int]:
    pages = set()
    for message in messages:
        for match in _PAGE_RE.finditer(message):
            number = int(match.group(1))
            if number > 0:
                pages.add(number - 1)
    return pages


# --- qpdf -------------------------------------------------------------------------------


@dataclass
class _Opened:
    pdf: object | None
    warnings: list[str] = field(default_factory=list)
    password_problem: bool = False
    error: str = ""


def _open_qpdf(path: Path, password: str | None, recovery: bool = True) -> _Opened:
    import pikepdf

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")  # z. B. »Passwort angegeben, aber nicht nötig«
            pdf = pikepdf.open(path, password=password or "", attempt_recovery=recovery)
    except pikepdf.PasswordError:
        return _Opened(None, password_problem=True)
    except (pikepdf.PdfError, OSError, RuntimeError, ValueError, MemoryError) as exc:
        return _Opened(None, error=_clean(str(exc), path))
    return _Opened(pdf, [_clean(w, path) for w in pdf.get_warnings()])


def _collect(pdf, path: Path, into: list[str]) -> list[str]:
    """Neue Warnungen von qpdf abholen (qpdf leert die Liste bei jeder Abfrage)."""
    new = [_clean(w, path) for w in pdf.get_warnings()]
    into.extend(new)
    return new


_SKIP_KEYS = ("/Parent", "/P", "/Annots", "/StructParents", "/B", "/Metadata", "/PieceInfo")


def _page_status(page_obj) -> tuple[set[int], bool]:
    """Objektnummern, die eine Seite zum Darstellen braucht (Inhalt und Ressourcen),
    und ob darunter Verweise auf fehlende Objekte sind (z. B. abgeschnittene Datei)."""
    import pikepdf

    refs: set[int] = set()
    missing = False
    stack = []
    for key in ("/Contents", "/Resources"):
        try:
            if key not in page_obj:
                continue
            value = page_obj.get(key)
        except Exception:
            missing = True
            continue
        if value is None:
            missing = True  # Schlüssel vorhanden, Objekt fehlt
        else:
            stack.append(value)
    containers = (pikepdf.Array, pikepdf.Dictionary, pikepdf.Stream)
    seen = 0
    while stack and seen < MAX_PAGE_REFS:
        obj = stack.pop()
        if not isinstance(obj, containers):
            continue  # Zahlen, Namen, Zeichenketten
        seen += 1
        try:
            if obj.is_indirect:
                number = obj.objgen[0]
                if number in refs:
                    continue
                refs.add(number)
            values = list(obj) if isinstance(obj, pikepdf.Array) else [obj.get(key) for key in obj.keys() if key not in _SKIP_KEYS]
        except Exception:
            missing = True  # Objekt nicht lesbar
            continue
        for value in values:
            if value is None:
                missing = True  # Verweis auf ein fehlendes Objekt
            else:
                stack.append(value)
    return refs, missing


def _page_refs(page_obj) -> set[int]:
    return _page_status(page_obj)[0]


def _incomplete_pages(pdf, damaged: set[int], mentioned: set[int]) -> list[int]:
    """Seiten, deren Inhalt oder Ressourcen beschädigt sind oder fehlen (0-basiert)."""
    bad = []
    for index, page in enumerate(pdf.pages):
        try:
            refs, missing = _page_status(page.obj)
            if missing or index in mentioned or (refs & damaged):
                bad.append(index)
        except Exception:
            bad.append(index)
    return bad


_OBJ_HEADER_RE = re.compile(rb"(?<![0-9])(\d{1,10})\s+(\d{1,5})\s+obj\b")
_PAGE_KEY_RE = re.compile(rb"/(Contents|Resources)\s*(\[[^\]]*\]|\d+\s+\d+\s+R)")
_REF_RE = re.compile(rb"(\d+)\s+(\d+)\s+R")


def _lost_page_content(path: Path, pdf) -> set[int]:
    """Seiten (0-basiert), deren Inhalt oder Ressourcen in der Datei auf Objekte verweisen,
    die nicht mehr existieren – z. B. weil die Datei abgeschnitten ist.

    qpdf behandelt einen Verweis auf ein fehlendes Objekt wie einen fehlenden Eintrag
    (so will es die PDF-Norm); eine solche Seite sähe leer aus. Nur für Seiten ohne
    ``/Contents`` wird die ursprüngliche Seitendefinition in der Datei nachgeschlagen.
    """
    candidates: dict[int, int] = {}
    for index, page in enumerate(pdf.pages):
        try:
            obj = page.obj
            if obj.is_indirect and ("/Contents" not in obj or "/Resources" not in obj):
                candidates[obj.objgen[0]] = index
        except Exception:
            continue
    if not candidates:
        return set()
    lost: set[int] = set()
    with open(path, "rb") as handle:
        if os.fstat(handle.fileno()).st_size == 0:
            return set()
        with mmap.mmap(handle.fileno(), 0, access=mmap.ACCESS_READ) as data:
            starts: dict[int, int] = {}
            for match in _OBJ_HEADER_RE.finditer(data):
                number = int(match.group(1))
                if number in candidates:
                    starts[number] = match.end()  # letzte Definition gilt (inkrementelle Updates)
            for number, start in starts.items():
                end = data.find(b"endobj", start, start + 65536)
                chunk = data[start : end if end > 0 else start + 4096]
                for key in _PAGE_KEY_RE.finditer(chunk):
                    for ref in _REF_RE.finditer(key.group(2)):
                        try:
                            target = pdf.get_object((int(ref.group(1)), int(ref.group(2))))
                        except Exception:
                            target = None
                        if target is None:
                            lost.add(candidates[number])
    return lost


def _damaged_streams(pdf, technical: list[str]) -> tuple[dict[int, str] | None, set[int]]:
    """Flate-Datenströme, die sich nicht vollständig dekodieren lassen (Objektnummer → Art), und die
    Seiten (0-basiert), deren Inhalt oder Ressourcen sie brauchen. qpdf übernimmt solche Ströme beim
    Neuschreiben teils gekürzt, ohne dass die Ausgabe danach auffällt – gezählt wird deshalb, was in
    der Quelle beschädigt ist. Fehlt nur die Prüfsumme, ist nichts verloren: Diese Ströme werden
    neu geschrieben, ihre Seiten zählen nicht als unvollständig. ``None``: Prüfung nicht möglich."""
    import pikepdf

    try:
        damaged, restorable = streams.damaged(pdf, technical)
        numbers = set(damaged) - restorable
        if not numbers:
            return damaged, set()
        return damaged, {index for index, page in enumerate(pdf.pages) if numbers & _page_refs(page.obj)}
    except (pikepdf.PikepdfError, RuntimeError, ValueError, TypeError) as exc:
        technical.append(f"Datenströme: Prüfung nicht möglich ({type(exc).__name__})")
        return None, set()


def _rescue_streams(pdf, technical: list[str], known: dict[int, str] | None = None) -> _Rescue:
    """Beschädigte Flate-Datenströme retten, bevor qpdf das Dokument schreibt – qpdf übernähme sie
    sonst unverändert oder (mit vorgeschalteten ASCII-Filtern) stillschweigend gekürzt, mitten in
    einem Befehl. Seiten, die beschädigte Datenströme brauchen, zählen danach als unvollständig.
    ``known``: für dasselbe Dokument schon ermittelt (``_source_info``) – nur diese werden geprüft."""
    import pikepdf

    try:
        found = streams.rescue(pdf, technical, set(known) if known is not None else None)
        damaged = set(found.partial) | set(found.kept)
        pages = {index for index, page in enumerate(pdf.pages) if damaged & _page_refs(page.obj)} if damaged else set()
    except (pikepdf.PikepdfError, RuntimeError, ValueError, TypeError, MemoryError) as exc:
        technical.append(f"Datenströme: Prüfung unterbrochen ({type(exc).__name__})")
        return _Rescue(uncertain=True)
    return _Rescue(pages, dict(found.partial), len(found.restored), list(found.kept.values()))


def _rescue_actions(partial: dict[int, str], restored: int) -> list[str]:
    """Durchgeführte Schritte der Rettung (»Details«)."""
    actions = []
    contents, images = streams.count(partial, streams.CONTENT), streams.count(partial, streams.IMAGE)
    if contents:
        actions.append(f"{contents} {'Inhaltsstrom' if contents == 1 else 'Inhaltsströme'} teilweise gerettet: lesbarer Teil bis zum letzten vollständigen Befehl übernommen, offene Blöcke geschlossen")
    if images:
        actions.append(f"{images} {'Bild' if images == 1 else 'Bilder'} teilweise gerettet: lesbare Zeilen übernommen, fehlende Zeilen weiß aufgefüllt")
    if restored:
        actions.append(f"{_streams_word(restored)} ohne gültiges Ende vollständig gelesen und neu geschrieben")
    return actions


def _streams_word(count: int) -> str:
    return f"{count} {'Datenstrom' if count == 1 else 'Datenströme'}"


class _DeepCheck:
    """Wie ``qpdf --check``: alle Datenströme dekodieren und die Inhalte jeder Seite
    einzeln lesen – ein Fehler auf einer Seite bricht die Prüfung nicht ab."""

    def __init__(self, pdf, path: Path, technical: list[str], progress: Progress) -> None:
        self.pdf = pdf
        self.path = path
        self.technical = technical
        self.progress = progress
        self.messages: list[str] = []
        self.bad_pages: set[int] = set()

    def run(self) -> None:
        import pikepdf

        class Discard(pikepdf.StreamParser):
            def handle_object(self, *_args) -> None:
                pass

            def handle_eof(self) -> None:
                pass

        pdf = self.pdf
        decode = getattr(pdf, "_decode_all_streams_and_discard", None)  # wie check_pdf_syntax
        if decode is not None:
            try:
                decode(None)
            except Exception as exc:
                self._note(f"Datenströme: {_clean(str(exc), self.path)}")
        self._collect()
        try:
            total = len(pdf.pages)
        except Exception as exc:
            self._note(f"Seitenbaum: {_clean(str(exc), self.path)}")
            return
        for index in range(total):
            self.progress("streams", index / max(1, total))
            before = len(self.messages)
            try:
                pdf.pages[index].parse_contents(Discard())
            except Exception as exc:
                self._note(f"Seite {index + 1}: {_clean(str(exc), self.path)}")
                self.bad_pages.add(index)
            self._collect()
            if len(self.messages) > before:
                self.bad_pages.add(index)

    def _note(self, message: str) -> None:
        self.messages.append(message)
        self.technical.append(message)

    def _collect(self) -> None:
        for warning in self.pdf.get_warnings():
            self._note(_clean(warning, self.path))


def _form_info(pdf) -> tuple[bool, int, int]:
    """(Formular vorhanden, Anzahl Felder, unterschriebene Signaturfelder)."""
    import pikepdf

    try:
        acro = pdf.Root.get("/AcroForm")
    except Exception:
        return False, 0, 0
    signed = 0
    count = 0
    if isinstance(acro, pikepdf.Dictionary):
        fields = acro.get("/Fields")
        stack = [(f, None) for f in fields] if isinstance(fields, pikepdf.Array) else []
        seen: set = set()
        while stack and count < MAX_FIELDS:
            item, inherited = stack.pop()
            try:
                if not isinstance(item, pikepdf.Dictionary):
                    continue
                key = item.objgen if item.is_indirect else id(item)
                if key in seen:
                    continue
                seen.add(key)
                count += 1
                kind = item.get("/FT", inherited)
                if kind == pikepdf.Name.Sig and item.get("/V") is not None:
                    signed += 1
                kids = item.get("/Kids")
                if isinstance(kids, pikepdf.Array):
                    stack.extend((kid, kind) for kid in kids)
            except Exception:
                continue
    try:
        if "/Perms" in pdf.Root:  # zertifiziertes Dokument (DocMDP)
            signed = max(signed, 1)
    except (pikepdf.PikepdfError, ValueError, TypeError) as exc:
        _log().info("Formularprüfung: Eintrag /Perms nicht lesbar (%s)", type(exc).__name__)
    return isinstance(acro, pikepdf.Dictionary) and count > 0, count, signed


def _attachments(pdf) -> int:
    try:
        return len(pdf.attachments)
    except Exception:
        return 0


def _has_outlines(pdf) -> bool:
    try:
        outlines = pdf.Root.get("/Outlines")
        return outlines is not None and outlines.get("/First") is not None
    except Exception:
        return False


def _metadata_ok(pdf) -> bool | None:
    try:
        info = pdf.trailer.get("/Info")
        if info is not None:
            for _key, value in info.items():
                str(value)
        xmp = pdf.Root.get("/Metadata")
        if xmp is not None:
            data = xmp.read_bytes()
            return not data or b"xmpmeta" in data or b"rdf:RDF" in data
        return True if info is not None else None
    except Exception:
        return False


# --- PDFium -----------------------------------------------------------------------------


@dataclass
class _Second:
    pages: int | None = None
    loadable: int = 0
    password_problem: bool = False
    error: str = ""


def _pdfium_probe(path: Path, password: str | None, load_pages: bool) -> _Second:
    import pypdfium2 as pdfium

    try:
        doc = pdfium.PdfDocument(str(path), password=password or None)
    except pdfium.PdfiumError as exc:
        text = str(exc)
        return _Second(password_problem="password" in text.lower(), error=text)
    except Exception as exc:  # pragma: no cover - unerwartete Fehler der Bibliothek
        return _Second(error=str(exc))
    try:
        result = _Second(pages=len(doc))
        if load_pages:
            for index in range(result.pages):
                try:
                    page = doc[index]
                    page.close()
                    result.loadable += 1
                except Exception:
                    continue
        else:
            result.loadable = result.pages
        return result
    finally:
        doc.close()


# --- Rohanalyse --------------------------------------------------------------------------


def _raw_findings(raw: RawStructure) -> list[str]:
    keys = []
    if not (raw.xref_table or raw.xref_stream) or not raw.startxref_valid:
        keys.append("xref")
    if not raw.trailer:
        keys.append("trailer")
    if not raw.eof:
        keys.append("eof")
    if raw.pages and (not raw.page_nodes or not raw.catalog):
        keys.append("pages")
    return keys or ["pages"]


def _tree_damage(raw: scanner.RawScan | None, pages: int | None) -> list[str]:
    """Schäden am Seitenbaum laut Rohdaten (qpdf entfernt Verweise ins Leere beim Öffnen
    stillschweigend). Zählt nur, wenn außerhalb des lesbaren Baums noch Seitenobjekte liegen –
    sonst fehlt keine Seite."""
    if raw is None or not pages or raw.stats.encrypted:
        return []
    _reachable, damage = rebuild.raw_tree(raw)
    return damage if damage and raw.stats.pages > pages else []


def _raw_checks(raw: RawStructure) -> list[Check]:
    """Befunde der Rohanalyse für die technischen Details."""
    found = f"{raw.candidates} gefunden, {raw.objects} gültig"
    if raw.superseded:
        found += f", {raw.superseded} ältere Fassungen"
    if raw.rejected:
        found += f", {raw.rejected} verworfen"
    checks = [
        Check("raw_objects", "Objektkandidaten", raw.objects > 0, found),
        Check("raw_catalog", "Dokumentkatalog (/Catalog)", raw.catalog, "gefunden" if raw.catalog else "nicht gefunden"),
        Check("raw_pages", "Seitenobjekte (/Page)", raw.pages > 0, str(raw.pages)),
        Check("raw_nodes", "Seitenbaum-Knoten (/Pages)", raw.page_nodes > 0, str(raw.page_nodes)),
        Check("raw_xref", "xref-Abschnitt", raw.xref_table or raw.xref_stream, "vorhanden" if raw.xref_table else ("als Datenstrom (PDF 1.5+)" if raw.xref_stream else "fehlt")),
        Check("raw_trailer", "Trailer-Wörterbuch", raw.trailer, "vorhanden" if raw.trailer else "fehlt"),
        Check("raw_startxref", "startxref", raw.startxref_valid, "gültig" if raw.startxref_valid else ("verweist ins Leere" if raw.startxref else "fehlt")),
        Check("raw_eof", "%%EOF", raw.eof, "vorhanden" if raw.eof else "fehlt"),
    ]
    if raw.object_streams:
        checks.append(Check("raw_objstm", "Objektströme", None, str(raw.object_streams)))
    if raw.encrypted:
        checks.append(Check("raw_encrypted", "Verschlüsselung", None, "erkannt – Wiederherstellung nur mit vollständigen Verschlüsselungsdaten"))
    return checks


# --- Analyse ----------------------------------------------------------------------------


def analyze(path: str | os.PathLike, password: str | None = None, progress: Progress | None = None) -> PdfAnalysis:
    progress = progress or _noop
    path = Path(path)
    result = PdfAnalysis(path=str(path), engine=engine_name())
    progress("hash")
    try:
        result.size, result.mtime, result.sha256 = file_digest(path)
    except OSError as exc:
        result.error = f"Die Datei kann nicht gelesen werden ({exc.strerror or exc})."
        return result
    if result.size == 0:
        result.error = "Die Datei ist leer."
        result.checks.append(Check("header", "PDF-Kennung", False, "Datei ist leer"))
        return result
    scan = _scan(path, result.size)
    result.looks_like_pdf = scan.header or bool(scan.before)
    result.pdf_version = scan.version
    result.data_before, result.data_after = scan.before, scan.after
    if scan.before:
        result.checks.append(Check("header", "PDF-Kennung", False, f"PDF {scan.version} – erst nach {_amount(scan.before)} fremder Daten"))
    else:
        result.checks.append(Check("header", "PDF-Kennung", scan.header, f"PDF {scan.version}" if scan.header else "nicht gefunden"))
    if scan.after:
        result.checks.append(Check("eof", "Dateiende", False, f"%%EOF vorhanden, danach {_amount(scan.after)} fremde Daten"))
    else:
        result.checks.append(Check("eof", "Dateiende", scan.eof, "vollständig" if scan.eof else "Kennung %%EOF fehlt – Datei möglicherweise abgeschnitten"))
    technical: list[str] = []
    # Stehen fremde Daten vor oder nach der PDF, prüfen die Engines die PDF-Daten allein – so wie
    # die Reparatur sie zuerst verarbeitet; die fremden Daten selbst sind ein eigener Befund.
    with _pdf_data(path, scan, technical) as source:
        _analyze_structure(result, source, scan, password, progress, technical)
    return result


def _analyze_structure(result: PdfAnalysis, path: Path, scan: _Scan, password: str | None, progress: Progress, technical: list[str]) -> None:
    progress("open")
    opened = _open_qpdf(path, password)
    technical.extend(opened.warnings)
    if opened.password_problem:
        result.encrypted = True
        result.password_required = True
        result.password_rejected = bool(password)
        result.condition = Condition.ENCRYPTED
        result.checks.append(Check("encryption", "Verschlüsselung", None, "Passwort erforderlich" if not password else "Passwort falsch"))
        result.technical = technical[:MAX_TECHNICAL]
        return

    page_count: int | None = None
    incomplete: list[int] = []
    pdf = opened.pdf
    if pdf is not None:
        try:
            result.encrypted = bool(pdf.is_encrypted)
            result.pdf_version = str(pdf.pdf_version) or result.pdf_version
            try:
                page_count = len(pdf.pages)
            except Exception as exc:
                technical.append(f"Seitenbaum: {_clean(str(exc), path)}")
            _collect(pdf, path, technical)
            result.forms, result.form_fields, result.signatures = _form_info(pdf)
            result.attachments = _attachments(pdf)
            result.outlines = _has_outlines(pdf)
            result.metadata_ok = _metadata_ok(pdf)
            _collect(pdf, path, technical)
            progress("streams")
            deep = _DeepCheck(pdf, path, technical, progress)
            deep.run()
            if page_count:
                found = set(_incomplete_pages(pdf, _damaged_objects(technical), _mentioned_pages(technical))) | deep.bad_pages
                if _findings(technical):
                    found |= _lost_page_content(path, pdf)
                if {"streams", "content"} & set(_findings(technical)):
                    found |= _damaged_streams(pdf, technical)[1]  # z. B. ein beschädigtes Bild der Seite
                incomplete = sorted(found)
        finally:
            pdf.close()
    elif opened.error:
        technical.append(f"qpdf: {opened.error}")

    findings = _findings(technical)
    qpdf_ok = pdf is not None and bool(page_count)
    progress("second")
    second = _pdfium_probe(path, password, load_pages=not qpdf_ok or bool(findings))
    # Rohanalyse nur bei beschädigten Dateien: Was steckt noch an Struktur in den Bytes?
    raw_scan: scanner.RawScan | None = None
    if not qpdf_ok or findings or not scan.eof:
        progress("raw_scan")
        try:
            raw_scan = scanner.scan(path, progress)
        except (OSError, ValueError, MemoryError) as exc:
            technical.append(f"Rohanalyse: {_clean(str(exc), path)}")
    raw = raw_scan.stats if raw_scan is not None else None
    result.raw = raw
    tree_damage = _tree_damage(raw_scan, page_count)
    if tree_damage:
        technical += [f"Seitenbaum: {reason}" for reason in tree_damage]
        if "pages" not in findings:
            findings.append("pages")
    if second.error:
        technical.append(f"PDFium: {second.error}")
    result.pdfium_pages = second.pages
    result.rasterizable_pages = second.loadable
    result.page_count = page_count
    known = [n for n in (page_count, second.pages) if n]
    tree_broken = bool(tree_damage)
    if (not qpdf_ok or tree_broken) and raw is not None and raw.pages:
        known.append(raw.pages)  # Seitenbaum nicht (vollständig) lesbar: die gefundenen Seitenobjekte zählen
    result.pages_expected = max(known) if known else None
    if qpdf_ok and page_count is not None:
        result.readable_pages = page_count - len(incomplete)

    # Fremde Daten vor bzw. nach der PDF: eigene Befunde (die Engines haben die PDF-Daten allein geprüft)
    findings[:0] = [key for key, amount in (("header", scan.before), ("tail", scan.after)) if amount and key not in findings]
    if result.looks_like_pdf and not scan.eof and "eof" not in findings:
        findings.append("eof")  # fehlendes Dateiende ist ein Befund – die Reparatur schreibt es neu
    if qpdf_ok:
        if not findings and not incomplete and scan.header:
            result.condition = Condition.HEALTHY
        elif not incomplete and (second.pages is None or second.pages <= page_count) and page_count >= (result.pages_expected or 0):
            result.condition = Condition.REPAIRABLE
        else:
            result.condition = Condition.DAMAGED
    elif pdf is not None or second.pages:
        result.condition = Condition.DAMAGED
        if not findings:
            findings.append("pages")
    elif result.looks_like_pdf and raw is not None and raw.recoverable:
        # Parser scheitern, die Rohdaten tragen aber noch: erweiterte Wiederherstellung möglich
        result.condition = Condition.RAW_RECOVERABLE
        findings.extend(key for key in _raw_findings(raw) if key not in findings)
    else:
        result.condition = Condition.UNREADABLE
        if raw is not None and raw.encrypted and raw.objects:
            result.error = "Die PDF ist verschlüsselt und ihre Struktur ist beschädigt. Ohne vollständige Verschlüsselungsdaten ist keine Wiederherstellung möglich."
        else:
            result.error = "Keine der Engines kann die Datei öffnen, und es wurde keine verwertbare PDF-Struktur gefunden." if result.looks_like_pdf else "Die Datei ist keine lesbare PDF."
    if raw is not None and raw.encrypted and not result.encrypted:
        # Verschlüsselt, aber die Verschlüsselungsangaben (Trailer) fehlen: Der Inhalt ist nicht
        # lesbar, und ein Passwortschutz wird nie umgangen.
        result.condition = Condition.UNREADABLE
        result.error = LOST_ENCRYPTION
    result.repairable = result.condition in (Condition.REPAIRABLE, Condition.DAMAGED, Condition.RAW_RECOVERABLE)

    # Befunde und Diagnose
    result.structural_errors = [FINDINGS[key] for key in findings]
    if incomplete:
        result.incomplete_pages = [index + 1 for index in incomplete]
        result.structural_errors.append(f"{len(incomplete)} von {page_count} Seiten haben fehlende oder beschädigte Inhalte (Seite {_page_list(result.incomplete_pages)}).")
    xref_ok = "xref" not in findings
    result.checks.append(Check("xref", "Querverweistabelle (xref)", xref_ok if pdf is not None else False, "in Ordnung" if xref_ok and pdf is not None else "beschädigt"))
    trailer_ok = "trailer" not in findings
    result.checks.append(Check("trailer", "Trailer", trailer_ok if pdf is not None else False, "vorhanden" if trailer_ok and pdf is not None else "fehlt oder beschädigt"))
    objects_ok = "objects" not in findings
    if pdf is None and raw is not None:
        # Ohne qpdf zählen die Rohdaten – nie »in Ordnung« ohne Prüfung
        result.checks.append(Check("objects", "Objekte", raw.objects > 0, f"{raw.objects} gefunden" if raw.objects else "keine gefunden"))
    else:
        result.checks.append(Check("objects", "Objekte", objects_ok if pdf is not None else None, "in Ordnung" if objects_ok else "fehlerhafte Objekte gefunden"))
    if page_count:
        result.checks.append(Check("pages", "Seitenbaum", "pages" not in findings, f"{page_count} Seiten"))
    elif raw is not None and raw.pages:
        result.checks.append(Check("pages", "Seitenbaum", False, f"nicht lesbar – {raw.pages} Seitenobjekte gefunden"))
    else:
        result.checks.append(Check("pages", "Seitenbaum", False, "nicht lesbar"))
    streams_ok = "streams" not in findings and "content" not in findings and not incomplete
    if pdf is None and raw is not None:
        result.checks.append(Check("streams", "Datenströme", raw.streams > 0 or None, f"{raw.streams} gefunden" if raw.streams else "keine gefunden"))
    else:
        result.checks.append(Check("streams", "Datenströme", streams_ok if pdf is not None else None, "lesbar" if streams_ok else ("Inhalte von %d Seiten beschädigt" % len(incomplete) if incomplete else "teilweise nicht lesbar")))
    result.checks.append(Check("metadata", "Metadaten", result.metadata_ok, {True: "lesbar", False: "beschädigt", None: "keine vorhanden"}[result.metadata_ok]))
    result.checks.append(Check("encryption", "Verschlüsselung", True, "verschlüsselt, Passwort korrekt" if result.encrypted else "nicht verschlüsselt"))
    result.checks.append(Check("second", "Zweite Engine (PDFium)", second.pages is not None, f"{second.pages} Seiten" if second.pages is not None else "kann die Datei nicht öffnen"))
    if raw is not None:
        result.checks += _raw_checks(raw)
        if not result.signatures and raw.signatures:
            result.signatures = raw.signatures  # Signaturen auch ohne lesbare Formularstruktur erkennen

    if result.signatures:
        result.warnings.append("Die PDF enthält digitale Signaturen. Eine Reparatur kann deren Gültigkeit aufheben.")
    if result.encrypted:
        result.warnings.append("Die PDF ist verschlüsselt. Die reparierte Datei bleibt mit einem Passwort geschützt.")
    result.technical = technical[:MAX_TECHNICAL]


# --- Reparatur ------------------------------------------------------------------------------


@dataclass
class _Candidate:
    method: Method
    path: Path
    pages: int
    incomplete: list[int] = field(default_factory=list)  # Seiten mit beschädigtem Inhalt (0-basiert)
    actions: list[str] = field(default_factory=list)
    lost: list[str] = field(default_factory=list)  # nicht übernommene Bestandteile
    critical_loss: bool = False  # z. B. Anhänge verloren
    problems: list[str] = field(default_factory=list)
    doubtful: bool = False  # z. B. Ressourcen fehlten beim Neuaufbau – höchstens »teilweise«
    notes: list[str] = field(default_factory=list)  # Hinweise ohne Verlust, z. B. entfernte fremde Daten
    removed: int = 0  # entfernte fremde Daten vor bzw. nach der PDF (Byte)
    rescued: int = 0  # Datenströme, von denen nur der lesbare Teil übernommen wurde
    kept: list[str] = field(default_factory=list)  # Arten beschädigter Datenströme, unverändert übernommen

    @property
    def complete(self) -> int:
        return self.pages - len(self.incomplete)

    def score(self) -> tuple:
        """Vollständige Seiten vor Seitenzahl vor Struktur (nie Bilder) vor Verlusten vor Methode."""
        return (self.complete, self.pages, self.method is not Method.RASTER, not self.critical_loss, -len(self.lost), PRIORITY[self.method])


@dataclass
class _Rescue:
    """Beschädigte Datenströme eines Dokuments, gerettet, bevor qpdf es schreibt (``recovery.streams``)."""

    pages: set[int] = field(default_factory=set)  # Seiten (0-basiert), die beschädigte Datenströme brauchen
    partial: dict[int, str] = field(default_factory=dict)  # nur der lesbare Teil übernommen (Objekt → Art)
    restored: int = 0  # vollständig gelesen und neu geschrieben
    kept: list[str] = field(default_factory=list)  # beschädigt, unverändert übernommen (Arten)
    uncertain: bool = False  # Prüfung unterbrochen – das Ergebnis gilt höchstens als »teilweise«

    def apply(self, candidate: _Candidate) -> None:
        """Auf den Kandidaten übertragen (gleiche Seitenfolge). Teilweise Gerettetes ist nie vollständig."""
        candidate.incomplete = sorted(set(candidate.incomplete) | self.pages)
        candidate.rescued += len(self.partial)
        candidate.kept += self.kept
        candidate.doubtful = candidate.doubtful or bool(self.partial) or self.uncertain
        candidate.actions += _rescue_actions(self.partial, self.restored)
        if self.uncertain:
            candidate.notes.append("Beschädigte Datenströme ließen sich nicht vollständig prüfen.")


@dataclass
class _Source:
    password_problem: bool = False
    metadata: bool = False
    pages: int | None = None
    pdfium_pages: int | None = None
    encrypted: bool = False
    attachments: int = 0
    outlines: bool = False
    forms: bool = False
    signatures: int = 0
    incomplete: list[int] = field(default_factory=list)
    findings: list[str] = field(default_factory=list)
    raw: scanner.RawScan | None = None  # Rohanalyse, wenn qpdf den Seitenbaum nicht liest
    tree_damaged: bool = False  # Seitenbaum mit Verweisen ins Leere (qpdf überspringt sie)
    rescue: bool = False  # beschädigte Datenströme retten, bevor qpdf schreibt (Modus AUTO)
    damaged: dict[int, str] | None = None  # beschädigte Datenströme der Quelle (Objekt → Art); None: nicht geprüft


@dataclass
class Validation:
    ok: bool
    pages: int = 0
    problems: list[str] = field(default_factory=list)
    incomplete: list[int] = field(default_factory=list)  # Seiten der Ausgabe mit unlesbarem Inhalt


def validate(path: Path, password: str | None = None) -> Validation:
    """Ausgabe prüfen: existiert, nicht leer, öffnet ohne Wiederherstellung, Seitenbaum lesbar,
    Strukturprüfung (Datenströme und Seiteninhalte) und Gegenprobe mit PDFium."""
    if not path.is_file() or path.stat().st_size == 0:
        return Validation(False, problems=["Ausgabedatei fehlt oder ist leer"])
    edges = _scan(path, path.stat().st_size)
    if not edges.header or not edges.eof:
        return Validation(False, problems=["Ausgabe ohne gültige PDF-Kennung" if not edges.header else "Ausgabe ohne Dateiende (%%EOF)"])
    opened = _open_qpdf(path, password, recovery=False)
    if opened.pdf is None:
        return Validation(False, problems=[f"Ausgabe lässt sich nicht öffnen: {opened.error or 'Passwort'}"])
    pdf = opened.pdf
    problems: list[str] = []
    try:
        if opened.warnings:
            return Validation(False, problems=[f"Ausgabe: {w}" for w in opened.warnings])
        try:
            pages = len(pdf.pages)
        except Exception as exc:
            return Validation(False, problems=[f"Seitenbaum der Ausgabe nicht lesbar: {exc}"])
        if pages <= 0:
            return Validation(False, problems=["Ausgabe enthält keine Seiten"])
        deep = _DeepCheck(pdf, path, problems, _noop)
        deep.run()
        incomplete = sorted(set(_incomplete_pages(pdf, _damaged_objects(problems), _mentioned_pages(problems))) | deep.bad_pages)
    finally:
        pdf.close()
    second = _pdfium_probe(path, password, load_pages=False)
    if second.pages is not None and second.pages != pages:
        problems.append(f"PDFium erkennt {second.pages} statt {pages} Seiten")
    return Validation(True, pages, problems, incomplete)


def _source_info(path: Path, password: str | None, deep: bool = False) -> _Source:
    """Angaben zur Quelle. ``deep``: auch beschädigte Datenströme suchen und ihre Seiten als
    unvollständig zählen (Modus AUTO – beschädigte Dateien)."""
    info = _Source(rescue=deep)
    opened = _open_qpdf(path, password)
    info.password_problem = opened.password_problem
    if opened.password_problem:
        return info
    technical = list(opened.warnings)
    if opened.pdf is not None:
        pdf = opened.pdf
        try:
            info.encrypted = bool(pdf.is_encrypted)
            info.metadata = bool(_metadata_ok(pdf))
            try:
                info.pages = len(pdf.pages)
            except Exception:
                info.pages = None
            info.forms, _count, info.signatures = _form_info(pdf)
            info.attachments = _attachments(pdf)
            info.outlines = _has_outlines(pdf)
            _collect(pdf, path, technical)
            if info.pages:
                found = set(_incomplete_pages(pdf, _damaged_objects(technical), _mentioned_pages(technical)))
                if _findings(technical):
                    found |= _lost_page_content(path, pdf)
                if deep:
                    info.damaged, pages = _damaged_streams(pdf, technical)
                    found |= pages
                info.incomplete = sorted(found)
        finally:
            pdf.close()
    info.findings = _findings(technical)
    second = _pdfium_probe(path, password, load_pages=False)
    info.pdfium_pages = second.pages
    if not info.pages or info.findings:
        try:
            info.raw = scanner.scan(path)
        except (OSError, ValueError, MemoryError) as exc:
            technical.append(f"Rohanalyse: {_clean(str(exc), path)}")
    info.tree_damaged = bool(_tree_damage(info.raw, info.pages))
    if info.tree_damaged and "pages" not in info.findings:
        info.findings.append("pages")
    return info


def _save_qpdf(pdf, out: Path, progress: Progress, stage: str) -> None:
    import pikepdf

    # qpdf schreibt /Size nur, wenn der Trailer den Eintrag hat – ein bei der
    # Wiederherstellung neu aufgebauter Trailer hat ihn nicht. Der Wert wird ersetzt.
    if "/Size" not in pdf.trailer:
        pdf.trailer.Size = 0
    pdf.save(
        out,
        fix_metadata_version=False,  # XMP bleibt unverändert (ohne lxml)
        preserve_pdfa=True,
        compress_streams=True,
        object_stream_mode=pikepdf.ObjectStreamMode.preserve,
        linearize=False,
        encryption=True if pdf.is_encrypted else None,  # Passwortschutz bleibt erhalten
        progress=lambda percent: progress(stage, percent / 100),
    )


def _stage_rewrite(path: Path, work: Path, password: str | None, source: _Source, progress: Progress, technical: list[str]) -> _Candidate | None:
    """Stufe 2: mit qpdf öffnen (Querverweise ggf. rekonstruiert) und vollständig neu schreiben."""
    progress("rewrite")
    opened = _open_qpdf(path, password)
    technical.extend(opened.warnings)
    if opened.pdf is None:
        technical.append(f"Stufe 2: qpdf kann die Datei nicht öffnen: {opened.error or 'Passwort'}")
        return None
    out = work / "stufe2.pdf"
    pdf = opened.pdf
    rescued = _Rescue()
    try:
        pages = len(pdf.pages)
        if pages == 0:
            technical.append("Stufe 2: keine Seiten gefunden")
            return None
        if source.rescue:
            rescued = _rescue_streams(pdf, technical, source.damaged)  # dieselbe Quelle, dieselben Objektnummern
        progress("write", 0.0)
        _save_qpdf(pdf, out, progress, "write")
        _collect(pdf, path, technical)
    except Exception as exc:
        technical.append(f"Stufe 2 fehlgeschlagen: {_clean(str(exc), path)}")
        return None
    finally:
        pdf.close()
    actions = [ACTIONS[key] for key in source.findings if key in ACTIONS]
    actions += ["Objekte neu nummeriert und Datei neu geschrieben"]
    candidate = _Candidate(Method.REWRITE, out, pages, list(source.incomplete), actions)
    rescued.apply(candidate)
    return candidate


def _copy_attachments(src, dest, technical: list[str]) -> int:
    """Dateianhänge neu anlegen (Objekte der Quelle dürfen nicht in die neue Datei)."""
    import pikepdf

    copied = 0
    try:
        items = list(src.attachments.items())
    except Exception as exc:
        technical.append(f"Anhänge nicht lesbar: {exc}")
        return 0
    for name, spec in items:
        try:
            stored = spec.get_file()
            data = stored.read_bytes()
            options = {"filename": spec.filename or name}
            if spec.description:
                options["description"] = spec.description
            if stored.mime_type:
                options["mime_type"] = stored.mime_type
            dest.attachments[name] = pikepdf.AttachedFileSpec(dest, data, **options)
            copied += 1
        except Exception as exc:
            technical.append(f"Anhang {copied + 1} nicht übertragbar: {exc}")
    return copied


def _stage_pages(path: Path, work: Path, password: str | None, source: _Source, progress: Progress, technical: list[str]) -> _Candidate | None:
    """Stufe 3a: jede Seite einzeln prüfen und nur lesbare Seiten in eine neue PDF übertragen."""
    import pikepdf

    opened = _open_qpdf(path, password)
    if opened.pdf is None:
        return None
    src = opened.pdf
    out = work / "stufe3-seiten.pdf"
    probe = work / "seite.pdf"
    good: list[int] = []
    rescued = _Rescue()
    try:
        try:
            total = len(src.pages)
        except Exception as exc:
            technical.append(f"Stufe 3 (Seiten): Seitenbaum nicht lesbar: {_clean(str(exc), path)}")
            return None
        if source.rescue:
            rescued = _rescue_streams(src, technical, source.damaged)
        for index in range(total):
            progress("pages", index / max(1, total))
            try:
                with pikepdf.new() as single, warnings.catch_warnings():
                    warnings.simplefilter("ignore")  # Formular-Widgets ohne /AcroForm in der Probe
                    single.pages.append(src.pages[index])
                    single.save(probe, fix_metadata_version=False)
                good.append(index)
            except Exception as exc:
                technical.append(f"Stufe 3 (Seiten): Seite {index + 1} nicht übertragbar: {_clean(str(exc), path)}")
        probe.unlink(missing_ok=True)
        if not good:
            return None
        lost: list[str] = []
        critical = False
        with pikepdf.new() as dest:
            dest.add_pages_from(src, good, forms="preserve")
            try:
                info = src.trailer.get("/Info")
                if info is not None:
                    dest.trailer.Info = dest.copy_foreign(info)
            except (pikepdf.PikepdfError, ValueError, TypeError) as exc:
                technical.append(f"Stufe 3 (Seiten): Dokumentinformationen nicht übertragbar ({type(exc).__name__})")
            if source.attachments:
                copied = _copy_attachments(src, dest, technical)
                if copied < source.attachments:
                    lost.append(f"{source.attachments - copied} von {source.attachments} Dateianhängen konnten nicht übernommen werden.")
                    critical = True
            if source.outlines:
                lost.append("Lesezeichen konnten nicht übernommen werden.")
            dest.save(out, fix_metadata_version=False)
    except Exception as exc:
        technical.append(f"Stufe 3 (Seiten) fehlgeschlagen: {_clean(str(exc), path)}")
        return None
    finally:
        src.close()
    incomplete = [good.index(i) for i in source.incomplete if i in good]
    actions = ["Lesbare Seiten einzeln geprüft und in eine neue PDF übertragen", f"{len(good)} von {total} Seiten übertragen"]
    candidate = _Candidate(Method.PAGES, out, len(good), incomplete, actions, lost, critical)
    rescued.pages = {good.index(i) for i in rescued.pages if i in good}  # Seiten der neuen PDF
    rescued.apply(candidate)
    return candidate


def _stage_pdfium(path: Path, work: Path, password: str | None, source: _Source, progress: Progress, technical: list[str]) -> _Candidate | None:
    """Stufe 3b: Seiten über PDFium (zweite Engine) in eine neue PDF übertragen – ohne Rasterisierung."""
    import pypdfium2 as pdfium

    try:
        src = pdfium.PdfDocument(str(path), password=password or None)
    except Exception as exc:
        technical.append(f"Stufe 3 (PDFium): Datei nicht lesbar: {exc}")
        return None
    out = work / "stufe3-pdfium.pdf"
    good: list[int] = []
    dest = None
    try:
        total = len(src)
        dest = pdfium.PdfDocument.new()
        for index in range(total):
            progress("pages", index / max(1, total))
            try:
                dest.import_pages(src, [index])
                good.append(index)
            except Exception as exc:
                technical.append(f"Stufe 3 (PDFium): Seite {index + 1} nicht übertragbar: {exc}")
        if not good:
            return None
        dest.save(str(out))
    except Exception as exc:
        technical.append(f"Stufe 3 (PDFium) fehlgeschlagen: {exc}")
        return None
    finally:
        if dest is not None:
            dest.close()
        src.close()
    lost = []
    critical = False
    if source.outlines:
        lost.append("Lesezeichen konnten nicht übernommen werden.")
    if source.forms:
        lost.append("Formularfelder wurden möglicherweise nicht vollständig übernommen.")
    if source.attachments:
        lost.append(f"{source.attachments} Dateianhänge konnten nicht übernommen werden.")
        critical = True
    incomplete = [good.index(i) for i in source.incomplete if i in good] if source.pages == source.pdfium_pages else []
    actions = ["Seiten mit der zweiten Engine (PDFium) gelesen und in eine neue PDF übertragen", f"{len(good)} von {total} Seiten übertragen"]
    return _Candidate(Method.PDFIUM, out, len(good), incomplete, actions, lost, critical)


def _stage_raster(path: Path, work: Path, password: str | None, source: _Source, progress: Progress, technical: list[str]) -> _Candidate | None:
    """Rettungsmodus: lesbare Seiten darstellen und als Bilder in eine neue PDF übertragen."""
    import pypdfium2 as pdfium
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas

    try:
        src = pdfium.PdfDocument(str(path), password=password or None)
    except Exception as exc:
        technical.append(f"Rettungsmodus: Datei nicht lesbar: {exc}")
        return None
    out = work / "rettung.pdf"
    drawn = 0
    total = 0
    try:
        total = len(src)
        sheet = canvas.Canvas(str(out), pageCompression=1)
        sheet.setCreator("PDF Tool – Rettungsmodus")
        for index in range(total):
            progress("raster", index / max(1, total))
            page = bitmap = None
            try:
                page = src[index]
                width, height = page.get_size()
                if width <= 0 or height <= 0:
                    raise ValueError("Seite ohne Größe")
                scale = min(RASTER_DPI / 72, math.sqrt(RASTER_MAX_PIXELS / (width * height)))
                bitmap = page.render(scale=scale)
                image = bitmap.to_pil().convert("RGB")
                buffer = io.BytesIO()
                image.save(buffer, "JPEG", quality=JPEG_QUALITY, optimize=True)
                image.close()
                sheet.setPageSize((width, height))
                sheet.drawImage(ImageReader(io.BytesIO(buffer.getvalue())), 0, 0, width, height)
                sheet.showPage()
                drawn += 1
            except Exception as exc:
                technical.append(f"Rettungsmodus: Seite {index + 1} nicht darstellbar: {exc}")
            finally:
                if bitmap is not None:
                    bitmap.close()
                if page is not None:
                    page.close()
        if not drawn:
            return None
        sheet.save()
    except Exception as exc:
        technical.append(f"Rettungsmodus fehlgeschlagen: {exc}")
        return None
    finally:
        src.close()
    lost = ["Text- und Vektorinformationen sind in der geretteten Datei nicht mehr enthalten (Seiten als Bilder)."]
    if source.outlines or source.forms or source.attachments:
        lost.append("Lesezeichen, Formularfelder, Links und Anhänge wurden nicht übernommen.")
    actions = ["Rettungsmodus: lesbare Seiten als Bilder in eine neue PDF übertragen", f"{drawn} von {total} Seiten gerettet"]
    return _Candidate(Method.RASTER, out, drawn, [], actions, lost, True)


def _normalize(source: Path, target: Path, progress: Progress, technical: list[str], label: str, rescue: bool = False) -> _Rescue | None:
    """Kandidat mit qpdf öffnen und neu schreiben – erst die normalisierte Datei wird geprüft.
    ``rescue``: beschädigte Datenströme vorher retten. ``None``: Normalisierung nicht möglich."""
    progress("normalize")
    opened = _open_qpdf(source, None)
    if opened.pdf is None:
        technical.append(f"{label}: Normalisierung nicht möglich: {opened.error or 'Passwort'}")
        return None
    pdf = opened.pdf
    rescued = _Rescue()
    try:
        if len(pdf.pages) == 0:
            technical.append(f"{label}: keine Seiten nach der Normalisierung")
            return None
        if rescue:
            rescued = _rescue_streams(pdf, technical)
        _save_qpdf(pdf, target, progress, "normalize")
        _collect(pdf, source, technical)
    except Exception as exc:  # noqa: BLE001
        technical.append(f"{label}: Normalisierung fehlgeschlagen: {_clean(str(exc), source)}")
        return None
    finally:
        pdf.close()
    return rescued


def _stage_lenient(path: Path, work: Path, password: str | None, source: _Source, progress: Progress, technical: list[str]) -> _Candidate | None:
    """Stufe 4: dritte, tolerante Engine (pypdf) – das Ergebnis wird mit qpdf normalisiert."""
    progress("lenient")
    raw_out = work / "stufe4-pypdf-roh.pdf"
    found = lenient.recover(path, raw_out, password, technical)
    if found is None:
        raw_out.unlink(missing_ok=True)
        return None
    out = work / "stufe4-pypdf.pdf"
    rescued = _normalize(raw_out, out, progress, technical, "Stufe 4 (pypdf)", source.rescue)
    raw_out.unlink(missing_ok=True)
    if rescued is None:
        return None
    lost = list(found.lost)
    critical = False
    if source.attachments and not found.whole_document:
        lost.append(f"{source.attachments} Dateianhänge konnten nicht übernommen werden.")
        critical = True
    actions = ["Dritte Engine (pypdf) hat die Datei mit toleranteren Regeln gelesen", f"{found.pages} von {found.total} Seiten übertragen", "Ergebnis mit qpdf normalisiert"]
    candidate = _Candidate(Method.LENIENT, out, found.pages, [], actions, lost, critical)
    rescued.apply(candidate)
    return candidate


def _stage_raw(path: Path, work: Path, password: str | None, source: _Source, progress: Progress, technical: list[str]) -> _Candidate | None:
    """Stufe 5: Rohrekonstruktion – Objekte aus den Bytes, neue xref, neuer Trailer, startxref und
    %%EOF, bei Bedarf ein neuer Seitenbaum, fehlende Schriften ersetzt. Verschlüsselte Dateien
    werden nicht angefasst (kein Umgehen eines Passwortschutzes)."""
    progress("raw_scan")
    try:
        raw = source.raw or scanner.scan(path, progress)
    except (OSError, ValueError, MemoryError) as exc:
        technical.append(f"Stufe 5: Rohanalyse nicht möglich: {_clean(str(exc), path)}")
        return None
    stats = raw.stats
    technical.append(
        f"Stufe 5: Rohanalyse – {stats.candidates} Objektköpfe, {stats.objects} gültige Objekte, {stats.streams} Datenströme, "
        f"{stats.pages} Seitenobjekte, {stats.page_nodes} Seitenbaum-Knoten, {stats.rejected} verworfen, {stats.superseded} ältere Fassungen"
    )
    if stats.encrypted:
        technical.append("Stufe 5: übersprungen – die Datei ist verschlüsselt (kein Umgehen des Passwortschutzes)")
        return None
    if not stats.recoverable:
        technical.append("Stufe 5: keine verwertbare Dokumentstruktur gefunden")
        return None
    progress("xref_rebuild")
    classic_path = work / "stufe5-roh.pdf"
    finished_path = work / "stufe5-seiten.pdf"
    out = work / "stufe5-rekonstruiert.pdf"
    try:
        classic = rebuild.write_classic(raw, path, classic_path, progress)
        if classic is None:
            return None
        actions = [
            f"PDF-Objekte direkt in der Datei gesucht: {stats.objects} Objekte, {stats.streams} Datenströme",
            "Querverweistabelle (xref) mit neuen Offsets aufgebaut",
            "Trailer neu geschrieben" + (" – Dokumentkatalog neu angelegt" if classic.catalog_created else ""),
            "startxref und Dateiende (%%EOF) neu geschrieben",
        ]
        if stats.superseded:
            actions.append(f"Bei {stats.superseded} mehrfach gespeicherten Objekten die neueste Fassung verwendet")
        if stats.object_streams:
            actions.append(f"{stats.object_streams} Objektströme entpackt")
        broken, _count, messages = rebuild.tree_is_broken(classic_path, stats.pages)
        technical.extend(messages[:20])
        if broken:
            progress("page_tree_rebuild")
        done = rebuild.finish(classic_path, finished_path, raw, technical, broken, _page_status, classic.truncated)
        if done is None:
            return None
        lost: list[str] = []
        doubtful = False
        method = Method.RAW_REBUILD
        if done.tree is not None:
            method = Method.PAGE_TREE_REBUILD
            actions.append(f"Seitenbaum aus {done.tree.pages} Seitenobjekten neu aufgebaut, Eltern-Verweise gesetzt")
            if done.tree.appended == done.tree.pages:
                actions.append("Seitenreihenfolge nach der Reihenfolge der Objekte in der Datei bestimmt")
            elif done.tree.appended:
                kept = done.tree.pages - done.tree.appended
                actions.append(f"Reihenfolge von {kept} Seiten aus dem erhaltenen Seitenbaum übernommen, {done.tree.appended} weitere angefügt")
            if done.tree.inherited:
                actions.append("Geerbte Seiteneigenschaften übernommen: " + ", ".join(done.tree.inherited))
            lost += done.tree.notes
            doubtful = done.tree.doubtful
        if done.fonts.replaced:
            fonts = len(done.fonts.replaced)
            actions.append(f"{fonts} fehlende {'Schrift' if fonts == 1 else 'Schriften'} durch die Standardschrift Helvetica ersetzt")
            lost.insert(
                0,
                f"Alle {done.pages} Seiten wurden übernommen. "
                + ("Eine Schrift fehlte in der Datei und wurde" if fonts == 1 else f"{fonts} Schriften fehlten in der Datei und wurden")
                + " durch eine Standardschrift ersetzt – das Schriftbild kann vom Original abweichen.",
            )
            doubtful = True
        if done.fonts.skipped:
            technical.append(f"Stufe 5: Schriften mit Zwei-Byte-Codes nicht ersetzt: {', '.join(done.fonts.skipped)}")
        rescued = _normalize(finished_path, out, progress, technical, "Stufe 5", source.rescue)
        if rescued is None:
            return None
    except (OSError, ValueError, MemoryError) as exc:
        technical.append(f"Stufe 5: Neuaufbau fehlgeschlagen: {_clean(str(exc), path)}")
        return None
    except Exception as exc:  # noqa: BLE001 - Fehler der PDF-Bibliothek: diese Stufe liefert nichts
        technical.append(f"Stufe 5: Neuaufbau fehlgeschlagen: {type(exc).__name__}: {_clean(str(exc), path)}")
        return None
    finally:
        classic_path.unlink(missing_ok=True)
        finished_path.unlink(missing_ok=True)
    actions.append("Ergebnis mit qpdf normalisiert")
    candidate = _Candidate(method, out, done.pages, done.incomplete, actions, lost, False)
    candidate.doubtful = doubtful
    rescued.apply(candidate)
    return candidate


def _encrypt_like_source(candidate: _Candidate, password: str | None, technical: list[str]) -> bool:
    """Ausgaben der zweiten Engine sind unverschlüsselt – mit dem eingegebenen Passwort schützen."""
    import pikepdf

    if not password:
        return False
    target = candidate.path.with_name(candidate.path.stem + "-geschuetzt.pdf")
    try:
        with pikepdf.open(candidate.path) as pdf:
            pdf.save(target, fix_metadata_version=False, encryption=pikepdf.Encryption(user=password, owner=password, R=6))
    except Exception as exc:
        technical.append(f"Verschlüsselung der Ausgabe fehlgeschlagen: {exc}")
        return False
    candidate.path = target
    candidate.actions.append("Mit dem eingegebenen Passwort geschützt (AES-256)")
    return True


def _stage_streams(best: _Candidate, password: str | None, progress: Progress, technical: list[str]) -> _Candidate:
    """Datenströme retten (nach der Auswahl): Meldet die Prüfung der besten Ausgabe noch unlesbare
    Flate-Datenströme (z. B. von PDFium unverändert übernommen), wird ihr lesbarer Teil übernommen
    (``recovery.streams``). Die neue Ausgabe wird wie jede andere geprüft und nur übernommen, wenn
    sie nichts verschlechtert – sonst bleibt ``best`` (mit der Angabe, was sich nicht retten ließ)."""
    import pikepdf

    progress("streams_rescue")
    opened = _open_qpdf(best.path, password, recovery=False)
    if opened.pdf is None:
        technical.append(f"Datenströme: Ausgabe nicht lesbar: {opened.error or 'Passwort'}")
        return best
    pdf = opened.pdf
    out = best.path.with_name(best.path.stem + "-datenstroeme.pdf")
    try:
        found = streams.rescue(pdf, technical)
        damaged = {**found.partial, **found.restored, **found.kept}
        refs = [_page_refs(page.obj) for page in pdf.pages] if damaged else []
        if found.changed:
            _save_qpdf(pdf, out, progress, "streams_rescue")
    except (pikepdf.PikepdfError, OSError, RuntimeError, ValueError, TypeError, MemoryError) as exc:
        technical.append(f"Datenströme: Rettung nicht möglich ({type(exc).__name__})")
        out.unlink(missing_ok=True)
        return best
    finally:
        pdf.close()

    def using(numbers) -> set[int]:
        """Seiten (0-basiert), deren Inhalt oder Ressourcen diese Objekte brauchen."""
        wanted = set(numbers)
        return {index for index, used in enumerate(refs) if used & wanted}

    if found.changed:
        progress("validate")
        check = validate(out, password)
        technical.extend(check.problems)
        if check.ok and check.pages == best.pages and len(check.problems) < len(best.problems) and set(check.incomplete) <= set(best.incomplete):
            rescued = _Candidate(best.method, out, check.pages, list(best.incomplete), list(best.actions), list(best.lost), best.critical_loss, check.problems, best.doubtful)
            rescued.notes, rescued.removed, rescued.rescued = list(best.notes), best.removed, best.rescued
            # In der Ausgabe noch Beschädigtes ersetzt die bisherige Angabe – es ist jetzt gerettet oder bleibt
            _Rescue(using(found.partial) | using(found.kept) | set(check.incomplete), dict(found.partial), len(found.restored), list(found.kept.values())).apply(rescued)
            return rescued
        technical.append("Gerettete Datenströme verworfen: Die Prüfung ergab keine Verbesserung")
        out.unlink(missing_ok=True)
    # Unverändert übernommen: Seiten, die beschädigte Datenströme brauchen, sind nicht vollständig
    best.kept = list(damaged.values())
    best.incomplete = sorted(set(best.incomplete) | using(damaged))
    return best


def _kept_texts(kept: list[str]) -> list[str]:
    """Hinweise zu beschädigten Datenströmen, die unverändert übernommen wurden."""
    images = kept.count(streams.IMAGE)
    texts = []
    if images:
        texts.append(
            "Ein beschädigtes Bild ließ sich nicht sicher retten und wurde unverändert übernommen."
            if images == 1
            else f"{images} beschädigte Bilder ließen sich nicht sicher retten und wurden unverändert übernommen."
        )
    if len(kept) > images or not images:
        texts.append("Einzelne Datenströme waren schon im Original nicht lesbar und wurden unverändert übernommen.")
    return texts


@dataclass
class _Input:
    """Eingabe der Stufen: das Original oder eine Kopie nur mit den PDF-Daten."""

    path: Path
    work: Path  # Ordner für die Ausgaben der Stufen
    source: _Source
    removed: int = 0  # entfernte fremde Daten (Byte)
    actions: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def _trimmed_input(path: Path, size: int, work: Path, password: str | None, deep: bool, progress: Progress, technical: list[str]) -> _Input | None:
    """Stehen fremde Daten vor oder nach der PDF (z. B. ein E-Mail- oder HTTP-Kopf, HTML), entsteht
    im Arbeitsordner eine Kopie nur mit den PDF-Daten – sie durchläuft die Stufen wie das Original."""
    try:
        edges = _scan(path, size)
    except OSError as exc:
        technical.append(f"Suche nach fremden Daten nicht möglich ({type(exc).__name__})")
        return None
    if not (edges.before or edges.after):
        return None
    progress("trim")
    target = work / CLEAN_DIR
    try:
        (work / INPUT_DIR).mkdir(exist_ok=True)
        target.mkdir(exist_ok=True)
        copy = _write_pdf_data(path, edges, work / INPUT_DIR / path.name)
    except OSError as exc:
        technical.append(f"Kopie ohne fremde Daten nicht möglich ({type(exc).__name__}) – nur das Original wird verarbeitet")
        return None
    technical.append(f"Fremde Daten: {edges.before} Byte vor dem PDF-Anfang, {edges.after} Byte nach dem letzten %%EOF – zuerst wird die PDF ohne sie verarbeitet")
    entry = _Input(copy, target, _source_info(copy, password, deep), edges.before + edges.after)
    if edges.before:
        entry.actions.append(f"{ACTIONS['header']} ({_amount(edges.before)})")
        entry.notes.append(f"Vor dem PDF-Anfang standen {_amount(edges.before)} fremde Daten (z. B. ein E-Mail- oder Webseiten-Kopf). Sie gehören nicht zur PDF und wurden entfernt.")
    if edges.after:
        entry.actions.append(f"{ACTIONS['tail']} ({_amount(edges.after)})")
        entry.notes.append(f"Nach dem Dateiende (%%EOF) standen {_amount(edges.after)} fremde Daten. Sie gehören nicht zur PDF und wurden entfernt.")
    return entry


def _run_stages(entry: _Input, stages, password: str | None, expected: int | None, progress: Progress, technical: list[str], candidates: list[_Candidate]) -> bool:
    """Die Stufen auf eine Eingabe anwenden; jeder Kandidat wird geprüft und gesammelt.
    ``True``: ein Kandidat ist vollständig ohne Verluste – weitere Stufen und Eingaben sind nicht nötig."""
    source = entry.source
    for stage in stages:
        candidate = stage(entry.path, entry.work, password, source, progress, technical)
        if candidate is None:
            continue
        candidate.actions[:0] = entry.actions
        candidate.notes += entry.notes
        candidate.removed = entry.removed
        if source.encrypted and candidate.method in (Method.PDFIUM, Method.RASTER, Method.LENIENT):
            _encrypt_like_source(candidate, password, technical)
        progress("validate")
        check = validate(candidate.path, password)
        technical.extend(check.problems)
        if not check.ok:
            technical.append(f"Ausgabe von {candidate.method.value} verworfen")
            candidate.path.unlink(missing_ok=True)
            continue
        candidate.pages = check.pages
        candidate.problems = check.problems
        candidate.incomplete = sorted(set(candidate.incomplete) | set(check.incomplete))
        candidates.append(candidate)
        best_possible = expected or check.pages
        if candidate.complete >= best_possible and not candidate.critical_loss and not candidate.lost and not candidate.doubtful:
            return True  # vollständig ohne Verluste – weitere Stufen nicht nötig
    return False


def _tidy(work: Path) -> None:
    """Kopie der Eingabe entfernen; den Ordner der Ausgaben für sie nur, wenn er leer ist (die Ausgabe bleibt)."""
    try:
        if (work / INPUT_DIR).is_dir():
            shutil.rmtree(work / INPUT_DIR)
        clean = work / CLEAN_DIR
        if clean.is_dir() and not any(clean.iterdir()):
            clean.rmdir()
    except OSError as exc:
        _log().info("Arbeitsordner: Kopie der Eingabe nicht entfernt (%s) – sie verschwindet mit dem Arbeitsordner", type(exc).__name__)


def _page_list(pages: list[int], limit: int = 12) -> str:
    """»2, 3, 5–9« – kompakt, höchstens ``limit`` Einträge."""
    ranges: list[str] = []
    start = previous = None
    for number in sorted(pages):
        if start is None:
            start = previous = number
        elif number == previous + 1:
            previous = number
        else:
            ranges.append(str(start) if start == previous else f"{start}–{previous}")
            start = previous = number
    if start is not None:
        ranges.append(str(start) if start == previous else f"{start}–{previous}")
    if len(ranges) > limit:
        return ", ".join(ranges[:limit]) + " …"
    return ", ".join(ranges)


def repair(
    path: str | os.PathLike,
    work_dir: str | os.PathLike,
    password: str | None = None,
    mode: RepairMode = RepairMode.AUTO,
    expected_sha256: str | None = None,
    progress: Progress | None = None,
) -> PdfRepairResult:
    """Repariert ``path`` in ``work_dir``. Die Ausgabedatei liegt danach im Arbeitsordner.

    Das Ergebnis enthält den Pfad der geprüften Ausgabe; übernommen wird sie vom
    aufrufenden Prozess (eindeutiger Name neben dem Original bzw. im Zielordner).
    Stehen fremde Daten vor oder nach der PDF, durchläuft zuerst eine Kopie ohne sie die Stufen;
    danach werden, wenn nötig, beschädigte Datenströme der besten Ausgabe gerettet.
    """
    progress = progress or _noop
    path = Path(path)
    work = Path(work_dir)
    result = PdfRepairResult(status=RepairStatus.FAILED, input_path=str(path))
    technical: list[str] = []
    progress("hash")
    try:
        size, _mtime, digest = file_digest(path)
    except OSError as exc:
        result.error = f"Die Datei ist nicht mehr lesbar ({exc.strerror or exc})."
        return result
    result.size_before = size
    if expected_sha256 and digest != expected_sha256:
        result.error = "Die Datei wurde seit der Analyse verändert. Bitte erneut auswählen."
        return result

    progress("open")
    deep = mode is RepairMode.AUTO
    source = _source_info(path, password, deep)
    if source.password_problem:
        result.status = RepairStatus.ENCRYPTED
        result.error = "Das Passwort fehlt oder ist falsch."
        return result
    if source.raw is not None and source.raw.stats.encrypted and not source.encrypted:
        result.error = LOST_ENCRYPTION
        technical.append("Reparatur abgelehnt: verschlüsselte Datei ohne Verschlüsselungsangaben")
        result.technical = technical[:MAX_TECHNICAL]
        return result
    known = [n for n in (source.pages, source.pdfium_pages) if n]
    if (not source.pages or source.tree_damaged) and source.raw is not None and source.raw.stats.pages:
        known.append(source.raw.stats.pages)  # Seitenbaum nicht lesbar: gefundene Seitenobjekte zählen
    expected = max(known) if known else None
    result.pages_before = expected

    candidates: list[_Candidate] = []
    if mode is RepairMode.RASTER:
        stages = (_stage_raster,)
    elif mode is RepairMode.REBUILD:
        stages = (_stage_rewrite,)
    else:
        stages = (_stage_rewrite, _stage_pages, _stage_pdfium, _stage_lenient, _stage_raw)
    inputs = [_Input(path, work, source)]
    try:
        trimmed = _trimmed_input(path, size, work, password, deep, progress, technical) if size else None
        if trimmed is not None:
            inputs.insert(0, trimmed)  # zuerst die PDF-Daten allein, danach (wenn nötig) das Original
            known = [n for n in (expected, trimmed.source.pages, trimmed.source.pdfium_pages) if n]
            expected = max(known) if known else None
            result.pages_before = expected
        for entry in inputs:
            if _run_stages(entry, stages, password, expected, progress, technical, candidates):
                break  # vollständig ohne Verluste – das Original muss nicht mehr durch die Stufen
            if mode is RepairMode.RASTER and candidates:
                break  # Rettungsmodus: ein Ergebnis genügt (jede Seite als Bild – das dauert)
        best = max(candidates, key=lambda c: c.score()) if candidates else None
        if best is not None and best.problems and best.method is not Method.RASTER:
            rescued = _stage_streams(best, password, progress, technical)
            if rescued is not best:
                best.path.unlink(missing_ok=True)
                candidates[candidates.index(best)] = rescued
                best = rescued

        # Original unverändert? (nur gelesen – geprüft wird trotzdem)
        try:
            _size, _mtime, after = file_digest(path)
        except OSError:
            after = ""
        if after != digest:
            for candidate in candidates:
                candidate.path.unlink(missing_ok=True)
            result.error = "Die Datei wurde während der Verarbeitung verändert oder gelöscht. Es wurde keine Ausgabe gespeichert."
            result.technical = technical[:MAX_TECHNICAL]
            return result

        if best is None:
            result.error = "Keine Stufe konnte eine lesbare PDF erzeugen."
            result.technical = technical[:MAX_TECHNICAL]
            return result
        for candidate in candidates:
            if candidate is not best:
                candidate.path.unlink(missing_ok=True)
    finally:
        _tidy(work)
    expected = max(expected or 0, best.pages)
    result.output_path = str(best.path)
    result.method = best.method
    result.size_after = best.path.stat().st_size
    result.pages_before = expected
    result.pages_after = best.pages
    result.data_removed = best.removed
    result.streams_rescued = best.rescued
    result.repair_actions = [f"{expected} Seiten erkannt", *best.actions, f"{best.pages} Seiten geschrieben"]
    if best.method is Method.REWRITE:
        kept = [name for name, present in (("Metadaten", source.metadata), ("Lesezeichen", source.outlines), ("Formulare", source.forms)) if present]
        if source.attachments:
            kept.append(f"{source.attachments} Dateianhänge")
        if kept:
            result.repair_actions.append(", ".join(kept) + " übernommen")
    result.warnings = list(best.lost) + list(best.notes)
    if best.rescued:
        result.warnings.append(f"{_streams_word(best.rescued)} teilweise gerettet: Übernommen wurde nur der lesbare Teil, der beschädigte Rest fehlt.")
    if best.incomplete:
        result.incomplete_pages = [index + 1 for index in best.incomplete]
        result.warnings.append(f"Seiten mit fehlendem oder beschädigtem Inhalt: {_page_list(result.incomplete_pages)} – übernommen, soweit lesbar.")
    if best.complete < expected:
        result.warnings.insert(0, f"{best.complete} von {expected} Seiten konnten vollständig rekonstruiert werden.")
    if source.signatures:
        result.warnings.append("Digitale Signaturen sind nach der Reparatur möglicherweise ungültig.")
    if best.problems or best.kept:
        result.warnings += _kept_texts(best.kept)
    complete = best.complete >= expected and not best.critical_loss and not best.doubtful and best.method is not Method.RASTER
    result.status = RepairStatus.REPAIRED if complete else RepairStatus.PARTIALLY_RECOVERED
    result.technical = technical[:MAX_TECHNICAL]
    return result
