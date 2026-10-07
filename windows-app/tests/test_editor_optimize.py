"""PDF verkleinern: kleinere, geprüfte Kopie – das geöffnete Dokument und die Datei bleiben gleich.

Ein großes Foto (auf der Seite viel kleiner gezeigt) wird auf die Zielauflösung verkleinert, auch in
einem Formular-XObject; ein Schwarzweißbild (1 Bit) bleibt unverändert. Die Kopie hat dieselben
Seiten und Strukturen, die Verschlüsselung bleibt.
"""

from __future__ import annotations

import io
import random
import sys
from pathlib import Path

import pikepdf
import pytest
from pikepdf import Array, Dictionary, Name

from tools.pdf_editor import commands, optimize, pages, save
from tools.pdf_editor.document import EditorDocument
from tools.pdf_editor.errors import EditorError


@pytest.fixture(autouse=True)
def no_lxml(monkeypatch):
    monkeypatch.setitem(sys.modules, "lxml", None)
    monkeypatch.setitem(sys.modules, "lxml.etree", None)


def photo_bytes(size=(1800, 1350)) -> bytes:
    """Foto-ähnliches JPEG (Verlauf mit Rauschen – lässt sich nicht beliebig klein komprimieren)."""
    from PIL import Image

    rng = random.Random(7)
    width, height = size
    image = Image.new("RGB", size)
    pixels = image.load()
    for y in range(0, height):
        for x in range(0, width, 3):
            value = (x * 255 // width, y * 255 // height, (x + y) * 127 // (width + height) + rng.randint(0, 60))
            for dx in range(3):
                if x + dx < width:
                    pixels[x + dx, y] = value
    buffer = io.BytesIO()
    image.save(buffer, "JPEG", quality=95)
    return buffer.getvalue()


def heavy(path: Path) -> Path:
    """Seite 1: großes Foto direkt (300 × 225 pt), Seite 2: dasselbe Foto in einem Formular-XObject,
    dazu ein Schwarzweißbild (1 Bit)."""
    pdf = pikepdf.new()
    jpeg = photo_bytes()
    photo = pdf.make_stream(jpeg, Type=Name.XObject, Subtype=Name.Image, Width=1800, Height=1350, ColorSpace=Name.DeviceRGB, BitsPerComponent=8, Filter=Name.DCTDecode)
    other = pdf.make_stream(photo_bytes((1600, 1200)), Type=Name.XObject, Subtype=Name.Image, Width=1600, Height=1200, ColorSpace=Name.DeviceRGB, BitsPerComponent=8, Filter=Name.DCTDecode)
    bits = pdf.make_stream(bytes([0b10101010]) * (800 // 8 * 600), Type=Name.XObject, Subtype=Name.Image, Width=800, Height=600, ColorSpace=Name.DeviceGray, BitsPerComponent=1)
    first = pdf.add_blank_page(page_size=(595, 842))
    first.Resources = Dictionary(XObject=Dictionary(Im1=photo, Im2=bits))
    first.Contents = pdf.make_stream(b"q 300 0 0 225 72 500 cm /Im1 Do Q q 200 0 0 150 72 300 cm /Im2 Do Q")
    form = pdf.make_stream(b"q 280 0 0 210 0 0 cm /Im0 Do Q", Type=Name.XObject, Subtype=Name.Form, BBox=Array([0, 0, 280, 210]), Resources=Dictionary(XObject=Dictionary(Im0=other)))
    second = pdf.add_blank_page(page_size=(595, 842))
    second.Resources = Dictionary(XObject=Dictionary(Fm1=form))
    second.Contents = pdf.make_stream(b"q 1 0 0 1 72 500 cm /Fm1 Do Q")
    pdf.save(path)
    return path


def test_copy_is_much_smaller_checked_and_the_open_document_stays(tmp_path: Path) -> None:
    path = heavy(tmp_path / "Fotos.pdf")
    original = path.read_bytes()
    doc = EditorDocument.open(path)
    try:
        result = optimize.optimize_copy(doc, tmp_path / "Fotos_klein.pdf", "mittel")
        assert result.images == 2 and result.skipped == 1  # zwei Fotos verkleinert, das 1-Bit-Bild bleibt
        assert result.after < result.before * 0.4 and result.saved_percent >= 60
        assert not doc.dirty and path.read_bytes() == original
    finally:
        doc.close()
    with pikepdf.open(tmp_path / "Fotos_klein.pdf") as pdf:
        assert len(pdf.pages) == 2
        photo = pdf.pages[0].Resources.XObject.Im1
        assert photo.Filter == Name.DCTDecode and int(photo.Width) == 625  # 300 pt bei 150 dpi
        bits = pdf.pages[0].Resources.XObject.Im2
        assert int(bits.BitsPerComponent) == 1 and int(bits.Width) == 800
        inner = pdf.pages[1].Resources.XObject.Fm1.Resources.XObject.Im0
        assert int(inner.Width) == round(1600 * 150 / (1600 / (280 / 72)))


def test_nothing_to_gain_writes_the_current_state_and_never_over_the_original(tmp_path: Path) -> None:
    import editorsamples as samples

    path = samples.standard_text(tmp_path / "Text.pdf")
    doc = EditorDocument.open(path)
    history = commands.History()
    try:
        pages.rotate(doc, history, [0], 90)
        with pytest.raises(EditorError):
            optimize.optimize_copy(doc, path)
        result = optimize.optimize_copy(doc, tmp_path / "Text_klein.pdf", "klein")
        assert result.images == 0 and result.after <= result.before
        assert doc.dirty  # die Änderung bleibt im Dokument; gespeichert ist nur die Kopie
    finally:
        doc.close()
    with pikepdf.open(tmp_path / "Text_klein.pdf") as pdf:
        assert int(pdf.pages[0].obj.get("/Rotate", 0)) == 90


def test_encrypted_copy_stays_encrypted(tmp_path: Path) -> None:
    path = heavy(tmp_path / "geheim.pdf")
    with pikepdf.open(path, allow_overwriting_input=True) as pdf:
        pdf.save(path, encryption=pikepdf.Encryption(user="geheim", owner="besitzer", R=6))
    doc = EditorDocument.open(path, password="geheim")
    try:
        result = optimize.optimize_copy(doc, tmp_path / "geheim_klein.pdf", "klein")
        assert result.images == 2
    finally:
        doc.close()
    with pytest.raises(pikepdf.PasswordError):
        pikepdf.open(tmp_path / "geheim_klein.pdf")
    with pikepdf.open(tmp_path / "geheim_klein.pdf", password="geheim") as pdf:
        assert pdf.is_encrypted and len(pdf.pages) == 2
    assert save.structure_of(pikepdf.open(tmp_path / "geheim_klein.pdf", password="besitzer")).pages == 2
