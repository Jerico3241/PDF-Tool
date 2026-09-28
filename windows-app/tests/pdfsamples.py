"""Programmatisch erzeugte Test-PDFs für das Werkzeug »PDF reparieren«.

Jede Funktion schreibt eine Datei und gibt ihren Pfad zurück. Die beschädigten
Varianten entstehen aus einer gültigen PDF durch gezielte Eingriffe in die Bytes.
"""

from __future__ import annotations

import io
import os
import random
import re
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
