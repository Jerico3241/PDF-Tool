"""PDF aus Bildern (4.0): jedes Bild eine Seite, in der gewählten Reihenfolge, als neue geprüfte Datei.

JPEGs werden unverändert übernommen (keine zweite Kompression), die EXIF-Ausrichtung wird beachtet,
Transparenz liegt auf Weiß, mehrseitige TIFFs ergeben mehrere Seiten. Unlesbare Dateien werden
übersprungen und genannt. Ohne lxml – wie in der installierten App.
"""

from __future__ import annotations

import io
import sys
import threading

import pikepdf
import pytest

from tools.pdf_editor import imagepdf
from tools.pdf_editor.errors import EditorError


@pytest.fixture(autouse=True)
def no_lxml(monkeypatch):
    monkeypatch.setitem(sys.modules, "lxml", None)
    monkeypatch.setitem(sys.modules, "lxml.etree", None)


def jpeg(path, size=(400, 300), color=(30, 90, 200), orientation=None, dpi=None):
    from PIL import Image

    image = Image.new("RGB", size, color)
    options = {"quality": 90}
    if orientation:
        exif = Image.Exif()
        exif[0x0112] = orientation
        options["exif"] = exif.tobytes()
    if dpi:
        options["dpi"] = (dpi, dpi)
    image.save(path, "JPEG", **options)
    return path


def png(path, size=(300, 200), alpha=False):
    from PIL import Image

    image = Image.new("RGBA" if alpha else "RGB", size, (200, 0, 0, 0) if alpha else (0, 160, 0))
    image.save(path, "PNG")
    return path


def page_sizes(path):
    with pikepdf.open(path) as pdf:
        return [tuple(round(float(v)) for v in page.mediabox[2:]) for page in pdf.pages]


def first_image(path):
    with pikepdf.open(path) as pdf:
        _name, image = next(iter(pdf.pages[0].Resources.XObject.items()))
        return image.get("/Filter"), int(image.Width), int(image.Height), image.read_raw_bytes()


def test_each_image_becomes_a_page_in_the_given_order(tmp_path):
    a = jpeg(tmp_path / "a.jpg", size=(400, 300))
    b = png(tmp_path / "b.png", size=(200, 500))
    result = imagepdf.create([b, a], tmp_path / "bilder.pdf")
    assert result.pages == 2 and result.skipped == []
    widths = page_sizes(tmp_path / "bilder.pdf")
    assert widths[0][0] < widths[0][1]  # zuerst das hohe PNG
    assert widths[1][0] > widths[1][1]


def test_jpeg_is_taken_over_unchanged(tmp_path):
    source = jpeg(tmp_path / "foto.jpg")
    imagepdf.create([source], tmp_path / "foto.pdf")
    filter_, width, height, raw = first_image(tmp_path / "foto.pdf")
    assert filter_ == "/DCTDecode"
    assert (width, height) == (400, 300)
    assert raw == source.read_bytes()


def test_exif_orientation_is_applied(tmp_path):
    source = jpeg(tmp_path / "hochkant.jpg", size=(400, 300), orientation=6)  # 90° gedreht aufgenommen
    imagepdf.create([source], tmp_path / "hochkant.pdf")
    _filter, width, height, _raw = first_image(tmp_path / "hochkant.pdf")
    assert (width, height) == (300, 400)
    width, height = page_sizes(tmp_path / "hochkant.pdf")[0]
    assert width < height


def test_transparency_lies_on_white(tmp_path):
    imagepdf.create([png(tmp_path / "leer.png", alpha=True)], tmp_path / "leer.pdf")
    with pikepdf.open(tmp_path / "leer.pdf") as pdf:
        _name, image = next(iter(pdf.pages[0].Resources.XObject.items()))
        assert "/SMask" not in image
        pixels = pikepdf.PdfImage(image).as_pil_image()
    assert pixels.getpixel((10, 10)) == (255, 255, 255)


def test_page_size_and_margin(tmp_path):
    imagepdf.create([jpeg(tmp_path / "a.jpg", size=(2000, 1000))], tmp_path / "a4.pdf", page_size="a4", margin="normal")
    assert page_sizes(tmp_path / "a4.pdf") == [(842, 595)]  # Querformat-Bild → A4 quer
    with pikepdf.open(tmp_path / "a4.pdf") as pdf:
        content = pdf.pages[0].Contents.read_bytes().decode()
    assert "28.35" in content or "28.4" in content  # 10 mm Rand


def test_auto_size_follows_image_resolution(tmp_path):
    imagepdf.create([jpeg(tmp_path / "a.jpg", size=(600, 300), dpi=300)], tmp_path / "a.pdf")
    assert page_sizes(tmp_path / "a.pdf") == [(144, 72)]  # 2 × 1 Zoll


def test_multipage_tiff_gives_several_pages(tmp_path):
    from PIL import Image

    frames = [Image.new("RGB", (100, 100), color) for color in ((255, 0, 0), (0, 255, 0), (0, 0, 255))]
    frames[0].save(tmp_path / "scan.tif", save_all=True, append_images=frames[1:])
    assert imagepdf.create([tmp_path / "scan.tif"], tmp_path / "scan.pdf").pages == 3


def test_unreadable_files_are_skipped_and_named(tmp_path):
    (tmp_path / "kaputt.jpg").write_bytes(b"kein Bild")
    result = imagepdf.create([tmp_path / "kaputt.jpg", jpeg(tmp_path / "gut.jpg"), tmp_path / "fehlt.png"], tmp_path / "x.pdf")
    assert result.pages == 1
    assert result.skipped == ["kaputt.jpg", "fehlt.png"]
    with pytest.raises(imagepdf.ImageError):
        imagepdf.create([tmp_path / "kaputt.jpg"], tmp_path / "y.pdf")
    assert not (tmp_path / "y.pdf").exists()


def test_invalid_options_and_cancel(tmp_path):
    image = jpeg(tmp_path / "a.jpg")
    with pytest.raises(EditorError):
        imagepdf.create([], tmp_path / "x.pdf")
    with pytest.raises(EditorError):
        imagepdf.create([image], tmp_path / "x.pdf", page_size="a3")
    stop = threading.Event()
    stop.set()
    with pytest.raises(EditorError):
        imagepdf.create([image], tmp_path / "x.pdf", cancel=stop)
    assert not (tmp_path / "x.pdf").exists()


def test_is_image():
    assert imagepdf.is_image("C:/Fotos/IMG_0001.JPG")
    assert imagepdf.is_image("scan.tiff")
    assert not imagepdf.is_image("brief.pdf")
