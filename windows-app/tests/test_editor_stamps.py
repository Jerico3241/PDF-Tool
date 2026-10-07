"""Stempel und Unterschrift: Erscheinungsbild, aufrecht auf gedrehten Seiten, Größe ändern und
verschieben (nur /Rect), Reduzieren, Speichern; Unterschrift aus Strichen und aus einem Bild
(Hintergrund durchsichtig); gespeicherte Unterschriften nur lokal und begrenzt.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

import pikepdf
import pytest
from PIL import Image, ImageDraw, ImageStat

import editorsamples as samples
from pdfium_lock import PDFIUM_LOCK
from tools.pdf_editor import annotations, commands, flatten, render, save, stamps
from tools.pdf_editor.document import EditorDocument
from tools.pdf_editor.errors import UnsupportedEdit


@pytest.fixture(autouse=True)
def no_lxml(monkeypatch):
    monkeypatch.setitem(sys.modules, "lxml", None)
    monkeypatch.setitem(sys.modules, "lxml.etree", None)


def region(doc: EditorDocument, page: int, view_rect, scale: float = 2.0) -> Image.Image:
    return render.to_pil(render.render_region(doc, page, view_rect, scale)).convert("RGB")


def colored_box(image: Image.Image, color, tolerance: int = 70):
    """Rahmen der Bildpunkte, die ungefähr ``color`` haben."""
    r0, g0, b0 = color
    mask = image.point(lambda v: v)  # Kopie
    pixels = mask.load()
    for y in range(mask.height):
        for x in range(mask.width):
            r, g, b = pixels[x, y]
            pixels[x, y] = (255, 255, 255) if abs(r - r0) + abs(g - g0) + abs(b - b0) < tolerance else (0, 0, 0)
    return mask.convert("L").getbbox()


def page_text(doc: EditorDocument, page: int = 0) -> str:
    with PDFIUM_LOCK:
        return doc.textpage(page).get_text_range()


def test_preset_stamp_has_its_own_appearance_and_can_be_flattened(tmp_path: Path) -> None:
    path = samples.standard_text(tmp_path / "Rechnung.pdf")
    doc = EditorDocument.open(path)
    history = commands.History()
    try:
        stamp = stamps.Stamp.preset("genehmigt", "{datum}")
        width, height = stamps.stamp_size(stamp)
        assert height == 46.0 and width > height * 2
        geo = doc.geometry(0)
        view = (320.0, 120.0, 320.0 + width, 120.0 + height)
        key = stamps.add_stamp(doc, history, 0, geo.rect_to_page(view), stamp)
        info = next(item for item in annotations.list_annotations(doc, 0) if item.key == key)
        today = datetime.now().strftime("%d.%m.%Y")
        assert info.label == "Stempel" and info.contents == f"GENEHMIGT – {today}" and info.ours
        annot = doc.pdf.pages[0].obj.Annots[-1]
        assert annot.Name == pikepdf.Name("/Approved") and [float(v) for v in annot.AP.N.BBox] == [0, 0, round(width, 3), round(height, 3)]
        box = colored_box(region(doc, 0, view), stamps.PRESETS["genehmigt"][1])
        assert box is not None and box[2] - box[0] > 150  # Rahmen und Schrift in Grün
        assert history.undo_title == "Stempel hinzufügen"
        result = flatten.flatten(doc, history, fields=False, comments=True)
        assert result.comments == 1 and "GENEHMIGT" in page_text(doc) and today in page_text(doc)
        save.save(doc, path)
    finally:
        doc.close()
    with pikepdf.open(path) as pdf:
        assert "/Annots" not in pdf.pages[0].obj or not any(a.get("/Subtype") == pikepdf.Name.Stamp for a in pdf.pages[0].Annots)


@pytest.mark.parametrize("page", [1, 2, 3])
def test_stamp_stands_upright_on_rotated_pages(tmp_path: Path, page: int) -> None:
    doc = EditorDocument.open(samples.rotated(tmp_path / "gedreht.pdf"))
    history = commands.History()
    try:
        geo = doc.geometry(page)
        stamp = stamps.Stamp("ERLEDIGT", color=(25, 95, 175))
        width, height = stamps.stamp_size(stamp)
        view = (100.0, 100.0, 100.0 + width, 100.0 + height)
        stamps.add_stamp(doc, history, page, geo.rect_to_page(view), stamp)
        box = colored_box(region(doc, page, view), (25, 95, 175))
        assert box is not None and box[2] - box[0] > 2 * (box[3] - box[1])  # breiter als hoch – in der Anzeige aufrecht
        flatten.flatten(doc, history, fields=False, comments=True)
        with PDFIUM_LOCK:
            textpage = doc.textpage(page)
            text = textpage.get_text_range()
            start = text.index("ERLEDIGT")
            xs = [geo.rect_to_view(_box(textpage.get_charbox(start + i, loose=False)))[0] for i in range(8)]
        assert xs == sorted(xs) and xs[-1] - xs[0] > 20  # Buchstaben laufen in der Anzeige von links nach rechts
    finally:
        doc.close()


def _box(charbox):
    left, bottom, right, top = charbox
    return (min(left, right), min(bottom, top), max(left, right), max(bottom, top))


def test_resize_and_move_only_change_the_rect(tmp_path: Path) -> None:
    doc = EditorDocument.open(samples.standard_text(tmp_path / "a.pdf"))
    history = commands.History()
    try:
        key = stamps.add_stamp(doc, history, 0, (300.0, 500.0, 420.0, 534.0), stamps.Stamp.preset("entwurf"))
        annot = doc.pdf.pages[0].obj.Annots[-1]
        stream = annot.AP.N.read_bytes()
        info = next(item for item in annotations.list_annotations(doc, 0) if item.key == key)
        assert info.subtype == "/Stamp" and "/Stamp" in annotations.RESIZABLE
        annotations.resize(doc, history, key, (300.0, 466.0, 540.0, 534.0))
        annotations.move(doc, history, key, -100.0, 10.0)
        annot = annotations.find(doc, key)[2]
        assert [round(float(v)) for v in annot.Rect] == [200, 476, 440, 544] and annot.AP.N.read_bytes() == stream
        with pytest.raises(UnsupportedEdit):
            annotations.update(doc, history, key, color=(0, 0, 0))
        history.undo(doc)
        history.undo(doc)
        assert [round(float(v)) for v in annotations.find(doc, key)[2].Rect] == [300, 500, 420, 534]
    finally:
        doc.close()


def test_signature_from_strokes_is_smooth_vector_ink_and_keeps_its_aspect(tmp_path: Path) -> None:
    path = samples.standard_text(tmp_path / "Vertrag.pdf")
    doc = EditorDocument.open(path)
    history = commands.History()
    try:
        strokes = [[(10 + i * 3, 40 + (8 if i % 2 else -8)) for i in range(40)], [(20, 70), (130, 66)]]
        signature = stamps.signature_from_strokes(strokes, pen=2.0)
        assert signature.kind == "strokes" and 2.0 < signature.aspect < 6.0
        assert stamps.Signature.from_dict(json.loads(json.dumps(signature.to_dict()))) == signature
        rect = stamps.fit_rect(signature.aspect, 300.0, 600.0, 40.0)
        geo = doc.geometry(0)
        key = stamps.add_signature(doc, history, 0, geo.rect_to_page(tuple(rect)), signature)
        info = next(item for item in annotations.list_annotations(doc, 0) if item.key == key)
        assert info.label == "Unterschrift" and info.contents == "Unterschrift"
        content = doc.pdf.pages[0].obj.Annots[-1].AP.N.read_bytes()
        assert b" c" in content and b"1 J 1 j" in content  # Bézier-Kurven, runde Enden
        box = colored_box(region(doc, 0, tuple(rect)), stamps.INK, tolerance=90)
        assert box is not None
        save.save(doc, path)
    finally:
        doc.close()
    reopened = EditorDocument.open(path)
    try:
        assert [item.label for item in annotations.list_annotations(reopened, 0)] == ["Unterschrift"]
    finally:
        reopened.close()


def test_signature_from_a_scan_gets_a_transparent_background(tmp_path: Path) -> None:
    scan = Image.new("RGB", (900, 400), (246, 244, 238))  # leicht graues Papier
    pen = ImageDraw.Draw(scan)
    pen.line([(120, 250), (260, 120), (330, 300), (480, 140), (620, 260), (760, 180)], fill=(30, 50, 140), width=9)
    scan_path = tmp_path / "unterschrift.jpg"
    scan.save(scan_path, quality=90)
    signature = stamps.signature_from_image(scan_path)
    assert signature.kind == "image" and signature.width < 900 and signature.height < 400
    r, g, b = signature.color
    assert b > r and b > g  # blaue Tinte bleibt blau
    path = samples.standard_text(tmp_path / "Brief.pdf")
    doc = EditorDocument.open(path)
    history = commands.History()
    try:
        geo = doc.geometry(0)
        # über die erste Textzeile legen: der Text darunter bleibt sichtbar (durchsichtiger Hintergrund)
        line = (72.0, geo.height - 760 - 12, 320.0, geo.height - 760 + 4)
        stamps.add_signature(doc, history, 0, geo.rect_to_page(line), signature)
        image = region(doc, 0, line, 3.0)
        dark = image.convert("L").point(lambda v: 255 if v < 60 else 0)
        assert ImageStat.Stat(dark).mean[0] > 2  # schwarzer Text scheint durch
        assert colored_box(image, signature.color, tolerance=120) is not None
        save.save(doc, path)
    finally:
        doc.close()
    with pikepdf.open(path) as pdf:
        xobject = pdf.pages[0].Annots[0].AP.N.Resources.XObject.PTSig
        assert xobject.SMask.Width == xobject.Width and xobject.ColorSpace == pikepdf.Name.DeviceRGB


def test_empty_or_tiny_signatures_and_unreadable_images_are_refused(tmp_path: Path) -> None:
    with pytest.raises(UnsupportedEdit):
        stamps.signature_from_strokes([])
    with pytest.raises(UnsupportedEdit):
        stamps.signature_from_strokes([[(1, 1), (2, 2)]])
    blank = tmp_path / "leer.png"
    Image.new("RGB", (300, 120), "white").save(blank)
    with pytest.raises(UnsupportedEdit):
        stamps.signature_from_image(blank)
    broken = tmp_path / "kaputt.png"
    broken.write_bytes(b"\x89PNG\r\n\x1a\nnichts")
    with pytest.raises(UnsupportedEdit):
        stamps.signature_from_image(broken)
    doc = EditorDocument.open(samples.standard_text(tmp_path / "a.pdf"))
    try:
        with pytest.raises(UnsupportedEdit):
            stamps.add_stamp(doc, commands.History(), 0, (10.0, 10.0, 200.0, 40.0), stamps.Stamp("   "))
    finally:
        doc.close()


def test_signature_store_keeps_at_most_six_and_survives_damage(tmp_path: Path) -> None:
    store = stamps.SignatureStore(tmp_path / "daten" / "unterschriften.json")
    assert store.load() == []
    signature = stamps.signature_from_strokes([[(0, 0), (40, 12), (80, 0)]])
    first = store.add(signature, "Privat")
    for number in range(5):
        store.add(signature)
    with pytest.raises(UnsupportedEdit):
        store.add(signature)
    loaded = store.load()
    assert len(loaded) == 6 and loaded[0].label == "Privat" and loaded[0].signature == signature
    assert store.get(first.ident) is not None and store.remove(first.ident) and not store.remove(first.ident)
    assert not list(store.path.parent.glob(".*.tmp"))
    for item in store.load():
        store.remove(item.ident)
    assert not store.path.exists()  # die letzte gelöscht: keine Datei bleibt zurück
    store.path.write_text("{kaputt", encoding="utf-8")
    assert store.load() == []
