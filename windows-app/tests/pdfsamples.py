"""Programmatisch erzeugte Test-PDFs für das Werkzeug »PDF reparieren«.

Jede Funktion schreibt eine Datei und gibt ihren Pfad zurück. Die beschädigten
Varianten entstehen aus einer gültigen PDF durch gezielte Eingriffe in die Bytes.
"""

from __future__ import annotations

import io
import os
import random
import re
import zlib
from pathlib import Path

import pikepdf
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas


def healthy(path: Path, pages: int = 5, image: bool = False) -> Path:
    """Gültige PDF mit Text, Vektorgrafik, Link und Lesezeichen je Seite."""
    path.parent.mkdir(parents=True, exist_ok=True)
    sheet = canvas.Canvas(str(path), pagesize=A4)
    sheet.setTitle("Testdokument")
    sheet.setAuthor("PDF Tool Tests")
    for index in range(pages):
        sheet.setFont("Helvetica", 14)
        sheet.drawString(72, 760, f"Seite {index + 1} – Testdokument mit Umlauten äöüß")
        sheet.rect(72, 600, 200, 100)
        sheet.linkURL("https://example.org", (72, 600, 272, 700))
        if image:
            from PIL import Image

            picture = Image.new("RGB", (64, 64), (200, 30 + index % 200, 60))
            buffer = io.BytesIO()
            picture.save(buffer, "PNG")
            from reportlab.lib.utils import ImageReader

            sheet.drawImage(ImageReader(io.BytesIO(buffer.getvalue())), 300, 600, 100, 100)
        sheet.bookmarkPage(f"p{index}")
        sheet.addOutlineEntry(f"Kapitel {index + 1}", f"p{index}")
        sheet.showPage()
    sheet.save()
    return path


def xref_offset(path: Path) -> Path:
    """Falscher startxref-Verweis."""
    data = healthy(path.with_name("_quelle_" + path.name)).read_bytes()
    bad = re.sub(rb"startxref\s+(\d+)", lambda m: b"startxref\n" + str(int(m.group(1)) + 137).encode(), data)
    path.write_bytes(bad)
    return path


def xref_garbage(path: Path) -> Path:
    """Einträge der Querverweistabelle überschrieben."""
    data = healthy(path.with_name("_quelle_" + path.name)).read_bytes()
    index = data.rfind(b"xref")
    path.write_bytes(data[: index + 5] + b"garbage garbage garbage\n" + data[index + 5 + 60 :])
    return path


def trailer_removed(path: Path) -> Path:
    data = healthy(path.with_name("_quelle_" + path.name)).read_bytes()
    start = data.rfind(b"trailer")
    end = data.rfind(b"startxref")
    path.write_bytes(data[:start] + data[end:])
    return path


def truncated(path: Path, keep: float = 0.7) -> Path:
    data = healthy(path.with_name("_quelle_" + path.name)).read_bytes()
    path.write_bytes(data[: int(len(data) * keep)])
    return path


def corrupt_stream(path: Path) -> Path:
    """Inhaltsstrom der ersten Seite verfälscht, Struktur intakt."""
    data = healthy(path.with_name("_quelle_" + path.name)).read_bytes()
    match = re.search(rb"/Filter \[ /ASCII85Decode /FlateDecode \] /Length (\d+)\s*>>\s*stream\r?\n", data)
    start, length = match.end(), int(match.group(1))
    chunk = bytearray(data[start : start + length])
    for offset in range(10, min(len(chunk) - 5, 60)):
        chunk[offset] = ord("z")
    path.write_bytes(data[:start] + bytes(chunk) + data[start + length :])
    return path


def garbage(path: Path, size: int = 20000) -> Path:
    """Pseudo-PDF: nur die Kennung, danach Zufallsdaten (nicht reparierbar)."""
    rng = random.Random(4711)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"%PDF-1.4\n" + bytes(rng.getrandbits(8) for _ in range(size)))
    return path


def encrypted(path: Path, password: str = "geheim") -> Path:
    source = healthy(path.with_name("_quelle_" + path.name))
    with pikepdf.open(source) as pdf:
        pdf.save(path, encryption=pikepdf.Encryption(user=password, owner=password + "-besitzer"))
    return path


def with_form(path: Path) -> Path:
    """PDF mit AcroForm-Textfeld und Kontrollkästchen."""
    path.parent.mkdir(parents=True, exist_ok=True)
    sheet = canvas.Canvas(str(path), pagesize=A4)
    sheet.drawString(72, 760, "Formular")
    sheet.acroForm.textfield(name="kunde", tooltip="Kunde", x=72, y=700, width=200, height=20, value="Muster GmbH")
    sheet.acroForm.checkbox(name="aktiv", x=72, y=660, checked=True)
    sheet.showPage()
    sheet.drawString(72, 760, "Seite 2")
    sheet.showPage()
    sheet.save()
    return path


def with_attachment(path: Path) -> Path:
    source = healthy(path.with_name("_quelle_" + path.name), pages=2)
    with pikepdf.open(source) as pdf:
        pdf.attachments["notiz.txt"] = pikepdf.AttachedFileSpec(pdf, b"Anhang-Inhalt", filename="notiz.txt")
        pdf.save(path)
    return path


def signed(path: Path) -> Path:
    """PDF mit einem unterschriebenen Signaturfeld (Struktur wie bei echten Signaturen)."""
    source = healthy(path.with_name("_quelle_" + path.name), pages=1)
    with pikepdf.open(source) as pdf:
        signature = pdf.make_indirect(
            pikepdf.Dictionary(
                Type=pikepdf.Name.Sig,
                Filter=pikepdf.Name("/Adobe.PPKLite"),
                SubFilter=pikepdf.Name("/adbe.pkcs7.detached"),
                ByteRange=pikepdf.Array([0, 100, 200, 300]),
                Contents=pikepdf.String(b"\x00" * 64),
            )
        )
        widget = pdf.make_indirect(
            pikepdf.Dictionary(
                Type=pikepdf.Name.Annot,
                Subtype=pikepdf.Name.Widget,
                FT=pikepdf.Name.Sig,
                T=pikepdf.String("Unterschrift"),
                V=signature,
                Rect=pikepdf.Array([0, 0, 0, 0]),
                F=132,
                P=pdf.pages[0].obj,
            )
        )
        pdf.pages[0].obj.Annots = pdf.make_indirect(pikepdf.Array([widget]))
        pdf.Root.AcroForm = pikepdf.Dictionary(Fields=pikepdf.Array([widget]), SigFlags=3)
        pdf.save(path)
    return path


def large(path: Path, pages: int = 300) -> Path:
    return healthy(path, pages=pages, image=True)


def not_pdf(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"Das ist keine PDF-Datei.\n" * 100)
    return path


def file_bytes(path: Path) -> bytes:
    with open(path, "rb") as handle:
        return handle.read()


def files_in(folder: Path) -> list[str]:
    return sorted(os.listdir(folder)) if folder.is_dir() else []


# --- Klassische PDF 1.4 von Hand (für die erweiterte Wiederherstellung) ---------------------------------------------


def classic_objects(pages: int = 3, inherit: bool = False, parent: int = 2, title: str = "Seite") -> dict[int, bytes]:
    """Objekte einer einfachen klassischen PDF: 1 Katalog, 2 Seitenbaum, 3 Schrift, dann je Seite Seite und Inhalt.

    ``inherit``: Seitengröße und Ressourcen stehen nur im Seitenbaum (die Seiten erben sie).
    ``parent``: Objektnummer, auf die ``/Parent`` der Seiten zeigt.
    """
    objs: dict[int, bytes] = {1: b"<< /Type /Catalog /Pages 2 0 R >>", 3: b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"}
    kids = []
    number = 4
    for index in range(pages):
        text = f"BT /F1 24 Tf 72 700 Td ({title} {index + 1} von {pages}) Tj ET 72 600 200 60 re S".encode()
        objs[number + 1] = b"<< /Length %d >>\nstream\n" % len(text) + text + b"\nendstream"
        page = b"<< /Type /Page /Parent %d 0 R /Contents %d 0 R" % (parent, number + 1)
        if not inherit:
            page += b" /MediaBox [0 0 595 842] /Resources << /Font << /F1 3 0 R >> >>"
        objs[number] = page + b" >>"
        kids.append(number)
        number += 2
    node = b"<< /Type /Pages /Kids [" + b" ".join(b"%d 0 R" % kid for kid in kids) + b"] /Count %d" % pages
    if inherit:
        node += b" /MediaBox [0 0 595 842] /Resources << /Font << /F1 3 0 R >> >>"
    objs[2] = node + b" >>"
    return objs


def classic_bytes(objs: dict[int, bytes], version: str = "1.4", trailer_extra: bytes = b"") -> bytes:
    """Gültige klassische PDF mit xref-Tabelle, Trailer, startxref und %%EOF."""
    out = bytearray(b"%PDF-" + version.encode() + b"\n%\xe2\xe3\xcf\xd3\n")
    offsets = {}
    for number in sorted(objs):
        offsets[number] = len(out)
        out += b"%d 0 obj\n" % number + objs[number] + b"\nendobj\n"
    xref = len(out)
    size = max(objs) + 1
    out += b"xref\n0 %d\n0000000000 65535 f \n" % size
    for number in range(1, size):
        out += (b"%010d 00000 n \n" % offsets[number]) if number in offsets else b"0000000000 00000 f \n"
    out += b"trailer\n<< /Size %d /Root 1 0 R" % size + trailer_extra + b" >>\nstartxref\n%d\n%%%%EOF\n" % xref
    return bytes(out)


def _cut_structure(data: bytes) -> bytes:
    """xref beschädigt, Trailer, startxref und %%EOF fehlen (Objekte bleiben)."""
    index = data.find(b"\nxref")
    return data[:index] + b"\nxref\n0 12\ngarbage 00000 f\n"


def real_case(path: Path, pages: int = 3) -> Path:
    """Der reale Schadensfall: PDF 1.4, Objekte und Datenströme vorhanden, xref beschädigt,
    Trailer fehlt, Seitenbaum defekt, %%EOF fehlt."""
    objs = classic_objects(pages)
    objs[2] = b"<< /Type /Pages /Kids [ 99 0 R ] /Count 1 >>"  # Seitenbaum zeigt ins Leere
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_cut_structure(classic_bytes(objs)))
    return path


def only_eof_missing(path: Path) -> Path:
    data = classic_bytes(classic_objects(2))
    path.write_bytes(data[: data.rfind(b"%%EOF")])
    return path


def xref_missing(path: Path) -> Path:
    """Keine Querverweistabelle mehr, Trailer mit /Root vorhanden."""
    data = classic_bytes(classic_objects(2))
    start, end = data.find(b"\nxref"), data.find(b"trailer")
    path.write_bytes(data[:start] + b"\n" + data[end:])
    return path


def trailer_missing(path: Path) -> Path:
    """Trailer fehlt (Katalog vorhanden), xref und startxref bleiben."""
    data = classic_bytes(classic_objects(2))
    start, end = data.find(b"trailer"), data.find(b"startxref")
    path.write_bytes(data[:start] + data[end:])
    return path


def broken_parents(path: Path) -> Path:
    """Seiten verweisen mit /Parent auf ein fehlendes Objekt, der Seitenbaum ist defekt."""
    objs = classic_objects(3, parent=77)
    objs[2] = b"<< /Type /Pages /Kids [ 98 0 R 99 0 R ] /Count 2 >>"
    path.write_bytes(_cut_structure(classic_bytes(objs)))
    return path


def inherited_resources(path: Path) -> Path:
    """Seiten haben Seitengröße und Schriften nur über den (defekten) Seitenbaum."""
    objs = classic_objects(3, inherit=True)
    objs[2] = objs[2].replace(b"/Kids [", b"/Kids [ 99 0 R ").replace(b"/Count 3", b"/Count 1").replace(b"4 0 R 6 0 R 8 0 R", b"")
    path.write_bytes(_cut_structure(classic_bytes(objs)))
    return path


FAKE_OBJECT = b"\n20 0 obj\n<< /Type /Page /MediaBox [0 0 10 10] >>\nendobj\n1 0 obj\n<< /Type /Catalog >>\nendobj\n"


def binary_false_positive(path: Path, indirect_length: bool = False) -> Path:
    """Ein Datenstrom enthält zufällig Bytes wie »20 0 obj … /Type /Page« und »1 0 obj« – das
    dürfen nie Objekte werden. Der Seitenbaum ist defekt, damit die Rohrekonstruktion greift."""
    objs = classic_objects(3)
    payload = bytes(range(256)) + FAKE_OBJECT + bytes(reversed(range(256)))
    if indirect_length:
        objs[30] = b"<< /Length 31 0 R >>\nstream\n" + payload + b"\nendstream"
        objs[31] = str(len(payload)).encode()
    else:
        objs[30] = b"<< /Length %d >>\nstream\n" % len(payload) + payload + b"\nendstream"
    objs[2] = b"<< /Type /Pages /Kids [ 99 0 R ] /Count 1 >>"
    path.write_bytes(_cut_structure(classic_bytes(objs)))
    return path


def incremental_update(path: Path) -> Path:
    """Inkrementelles Update ersetzt den Inhalt von Seite 1 (»ALT« → »NEU«); danach sind xref,
    Trailer und Seitenbaum beschädigt. Richtig ist die spätere Definition."""
    objs = classic_objects(2, title="ALT")
    base = classic_bytes(objs)
    text = b"BT /F1 24 Tf 72 700 Td (NEU 1 von 2) Tj ET"
    update = b"5 0 obj\n<< /Length %d >>\nstream\n" % len(text) + text + b"\nendstream\nendobj\n"
    data = base + update + b"xref\n5 1\n%010d 00000 n \ntrailer\n<< /Size 8 /Root 1 0 R /Prev 1 >>\nstartxref\n0\n%%%%EOF\n" % len(base)
    # Schaden: Seitenbaum defekt, alle Querverweise und Trailer zerstört
    data = data.replace(b"/Kids [4 0 R 6 0 R] /Count 2", b"/Kids [ 99 0 R ] /Count 1")
    first = data.find(b"\nxref")
    data = data[:first] + b"\nxref garbage\n" + data[data.find(b"%%EOF", first) + 5 :]
    data = data[: data.rfind(b"xref\n5 1")]
    path.write_bytes(data)
    return path


def encrypted_damaged(path: Path) -> Path:
    """Verschlüsselte PDF, deren Trailer (mit /Encrypt) verloren ist."""
    source = healthy(path.with_name("_quelle_" + path.name), pages=2)
    locked = path.with_name("_geschuetzt_" + path.name)
    with pikepdf.open(source) as pdf:
        pdf.save(locked, encryption=pikepdf.Encryption(user="geheim", owner="geheim", R=4, aes=False, metadata=False), object_stream_mode=pikepdf.ObjectStreamMode.disable)
    data = locked.read_bytes()
    index = data.find(b"\nxref")
    path.write_bytes(data[:index] + b"\n")
    return path


def object_streams_damaged(path: Path, pages: int = 3) -> Path:
    """PDF 1.5 mit Objektströmen, deren Querverweis-Datenstrom, startxref und %%EOF fehlen."""
    source = healthy(path.with_name("_quelle_" + path.name), pages=pages)
    packed = path.with_name("_objstm_" + path.name)
    with pikepdf.open(source) as pdf:
        pdf.save(packed, object_stream_mode=pikepdf.ObjectStreamMode.generate)
    data = packed.read_bytes()
    xref = re.search(rb"\d+ 0 obj\s*<<[^>]*?/Type\s*/XRef", data)
    path.write_bytes(data[: xref.start()] if xref else data[: data.rfind(b"startxref")])
    return path


def truncated_generator(path: Path) -> Path:
    """Nachbau eines realen Schadensbilds (ohne dessen Inhalte): Ein Programm schreibt zuerst
    Inhalte, Seiten und Bilder, erst am Ende Schriften, Seitenbaum, Katalog, xref und Trailer.
    Die Datei endet nach der letzten Seite, danach nur Null-Bytes – Katalog, Seitenbaum-Knoten,
    alle Schriften, xref, Trailer, startxref und %%EOF fehlen."""
    import zlib

    pixels = zlib.compress(bytes([200, 30, 60]) * 256)
    image = b"<</Type/XObject/Subtype/Image/Width 16/Height 16/Length %d/ColorSpace/DeviceRGB/BitsPerComponent 8/Filter/FlateDecode>>stream\n" % len(pixels) + pixels + b"\nendstream"
    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    numbers = iter(range(4, 100))
    for index in range(3):
        text = (
            "BT /F1 12 Tf 72 760 Td (Vertrag Seite %d von 3) Tj ET BT /F2 9 Tf 72 740 Td "
            "(§%d Vertragsdauer und Kündigung – außerordentlich) Tj ET q 16 0 0 16 500 780 cm /img1 Do Q" % (index + 1, index + 3)
        ).encode("cp1252")
        stream = zlib.compress(text)
        content, page, picture = next(numbers), next(numbers), next(numbers)
        out += b"%d 0 obj\n<</Length %d/Filter/FlateDecode>>stream\n" % (content, len(stream)) + stream + b"\nendstream\nendobj\n"
        out += (
            b"%d 0 obj\n<</Type/Page/MediaBox[0 0 595 842]/Resources<</ProcSet [/PDF /Text /ImageC]/Font<</F1 2 0 R/F2 3 0 R>>"
            b"/XObject<</img1 %d 0 R>>>>/Contents %d 0 R/Parent 1 0 R>>\nendobj\n" % (page, picture, content)
        )
        out += b"%d 0 obj\n" % picture + image + b"\nendobj\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(bytes(out) + b"\x00" * 13)
    return path


# --- Fremde Daten vor bzw. nach der PDF -----------------------------------------------------------------------------

MAIL_HEADER = (
    b"Return-Path: <rechnung@example.org>\r\n"
    + b"Received: from mail.example.org by mx.example.org; Mon, 5 Oct 2026 10:00:00 +0200\r\n" * 20
    + b'Subject: Rechnung\r\nContent-Type: application/pdf; name="Rechnung.pdf"\r\nContent-Transfer-Encoding: binary\r\n\r\n'
)
HTTP_HEADER = b"HTTP/1.1 200 OK\r\nContent-Type: application/pdf\r\nCache-Control: no-cache\r\nX-Trace: " + b"0123456789abcdef" * 80 + b"\r\n\r\n"
HTML_PAGE = b"<!DOCTYPE html>\n<html><head><title>Download</title></head><body>" + b"<p>Der Download startet gleich.</p>\n" * 40 + b"</body></html>\n"
BOM_AND_GARBAGE = b"\xef\xbb\xbf" + bytes(byte | 0x80 for byte in random.Random(7).randbytes(1500))  # nur Bytes ab 0x80


def with_prefix(path: Path, prefix: bytes, source: Path | None = None) -> Path:
    """Fremde Daten vor der PDF – z. B. ein E-Mail- oder HTTP-Kopf, eine HTML-Seite oder Müll."""
    data = file_bytes(source) if source is not None else healthy(path.with_name("_quelle_" + path.name), pages=3).read_bytes()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(prefix + data)
    return path


def with_suffix(path: Path, suffix: bytes, source: Path | None = None) -> Path:
    """Fremde Daten nach dem letzten %%EOF."""
    data = file_bytes(source) if source is not None else healthy(path.with_name("_quelle_" + path.name), pages=3).read_bytes()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data + suffix)
    return path


def eof_damaged(path: Path) -> Path:
    """Kennung %%EOF beschädigt (»%%E0F«), startxref bleibt."""
    data = classic_bytes(classic_objects(2))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data.replace(b"%%EOF", b"%%E0F"))
    return path


# --- Beschädigte Datenströme ----------------------------------------------------------------------------------------

IMAGE_SIZE = (40, 30)


def content_lines(page: int, count: int = 50) -> bytes:
    """Inhaltsstrom mit ``count`` Textzeilen, jede ein eigener Textblock (BT … ET)."""
    return b"".join(b"BT /F1 12 Tf 72 %d Td (Zeile %d von Seite %d) Tj ET\n" % (780 - 14 * n, n + 1, page) for n in range(count))


def flate_truncated(path: Path, pages: int = 3, damaged: int = 2, keep: float = 0.5) -> Path:
    """Der Flate-Inhaltsstrom von Seite ``damaged`` bricht ab (nur ``keep`` der Daten); /Length passt
    dazu – Querverweise, Trailer und Seitenbaum sind intakt."""
    objs = classic_objects(pages)
    packed = zlib.compress(content_lines(damaged))
    cut = packed[: int(len(packed) * keep)]
    objs[3 + 2 * damaged] = b"<< /Length %d /Filter /FlateDecode >>\nstream\n" % len(cut) + cut + b"\nendstream"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(classic_bytes(objs))
    return path


def a85_truncated(path: Path) -> Path:
    """Inhaltsstrom der ersten Seite (ASCII85 + Flate wie bei reportlab) bricht nach der Hälfte ab;
    Leerzeichen halten /Length und alle Offsets gleich."""
    data = healthy(path.with_name("_quelle_" + path.name)).read_bytes()
    match = re.search(rb"/Filter \[ /ASCII85Decode /FlateDecode \] /Length (\d+)\s*>>\s*stream\r?\n", data)
    start, length = match.end(), int(match.group(1))
    half = length // 2
    path.write_bytes(data[: start + half] + b" " * (length - half) + data[start + length :])
    return path


def form_truncated(path: Path) -> Path:
    """Seite 1 zeichnet ein Formular (Form-XObject), dessen Flate-Inhalt abbricht."""
    objs = classic_objects(2)
    packed = zlib.compress(b"q\n" + content_lines(1) + b"Q\n")
    cut = packed[: len(packed) // 2]
    objs[20] = (
        b"<< /Type /XObject /Subtype /Form /BBox [0 0 595 842] /Resources << /Font << /F1 3 0 R >> >> /Length %d /Filter /FlateDecode >>\nstream\n" % len(cut)
        + cut
        + b"\nendstream"
    )
    text = b"q /Fm1 Do Q"
    objs[5] = b"<< /Length %d >>\nstream\n" % len(text) + text + b"\nendstream"
    objs[4] = objs[4].replace(b"/Font << /F1 3 0 R >>", b"/Font << /F1 3 0 R >> /XObject << /Fm1 20 0 R >>")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(classic_bytes(objs))
    return path


def image_pixels(width: int = IMAGE_SIZE[0], height: int = IMAGE_SIZE[1]) -> bytes:
    """RGB-Verlauf (reproduzierbar, nirgends weiß)."""
    return b"".join(bytes([(x * 6) % 200, (y * 8) % 200, 120]) for y in range(height) for x in range(width))


def image_truncated(path: Path, kind: str = "rgb") -> Path:
    """Eine Seite mit einem Bild (Flate), dessen Daten nach der Hälfte abbrechen. ``kind``: »rgb«
    (ohne Prädiktor), »png« (PNG-Prädiktor) oder »indexed« (Farbpalette – nicht sicher zu retten)."""
    width, height = IMAGE_SIZE
    pixels = image_pixels()
    extra = b"/ColorSpace /DeviceRGB /BitsPerComponent 8"
    if kind == "png":
        data = b"".join(b"\x00" + pixels[row * width * 3 : (row + 1) * width * 3] for row in range(height))
        extra += b" /DecodeParms << /Predictor 15 /Colors 3 /BitsPerComponent 8 /Columns %d >>" % width
    elif kind == "indexed":
        data = bytes((x + y) % 4 for y in range(height) for x in range(width))
        extra = b"/ColorSpace [/Indexed /DeviceRGB 3 <FF000000FF000000FFFFFFFF>] /BitsPerComponent 8"
    else:
        data = pixels
    packed = zlib.compress(data)
    cut = packed[: len(packed) // 2]
    objs = classic_objects(1)
    objs[20] = b"<< /Type /XObject /Subtype /Image /Width %d /Height %d %s /Filter /FlateDecode /Length %d >>\nstream\n" % (width, height, extra, len(cut)) + cut + b"\nendstream"
    text = b"q 200 0 0 150 72 500 cm /Im1 Do Q BT /F1 24 Tf 72 700 Td (Bildseite) Tj ET"
    objs[5] = b"<< /Length %d >>\nstream\n" % len(text) + text + b"\nendstream"
    objs[4] = objs[4].replace(b"/Font << /F1 3 0 R >>", b"/Font << /F1 3 0 R >> /XObject << /Im1 20 0 R >>")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(classic_bytes(objs))
    return path
