"""Anhänge eines PDFs: auflisten, speichern, öffnen, hinzufügen und entfernen.

Zwei Arten gibt es: Anhänge des Dokuments (Namensbaum ``/EmbeddedFiles``) und Dateianhänge auf einer
Seite (Anmerkung ``/FileAttachment``). Beide lassen sich speichern und öffnen; hinzugefügt und entfernt
werden Anhänge des Dokuments – Dateianhänge auf Seiten sind Kommentare und werden dort gelöscht.

* Geändert wird wie überall über ``commands.record``: Der Namensbaum wird als **neues** Objekt
  geschrieben (flach und sortiert), der alte bleibt für Rückgängig unverändert.
* Öffnen nur für Dokument-, Bild- und Textformate: Programme, Skripte und Verknüpfungen lassen sich
  nur speichern – ein Anhang wird nie ausgeführt.
* Inhalte und Dateinamen von Anhängen werden nie protokolliert.
"""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

import pikepdf
from pikepdf import Array, Dictionary, Name, String

from . import commands
from .commands import History
from .document import EditorDocument
from .errors import EditorError, UnsupportedEdit

MAX_ATTACHMENT = 512 * 1024 * 1024  # größere Dateien werden nicht angehängt (Arbeitsspeicher)
# Öffnen (mit dem zugeordneten Programm) nur für diese Formate – alles andere nur »Speichern unter«
OPENABLE = {
    ".pdf", ".txt", ".csv", ".tsv", ".json", ".xml", ".md", ".log",
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tif", ".tiff", ".webp",
    ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".odt", ".ods", ".odp", ".rtf",
    ".eml", ".msg", ".zip", ".mp3", ".wav", ".mp4",
}


@dataclass(frozen=True)
class AttachmentInfo:
    key: str  # »n:<Name im Baum>« (Dokument) bzw. »a:<Objektnummer>« (Seite)
    name: str  # Dateiname
    description: str
    size: int  # Bytes (−1: unbekannt)
    modified: str
    page: int  # −1: Anhang des Dokuments
    openable: bool


# --- Lesen --------------------------------------------------------------------------------------------------
def list_attachments(document: EditorDocument) -> list[AttachmentInfo]:
    """Anhänge des Dokuments (sortiert nach Name), danach Dateianhänge der Seiten (nach Seite)."""
    result = []
    for key, spec in _tree_entries(document.pdf):
        result.append(_info("n:" + key, spec, -1))
    for index in range(document.page_count):
        annots = document.pdf.pages[index].obj.get("/Annots")
        if not isinstance(annots, Array):
            continue
        for annot in annots:
            if isinstance(annot, Dictionary) and annot.get("/Subtype") == Name.FileAttachment and annot.is_indirect and isinstance(annot.get("/FS"), Dictionary):
                result.append(_info(f"a:{annot.objgen[0]}-{annot.objgen[1]}", annot.FS, index, fallback=_text(annot.get("/Contents"))))
    return result


def _tree_entries(pdf: pikepdf.Pdf) -> list[tuple[str, pikepdf.Object]]:
    names = pdf.Root.get("/Names")
    tree = names.get("/EmbeddedFiles") if isinstance(names, Dictionary) else None
    if not isinstance(tree, Dictionary):
        return []
    try:
        entries = [(str(key), value) for key, value in pikepdf.NameTree(tree).items()]
    except (pikepdf.PdfError, TypeError, ValueError) as exc:
        raise EditorError("Die Anhänge dieses PDFs sind beschädigt und lassen sich nicht lesen.") from exc
    return [(key, value) for key, value in entries if isinstance(value, Dictionary)]


def _info(key: str, spec: Dictionary, page: int, fallback: str = "") -> AttachmentInfo:
    name = _file_name(spec) or fallback or "Anhang"
    stream = _stream(spec)
    size = -1
    modified = ""
    if stream is not None:
        params = stream.get("/Params")
        if isinstance(params, Dictionary):
            try:
                size = int(params.get("/Size", -1))
            except (TypeError, ValueError):
                size = -1
            modified = _date(params.get("/ModDate") or params.get("/CreationDate"))
        if size < 0:
            try:
                size = len(stream.read_bytes())
            except (pikepdf.PdfError, ValueError):
                size = -1
    return AttachmentInfo(key, name, _text(spec.get("/Desc")), size, modified, page, Path(name).suffix.lower() in OPENABLE)


def _file_name(spec: Dictionary) -> str:
    for key in ("/UF", "/F", "/DOS", "/Unix", "/Mac"):
        value = spec.get(key)
        if value is not None:
            name = _text(value).replace("\\", "/").rsplit("/", 1)[-1].strip()
            if name:
                return _safe_name(name)
    return ""


def _safe_name(name: str) -> str:
    """Dateiname ohne Pfadbestandteile und ohne unter Windows unzulässige Zeichen."""
    cleaned = "".join("_" if char in '<>:"/\\|?*' or ord(char) < 32 else char for char in name).strip(" .")
    return cleaned[:180] or "Anhang"


def _stream(spec: Dictionary):
    ef = spec.get("/EF")
    if not isinstance(ef, Dictionary):
        return None
    for key in ("/UF", "/F"):
        stream = ef.get(key)
        if isinstance(stream, pikepdf.Stream):
            return stream
    return None


def _text(value) -> str:
    if value is None:
        return ""
    try:
        return str(value)
    except (TypeError, ValueError):
        return ""


def _date(value) -> str:
    if value is None:
        return ""
    try:
        from pikepdf.models.metadata import decode_pdf_date

        return decode_pdf_date(str(value)).astimezone().strftime("%d.%m.%Y %H:%M")
    except (ValueError, TypeError, AttributeError):
        return ""


def _find(document: EditorDocument, key: str) -> tuple[AttachmentInfo, Dictionary]:
    if key.startswith("n:"):
        for name, spec in _tree_entries(document.pdf):
            if name == key[2:]:
                return _info(key, spec, -1), spec
    elif key.startswith("a:"):
        for info in list_attachments(document):
            if info.key == key:
                number, _sep, generation = key[2:].partition("-")
                annot = document.pdf.get_object((int(number), int(generation)))
                return info, annot.FS
    raise UnsupportedEdit("Der Anhang ist nicht mehr vorhanden.")


def read(document: EditorDocument, key: str) -> tuple[str, bytes]:
    """(Dateiname, Inhalt) eines Anhangs."""
    info, spec = _find(document, key)
    stream = _stream(spec)
    if stream is None:
        raise UnsupportedEdit("Dieser Anhang enthält keine Datei.")
    try:
        return info.name, stream.read_bytes()
    except (pikepdf.PdfError, ValueError) as exc:
        raise EditorError("Der Anhang ist beschädigt und lässt sich nicht lesen.") from exc


# --- Speichern, Öffnen ---------------------------------------------------------------------------------------
def save_to(document: EditorDocument, key: str, target: str | os.PathLike) -> Path:
    """Anhang als Datei speichern (über eine temporäre Datei; ein Abbruch hinterlässt keine halbe Datei)."""
    _name, data = read(document, key)
    target = Path(target)
    handle, temp = tempfile.mkstemp(prefix=".pdftool-", suffix=".tmp", dir=str(target.parent))
    try:
        with os.fdopen(handle, "wb") as out:
            out.write(data)
            out.flush()
            os.fsync(out.fileno())
        os.replace(temp, target)
    except OSError:
        if os.path.exists(temp):
            os.remove(temp)
        raise
    return target


def export_for_opening(document: EditorDocument, key: str, folder: str | os.PathLike) -> Path:
    """Anhang in einen eigenen Ordner schreiben, damit ihn das zugeordnete Programm öffnen kann – nur für
    Formate aus ``OPENABLE`` (Programme und Skripte werden nie geöffnet)."""
    name, data = read(document, key)
    if Path(name).suffix.lower() not in OPENABLE:
        raise UnsupportedEdit("Dieser Dateityp wird aus Sicherheitsgründen nicht geöffnet. Bitte »Speichern unter …« verwenden.")
    folder = Path(tempfile.mkdtemp(prefix="anhang-", dir=str(folder)))
    path = folder / name
    path.write_bytes(data)
    return path


# --- Hinzufügen, Entfernen ------------------------------------------------------------------------------------
def add(document: EditorDocument, history: History, path: str | os.PathLike, description: str = "") -> str:
    """Datei als Anhang des Dokuments hinzufügen; liefert den Schlüssel. Gleiche Namen werden nummeriert."""
    document.ensure_editable()
    path = Path(path)
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise EditorError(f"Die Datei kann nicht gelesen werden ({exc.strerror or 'Zugriff verweigert'}).") from exc
    if size > MAX_ATTACHMENT:
        raise UnsupportedEdit("Die Datei ist zu groß für einen Anhang (höchstens 512 MB).")
    pdf = document.pdf
    entries = _tree_entries(pdf)
    name = _unique(_safe_name(path.name), {key for key, _spec in entries})
    try:
        spec = pikepdf.AttachedFileSpec.from_filepath(pdf, path, description=description)
    except OSError as exc:
        raise EditorError(f"Die Datei kann nicht gelesen werden ({exc.strerror or 'Zugriff verweigert'}).") from exc
    obj = spec.obj  # mit /Params (Größe, Datum, Prüfsumme) von pikepdf
    obj.UF = String(name)
    obj.F = String(name)
    with commands.record(document, history, "Anhang hinzufügen") as rec:
        _write_tree(document, rec, [*entries, (name, pdf.make_indirect(obj))])
    return "n:" + name


def remove(document: EditorDocument, history: History, key: str) -> None:
    """Anhang des Dokuments entfernen (Dateianhänge auf Seiten sind Kommentare – dort löschen)."""
    document.ensure_editable()
    if not key.startswith("n:"):
        raise UnsupportedEdit("Dateianhänge auf einer Seite sind Kommentare – bitte in den Kommentaren löschen.")
    entries = _tree_entries(document.pdf)
    kept = [(name, spec) for name, spec in entries if name != key[2:]]
    if len(kept) == len(entries):
        raise UnsupportedEdit("Der Anhang ist nicht mehr vorhanden.")
    with commands.record(document, history, "Anhang entfernen") as rec:
        _write_tree(document, rec, kept)


def _unique(name: str, taken: set[str]) -> str:
    if name not in taken:
        return name
    stem, suffix = os.path.splitext(name)
    number = 2
    while f"{stem} ({number}){suffix}" in taken:
        number += 1
    return f"{stem} ({number}){suffix}"


def _write_tree(document: EditorDocument, rec, entries: list[tuple[str, pikepdf.Object]]) -> None:
    """Namensbaum ``/EmbeddedFiles`` neu (flach, sortiert) – in eigenem ``/Names`` des Katalogs."""
    pdf = document.pdf
    rec.root(("/Names",))
    names = commands.own_dict(pdf.Root, "/Names", pdf)
    if entries:
        flat = []
        # Reihenfolge wie die PDF-Norm sie verlangt: nach den Bytes der Schlüssel (PDFDocEncoding bzw. UTF-16)
        for name, spec in sorted(entries, key=lambda item: bytes(String(item[0]))):
            flat += [String(name), spec]
        names.EmbeddedFiles = pdf.make_indirect(Dictionary(Names=Array(flat)))
    elif "/EmbeddedFiles" in names:
        del names["/EmbeddedFiles"]
    if not len(names.keys()):
        del pdf.Root["/Names"]
