"""Eigenschaften und Metadaten: Titel, Autor, Thema und Stichwörter lesen und ändern (Info-
Dictionary und XMP bleiben übereinstimmend), dazu technische Angaben für »Eigenschaften«
(PDF-Version, Seitengröße, Schriften, Verschlüsselung, Berechtigungen, Formular, Signaturen …).

Es werden nur Strukturen gelesen – keine Inhalte protokolliert.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

import pikepdf
from pikepdf import Dictionary, Name, String

from . import commands, xmp
from .commands import History
from .document import EditorDocument
from .errors import EditorError

EDITABLE = (("title", "/Title", "dc:title"), ("author", "/Author", "dc:creator"), ("subject", "/Subject", "dc:description"), ("keywords", "/Keywords", "pdf:Keywords"))
FONT_SCAN_PAGES = 500  # Schriften werden auf höchstens so vielen Seiten gesucht (große Dokumente)
MM_PER_PT = 25.4 / 72


@dataclass
class Properties:
    file_name: str
    path: str
    size_bytes: int
    pdf_version: str
    pages: int
    page_size: str  # z. B. »210 × 297 mm (A4)« der ersten Seite
    title: str = ""
    author: str = ""
    subject: str = ""
    keywords: str = ""
    creator: str = ""
    producer: str = ""
    created: str = ""
    modified: str = ""
    encrypted: bool = False
    encryption: str = ""
    restrictions: list[str] = field(default_factory=list)
    fonts: list[tuple[str, str, bool]] = field(default_factory=list)  # (Name, Art, eingebettet)
    fonts_complete: bool = True
    tagged: bool = False
    linearized: bool = False
    form: str = ""  # »AcroForm«, »XFA« oder leer
    signatures: int = 0
    javascript: bool = False
    attachments: int = 0
    layers: bool = False


# --- Lesen -------------------------------------------------------------------------------------------------
def read(document: EditorDocument) -> Properties:
    pdf = document.pdf
    info = _info_dict(pdf)
    try:
        size = document.path.stat().st_size if document.path is not None and document.path.exists() else 0
    except OSError:
        size = 0
    geo = document.geometry(0)
    props = Properties(
        file_name=document.name,
        path=str(document.path or ""),
        size_bytes=size,
        pdf_version=str(pdf.pdf_version),
        pages=document.page_count,
        page_size=page_size_text(geo.width, geo.height),
    )
    for attr, key, _xmp in EDITABLE:
        setattr(props, attr, _text(info.get(key)) if info is not None else "")
    if info is not None:
        props.creator = _text(info.get("/Creator"))
        props.producer = _text(info.get("/Producer"))
        props.created = _date(info.get("/CreationDate"))
        props.modified = _date(info.get("/ModDate"))
    props.encrypted = bool(pdf.is_encrypted)
    if pdf.is_encrypted:
        # Nur Verfahren und Schlüssellänge lesen – das Objekt enthält auch Passwort und Schlüssel
        try:
            info = pdf.encryption
            method = str(info.stream_method.name).lower()
            name = "AES" if method.startswith("aes") else ("RC4" if method.startswith("rc4") else "verschlüsselt")
            props.encryption = f"{name} ({int(info.bits)} Bit)" if name != "verschlüsselt" and info.bits else name
        except (AttributeError, ValueError, TypeError):
            props.encryption = "verschlüsselt"
    props.restrictions = document.permissions.summary()
    props.fonts, props.fonts_complete = _fonts(pdf)
    root = pdf.Root
    mark = root.get("/MarkInfo")
    props.tagged = isinstance(mark, Dictionary) and bool(mark.get("/Marked", False)) or "/StructTreeRoot" in root
    try:
        props.linearized = bool(pdf.is_linearized)
    except (pikepdf.PdfError, AttributeError):
        props.linearized = False
    props.form = "XFA" if document.report.xfa else ("AcroForm" if isinstance(root.get("/AcroForm"), Dictionary) and len(root.AcroForm.get("/Fields", [])) else "")
    props.signatures = document.report.signed
    props.javascript = document.report.javascript
    try:
        props.attachments = len(pdf.attachments)
    except (pikepdf.PdfError, TypeError, ValueError):
        props.attachments = 0
    props.layers = "/OCProperties" in root
    return props


def page_size_text(width: float, height: float) -> str:
    w, h = round(width * MM_PER_PT), round(height * MM_PER_PT)
    names = {(210, 297): "A4", (148, 210): "A5", (297, 420): "A3", (216, 279): "Letter", (216, 356): "Legal", (105, 148): "A6"}
    portrait = (min(w, h), max(w, h))
    name = next((label for (a, b), label in names.items() if abs(portrait[0] - a) <= 1 and abs(portrait[1] - b) <= 1), "")
    orientation = "" if not name else (" Querformat" if w > h else "")
    return f"{w} × {h} mm" + (f" ({name}{orientation})" if name else "")


def _info_dict(pdf: pikepdf.Pdf):
    info = pdf.trailer.get("/Info")
    return info if isinstance(info, Dictionary) else None


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


def _fonts(pdf: pikepdf.Pdf) -> tuple[list[tuple[str, str, bool]], bool]:
    seen: dict = {}
    complete = len(pdf.pages) <= FONT_SCAN_PAGES

    def visit(resources, depth: int = 0) -> None:
        if not isinstance(resources, Dictionary) or depth > 6:
            return
        fonts = resources.get("/Font")
        if isinstance(fonts, Dictionary):
            for font in fonts.values():
                if isinstance(font, Dictionary) and font.objgen not in seen:
                    seen[font.objgen if font.is_indirect else id(font)] = _font_entry(font)
        xobjects = resources.get("/XObject")
        if isinstance(xobjects, Dictionary):
            for xobject in xobjects.values():
                if isinstance(xobject, pikepdf.Stream) and xobject.get("/Subtype") == Name.Form:
                    visit(xobject.get("/Resources"), depth + 1)

    from .document import inherited

    for page in list(pdf.pages)[:FONT_SCAN_PAGES]:
        visit(inherited(page.obj, "/Resources"))
    entries = sorted(set(seen.values()), key=lambda item: item[0].lower())
    return entries, complete


def _font_entry(font) -> tuple[str, str, bool]:
    name = str(font.get("/BaseFont", "")).lstrip("/").split("+", 1)[-1] or "(ohne Namen)"
    subtype = str(font.get("/Subtype", "")).lstrip("/")
    descriptor = font.get("/FontDescriptor")
    if subtype == "Type0" and isinstance(font.get("/DescendantFonts"), pikepdf.Array) and len(font.DescendantFonts):
        descriptor = font.DescendantFonts[0].get("/FontDescriptor")
    embedded = isinstance(descriptor, Dictionary) and any(key in descriptor for key in ("/FontFile", "/FontFile2", "/FontFile3")) or subtype == "Type3"
    kinds = {"Type1": "Type 1", "TrueType": "TrueType", "Type0": "Type 0 (CID)", "Type3": "Type 3", "MMType1": "Multiple Master"}
    return (name, kinds.get(subtype, subtype), bool(embedded))


# --- Ändern -----------------------------------------------------------------------------------------------
def update(document: EditorDocument, history: History, *, title: str | None = None, author: str | None = None, subject: str | None = None, keywords: str | None = None) -> None:
    """Titel, Autor, Thema, Stichwörter setzen (leer = entfernen) – Info und XMP gemeinsam."""
    document.ensure_editable()
    values = {"title": title, "author": author, "subject": subject, "keywords": keywords}
    if all(value is None for value in values.values()):
        return
    pdf = document.pdf
    with commands.record(document, history, "Eigenschaften ändern") as rec:
        rec.object(pdf.trailer, ("/Info",))
        info = _info_dict(pdf)
        if info is None:
            pdf.trailer.Info = pdf.make_indirect(Dictionary())
            info = pdf.trailer.Info
        rec.object(info, tuple(key for _attr, key, _xmp in EDITABLE) + ("/ModDate",))
        rec.root(("/Metadata",))
        for attr, key, _xmp in EDITABLE:
            value = values[attr]
            if value is None:
                continue
            if value.strip():
                info[key] = String(value.strip())
            elif key in info:
                del info[key]
        from pikepdf.models.metadata import encode_pdf_date

        now = datetime.now(timezone.utc)
        info.ModDate = String(encode_pdf_date(now))
        old = pdf.Root.get("/Metadata")
        if isinstance(old, pikepdf.Stream):
            # XMP angleichen – mit der Standardbibliothek (lxml gehört nicht zur Laufzeit, pikepdfs
            # open_metadata bräuchte es). In eine neue Kopie schreiben: der bisherige Stream bleibt
            # für Rückgängig unverändert. Beschädigtes XMP: nichts ändern (Rückgängig stellt Info wieder her).
            try:
                updated = xmp.sync(old.read_bytes(), {attr: values[attr] for attr, _key, _xmp in EDITABLE}, now)
            except (xmp.XmpError, pikepdf.PdfError) as exc:
                raise EditorError("Die XMP-Metadaten dieses PDFs sind beschädigt und wurden nicht geändert.") from exc
            copy = pdf.make_stream(updated)
            copy.Type = Name.Metadata
            copy.Subtype = Name.XML
            pdf.Root.Metadata = copy
