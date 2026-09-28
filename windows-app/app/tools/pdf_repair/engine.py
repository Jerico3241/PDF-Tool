"""Analyse und Reparatur beschädigter PDF-Dateien – läuft im Arbeitsprozess (``process.py``).

Engines
-------
* **qpdf** über pikepdf: Strukturprüfung, Rekonstruktion der Querverweistabelle,
  Neu-Schreiben mit neuem Trailer und neu nummerierten Objekten.
* **PDFium** über pypdfium2: zweite Meinung beim Öffnen, Übertragen lesbarer
  Seiten, wenn qpdf eine Datei nicht verarbeiten kann, und – nur nach
  ausdrücklicher Bestätigung – der Rettungsmodus (Seiten als Bilder).

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
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .models import Check, Condition, Method, PdfAnalysis, PdfRepairResult, RepairMode, RepairStatus

Progress = Callable[..., None]

HEAD_BYTES = 1024
TAIL_BYTES = 4096
RASTER_DPI = 150
RASTER_MAX_PIXELS = 24_000_000  # je Seite – schützt vor riesigen Bitmaps
JPEG_QUALITY = 85
MAX_TECHNICAL = 300
MAX_FIELDS = 10_000
MAX_PAGE_REFS = 5_000  # je Seite untersuchte Objekte (Inhalt und Ressourcen)

FINDINGS = {
    "xref": "Die Querverweistabelle (xref) ist beschädigt.",
    "trailer": "Der Trailer fehlt oder ist beschädigt.",
    "streams": "Datenströme sind beschädigt oder unvollständig.",
    "content": "Seiteninhalte sind teilweise fehlerhaft.",
    "pages": "Der Seitenbaum ist fehlerhaft.",
    "objects": "Objekte der Dateistruktur sind fehlerhaft.",
    "other": "Weitere Unstimmigkeiten in der Dateistruktur.",
}
ACTIONS = {
    "xref": "Querverweistabelle neu aufgebaut",
    "trailer": "Trailer neu geschrieben",
    "streams": "Lesbare Teile beschädigter Datenströme übernommen",
    "content": "Seiteninhalte übernommen, soweit lesbar",
    "pages": "Seitenbaum neu aufgebaut",
    "objects": "Objektstruktur rekonstruiert",
}
_RULES = (
    ("trailer", re.compile(r"trailer", re.I)),
    ("xref", re.compile(r"xref|cross-reference|startxref", re.I)),
    ("content", re.compile(r"content stream|\bcontent\b", re.I)),
    ("streams", re.compile(r"stream|inflate|decod|filter|zlib|lzw|dct|jbig|jpx|ccitt", re.I)),
    ("pages", re.compile(r"\bpages?\b", re.I)),
    ("objects", re.compile(r"object|\bobj\b|endobj|expected|unexpected|token|dictionary|array|reference|offset", re.I)),
)
_OBJECT_RE = re.compile(r"\bobject (\d+) (\d+)\b")
_PAGE_RE = re.compile(r"\bpage (\d+)\b", re.I)
_GENERIC = ("file is damaged",)


def _noop(*_args) -> None:
    pass


# --- Datei ---------------------------------------------------------------------------


def file_digest(path: Path) -> tuple[int, float, str]:
    """Größe, Änderungszeit und SHA-256 – blockweise gelesen, nie die ganze Datei im Speicher."""
    stat = os.stat(path)
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return stat.st_size, stat.st_mtime, digest.hexdigest()


@dataclass
class _Scan:
    header: bool
    version: str | None
    eof: bool
    startxref: bool


def _scan(path: Path, size: int) -> _Scan:
    with open(path, "rb") as handle:
        head = handle.read(HEAD_BYTES)
        handle.seek(max(0, size - TAIL_BYTES))
        tail = handle.read()
    match = re.search(rb"%PDF-(\d\.\d)", head)
    return _Scan(bool(match), match.group(1).decode() if match else None, b"%%EOF" in tail, b"startxref" in tail)


def engine_name() -> str:
    parts = []
    try:
        import pikepdf

        parts.append(f"qpdf {pikepdf.__libqpdf_version__}")
    except Exception:  # pragma: no cover - ohne pikepdf nicht lauffähig
        pass
    try:
        import pypdfium2

        info = getattr(pypdfium2, "PDFIUM_INFO", "")
        parts.append(f"PDFium {getattr(info, 'build', info)}")
    except Exception:  # pragma: no cover
        pass
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
    except Exception:
        pass
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
    result.looks_like_pdf = scan.header
    result.pdf_version = scan.version
    result.checks.append(Check("header", "PDF-Kennung", scan.header, f"PDF {scan.version}" if scan.header else "nicht gefunden"))
    result.checks.append(Check("eof", "Dateiende", scan.eof, "vollständig" if scan.eof else "Kennung %%EOF fehlt – Datei möglicherweise abgeschnitten"))

    progress("open")
    opened = _open_qpdf(path, password)
    technical: list[str] = list(opened.warnings)
    if opened.password_problem:
        result.encrypted = True
        result.password_required = True
        result.password_rejected = bool(password)
        result.condition = Condition.ENCRYPTED
        result.checks.append(Check("encryption", "Verschlüsselung", None, "Passwort erforderlich" if not password else "Passwort falsch"))
        result.technical = technical[:MAX_TECHNICAL]
        return result

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
                incomplete = sorted(found)
        finally:
            pdf.close()
    elif opened.error:
        technical.append(f"qpdf: {opened.error}")

    findings = _findings(technical)
    qpdf_ok = pdf is not None and bool(page_count)
    progress("second")
    second = _pdfium_probe(path, password, load_pages=not qpdf_ok or bool(findings))
    if second.error:
        technical.append(f"PDFium: {second.error}")
    result.pdfium_pages = second.pages
    result.rasterizable_pages = second.loadable
    result.page_count = page_count
    known = [n for n in (page_count, second.pages) if n]
    result.pages_expected = max(known) if known else None
    if qpdf_ok and page_count is not None:
        result.readable_pages = page_count - len(incomplete)

    if qpdf_ok:
        if not findings and not incomplete and scan.header:
            result.condition = Condition.HEALTHY
        elif not incomplete and (second.pages is None or second.pages <= page_count):
            result.condition = Condition.REPAIRABLE
        else:
            result.condition = Condition.DAMAGED
    elif pdf is not None or second.pages:
        result.condition = Condition.DAMAGED
        if not findings:
            findings.append("pages")
    else:
        result.condition = Condition.UNREADABLE
        result.error = "Keine der Engines kann die Datei öffnen." if scan.header else "Die Datei ist keine lesbare PDF."
    result.repairable = result.condition in (Condition.REPAIRABLE, Condition.DAMAGED)

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
    result.checks.append(Check("objects", "Objekte", objects_ok if pdf is not None else None, "in Ordnung" if objects_ok else "fehlerhafte Objekte gefunden"))
    if page_count:
        result.checks.append(Check("pages", "Seitenbaum", "pages" not in findings, f"{page_count} Seiten"))
    else:
        result.checks.append(Check("pages", "Seitenbaum", False, "nicht lesbar"))
    streams_ok = "streams" not in findings and "content" not in findings and not incomplete
    result.checks.append(Check("streams", "Datenströme", streams_ok if pdf is not None else None, "lesbar" if streams_ok else ("Inhalte von %d Seiten beschädigt" % len(incomplete) if incomplete else "teilweise nicht lesbar")))
    result.checks.append(Check("metadata", "Metadaten", result.metadata_ok, {True: "lesbar", False: "beschädigt", None: "keine vorhanden"}[result.metadata_ok]))
    result.checks.append(Check("encryption", "Verschlüsselung", True, "verschlüsselt, Passwort korrekt" if result.encrypted else "nicht verschlüsselt"))
    result.checks.append(Check("second", "Zweite Engine (PDFium)", second.pages is not None, f"{second.pages} Seiten" if second.pages is not None else "kann die Datei nicht öffnen"))

    if result.signatures:
        result.warnings.append("Die PDF enthält digitale Signaturen. Eine Reparatur kann deren Gültigkeit aufheben.")
    if result.encrypted:
        result.warnings.append("Die PDF ist verschlüsselt. Die reparierte Datei bleibt mit einem Passwort geschützt.")
    result.technical = technical[:MAX_TECHNICAL]
    return result


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

    @property
    def complete(self) -> int:
        return self.pages - len(self.incomplete)

    def score(self) -> tuple:
        priority = {Method.REWRITE: 3, Method.PAGES: 2, Method.PDFIUM: 1, Method.RASTER: 0}[self.method]
        return (self.complete, self.pages, not self.critical_loss, priority)


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


def _source_info(path: Path, password: str | None) -> _Source:
    info = _Source()
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
                info.incomplete = sorted(found)
        finally:
            pdf.close()
    info.findings = _findings(technical)
    second = _pdfium_probe(path, password, load_pages=False)
    info.pdfium_pages = second.pages
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
    try:
        pages = len(pdf.pages)
        if pages == 0:
            technical.append("Stufe 2: keine Seiten gefunden")
            return None
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
    return _Candidate(Method.REWRITE, out, pages, list(source.incomplete), actions)


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
    try:
        try:
            total = len(src.pages)
        except Exception as exc:
            technical.append(f"Stufe 3 (Seiten): Seitenbaum nicht lesbar: {_clean(str(exc), path)}")
            return None
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
            except Exception:
                pass
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
    return _Candidate(Method.PAGES, out, len(good), incomplete, actions, lost, critical)


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
    source = _source_info(path, password)
    if source.password_problem:
        result.status = RepairStatus.ENCRYPTED
        result.error = "Das Passwort fehlt oder ist falsch."
        return result
    known = [n for n in (source.pages, source.pdfium_pages) if n]
    expected = max(known) if known else None
    result.pages_before = expected

    candidates: list[_Candidate] = []
    if mode is RepairMode.RASTER:
        stages = (_stage_raster,)
    elif mode is RepairMode.REBUILD:
        stages = (_stage_rewrite,)
    else:
        stages = (_stage_rewrite, _stage_pages, _stage_pdfium)
    for stage in stages:
        candidate = stage(path, work, password, source, progress, technical)
        if candidate is None:
            continue
        if source.encrypted and candidate.method in (Method.PDFIUM, Method.RASTER):
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
        if candidate.method is Method.REWRITE and candidate.complete >= best_possible and not candidate.critical_loss:
            break  # vollständig – weitere Stufen nicht nötig

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

    if not candidates:
        result.error = "Keine Stufe konnte eine lesbare PDF erzeugen."
        result.technical = technical[:MAX_TECHNICAL]
        return result
    best = max(candidates, key=lambda c: c.score())
    for candidate in candidates:
        if candidate is not best:
            candidate.path.unlink(missing_ok=True)
    expected = max(expected or 0, best.pages)
    result.output_path = str(best.path)
    result.method = best.method
    result.size_after = best.path.stat().st_size
    result.pages_before = expected
    result.pages_after = best.pages
    result.repair_actions = [f"{expected} Seiten erkannt", *best.actions, f"{best.pages} Seiten geschrieben"]
    if best.method is Method.REWRITE:
        kept = [name for name, present in (("Metadaten", source.metadata), ("Lesezeichen", source.outlines), ("Formulare", source.forms)) if present]
        if source.attachments:
            kept.append(f"{source.attachments} Dateianhänge")
        if kept:
            result.repair_actions.append(", ".join(kept) + " übernommen")
    result.warnings = list(best.lost)
    if best.incomplete:
        result.incomplete_pages = [index + 1 for index in best.incomplete]
        result.warnings.append(f"Seiten mit fehlendem oder beschädigtem Inhalt: {_page_list(result.incomplete_pages)} – übernommen, soweit lesbar.")
    if best.complete < expected:
        result.warnings.insert(0, f"{best.complete} von {expected} Seiten konnten vollständig rekonstruiert werden.")
    if source.signatures:
        result.warnings.append("Digitale Signaturen sind nach der Reparatur möglicherweise ungültig.")
    if best.problems:
        result.warnings.append("Einzelne Datenströme waren schon im Original nicht lesbar und wurden unverändert übernommen.")
    complete = best.complete >= expected and not best.critical_loss and best.method is not Method.RASTER
    result.status = RepairStatus.REPAIRED if complete else RepairStatus.PARTIALLY_RECOVERED
    result.technical = technical[:MAX_TECHNICAL]
    return result
