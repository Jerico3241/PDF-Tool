"""Künstliche Test-PDFs für den PDF Reader/Editor – deterministisch per Code erzeugt.

Keine echten Dokumente: Texte, Namen und Werte sind frei erfunden. Schriften stammen aus
ReportLab (Standardschriften, Bitstream Vera – freie Lizenz) und werden je nach Fall als
Standardschrift (nicht eingebettet), eingebettete Teilmenge (TrueType) oder CID-Schrift
(Identity-H, über PDFium) geschrieben.
"""

from __future__ import annotations

import ctypes
import io
from pathlib import Path

import pikepdf
from pikepdf import Array, Dictionary, Name, String

A4 = (595.0, 842.0)


def vera_path() -> Path:
    import reportlab

    return Path(reportlab.__file__).parent / "fonts" / "Vera.ttf"


def standard_text(path: Path, pages: int = 1, lines: tuple[str, ...] | None = None) -> Path:
    """Standardschriften (Helvetica, Helvetica-Bold, Times), WinAnsi, nicht eingebettet."""
    from reportlab.pdfgen import canvas

    lines = lines or ("Rechnung Nr. 4711 vom 01.10.2026", "Gesamtbetrag: 1.234,56 EUR", "Zahlbar innerhalb von 14 Tagen.")
    c = canvas.Canvas(str(path), pagesize=A4)
    c.setTitle("Testdokument")
    c.setAuthor("PDF Tool Tests")
    for number in range(pages):
        c.setFont("Helvetica", 14)
        c.drawString(72, 760, lines[0])
        c.setFont("Helvetica-Bold", 12)
        c.drawString(72, 730, lines[1] if len(lines) > 1 else "")
        c.setFont("Times-Roman", 11)
        c.drawString(72, 700, lines[2] if len(lines) > 2 else "")
        c.setFont("Helvetica", 9)
        c.drawString(72, 60, f"Seite {number + 1} von {pages}")
        c.showPage()
    c.save()
    return path


# XMP-Metadaten wie aus Word oder Acrobat: einfache Eigenschaften als Attribute, Listen als Elemente
XMP_PACKET = """<?xpacket begin="\ufeff" id="W5M0MpCehiHzreSzNTczkc9d"?>
<x:xmpmeta xmlns:x="adobe:ns:meta/" x:xmptk="Adobe XMP Core 5.6">
 <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
  <rdf:Description rdf:about="" xmlns:pdf="http://ns.adobe.com/pdf/1.3/" pdf:Producer="Textverarbeitung 365" pdf:PDFVersion="1.7"/>
  <rdf:Description rdf:about="" xmlns:xmp="http://ns.adobe.com/xap/1.0/" xmp:CreatorTool="Textverarbeitung 365" xmp:CreateDate="2026-09-30T10:00:00+02:00" xmp:ModifyDate="2026-09-30T10:00:00+02:00"/>
  <rdf:Description rdf:about="" xmlns:dc="http://purl.org/dc/elements/1.1/">
   <dc:format>application/pdf</dc:format>
   <dc:title><rdf:Alt><rdf:li xml:lang="x-default">Testdokument</rdf:li></rdf:Alt></dc:title>
   <dc:creator><rdf:Seq><rdf:li>PDF Tool Tests</rdf:li></rdf:Seq></dc:creator>
  </rdf:Description>
 </rdf:RDF>
</x:xmpmeta>
<?xpacket end="w"?>"""


def with_xmp(path: Path, pages: int = 1) -> Path:
    """Wie ``standard_text``, zusätzlich mit XMP-Metadaten (die meisten echten PDFs haben welche) –
    ohne lxml geschrieben, wie es die Laufzeit der App auch nicht hat."""
    standard_text(path, pages=pages)
    with pikepdf.open(path, allow_overwriting_input=True) as pdf:
        stream = pdf.make_stream(XMP_PACKET.encode("utf-8"))
        stream.Type = Name.Metadata
        stream.Subtype = Name.XML
        pdf.Root.Metadata = stream
        pdf.save(path, fix_metadata_version=False)
    return path


def paragraph(path: Path) -> Path:
    """Ein Absatz über mehrere Zeilen (je Zeile ein Textoperator, gleicher Zeilenabstand)."""
    from reportlab.pdfgen import canvas

    c = canvas.Canvas(str(path), pagesize=A4)
    text = c.beginText(72, 760)
    text.setFont("Helvetica", 12)
    text.setLeading(15)
    for line in ("Dies ist ein Absatz mit mehreren Zeilen,", "der als Block bearbeitet werden kann und", "dabei seine Breite behalten soll."):
        text.textLine(line)
    c.drawText(text)
    c.setFont("Helvetica", 12)
    c.drawString(72, 600, "Ein zweiter Block weiter unten.")
    c.showPage()
    c.save()
    return path


def subset_font(path: Path) -> Path:
    """Eingebettete TrueType-Teilmenge (Bitstream Vera) – nur die verwendeten Zeichen."""
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.pdfgen import canvas

    pdfmetrics.registerFont(TTFont("VeraTest", str(vera_path())))
    c = canvas.Canvas(str(path), pagesize=A4)
    c.setFont("VeraTest", 14)
    c.drawString(72, 760, "Angebot fuer Muster GmbH")
    c.setFont("VeraTest", 11)
    c.drawString(72, 730, "Preis: 99 EUR netto")
    c.showPage()
    c.save()
    return path


def cid_font(path: Path, lines: tuple[str, ...] = ("Lieferschein 2026-0042", "Menge: 3 Stück")) -> Path:
    """CID-Schrift (Type0, Identity-H) über PDFium – wie bei vielen Office-PDFs."""
    import pypdfium2 as pdfium
    import pypdfium2.raw as r

    data = vera_path().read_bytes()
    doc = pdfium.PdfDocument.new()
    page = doc.new_page(*A4)
    buffer = (ctypes.c_uint8 * len(data)).from_buffer_copy(data)
    font = r.FPDFText_LoadFont(doc.raw, buffer, len(data), r.FPDF_FONT_TRUETYPE, 1)
    y = 760.0
    for line in lines:
        obj = r.FPDFPageObj_CreateTextObj(doc.raw, font, 14.0)
        text = (line + "\0").encode("utf-16-le")
        r.FPDFText_SetText(obj, ctypes.cast(ctypes.c_char_p(text), r.FPDF_WIDESTRING))
        r.FPDFPageObj_Transform(obj, 1, 0, 0, 1, 72, y)
        r.FPDFPage_InsertObject(page.raw, obj)
        y -= 30
    r.FPDFPage_GenerateContent(page.raw)
    r.FPDFFont_Close(font)
    buf = io.BytesIO()
    doc.save(buf)
    path.write_bytes(buf.getvalue())
    return path


def rotated(path: Path) -> Path:
    """Vier Seiten mit /Rotate 0, 90, 180, 270 und eine mit eigener CropBox."""
    source = standard_text(path.with_name(path.stem + "-quelle.pdf"))
    src = pikepdf.open(source)
    pdf = pikepdf.new()
    for angle in (0, 90, 180, 270):
        pdf.pages.append(src.pages[0])
        pdf.pages[-1].Rotate = angle
    pdf.pages.append(src.pages[0])
    pdf.pages[-1].CropBox = Array([50, 600, 450, 800])
    pdf.save(path)
    src.close()
    source.unlink()
    return path


def complex_content(path: Path) -> Path:
    """Inhaltsstrom mit markiertem Inhalt (Artefakt, MCID), Inline-Bild, Fläche und TJ mit Kerning."""
    pdf = pikepdf.new()
    page = pdf.add_blank_page(page_size=A4)
    font = pdf.make_indirect(Dictionary(Type=Name.Font, Subtype=Name.Type1, BaseFont=Name.Helvetica, Encoding=Name.WinAnsiEncoding))
    page.Resources = Dictionary(Font=Dictionary(F1=font))
    page.Contents = pdf.make_stream(
        b"/Artifact <</Type /Pagination>> BDC\nBT /F1 12 Tf 72 800 Td (Kopfzeile Artefakt) Tj ET\nEMC\n"
        b"/P <</MCID 0>> BDC\nBT /F1 14 Tf 72 760 Td [(Ver) 30 (trag ) -200 (Nr. 9)] TJ ET\nEMC\n"
        b"q 100 0 0 50 72 600 cm BI /W 2 /H 2 /CS /G /BPC 8 ID \x00\xff\xff\x00 EI Q\n"
        b"q 0.2 0.4 0.8 rg 300 600 100 50 re f Q\n"
    )
    pdf.save(path)
    return path


def _helvetica(pdf: pikepdf.Pdf) -> pikepdf.Object:
    return pdf.make_indirect(Dictionary(Type=Name.Font, Subtype=Name.Type1, BaseFont=Name.Helvetica, Encoding=Name.WinAnsiEncoding))


def form_xobject_text(path: Path) -> Path:
    """Text in einem Formular-XObject (wie ein eingebetteter Briefkopf) und Text direkt auf der Seite."""
    pdf = pikepdf.new()
    page = pdf.add_blank_page(page_size=A4)
    font = _helvetica(pdf)
    head = pdf.make_stream(b"BT /F1 12 Tf 0 10 Td (Briefkopf Muster AG) Tj ET", Type=Name.XObject, Subtype=Name.Form, BBox=Array([0, 0, 300, 40]), Resources=Dictionary(Font=Dictionary(F1=font)))
    page.Resources = Dictionary(Font=Dictionary(F1=font), XObject=Dictionary(X1=head))
    page.Contents = pdf.make_stream(b"q 1 0 0 1 72 770 cm /X1 Do Q\nBT /F1 12 Tf 72 700 Td (Text auf der Seite) Tj ET\n")
    pdf.save(path)
    return path


def scanned_with_ocr(path: Path) -> Path:
    """»Gescannte« Seite: Bild mit Schrift, darüber unsichtbarer Text einer Texterkennung (Tr 3)."""
    from PIL import Image, ImageDraw, ImageFont

    image = Image.new("L", (600, 100), 244)  # leicht grauer »Papier«-Hintergrund
    ImageDraw.Draw(image).text((10, 25), "Rechnung 123", fill=20, font=ImageFont.truetype(str(vera_path()), 48))
    pdf = pikepdf.new()
    page = pdf.add_blank_page(page_size=A4)
    scan = pdf.make_stream(image.tobytes(), Type=Name.XObject, Subtype=Name.Image, Width=600, Height=100, ColorSpace=Name.DeviceGray, BitsPerComponent=8)
    page.Resources = Dictionary(Font=Dictionary(F1=_helvetica(pdf)), XObject=Dictionary(Im1=scan))
    page.Contents = pdf.make_stream(b"q 300 0 0 50 72 700 cm /Im1 Do Q\nBT 3 Tr /F1 22 Tf 77 714 Td (Rechnung 123) Tj ET\n")
    pdf.save(path)
    return path


def scaled_text(path: Path) -> Path:
    """Schriftgröße 1 mit skalierter Textmatrix (wirksam 12 pt) – wie bei manchen Programmen."""
    pdf = pikepdf.new()
    page = pdf.add_blank_page(page_size=A4)
    page.Resources = Dictionary(Font=Dictionary(F1=_helvetica(pdf)))
    page.Contents = pdf.make_stream(b"BT /F1 1 Tf 12 0 0 12 72 760 Tm (Skalierter Text) Tj ET\nBT /F1 10 Tf 72 700 Td (Zweite Zeile) Tj ET\n")
    pdf.save(path)
    return path


def vertical_text(path: Path) -> Path:
    """Senkrechter Text (Textmatrix um 90° gedreht) neben waagerechtem Text."""
    pdf = pikepdf.new()
    page = pdf.add_blank_page(page_size=A4)
    page.Resources = Dictionary(Font=Dictionary(F1=_helvetica(pdf)))
    page.Contents = pdf.make_stream(b"BT /F1 12 Tf 0 1 -1 0 60 300 Tm (Senkrechter Rand) Tj ET\nBT /F1 12 Tf 100 700 Td (Waagerecht) Tj ET\n")
    pdf.save(path)
    return path


def with_images(path: Path) -> Path:
    """Ein JPEG und ein PNG mit Transparenz (über ReportLab, Bilder per PIL erzeugt)."""
    from PIL import Image, ImageDraw
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas

    photo = Image.new("RGB", (120, 80), (40, 120, 200))
    ImageDraw.Draw(photo).ellipse((20, 10, 100, 70), fill=(250, 200, 40))
    logo = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    ImageDraw.Draw(logo).rectangle((8, 8, 56, 56), fill=(200, 30, 30, 160))
    jpeg, png = io.BytesIO(), io.BytesIO()
    photo.save(jpeg, "JPEG", quality=85)
    logo.save(png, "PNG")
    c = canvas.Canvas(str(path), pagesize=A4)
    c.setFont("Helvetica", 12)
    c.drawString(72, 780, "Seite mit zwei Bildern")
    c.drawImage(ImageReader(io.BytesIO(jpeg.getvalue())), 72, 600, width=180, height=120)
    c.drawImage(ImageReader(io.BytesIO(png.getvalue())), 320, 600, width=96, height=96, mask="auto")
    c.showPage()
    c.save()
    return path


def direct_image(path: Path, rotate: int = 0) -> Path:
    """Bild-XObject direkt auf der Seite (``q … cm /Im1 Do Q``) und etwas Text."""
    from PIL import Image

    photo = Image.new("RGB", (40, 20), (30, 160, 60))
    pdf = pikepdf.new()
    page = pdf.add_blank_page(page_size=A4)
    image = pdf.make_stream(photo.tobytes(), Type=Name.XObject, Subtype=Name.Image, Width=40, Height=20, ColorSpace=Name.DeviceRGB, BitsPerComponent=8)
    page.Resources = Dictionary(Font=Dictionary(F1=_helvetica(pdf)), XObject=Dictionary(Im1=image))
    page.Contents = pdf.make_stream(b"q 200 0 0 100 100 500 cm /Im1 Do Q\nBT /F1 12 Tf 100 450 Td (Bildunterschrift) Tj ET\n")
    if rotate:
        page.Rotate = rotate
    pdf.save(path)
    return path


def image_in_form(path: Path) -> Path:
    """Bild in einem Formular-XObject (wie es manche Programme für Logos schreiben)."""
    from PIL import Image

    photo = Image.new("RGB", (30, 20), (30, 160, 60))
    pdf = pikepdf.new()
    page = pdf.add_blank_page(page_size=A4)
    image = pdf.make_stream(photo.tobytes(), Type=Name.XObject, Subtype=Name.Image, Width=30, Height=20, ColorSpace=Name.DeviceRGB, BitsPerComponent=8)
    form = pdf.make_stream(b"q 180 0 0 120 0 0 cm /Im0 Do Q", Type=Name.XObject, Subtype=Name.Form, BBox=Array([0, 0, 180, 120]), Resources=Dictionary(XObject=Dictionary(Im0=image)))
    page.Resources = Dictionary(XObject=Dictionary(Fm1=form))
    page.Contents = pdf.make_stream(b"q 1 0 0 1 72 600 cm /Fm1 Do Q\n")
    pdf.save(path)
    return path


def two_tone_png(path: Path, alpha: bool = False) -> Path:
    """PNG 60×40: obere Hälfte rot, untere blau (zum Prüfen der Ausrichtung); optional mit
    durchsichtigem rechten Drittel."""
    from PIL import Image, ImageDraw

    image = Image.new("RGBA", (60, 40), (0, 0, 255, 255))
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 59, 19), fill=(255, 0, 0, 255))
    if alpha:
        draw.rectangle((40, 0, 59, 39), fill=(0, 0, 0, 0))
    image.save(path, "PNG")
    return path


def photo_jpeg(path: Path, size: tuple[int, int] = (80, 60)) -> Path:
    from PIL import Image

    Image.new("RGB", size, (200, 120, 40)).save(path, "JPEG", quality=90)
    return path


def structured(path: Path) -> Path:
    """Lesezeichen, Link, Notiz-Anmerkung, Anhang, Metadaten, Ebenen und Sprungziel."""
    standard_text(path, pages=3)
    pdf = pikepdf.open(path, allow_overwriting_input=True)
    with pdf.open_outline() as outline:
        chapter = pikepdf.OutlineItem("Kapitel 1", 0)
        chapter.children.append(pikepdf.OutlineItem("Abschnitt 1.1", 1))
        outline.root.append(chapter)
        outline.root.append(pikepdf.OutlineItem("Kapitel 2", 2))
    link = pdf.make_indirect(Dictionary(Type=Name.Annot, Subtype=Name.Link, Rect=Array([72, 50, 200, 70]), Border=Array([0, 0, 0]), Dest=Array([pdf.pages[2].obj, Name.Fit])))
    note = pdf.make_indirect(Dictionary(Type=Name.Annot, Subtype=Name.Text, Rect=Array([400, 760, 420, 780]), Contents=String("Bitte prüfen"), Name=Name.Comment, C=Array([1, 0.8, 0])))
    pdf.pages[0].Annots = pdf.make_indirect(Array([link, note]))
    layer = pdf.make_indirect(Dictionary(Type=Name.OCG, Name=String("Wasserzeichen")))
    pdf.Root.OCProperties = Dictionary(OCGs=Array([layer]), D=Dictionary(ON=Array([layer])))
    pdf.Root.Names = pdf.make_indirect(Dictionary(Dests=Dictionary(Names=Array([String("ende"), Array([pdf.pages[2].obj, Name.Fit])]))))
    pdf.attachments["notiz.txt"] = pikepdf.AttachedFileSpec(pdf, b"Anhang zum Test", mime_type="text/plain")  # nach /Names (sonst überschrieben)
    # XMP ohne lxml (wie die App): Titel »Strukturtest« in Info und XMP
    pdf.docinfo["/Title"] = "Strukturtest"
    xmp = pdf.make_stream(XMP_PACKET.replace("Testdokument", "Strukturtest").encode("utf-8"))
    xmp.Type = Name.Metadata
    xmp.Subtype = Name.XML
    pdf.Root.Metadata = xmp
    pdf.save(path, fix_metadata_version=False)
    pdf.close()
    return path


def form(path: Path) -> Path:
    """AcroForm mit Textfeld, Kontrollkästchen, Optionsfeldern, Auswahl- und Listenfeld."""
    from reportlab.pdfgen import canvas

    c = canvas.Canvas(str(path), pagesize=A4)
    c.setFont("Helvetica", 12)
    c.drawString(72, 790, "Formular (künstlich)")
    acro = c.acroForm
    c.drawString(72, 752, "Name:")
    acro.textfield(name="name", x=140, y=745, width=200, height=20, value="", borderStyle="inset", forceBorder=True)
    c.drawString(72, 712, "Einverstanden:")
    acro.checkbox(name="ok", x=180, y=708, size=14, checked=False, buttonStyle="check")
    c.drawString(72, 672, "Versand:")
    acro.radio(name="versand", value="post", x=150, y=668, size=14, selected=True)
    acro.radio(name="versand", value="mail", x=220, y=668, size=14, selected=False)
    c.drawString(72, 632, "Land:")
    acro.choice(name="land", x=140, y=625, width=150, height=20, value="Deutschland", options=["Deutschland", "Österreich", "Schweiz"])
    c.drawString(72, 592, "Farben:")
    acro.listbox(name="farben", x=140, y=530, width=150, height=60, value="Rot", options=["Rot", "Grün", "Blau"])
    c.showPage()
    c.save()
    return path


def encrypted(path: Path, user: str = "geheim", owner: str = "besitzer", allow_edit: bool = True) -> Path:
    tmp = standard_text(path.with_name(path.stem + "-offen.pdf"))
    pdf = pikepdf.open(tmp)
    allow = pikepdf.Permissions(modify_other=allow_edit, modify_annotation=allow_edit, modify_form=allow_edit, modify_assembly=allow_edit)
    pdf.save(path, encryption=pikepdf.Encryption(user=user, owner=owner, R=6, allow=allow))
    pdf.close()
    tmp.unlink()
    return path


def copy_protected(path: Path) -> Path:
    """Ohne Kennwort lesbar und bearbeitbar, aber Kopieren (Inhalte herauslösen) ist nicht erlaubt."""
    tmp = mixed_objects(path.with_name(path.stem + "-offen.pdf"))
    pdf = pikepdf.open(tmp)
    allow = pikepdf.Permissions(extract=False, accessibility=True)
    pdf.save(path, encryption=pikepdf.Encryption(user="", owner="besitzer", R=6, allow=allow))
    pdf.close()
    tmp.unlink()
    return path


def signed(path: Path) -> Path:
    """Signaturfeld mit Wert (nur Struktur, keine echte Kryptografie) – zum Erkennen und Warnen."""
    standard_text(path)
    pdf = pikepdf.open(path, allow_overwriting_input=True)
    value = pdf.make_indirect(Dictionary(Type=Name.Sig, Filter=Name("/Adobe.PPKLite"), SubFilter=Name("/adbe.pkcs7.detached"), ByteRange=Array([0, 10, 20, 10]), Contents=String(b"\x00" * 16)))
    widget = pdf.make_indirect(Dictionary(Type=Name.Annot, Subtype=Name.Widget, FT=Name.Sig, T=String("Unterschrift"), V=value, Rect=Array([0, 0, 0, 0]), F=132, P=pdf.pages[0].obj))
    pdf.pages[0].Annots = pdf.make_indirect(Array([widget]))
    pdf.Root.AcroForm = pdf.make_indirect(Dictionary(Fields=Array([widget]), SigFlags=3))
    pdf.save(path)
    pdf.close()
    return path


def big(path: Path, pages: int = 500) -> Path:
    """Viele Seiten (je Seite eigener Text) – schnell über pikepdf vervielfältigt."""
    pdf = pikepdf.new()
    font = pdf.make_indirect(Dictionary(Type=Name.Font, Subtype=Name.Type1, BaseFont=Name.Helvetica, Encoding=Name.WinAnsiEncoding))
    for number in range(pages):
        page = pdf.add_blank_page(page_size=A4)
        page.Resources = Dictionary(Font=Dictionary(F1=font))
        text = f"Seite {number + 1} von {pages} - Suchwort{'Treffer' if number % 50 == 7 else ''}"
        page.Contents = pdf.make_stream(f"BT /F1 18 Tf 72 760 Td ({text}) Tj ET\nq 0.9 0.9 0.95 rg 60 100 475 600 re f Q\n".encode("latin-1"))
    pdf.save(path)
    return path


def damaged(path: Path) -> Path:
    """PDF-Kopf, danach nur Datenmüll – weder qpdf noch PDFium können das öffnen."""
    import random

    noise = random.Random(4711).randbytes(20000)
    path.write_bytes(b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n" + noise)
    return path


# --- Objekt bearbeiten: Testfälle A–L -------------------------------------------------------------------------
def _page_with(pdf: pikepdf.Pdf, content: bytes, fonts: dict | None = None, xobjects: dict | None = None) -> pikepdf.Object:
    page = pdf.add_blank_page(page_size=A4)
    resources = Dictionary(Font=Dictionary(fonts or {"/F1": _helvetica(pdf)}))
    if xobjects:
        resources.XObject = Dictionary(xobjects)
    page.Resources = resources
    page.Contents = pdf.make_stream(content)
    return page


def _font(pdf: pikepdf.Pdf, base: str) -> pikepdf.Object:
    return pdf.make_indirect(Dictionary(Type=Name.Font, Subtype=Name.Type1, BaseFont=Name("/" + base), Encoding=Name.WinAnsiEncoding))


def object_line(path: Path) -> Path:
    """A: eine einfache Textzeile."""
    pdf = pikepdf.new()
    _page_with(pdf, b"BT /F1 14 Tf 72 760 Td (Rechnung Nr. 4711) Tj ET\n")
    pdf.save(path)
    return path


def object_address(path: Path) -> Path:
    """B/F: Adresse – vier sichtbare Zeilen in **einem** Textobjekt (ein BT … ET, Zeilen per Td)."""
    pdf = pikepdf.new()
    _page_with(pdf, (
        "BT /F1 11 Tf 72 760 Td (Firma) Tj 0 -14 Td (Hottgenroth Software AG) Tj "
        "0 -14 Td (Von-H\xfcnefeld-Str. 3) Tj 0 -14 Td (50829 K\xf6ln) Tj ET\n"
    ).encode("cp1252"))
    pdf.save(path)
    return path


def object_split_word(path: Path) -> Path:
    """C: ein Wort aus mehreren Textoperatoren (»Hott« + »genroth«), danach » Software AG«."""
    pdf = pikepdf.new()
    _page_with(pdf, b"BT /F1 12 Tf 72 760 Td (Hott) Tj (genroth) Tj ( Software AG) Tj ET\n")
    pdf.save(path)
    return path


def object_kerned_words(path: Path) -> Path:
    """Wortabstände als TJ-Verschiebung ohne Leerzeichen – wie viele Programme sie schreiben."""
    pdf = pikepdf.new()
    _page_with(pdf, b"BT /F1 12 Tf 72 760 Td [(Hottgenroth) -280 (Software) -280 (AG)] TJ ET\n")
    pdf.save(path)
    return path


def object_fonts(path: Path) -> Path:
    """D: mehrere Wörter einer Zeile in unterschiedlichen Schriften."""
    pdf = pikepdf.new()
    fonts = {"/F1": _helvetica(pdf), "/F2": _font(pdf, "Helvetica-Bold"), "/F3": _font(pdf, "Times-Italic")}
    _page_with(pdf, b"BT /F1 12 Tf 72 760 Td (Normal ) Tj /F2 12 Tf (Fett ) Tj /F3 12 Tf (Kursiv) Tj ET\n", fonts)
    pdf.save(path)
    return path


def object_table(path: Path) -> Path:
    """E/51: Tabellenkopf und -zeile, jede Zelle ein eigener Operator an eigener Stelle."""
    pdf = pikepdf.new()
    head = [(72, "Pos."), (112, "Anz."), (152, "Leistung"), (330, "St\xfcckpreis"), (430, "Gesamtpreis")]
    row = [(72, "1"), (112, "2"), (152, "Wartung Software"), (330, "120,00"), (430, "240,00")]
    parts = []
    for y, cells in ((760, head), (742, row)):
        for x, text in cells:
            parts.append(f"BT /F1 10 Tf {x} {y} Td ({text}) Tj ET")
    _page_with(pdf, ("\n".join(parts) + "\n").encode("cp1252"))
    pdf.save(path)
    return path


def object_table_one_operator(path: Path) -> Path:
    """Tabellenzeile in einem einzigen TJ: Spalten nur durch große Verschiebungen getrennt."""
    pdf = pikepdf.new()
    _page_with(pdf, b"BT /F1 10 Tf 72 760 Td [(Pos.) -2400 (Anz.) -2400 (Leistung) -9000 (Gesamt)] TJ ET\n")
    pdf.save(path)
    return path


def object_colored_background(path: Path) -> Path:
    """G: Text auf farbiger Fläche."""
    pdf = pikepdf.new()
    _page_with(pdf, b"q 0.80 0.88 1 rg 60 740 300 40 re f Q\nBT /F1 14 Tf 72 755 Td (Auf blauer Fl\xe4che) Tj ET\nBT /F1 12 Tf 72 700 Td (Daneben) Tj ET\n")
    pdf.save(path)
    return path


def object_text_on_image(path: Path) -> Path:
    """H: Text über einem Bild (Farbverlauf)."""
    from PIL import Image

    image = Image.new("RGB", (300, 60))
    image.putdata([(int(255 * x / 299), 120, 255 - int(255 * x / 299)) for _y in range(60) for x in range(300)])
    pdf = pikepdf.new()
    picture = pdf.make_stream(image.tobytes(), Type=Name.XObject, Subtype=Name.Image, Width=300, Height=60, ColorSpace=Name.DeviceRGB, BitsPerComponent=8)
    _page_with(pdf, b"q 300 0 0 60 72 730 cm /Im1 Do Q\nBT 1 1 1 rg /F1 16 Tf 84 752 Td (Text auf Bild) Tj ET\n", xobjects={"/Im1": picture})
    pdf.save(path)
    return path


def object_scaled_matrix(path: Path) -> Path:
    """Text mit Schriftgröße 1 und skalierender Textmatrix (wie viele PDF-Programme schreiben):
    sichtbar 11 pt, eine Zeile mit drei Wörtern."""
    pdf = pikepdf.new()
    _page_with(pdf, b"BT /F1 1 Tf 11 0 0 11 72 760 Tm 0.05 Tc (Rechnung Nr. 4711) Tj ET\n")
    pdf.save(path)
    return path


def object_repeated(path: Path) -> Path:
    """L: mehrere gleiche Wörter nebeneinander."""
    pdf = pikepdf.new()
    _page_with(pdf, b"BT /F1 12 Tf 72 760 Td (Test Test Test) Tj ET\n")
    pdf.save(path)
    return path


def object_rotated(path: Path) -> Path:
    """I/40/41: die Adresse (wie B) auf Seiten mit /Rotate 90, 180, 270, mit CropBox ≠ MediaBox und mit
    CropBox und /Rotate 90 zusammen."""
    source = object_address(path.with_name(path.stem + "-quelle.pdf"))
    src = pikepdf.open(source)
    pdf = pikepdf.new()
    for angle, crop in ((90, None), (180, None), (270, None), (0, [40, 650, 400, 800]), (90, [40, 650, 400, 800])):
        pdf.pages.append(src.pages[0])
        page = pdf.pages[-1]
        page.Rotate = angle  # immer setzen: eine kopierte Seite übernimmt sonst die Werte der vorigen Kopie
        if crop:
            page.CropBox = Array(crop)
        elif "/CropBox" in page.obj:
            del page.obj["/CropBox"]
    pdf.save(path)
    src.close()
    source.unlink()
    return path


def mixed_objects(path: Path, rotate: int = 0) -> Path:
    """Text, ein Bild und Vektorobjekte (Rahmen, Kreisfläche, Linie, Hintergrund) auf einer Seite."""
    from PIL import Image

    photo = Image.new("RGB", (40, 20), (30, 160, 60))
    pdf = pikepdf.new()
    image = pdf.make_stream(photo.tobytes(), Type=Name.XObject, Subtype=Name.Image, Width=40, Height=20, ColorSpace=Name.DeviceRGB, BitsPerComponent=8)
    content = (
        b"0.96 0.96 0.96 rg 0 0 595 842 re f\n"  # Hintergrund (kein Objekt)
        b"BT /F1 14 Tf 72 760 Td (Hottgenroth Software AG) Tj ET\n"
        b"BT /F1 11 Tf 72 700 Td (Rechnung Nr. 4711) Tj ET\n"
        b"q 0.9 0.1 0.1 RG 2 w 300 600 120 60 re S Q\n"  # Rahmen
        b"q 0.1 0.3 0.9 rg 470 580 m 470 602 487 620 510 620 c 532 620 550 602 550 580 c 550 557 532 540 510 540 c 487 540 470 557 470 580 c f Q\n"  # Kreisfläche
        b"0 0 0 RG 1.5 w 72 520 m 520 520 l S\n"  # Linie (ohne Klammer)
        b"q 120 0 0 60 72 560 cm /Im1 Do Q\n"
    )
    page = _page_with(pdf, content, xobjects={"/Im1": image})
    if rotate:
        page.Rotate = rotate
    pdf.save(path)
    return path


# --- Texterkennung (OCR): gescannte Seiten ---------------------------------------------------------------------
SCAN_DPI = 300
SCAN_LINES = (
    "Hottgenroth Software AG",
    "Rechnung Nr. 4711",
    "Müller Straße 12, 50829 Köln",
    "Vielen Dank für die gute Zusammenarbeit und den Auftrag.",
)
SCAN_LEFT, SCAN_TOP, SCAN_SIZE, SCAN_LEADING = 72.0, 90.0, 13.0, 26.0  # Anzeige-Punkte (Ursprung oben links)
SCAN_MARGIN_WORD = "Randvermerk"  # steht beim Zuschnitt (CropBox) nur außerhalb des sichtbaren Bereichs


def _scan_font():
    from PIL import ImageFont

    return ImageFont.truetype(str(vera_path()), round(SCAN_SIZE * SCAN_DPI / 72))


def scan_word_box(word: str, line: int = 0) -> tuple[float, float, float, float]:
    """Wo ``word`` in Zeile ``line`` des erzeugten Scans zu sehen ist: Anzeige-Punkte (x0, y0, x1, y1)."""
    font = _scan_font()
    text = SCAN_LINES[line]
    start = text.index(word)
    scale = SCAN_DPI / 72
    x = SCAN_LEFT * scale + font.getlength(text[:start])
    y = (SCAN_TOP + line * SCAN_LEADING) * scale
    left, top, right, bottom = font.getbbox(word)
    return ((x + left) / scale, (y + top) / scale, (x + right) / scale, (y + bottom) / scale)


def scan_image(width: float, height: float, lines: tuple[str, ...] = SCAN_LINES):
    """»Gescannte« Seite (Graustufen, 300 dpi) im Format ``width`` × ``height`` Punkte: Text in Bitstream Vera
    auf leicht grauem Papier – nur Pixel, kein PDF-Text."""
    from PIL import Image, ImageDraw

    scale = SCAN_DPI / 72
    image = Image.new("L", (round(width * scale), round(height * scale)), 246)
    draw = ImageDraw.Draw(image)
    font = _scan_font()
    for number, line in enumerate(lines):
        draw.text((SCAN_LEFT * scale, (SCAN_TOP + number * SCAN_LEADING) * scale), line, fill=24, font=font)
    return image


def _gray_image(pdf: pikepdf.Pdf, image) -> pikepdf.Stream:
    import zlib

    stream = pdf.make_stream(b"")
    stream.write(zlib.compress(image.tobytes(), 6), filter=Name.FlateDecode, type_check=False)
    stream.Type = Name.XObject
    stream.Subtype = Name.Image
    stream.Width, stream.Height = image.size
    stream.ColorSpace = Name.DeviceGray
    stream.BitsPerComponent = 8
    return stream


def _scan_page(pdf: pikepdf.Pdf, media: tuple[float, float], rotate: int = 0, crop: list[float] | None = None) -> pikepdf.Object:
    """Seite, die nur aus einem Scan besteht: Das Bild füllt den sichtbaren Bereich so, dass die Anzeige
    (``/Rotate``, CropBox) es aufrecht zeigt. Mit CropBox liegt darunter ein seitengroßes Bild mit einem
    Randvermerk, den der Zuschnitt verdeckt."""
    from PIL import ImageDraw

    from tools.pdf_editor.geometry import PageGeometry

    page = pdf.add_blank_page(page_size=media)
    geo = PageGeometry(tuple(float(v) for v in (crop or (0, 0, media[0], media[1]))), rotate)
    origin, right, top = geo.to_page(0, geo.height), geo.to_page(geo.width, geo.height), geo.to_page(0, 0)
    matrix = (right[0] - origin[0], right[1] - origin[1], top[0] - origin[0], top[1] - origin[1], origin[0], origin[1])
    xobjects = {"/Im1": _gray_image(pdf, scan_image(geo.width, geo.height))}
    content = b""
    if crop:
        margin = scan_image(media[0], media[1], lines=())
        ImageDraw.Draw(margin).text((12 * SCAN_DPI / 72, 12 * SCAN_DPI / 72), SCAN_MARGIN_WORD, fill=24, font=_scan_font())
        xobjects["/Im0"] = _gray_image(pdf, margin)
        content += f"q {media[0]} 0 0 {media[1]} 0 0 cm /Im0 Do Q\n".encode("ascii")
        page.CropBox = Array(crop)
    content += ("q " + " ".join(f"{value:.4f}" for value in matrix) + " cm /Im1 Do Q\n").encode("ascii")
    page.Resources = Dictionary(XObject=Dictionary(xobjects))
    page.Contents = pdf.make_stream(content)
    if rotate:
        page.Rotate = rotate
    return page


def scanned(path: Path, *, rotate: int = 0, crop: list[float] | None = None, text_page: bool = False) -> Path:
    """Gescanntes PDF ohne Text (A4, 300 dpi). ``rotate``: Seite mit ``/Rotate`` – der Scan liegt im
    Seitenraum gedreht, die Anzeige zeigt ihn aufrecht; ``crop``: CropBox mit Versatz; ``text_page``:
    gemischtes Dokument – zuerst eine Seite mit echtem PDF-Text, dann die Scanseite."""
    pdf = pikepdf.new()
    if text_page:
        _page_with(pdf, b"BT /F1 14 Tf 72 760 Td (Angebot Nr. 815 fuer Muster GmbH) Tj ET\nBT /F1 11 Tf 72 730 Td (Bitte pruefen Sie die beigefuegten Unterlagen.) Tj ET\n")
    _scan_page(pdf, (A4[1], A4[0]) if rotate in (90, 270) else A4, rotate, crop)
    pdf.save(path)
    return path


def text_only_pdf(width: float, height: float, words: list[tuple[str, float, float, float]], mode: int = 3) -> bytes:
    """Text-only-PDF einer Seite wie von Tesseract (``textonly_pdf``): unsichtbarer Text (``3 Tr``) auf einer
    Seite ``width`` × ``height`` Punkte. ``words``: (Text, x, Grundlinie y, Größe), Ursprung unten links – so
    lassen sich Textebenen auch ohne Tesseract prüfen. ``mode=0``: sichtbar (für die Prüfung der Darstellung)."""
    pdf = pikepdf.new()
    parts = [f"BT {mode} Tr /F1 {size} Tf 1 0 0 1 {x:.2f} {y:.2f} Tm ({text}) Tj ET" for text, x, y, size in words]
    _page_with(pdf, ("\n".join(parts) + "\n").encode("cp1252"))
    pdf.pages[0].MediaBox = Array([0, 0, width, height])
    buffer = io.BytesIO()
    pdf.save(buffer)
    return buffer.getvalue()
