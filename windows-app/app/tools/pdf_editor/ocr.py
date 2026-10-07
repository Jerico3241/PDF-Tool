"""Texterkennung (OCR) gescannter Seiten mit Tesseract – vollständig lokal.

Eine gescannte Seite ist nur ein Bild: Suchen, Markieren und Kopieren finden nichts. Die Texterkennung
legt eine **unsichtbare Textebene** (Darstellungsart 3) über die Seite. Die Seite sieht danach genauso
aus wie vorher, der erkannte Text ist aber lesbar, suchbar und kopierbar.

Drei Schritte – der Arbeitsthread des Editors wartet nie auf Tesseract:

1. ``render_page_image`` (Arbeitsthread, schnell): die sichtbare Seite wie in der Anzeige (CropBox,
   ``/Rotate``) als Graustufen-PNG, 300 dpi; sehr große Seiten mit weniger dpi (``MAX_PIXELS``).
2. ``recognize`` (beliebiger Thread): Tesseract als eigener Prozess. Er schreibt eine Text-only-PDF der
   Seite (``textonly_pdf``) und eine TSV-Datei (Wortzahl, mittlere Sicherheit, Sprache). Das Bild liegt
   nur in einem privaten temporären Ordner, der danach immer gelöscht wird. »Abbrechen« beendet den
   Prozess. Nichts verlässt den Rechner.
3. ``apply_text_layers`` (Arbeitsthread): je Seite die Text-only-Seite als Formular-XObject
   (``/PTOCR1`` …) übernehmen und mit einer Matrix platzieren, die den Raum der Anzeige auf den
   Seitenraum abbildet – auch bei ``/Rotate`` und CropBox-Versatz. Eine vorhandene Textebene von PDF
   Tool wird ersetzt. Ein Schritt für Rückgängig; geprüft wird wie beim Bearbeiten: Darstellung
   unverändert, erkannter Text lesbar – sonst wird alles zurückgenommen.

Die Engine: gebündelt im Installationsordner (``ocr\\tesseract.exe`` mit ``ocr\\tessdata``, siehe
``build.py``), sonst ``PDFTOOL_TESSERACT`` (Pfad zur ausführbaren Datei), sonst ``tesseract`` im PATH.

Dieses Modul protokolliert nichts. Erkannte Texte werden nur gehalten, solange die Prüfung sie braucht;
``RecognizedPage`` enthält außer der Text-only-PDF nur Zahlen und den Sprachcode.
"""

from __future__ import annotations

import ctypes
import io
import math
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import pikepdf

from pdfium_lock import PDFIUM_LOCK

from . import commands, render, textedit, textlayer
from .commands import History
from .content import append_content, fmt, invert, mul, page_xobjects
from .document import EditorDocument
from .errors import EditorError
from .geometry import Rect, contains, normalize

INSTALL_DIR = Path(__file__).resolve().parents[3]  # wie appstate.INSTALL_DIR (…\app\tools\pdf_editor\ocr.py)
BUNDLED_DIR = INSTALL_DIR / "ocr"  # build.py: tesseract.exe, seine DLLs und tessdata
ENGINE_VARIABLE = "PDFTOOL_TESSERACT"
LAYER_PREFIX = "/PTOCR"  # Ressourcennamen der Textebenen von PDF Tool
TEMP_PREFIX = "pdf-tool-ocr-"
DEFAULT_DPI = 300
MAX_PIXELS = 16_000_000  # Seitenbild für die Erkennung – A4 bei 300 dpi hat 8,7 Mio., A3 wird leicht verkleinert
MIN_VERSION = 4  # LSTM-Sprachdaten und ``textonly_pdf`` gibt es ab Tesseract 4
TEXT_LIMIT = 25  # weniger Zeichen (ohne Leerraum) gelten als »praktisch kein Text«
IMAGE_LIMIT = 0.5  # ab diesem Anteil der sichtbaren Fläche unter Bildern: »überwiegend Bild«
COVER_GRID = 50  # Raster für die Bildfläche (50 × 50 Stichproben je Seite)
CHECK_SCALE = 1.0  # Pixel je Punkt für die Prüfung der Darstellung (je Seite ein Graustufenbild im Speicher)
SIZE_TOLERANCE = 0.01  # erlaubte Abweichung zwischen erkannter und aktueller Seitengröße (1 % + 2 pt)
PROBE_TIMEOUT = 30.0  # »--version« und »--list-langs« – der erste Start unter Windows prüft der Virenscanner
POLL_SECONDS = 0.1  # so oft prüft ``recognize`` Abbruch und Zeitlimit
REMOVE_ATTEMPTS = 20  # temporären Ordner löschen: Wiederholungen (Virenscanner, eben beendeter Prozess)
REMOVE_DELAY = 0.1
CREATE_NO_WINDOW = 0x08000000  # Windows: Tesseract ohne Konsolenfenster
BELOW_NORMAL_PRIORITY_CLASS = 0x00004000  # Windows: die Oberfläche bleibt flüssig
DLL_NOT_FOUND = (0xC0000135, -1073741515)  # Windows: eine DLL fehlt (STATUS_DLL_NOT_FOUND)

LANGUAGE_NAMES = {
    "deu": "Deutsch",
    "eng": "Englisch",
    "fra": "Französisch",
    "ita": "Italienisch",
    "spa": "Spanisch",
    "nld": "Niederländisch",
    "por": "Portugiesisch",
    "pol": "Polnisch",
    "ces": "Tschechisch",
    "slk": "Slowakisch",
    "slv": "Slowenisch",
    "hrv": "Kroatisch",
    "hun": "Ungarisch",
    "ron": "Rumänisch",
    "dan": "Dänisch",
    "swe": "Schwedisch",
    "nor": "Norwegisch",
    "fin": "Finnisch",
    "tur": "Türkisch",
    "ell": "Griechisch",
    "rus": "Russisch",
    "ukr": "Ukrainisch",
    "lat": "Latein",
    "deu_latf": "Deutsch (Fraktur)",
    "osd": "Ausrichtung und Schrift",
}

# Häufige Wörter je Sprache für ``detect_language``. Wörter, die in mehreren Listen stehen (»de«, »la«,
# »in« …), zählen für keine Sprache – entscheidend sind die eindeutigen.
STOPWORDS = {
    "deu": "der die das und ist nicht mit sich des den dem ein eine einer einem eines auf für von zu wird werden sind auch "
    "bei nach oder aus wir ihr wie über zum zur vom noch nur kann haben hat im ich sie es an in er so als was will worden",
    "eng": "the and of to that for it with as was are be this by from at or an have not which you your will can has we "
    "were been their they he she his her its would there in is so no on",
    "fra": "le la les et des du un une est que qui dans pour pas sur au aux avec ce cette sont par plus ne nous vous elle "
    "être été ses leur mais ou de en te il se son on",
    "ita": "il lo gli della delle degli che non per con una sono del dei nel nella alla è sul anche più questo questa "
    "essere le la un qui ne al se in su ma de",
    "spa": "el los las del que en por con para una es se al lo como más pero sus está este esta muy también fue la un "
    "de su no son",
    "nld": "de het een en van in is dat op te zijn met voor niet aan er ook als bij door maar om uit wordt worden dit "
    "deze naar",
}
_WORDS = re.compile(r"[^\W\d_]+", re.UNICODE)


def _unique_stopwords() -> dict[str, frozenset[str]]:
    counts = Counter(word for words in STOPWORDS.values() for word in set(words.split()))
    return {code: frozenset(word for word in words.split() if counts[word] == 1) for code, words in STOPWORDS.items()}


_STOPWORDS = _unique_stopwords()


class OcrError(EditorError):
    """Texterkennung nicht möglich – ``str(error)`` ist ein verständlicher Satz für die Oberfläche."""


class OcrCancelled(Exception):
    """Die Texterkennung wurde abgebrochen; der Tesseract-Prozess ist beendet."""


# --- Engine ------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class OcrEngine:
    executable: Path
    tessdata: Path
    version: str  # z. B. »5.5.3.20260724«
    languages: tuple[str, ...]  # installierte Sprachdaten (ohne »osd«)

    @property
    def orientation(self) -> bool:
        """Lageerkennung (``osd.traineddata``) vorhanden – dann erkennt Tesseract auch quer liegende Scans."""
        return (self.tessdata / "osd.traineddata").is_file()


def find_engine() -> OcrEngine | None:
    """Erste brauchbare Engine: gebündelt im Installationsordner, dann ``PDFTOOL_TESSERACT``, dann
    ``tesseract`` im PATH. Brauchbar heißt: startet, ist mindestens Version 4 und hat Sprachdaten."""
    bundled = BUNDLED_DIR / _executable_name()
    if bundled.is_file():
        engine = _probe(bundled, BUNDLED_DIR / "tessdata")
        if engine is not None:
            return engine
    configured = os.environ.get(ENGINE_VARIABLE, "").strip().strip('"')
    if configured:
        engine = _probe(Path(configured), None)
        if engine is not None:
            return engine
    found = shutil.which("tesseract")
    if found:
        return _probe(Path(found), None)
    return None


def installed_languages(tessdata: Path) -> tuple[str, ...]:
    """Sprachdaten im tessdata-Ordner (``deu.traineddata`` → »deu«), ohne die Lageerkennung »osd«."""
    try:
        names = [path.stem for path in Path(tessdata).glob("*.traineddata") if path.is_file()]
    except OSError:
        return ()
    return tuple(sorted(name for name in names if name != "osd" and re.fullmatch(r"[A-Za-z0-9_]+", name)))


def language_label(code: str) -> str:
    """Anzeigename einer Sprache (»deu« → »Deutsch«); unbekannte Codes bleiben, wie sie sind."""
    return LANGUAGE_NAMES.get(code, code)


def _executable_name() -> str:
    return "tesseract.exe" if os.name == "nt" else "tesseract"


def _probe(executable: Path, tessdata: Path | None) -> OcrEngine | None:
    if not executable.is_file():
        return None
    try:
        output = _query(executable, "--version")
    except (OSError, subprocess.SubprocessError):
        return None
    match = re.search(r"tesseract\s+v?(\d+)\.([\w.-]+)", output, re.IGNORECASE)
    if match is None or int(match.group(1)) < MIN_VERSION:
        return None
    if tessdata is None:
        tessdata = _tessdata_of(executable)
    if tessdata is None:
        return None
    languages = installed_languages(tessdata)
    if not languages:
        return None
    return OcrEngine(Path(os.path.abspath(executable)), Path(os.path.abspath(tessdata)), f"{match.group(1)}.{match.group(2)}", languages)


def _query(executable: Path, *args: str) -> str:
    """Kurzer Aufruf (Version, Sprachliste) – Ausgabe von stdout und stderr zusammen."""
    done = subprocess.run([str(executable), *args], cwd=str(executable.parent), stdin=subprocess.DEVNULL, capture_output=True, timeout=PROBE_TIMEOUT, creationflags=_flags())
    if done.returncode != 0:
        raise subprocess.CalledProcessError(done.returncode, "tesseract")
    return (done.stdout + b"\n" + done.stderr).decode("utf-8", "replace")


def _tessdata_of(executable: Path) -> Path | None:
    """tessdata-Ordner einer Engine aus PATH oder ``PDFTOOL_TESSERACT``: so, wie Tesseract ihn selbst
    findet (»--list-langs« nennt ihn), sonst ``TESSDATA_PREFIX`` oder ``tessdata`` neben dem Programm."""
    candidates: list[Path] = []
    try:
        listed = re.search(r'"([^"\r\n]+)"', _query(executable, "--list-langs"))
    except (OSError, subprocess.SubprocessError):
        listed = None
    if listed is not None:
        candidates.append(executable.parent / listed.group(1))  # absolut bleibt absolut
    prefix = os.environ.get("TESSDATA_PREFIX", "").strip()
    if prefix:
        candidates.append(Path(prefix))
    candidates.append(executable.parent / "tessdata")
    for candidate in candidates:
        if candidate.is_dir() and installed_languages(candidate):
            return candidate
    return None


def _flags() -> int:
    return CREATE_NO_WINDOW | BELOW_NORMAL_PRIORITY_CLASS if os.name == "nt" else 0


# --- Seiten prüfen -------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class PageScan:
    page: int
    chars: int  # PDFium-Textzeichen ohne Leerraum (auch unsichtbarer Text)
    image_cover: float  # Anteil der sichtbaren Seitenfläche unter Bildern (0..1)
    ocr_layer: bool  # eine Textebene von PDF Tool ist schon vorhanden

    @property
    def needs_ocr(self) -> bool:
        """Praktisch kein Text und überwiegend Bild – typisch für einen Scan. Eine Seite mit einer Textebene
        von PDF Tool gilt als erkannt (auch wenn wenig Text darauf stand); erneut erkennen geht trotzdem."""
        return not self.ocr_layer and self.chars < TEXT_LIMIT and self.image_cover >= IMAGE_LIMIT


def scan_pages(document: EditorDocument, pages=None) -> list[PageScan]:
    """Text und Bildanteil der Seiten (alle oder ``pages``) – nur lesen. Arbeitsthread."""
    indexes = range(document.page_count) if pages is None else sorted({int(page) for page in pages})
    result = []
    for page in indexes:
        _check_page(document, page)
        chars, cover = _measure(document, page)
        result.append(PageScan(page, chars, cover, has_text_layer(document, page)))
    return result


def has_text_layer(document: EditorDocument, page: int) -> bool:
    """Hat die Seite eine Textebene von PDF Tool (``/PTOCR…``)?"""
    _check_page(document, page)
    return bool(_layer_names(document.pdf.pages[page].obj))


def _measure(document: EditorDocument, page: int) -> tuple[int, float]:
    import pypdfium2.raw as r

    rects: list[Rect] = []
    with PDFIUM_LOCK:
        text = document.textpage(page).get_text_range()
        pdf_page = document.page_object(page)
        for index in range(r.FPDFPage_CountObjects(pdf_page.raw)):
            obj = r.FPDFPage_GetObject(pdf_page.raw, index)
            kind = r.FPDFPageObj_GetType(obj)
            if kind == r.FPDF_PAGEOBJ_IMAGE or (kind == r.FPDF_PAGEOBJ_FORM and _has_image(obj)):
                left, bottom, right, top = (ctypes.c_float() for _ in range(4))
                if r.FPDFPageObj_GetBounds(obj, left, bottom, right, top):
                    rects.append(normalize((left.value, bottom.value, right.value, top.value)))
    chars = sum(1 for char in text if not char.isspace() and char != "\x00")
    return chars, _covered(rects, document.geometry(page).crop)


def _has_image(form, depth: int = 0) -> bool:
    """Enthält ein Formular-XObject (auch verschachtelt) ein Bild? Viele Scanprogramme legen den Scan so ab."""
    import pypdfium2.raw as r

    if depth > 4:
        return False
    for index in range(max(0, r.FPDFFormObj_CountObjects(form))):
        inner = r.FPDFFormObj_GetObject(form, index)
        kind = r.FPDFPageObj_GetType(inner)
        if kind == r.FPDF_PAGEOBJ_IMAGE or (kind == r.FPDF_PAGEOBJ_FORM and _has_image(inner, depth + 1)):
            return True
    return False


def _covered(rects: list[Rect], crop: Rect) -> float:
    """Anteil von ``crop``, den die Rechtecke zusammen bedecken (Stichproben, Überlappung zählt einmal)."""
    if not rects:
        return 0.0
    x0, y0, x1, y1 = crop
    hits = 0
    for i in range(COVER_GRID):
        x = x0 + (i + 0.5) * (x1 - x0) / COVER_GRID
        for j in range(COVER_GRID):
            y = y0 + (j + 0.5) * (y1 - y0) / COVER_GRID
            if any(contains(rect, x, y) for rect in rects):
                hits += 1
    return round(hits / (COVER_GRID * COVER_GRID), 3)


# --- 1. Seitenbild -------------------------------------------------------------------------------------------
def render_page_image(document: EditorDocument, page: int, dpi: int = DEFAULT_DPI) -> tuple[bytes, int]:
    """Die sichtbare Seite wie in der Anzeige (CropBox, Drehung) als Graustufen-PNG und die tatsächlich
    verwendete Auflösung. Ohne Anmerkungen – sie gehören nicht zum Inhalt der Seite. Arbeitsthread."""
    _check_page(document, page)
    geo = document.geometry(page)
    limit = 72.0 * math.sqrt(MAX_PIXELS / max(1.0, geo.width * geo.height))
    dpi = max(1, min(int(dpi), int(limit)))
    raster = render.render_page(document, page, max(1, round(geo.width * dpi / 72.0)), annotations=False)
    image = render.to_pil(raster).convert("L")
    used = max(1, round(raster.width * 72.0 / geo.width))
    buffer = io.BytesIO()
    image.save(buffer, "PNG", dpi=(used, used), compress_level=1)
    return buffer.getvalue(), used


# --- 2. Erkennen ---------------------------------------------------------------------------------------------
@dataclass
class RecognizedPage:
    page: int
    pdf: bytes  # Text-only-PDF der Seite von Tesseract (``textonly_pdf``)
    words: int
    confidence: float  # mittlere Sicherheit der erkannten Wörter, 0..100
    language: str  # erkannte Sprache (Heuristik ``detect_language``, leer = unbekannt)
    dpi: int


def recognize(engine: OcrEngine, page: int, png: bytes, languages: list[str], dpi: int, *, cancel: threading.Event | None = None, timeout: float = 600) -> RecognizedPage:
    """Seitenbild mit Tesseract erkennen – in einem eigenen Prozess, aus einem beliebigen Thread.

    ``cancel`` gesetzt: Der Prozess wird beendet, dann ``OcrCancelled``. Zeitüberschreitung, fehlende
    Sprachdaten oder ein Fehler von Tesseract: ``OcrError``. Der temporäre Ordner (Bild, Ergebnis) wird in
    jedem Fall gelöscht."""
    codes = _languages(engine, languages)
    if cancel is not None and cancel.is_set():
        raise OcrCancelled()
    folder = Path(tempfile.mkdtemp(prefix=TEMP_PREFIX))  # nur für diesen Benutzer lesbar
    try:
        result = _recognize_in(folder, engine, page, png, codes, int(dpi), cancel, timeout)
    except BaseException as exc:
        if _remove_folder(folder) is not None:
            exc.add_note("Die temporären Dateien der Texterkennung ließen sich nicht löschen.")
        raise
    problem = _remove_folder(folder)
    if problem is not None:
        raise OcrError("Die temporären Dateien der Texterkennung ließen sich nicht löschen.") from problem
    return result


def _languages(engine: OcrEngine, languages: list[str]) -> list[str]:
    codes = list(dict.fromkeys(code.strip() for code in languages if code and code.strip()))
    if not codes:
        raise OcrError("Bitte mindestens eine Sprache für die Texterkennung wählen.")
    for code in codes:
        if code not in engine.languages:
            raise OcrError(f"Für die Texterkennung fehlt die Sprache »{language_label(code)}«.")
    return codes


def _recognize_in(folder: Path, engine: OcrEngine, page: int, png: bytes, codes: list[str], dpi: int, cancel: threading.Event | None, timeout: float) -> RecognizedPage:
    (folder / "seite.png").write_bytes(png)
    tessdata = _argument_path(engine.tessdata, folder)
    command = [
        str(engine.executable), "seite.png", "ergebnis",
        "--tessdata-dir", tessdata,
        "-l", "+".join(codes),
        "--dpi", str(dpi),
        "--psm", "1" if engine.orientation else "3",  # 1: mit Lageerkennung (quer liegende Scans)
        "-c", "tessedit_create_pdf=1",
        "-c", "tessedit_create_tsv=1",
        "-c", "textonly_pdf=1",
    ]
    environment = dict(os.environ, OMP_THREAD_LIMIT="1", TESSDATA_PREFIX=tessdata)  # mehrere Seiten parallel
    try:
        with open(folder / "meldungen.txt", "wb") as messages:
            process = subprocess.Popen(command, cwd=str(folder), env=environment, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=messages, creationflags=_flags())
    except OSError as exc:
        raise OcrError("Die Texterkennung (Tesseract) konnte nicht gestartet werden.") from exc
    try:
        code = _wait(process, cancel, timeout)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
    if code != 0:
        raise _failure(code, (folder / "meldungen.txt").read_text(encoding="utf-8", errors="replace"))
    pdf_path, tsv_path = folder / "ergebnis.pdf", folder / "ergebnis.tsv"
    if not pdf_path.is_file() or not tsv_path.is_file():
        raise OcrError("Die Texterkennung hat kein Ergebnis geliefert.")
    pdf = pdf_path.read_bytes()
    if not pdf.startswith(b"%PDF-"):
        raise OcrError("Das Ergebnis der Texterkennung ist keine gültige PDF.")
    words, confidence, text = _read_tsv(tsv_path.read_text(encoding="utf-8", errors="replace"))
    return RecognizedPage(page, pdf, words, round(confidence, 1), detect_language(text), dpi)


def _wait(process: subprocess.Popen, cancel: threading.Event | None, timeout: float) -> int:
    deadline = time.monotonic() + timeout
    while True:
        try:
            return process.wait(timeout=POLL_SECONDS)
        except subprocess.TimeoutExpired:
            pass
        if cancel is not None and cancel.is_set():
            raise OcrCancelled()
        if time.monotonic() >= deadline:
            raise OcrError("Die Texterkennung hat zu lange gedauert und wurde abgebrochen.")


def _failure(code: int, messages: str) -> OcrError:
    """Fehler von Tesseract als Satz für die Oberfläche (die Meldungen selbst werden nicht weitergegeben)."""
    missing = re.search(r"Failed loading language '([^']+)'", messages)
    if missing is not None:
        return OcrError(f"Die Sprachdaten für »{language_label(missing.group(1))}« sind nicht lesbar.")
    if code in DLL_NOT_FOUND:
        return OcrError("Die Texterkennung ist unvollständig installiert (eine Programmdatei fehlt).")
    return OcrError(f"Die Texterkennung ist fehlgeschlagen (Tesseract, Code {code}).")


def _read_tsv(text: str) -> tuple[int, float, str]:
    """Wörter (Ebene 5 mit Sicherheit ≥ 0), mittlere Sicherheit und die Wörter für die Spracherkennung."""
    words: list[str] = []
    total = 0.0
    for line in text.splitlines()[1:]:
        cells = line.split("\t")
        if len(cells) < 12 or cells[0] != "5" or not cells[11].strip():
            continue
        try:
            confidence = float(cells[10])
        except ValueError:
            continue
        if confidence < 0:
            continue
        words.append(cells[11].strip())
        total += confidence
    return len(words), (total / len(words) if words else 0.0), " ".join(words)


def _argument_path(target: Path, cwd: Path) -> str:
    """Pfad für die Kommandozeile von Tesseract. Tesseract liest Pfade unter Windows im ANSI-Zeichensatz –
    ein Benutzername wie »Łukasz« wäre im absoluten Pfad nicht darstellbar. Liegen Temp- und Programmordner
    im selben Benutzerprofil, enthält der relative Pfad nur ASCII-Zeichen."""
    absolute = str(target)
    if absolute.isascii():
        return absolute
    try:
        relative = os.path.relpath(target, cwd)
    except ValueError:  # anderes Laufwerk
        return absolute
    return relative if relative.isascii() else absolute


def _remove_folder(folder: Path) -> OSError | None:
    """Temporären Ordner löschen, mit kurzen Wiederholungen. Rückgabe: der Fehler, falls er bleibt."""
    error: OSError | None = None
    for _attempt in range(REMOVE_ATTEMPTS):
        try:
            shutil.rmtree(folder)
            return None
        except FileNotFoundError:
            return None
        except OSError as exc:
            error = exc
            time.sleep(REMOVE_DELAY)
    return error


def detect_language(text: str) -> str:
    """Sprache eines Textes über häufige Wörter: »deu«, »eng«, »fra«, »ita«, »spa« oder »nld«; leer, wenn
    der Text zu wenig Anhaltspunkte hat oder zwei Sprachen gleichauf liegen."""
    words = [word.lower() for word in _WORDS.findall(text or "")]
    scores = Counter()
    for word in words:
        for code, stopwords in _STOPWORDS.items():
            if word in stopwords:
                scores[code] += 1
    ranked = scores.most_common(2)
    if not ranked or ranked[0][1] < 2:
        return ""
    if len(ranked) > 1 and ranked[1][1] * 3 >= ranked[0][1] * 2:  # zweite Sprache fast gleichauf
        return ""
    return ranked[0][0]


# --- 3. Übernehmen -------------------------------------------------------------------------------------------
class _Layer:
    """Text-only-Seite von Tesseract, geöffnet zum Übernehmen."""

    def __init__(self, result: RecognizedPage) -> None:
        try:
            self.source = pikepdf.open(io.BytesIO(result.pdf))
        except (pikepdf.PdfError, ValueError) as exc:
            raise OcrError("Das Ergebnis der Texterkennung ist keine gültige PDF.") from exc
        self.adopted = False
        try:
            if len(self.source.pages) != 1:
                raise OcrError("Das Ergebnis der Texterkennung hat nicht genau eine Seite.")
            try:
                x0, y0, x1, y1 = normalize(tuple(float(value) for value in self.source.pages[0].MediaBox))
            except (TypeError, ValueError, pikepdf.PdfError) as exc:
                raise OcrError("Das Ergebnis der Texterkennung hat keine gültige Seitengröße.") from exc
            self.width, self.height = x1 - x0, y1 - y0
            self.text = _pdf_text(result.pdf)  # nur bis zur Prüfung gehalten
            if not self.text:
                raise OcrError("Der erkannte Text ist im Ergebnis der Texterkennung nicht lesbar.")
        except BaseException:
            self.source.close()
            raise

    def matches(self, width: float, height: float) -> bool:
        """Passt die Seite (Breite × Höhe der Anzeige) noch zum Bild, das erkannt wurde?"""
        return all(abs(a - b) <= SIZE_TOLERANCE * b + 2.0 for a, b in ((self.width, width), (self.height, height)))

    def close(self) -> None:
        if not self.adopted:
            self.source.close()


def apply_text_layers(document: EditorDocument, history: History, results: list[RecognizedPage], *, title: str = "Text erkennen (OCR)") -> int:
    """Erkannten Text als unsichtbare Textebene übernehmen – ein Schritt für Rückgängig. Seiten ohne
    erkannte Wörter bleiben unverändert; eine vorhandene Textebene von PDF Tool wird ersetzt.

    Die Seite muss noch so aussehen wie beim Rendern (gleiche Größe und Drehung) – die Oberfläche
    verwirft Ergebnisse, wenn sich das Dokument inzwischen geändert hat (``document.revision``).
    Danach geprüft: Darstellung unverändert, erkannter Text lesbar – sonst wird alles zurückgenommen
    und ``OcrError`` gemeldet. Rückgabe: Anzahl geänderter Seiten. Arbeitsthread."""
    document.ensure_editable()
    chosen: dict[int, RecognizedPage] = {}
    for result in results:
        _check_page(document, result.page)
        if result.words > 0:
            chosen[result.page] = result  # mehrfach erkannt: das letzte Ergebnis gilt
    if not chosen:
        return 0
    pages = sorted(chosen)
    layers: dict[int, _Layer] = {}
    try:
        for page in pages:
            layers[page] = _Layer(chosen[page])
            geo = document.geometry(page)
            if not layers[page].matches(geo.width, geo.height):
                raise OcrError("Die Seite wurde seit der Texterkennung verändert. Bitte den Text erneut erkennen.")
        before = {page: _picture(document, page) for page in pages}
        with commands.record(document, history, title, pages=tuple(pages)) as rec:
            for page in pages:
                obj = rec.page(page)
                _remove_layer(document.pdf, obj)
                _place(document, page, obj, layers[page])
            _verify(document, pages, before, {page: layers[page].text for page in pages})
            rec.fresh = True  # ``_verify`` hat die Darstellung des neuen Stands geladen
    finally:
        for layer in layers.values():
            layer.close()
    return len(pages)


def remove_text_layers(document: EditorDocument, history: History, pages) -> int:
    """Textebenen von PDF Tool entfernen (ein Schritt für Rückgängig). Rückgabe: Anzahl geänderter Seiten."""
    document.ensure_editable()
    chosen = sorted({int(page) for page in pages})
    for page in chosen:
        _check_page(document, page)
    targets = [page for page in chosen if has_text_layer(document, page)]
    if not targets:
        return 0
    before = {page: _picture(document, page) for page in targets}
    with commands.record(document, history, "Erkannten Text entfernen", pages=tuple(targets)) as rec:
        for page in targets:
            _remove_layer(document.pdf, rec.page(page))
        _verify(document, targets, before, {})
        rec.fresh = True
    return len(targets)


def _place(document: EditorDocument, page: int, obj: pikepdf.Object, layer: _Layer) -> None:
    """Text-only-Seite als Formular-XObject übernehmen und über die ganze sichtbare Seite legen."""
    pdf = document.pdf
    form = pdf.copy_foreign(layer.source.pages[0].as_form_xobject())
    document.adopt(layer.source)  # qpdf liest die Stream-Daten erst beim Schreiben
    layer.adopted = True
    xobjects = commands.own_resources(obj, pdf, "/XObject").XObject
    number = 1
    while f"{LAYER_PREFIX}{number}" in xobjects:
        number += 1
    name = f"{LAYER_PREFIX}{number}"
    xobjects[name] = form
    matrix = _placement(document.geometry(page), form)
    append_content(pdf, obj, f"{' '.join(fmt(value) for value in matrix)} cm {name} Do".encode("ascii"))


def _placement(geo, form: pikepdf.Object) -> tuple[float, float, float, float, float, float]:
    """Matrix für ``cm``: Formularraum (Breite × Höhe der Anzeige, Ursprung unten links, so ausgerichtet
    wie die Anzeige) → Seitenraum. Die Ecken der Anzeige kommen über ``PageGeometry.to_page`` – damit
    gelten ``/Rotate`` und CropBox-Versatz. Eine ``/Matrix`` des Formulars wird herausgerechnet."""
    bx0, by0, bx1, by1 = normalize(tuple(float(value) for value in form.BBox))
    width, height = bx1 - bx0, by1 - by0
    origin = geo.to_page(0.0, geo.height)  # unten links in der Anzeige
    right = geo.to_page(geo.width, geo.height)  # unten rechts
    top = geo.to_page(0.0, 0.0)  # oben links
    a, b = (right[0] - origin[0]) / width, (right[1] - origin[1]) / width
    c, d = (top[0] - origin[0]) / height, (top[1] - origin[1]) / height
    wanted = (a, b, c, d, origin[0] - a * bx0 - c * by0, origin[1] - b * bx0 - d * by0)
    own = form.get("/Matrix")
    if own is None:
        return wanted
    return mul(invert(tuple(float(value) for value in own)), wanted)  # type: ignore[arg-type]


def _layer_names(obj: pikepdf.Object) -> list[str]:
    return [name for name in page_xobjects(obj) if name.startswith(LAYER_PREFIX)]


def _calls_layer(ins) -> bool:
    return not isinstance(ins, pikepdf.ContentStreamInlineImage) and str(ins.operator) == "Do" and bool(ins.operands) and str(ins.operands[0]).startswith(LAYER_PREFIX)


def _is(ins, operator: str) -> bool:
    return not isinstance(ins, pikepdf.ContentStreamInlineImage) and str(ins.operator) == operator


def _only_layer(stream) -> bool:
    """Ein Inhaltsstrom, der nur eine Textebene zeichnet (so hängt ``_place`` sie an)."""
    if not isinstance(stream, pikepdf.Stream):
        return False
    try:
        instructions = list(pikepdf.parse_content_stream(stream))
    except pikepdf.PdfError:
        return False
    calls = [ins for ins in instructions if _calls_layer(ins)]
    return bool(calls) and all(_calls_layer(ins) or any(_is(ins, op) for op in ("q", "Q", "cm")) for ins in instructions)


def _remove_layer(pdf: pikepdf.Pdf, obj: pikepdf.Object) -> bool:
    """Textebene von PDF Tool aus dem Inhalt und den Ressourcen der Seite nehmen – neue Objekte, die
    bisherigen Streams bleiben unverändert. Rückgabe: ob es eine Ebene gab."""
    names = _layer_names(obj)
    if not names:
        return False
    contents = obj.get("/Contents")
    streams = list(contents) if isinstance(contents, pikepdf.Array) else ([contents] if contents is not None else [])
    kept = [stream for stream in streams if not _only_layer(stream)]
    if len(kept) != len(streams):
        obj["/Contents"] = pikepdf.Array(kept)
    instructions = list(pikepdf.parse_content_stream(obj))
    if any(_calls_layer(ins) for ins in instructions):  # mit anderem Inhalt in einem Strom (nach einer Bearbeitung)
        obj["/Contents"] = pdf.make_stream(pikepdf.unparse_content_stream(_without_layer(instructions)))
    xobjects = commands.own_resources(obj, pdf, "/XObject").XObject
    for name in names:
        if name in xobjects:
            del xobjects[name]
    return True


def _without_layer(instructions: list) -> list:
    """Aufrufe der Textebene samt ihrer Klammer ``q … cm … Q`` entfernen."""
    result = list(instructions)
    index = 0
    while index < len(result):
        if not _calls_layer(result[index]):
            index += 1
            continue
        if index >= 2 and index + 1 < len(result) and _is(result[index - 2], "q") and _is(result[index - 1], "cm") and _is(result[index + 1], "Q"):
            del result[index - 2 : index + 2]
            index -= 2
        else:
            del result[index]
    return result


def _picture(document: EditorDocument, page: int):
    width = max(200, int(document.geometry(page).width * CHECK_SCALE))
    return render.to_pil(render.render_page(document, page, width)).convert("L")


def _verify(document: EditorDocument, pages: list[int], before: dict, texts: dict[int, str]) -> None:
    """Darstellung aller Seiten unverändert (der Text ist unsichtbar), erkannter Text lesbar – sonst
    ``OcrError`` (``commands.record`` nimmt die Änderung dann zurück)."""
    from PIL import ImageChops

    document.touch()  # Darstellung aus dem geänderten Stand
    for page in pages:
        after = _picture(document, page)
        if after.size != before[page].size:
            raise OcrError("Die Seitengröße hätte sich geändert. Die Texterkennung wurde nicht übernommen.")
        diff = ImageChops.difference(before[page], after).point(lambda value: 255 if value > textedit.DIFF_THRESHOLD else 0)
        if diff.getbbox() is not None:
            raise OcrError("Die Textebene hätte die Darstellung der Seite verändert. Die Texterkennung wurde nicht übernommen.")
        wanted = texts.get(page, "")
        if not wanted:
            continue
        found = _squash(textlayer.text(document, page))
        if wanted not in found and Counter(wanted) - Counter(found):  # in Reihenfolge oder wenigstens jedes Zeichen
            raise OcrError("Der erkannte Text ist im PDF nicht lesbar. Die Texterkennung wurde nicht übernommen.")


def _pdf_text(data: bytes) -> str:
    """Text der ersten Seite einer PDF (PDFium), ohne Leerraum – für die Prüfung nach dem Übernehmen."""
    import pypdfium2 as pdfium

    with PDFIUM_LOCK:
        try:
            view = pdfium.PdfDocument(data)
        except pdfium.PdfiumError as exc:
            raise OcrError("Das Ergebnis der Texterkennung ist keine gültige PDF.") from exc
        try:
            page = view[0]
            try:
                textpage = page.get_textpage()
                try:
                    return _squash(textpage.get_text_range())
                finally:
                    textpage.close()
            finally:
                page.close()
        finally:
            view.close()


def _squash(text: str) -> str:
    return re.sub(r"\s+", "", text).replace("\x00", "")


def _check_page(document: EditorDocument, page: int) -> None:
    if not 0 <= int(page) < document.page_count:
        raise OcrError("Diese Seite gibt es im Dokument nicht (mehr).")
